"""Persistent interval scheduling over the same asynchronous creation job queue."""
import copy
import json
import math
import os
import random
import tempfile
import threading
import time
from pathlib import Path


DEFAULTS = {"enabled": False, "account_ids": [], "count": 5, "interval_mode": "random",
            "interval_minutes": 60, "min_minutes": 60, "max_minutes": 90,
            "item_interval_seconds": 3, "label": "自动创建"}


class AutoRegistration:
    def __init__(self, jobs, manager, path, *, clock=time.time, randint=random.randint):
        self.jobs, self.manager, self.path = jobs, manager, Path(path)
        self.clock, self.randint = clock, randint
        self.lock = threading.RLock()
        self.wake, self.stop_event = threading.Event(), threading.Event()
        self.thread = None
        self.config = dict(DEFAULTS)
        self.next_run = None
        self.current = None
        self.history, self.logs = [], []
        if self.path.exists():
            data = json.loads(self.path.read_text())
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump({"config": self.config, "next_run": self.next_run, "current": self.current,
                           "history": self.history[:40], "logs": self.logs}, stream, ensure_ascii=False)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name): os.unlink(name)

    def configure(self, data):
        with self.lock:
            if not isinstance(data, dict) or set(data) - set(DEFAULTS):
                raise ValueError("自动创建配置字段无效")
            config = {**self.config, **data}
            if type(config["enabled"]) is not bool: raise ValueError("开关必须为布尔值")
            ids = config["account_ids"]
            if not isinstance(ids, list) or any(not isinstance(a, str) or not self.manager.get_account(a) for a in ids):
                raise ValueError("请选择有效账号")
            config["account_ids"] = list(dict.fromkeys(ids))
            if config["enabled"] and not ids: raise ValueError("开启前请至少选择一个账号")
            for key, low, high in (("count", 1, 20), ("interval_minutes", 1, 10080),
                                   ("min_minutes", 1, 10080), ("max_minutes", 1, 10080),
                                   ("item_interval_seconds", 0, 300)):
                if type(config[key]) is not int or not low <= config[key] <= high:
                    raise ValueError(f"{key} 必须为 {low} 到 {high} 的整数")
            if config["interval_mode"] not in ("fixed", "random"): raise ValueError("请选择固定或随机间隔")
            if config["min_minutes"] > config["max_minutes"]: raise ValueError("最小间隔不能大于最大间隔")
            if not isinstance(config["label"], str) or len(config["label"]) > 100: raise ValueError("标签最多 100 字")
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

    def run_now(self, config=None, *, scheduled=False):
        with self.lock:
            if self.current or self.jobs.active: raise RuntimeError("已有任务运行，请等待完成")
            if config:
                self.configure(config)
            ids = self.config["account_ids"]
            if not ids: raise ValueError("请至少选择一个账号")
            # Session failures are reported as normal job results; do not silently skip accounts.
            job_id = self.jobs.start(ids, self.config["count"], self.config["label"],
                                     item_interval=self.config["item_interval_seconds"])
            self.current = {"job_id": job_id, "started_at": self.clock(), "status": "running",
                            "trigger": "scheduled" if scheduled else "manual",
                            "target": len(ids) * self.config["count"], "logged_results": 0,
                            "lines": [], "total_created": 0, "total_errors": 0}
            if scheduled:
                self.next_run = None
            self.log("info", f"任务 {job_id[:8]} 开始：{len(ids)} 个账号，每账号 {self.config['count']} 个")
            self.persist()
            self.wake.set()
            return job_id

    def tick(self):
        with self.lock:
            if self.current:
                job = self.jobs.get(self.current["job_id"])
                if job:
                    results = [row for rows in job["results"].values() for row in rows]
                    new = results[self.current["logged_results"]:]
                    for result in new:
                        self.log("success" if result.get("ok") else "error",
                                 (result.get("email", "") + " 创建及收件配置完成") if result.get("ok")
                                 else "本账号停止本轮：" + str(result.get("error", "配置失败"))[:240])
                    self.current.update(logged_results=len(results), lines=job.get("lines", []),
                                        total_created=job.get("total_created", 0), total_errors=job.get("total_errors", 0),
                                        progress=job.get("progress", ""))
                    if job["status"] != "running":
                        keep_deadline = self.current.get("trigger") == "manual" and not job.get("total_created", 0)
                        self.current.update(status=job["status"], finished_at=self.clock())
                        self.log("info", f"本轮结束：成功 {job.get('total_created', 0)} 个，失败 {job.get('total_errors', 0)} 个")
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
            raise KeyError("任务不存在或已超出保留范围")

    def download_task(self, job_id):
        with self.lock:
            task = self.get_task(job_id)
            if task["status"] == "running": raise ValueError("请等待本轮完成后下载")
            if not task.get("lines"): raise ValueError("本轮没有成功结果可下载")
            stored = next(row for row in self.history if row["job_id"] == job_id)
            stored.update(downloaded=True, downloaded_at=self.clock(),
                          download_count=stored.get("download_count", 0) + 1)
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
