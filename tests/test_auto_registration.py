import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from auto_registration import AutoRegistration
from creation_jobs import CreationJobs
import web_ui


class AutoRegistrationTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "auto.json"
        self.now = 10000
        self.manager = Mock()
        self.manager.get_account.side_effect = lambda key: {"id": key} if key == "a1" else None
        self.jobs = Mock()
        self.jobs.active = False
        self.jobs.start.return_value = "job1"
        self.auto = AutoRegistration(self.jobs, self.manager, self.path, clock=lambda: self.now,
                                     randint=lambda low, high: high)

    def enable(self, **kwargs):
        return self.auto.configure({"enabled": True, "account_ids": ["a1"], **kwargs})

    def job(self, **kwargs):
        return {"status": "running", "results": {}, "lines": [], "total_created": 0,
                "total_errors": 0, "progress": "处理中", **kwargs}

    def test_fixed_interval_schedules_without_creating_during_http_config(self):
        data = self.enable(interval_mode="fixed", interval_minutes=60)
        self.assertEqual(data["remaining_seconds"], 3600)
        self.jobs.start.assert_not_called()
        self.now += 3600
        self.auto.tick()
        self.jobs.start.assert_called_once_with(["a1"], 5, "自动创建", item_interval=3)
        self.assertIsNone(self.auto.snapshot()["next_run"])

    def test_random_interval_is_drawn_after_completion_including_failure(self):
        self.enable(min_minutes=60, max_minutes=90)
        self.assertEqual(self.auto.next_run, self.now + 5400)
        self.auto.run_now(scheduled=True)
        self.now += 120
        self.jobs.get.return_value = self.job(status="completed", total_errors=1,
            results={"a1": [{"ok": False, "error": "Apple limit"}]})
        self.auto.tick()
        self.assertEqual(self.auto.next_run, self.now + 5400)
        self.assertEqual(len(self.auto.history), 1)
        self.assertTrue(any("Apple limit" in log["message"] for log in self.auto.logs))
        self.auto.tick()
        self.assertEqual(len(self.auto.history), 1)

    def test_manual_failure_preserves_original_deadline_during_and_after_run(self):
        self.enable()
        deadline = self.auto.next_run
        self.now += 300
        self.auto.run_now()
        self.assertEqual(self.auto.next_run, deadline)
        self.now += 30
        self.jobs.get.return_value = self.job(status="completed", total_errors=1)
        self.auto.tick()
        self.assertEqual(self.auto.next_run, deadline)
        self.assertEqual(self.auto.snapshot()["remaining_seconds"], 5400 - 330)

    def test_manual_partial_success_resets_deadline_after_completion(self):
        self.enable()
        self.now += 300
        self.auto.run_now()
        self.now += 30
        self.jobs.get.return_value = self.job(status="completed", total_created=1, total_errors=1)
        self.auto.tick()
        self.assertEqual(self.auto.next_run, self.now + 5400)

    def test_manual_configuration_changes_do_not_reset_deadline_on_failure(self):
        self.enable()
        deadline = self.auto.next_run
        self.now += 300
        self.auto.run_now({"count": 2, "min_minutes": 31, "max_minutes": 40})
        self.jobs.get.return_value = self.job(status="completed", total_errors=1)
        self.auto.tick()
        self.assertEqual(self.auto.config["count"], 2)
        self.assertEqual(self.auto.next_run, deadline)

    def test_save_keeps_deadline_and_new_parameters_apply_to_next_run(self):
        self.enable()
        deadline = self.auto.next_run
        self.now += 120
        self.auto.configure({"count": 2, "item_interval_seconds": 9, "min_minutes": 31, "max_minutes": 40})
        self.assertEqual(self.auto.next_run, deadline)
        self.auto.run_now()
        self.jobs.start.assert_called_once_with(["a1"], 2, "自动创建", item_interval=9)
        self.jobs.get.return_value = self.job(status="completed", total_created=1)
        self.auto.tick()
        self.assertEqual(self.auto.next_run, self.now + 40 * 60)

    def test_per_round_result_and_download_state_persist_independently(self):
        self.auto.configure({"account_ids": ["a1"]})
        self.auto.run_now()
        self.jobs.get.return_value = self.job(status="completed", total_created=1,
            lines=["one@icloud.com----https://mail.example/one"])
        self.auto.tick()
        other = {**self.auto.history[0], "job_id": "other"}
        self.auto.history.append(other)
        client = web_ui.app.test_client()
        with patch.object(web_ui, "_auto_registration", self.auto):
            response = client.get("/api/auto-registration/tasks/job1")
            self.assertFalse(response.json["task"].get("downloaded", False))
            response = client.get("/api/auto-registration/tasks/job1/export")
            self.assertEqual(response.text, "one@icloud.com----https://mail.example/one\n")
            self.assertTrue(self.auto.get_task("job1")["downloaded"])
            self.assertFalse(self.auto.get_task("other").get("downloaded", False))
            self.assertEqual(client.get("/api/auto-registration/tasks/missing/export").status_code, 404)
        restored = AutoRegistration(self.jobs, self.manager, self.path)
        self.assertTrue(restored.get_task("job1")["downloaded"])
        self.assertEqual(restored.get_task("job1")["download_count"], 1)

    def test_empty_and_running_task_download_do_not_mark_as_downloaded(self):
        self.auto.configure({"account_ids": ["a1"]})
        self.auto.run_now()
        with self.assertRaises(ValueError): self.auto.download_task("job1")
        self.jobs.get.return_value = self.job(status="completed", total_errors=1)
        self.auto.tick()
        with patch.object(web_ui, "_auto_registration", self.auto):
            response = web_ui.app.test_client().get("/api/auto-registration/tasks/job1/export")
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.auto.get_task("job1").get("downloaded", False))

    def test_failed_manual_round_past_deadline_runs_one_scheduled_round_then_waits(self):
        self.enable(interval_mode="fixed", interval_minutes=1)
        self.auto.run_now()
        self.now += 90
        self.jobs.get.return_value = self.job(status="completed", total_errors=1)
        self.auto.tick()
        self.assertLess(self.auto.next_run, self.now)
        self.auto.tick()
        self.assertEqual(self.auto.current["trigger"], "scheduled")
        self.auto.tick()
        self.assertEqual(self.auto.next_run, self.now + 60)
        self.auto.tick()
        self.assertEqual(self.jobs.start.call_count, 2)

    def test_restart_of_unsuccessful_manual_round_keeps_deadline(self):
        self.enable()
        deadline = self.auto.next_run
        self.auto.run_now()
        self.now += 30
        restored = AutoRegistration(self.jobs, self.manager, self.path, clock=lambda: self.now)
        self.assertEqual(restored.next_run, deadline)

    def test_waits_for_manual_job_and_duplicate_run_is_rejected(self):
        self.enable(interval_mode="fixed", interval_minutes=1)
        self.now += 60
        self.jobs.active = True
        self.auto.tick()
        self.jobs.start.assert_not_called()
        with self.assertRaises(RuntimeError): self.auto.run_now()
        self.jobs.active = False
        self.auto.tick()
        self.jobs.get.return_value = self.job()
        self.auto.tick()
        self.jobs.start.assert_called_once()

    def test_switch_off_cancels_and_never_schedules_next_round(self):
        self.enable()
        self.auto.run_now()
        self.auto.configure({"enabled": False})
        self.jobs.cancel.assert_called_once_with("job1")
        self.jobs.get.return_value = self.job(status="cancelled", total_created=1, lines=["one----link"])
        self.auto.tick()
        self.assertIsNone(self.auto.next_run)
        self.assertEqual(self.auto.history[0]["lines"], ["one----link"])

    def test_restart_restores_config_and_logs_without_repeating_interrupted_round(self):
        self.enable()
        self.auto.run_now()
        restored = AutoRegistration(self.jobs, self.manager, self.path, clock=lambda: self.now,
                                    randint=lambda low, high: high)
        self.assertTrue(restored.config["enabled"])
        self.assertIsNone(restored.current)
        self.assertEqual(restored.history[0]["status"], "interrupted")
        self.assertGreater(restored.next_run, self.now)
        self.assertTrue(restored.logs)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_invalid_configuration_does_not_mutate_saved_state(self):
        self.enable()
        before = self.path.read_text()
        for data in ({"count": True}, {"count": 0}, {"min_minutes": 100, "max_minutes": 2},
                     {"account_ids": ["bad"]}, {"interval_mode": "wrong"}, {"enabled": 1},
                     {"min_minutes": 0}, {"item_interval_seconds": -1}, None):
            with self.assertRaises(ValueError): self.auto.configure(data)
            self.assertEqual(self.path.read_text(), before)

    def test_api_returns_async_job_and_validates_config(self):
        client = web_ui.app.test_client()
        self.auto.configure({"account_ids": ["a1"]})
        with patch.object(web_ui, "_auto_registration", self.auto):
            self.assertEqual(client.post("/api/auto-registration", json={"count": -1}).status_code, 400)
            response = client.post("/api/auto-registration/run")
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.json["job_id"], "job1")
            self.assertEqual(client.get("/api/auto-registration").json["current"]["job_id"], "job1")

    def test_completed_job_results_are_logged_once_and_export_as_plain_text(self):
        self.auto.configure({"account_ids": ["a1"]})
        self.auto.run_now()
        self.jobs.get.return_value = self.job(total_created=1, lines=["one@icloud.com----https://mail.example/one"],
            results={"a1": [{"ok": True, "email": "one@icloud.com"}]})
        self.auto.tick()
        self.auto.tick()
        self.assertEqual(sum(log["level"] == "success" for log in self.auto.logs), 1)
        self.jobs.get.return_value["status"] = "completed"
        self.auto.tick()
        with patch.object(web_ui, "_auto_registration", self.auto):
            response = web_ui.app.test_client().get("/api/auto-registration/export")
            self.assertEqual(response.mimetype, "text/plain")
            self.assertEqual(response.text, "one@icloud.com----https://mail.example/one\n")

    def test_real_job_cancellation_finishes_current_alias_but_does_not_start_another(self):
        entered, finish = threading.Event(), threading.Event()
        manager = Mock()
        def create(*args):
            entered.set()
            self.assertTrue(finish.wait(3))
            return [{"ok": True, "line": "one----link"}]
        manager.create_aliases_for_account.side_effect = create
        jobs = CreationJobs(manager)
        jid = jobs.start(["a1"], count=5)
        self.assertTrue(entered.wait(3))
        jobs.cancel(jid)
        finish.set()
        # The original append may already have run; join the actual worker instead.
        for thread in list(threading.enumerate()):
            if thread.name.startswith("Thread") and thread is not threading.current_thread() and thread.daemon:
                # Only this test creates a live CreationJobs worker.
                if getattr(thread, "_target", None) == jobs._run: thread.join(3)
        self.assertFalse(jobs.active)
        self.assertEqual(jobs.get(jid)["status"], "cancelled")
        manager.create_aliases_for_account.assert_called_once()


if __name__ == "__main__": unittest.main()
