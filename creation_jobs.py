"""Background creation jobs; polling never repeats a mutating request."""
import copy
import re
import secrets
import threading
from storage import Storage


class CreationJobs:
    # 不同创建任务使用独立记录，但复用串行执行、取消和结果持久化。
    document_kind = "creation_job"
    target_label = "账号"
    round_robin = False
    def __init__(self, manager, on_result=None):
        self.manager = manager
        candidate = getattr(manager, "storage", None)
        self.storage = candidate if isinstance(candidate, Storage) else None
        self._lock = threading.RLock()
        self._jobs = {}
        self._active = None
        self.on_result = on_result
        self._cancel_events = {}

    @property
    def active(self):
        with self._lock:
            return self._active is not None

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None and self.storage:
                job = self.storage.read_document(self.document_kind, job_id)
                if job and job.get("status") == "running":
                    job.update(status="interrupted", error="服务重启，未自动重试该任务")
                    self.storage.write_document(self.document_kind, job, job_id)
            return copy.deepcopy(job) if job else None

    def start(self, account_ids, count=1, label="", interval=3, repair=None, item_interval=0):
        with self._lock:
            if self._active:
                raise RuntimeError("已有创建任务运行中，请等待完成")
            job_id = secrets.token_hex(12)
            self._jobs[job_id] = {"id": job_id, "status": "running", "results": {}, "events": [], "lines": [],
                                  "total_created": 0, "total_errors": 0, "progress": "准备账号配置"}
            self._persist(job_id)
            self._active = job_id
            self._cancel_events[job_id] = threading.Event()
            threading.Thread(target=self._run, args=(job_id, account_ids, count, label, interval, repair, item_interval), daemon=True).start()
            return job_id

    def _persist(self, job_id):
        if self.storage:
            self.storage.write_document(self.document_kind, self._jobs[job_id], job_id)

    def create_item(self, target, label):
        return self.manager.create_aliases_for_account(target, 1, label)[0]

    def cancel(self, job_id):
        with self._lock:
            event = self._cancel_events.get(job_id)
            if event and self._jobs[job_id]["status"] == "running":
                event.set()
                self._jobs[job_id]["progress"] = "正在停止，等待当前邮箱完成"
                self._persist(job_id)
                return True
            return False

    def _append(self, job_id, account_id, result):
        with self._lock:
            job = self._jobs[job_id]
            job["results"].setdefault(account_id, []).append(result)
            job["events"].append(result)
            if result.get("ok"):
                job["lines"].append(result["line"])
                job["total_created"] += 1
            else:
                job["total_errors"] += 1
            self._persist(job_id)
        if self.on_result:
            self.on_result(result)

    def _work_items(self, account_ids, count, repair):
        if self.round_robin and repair is None:
            for ordinal in range(count):
                for index, account_id in enumerate(account_ids):
                    yield index, account_id, ordinal, ordinal, count
        else:
            for index, account_id in enumerate(account_ids):
                targets = repair.get(account_id, []) if repair is not None else range(count)
                for ordinal, target in enumerate(targets):
                    yield index, account_id, ordinal, target, len(targets)

    def _run(self, job_id, account_ids, count, label, interval, repair, item_interval=0):
        cancel = self._cancel_events[job_id]
        try:
            failed, previous = set(), None
            for index, account_id, ordinal, target, total in self._work_items(account_ids, count, repair):
                if account_id in failed: continue
                if previous is not None:
                    gap = item_interval if self.round_robin or previous == account_id else interval
                    if gap: cancel.wait(gap)
                if cancel.is_set(): break
                with self._lock:
                    action = "补齐收件地址" if repair is not None else "创建并配置收件"
                    self._jobs[job_id]["progress"] = f"{self.target_label} {index + 1}/{len(account_ids)}，邮箱 {ordinal + 1}/{total}：{action}"
                    self._persist(job_id)
                try:
                    if repair is not None:
                        result = self.manager.setup_alias_inbox(account_id, target)
                    else:
                        result = self.create_item(account_id, label)
                except Exception as error:
                    message = str(error)[:250]
                    status = re.search(r"HTTP (401|403|421)\b", message)
                    if status:
                        message = f"iCloud 会话不可用（HTTP {status.group(1)}），请更新该账号 Cookie 后重新补齐"
                    result = {"ok": False, "account_id": account_id, "error": message}
                    if repair is not None:
                        result["email"] = target
                        from inbox_links import update_link
                        update_link(target, {"last_error": message})
                self._append(job_id, account_id, result)
                previous = account_id
                if not result.get("ok") and repair is None:
                    failed.add(account_id)
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "cancelled" if cancel.is_set() else "completed"
                job["progress"] = f"已完成 {job['total_created']} 个，失败 {job['total_errors']} 个"
                job["output"] = "\n".join(job["lines"])
                job["ok"] = job["total_errors"] == 0
        except Exception as error:
            with self._lock:
                self._jobs[job_id].update(status="failed", error=str(error)[:250], ok=False)
        finally:
            with self._lock:
                self._persist(job_id)
                self._active = None
                self._cancel_events.pop(job_id, None)
