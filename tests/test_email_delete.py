import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from storage import Storage
from email_delete import EmailDeleteJobs
from mail_provisioning import MailProvisioner
from inbox_links import is_ready


class DeleteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Storage(Path(self.temp.name)/'db.sqlite3')
        self.email='source@icloud.com'
        self.store.add_email(self.email,'a')
        self.store.update_link(self.email,{'email':self.email,'account_id':'a','configured':True,'inbox_url':'public',
            'destination':'sink@fastaiapi.cloud','rule_id':'own','forward_inbox_url':'private'})
        self.child='source+tag@icloud.com'
        self.store.add_email(self.child,'a')
        self.store.update_link(self.child,{'base_email':self.email,'configured':True,'inbox_url':'public'})
        self.aliases=[{'email':self.email,'anonymousId':'alias-id','active':True}]
        self.rules=[{'ruleId':'own','prefix':'TO','body':self.email,'target':'sink@fastaiapi.cloud','action':'FRWD'},
                    {'ruleId':'foreign','prefix':'TO','body':'other@icloud.com','target':'personal@test.com','action':'FRWD'}]
        self.client=Mock();self.client._service_url='https://hme.icloud.com'
        self.client.list_aliases.side_effect=lambda **kwargs:list(map(dict,self.aliases))
        self.calls=[];self.fail_rules=False;self.lost_response=False
        def request(method,url,**kwargs):
            self.calls.append((url,kwargs))
            if url.endswith('/deactivate'):
                self.aliases[0]['active']=False
            elif url.endswith('/delete'):self.aliases=[]
            elif url.endswith('/batch') and not self.fail_rules:
                identifier=kwargs['json_data']['data'][0]['data']['ruleId']
                self.rules=[r for r in self.rules if r['ruleId']!=identifier]
            if self.lost_response:raise TimeoutError('ambiguous response')
            return {'success':True}
        self.client._request.side_effect=request
        manager=Mock(storage=self.store,accounts={});manager._lock=threading.RLock();manager._workflow_lock.side_effect=lambda _:threading.RLock()
        self.jobs=EmailDeleteJobs(manager);self.jobs.records={self.email:{'email':self.email,'account_id':'a'},
                                                          self.child:{'email':self.child,'account_id':'a'}}
        provisioner=Mock(rules_url='https://mail.icloud.com/rules/')
        provisioner.list_rules.side_effect=lambda:list(map(dict,self.rules))
        provisioner.matching_rule=MailProvisioner.matching_rule
        self.jobs.contexts={'a':(self.client,provisioner)}

    def test_source_alias_and_only_owned_rule_removed_children_retained_as_unready(self):
        result=self.jobs.create_item(self.email,'')
        self.assertTrue(result['ok'])
        self.assertEqual(self.aliases,[])
        self.assertEqual([r['ruleId'] for r in self.rules],['foreign'])
        self.assertEqual([r['email'] for r in self.store.emails()],[self.child])
        self.assertFalse(is_ready(self.store.load_links()[self.child]))
        self.assertTrue(self.store.load_links()[self.child]['parent_deleted'])
        self.assertEqual(self.store.read_document('email_deletion',self.email)['stage'],'completed')
        self.assertTrue(all(options['max_attempts']==1 for _,options in self.calls))

    def test_partial_failure_keeps_record_credentials_and_retry_cleans_remaining_rule(self):
        self.fail_rules=True
        self.assertFalse(self.jobs.create_item(self.email,'')['ok'])
        self.assertEqual(self.aliases,[])
        self.assertIn(self.email,self.store.load_links())
        self.assertEqual(self.store.load_links()[self.email]['forward_inbox_url'],'private')
        self.fail_rules=False
        self.assertTrue(self.jobs.create_item(self.email,'')['ok'])
        self.assertNotIn(self.email,self.store.load_links())

    def test_lost_response_readback_prevents_duplicate_mutation(self):
        self.lost_response=True
        self.assertTrue(self.jobs.create_item(self.email,'')['ok'])
        self.assertEqual(len(self.calls),3)

    def test_foreign_saved_rule_id_aborts_before_alias_mutation(self):
        self.store.update_link(self.email,{'rule_id':'foreign'})
        self.assertFalse(self.jobs.create_item(self.email,'')['ok'])
        self.assertEqual(self.calls,[])
        self.assertTrue(self.aliases)

    def test_split_only_never_deletes_apple_alias_or_source_rule(self):
        self.assertTrue(self.jobs.create_item(self.child,'')['ok'])
        self.assertEqual(self.calls,[])
        self.assertTrue(is_ready(self.store.load_links()[self.email]))
        self.assertEqual(len(self.rules),2)

    def test_expired_cookie_never_removes_local_record(self):
        self.jobs.contexts={'a':RuntimeError('HTTP 421: private response')}
        result=self.jobs.create_item(self.email,'')
        self.assertFalse(result['ok']);self.assertNotIn('private response',result['error'])
        self.assertIn(self.email,self.store.load_links())

    def test_full_cleanup_revokes_children_and_source_mapping_then_deletes_physical_inbox(self):
        self.jobs.cleanup_inboxes=True
        seen=[]
        with patch('public_inbox.revoke_inbox_link',side_effect=lambda row:seen.append(('revoke',row['email']))), \
             patch('mailbox_cleanup.delete_domain_inbox',side_effect=lambda row,store:seen.append(('physical',row['email']))):
            self.assertTrue(self.jobs.create_item(self.child,'')['ok'])
            self.assertTrue(self.jobs.create_item(self.email,'')['ok'])
        self.assertEqual(seen,[('revoke',self.child),('revoke',self.email),('physical',self.email)])
        self.assertFalse(self.store.load_links())

    def test_failed_physical_cleanup_retains_source_for_retry_after_apple_deletion(self):
        self.jobs.cleanup_inboxes=True
        with patch('public_inbox.revoke_inbox_link'), \
             patch('mailbox_cleanup.delete_domain_inbox',side_effect=RuntimeError('temporary')):
            result=self.jobs.create_item(self.email,'')
        self.assertFalse(result['ok'])
        self.assertEqual(self.aliases,[])
        self.assertIn(self.email,self.store.load_links())
        with patch('public_inbox.revoke_inbox_link'), patch('mailbox_cleanup.delete_domain_inbox'):
            self.assertTrue(self.jobs.create_item(self.email,'')['ok'])


    def test_legacy_local_deleted_split_restores_audit_credentials_for_revocation(self):
        record=self.store.load_links()[self.child]
        record.update(public_id='mbx_123456789',public_secret='private-secret',account_id='a')
        self.store.write_document('email_deletion',{'email':self.child,'account_id':'a','link':record},self.child)
        with self.store.connect() as db:
            db.execute('DELETE FROM inbox_links WHERE email=?',(self.child,))
        # 前一次失败留下的状态行不能覆盖审计中仍有用的清理凭据。
        self.store.update_link(self.child,{'deletion_error':'temporary'})
        self.jobs.cleanup_inboxes=True
        with patch('public_inbox.revoke_inbox_link') as revoke:
            self.assertTrue(self.jobs.create_item(self.child,'')['ok'])
        self.assertEqual(revoke.call_args.args[0]['public_secret'],'private-secret')
        self.assertTrue(self.store.read_document('email_deletion',self.child)['remote_cleanup_completed'])

class StrictAppleListTest(unittest.TestCase):
    def test_error_payload_is_never_treated_as_empty_mailbox(self):
        from icloud_hme import ICloudHME
        client=object.__new__(ICloudHME)
        client._resolve_service=Mock();client._log=Mock();client._service_url='https://hme.icloud.com'
        for payload in ({'success':False,'error':{'code':'session'}},{'success':True,'result':{}}):
            client._request=Mock(return_value=payload)
            with self.assertRaises(RuntimeError):client.list_aliases(strict=True)
        client._request=Mock(return_value={'success':True,'result':{'hmeEmails':[]}})
        self.assertEqual(client.list_aliases(strict=True),[])
