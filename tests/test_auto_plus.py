from tests.auth_helpers import admin_client
import copy
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from auto_plus import PlusCreationJobs, AutoPlusAddresses
from auto_registration import AutoRegistration
from storage import Storage


class AutoPlusTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'schedule.json'
        self.store = Storage(self.path.with_suffix('.sqlite3'))
        self.records = {'base@icloud.com': {'email': 'base@icloud.com', 'account_id': 'owner',
            'configured': True, 'destination': 'sink@example.com', 'inbox_url': 'https://mail.example/base',
            'forward_inbox_url': 'https://webmail.fastaiapi.cloud/?jwt=private'}}
        self.workflow = threading.RLock()
        self.manager = SimpleNamespace(storage=self.store, accounts={'owner': {'alias_total': 1}},
                                       _workflow_lock=lambda _: self.workflow, get_account=lambda _: {'id': 'owner'})
        self.jobs = PlusCreationJobs(self.manager)
        self.now = 10000
        for p in [patch('auto_plus.load_links', side_effect=lambda: copy.deepcopy(self.records)),
                  patch('auto_plus.update_link', side_effect=self.update),
                  patch('plus_addressing.load_links', side_effect=lambda: copy.deepcopy(self.records)),
                  patch('plus_addressing.update_link', side_effect=self.update),
                  patch('plus_addressing.publish_inbox_link', side_effect=self.publish)]:
            p.start(); self.addCleanup(p.stop)
        self.auto = AutoPlusAddresses(self.jobs, self.manager, self.path, clock=lambda: self.now)

    def update(self, email, values):
        self.records.setdefault(email, {}).update(values)
        return copy.deepcopy(self.records[email])

    def publish(self, record):
        return self.update(record['email'], {'public_registered': True, 'inbox_url': 'https://mail.example/'+record['email']})

    def wait(self, key):
        until = time.monotonic() + 3
        while self.jobs.active and time.monotonic() < until:
            time.sleep(.005)
        return self.jobs.get(key)

    def test_bulk_split_saves_all_addresses_and_links_without_increasing_source_counts(self):
        result = self.wait(self.jobs.start(['base@icloud.com'], 100, 'batch', item_interval=0))
        self.assertEqual(result['total_created'], 100)
        self.assertEqual(len(result['lines']), 100)
        self.assertEqual(len(set(self.records)), 101)
        self.assertEqual(len(self.store.emails()), 100)
        self.assertEqual(self.manager.accounts['owner']['alias_total'], 1)
        self.assertTrue(all(r['kind']=='plus' and not r.get('verified') for e,r in self.records.items() if '+' in e))
        for email in self.records:
            if '+' in email:self.assertRegex(email,r'^base\+[a-z0-9]{4}@icloud\.com$')

    def test_short_suffix_collision_retries_without_overwriting_existing_link(self):
        original={'configured':True,'inbox_url':'https://mail.example/existing','kind':'plus','base_email':'base@icloud.com'}
        self.records['base+aaaa@icloud.com']=copy.deepcopy(original)
        with patch('auto_plus.secrets.choice',side_effect=list('aaaab1c2')):
            result=self.jobs.create_item('base@icloud.com','auto')
        self.assertTrue(result['ok'])
        self.assertEqual(result['email'],'base+b1c2@icloud.com')
        self.assertEqual(self.records['base+aaaa@icloud.com'],original)

    def test_exhausted_collisions_leave_existing_records_untouched(self):
        self.records['base+aaaa@icloud.com']={'configured':True,'inbox_url':'https://mail.example/existing'}
        before=copy.deepcopy(self.records)
        with patch('auto_plus.secrets.choice',return_value='a'):
            result=self.jobs.create_item('base@icloud.com','auto')
        self.assertFalse(result['ok'])
        self.assertEqual(self.records,before)
        self.assertEqual(self.store.emails(),[])

    def test_four_character_suffix_fits_local_part_limit_and_rejects_invalid_dots(self):
        from plus_addressing import plus_address
        self.assertEqual(len(plus_address('a'*59+'@icloud.com','a1b2').split('@')[0]),64)
        for local in ['a'*60,'.abc','abc.','a..b']:
            with self.assertRaises(ValueError):plus_address(local+'@icloud.com','a1b2')
        base='a'*59+'@icloud.com'
        self.records[base]={**self.records['base@icloud.com'],'email':base}
        result=self.wait(self.jobs.start([base],1,'long-label',item_interval=0))
        self.assertEqual(result['total_created'],1)

    def test_failed_publication_is_visible_and_resumes_same_address(self):
        with patch('plus_addressing.publish_inbox_link', side_effect=RuntimeError('HTTP 503 private-token')):
            failed = self.wait(self.jobs.start(['base@icloud.com'], 3, 'resume', item_interval=0))
        self.assertEqual(failed['total_errors'], 1)
        self.assertEqual(len(self.store.emails()), 1)
        pending = self.store.emails()[0]['email']
        self.assertNotIn('private-token', str(failed))
        fixed = self.wait(self.jobs.start(['base@icloud.com'], 1, 'resume', item_interval=0))
        self.assertEqual(fixed['results']['base@icloud.com'][0]['email'], pending)
        self.assertEqual(len(self.store.emails()), 1)

    def test_schedule_runs_after_deadline_and_persists_separately_from_registration(self):
        native = AutoRegistration(Mock(), self.manager, self.path, clock=lambda: self.now)
        native.configure({'account_ids':['owner'], 'count':2})
        self.auto.configure({'base_emails':['base@icloud.com'], 'enabled':True, 'count':10,
                             'interval_mode':'fixed', 'interval_minutes':60, 'item_interval_seconds':0})
        self.assertEqual(self.auto.next_run, self.now+3600)
        self.assertFalse(self.jobs.active)
        self.now += 3600
        self.auto.tick()
        key = self.auto.current['job_id']
        self.wait(key); self.auto.tick()
        self.assertEqual(self.auto.history[0]['total_created'], 10)
        self.assertEqual(self.auto.next_run, self.now+3600)
        restored = AutoPlusAddresses(self.jobs, self.manager, self.path, clock=lambda: self.now)
        self.assertTrue(restored.config['enabled'])
        self.assertEqual(restored.config['base_emails'], ['base@icloud.com'])
        self.assertEqual(restored.get_task(key)['lines'], self.auto.history[0]['lines'])
        self.assertEqual(native.storage.read_document('auto')['config']['count'], 2)

    def test_invalid_configuration_does_not_change_schedule(self):
        self.auto.configure({'base_emails':['base@icloud.com'], 'enabled':True})
        before = self.auto.storage.read_document('auto_plus')
        for data in [{'all_sources':False, 'base_emails':['unknown@icloud.com']}, {'count':201}, {'count':True},
                     {'label':'中文'}, {'label':'x'*11}, {'interval_minutes':0}]:
            with self.assertRaises(ValueError): self.auto.configure(data)
            self.assertEqual(self.auto.storage.read_document('auto_plus'), before)

    def add_source(self, email):
        self.records[email] = {**self.records['base@icloud.com'], 'email': email}

    def test_default_all_sources_ignores_individual_selection_and_includes_more_than_twenty(self):
        for index in range(25):
            self.add_source(f'source{index}@icloud.com')
        self.records['incomplete@icloud.com'] = {'email':'incomplete@icloud.com','account_id':'owner'}
        self.assertTrue(self.auto.snapshot()['config']['all_sources'])
        self.auto.configure({'base_emails':['unknown@icloud.com'], 'count':1, 'item_interval_seconds':0})
        self.assertEqual(len(self.auto.config['base_emails']),26)
        key = self.auto.run_now()
        result = self.wait(key)
        self.assertEqual(result['total_created'],26)
        self.auto.tick()
        self.add_source('newly-ready@icloud.com')
        key = self.auto.run_now()
        self.assertEqual(self.auto.current['target'],27)
        self.assertEqual(self.wait(key)['total_created'],27)

    def test_manual_mode_only_uses_selected_sources(self):
        self.add_source('other@icloud.com')
        self.auto.configure({'all_sources':False,'base_emails':['base@icloud.com'],
                             'count':1,'item_interval_seconds':0})
        result = self.wait(self.auto.run_now())
        self.assertEqual(list(result['results']), ['base@icloud.com'])

    def test_round_robin_order_is_preserved_in_records_events_and_export(self):
        bases = ['base@icloud.com','second@icloud.com','third@icloud.com']
        for base in bases[1:]: self.add_source(base)
        result = self.wait(self.jobs.start(bases,3,'order',item_interval=0))
        expected = bases * 3
        self.assertEqual([row['base_email'] for row in result['events']], expected)
        def source(email): return email.split('+')[0]+'@icloud.com'
        self.assertEqual([source(row['email']) for row in self.store.emails()], expected)
        self.assertEqual([source(line.split('----')[0]) for line in result['lines']], expected)

    def test_failed_source_stops_its_round_and_other_sources_continue_interleaved(self):
        self.add_source('second@icloud.com'); self.add_source('third@icloud.com')
        original = self.jobs.create_item
        calls = []
        def create(base,label):
            calls.append(base)
            return {'ok':False,'error':'test failure'} if base=='base@icloud.com' else original(base,label)
        with patch.object(self.jobs,'create_item',side_effect=create):
            result = self.wait(self.jobs.start(list(self.jobs.sources()),3,'errors',item_interval=0))
        self.assertEqual(calls,['base@icloud.com']+['second@icloud.com','third@icloud.com']*3)
        self.assertEqual((result['total_created'],result['total_errors']),(6,1))

    def test_interleaved_progress_logs_each_result_once_in_creation_order(self):
        with patch.object(self.jobs,'start',return_value='interleaved'):
            self.auto.run_now()
        a1,b1,a2 = [{'ok':True,'email':email} for email in ['a+1@icloud.com','b+1@icloud.com','a+2@icloud.com']]
        job={'status':'running','results':{'a':[a1],'b':[b1]},'events':[a1,b1],
             'lines':[], 'total_created':2, 'total_errors':0}
        with patch.object(self.jobs,'get',side_effect=lambda _:copy.deepcopy(job)):
            self.auto.tick()
            job['results']['a'].append(a2);job['events'].append(a2);job['total_created']=3
            self.auto.tick()
        messages=[row['message'] for row in self.auto.logs if row['level']=='success']
        self.assertEqual([msg.split(' ')[0] for msg in messages],[a1['email'],b1['email'],a2['email']])

    def test_manual_failure_keeps_deadline_and_shutdown_cancels_remaining_items(self):
        self.auto.configure({'base_emails':['base@icloud.com'], 'enabled':True, 'item_interval_seconds':0})
        deadline = self.auto.next_run
        with patch('auto_plus.setup_shared_inbox', side_effect=RuntimeError('HTTP 503')):
            key = self.auto.run_now(); self.wait(key); self.auto.tick()
        self.assertEqual(self.auto.next_run, deadline)
        entered, release = threading.Event(), threading.Event()
        original = self.publish
        def publish(record):
            entered.set(); release.wait(3); return original(record)
        with patch('plus_addressing.publish_inbox_link', side_effect=publish):
            key = self.auto.run_now()
            self.assertTrue(entered.wait(3))
            self.auto.configure({'enabled':False}); release.set(); self.wait(key); self.auto.tick()
        self.assertEqual(self.auto.history[0]['status'], 'cancelled')
        self.assertEqual(self.auto.history[0]['total_created'], 1)
        self.assertIsNone(self.auto.next_run)

    def test_type_projection_and_export_match_list_filter(self):
        import web_ui
        self.store.add_email('base@icloud.com','owner')
        self.wait(self.jobs.start(['base@icloud.com'],1,'typed',item_interval=0))
        with patch.object(web_ui,'email_storage',return_value=self.store), \
                patch.object(web_ui,'load_links',side_effect=lambda:copy.deepcopy(self.records)), \
                patch.object(web_ui,'export_lines',side_effect=lambda emails:list(emails)):
            client = admin_client()
            rows = client.get('/api/emails').json['emails']
            self.assertEqual({r['address_type_label'] for r in rows},{'源地址','分裂地址'})
            split = next(r for r in rows if r['address_type']=='split')
            self.assertEqual(split['source_email'],'base@icloud.com')
            self.assertEqual(client.get('/api/inbox-links/export?address_type=split').text,split['email']+'\n')
            self.assertEqual(client.get('/api/inbox-links/export?address_type=source').text,'base@icloud.com\n')

    def test_removed_source_does_not_prevent_disabling_schedule(self):
        self.auto.configure({'base_emails':['base@icloud.com'], 'enabled':True})
        self.records.clear()
        self.assertFalse(self.auto.configure({'enabled':False})['config']['enabled'])
        self.assertIsNone(self.auto.next_run)


if __name__ == '__main__':
    unittest.main()
