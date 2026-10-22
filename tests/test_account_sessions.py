import json
import tempfile
import unittest
import time
from pathlib import Path
from unittest.mock import patch
import account_manager as module
from creation_jobs import CreationJobs


class AccountSessionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = patch.multiple(module, ACCOUNTS_FILE=self.root / 'accounts.json',
            RESULTS_DIR=self.root / 'results', OLD_COOKIES_FILE=self.root / 'legacy.json')
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.records = {'acc_a': {'id': 'acc_a', 'real_email': 'a@example.com', 'cookies': {'token': 'A'}},
                        'acc_b': {'id': 'acc_b', 'real_email': 'b@example.com', 'cookies': {'token': 'B'}}}
        (self.root / 'accounts.json').write_text(json.dumps({'accounts': self.records}))

    def test_migration_persists_two_private_database_rows_and_reloads(self):
        original = (self.root / 'accounts.json').read_bytes()
        manager = module.AccountManager()
        self.assertEqual((self.root / 'accounts.json').read_bytes(), original)
        with manager.storage.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM account_sessions').fetchone()[0], 2)
            self.assertNotIn('cookies', json.loads(db.execute('SELECT data FROM accounts WHERE id=?', ('acc_a',)).fetchone()[0]))
        self.assertEqual(manager.storage.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(module.AccountManager().accounts['acc_b']['cookies'], {'token': 'B'})

    def test_cookie_rotation_and_stale_client_cannot_change_other_or_new_session(self):
        manager = module.AccountManager()
        a, b = manager.get_client('acc_a'), manager.get_client('acc_b')
        a.on_cookie_update({'token': 'A2'})
        self.assertEqual(manager.accounts['acc_b']['cookies'], {'token': 'B'})
        self.assertEqual(b.session.cookies.get('token'), 'B')
        manager.update_account('acc_a', cookies={'token': 'A-login-again'})
        a.on_cookie_update({'token': 'stale'})
        reloaded = module.AccountManager()
        self.assertEqual(reloaded.accounts['acc_a']['cookies']['token'], 'A-login-again')
        self.assertEqual(reloaded.accounts['acc_b']['cookies']['token'], 'B')

    def test_legacy_files_do_not_overwrite_database_after_migration(self):
        manager = module.AccountManager()
        manager.update_account('acc_a', cookies={'token': 'new-session'})
        (self.root / 'accounts.json').write_text('{broken')
        reloaded = module.AccountManager()
        self.assertEqual(reloaded.accounts['acc_a']['cookies'], {'token': 'new-session'})
        self.assertEqual(reloaded.accounts['acc_b']['cookies'], {'token': 'B'})

    def test_clients_do_not_share_mutable_cookie_jars(self):
        manager = module.AccountManager()
        a, b = manager.get_client('acc_a'), manager.get_client('acc_b')
        a.cookies['token'] = 'changed'
        a.session.cookies.set('token', 'jar-change')
        self.assertEqual(b.session.cookies.get('token'), 'B')
        self.assertEqual(manager.accounts['acc_a']['cookies']['token'], 'A')

    def test_failed_account_does_not_block_five_creations_for_other_account(self):
        class Manager:
            def create_aliases_for_account(self, acc_id, count, label):
                if acc_id == 'acc_a':
                    return [{'ok': False, 'error': 'Session expired', 'account_id': acc_id}]
                return [{'ok': True, 'line': 'email----link', 'account_id': acc_id}]
        jobs = CreationJobs(Manager())
        key = jobs.start(['acc_a', 'acc_b'], count=5, interval=0)
        deadline = time.monotonic() + 2
        while jobs.get(key)['status'] == 'running' and time.monotonic() < deadline:
            time.sleep(.005)
        result = jobs.get(key)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['total_created'], 5)
        self.assertEqual(result['total_errors'], 1)
        self.assertEqual(len(result['results']['acc_b']), 5)
