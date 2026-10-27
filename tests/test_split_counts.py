"""验证源地址分裂次数的持久化、去重、历史回填及分页返回。"""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from storage import Storage
import email_catalog
from plus_addressing import setup_shared_inbox


class SplitCountsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Storage(Path(self.folder.name) / 'db.sqlite3')
        self.base = 'base@icloud.com'
        self.target = 'base+tag@icloud.com'
        self.source = {'email': self.base, 'account_id': 'owner', 'configured': True,
                       'inbox_url': 'https://mail.test/base', 'destination': 'sink@test.com',
                       'forward_inbox_url': 'private'}
        self.store.update_link(self.base, self.source)

    def record(self, **extra):
        return {'kind': 'plus', 'base_email': self.base, 'configured': True,
                'inbox_url': 'https://mail.test/plus', **extra}

    def test_failed_split_not_counted_success_and_repair_only_count_once(self):
        self.store.update_link(self.target, self.record(configured=False))
        self.assertEqual(self.store.split_counts(), {})
        self.store.update_link(self.target, {'configured': True})
        self.store.update_link(self.target, {'configured': True, 'verified': True})
        self.assertEqual(self.store.split_counts(), {self.base: 1})
        self.store.update_link('base+two@icloud.com', self.record())
        self.assertEqual(self.store.split_counts()[self.base], 2)

    def test_count_persists_after_child_deleted_and_database_reopened(self):
        self.store.update_link(self.target, self.record())
        with self.store.connect() as db:
            db.execute('DELETE FROM inbox_links WHERE email=?', (self.target,))
        restored = Storage(self.store.path)
        self.assertEqual(restored.split_counts()[self.base], 1)

    def test_parallel_repeated_updates_never_double_count_or_lose_new_addresses(self):
        def configure(index):
            self.store.update_link(f'base+tag{index % 5}@icloud.com', self.record())
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(configure, range(40)))
        self.assertEqual(self.store.split_counts()[self.base], 5)

    def test_history_backfill_deduplicates_links_and_completed_job_and_retains_deleted_success(self):
        # 模拟升级前的数据：同一地址同时出现在配置和任务中，另一个地址已从列表删除。
        with self.store.connect() as db:
            db.execute("DELETE FROM migrations WHERE name='split_history_backfill_v1'")
            db.execute('INSERT INTO inbox_links VALUES(?,?)', (self.target, json.dumps(self.record())))
        event = {'ok': True, 'email': self.target, 'base_email': self.base, 'inbox_url': 'public'}
        self.store.write_document('plus_creation_job', {'events': [
            event, {**event, 'email': 'base+deleted@icloud.com'},
            {**event, 'email': 'base+failed@icloud.com', 'ok': False}]}, 'old')
        self.store.ensure_split_history()
        self.store.ensure_split_history()
        self.assertEqual(self.store.split_counts()[self.base], 2)

    def test_source_counts_are_returned_with_paging_and_split_rows_have_no_count(self):
        for email in [self.base, self.target, 'untouched@icloud.com']:
            self.store.add_email(email, 'owner')
        self.store.update_link(self.target, self.record())
        source_page = email_catalog.page(self.store, {'address_type': 'source', 'page_size': 1}, '')
        self.assertEqual(len(source_page['rows']), 1)
        rows = email_catalog.page(self.store, {}, '')['rows']
        values = {row['email']: row['split_count'] for row in rows}
        self.assertEqual(values, {self.base: 1, self.target: None, 'untouched@icloud.com': 0})

    def test_shared_inbox_actual_success_and_idempotent_repair_increment_once(self):
        def publish(record):
            self.store.update_link(record['email'], {'public_registered': True, 'inbox_url': 'public'})
        with patch('plus_addressing.load_links', side_effect=self.store.load_links), \
             patch('plus_addressing.update_link', side_effect=self.store.update_link), \
             patch('plus_addressing.publish_inbox_link', side_effect=RuntimeError('publish failed')):
            with self.assertRaises(RuntimeError):
                setup_shared_inbox(self.base, self.target)
        self.assertEqual(self.store.split_counts(), {})
        with patch('plus_addressing.load_links', side_effect=self.store.load_links), \
             patch('plus_addressing.update_link', side_effect=self.store.update_link), \
             patch('plus_addressing.publish_inbox_link', side_effect=publish):
            setup_shared_inbox(self.base, self.target)
            setup_shared_inbox(self.base, self.target)
        self.assertEqual(self.store.split_counts(), {self.base: 1})
