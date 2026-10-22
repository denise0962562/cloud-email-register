"""Transactional project-local SQLite storage; JSON is used only as row payloads.

Legacy files are imported once, then remain untouched as recovery material.
"""
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / 'icloud_hme.sqlite3'


def database_for(legacy_path):
    path = Path(legacy_path).resolve()
    if path.parent in (ROOT, ROOT / 'results'):
        return DB_PATH
    return path.with_suffix('.sqlite3')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Storage:
    def __init__(self, path=DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS migrations(name TEXT PRIMARY KEY, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));
                CREATE TABLE IF NOT EXISTS account_sessions(account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
                    cookies TEXT NOT NULL CHECK(json_valid(cookies)));
                CREATE TABLE IF NOT EXISTS inbox_links(email TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));
                CREATE TABLE IF NOT EXISTS email_records(seq INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL,
                    account_id TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT '', raw TEXT NOT NULL DEFAULT '');
                CREATE INDEX IF NOT EXISTS email_records_account ON email_records(account_id);
                CREATE TABLE IF NOT EXISTS documents(kind TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL CHECK(json_valid(data)),
                    PRIMARY KEY(kind,key));
                CREATE TABLE IF NOT EXISTS tasks(job_id TEXT PRIMARY KEY, data TEXT NOT NULL CHECK(json_valid(data)));
                CREATE TABLE IF NOT EXISTS task_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, digest TEXT UNIQUE NOT NULL,
                    data TEXT NOT NULL CHECK(json_valid(data)));
                CREATE TABLE IF NOT EXISTS legacy_sources(path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, content BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS fastai_sync(email TEXT NOT NULL, api_url TEXT NOT NULL,
                    inbox_url TEXT NOT NULL, status TEXT NOT NULL, synced_at REAL,
                    last_error TEXT NOT NULL DEFAULT '', job_id TEXT NOT NULL,
                    PRIMARY KEY(email,api_url));
                PRAGMA user_version=1;
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=30000')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def import_once(self, name, importer):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM migrations WHERE name=?', (name,)).fetchone():
                return
            importer(db)
            db.execute('INSERT INTO migrations VALUES (?,?)', (name, datetime.now(timezone.utc).isoformat()))

    @staticmethod
    def archive(db, path):
        path = Path(path)
        if path.exists():
            blob = path.read_bytes()
            db.execute('INSERT OR IGNORE INTO legacy_sources VALUES (?,?,?)',
                       (str(path.resolve()), hashlib.sha256(blob).hexdigest(), blob))

    def import_accounts(self, metadata_path, sessions_dir, old_cookies_path=None):
        def importer(db):
            source = Path(metadata_path)
            self.archive(db, source)
            accounts = json.loads(source.read_text()).get('accounts', {}) if source.exists() else {}
            if not accounts and not source.exists() and old_cookies_path and Path(old_cookies_path).exists():
                self.archive(db, old_cookies_path)
                accounts = {'acc_legacy': {'id': 'acc_legacy', 'name': '默认账号',
                    'cookies': json.loads(Path(old_cookies_path).read_text()), 'status': 'active'}}
            for key, original in accounts.items():
                account = dict(original)
                cookies = account.pop('cookies', {})
                session = Path(sessions_dir) / (key + '.json')
                if session.exists():
                    self.archive(db, session)
                    cookies = json.loads(session.read_text())['cookies']
                if not isinstance(cookies, dict): raise ValueError('账号会话格式无效: ' + key)
                db.execute('INSERT INTO accounts VALUES (?,?)', (key, encode(account)))
                db.execute('INSERT INTO account_sessions VALUES (?,?)', (key, encode(cookies)))
        self.import_once('accounts', importer)

    def load_accounts(self):
        with self.connect() as db:
            return {key: {**json.loads(data), 'cookies': json.loads(cookies)} for key, data, cookies in
                    db.execute('SELECT a.id,a.data,s.cookies FROM accounts a JOIN account_sessions s ON s.account_id=a.id')}

    def save_accounts(self, accounts, previous):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for key in set(previous) - set(accounts):
                db.execute('DELETE FROM accounts WHERE id=?', (key,))
            for key, value in accounts.items():
                meta = {k: v for k, v in value.items() if k != 'cookies'}
                old = previous.get(key)
                old_meta = {k: v for k, v in old.items() if k != 'cookies'} if old is not None else None
                if meta != old_meta:
                    db.execute('INSERT INTO accounts VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data', (key, encode(meta)))
                cookies = value.get('cookies', {})
                if old is None:
                    db.execute('INSERT INTO account_sessions VALUES (?,?)', (key, encode(cookies)))
                elif cookies != old.get('cookies', {}):
                    cursor = db.execute('UPDATE account_sessions SET cookies=? WHERE account_id=? AND cookies=?',
                                        (encode(cookies), key, encode(old.get('cookies', {}))))
                    if not cursor.rowcount:
                        raise RuntimeError('登录态已被更新，拒绝旧会话覆盖: ' + key)

    def import_links(self, path):
        def importer(db):
            self.archive(db, path)
            data = json.loads(Path(path).read_text()) if Path(path).exists() else {}
            for key, record in data.items():
                db.execute('INSERT INTO inbox_links VALUES (?,?)', (key.lower(), encode(record)))
        self.import_once('inbox_links', importer)

    def load_links(self):
        with self.connect() as db:
            return {key: json.loads(data) for key, data in db.execute('SELECT email,data FROM inbox_links ORDER BY rowid')}

    def update_link(self, email, values):
        email = email.lower()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM inbox_links WHERE email=?', (email,)).fetchone()
            record = json.loads(row[0]) if row else {'email': email}
            record.update(values)
            record['updated_at'] = datetime.now(timezone.utc).isoformat()
            db.execute('INSERT INTO inbox_links VALUES (?,?) ON CONFLICT(email) DO UPDATE SET data=excluded.data', (email, encode(record)))
            return record

    def import_emails(self, path):
        def importer(db):
            self.archive(db, path)
            if Path(path).exists():
                for line in Path(path).read_text().splitlines():
                    if line.strip() and '@' in line:
                        parts = line.strip().split('\t')
                        db.execute('INSERT INTO email_records(email,account_id,raw) VALUES (?,?,?)',
                                   (parts[0], parts[1] if len(parts) > 1 else '', line))
        self.import_once('email_records', importer)

    def add_email(self, email, account_id):
        with self.connect() as db:
            db.execute('INSERT INTO email_records(email,account_id,created_at) VALUES (?,?,?)',
                       (email, account_id, datetime.now(timezone.utc).isoformat()))

    def backfill_creation_times(self, account_id, aliases):
        """Fill missing timestamps from Apple without changing existing times or ownership."""
        changed = 0
        with self.connect() as db:
            for alias in aliases:
                value = alias.get('createdAt')
                if value is None or isinstance(value, bool): continue
                try:
                    if isinstance(value,(int,float)) or str(value).replace('.','',1).isdigit():
                        stamp = float(value)
                        if stamp <= 0: continue
                        if stamp > 100000000000: stamp /= 1000
                        date = datetime.fromtimestamp(stamp,timezone.utc)
                    else:
                        date = datetime.fromisoformat(str(value).replace('Z','+00:00'))
                        if date.tzinfo is None: date = date.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
                    text = date.astimezone(timezone.utc).isoformat()
                except (ValueError, TypeError, OverflowError, OSError):
                    continue
                cursor = db.execute("UPDATE email_records SET created_at=? WHERE email=? AND account_id=? AND created_at=''",
                                    (text,alias.get('email','').lower(),account_id))
                changed += cursor.rowcount
        return changed

    def emails(self):
        with self.connect() as db:
            return [dict(zip(('email','account_id','created_at'), row)) for row in
                    db.execute('SELECT email,account_id,created_at FROM email_records ORDER BY seq')]

    def read_document(self, kind, key='default'):
        with self.connect() as db:
            row = db.execute('SELECT data FROM documents WHERE kind=? AND key=?', (kind,key)).fetchone()
            return json.loads(row[0]) if row else None

    def write_document(self, kind, data, key='default'):
        with self.connect() as db:
            db.execute('INSERT INTO documents VALUES (?,?,?) ON CONFLICT(kind,key) DO UPDATE SET data=excluded.data',
                       (kind,key,encode(data)))

    def import_document(self, kind, path):
        def importer(db):
            self.archive(db, path)
            if Path(path).exists():
                data = json.loads(Path(path).read_text())
                db.execute('INSERT INTO documents VALUES (?,?,?)', (kind,'default',encode(data)))
                if kind == 'auto': self._archive_tasks(db, data)
        self.import_once(kind, importer)

    @staticmethod
    def _archive_tasks(db, state):
        for task in state.get('history', []):
            db.execute('INSERT INTO tasks VALUES (?,?) ON CONFLICT(job_id) DO UPDATE SET data=excluded.data',
                       (task['job_id'], encode(task)))
        for entry in state.get('logs', []):
            text = encode(entry)
            db.execute('INSERT OR IGNORE INTO task_logs(digest,data) VALUES (?,?)', (hashlib.sha256(text.encode()).hexdigest(),text))

    def save_auto(self, state):
        with self.connect() as db:
            db.execute('INSERT INTO documents VALUES (?,?,?) ON CONFLICT(kind,key) DO UPDATE SET data=excluded.data',
                       ('auto','default',encode(state)))
            self._archive_tasks(db, state)

    def get_task(self, key):
        with self.connect() as db:
            row = db.execute('SELECT data FROM tasks WHERE job_id=?', (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def save_task(self, task):
        with self.connect() as db:
            db.execute('INSERT INTO tasks VALUES (?,?) ON CONFLICT(job_id) DO UPDATE SET data=excluded.data',
                       (task['job_id'],encode(task)))

    def backup(self, destination):
        """Consistent online backup, including changes still present in the WAL."""
        destination = Path(destination)
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
        target = sqlite3.connect(destination)
        try:
            with self.connect() as source:
                source.backup(target)
        finally:
            target.close()
