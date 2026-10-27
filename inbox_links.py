"""Local registry of per-alias inbox links. Credentials stay in ignored results/."""
import threading
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from storage import Storage, database_for

REGISTRY = Path(__file__).resolve().parent / "results" / "inbox_links.json"
_lock = threading.RLock()


def link_storage(path=REGISTRY):
    store = Storage(database_for(path))
    store.import_links(path)
    return store


def load_links(path=REGISTRY):
    return link_storage(path).load_links()


def save_link(alias, destination, url, *, verified=False, path=REGISTRY):
    parsed = urlparse(url)
    legacy = parsed.path == "/" and bool(parse_qs(parsed.query).get("jwt"))
    public = bool(re.fullmatch(r"/m/mbx_\d{9}\.[A-Za-z0-9_-]{43}", parsed.path)) and not parsed.query
    if (parsed.scheme != "https" or parsed.netloc != "webmail.fastaiapi.cloud"
            or parsed.fragment or not (legacy or public)):
        raise ValueError("收件链接必须是 webmail.fastaiapi.cloud 的 HTTPS 专属链接")
    for address in (alias, destination):
        if "@" not in address or any(c.isspace() for c in address):
            raise ValueError("邮箱地址无效")
    return update_link(alias, {
        "email": alias.lower(), "destination": destination.lower(),
        "inbox_url": url, "verified": bool(verified),
    }, path)


def update_link(alias, values, path=REGISTRY):
    return link_storage(path).update_link(alias, values)


def is_ready(record):
    return bool(not record.get("deleted") and not record.get("deleting") and not record.get("parent_deleted") and record.get("inbox_url") and (record.get("configured") or record.get("verified")))


def export_lines(emails, path=REGISTRY):
    links = load_links(path)
    return [f"{email}----{links[email.lower()]['inbox_url']}"
            for email in emails
            if is_ready(links.get(email.lower(), {}))]
