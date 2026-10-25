import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import web_ui
from auto_registration import AutoRegistration
from auto_plus import AutoPlusAddresses
from fastai_sync import FastAISync, DEFAULTS as SYNC_DEFAULTS
from storage import Storage


class DeploymentStartupTest(unittest.TestCase):
    def test_imported_enabled_overdue_schedules_disabled_before_first_tick(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = Storage(root / 'state.sqlite3')
            for kind, defaults in [('auto', AutoRegistration.defaults),
                                   ('auto_plus', AutoPlusAddresses.defaults),
                                   ('fastai_sync_state', SYNC_DEFAULTS)]:
                config = {**copy.deepcopy(defaults), 'enabled': True}
                store.write_document(kind, {'config': config, 'next_run': 1,
                                            'history': [], 'logs': []})
            # No actual targets are necessary: disabling also works after a target
            # was removed. An overdue enabled job must never reach its queue.
            manager = Mock(storage=store)
            manager.list_accounts.return_value = []
            jobs = Mock()
            jobs.active = None
            auto = AutoRegistration(jobs, manager, root / 'state.json')
            split = AutoPlusAddresses(jobs, manager, root / 'state.json')
            sync = FastAISync(store)
            serve = Mock()
            with patch.multiple(web_ui, _auto_registration=auto, _auto_plus=split,
                                _fastai_sync=sync, _account_mgr=manager), \
                    patch.object(auto, 'start', side_effect=auto.tick), \
                    patch.object(split, 'start', side_effect=split.tick), \
                    patch.object(sync, 'start_scheduler', side_effect=sync.tick), \
                    patch.object(sync, 'start') as sync_job, \
                    patch('threading.Thread') as thread, \
                    patch('signal.signal'), \
                    patch.dict(sys.modules, {'waitress': SimpleNamespace(serve=serve)}), \
                    patch.object(sys, 'argv', ['web_ui.py', '--disable-automation', '--no-sync']):
                web_ui.main()
            serve.assert_called_once()
            thread.assert_not_called()
            jobs.start.assert_not_called()
            sync_job.assert_not_called()
            for kind in ('auto', 'auto_plus', 'fastai_sync_state'):
                state = store.read_document(kind)
                self.assertFalse(state['config']['enabled'])
                self.assertIsNone(state['next_run'])

    def test_conflicting_flags_rejected_without_enabling_tasks(self):
        with patch.object(sys, 'argv', ['web_ui.py', '--disable-automation', '--scheduler']), \
                patch.object(web_ui._auto_registration, 'configure') as configure:
            with self.assertRaises(SystemExit) as result:
                web_ui.main()
            self.assertEqual(result.exception.code, 2)
            configure.assert_not_called()
