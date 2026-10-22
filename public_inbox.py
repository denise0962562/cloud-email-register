"""Register opaque public inbox links without uploading Apple session cookies."""
import hashlib
import json
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from inbox_links import REGISTRY, update_link

from storage import Storage, database_for

CONFIG = Path(__file__).resolve().parent / "results" / "cloud_inbox_config.json"
PUBLIC_ORIGIN = "https://webmail.fastaiapi.cloud"


def load_config(path=CONFIG):
    try:
        store = Storage(database_for(path))
        store.import_document("public_config", path)
        data = store.read_document("public_config")
        if data is None:
            raise FileNotFoundError(path)
    except FileNotFoundError:
        raise RuntimeError("专属收件服务尚未部署，请先配置 Cloudflare 收件服务") from None
    if data.get("base_url") != PUBLIC_ORIGIN or len(data.get("admin_token", "")) < 32:
        raise RuntimeError("Cloudflare 收件服务配置无效")
    return data


def publish_inbox_link(record, *, registry=REGISTRY, config=None, http=None):
    config = config or load_config()
    legacy = record.get("forward_inbox_url") or record["inbox_url"]
    token = parse_qs(urlparse(legacy).query).get("jwt", [""])[0]
    if not token:
        raise RuntimeError("缺少独立收件箱凭据，请重新配置此邮箱")
    mailbox_id = record.get("public_id") or f"mbx_{secrets.randbelow(10**9):09d}"
    secret = record.get("public_secret") or secrets.token_urlsafe(32)
    # Save before the request, so retries use the same link and mapping.
    record = update_link(record["email"], {"public_id": mailbox_id, "public_secret": secret,
                                          "forward_inbox_url": legacy}, registry)
    session = http or requests.Session()
    try:
        response = session.put(PUBLIC_ORIGIN + "/m/_admin/mailboxes/" + mailbox_id, headers={
            "Authorization": "Bearer " + config["admin_token"],
        }, json={"alias": record["email"], "destination": record["destination"],
                 "api_token": token, "token_hash": hashlib.sha256(secret.encode()).hexdigest()}, timeout=25)
    except requests.RequestException:
        raise RuntimeError("专属收件链接注册失败，已保存进度，可重试") from None
    if response.status_code != 200:
        raise RuntimeError(f"专属收件服务返回 HTTP {response.status_code}，已保存进度")
    data = response.json()
    if not data.get("ok") or data.get("alias") != record["email"]:
        raise RuntimeError("专属收件服务未确认邮箱归属")
    return update_link(record["email"], {"inbox_url": f"{PUBLIC_ORIGIN}/m/{mailbox_id}.{secret}",
                                         "public_registered": True}, registry)
