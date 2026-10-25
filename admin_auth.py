"""Administrator sessions and narrowly scoped API keys, independent of mailbox imports."""
import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

SCOPES = {'emails:read', 'inbox-links:read', 'mail:read'}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class AuthStore:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        import os
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS admin(id INTEGER PRIMARY KEY CHECK(id=1), username TEXT NOT NULL,
                    password_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL,
                    expires_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS api_keys(id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL, prefix TEXT NOT NULL, scopes TEXT NOT NULL,
                    created_at REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS login_failures(bucket TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS login_failures_bucket ON login_failures(bucket,created_at);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def validate_password(password):
        if not isinstance(password, str) or not 12 <= len(password) <= 256:
            raise ValueError('管理员密码须为 12–256 个字符')

    def create_admin(self, username, password):
        if not isinstance(username, str) or not 1 <= len(username.strip()) <= 64:
            raise ValueError('用户名须为 1–64 个字符')
        self.validate_password(password)
        encoded = generate_password_hash(password)
        with self.connect() as db:
            db.execute('INSERT INTO admin VALUES (1,?,?)', (username.strip(), encoded))

    def login(self, username, password, peer, days=30):
        if not isinstance(username, str) or not isinstance(password, str) or len(username)>64 or len(password)>256:
            return None
        now, bucket = self.clock(), digest(username + '\0' + peer)
        with self.connect() as db:
            # Serialize failed-attempt checks across worker threads.
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM login_failures WHERE created_at < ?', (now-900,))
            if db.execute('SELECT count(*) FROM login_failures WHERE bucket=?', (bucket,)).fetchone()[0] >= 8:
                raise ValueError('尝试次数过多，请 15 分钟后重试')
            admin = db.execute('SELECT * FROM admin WHERE id=1').fetchone()
            if not admin or not secrets.compare_digest(username.encode(), admin['username'].encode()) or not check_password_hash(admin['password_hash'], password):
                db.execute('INSERT INTO login_failures VALUES (?,?)', (bucket,now))
                return None
            db.execute('DELETE FROM login_failures WHERE bucket=?', (bucket,))
            db.execute('DELETE FROM sessions WHERE expires_at<=?', (now,))
            token, csrf, expires = secrets.token_urlsafe(32), secrets.token_urlsafe(32), now+days*86400
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (digest(token),csrf,expires))
        return token, {'username': username, 'csrf_token': csrf, 'expires_at': expires}

    def session(self, token):
        if not token or len(token)>256:
            return None
        with self.connect() as db:
            row = db.execute('SELECT a.username,s.csrf,s.expires_at FROM sessions s CROSS JOIN admin a '
                             'WHERE s.token_hash=? AND s.expires_at>? AND a.id=1', (digest(token),self.clock())).fetchone()
        return {'username':row['username'], 'csrf_token':row['csrf'], 'expires_at':row['expires_at']} if row else None

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(token),))

    def change_password(self, old, new):
        self.validate_password(new)
        if not isinstance(old,str) or len(old)>256:
            raise ValueError('原密码不正确')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT password_hash FROM admin WHERE id=1').fetchone()
            if not row or not check_password_hash(row[0], old):
                raise ValueError('原密码不正确')
            db.execute('UPDATE admin SET password_hash=? WHERE id=1', (generate_password_hash(new),))
            db.execute('DELETE FROM sessions')

    def reset_password(self, new):
        self.validate_password(new)
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM admin').fetchone():
                raise ValueError('请先初始化管理员')
            db.execute('UPDATE admin SET password_hash=?', (generate_password_hash(new),))
            db.execute('DELETE FROM sessions')

    def create_key(self, name, scopes):
        if not isinstance(name,str) or not 1<=len(name.strip())<=80:
            raise ValueError('密钥名称须为 1–80 个字符')
        if not isinstance(scopes,list) or not scopes or any(not isinstance(s,str) or s not in SCOPES for s in scopes):
            raise ValueError('请选择有效的公开 API 权限')
        token, key_id = 'hme_' + secrets.token_urlsafe(32), secrets.token_hex(12)
        with self.connect() as db:
            db.execute('INSERT INTO api_keys VALUES (?,?,?,?,?,?,0)',
                       (key_id,name.strip(),digest(token),token[:12],json.dumps(sorted(set(scopes))),self.clock()))
        return key_id, token

    def keys(self):
        with self.connect() as db:
            rows = db.execute('SELECT id,name,prefix,scopes,created_at,revoked FROM api_keys ORDER BY created_at DESC').fetchall()
        return [{**dict(r),'scopes':json.loads(r['scopes']), 'revoked':bool(r['revoked'])} for r in rows]

    def revoke_key(self, key_id):
        with self.connect() as db:
            return bool(db.execute('UPDATE api_keys SET revoked=1 WHERE id=?', (key_id,)).rowcount)

    def key_scopes(self, token):
        if not token or len(token)>256:
            return None
        with self.connect() as db:
            row = db.execute('SELECT scopes FROM api_keys WHERE token_hash=? AND revoked=0', (digest(token),)).fetchone()
        return set(json.loads(row[0])) if row else None
