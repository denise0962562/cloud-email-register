from tests.auth_helpers import admin_client
import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import requests
from storage import Storage
from fastai_sync import FastAISync
from admin_auth import AuthStore
import web_ui


def accepted(action='inserted'):
    return Mock(status_code=200,json=lambda:{'ok':True,'parsed':1,'inserted':int(action=='inserted'),
                'updated':int(action=='updated'),'skipped':int(action=='skipped')})


class FastAISyncTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        auth = AuthStore(Path(self.folder.name)/'auth.sqlite3')
        auth_patch = patch.dict(web_ui.app.extensions, {'admin_auth': auth})
        auth_patch.start(); self.addCleanup(auth_patch.stop)
        self.db=Storage(Path(self.folder.name)/'sync.sqlite3')
        self.http=Mock();self.http.post.return_value=accepted()
        self.now=1000
        self.sync=FastAISync(self.db,http_factory=lambda:self.http,clock=lambda:self.now)

    def alias(self,email='one@icloud.com',ready=True):
        self.db.add_email(email,'account')
        self.db.update_link(email,{'configured':ready,'inbox_url':'https://webmail.fastaiapi.cloud/m/'+email})

    def wait(self,job):
        deadline=time.monotonic()+3
        while self.sync.active and time.monotonic()<deadline:time.sleep(.005)
        self.assertIsNone(self.sync.active)
        return self.sync.get_job(job['id'])

    def test_selected_bulk_ignores_batch_limit_resends_selected_and_can_cancel(self):
        self.alias('one@icloud.com');self.alias('two@icloud.com');self.alias('other@icloud.com')
        self.sync.configure({'batch_size':1})
        first=self.wait(self.sync.start(emails=['one@icloud.com'],selected_only=True))
        self.assertEqual(first['succeeded'],1)
        entered,release=threading.Event(),threading.Event()
        def blocked(*args,**kwargs):
            entered.set();release.wait(2);return accepted()
        self.http.post.side_effect=blocked
        job=self.sync.start(emails=['one@icloud.com','two@icloud.com'],selected_only=True)
        self.assertEqual(job['total'],2)
        self.assertTrue(entered.wait(1))
        with self.assertRaises(RuntimeError):
            self.sync.start(emails=['other@icloud.com'],selected_only=True)
        self.assertTrue(self.sync.cancel(job['id']))
        release.set()
        finished=self.wait(job)
        self.assertEqual((finished['status'],finished['succeeded'],finished['processed']),('cancelled',1,1))
        self.assertEqual(finished['items'][1]['status'],'pending')
        self.assertFalse(self.sync.cancel(job['id']))
        restored=FastAISync(self.db)
        self.assertEqual(restored.get_job(job['id'])['status'],'cancelled')

    def test_bearer_token_persists_without_exposing_in_status_or_jobs(self):
        self.alias()
        client = admin_client()
        with patch.object(web_ui, '_fastai_sync', self.sync):
            response = client.post('/api/fastai-sync', json={'api_token': 'Bearer test-secret-123'})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json['config']['api_token_configured'])
            self.assertNotIn('test-secret-123', response.get_data(as_text=True))
            self.assertNotIn('api_token', response.json['config'])
            self.sync.configure({'batch_size': 1})
            restored = FastAISync(self.db, http_factory=lambda: self.http)
            self.assertEqual(restored.config['api_token'], 'test-secret-123')
            self.assertNotIn('test-secret-123', client.get('/api/fastai-sync').get_data(as_text=True))
            job = self.wait(self.sync.start())
            self.assertNotIn('test-secret-123', str(job))
            self.assertNotIn('test-secret-123', str(self.sync.snapshot()))
        options = self.http.post.call_args.kwargs
        self.assertEqual(options['headers'], {'Authorization': 'Bearer test-secret-123'})
        self.assertFalse(options['allow_redirects'])

    def test_token_clearing_and_legacy_config_without_token(self):
        self.alias()
        self.sync.configure({'api_token': 'old-token'})
        self.sync.configure({'api_token': ''})
        self.wait(self.sync.start())
        self.assertEqual(self.http.post.call_args.kwargs['headers'], {})
        self.assertFalse(FastAISync(self.db).snapshot()['config']['api_token_configured'])
        self.db.write_document('fastai_sync_state', {'config': {'enabled': False}})
        self.assertEqual(FastAISync(self.db).config['api_token'], '')

    def test_invalid_token_does_not_change_saved_config(self):
        self.sync.configure({'api_token': 'valid-token'})
        before = self.db.read_document('fastai_sync_state')
        for token in (None, 42, 'x' * 8193, 'bad token', 'bad\r\nHeader: injected', '中文'):
            with self.subTest(token_type=type(token).__name__):
                with self.assertRaises(ValueError):
                    self.sync.configure({'api_token': token})
                self.assertEqual(self.db.read_document('fastai_sync_state'), before)

    def test_running_round_keeps_token_and_next_scheduled_round_uses_new_token(self):
        self.alias(); self.alias('two@icloud.com')
        entered, release = threading.Event(), threading.Event()
        def blocked(*args, **kwargs):
            entered.set(); release.wait(2)
            return accepted()
        self.http.post.side_effect = blocked
        self.sync.configure({'api_token': 'round-token'})
        job = self.sync.start()
        self.assertTrue(entered.wait(1))
        try:
            self.sync.configure({'api_token': 'next-token'})
        finally:
            release.set()
        self.assertEqual(self.wait(job)['succeeded'], 2)
        for call in self.http.post.call_args_list:
            self.assertEqual(call.kwargs['headers']['Authorization'], 'Bearer round-token')
        self.alias('three@icloud.com')
        self.sync.configure({'enabled': True, 'interval_minutes': 1})
        self.now += 60
        self.sync.tick()
        self.assertEqual(self.wait({'id': self.sync.latest})['succeeded'], 1)
        self.assertEqual(self.http.post.call_args.kwargs['headers']['Authorization'], 'Bearer next-token')

    def test_redirect_is_not_confirmed_or_marked_synced(self):
        self.alias()
        self.sync.configure({'api_token': 'redirect-token'})
        self.http.post.return_value = Mock(status_code=302)
        job = self.wait(self.sync.start())
        self.assertEqual(job['succeeded'], 0)
        self.assertEqual(self.sync.snapshot()['pending'], 1)
        self.assertFalse(self.http.post.call_args.kwargs['allow_redirects'])

    def test_round_limit_all_override_and_durable_logs_history(self):
        for n in range(5): self.alias(f'box{n}@icloud.com')
        self.sync.configure({'batch_size':2,'enabled':True})
        deadline=self.sync.next_run
        self.sync.configure({'batch_size':1})
        self.assertEqual(self.sync.next_run,deadline)
        first=self.wait(self.sync.start(scheduled=True))
        self.assertEqual((first['total'],first['succeeded']),(1,1))
        second=self.wait(self.sync.start(all_pending=True))
        self.assertEqual((second['total'],second['succeeded']),(4,4))
        restored=FastAISync(self.db,clock=lambda:self.now)
        state=restored.snapshot()
        self.assertEqual(state['config']['batch_size'],1)
        self.assertEqual(len(state['history']),2)
        self.assertNotIn('items',state['history'][0])
        self.assertTrue(any('box4@icloud.com' in log['message'] for log in state['logs']))
        self.assertEqual(state['pending'],0)

    def test_batch_validation_and_new_panel_routes(self):
        for invalid in [0,10001,True,1.5,'5']:
            with self.assertRaises(ValueError): self.sync.configure({'batch_size':invalid})
        client=admin_client()
        for route in ['/fastai-sync','/fastai-sync-panel','/static/fastai_sync_panel.js']:
            with client.get(route) as response:
                self.assertEqual(response.status_code,200)
        with patch.object(web_ui,'_fastai_sync',self.sync):
            self.alias();self.alias('two@icloud.com');self.sync.configure({'batch_size':1})
            result=client.post('/api/fastai-sync/run',json={'all':True})
            self.assertEqual(result.status_code,202)
            self.assertEqual(self.wait(result.json['job'])['total'],2)
            self.assertEqual(client.post('/api/fastai-sync/run',json={'all':'yes'}).status_code,400)

    def test_include_synced_switch_defaults_off_and_persists(self):
        self.alias();self.wait(self.sync.start())
        self.assertFalse(self.sync.config['include_synced'])
        self.assertEqual(self.wait(self.sync.start())['total'],0)
        self.sync.configure({'include_synced':True})
        self.assertEqual(self.sync.snapshot()['eligible'],1)
        self.assertEqual(self.sync.snapshot()['pending'],0)
        self.assertTrue(FastAISync(self.db).config['include_synced'])
        self.assertEqual(self.wait(self.sync.start())['succeeded'],1)
        self.assertEqual(self.wait(self.sync.start(all_pending=True))['total'],0)
        self.sync.configure({'include_synced':False})
        self.assertEqual(self.wait(self.sync.start())['total'],0)
        with self.assertRaises(ValueError): self.sync.configure({'include_synced':'false'})

    def test_failed_resend_retains_previous_confirmation(self):
        self.alias();first=self.wait(self.sync.start())
        previous=self.sync.records()['one@icloud.com']
        self.sync.configure({'include_synced':True})
        self.http.post.side_effect=requests.Timeout()
        self.now+=5
        job=self.wait(self.sync.start())
        self.assertEqual(job['failed'],1)
        self.assertEqual(self.sync.records()['one@icloud.com'],previous)
        self.assertEqual(self.sync.snapshot()['pending'],0)

    def test_only_ready_unsynced_rows_imported_and_duplicates_confirmed(self):
        self.alias();self.alias();self.alias('pending@icloud.com',False)
        self.http.post.return_value=accepted('skipped')
        job=self.wait(self.sync.start())
        self.assertEqual((job['total'],job['succeeded'],job['failed']),(1,1,0))
        self.assertEqual(self.http.post.call_args.kwargs['json'],{
            'kind':'icloud_relay','text':'one@icloud.com----https://webmail.fastaiapi.cloud/m/one@icloud.com'})
        self.assertEqual(self.sync.records()['one@icloud.com']['status'],'synced')
        self.wait(self.sync.start());self.assertEqual(self.http.post.call_count,1)
        restored=FastAISync(self.db)
        self.assertEqual(restored.snapshot()['pending'],0)

    def test_validation_failure_is_not_marked_and_retry_only_imports_failed(self):
        self.alias();self.alias('two@icloud.com')
        self.http.post.side_effect=[Mock(status_code=422),accepted(),accepted()]
        job=self.wait(self.sync.start())
        self.assertEqual((job['succeeded'],job['failed']),(1,1))
        self.assertEqual(self.sync.records()['one@icloud.com']['status'],'failed')
        again=self.wait(self.sync.start())
        self.assertEqual(again['total'],1);self.assertEqual(again['succeeded'],1)
        self.assertEqual(self.http.post.call_count,3)

    def test_timeout_stops_and_never_marks_unconfirmed_results(self):
        self.alias();self.alias('two@icloud.com')
        self.http.post.side_effect=requests.Timeout()
        job=self.wait(self.sync.start())
        self.assertEqual(job['status'],'failed');self.assertEqual(job['processed'],1)
        self.assertEqual(self.sync.snapshot()['pending'],2)
        self.assertEqual(self.sync.records()['one@icloud.com']['status'],'failed')

    def test_bad_success_payload_not_treated_as_confirmation(self):
        self.alias();self.http.post.return_value=Mock(status_code=200,json=lambda:{'ok':True})
        job=self.wait(self.sync.start());self.assertEqual(job['succeeded'],0)
        self.assertEqual(job['failed'],1)

    def test_url_change_or_destination_change_requires_sync_again(self):
        self.alias();self.wait(self.sync.start())
        self.db.update_link('one@icloud.com',{'inbox_url':'https://webmail.fastaiapi.cloud/m/new'})
        self.assertEqual(self.sync.snapshot()['pending'],1)
        self.wait(self.sync.start());self.assertEqual(self.sync.snapshot()['pending'],0)
        self.sync.configure({'api_url':'http://localhost:9999/'})
        self.assertEqual(self.sync.config['api_url'],'http://localhost:9999/api/import')
        self.assertEqual(self.sync.snapshot()['pending'],1)
        self.wait(self.sync.start());self.assertEqual(self.http.post.call_count,3)
        self.assertEqual(self.sync.snapshot()['pending'],0)

    def test_concurrent_start_and_progress_queries_do_not_repeat_import(self):
        self.alias();entered=threading.Event();release=threading.Event()
        def blocked(*args,**kwargs):entered.set();release.wait(2);return accepted()
        self.http.post.side_effect=blocked
        first=self.sync.start();self.assertTrue(entered.wait(1))
        second=self.sync.start();self.assertEqual(first['id'],second['id'])
        for _ in range(4):self.assertEqual(self.sync.snapshot()['job']['status'],'running')
        release.set();self.wait(first);self.assertEqual(self.http.post.call_count,1)

    def test_config_saved_in_database_and_interval_takes_effect_without_reset(self):
        self.sync.configure({'enabled':True,'interval_minutes':2,'api_url':'https://example.com/api/import'})
        self.assertEqual(self.sync.next_run,1120)
        self.sync.configure({'interval_minutes':5});self.assertEqual(self.sync.next_run,1120)
        restored=FastAISync(self.db,clock=lambda:self.now)
        self.assertEqual(restored.config,self.sync.config);self.assertEqual(restored.next_run,1120)
        self.now=1120;self.sync.tick() # Empty scheduled jobs still wait another full interval.
        self.assertEqual(self.sync.next_run,1420)
        self.sync.configure({'enabled':False});self.assertIsNone(self.sync.next_run)

    def test_automatic_job_uses_configured_endpoint_and_records_success(self):
        self.alias();self.sync.configure({'enabled':True,'interval_minutes':1,'api_url':'http://localhost:9000'})
        self.now=1060;self.sync.tick();job=self.wait({'id':self.sync.latest})
        self.assertEqual(job['trigger'],'scheduled');self.assertEqual(job['succeeded'],1)
        self.assertEqual(self.http.post.call_args.args[0],'http://localhost:9000/api/import')
        self.assertEqual(self.sync.next_run,1120)

    def test_restart_preserves_success_and_recovers_incomplete_job(self):
        self.alias();job={'id':'old','status':'running','items':[{'email':'one@icloud.com','status':'running'}]}
        self.db.write_document('fastai_sync_job',job,'old')
        self.db.write_document('fastai_sync_state',{'active':'old','latest':'old','config':self.sync.config})
        restored=FastAISync(self.db)
        self.assertEqual(restored.get_job('old')['status'],'interrupted')
        self.assertEqual(restored.snapshot()['pending'],1)

    def test_invalid_config_does_not_modify_database(self):
        before=self.db.read_document('fastai_sync_state')
        for config in ({'interval_minutes':0},{'interval_minutes':True},{'enabled':1},
                       {'api_url':'file:///tmp/test'},{'api_url':'http://u:p@host'}, {'unknown':True}):
            with self.assertRaises(ValueError):self.sync.configure(config)
            self.assertEqual(self.db.read_document('fastai_sync_state'),before)

    def test_restart_recovers_confirmation_committed_before_job_progress(self):
        self.alias()
        job={'id':'crash','api_url':self.sync.config['api_url'],'status':'running',
             'items':[{'email':'one@icloud.com','status':'running'}]}
        self.sync._set_status(self.sync.pending()[0],job,'synced')
        self.db.write_document('fastai_sync_job',job,'crash')
        self.db.write_document('fastai_sync_state',{'active':'crash','latest':'crash','config':self.sync.config})
        restored=FastAISync(self.db)
        self.assertEqual(restored.get_job('crash')['succeeded'],1)
        self.assertEqual(restored.get_job('crash')['processed'],1)
        self.assertEqual(restored.snapshot()['pending'],0)

    def test_api_reports_status_and_persists_settings(self):
        self.alias();client=admin_client()
        with patch.object(web_ui,'_fastai_sync',self.sync):
            self.assertEqual(client.post('/api/fastai-sync',json={'interval_minutes':0}).status_code,400)
            self.assertTrue(client.post('/api/fastai-sync',json={'interval_minutes':3}).json['ok'])
            response=client.post('/api/fastai-sync/run');self.assertEqual(response.status_code,202)
            self.wait(response.json['job'])
            response=client.get('/api/fastai-sync/jobs/'+self.sync.latest)
            self.assertEqual(response.json['job']['succeeded'],1)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertEqual(client.get('/api/fastai-sync/jobs/absent').status_code,404)

    def test_email_column_only_marks_confirmed_import_for_current_target_and_link(self):
        self.alias();client=admin_client()
        with patch.object(web_ui,'_fastai_sync',self.sync), patch.object(web_ui,'email_storage',return_value=self.db), \
                patch.object(web_ui,'load_links',side_effect=self.db.load_links):
            self.assertFalse(client.get('/api/emails').json['emails'][0]['fastai_synced'])
            self.wait(self.sync.start())
            row=client.get('/api/emails').json['emails'][0]
            self.assertTrue(row['fastai_synced']);self.assertEqual(row['fastai_sync_status'],'synced')
            self.sync.configure({'api_url':'http://localhost:9999'})
            self.assertFalse(client.get('/api/emails').json['emails'][0]['fastai_synced'])
