"""收件配置清理必须验证归属，不得删除分裂地址共享的数据。"""
import unittest
from unittest.mock import Mock
from mailbox_cleanup import delete_domain_inbox
from public_inbox import revoke_inbox_link


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.record={'email':'base@icloud.com','destination':'sink@fastaiapi.cloud',
                     'forward_inbox_url':'https://webmail.fastaiapi.cloud/?jwt=private'}
        self.store=Mock();self.store.load_links.return_value={self.record['email']:self.record}
        self.http=Mock()
        self.http.get.return_value=Mock(status_code=200,json=lambda:{'address':'sink@fastaiapi.cloud'})
        self.http.delete.return_value=Mock(status_code=200,json=lambda:{'success':True})

    def test_physical_delete_requires_exact_owner_and_confirmed_success(self):
        delete_domain_inbox(self.record,self.store,self.http)
        self.assertTrue(self.http.delete.call_args.args[0].endswith('/api/delete_address'))
        self.http.get.return_value=Mock(status_code=200,json=lambda:{'address':'other@fastaiapi.cloud'})
        self.http.delete.reset_mock()
        with self.assertRaises(RuntimeError):delete_domain_inbox(self.record,self.store,self.http)
        self.http.delete.assert_not_called()

    def test_shared_physical_inbox_cannot_be_deleted(self):
        self.store.load_links.return_value={'other@icloud.com':{'destination':'sink@fastaiapi.cloud'}}
        with self.assertRaises(RuntimeError):delete_domain_inbox(self.record,self.store,self.http)
        self.http.delete.assert_not_called()
        with self.assertRaises(ValueError):
            delete_domain_inbox({**self.record,'email':'base+tag@icloud.com'},self.store,self.http)

    def test_revoke_public_link_confirms_alias_and_rejects_foreign_id(self):
        config={'admin_token':'private-admin'}
        record={**self.record,'public_id':'mbx_123456789','public_secret':'s'*43}
        self.http.delete.return_value=Mock(status_code=200,json=lambda:{'ok':True,'alias':record['email']})
        revoke_inbox_link(record,config=config,http=self.http)
        self.assertNotIn('public_secret',self.http.delete.call_args.kwargs['json'])
        with self.assertRaises(RuntimeError):
            revoke_inbox_link({**record,'public_id':'../../other'},config=config,http=self.http)
        self.http.delete.return_value=Mock(status_code=200,json=lambda:{'ok':True,'alias':'other@icloud.com'})
        with self.assertRaises(RuntimeError):revoke_inbox_link(record,config=config,http=self.http)
