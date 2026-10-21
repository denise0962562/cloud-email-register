import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from creation_jobs import CreationJobs
from inbox_links import export_lines, load_links, save_link, update_link
from mail_provisioning import MailProvisioner


class FakeApple:
    _service_url = "https://p1-maildomainws.icloud.com"

    def __init__(self):
        self.rules = []
        self.fail = False
        self.uncertain = False
        self.creates = 0

    def validate_session(self):
        return {"webservices": {"mcc": {"url": "https://p1-mcc.icloud.com"}}}

    def get_account_info(self):
        return {"dsid": "123"}

    def _request(self, method, url, json_data=None, **kwargs):
        if url.endswith("/v2/hme/list"):
            return {"success": True, "result": {"selectedForwardTo": "owner@icloud.com", "forwardToEmails": ["owner@icloud.com"]}}
        if method == "GET":
            return {"mailRules": list(self.rules)}
        if self.fail:
            raise TimeoutError("test mutation failure")
        self.creates += 1
        rule = dict(json_data["data"][0]["data"], ruleId="new-rule")
        self.rules.append(rule)
        if self.uncertain:
            raise TimeoutError("lost successful response")
        return {"message": "OK"}


class FakeDomain:
    def __init__(self):
        self.creates = 0
        self.address = "isolated@fastaiapi.cloud"

    def request(self, method, url, **kwargs):
        if method == "POST":
            self.creates += 1
            payload = {"address": self.address, "jwt": "test-token"}
        else:
            payload = {"address": self.address}
        return Mock(ok=True, json=lambda: payload)


class ProvisioningTest(unittest.TestCase):
    def test_new_account_sets_forward_target_after_first_alias_exists(self):
        apple = FakeApple()
        original = apple._request
        state = {"aliases": [], "selected": None, "updates": 0}

        def request(method, url, json_data=None, **kwargs):
            if url.endswith('/v2/hme/list'):
                return {"success": True, "result": {
                    "forwardToEmails": ['owner@icloud.com'],
                    "hmeEmails": state['aliases'], "selectedForwardTo": state['selected']}}
            if url.endswith('/v1/hme/updateForwardTo'):
                self.assertTrue(state['aliases'])
                state['updates'] += 1
                state['selected'] = json_data['forwardToEmail']
                return {"success": True}
            return original(method, url, json_data, **kwargs)

        apple._request = request
        with tempfile.TemporaryDirectory() as folder:
            p = MailProvisioner(apple, Path(folder) / 'links.json', FakeDomain(), publisher=lambda r: r)
            p.prepare()
            self.assertEqual(state['updates'], 0)
            state['aliases'] = [{'hme': 'first@icloud.com'}]
            result = p.provision('first@icloud.com', 'account-1')
            self.assertTrue(result['configured'])
            self.assertEqual(state['selected'], 'owner@icloud.com')
            self.assertEqual(state['updates'], 1)

    def test_failed_forwarding_resumes_without_new_inbox_or_alias(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "registry.json"
            apple, domain = FakeApple(), FakeDomain()
            provisioner = MailProvisioner(apple, path, domain, publisher=lambda r: r)
            provisioner.prepare()
            apple.fail = True
            with self.assertRaises(RuntimeError):
                provisioner.provision("one@icloud.com", "account-1")
            self.assertEqual(export_lines(["one@icloud.com"], path), [])
            self.assertEqual(load_links(path)["one@icloud.com"]["stage"], "pending")
            apple.fail = False
            record = provisioner.provision("one@icloud.com", "account-1")
            self.assertTrue(record["configured"])
            self.assertFalse(record["verified"])
            self.assertEqual(domain.creates, 1)
            self.assertEqual(apple.creates, 1)
            self.assertEqual(apple.rules[0]["body"], "one@icloud.com")
            self.assertEqual(apple.rules[0]["target"], domain.address)
            self.assertEqual(len(export_lines(["one@icloud.com", "other@icloud.com"], path)), 1)
            provisioner.provision("one@icloud.com", "account-1")
            self.assertEqual(domain.creates, 1)

    def test_lost_successful_rule_response_does_not_duplicate_rule(self):
        apple = FakeApple()
        apple.uncertain = True
        provisioner = MailProvisioner(apple, publisher=lambda r: r)
        provisioner.prepare()
        self.assertEqual(provisioner.ensure_rule("one@icloud.com", "one@fastaiapi.cloud"), "new-rule")
        self.assertEqual(provisioner.ensure_rule("one@icloud.com", "one@fastaiapi.cloud"), "new-rule")
        self.assertEqual(apple.creates, 1)

    def test_conflicting_rule_is_not_overwritten(self):
        apple = FakeApple()
        apple.rules = [{"ruleId": "user-rule", "prefix": "TO", "body": "one@icloud.com",
                        "action": "FRWD", "target": "someone@example.com"}]
        provisioner = MailProvisioner(apple, publisher=lambda r: r)
        provisioner.prepare()
        with self.assertRaisesRegex(RuntimeError, "冲突"):
            provisioner.ensure_rule("one@icloud.com", "one@fastaiapi.cloud")
        self.assertEqual(apple.creates, 0)
        self.assertEqual(apple.rules[0]["target"], "someone@example.com")

    def test_long_alias_keeps_full_match_but_uses_valid_rule_name(self):
        apple = FakeApple()
        provisioner = MailProvisioner(apple, publisher=lambda r: r)
        provisioner.prepare()
        alias = "cabaret_shellac_6o@icloud.com"
        provisioner.ensure_rule(alias, "one@fastaiapi.cloud")
        self.assertLessEqual(len(apple.rules[0]["ruleName"]), 30)
        self.assertEqual(apple.rules[0]["body"], alias)

    def test_wrong_mailbox_identity_never_gets_forwarding_rule(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "registry.json"
            save_link("one@icloud.com", "one@fastaiapi.cloud", "https://webmail.fastaiapi.cloud/?jwt=x", path=path)
            apple = FakeApple()
            provisioner = MailProvisioner(apple, path, FakeDomain(), publisher=lambda r: r)
            provisioner.prepare()
            with self.assertRaisesRegex(RuntimeError, "凭据校验失败"):
                provisioner.provision("one@icloud.com", "account-1")
            self.assertEqual(apple.creates, 0)

    def test_job_polling_never_creates_again_and_exports_only_successes(self):
        entered, release = threading.Event(), threading.Event()
        manager = Mock()
        def create(account_id, count, label):
            entered.set()
            release.wait(3)
            return [{"ok": True, "email": "one@icloud.com", "line": "one@icloud.com----https://example.com/inbox"}]
        manager.create_aliases_for_account.side_effect = create
        jobs = CreationJobs(manager)
        job_id = jobs.start(["account-1"], count=2, interval=0)
        self.assertTrue(entered.wait(1))
        self.assertEqual(jobs.get(job_id)["status"], "running")
        with self.assertRaises(RuntimeError):
            jobs.start(["account-1"])
        release.set()
        for _ in range(100):
            if jobs.get(job_id)["status"] != "running": break
            time.sleep(.01)
        self.assertEqual(jobs.get(job_id)["total_created"], 2)
        self.assertEqual(manager.create_aliases_for_account.call_count, 2)
        for _ in range(5): jobs.get(job_id)
        self.assertEqual(manager.create_aliases_for_account.call_count, 2)

    def test_alias_is_recorded_before_setup_failure_and_batch_stops(self):
        import account_manager as module
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            with patch.multiple(module, ACCOUNTS_FILE=directory / "accounts.json", RESULTS_DIR=directory,
                                LATEST_EMAILS=directory / "latest.txt"):
                manager = module.AccountManager()
                manager.accounts = {"account-1": {"id": "account-1", "name": "test", "cookies": {}}}
                client = Mock()
                client.create_alias.return_value = {"email": "one@icloud.com"}
                manager.get_client = Mock(return_value=client)
                with patch("mail_provisioning.MailProvisioner") as factory:
                    factory.return_value.provision.side_effect = RuntimeError("forwarding failed")
                    result = manager.create_aliases_for_account("account-1", count=5)
                self.assertEqual(client.create_alias.call_count, 1)
                self.assertTrue(result[0]["alias_created"])
                self.assertFalse(result[0]["ok"])
                self.assertEqual((directory / "latest.txt").read_text(), "one@icloud.com\taccount-1\n")


if __name__ == "__main__":
    unittest.main()
