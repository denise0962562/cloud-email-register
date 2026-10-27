from tests.auth_helpers import admin_client
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import web_ui
from inbox_links import export_lines, save_link, update_link


class WebWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.client = admin_client()

    def test_text_export_filters_accounts_and_omits_incomplete_records(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            registry = root / "links.json"
            (root / "latest_emails.txt").write_text("one@icloud.com\ta1\ntwo@icloud.com\ta2\npending@icloud.com\ta1\n")
            for alias in ("one", "two", "pending"):
                save_link(alias + "@icloud.com", alias + "@fastaiapi.cloud",
                          "https://webmail.fastaiapi.cloud/?jwt=" + alias, path=registry)
            for alias in ("one", "two"):
                update_link(alias + "@icloud.com", {"configured": True}, registry)
            with patch.object(web_ui, "RESULTS_DIR", root), patch.object(
                    web_ui, "export_lines", side_effect=lambda emails: export_lines(emails, registry)):
                response = self.client.get("/api/inbox-links/export?account_id=a1")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.text, "one@icloud.com----https://webmail.fastaiapi.cloud/?jwt=one\n")
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(response.mimetype, "text/plain")
                self.assertEqual(len(self.client.get("/api/inbox-links/export").text.splitlines()), 2)

    def test_invalid_job_counts_never_start_creation(self):
        with patch.object(web_ui._account_mgr, "get_account", return_value={"status": "active"}), \
                patch.object(web_ui._creation_jobs, "start") as start:
            for count in (0, -1, 21, True, "2"):
                response = self.client.post("/api/create-jobs", json={"account_ids": ["a1"], "count_per_account": count})
                self.assertEqual(response.status_code, 400)
            start.assert_not_called()

    def test_one_click_repair_scopes_deduplicates_and_skips_ready_links(self):
        from unittest.mock import Mock
        rows = [{"email": e, "account_id": a} for e, a in [
            ("pending@icloud.com", "a1"), ("pending@icloud.com", "a1"),
            ("ready@icloud.com", "a1"), ("base+tag@icloud.com", "a1"), ("other@icloud.com", "a2")]]
        with patch.object(web_ui._account_mgr, "get_account", return_value={"status": "error"}), \
             patch.object(web_ui, "email_storage", return_value=Mock(emails=lambda: rows)), \
             patch.object(web_ui, "load_links", return_value={"ready@icloud.com": {"configured": True, "inbox_url": "https://example.com"}}), \
             patch.object(web_ui._creation_jobs, "start", return_value="repair-job") as start:
            response = self.client.post("/api/inbox-links/repair", json={"account_id": "a1", "address_type": "source"})
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json["pending"], 1)
            self.assertEqual(start.call_args.kwargs["repair"], {"a1": ["pending@icloud.com"]})

    def test_empty_repair_does_not_start_job(self):
        from unittest.mock import Mock
        with patch.object(web_ui._account_mgr, "get_account", return_value={"status": "active"}), \
             patch.object(web_ui, "email_storage", return_value=Mock(emails=lambda: [])), \
             patch.object(web_ui._creation_jobs, "start") as start:
            response = self.client.post("/api/inbox-links/repair", json={"account_id": "a1"})
            self.assertEqual(response.json["pending"], 0)
            start.assert_not_called()

    def test_job_start_returns_id_for_polling_instead_of_blocking(self):
        with patch.object(web_ui._account_mgr, "get_account", return_value={"status": "active"}), \
                patch.object(web_ui._creation_jobs, "start", return_value="test-job") as start:
            response = self.client.post("/api/create-jobs", json={"account_ids": ["a1", "a1"], "count_per_account": 2})
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json["job_id"], "test-job")
            self.assertEqual(start.call_args.args[:2], (["a1"], 2))


if __name__ == "__main__":
    unittest.main()
