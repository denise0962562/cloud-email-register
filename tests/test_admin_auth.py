import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import web_ui
from admin_auth import AuthStore
from auth_web import COOKIE


class AdminAuthTest(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.now=1000
        self.store=AuthStore(Path(folder.name)/'auth.sqlite3', clock=lambda:self.now)
        self.store.create_admin('admin','initial-password-123')
        p=patch.dict(web_ui.app.extensions, {'admin_auth':self.store});p.start();self.addCleanup(p.stop)
        self.client=web_ui.app.test_client()

    def login(self, client=None):
        response=(client or self.client).post('/api/auth/login',json={'username':'admin','password':'initial-password-123'})
        self.assertEqual(response.status_code,200)
        return response.json['csrf_token'],response

    def test_all_existing_management_routes_fail_closed(self):
        # Covers new routes as they are added; only public/auth bootstrap are exempt.
        for rule in web_ui.app.url_map.iter_rules():
            if not rule.rule.startswith('/api/') or rule.rule.startswith('/api/public/') or rule.rule=='/api/auth/login':continue
            path=rule.rule.replace('<acc_id>','x').replace('<job_id>','x').replace('<key_id>','x').replace('<msg_id>','x').replace('<alias_email>','x')
            method='GET' if 'GET' in rule.methods else next(m for m in rule.methods if m not in ['HEAD','OPTIONS'])
            self.assertEqual(self.client.open(path,method=method).status_code,401,path)
        self.assertEqual(self.client.get('/').location,'/login')
        self.assertEqual(self.client.get('/static/auto_plus.html').status_code,302)
        self.assertEqual(self.client.get('/healthz').json,{'ok':True})

    def test_month_absolute_expiry_cookie_security_and_logout_revocation(self):
        csrf,response=self.login()
        cookie=response.headers['Set-Cookie']
        for attr in ['HttpOnly','Secure','SameSite=Lax','Max-Age=2592000']:self.assertIn(attr,cookie)
        token=self.client.get_cookie(COOKIE).value
        self.assertNotIn(token,self.store.path.read_bytes().decode('latin1'))
        self.now+=29*86400
        self.assertEqual(self.client.get('/api/auth/session').status_code,200)
        self.assertEqual(self.client.get('/api/auth/session').json['expires_at'],1000+30*86400)
        self.now+=86400
        self.assertEqual(self.client.get('/api/auth/session').status_code,401)
        self.now=1000;csrf,_=self.login();token=self.client.get_cookie(COOKIE).value
        self.assertEqual(self.client.post('/api/auth/logout',headers={'X-CSRF-Token':csrf}).status_code,200)
        self.client.set_cookie(COOKIE,token)
        self.assertEqual(self.client.get('/api/auth/session').status_code,401)

    def test_csrf_enforced_and_frames_receive_session_helper(self):
        csrf,_=self.login()
        self.assertEqual(self.client.post('/api/admin/api-keys',json={'name':'x','scopes':['emails:read']}).status_code,403)
        response=self.client.post('/api/admin/api-keys',json={'name':'x','scopes':['emails:read']},headers={'X-CSRF-Token':csrf})
        self.assertEqual(response.status_code,201)
        for path in ['/','/auto-panel','/plus-panel','/admin/security']:
            with self.client.get(path) as r:self.assertIn(b'/static/admin_session.js',r.data,path)

    def test_keys_are_scoped_revocable_hashed_and_not_admin_sessions(self):
        csrf,_=self.login()
        r=self.client.post('/api/admin/api-keys',json={'name':'integration','scopes':['emails:read']},headers={'X-CSRF-Token':csrf})
        token,key_id=r.json['api_key'],r.json['id']
        self.assertNotIn(token,self.store.path.read_bytes().decode('latin1'))
        self.assertNotIn(token,json.dumps(self.client.get('/api/admin/api-keys').json))
        caller=web_ui.app.test_client();header={'Authorization':'Bearer '+token}
        with patch.object(web_ui,'email_storage') as storage,patch.object(web_ui,'load_links',return_value={}),patch.object(web_ui._fastai_sync,'records',return_value={}):
            storage.return_value.emails.return_value=[]
            self.assertEqual(caller.get('/api/public/emails',headers=header).status_code,200)
        self.assertEqual(caller.get('/api/public/inbox-links/export',headers=header).status_code,403)
        self.assertEqual(caller.get('/api/accounts',headers=header).status_code,401)
        self.assertEqual(caller.post('/api/accounts/add',headers=header).status_code,401)
        self.assertEqual(caller.get('/api/public/emails?api_key='+token).status_code,401)
        self.assertEqual(self.client.get('/api/public/emails').status_code,401)
        self.assertEqual(caller.post('/api/public/emails',headers=header).status_code,404)
        self.client.delete('/api/admin/api-keys/'+key_id,headers={'X-CSRF-Token':csrf})
        self.assertEqual(caller.get('/api/public/emails',headers=header).status_code,401)

    def test_password_change_revokes_every_session_and_old_password_fails(self):
        csrf,_=self.login();other=web_ui.app.test_client();self.login(other)
        r=self.client.post('/api/auth/password',json={'old_password':'initial-password-123','new_password':'changed-password-456'},headers={'X-CSRF-Token':csrf})
        self.assertEqual(r.status_code,200)
        self.assertEqual(other.get('/api/auth/session').status_code,401)
        self.assertEqual(self.client.post('/api/auth/login',json={'username':'admin','password':'initial-password-123'}).status_code,401)
        self.assertEqual(self.client.post('/api/auth/login',json={'username':'admin','password':'changed-password-456'}).status_code,200)

    def test_login_throttle_and_no_cross_origin_login(self):
        self.assertEqual(self.client.post('/api/auth/login',headers={'Origin':'https://evil.example'},json={}).status_code,403)
        for _ in range(8):
            self.assertEqual(self.client.post('/api/auth/login',json={'username':'admin','password':'wrong'}).status_code,401)
        self.assertEqual(self.client.post('/api/auth/login',json={'username':'admin','password':'initial-password-123'}).status_code,429)
        self.now+=901;self.login()

    def test_missing_admin_has_no_remote_bootstrap(self):
        with self.store.connect() as db:db.execute('DELETE FROM admin')
        self.assertEqual(self.client.post('/api/auth/login',json={'username':'admin','password':'initial-password-123'}).status_code,401)
        self.assertEqual(self.client.post('/api/auth/setup',json={}).status_code,401)

    def test_public_export_and_mail_use_key_scopes_and_sessions_cannot_be_keys(self):
        csrf,_=self.login()
        session_token=self.client.get_cookie(COOKIE).value
        caller=web_ui.app.test_client()
        self.assertEqual(caller.get('/api/public/emails',headers={'Authorization':'Bearer '+session_token}).status_code,401)
        _,key=self.store.create_key('reader',['inbox-links:read','mail:read'])
        header={'X-API-Key':key}
        with patch.object(web_ui,'export_lines',return_value=['example@icloud.com----https://example.test/inbox']), \
                patch.object(web_ui,'email_storage') as storage:
            storage.return_value.emails.return_value=[{'email':'example@icloud.com','account_id':'a'}]
            response=caller.get('/api/public/inbox-links/export',headers=header)
            self.assertEqual(response.status_code,200)
            self.assertIn('example@icloud.com----',response.text)
        with patch.object(web_ui._account_mgr,'list_accounts',return_value=[{'id':'a','real_email':'owner@icloud.com'}]), \
                patch.object(web_ui._account_mgr,'check_alias_mail',return_value=[{'subject':'test'}]):
            response=caller.get('/api/public/mail?email=owner@icloud.com&alias=example@icloud.com',headers=header)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['count'],1)
