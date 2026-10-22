import json
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from storage import Storage
from migrate_sqlite import migrate
from auto_registration import AutoRegistration, DEFAULTS
from creation_jobs import CreationJobs


class SQLiteStorageTest(unittest.TestCase):
    def fixture(self, root):
        results = root / 'results'
        sessions = results / 'account_sessions'
        sessions.mkdir(parents=True)
        accounts = {key: {'id':key,'real_email':key+'@example.com','status':'active'} for key in ('a','b')}
        (root/'accounts.json').write_text(json.dumps({'accounts':accounts}))
        for key in accounts: (sessions/(key+'.json')).write_text(json.dumps({'cookies':{'token':key}}))
        links = {'first@icloud.com': {'email':'first@icloud.com','account_id':'a','configured':True,
                  'inbox_url':'https://webmail.fastaiapi.cloud/m/private','public_secret':'keep-identical',
                  'forward_inbox_url':'https://webmail.fastaiapi.cloud/?jwt=upstream'}}
        (results/'inbox_links.json').write_text(json.dumps(links))
        (results/'latest_emails.txt').write_text('first@icloud.com\ta\nfirst@icloud.com\ta\nsecond@icloud.com\tb\n')
        state = {'config':{**DEFAULTS,'enabled':True,'account_ids':['a','b'],'count':5,'interval_mode':'fixed','interval_minutes':60},
                 'next_run':123456, 'current':None,
                 'history':[{'job_id':'old-job','status':'completed','lines':['first@icloud.com----url'],
                             'total_created':1,'downloaded':True,'download_count':3,'downloaded_at':99}],
                 'logs':[{'time':80,'level':'success','message':'complete'}]}
        (results/'auto_registration.json').write_text(json.dumps(state))
        return state

    def test_lossless_idempotent_migration_and_account_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=self.fixture(root)
            first=migrate(root);second=migrate(root)
            self.assertEqual(first,second)
            db=Storage(root/'icloud_hme.sqlite3')
            self.assertEqual(db.read_document('auto'),state)
            self.assertEqual(len(db.emails()),3)  # Preserve duplicate legacy records and order.
            accounts=db.load_accounts();old=json.loads(json.dumps(accounts))
            accounts['a']['cookies']={'token':'rotated'}
            db.save_accounts(accounts,old)
            self.assertEqual(db.load_accounts()['b']['cookies'],{'token':'b'})
            stale=json.loads(json.dumps(old));stale['a']['cookies']={'token':'stale'}
            with self.assertRaises(RuntimeError):db.save_accounts(stale,old)
            self.assertEqual(db.load_accounts()['a']['cookies'],{'token':'rotated'})
            self.assertEqual(db.path.stat().st_mode & 0o777,0o600)
            self.assertEqual(db.get_task('old-job')['download_count'],3)

    def test_invalid_legacy_session_rolls_back_entire_account_import(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root)
            (root/'results/account_sessions/b.json').write_text('{broken')
            store=Storage(root/'icloud_hme.sqlite3')
            with self.assertRaises(ValueError):store.import_accounts(root/'accounts.json',root/'results/account_sessions')
            self.assertEqual(store.load_accounts(),{})
            with store.connect() as db:self.assertIsNone(db.execute("SELECT 1 FROM migrations WHERE name='accounts'").fetchone())

    def test_concurrent_link_updates_do_not_drop_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Storage(Path(folder)/'db.sqlite3')
            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(lambda n:store.update_link('one@icloud.com',{str(n):n}),range(24)))
            record=store.load_links()['one@icloud.com']
            for n in range(24):self.assertEqual(record[str(n)],n)

    def test_creation_result_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Storage(Path(folder)/'db.sqlite3')
            manager=Mock();manager.storage=store
            manager.create_aliases_for_account.return_value=[{'ok':True,'line':'one----url','account_id':'a'}]
            jobs=CreationJobs(manager);key=jobs.start(['a'],1)
            import time
            deadline=time.monotonic()+3
            while jobs.active and time.monotonic()<deadline:time.sleep(.005)
            restored=CreationJobs(manager)
            self.assertEqual(restored.get(key)['lines'],['one----url'])
            self.assertEqual(restored.get(key)['status'],'completed')

    def test_old_tasks_remain_exportable_after_display_history_is_trimmed(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'auto.json'
            auto=AutoRegistration(Mock(),Mock(),path,clock=lambda:100)
            task={'job_id':'archived','status':'completed','lines':['one----url'],'total_created':1}
            auto.history=[task];auto.persist();auto.history=[];auto.persist()
            self.assertEqual(auto.get_task('archived')['lines'],['one----url'])
            self.assertTrue(auto.download_task('archived')['downloaded'])
            restored=AutoRegistration(Mock(),Mock(),path,clock=lambda:200)
            self.assertEqual(restored.get_task('archived')['download_count'],1)
