import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from plus_addressing import PlusJobs, WebMailSender, inbox_subjects, plus_address, setup_shared_inbox
from storage import Storage


class PlusAddressTest(unittest.TestCase):
    def test_only_valid_non_nested_tags_and_supported_bases(self):
        self.assertEqual(plus_address('Words-here.4w@icloud.com', 'Tag01'), 'words-here.4w+tag01@icloud.com')
        for base, tag in [('a+tag@icloud.com', 'x'), ('a@icloud.com.evil', 'x'),
                          ('a@icloud.com', 'x+y'), ('a@icloud.com', '\r\nBcc:x'),
                          ('a@icloud.com', ''), ('x'*63+'@icloud.com', 'xx')]:
            with self.assertRaises(ValueError):
                plus_address(base, tag)

    def test_ascii_local_part_length_boundary(self):
        address = plus_address('a'*39+'@icloud.com', 'b'*24)
        self.assertEqual(len(address.split('@')[0].encode('ascii')), 64)
        with self.assertRaises(ValueError):
            plus_address('a'*40+'@icloud.com', 'b'*24)

    def test_sender_rejects_service_urls_before_sending_credentials(self):
        for url in ['http://p1-mail.icloud.com', 'https://icloud.com.evil.test',
                    'https://p1-mail.icloud.com:444', 'https://p1-mail.icloud.com/path']:
            client = Mock(host='icloud.com')
            client.validate_session.return_value = {'dsInfo': {'dsid': '123'}, 'webservices': {'mail': {'url': url}}}
            with self.assertRaises(ValueError):
                WebMailSender(client, {'icloud_email': 'owner@icloud.com'}).prepare()
            client._request.assert_not_called()

    def test_send_timeout_is_unknown_and_never_retried(self):
        client = Mock()
        client._request.side_effect = TimeoutError('secret-session-value')
        sender = WebMailSender(client, {})
        sender.url, sender.dsid, sender.sender = 'https://p1-mail.icloud.com/wm/message', '123', 'owner@icloud.com'
        sender.client_id = 'test-client'
        result = sender.send('alias+tag@icloud.com', 'marker')
        self.assertEqual(result['send_status'], 'unknown')
        self.assertNotIn('secret-session', result['error'])
        self.assertEqual(client._request.call_count, 1)
        self.assertEqual(client._request.call_args.kwargs['max_attempts'], 1)

    def test_inbox_checks_destination_and_decodes_subject(self):
        rows = {'results': [{'address': 'one@example.com', 'raw': 'Subject: =?utf-8?b?SE1FLVByb2Jl?=\r\n\r\n'},
                            {'address': 'other@example.com', 'raw': 'Subject: Wrong-Mailbox\r\n\r\n'}]}
        response = Mock(status_code=200)
        response.raw.read.return_value = json.dumps(rows).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch('plus_addressing.requests.get', return_value=response) as get:
            result = inbox_subjects({'destination': 'one@example.com', 'forward_inbox_url': 'https://webmail.fastaiapi.cloud/?jwt=private'})
        self.assertEqual(result, {'HME-Probe'})
        self.assertFalse(get.call_args.kwargs['allow_redirects'])


class PlusJobsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Storage(Path(self.temp.name)/'store.sqlite3')
        self.manager = SimpleNamespace(storage=self.store, accounts={'sender': {}, 'owner': {}}, get_client=lambda _: object())
        self.records = {'base@icloud.com': {'email': 'base@icloud.com', 'account_id': 'owner', 'configured': True,
                        'destination': 'base@example.com', 'inbox_url': 'https://webmail.fastaiapi.cloud/m/base',
                        'forward_inbox_url': 'https://webmail.fastaiapi.cloud/?jwt=private'}}
        self.receipts = set()
        self.sent = []
        outer = self
        class Sender:
            def __init__(self, client, account): pass
            def prepare(self): pass
            def send(self, recipient, marker):
                outer.sent.append(recipient)
                outer.receipts.add(marker)
                return {'send_status': 'accepted'}
        self.factory = Sender
        self.patchers = [patch('plus_addressing.load_links', side_effect=lambda: copy.deepcopy(self.records)),
                         patch('plus_addressing.update_link', side_effect=self.update),
                         patch('plus_addressing.publish_inbox_link', side_effect=self.publish)]
        for p in self.patchers:
            p.start(); self.addCleanup(p.stop)

    def update(self, email, values):
        self.records.setdefault(email, {}).update(values)
        return copy.deepcopy(self.records[email])

    def publish(self, record):
        return self.update(record['email'], {'public_registered': True,
                           'inbox_url': 'https://webmail.fastaiapi.cloud/m/plus-link'})

    def wait(self, jobs, job_id):
        deadline = time.monotonic()+3
        while jobs.get(job_id)['status'] == 'running' and time.monotonic() < deadline:
            time.sleep(.005)
        return jobs.get(job_id)

    def test_actual_shared_receipts_export_and_do_not_change_cloud_alias_counts(self):
        jobs = PlusJobs(self.manager, self.factory, lambda _: set(self.receipts))
        job_id = jobs.start('sender', ['base@icloud.com'], ['new'])
        result = self.wait(jobs, job_id)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.sent, ['base@icloud.com', 'base+new@icloud.com'])
        self.assertEqual(result['rows'][1]['receive_status'], 'shared_inbox')
        self.assertTrue(self.records['base+new@icloud.com']['verified'])
        self.assertEqual(self.store.emails()[0]['email'], 'base+new@icloud.com')
        self.assertEqual(len(result['lines']), 1)
        self.assertNotIn('private', json.dumps(result))
        self.assertEqual(self.manager.accounts['owner'], {})
        self.assertEqual(jobs.get(job_id), result)  # 轮询不得再次发信。
        self.assertEqual(len(self.sent), 2)

    def test_expired_sender_stops_before_any_inbox_or_send(self):
        factory = Mock()
        factory.return_value.prepare.side_effect = RuntimeError('HTTP 421: secret-cookie')
        jobs = PlusJobs(self.manager, factory)
        result = self.wait(jobs, jobs.start('sender', ['base@icloud.com'], ['x']))
        self.assertEqual(result['status'], 'failed')
        self.assertIn('421', result['error'])
        self.assertNotIn('secret-cookie', result['error'])
        self.assertEqual(result['lines'], [])
        self.assertEqual(len(self.records), 1)
        factory.return_value.send.assert_not_called()

    def test_accepted_send_without_receipt_never_exports_or_registers_address(self):
        jobs = PlusJobs(self.manager, self.factory, lambda _: set())
        with patch('plus_addressing.time.monotonic', side_effect=[0, 1000, 1001]):
            # 直接执行以确定性验证超时，不必实际等待 30 秒。
            job = {'id': 'timeout', 'sender_id': 'sender', 'bases': ['base@icloud.com'],
                   'tags': ['x'], 'rows': [], 'lines': [], 'status': 'running'}
            jobs._run(job, 30)
        result = jobs.get('timeout')
        self.assertEqual(result['lines'], [])
        self.assertEqual(self.store.emails(), [])
        self.assertFalse(self.records['base+x@icloud.com']['verified'])
        self.assertEqual(result['rows'][1]['receive_status'], 'not_observed')

    def test_restart_marks_interrupted_without_resending(self):
        self.store.write_document('plus_job', {'id': 'old', 'status': 'running', 'rows': [], 'lines': []}, 'old')
        jobs = PlusJobs(self.manager, self.factory)
        self.assertEqual(jobs.get('old')['status'], 'interrupted')
        self.assertFalse(self.sent)

    def test_invalid_payloads_and_conflicting_existing_link_do_not_mutate(self):
        jobs = PlusJobs(self.manager, self.factory)
        for sender, bases, tags, timeout in [({}, ['base@icloud.com'], ['x'], 30),
                ('sender', ['missing@icloud.com'], ['x'], 30), ('sender', ['base@icloud.com'], ['X','x'], 30),
                ('sender', ['base@icloud.com'], ['x'], True)]:
            with self.assertRaises(ValueError): jobs.start(sender, bases, tags, timeout)
        self.records['base+x@icloud.com'] = {'account_id': 'someone-else'}
        with self.assertRaises(ValueError): setup_shared_inbox('base@icloud.com', 'base+x@icloud.com')
        self.assertEqual(self.records['base+x@icloud.com'], {'account_id': 'someone-else'})


class PlusApiTest(unittest.TestCase):
    def setUp(self):
        import web_ui
        self.web = web_ui
        self.client = web_ui.app.test_client()

    def test_non_object_payload_does_not_start_a_job(self):
        with patch.object(self.web._plus_jobs, 'start') as start:
            self.assertEqual(self.client.post('/api/plus-jobs', json=[]).status_code, 400)
            start.assert_not_called()

    def test_start_returns_job_id_and_conflict_does_not_retry(self):
        payload = {'sender_id': 'a', 'bases': ['base@icloud.com'], 'tags': ['x'], 'timeout': 30}
        with patch.object(self.web._plus_jobs, 'start', return_value='key') as start:
            response = self.client.post('/api/plus-jobs', json=payload)
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json, {'job_id': 'key'})
            start.assert_called_once_with('a', ['base@icloud.com'], ['x'], 30)
        with patch.object(self.web._plus_jobs, 'start', side_effect=RuntimeError('已有测试')):
            self.assertEqual(self.client.post('/api/plus-jobs', json=payload).status_code, 409)

    def test_poll_and_export_read_results_without_sending(self):
        with patch.object(self.web._plus_jobs, 'get', return_value={'id': 'key', 'lines': ['plus----link']}), \
                patch.object(self.web._plus_jobs, 'start') as start:
            response = self.client.get('/api/plus-jobs/key')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual(self.client.get('/api/plus-jobs/key/export').text, 'plus----link\n')
            start.assert_not_called()

    def test_unknown_task_and_page_assets(self):
        with patch.object(self.web._plus_jobs, 'get', return_value=None):
            self.assertEqual(self.client.get('/api/plus-jobs/missing').status_code, 404)
        page = self.client.get('/plus')
        self.assertEqual(page.status_code, 200)
        self.assertIn('共用', page.text)
        self.assertEqual(self.client.get('/static/plus_addressing.js').status_code, 200)


if __name__ == '__main__':
    unittest.main()
