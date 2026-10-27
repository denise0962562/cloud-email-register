"""自动分裂复用现有创建队列和定时器，独立保存配置及任务记录。"""
import json
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
    record_skips = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._source_owners = {}
        self._failed_addresses = set()

    def group_key(self, target):
        return self._source_owners.get(target, target)

    def skip_reason(self, target):
        account = self.manager.get_account(self.group_key(target)) or {}
        if account.get('session_requires_login'):
            return '账号 Cookie 已确认失效，跳过本轮剩余任务'

    def stop_group(self, target, result):
        # 收件服务的 401/403 并不能证明 Apple Cookie 失效。
        return self.group_key(target) if result.get('session_expired') else None

    def skipped_result(self, target, reason):
        return {**super().skipped_result(target, reason), 'base_email': target}

    def sources(self):
        return {email: row for email, row in load_links().items()
                if "+" not in email and is_ready(row) and row.get("forward_inbox_url")
                and row.get("account_id") in self.manager.accounts}

    def start(self, bases, count=10, label="auto", *, item_interval=3, total=None):
        if (not isinstance(bases, list) or not bases
                or any(not isinstance(x, str) for x in bases) or len(set(bases)) != len(bases)):
            raise ValueError("请选择不同的已配置收件源地址")
        sources = self.sources()
        if any(base not in sources for base in bases):
            raise ValueError("源地址不存在、所属账号已移除或未配置收件")
        if type(count) is not int or not 1 <= count <= 200:
            raise ValueError("每个源地址每轮生成数量必须为 1–200 的整数（本地批次限制）")
        if total is not None and (type(total) is not int or not 1 <= total <= 10000):
            raise ValueError('整批创建数量必须为 1–10000 的整数')
        validate_prefix(label)
        if type(item_interval) is not int or not 0 <= item_interval <= 300:
            raise ValueError("地址间隔必须为 0–300 秒的整数")
        for base in bases:
            plus_address(base, "a0b1")
        with self._lock:
            if self._active:
                raise RuntimeError('已有创建任务运行中，请等待完成')
            self._source_owners = {base: sources[base]['account_id'] for base in bases}
            self._failed_addresses = set()
            self._rotation_plan = None
            if total is not None:
                start = self.rotation_start(bases)
                self._rotation_plan = {'bases': list(bases), 'start': start}
                # 整批数量独立于源地址数；每次只取下一个源，走到末尾再绕回开头。
                plan = [bases[(start + index) % len(bases)] for index in range(total)]
                return super().start(plan, 1, label.lower(), interval=0, item_interval=item_interval)
            return super().start(bases, count, label.lower(), interval=0, item_interval=item_interval)

    def rotation_start(self, bases):
        """优先按上次源地址接续；源被移除时按保存的位置回退，避免每批回到第一条。"""
        if not bases or not self.storage:
            return 0
        state = self.storage.read_document('plus_rotation') or {}
        if not state:
            # 升级前的手动批次也有逐项日志，从最近一次实际处理的位置接续。
            with self.storage.connect() as db:
                row = db.execute("SELECT json_extract(data,'$.events[#-1].base_email') "
                                 "FROM documents WHERE kind='plus_creation_job' "
                                 "AND json_array_length(json_extract(data,'$.events'))>0 "
                                 "ORDER BY rowid DESC LIMIT 1").fetchone()
            state = {'last_base': row[0]} if row else {}
        last = state.get('last_base')
        return (bases.index(last) + 1) % len(bases) if last in bases else state.get('next_index', 0) % len(bases)

    def _persist(self, job_id):
        job = self._jobs[job_id]
        rotation = job.get('rotation') or getattr(self, '_rotation_plan', None)
        if not rotation or not self.storage:
            return super()._persist(job_id)
        job['rotation'] = rotation
        events = job.get('events', [])
        with self.storage.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO documents VALUES(?,?,?) ON CONFLICT(kind,key) DO UPDATE SET data=excluded.data',
                       (self.document_kind, job_id, json.dumps(job, ensure_ascii=False)))
            if events:
                bases = rotation['bases']
                position = (rotation['start'] + len(events)) % len(bases)
                state = {'last_base': bases[(position - 1) % len(bases)], 'next_index': position}
                # 任务结果和游标在同一事务提交；取消、刷新或服务重启都不会重复前移。
                db.execute('INSERT INTO documents VALUES(?,?,?) ON CONFLICT(kind,key) DO UPDATE SET data=excluded.data',
                           ('plus_rotation', 'default', json.dumps(state, ensure_ascii=False)))

    def create_item(self, base, label):
        target = None
        try:
            source = self.sources().get(base)
            if not source:
                raise ValueError("源地址已不可用")
            with self.manager._workflow_lock(source["account_id"]):
                reason = self.skip_reason(base)
                if reason:
                    return {**self.skipped_result(base, reason), 'session_expired': True}
                links = load_links()
                # 发布失败留下的分裂地址先续配，避免不断留下不可用记录。
                pending = next((email for email, row in links.items()
                                if row.get("kind") == "plus" and row.get("base_email") == base
                                and row.get("auto_prefix") == label and not is_ready(row)
                                and email not in self._failed_addresses), None)
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
            from icloud_hme import ICloudSessionExpired
            if target:
                update_link(target, {"last_error": safe_error(error)})
                if self.active:
                    self._failed_addresses.add(target)
            return {"ok": False, "email": target, "error": safe_error(error),
                    'account_id': self.group_key(base), 'session_expired': isinstance(error, ICloudSessionExpired)}


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
                "interval_minutes": 60, "label": "auto", "sync_to_fastai": False, "batch_total": None}

    sync_on_completion = False

    def __init__(self, *args, fastai_sync=None, **kwargs):
        self.fastai_sync = fastai_sync
        super().__init__(*args, fastai_sync=fastai_sync, **kwargs)

    def target_size(self, ids):
        return self.config['batch_total'] if self.config['batch_total'] is not None else super().target_size(ids)

    def start_job(self, ids):
        if self.config['batch_total'] is None:
            return super().start_job(ids)
        return self.jobs.start(ids, 1, self.config['label'],
                               item_interval=self.config['item_interval_seconds'],
                               total=self.config['batch_total'])

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
            total = data.get('batch_total', self.config['batch_total'])
            if total is not None and (type(total) is not int or not 1 <= total <= 10000):
                raise ValueError('整批创建数量必须为 1–10000 的整数')
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
            bases = data['config']['base_emails']
            data['next_source'] = bases[self.jobs.rotation_start(bases)] if bases else None
            return data
