"""Background creation jobs; polling never repeats a mutating request."""
import copy
import secrets
import threading


class CreationJobs:
    def __init__(self, manager, on_result=None):
        self.manager = manager
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
            return copy.deepcopy(job) if job else None

    def start(self, account_ids, count=1, label="", interval=3, repair=None, item_interval=0):
        with self._lock:
            if self._active:
                raise RuntimeError("已有创建任务运行中，请等待完成")
            job_id = secrets.token_hex(12)
            self._jobs[job_id] = {"id": job_id, "status": "running", "results": {}, "lines": [],
                                  "total_created": 0, "total_errors": 0, "progress": "准备账号配置"}
            self._active = job_id
            self._cancel_events[job_id] = threading.Event()
            threading.Thread(target=self._run, args=(job_id, account_ids, count, label, interval, repair, item_interval), daemon=True).start()
            return job_id

    def cancel(self, job_id):
        with self._lock:
            event = self._cancel_events.get(job_id)
            if event and self._jobs[job_id]["status"] == "running":
                event.set()
                self._jobs[job_id]["progress"] = "正在停止，等待当前邮箱完成"
                return True
            return False

    def _append(self, job_id, account_id, result):
        with self._lock:
            job = self._jobs[job_id]
            job["results"].setdefault(account_id, []).append(result)
            if result.get("ok"):
                job["lines"].append(result["line"])
                job["total_created"] += 1
            else:
                job["total_errors"] += 1
        if self.on_result:
            self.on_result(result)

    def _run(self, job_id, account_ids, count, label, interval, repair, item_interval=0):
        cancel = self._cancel_events[job_id]
        try:
            for index, account_id in enumerate(account_ids):
                if cancel.is_set(): break
                targets = repair.get(account_id, []) if repair is not None else range(count)
                for ordinal, target in enumerate(targets):
                    if cancel.is_set(): break
                    with self._lock:
                        self._jobs[job_id]["progress"] = f"账号 {index + 1}/{len(account_ids)}，邮箱 {ordinal + 1}/{len(targets)}：创建并配置收件"
                    try:
                        if repair is not None:
                            result = self.manager.setup_alias_inbox(account_id, target)
                        else:
                            result = self.manager.create_aliases_for_account(account_id, 1, label)[0]
                    except Exception as error:
                        result = {"ok": False, "account_id": account_id, "error": str(error)[:250]}
                    self._append(job_id, account_id, result)
                    if not result.get("ok") and repair is None:
                        break
                    if ordinal < len(targets) - 1 and item_interval:
                        cancel.wait(item_interval)
                if index < len(account_ids) - 1 and interval:
                    cancel.wait(interval)
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
                self._active = None
                self._cancel_events.pop(job_id, None)
