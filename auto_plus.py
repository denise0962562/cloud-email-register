"""自动分裂复用现有创建队列和定时器，独立保存配置及任务记录。"""
import re
import secrets
import string

from auto_registration import AutoRegistration, DEFAULTS
from creation_jobs import CreationJobs
from inbox_links import load_links, is_ready, update_link
from plus_addressing import plus_address, setup_shared_inbox, safe_error


class PlusCreationJobs(CreationJobs):
    document_kind = "plus_creation_job"
    target_label = "源地址"
    round_robin = True

    def sources(self):
        return {email: row for email, row in load_links().items()
                if "+" not in email and is_ready(row) and row.get("forward_inbox_url")
                and row.get("account_id") in self.manager.accounts}

    def start(self, bases, count=10, label="auto", *, item_interval=3):
        if (not isinstance(bases, list) or not bases
                or any(not isinstance(x, str) for x in bases) or len(set(bases)) != len(bases)):
            raise ValueError("请选择不同的已配置收件源地址")
        sources = self.sources()
        if any(base not in sources for base in bases):
            raise ValueError("源地址不存在、所属账号已移除或未配置收件")
        if type(count) is not int or not 1 <= count <= 200:
            raise ValueError("每个源地址每轮生成数量必须为 1–200 的整数（本地批次限制）")
        validate_prefix(label)
        if type(item_interval) is not int or not 0 <= item_interval <= 300:
            raise ValueError("地址间隔必须为 0–300 秒的整数")
        for base in bases:
            plus_address(base, "a0b1")
        return super().start(bases, count, label.lower(), interval=0, item_interval=item_interval)

    def create_item(self, base, label):
        target = None
        try:
            source = self.sources().get(base)
            if not source:
                raise ValueError("源地址已不可用")
            with self.manager._workflow_lock(source["account_id"]):
                links = load_links()
                # 发布失败留下的分裂地址先续配，避免不断留下不可用记录。
                pending = next((email for email, row in links.items()
                                if row.get("kind") == "plus" and row.get("base_email") == base
                                and row.get("auto_prefix") == label and not is_ready(row)), None)
                target = pending
                if not pending:
                    # Four-character suffixes have a smaller namespace. Retry
                    # collisions without touching an existing address or link.
                    for _ in range(64):
                        tag = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))
                        candidate = plus_address(base, tag)
                        if candidate not in links:
                            target = candidate
                            break
                    else:
                        raise ValueError("无法生成未使用的四位后缀，请稍后重试或更换源地址")
                    update_link(target, {"email": target, "kind": "plus", "base_email": base,
                                "account_id": source["account_id"], "auto_prefix": label,
                                "destination": source["destination"],
                                "forward_inbox_url": source["forward_inbox_url"], "configured": False})
                    self.manager.storage.add_email_once(target, source["account_id"])
                record = setup_shared_inbox(base, target)
                return {"ok": True, "email": target, "base_email": base, "address_type": "split",
                        "account_id": source["account_id"], "verified": bool(record.get("verified")),
                        "inbox_url": record["inbox_url"], "line": target + "----" + record["inbox_url"]}
        except Exception as error:
            if target:
                update_link(target, {"last_error": safe_error(error)})
            return {"ok": False, "email": target, "error": safe_error(error)}


def validate_prefix(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,10}", value):
        raise ValueError("后缀前缀必须为 1–10 位英文字母、数字、下划线或短横线")


class AutoPlusAddresses(AutoRegistration):
    document_kind = "auto_plus"
    target_key = "base_emails"
    target_label = "源地址"
    count_limit = 200
    target_limit = None
    defaults = {**{key: value for key, value in DEFAULTS.items() if key != "account_ids"},
                "base_emails": [], "all_sources": True, "count": 10, "interval_mode": "fixed",
                "interval_minutes": 60, "label": "auto", "sync_to_fastai": False}

    def __init__(self, *args, fastai_sync=None, **kwargs):
        self.fastai_sync = fastai_sync
        super().__init__(*args, **kwargs)

    def task_metadata(self):
        # 每轮固定提交时的开关，修改配置从下一轮生效。
        return {'sync_to_fastai': self.config['sync_to_fastai'], 'sync_cursor': 0}

    def tick(self):
        with self.lock:
            # 入队和游标均持久化；重启后可继续交接已成功的结果。
            for task in ([self.current] if self.current else []) + self.history:
                if not task.get('sync_to_fastai') or task.get('sync_handoff_done') or self.fastai_sync is None:
                    continue
                job = self.jobs.get(task['job_id']) or {}
                events = job.get('events', [])
                cursor = task.get('sync_cursor', 0)
                if cursor >= len(events):
                    if job and job.get('status') != 'running':
                        task['sync_handoff_done'] = True
                        self.persist()
                    continue
                emails = [r['email'] for r in events[cursor:] if r.get('ok') and r.get('email')]
                if emails:
                    self.fastai_sync.enqueue_split(emails, task['job_id'])
                    self.log('info', f'分裂成功邮箱已交给 FastAI 后台同步：{len(emails)} 个')
                task['sync_cursor'] = len(events)
                self.persist()
            super().tick()

    def valid_target(self, target):
        sources = getattr(self, "_validating_sources", None)
        return target in (sources if sources is not None else self.jobs.sources())

    def validate_label(self, label):
        validate_prefix(label)

    def configure(self, data):
        with self.lock:
            if not isinstance(data, dict):
                raise ValueError("自动创建配置字段无效")
            if type(data.get('sync_to_fastai', self.config['sync_to_fastai'])) is not bool:
                raise ValueError('分裂后同步 FastAI 开关必须为布尔值')
            all_sources = data.get("all_sources", self.config["all_sources"])
            if type(all_sources) is not bool:
                raise ValueError("全部源地址开关必须为布尔值")
            sources = self.jobs.sources()
            if all_sources:
                data = {**data, "base_emails": list(sources)}
            self._validating_sources = sources
            try:
                return super().configure(data)
            finally:
                del self._validating_sources

    def run_now(self, config=None, *, scheduled=False):
        with self.lock:
            if self.current or self.jobs.active:
                raise RuntimeError("已有任务运行，请等待完成")
            # Resolve all eligible sources anew for every round, including ones
            # configured after this schedule was saved.
            self.configure(config if config is not None else {})
            return super().run_now(scheduled=scheduled)

    def snapshot(self):
        with self.lock:
            data = super().snapshot()
            if self.config["all_sources"]:
                data["config"]["base_emails"] = list(self.jobs.sources())
            return data
