"""自动分裂复用现有创建队列和定时器，独立保存配置及任务记录。"""
import re
import secrets

from auto_registration import AutoRegistration, DEFAULTS
from creation_jobs import CreationJobs
from inbox_links import load_links, is_ready, update_link
from plus_addressing import plus_address, setup_shared_inbox, safe_error


class PlusCreationJobs(CreationJobs):
    document_kind = "plus_creation_job"
    target_label = "源地址"

    def sources(self):
        return {email: row for email, row in load_links().items()
                if "+" not in email and is_ready(row) and row.get("forward_inbox_url")
                and row.get("account_id") in self.manager.accounts}

    def start(self, bases, count=10, label="auto", *, item_interval=3):
        if (not isinstance(bases, list) or not 1 <= len(bases) <= 20
                or any(not isinstance(x, str) for x in bases) or len(set(bases)) != len(bases)):
            raise ValueError("请选择 1–20 个不同的源地址")
        sources = self.sources()
        if any(base not in sources for base in bases):
            raise ValueError("源地址不存在、所属账号已移除或未配置收件")
        if type(count) is not int or not 1 <= count <= 200:
            raise ValueError("每个源地址每轮生成数量必须为 1–200 的整数（本地批次限制）")
        validate_prefix(label)
        if type(item_interval) is not int or not 0 <= item_interval <= 300:
            raise ValueError("地址间隔必须为 0–300 秒的整数")
        for base in bases:
            plus_address(base, label + "-" + "0" * 12)
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
                target = pending or plus_address(base, label + "-" + secrets.token_hex(6))
                if not pending:
                    # 随机碰撞时直接停止本源地址本轮，不覆盖已有配置。
                    if target in links:
                        raise ValueError("分裂地址发生碰撞，请重试")
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
    target_limit = 20
    defaults = {**{key: value for key, value in DEFAULTS.items() if key != "account_ids"},
                "base_emails": [], "count": 10, "interval_mode": "fixed",
                "interval_minutes": 60, "label": "auto"}

    def valid_target(self, target):
        return target in self.jobs.sources()

    def validate_label(self, label):
        validate_prefix(label)
