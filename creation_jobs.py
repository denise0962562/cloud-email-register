"""Background creation jobs; polling never repeats a mutating request."""
import copy
import re
import secrets
import threading
import time
from storage import Storage


class CreationJobs:
    # 不同创建任务使用独立记录，但复用串行执行、取消和结果持久化。
    document_kind = "creation_job"
    target_label = "账号"
    round_robin = False
    record_skips = False
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
                                  "started_at": time.time(), "total": sum(map(len,repair.values())) if repair is not None else len(account_ids)*count,
                                  "total_created": 0, "total_errors": 0, "total_skipped": 0, "progress": "准备账号配置"}
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
            result.setdefault("finished_at", time.time())
            job["results"].setdefault(account_id, []).append(result)
            job["events"].append(result)
            if result.get("ok"):
                job["lines"].append(result["line"])
                job["total_created"] += 1
            elif result.get('skipped'):
                job['total_skipped'] += 1
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

    def group_key(self, target):
        return target

    def skip_reason(self, target):
        return None

    def stop_group(self, target, result):
        return self.group_key(target) if not result.get('ok') else None

    def skipped_result(self, target, reason):
        return {'ok': False, 'skipped': True, 'account_id': self.group_key(target), 'error': reason}

    def _run(self, job_id, account_ids, count, label, interval, repair, item_interval=0):
        cancel = self._cancel_events[job_id]
        try:
            failed, previous = {}, None
            for index, account_id, ordinal, target, total in self._work_items(account_ids, count, repair):
                if cancel.is_set(): break
                group = self.group_key(account_id)
                reason = failed.get(group) or self.skip_reason(account_id)
                if reason:
                    failed[group] = reason
                    if self.record_skips:
                        self._append(job_id, account_id, self.skipped_result(account_id, reason))
                    continue
                if previous is not None:
                    gap = item_interval if self.round_robin or previous == account_id else interval
                    if gap: cancel.wait(gap)
                if cancel.is_set(): break
                reason = self.skip_reason(account_id)
                if reason:
                    failed[group] = reason
                    if self.record_skips:
                        self._append(job_id, account_id, self.skipped_result(account_id, reason))
                    continue
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
                    from icloud_hme import ICloudSessionExpired
                    message = str(error)[:250]
                    status = re.search(r"HTTP (401|403|421)\b", message)
                    if status:
                        message = f"iCloud 会话不可用（HTTP {status.group(1)}），请更新该账号 Cookie 后重新补齐"
                    if self.record_skips:
                        from plus_addressing import safe_error
                        message = safe_error(error)
                    result = {"ok": False, "account_id": account_id, "error": message,
                              'session_expired': isinstance(error, ICloudSessionExpired)}
                    if repair is not None:
                        result["email"] = target
                        from inbox_links import update_link
                        update_link(target, {"last_error": message})
                self._append(job_id, account_id, result)
                previous = account_id
                if not result.get("ok") and repair is None:
                    blocked = self.stop_group(account_id, result)
                    if blocked is not None:
                        failed[blocked] = '账号 Cookie 已确认失效，跳过本轮剩余任务' if result.get('session_expired') else '本轮账号处理失败'
            with self._lock:
                job = self._jobs[job_id]
                job["status"] = "cancelled" if cancel.is_set() else "completed"
                job["progress"] = f"已完成 {job['total_created']} 个，失败 {job['total_errors']} 个，跳过 {job['total_skipped']} 个"
                job["output"] = "\n".join(job["lines"])
                job["ok"] = job["total_errors"] == 0 and job['total_skipped'] == 0
        except Exception as error:
            with self._lock:
                self._jobs[job_id].update(status="failed", error=str(error)[:250], ok=False)
        finally:
            with self._lock:
                self._jobs[job_id]["finished_at"] = time.time()
                self._persist(job_id)
                self._active = None
                self._cancel_events.pop(job_id, None)
