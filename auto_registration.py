"""Persistent interval scheduling over the same asynchronous creation job queue."""
import copy
import math
import random
import threading
import time
from pathlib import Path


from storage import Storage, database_for
from registration_policy import ROTATION_DEFAULTS

DEFAULTS = {"enabled": False, "account_ids": [], "count": 5, "interval_mode": "random",
            "interval_minutes": 60, "min_minutes": 60, "max_minutes": 90,
            "item_interval_seconds": 3, "label": "自动创建"}


class AutoRegistration:
    # 调度、历史和下载状态共用同一实现，具体任务只定义目标与配置约束。
    defaults = {**DEFAULTS, **ROTATION_DEFAULTS}
    document_kind = "auto"
    target_key = "account_ids"
    target_label = "账号"
    count_limit = 20
    target_limit = None

    def __init__(self, jobs, manager, path, *, clock=time.time, randint=random.randint):
        self.jobs, self.manager, self.path = jobs, manager, Path(path)
        self.clock, self.randint = clock, randint
        self.lock = threading.RLock()
        self.wake, self.stop_event = threading.Event(), threading.Event()
        self.thread = None
        self.config = copy.deepcopy(self.defaults)
        self.next_run = None
        self.current = None
        self.history, self.logs = [], []
        self.storage = Storage(database_for(self.path))
        self.storage.import_document(self.document_kind, self.path)
        data = self.storage.read_document(self.document_kind)
        if data is not None:
            self.config.update(data.get("config", {}))
            self.next_run = data.get("next_run")
            self.history, self.logs = data.get("history", [])[-40:], data.get("logs", [])[-300:]
            if data.get("current"):
                old = data["current"]
                old.update(status="interrupted", finished_at=self.clock())
                self.history.insert(0, old)
                self.log("warn", "服务重启中断了上一轮；已保存的邮箱可在邮箱列表补全配置")
                if not (old.get("trigger") == "manual" and not old.get("total_created")
                        and self.next_run is not None):
                    self.next_run = self.clock() + self.delay()
        if self.config["enabled"] and self.next_run is None:
            self.next_run = self.clock() + self.delay()

    def delay(self):
        c = self.config
        minutes = c["interval_minutes"] if c["interval_mode"] == "fixed" else self.randint(c["min_minutes"], c["max_minutes"])
        return minutes * 60

    def log(self, level, message):
        self.logs.append({"time": self.clock(), "level": level, "message": message})
        self.logs = self.logs[-300:]

    def persist(self):
        self.storage.save_auto({"config": self.config, "next_run": self.next_run, "current": self.current,
                                "history": self.history[:40], "logs": self.logs}, kind=self.document_kind)

    def valid_target(self, target):
        return bool(self.manager.get_account(target))

    def validate_label(self, label):
        if not isinstance(label, str) or len(label) > 100:
            raise ValueError("标签最多 100 字")

    def configure(self, data):
        with self.lock:
            if not isinstance(data, dict) or set(data) - set(self.defaults):
                raise ValueError("自动创建配置字段无效")
            config = {**self.config, **data}
            if 'rotation_enabled' in self.defaults:
                if type(config['rotation_enabled']) is not bool:
                    raise ValueError('容量轮换开关必须为布尔值')
                for key, low, high in (('rotation_threshold', 1, 10000), ('rotation_count', 1, 20),
                                       ('delete_retries', 0, 3), ('split_per_source', 0, 20),
                                       ('hourly_create_limit', 1, 50), ('quota_window_minutes', 1, 1440)):
                    if type(config[key]) is not int or not low <= config[key] <= high:
                        raise ValueError(f'{key} 必须为 {low} 到 {high} 的整数')
            if type(config["enabled"]) is not bool: raise ValueError("开关必须为布尔值")
            ids = config[self.target_key]
            # 已移除的目标不能阻止用户关闭调度和取消当前任务。
            disabling = data.get("enabled") is False
            if (not isinstance(ids, list) or any(not isinstance(a, str) for a in ids)
                    or (not disabling and any(not self.valid_target(a) for a in ids))):
                raise ValueError("请选择有效" + self.target_label)
            config[self.target_key] = list(dict.fromkeys(ids))
            if self.target_limit and len(config[self.target_key]) > self.target_limit:
                raise ValueError(f"每次最多选择 {self.target_limit} 个{self.target_label}")
            if config["enabled"] and not ids: raise ValueError("开启前请至少选择一个" + self.target_label)
            for key, low, high in (("count", 1, self.count_limit), ("interval_minutes", 1, 10080),
                                   ("min_minutes", 1, 10080), ("max_minutes", 1, 10080),
                                   ("item_interval_seconds", 0, 300)):
                if type(config[key]) is not int or not low <= config[key] <= high:
                    raise ValueError(f"{key} 必须为 {low} 到 {high} 的整数")
            if config["interval_mode"] not in ("fixed", "random"): raise ValueError("请选择固定或随机间隔")
            if config["min_minutes"] > config["max_minutes"]: raise ValueError("最小间隔不能大于最大间隔")
            self.validate_label(config["label"])
            changed = config != self.config
            self.config = config
            if not config["enabled"]:
                self.next_run = None
                if self.current and data.get("enabled") is False:
                    self.current["cancelling"] = True
                    self.jobs.cancel(self.current["job_id"])
            elif self.next_run is None and not self.current:
                # Turning on schedules the first round; Run Now is an explicit separate action.
                self.next_run = self.clock() + self.delay()
            if changed:
                self.log("info", "配置已保存；自动创建" + ("已开启，等待下次执行" if config["enabled"] else "已关闭"))
                self.persist()
            self.wake.set()
            return self.snapshot()

    def start_job(self, ids):
        if hasattr(type(self.jobs), 'start_registration'):
            return self.jobs.start_registration(ids, self.config)
        return self.jobs.start(ids, self.config["count"], self.config["label"],
                               item_interval=self.config["item_interval_seconds"])

    def target_size(self, ids):
        return len(ids) * self.config["count"]

    def run_now(self, config=None, *, scheduled=False):
        with self.lock:
            if self.current or self.jobs.active: raise RuntimeError("已有任务运行，请等待完成")
            if config:
                self.configure(config)
            ids = self.config[self.target_key]
            if not ids: raise ValueError("请至少选择一个" + self.target_label)
            # Session failures are reported as normal job results; do not silently skip accounts.
            job_id = self.start_job(ids)
            self.current = {"job_id": job_id, "started_at": self.clock(), "status": "running",
                            "trigger": "scheduled" if scheduled else "manual",
                            "target": self.target_size(ids), "logged_results": 0,
                            "lines": [], "total_created": 0, "total_errors": 0,
                            **self.task_metadata()}
            if scheduled:
                self.next_run = None
            self.log("info", f"任务 {job_id[:8]} 开始：{len(ids)} 个{self.target_label}，本批目标 {self.current['target']} 个")
            self.persist()
            self.wake.set()
            return job_id

    def task_metadata(self):
        return {}

    def tick(self):
        with self.lock:
            if self.current:
                job = self.jobs.get(self.current["job_id"])
                if job:
                    results = job.get("events", [row for rows in job["results"].values() for row in rows])
                    new = results[self.current["logged_results"]:]
                    for result in new:
                        self.log("success" if result.get("ok") else 'warn' if result.get('skipped') else "error",
                                 (result.get("message") or (result.get("email", "") + " 创建及收件配置完成")) if result.get("ok")
                                 else ('已跳过：' if result.get('skipped') else '单个邮箱失败：') + str(result.get("error", "配置失败"))[:240])
                    self.current.update(logged_results=len(results), lines=job.get("lines", []),
                                        total_created=job.get("total_created", 0), total_errors=job.get("total_errors", 0),
                                        total_skipped=job.get('total_skipped', 0),
                                        progress=job.get("progress", ""))
                    for key in ('total_split', 'total_deleted', 'total_deleted_split'):
                        if key in job:
                            self.current[key] = job[key]
                    if job["status"] != "running":
                        keep_deadline = self.current.get("trigger") == "manual" and not job.get("total_created", 0)
                        self.current.update(status=job["status"], finished_at=self.clock())
                        self.log("info", job['progress'] if 'total_split' in job or 'total_deleted' in job else f"本轮结束：成功 {job.get('total_created', 0)} 个，失败 {job.get('total_errors', 0)} 个，跳过 {job.get('total_skipped', 0)} 个")
                        self.history.insert(0, self.current)
                        self.history = self.history[:40]
                        self.current = None
                        if not self.config["enabled"]:
                            self.next_run = None
                        elif not keep_deadline or self.next_run is None:
                            self.next_run = self.clock() + self.delay()
                        if keep_deadline and self.config["enabled"]:
                            self.log("info", "立即执行未成功创建邮箱，保留原定下轮时间")
                        self.persist()
                    elif new: self.persist()
                return
            if self.config["enabled"] and self.next_run is not None and self.clock() >= self.next_run:
                if self.jobs.active: return  # Manual and scheduled tasks share a single queue.
                try: self.run_now(scheduled=True)
                except Exception as error:
                    self.log("error", "任务启动失败：" + str(error)[:240])
                    self.next_run = self.clock() + self.delay()
                    self.persist()

    def snapshot(self):
        with self.lock:
            now = self.clock()
            return copy.deepcopy({"config": self.config, "current": self.current, "history": self.history,
                                  "logs": self.logs, "next_run": self.next_run, "server_time": now,
                                  "remaining_seconds": max(0, math.ceil(self.next_run - now)) if self.next_run else None,
                                  "waiting_for_manual": bool(not self.current and self.jobs.active)})

    def get_task(self, job_id):
        with self.lock:
            for task in ([self.current] if self.current else []) + self.history:
                if task["job_id"] == job_id:
                    return copy.deepcopy(task)
            archived = self.storage.get_task(job_id)
            if archived is not None:
                return archived
            raise KeyError("任务不存在")

    def download_task(self, job_id):
        with self.lock:
            task = self.get_task(job_id)
            if task["status"] == "running": raise ValueError("请等待本轮完成后下载")
            if not task.get("lines"): raise ValueError("本轮没有成功结果可下载")
            stored = next((row for row in self.history if row["job_id"] == job_id), task)
            stored.update(downloaded=True, downloaded_at=self.clock(),
                          download_count=stored.get("download_count", 0) + 1)
            self.storage.save_task(stored)
            self.persist()
            return copy.deepcopy(stored)

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive(): return
            self.persist()
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    def _loop(self):
        while not self.stop_event.is_set():
            self.wake.clear()
            try: self.tick()
            except Exception as error:
                with self.lock: self.log("error", "调度异常：" + str(error)[:240])
            self.wake.wait(1)

    def close(self):
        self.stop_event.set()
        self.wake.set()
