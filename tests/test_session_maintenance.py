import unittest
from unittest.mock import Mock

import requests
from icloud_hme import ICloudHME, ICloudSessionExpired
from session_maintenance import SessionMaintenance


class SessionMaintenanceTest(unittest.TestCase):
    def test_cookie_rotation_replaces_duplicate_and_persists_before_next_request(self):
        saved = Mock()
        client = ICloudHME({'token': 'old'}, on_cookie_update=saved, verbose=False)
        response = requests.Response()
        response.status_code = 200
        response._content = b'{}'
        response.cookies.set('token', 'new', domain='.icloud.com', path='/')
        client.session.request = Mock(return_value=response)
        client._request('POST', client.setup_url + '/validate')
        self.assertEqual([(c.name, c.value) for c in client.session.cookies], [('token', 'new')])
        self.assertEqual(client.cookies['token'], 'new')
        saved.assert_called_once_with({'token': 'new'})

    def test_expired_cookie_does_not_retry_or_expose_response(self):
        client = ICloudHME({}, verbose=False)
        response = requests.Response()
        response.status_code = 421
        response._content = b'private-session-secret'
        client.session.request = Mock(return_value=response)
        with self.assertRaises(ICloudSessionExpired) as caught:
            client.validate_session()
        self.assertNotIn('private-session-secret', str(caught.exception))
        self.assertEqual(client.session.request.call_count, 1)

    def test_transient_failure_retries_other_accounts_continue_and_login_failure_pauses(self):
        now = [0]
        accounts = [{'id': 'a', 'cookies': {'token': 'a'}}, {'id': 'b', 'cookies': {'token': 'b'}}]
        manager = Mock()
        manager.list_accounts.return_value = accounts
        manager.keep_session_alive.side_effect = [
            {'status': 'error'}, {'status': 'active'},
            {'status': 'error', 'session_requires_login': True}, {'status': 'active'},
            {'status': 'active'}]
        emit = Mock()
        keeper = SessionMaintenance(manager, emit, clock=lambda: now[0])
        keeper.tick()
        self.assertEqual(manager.keep_session_alive.call_count, 2)
        now[0] = 299
        keeper.tick()
        self.assertEqual(manager.keep_session_alive.call_count, 2)
        now[0] = 300
        keeper.tick()
        accounts[0]['session_requires_login'] = True
        now[0] = 900
        keeper.tick()
        self.assertEqual(manager.keep_session_alive.call_args.args, ('b',))

    def test_failure_of_one_account_does_not_terminate_loop(self):
        manager = Mock()
        manager.list_accounts.return_value = [{'id': 'a', 'cookies': {'t': 'a'}},
                                               {'id': 'b', 'cookies': {'t': 'b'}}]
        manager.keep_session_alive.side_effect = [RuntimeError('private'), {'status': 'active'}]
        emit = Mock()
        SessionMaintenance(manager, emit).tick()
        self.assertEqual(manager.keep_session_alive.call_count, 2)
        self.assertNotIn('private', str(emit.call_args_list))
