"""Import legacy files without deleting them; verify exact values before deployment."""
import argparse
import hashlib
import json
from pathlib import Path
from storage import ROOT, Storage, encode


def migrate(root=ROOT, snapshot=None):
    root = Path(root).resolve()
    store = Storage(root / 'icloud_hme.sqlite3')
    results = root / 'results'
    store.import_accounts(root / 'accounts.json', results / 'account_sessions', root / 'cookies.json')
    store.import_links(results / 'inbox_links.json')
    store.import_emails(results / 'latest_emails.txt')
    for kind, path in [('auto', results / 'auto_registration.json'),
                       ('mail_cache', results / 'mail_cache.json'),
                       ('scheduler', root / 'scheduler_state.json'),
                       ('public_config', results / 'cloud_inbox_config.json')]:
        store.import_document(kind, path)

    sources = [root / 'accounts.json', root / 'scheduler_state.json', root / 'cookies.json']
    for folder in (results, root / 'logs'):
        if folder.exists():
            sources.extend(p for p in folder.rglob('*') if p.is_file() and p.suffix in ('.json','.txt','.log'))
    if snapshot: sources.append(Path(snapshot))

    def archive_sources(db):
        for path in sources:
            store.archive(db, path)
            if path.exists() and path.suffix == '.json':
                # Auxiliary historical exports are retained byte-for-byte even when not valid JSON.
                try: data = json.loads(path.read_text())
                except (ValueError, UnicodeError): continue
                if isinstance(data, dict) and data.get('id') and isinstance(data.get('results'), dict):
                    db.execute('INSERT OR IGNORE INTO documents VALUES (?,?,?)', ('creation_job',str(data['id']),encode(data)))
                if path.name.startswith('round_'):
                    db.execute('INSERT OR IGNORE INTO documents VALUES (?,?,?)', ('legacy_round',str(path.relative_to(root)),encode(data)))
        if snapshot:
            saved = json.loads(Path(snapshot).read_text())
            for key, data in saved.get('jobs', {}).items():
                db.execute('INSERT INTO documents VALUES (?,?,?) ON CONFLICT(kind,key) DO UPDATE SET data=excluded.data',
                           ('creation_job',key,encode(data)))
    store.import_once('legacy_source_archive', archive_sources)

    original = json.loads((root / 'accounts.json').read_text())['accounts'] if (root / 'accounts.json').exists() else {}
    accounts = store.load_accounts()
    assert set(accounts) == set(original), '账号集合不匹配'
    for key, meta in original.items():
        restored = dict(accounts[key]); cookies = restored.pop('cookies')
        expected_meta = {k:v for k,v in meta.items() if k != 'cookies'}
        assert restored == expected_meta, '账号元数据不匹配: ' + key
        session = results / 'account_sessions' / (key + '.json')
        expected_cookies = json.loads(session.read_text())['cookies'] if session.exists() else meta.get('cookies', {})
        assert cookies == expected_cookies, '账号会话不匹配: ' + key
    link_path = results / 'inbox_links.json'
    expected_links = json.loads(link_path.read_text()) if link_path.exists() else {}
    assert store.load_links() == expected_links, '收件链接或凭据不匹配'
    email_path = results / 'latest_emails.txt'
    raw_emails = []
    for line in email_path.read_text().splitlines() if email_path.exists() else []:
        if line.strip() and '@' in line:
            parts = line.strip().split('\t'); raw_emails.append((parts[0],parts[1] if len(parts)>1 else ''))
    assert [(r['email'],r['account_id']) for r in store.emails()] == raw_emails, '邮箱记录顺序或数量不匹配'
    auto_path = results / 'auto_registration.json'
    expected_auto = json.loads(auto_path.read_text()) if auto_path.exists() else None
    assert store.read_document('auto') == expected_auto, '任务配置、倒计时、日志或历史不匹配'
    with store.connect() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        for path in sources:
            if path.exists():
                row = db.execute('SELECT sha256,content FROM legacy_sources WHERE path=?',(str(path.resolve()),)).fetchone()
                assert row and row[0] == hashlib.sha256(path.read_bytes()).hexdigest() and row[1] == path.read_bytes(), '原始归档不匹配: ' + str(path)
        counts = {table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in
                  ('accounts','account_sessions','inbox_links','email_records','tasks','task_logs','legacy_sources')}
    return {'database':str(store.path), 'verified_exact_match':True,'integrity_check':'ok','counts':counts}


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--snapshot',type=Path)
    args=parser.parse_args()
    print(json.dumps(migrate(args.root,args.snapshot),ensure_ascii=False,indent=2))
