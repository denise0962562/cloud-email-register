import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import web_ui
from storage import Storage
from inbox_links import is_ready
from tests.auth_helpers import admin_client
from inbox_clear import clear_inbox


class EmailCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Storage(Path(self.temp.name)/'catalog.sqlite3')
        for p in [patch.object(web_ui,'email_storage',return_value=self.store),
                  patch.object(web_ui,'load_links',side_effect=self.store.load_links),
                  patch.object(web_ui._fastai_sync,'config',{'api_url':'https://sync.test'})]:
            p.start();self.addCleanup(p.stop)
        self.client=admin_client()

    def add(self,email,account='a1',ready=True,destination=None):
        self.store.add_email(email,account)
        self.store.update_link(email,{'email':email,'account_id':account,'configured':ready,
            'inbox_url':'https://webmail.fastaiapi.cloud/m/public',
            'forward_inbox_url':'https://webmail.fastaiapi.cloud/?jwt=VERY_PRIVATE_TOKEN',
            'destination':destination or email.split('@')[0]+'@fastaiapi.cloud'})

    def test_real_sql_paging_keyword_type_account_and_no_credential_leak(self):
        for n in range(125):self.add(f'one_{n}@icloud.com')
        self.add('other@icloud.com','a2');self.add('one_0+tag@icloud.com')
        with patch.object(self.store,'emails',side_effect=AssertionError('must not load all emails')), \
             patch.object(web_ui,'load_links',side_effect=AssertionError('must not load all links')):
            r=self.client.get('/api/emails?page=2&page_size=25&q=one_&account_id=a1&address_type=source')
        self.assertEqual(r.status_code,200)
        self.assertEqual((r.json['total'],r.json['pages'],r.json['page'],len(r.json['emails'])),(125,5,2,25))
        self.assertNotIn('VERY_PRIVATE_TOKEN',r.text)
        self.assertEqual(self.client.get('/api/emails?page=1&q=one%25').json['total'],0)
        for q in ['page=0','page=no','page_size=201','page=1&sort=email;DROP','page=1&address_type=wrong']:
            self.assertEqual(self.client.get('/api/emails?'+q).status_code,400)

    def test_sorting_and_page_clamp_are_server_side(self):
        self.add('new@icloud.com');self.add('old@icloud.com');self.add('missing@icloud.com')
        with self.store.connect() as db:
            db.execute("UPDATE email_records SET created_at=CASE email WHEN 'new@icloud.com' THEN '2026-10-27T00:00:00Z' WHEN 'old@icloud.com' THEN '2025-01-01T00:00:00Z' ELSE '' END")
        for direction,expected in [('asc',['old','new','missing']),('desc',['new','old','missing'])]:
            rows=self.client.get('/api/emails?page=1&direction='+direction).json['emails']
            self.assertEqual([x['email'].split('@')[0] for x in rows],expected)
        r=self.client.get('/api/emails?page=100&page_size=2').json
        self.assertEqual((r['page'],len(r['emails'])),(2,1))

    def test_snapshot_all_selection_excludes_new_rows_and_unchecked_rows_when_deleting(self):
        for email in ['one@icloud.com','one2@icloud.com','other@icloud.com']:self.add(email)
        data=self.client.get('/api/emails?page=1&q=one').json
        self.add('one-new@icloud.com')
        selection={'all_matching':True,'filters':{'q':'one'},'through_seq':data['snapshot_max_seq'],'excluded':['one2@icloud.com']}
        r=self.client.post('/api/emails/bulk',json={'action':'delete','selection':selection})
        self.assertEqual((r.status_code,r.json['deleted']),(200,1))
        self.assertEqual({x['email'] for x in self.store.emails()},{'one2@icloud.com','other@icloud.com','one-new@icloud.com'})
        record=self.store.load_links()['one@icloud.com']
        self.assertIn('VERY_PRIVATE_TOKEN',record['forward_inbox_url'])
        self.assertFalse(is_ready(record))

    def test_selected_split_is_once_per_source_and_rejects_split_addresses(self):
        for email in ['one@icloud.com','two@icloud.com','one+tag@icloud.com']:self.add(email)
        with patch.object(web_ui._plus_creation_jobs,'sources',return_value={'one@icloud.com':{},'two@icloud.com':{}}), \
             patch.object(web_ui._plus_creation_jobs,'start',return_value='split-job') as start:
            r=self.client.post('/api/emails/bulk',json={'action':'split','selection':{'emails':['one@icloud.com','one@icloud.com','two@icloud.com']}})
            self.assertEqual(r.status_code,202);self.assertEqual(r.json['selected'],2)
            self.assertEqual(start.call_args.kwargs['count'],1)
            self.assertEqual(set(start.call_args.args[0]),{'one@icloud.com','two@icloud.com'})
            start.reset_mock()
            r=self.client.post('/api/emails/bulk',json={'action':'split','selection':{'emails':['one+tag@icloud.com']}})
            self.assertEqual(r.status_code,400);start.assert_not_called()

    def test_repair_only_selected_incomplete_addresses(self):
        self.add('ready@icloud.com');self.add('pending@icloud.com',ready=False);self.add('unselected@icloud.com',ready=False)
        with patch.object(web_ui._account_mgr,'get_account',return_value={'id':'a1'}), \
             patch.object(web_ui._creation_jobs,'start',return_value='repair-job') as start:
            r=self.client.post('/api/emails/bulk',json={'action':'repair','selection':{'emails':['ready@icloud.com','pending@icloud.com']}})
            self.assertEqual(r.status_code,202)
            self.assertEqual(start.call_args.kwargs['repair'],{'a1':['pending@icloud.com']})

    def test_clear_skips_split_addresses_and_deduplicates_physical_inboxes(self):
        for email in ['one@icloud.com','two@icloud.com','one+tag@icloud.com']:
            self.add(email,destination='shared@fastaiapi.cloud')
        with patch.object(web_ui._inbox_clear_jobs,'start_inboxes',return_value='clear-job') as start:
            r=self.client.post('/api/emails/bulk',json={'action':'clear','selection':{'emails':[x['email'] for x in self.store.emails()]}})
            self.assertEqual(r.status_code,202)
            records=start.call_args.args[0];self.assertEqual(len(records),1)
            self.assertNotIn('+',records[0]['email'])
            start.reset_mock()
            r=self.client.post('/api/emails/bulk',json={'action':'clear','selection':{'emails':['one+tag@icloud.com']}})
            self.assertEqual(r.json['selected'],0);start.assert_not_called()

    def test_invalid_all_selection_and_empty_ids_cannot_become_select_all(self):
        self.add('one@icloud.com')
        for selection in [{},{'emails':[]},{'emails':'one@icloud.com'},{'all_matching':True},{'all_matching':True,'filters':{},'through_seq':True}]:
            self.assertEqual(self.client.post('/api/emails/bulk',json={'action':'delete','selection':selection}).status_code,400)
        self.assertEqual(len(self.store.emails()),1)


class ClearInboxTests(unittest.TestCase):
    def setUp(self):
        self.record={'email':'one@icloud.com','destination':'sink@fastaiapi.cloud',
                     'forward_inbox_url':'https://webmail.fastaiapi.cloud/?jwt=private'}
        self.http=Mock()

    def response(self,data,status=200):return Mock(status_code=status,json=lambda:data)

    def test_scope_checked_before_single_delete_and_no_apple_session_is_sent(self):
        self.http.request.side_effect=[self.response({'address':'sink@fastaiapi.cloud'}),self.response({'success':True})]
        self.assertTrue(clear_inbox(self.record,self.http))
        self.assertEqual([x.args[:2] for x in self.http.request.call_args_list],[('GET','https://api.fastaiapi.cloud/api/settings'),('DELETE','https://api.fastaiapi.cloud/api/clear_inbox')])
        self.assertFalse(any('Cookie' in x.kwargs['headers'] for x in self.http.request.call_args_list))

    def test_wrong_identity_and_split_address_never_delete(self):
        self.http.request.return_value=self.response({'address':'other@fastaiapi.cloud'})
        with self.assertRaisesRegex(RuntimeError,'归属'):clear_inbox(self.record,self.http)
        self.assertEqual(self.http.request.call_count,1)
        self.http.reset_mock()
        with self.assertRaises(ValueError):clear_inbox({**self.record,'email':'one+tag@icloud.com'},self.http)
        self.http.request.assert_not_called()

    def test_lost_delete_response_is_not_retried_or_reported_as_success(self):
        import requests
        self.http.request.side_effect=[self.response({'address':'sink@fastaiapi.cloud'}),requests.Timeout('private')]
        with self.assertRaisesRegex(RuntimeError,'不会自动重发'):clear_inbox(self.record,self.http)
        self.assertEqual(self.http.request.call_count,2)
