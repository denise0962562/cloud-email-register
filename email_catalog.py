"""SQL-backed mailbox paging and explicit/snapshot-based bulk selections."""
import json
from datetime import datetime, timezone
import math


def filters(data):
    if not isinstance(data, dict):
        raise ValueError('筛选条件无效')
    result = {key: data.get(key, default) for key, default in
              [('q',''),('account_id','all'),('address_type','all'),('sort','created_at'),('direction','desc')]}
    if any(not isinstance(value,str) for value in result.values()):
        raise ValueError('筛选条件必须是文本')
    result['q'] = result['q'].strip()
    if len(result['q']) > 200 or result['address_type'] not in ('all','source','split'):
        raise ValueError('关键词或地址类型无效')
    if result['sort'] not in ('created_at','fastai_synced_at') or result['direction'] not in ('asc','desc'):
        raise ValueError('排序条件无效')
    return result


def stamp(value):
    try:
        if value is None or value == '' or isinstance(value,bool): return None
        try:
            number = float(value)
            return (number / 1000 if number > 1e11 else number) if math.isfinite(number) and number > 0 else None
        except (TypeError,ValueError):
            date = datetime.fromisoformat(str(value).replace('Z','+00:00'))
            return (date if date.tzinfo else date.replace(tzinfo=timezone.utc)).timestamp()
    except (ValueError,TypeError,OverflowError):
        return None


BASE = '''WITH latest AS (SELECT MAX(seq) AS seq FROM email_records GROUP BY lower(email))
 SELECT lower(e.email) AS email,e.account_id,e.created_at,e.seq,l.data AS link_data,
 s.status AS sync_status,s.synced_at,s.last_error AS sync_error
 FROM latest JOIN email_records e ON e.seq=latest.seq
 LEFT JOIN inbox_links l ON l.email=lower(e.email)
 LEFT JOIN fastai_sync s ON s.email=lower(e.email) AND s.api_url=?
 AND s.inbox_url=json_extract(l.data,'$.inbox_url')'''


def where(f):
    clauses, args = [], []
    if f['q']:
        clauses.append('instr(lower(e.email),lower(?))>0'); args.append(f['q'])
    if f['account_id'] not in ('all',''):
        clauses.append('e.account_id=?'); args.append(f['account_id'])
    if f['address_type'] != 'all':
        clauses.append("instr(substr(e.email,1,instr(e.email,'@')-1),'+')" + ('>0' if f['address_type']=='split' else '=0'))
    return clauses,args


def page(store, query, api_url):
    f = filters(dict(query))
    try:
        number, size = int(query.get('page',1)), int(query.get('page_size',50))
    except (TypeError,ValueError): raise ValueError('分页参数必须是整数')
    if number < 1 or not 1 <= size <= 200: raise ValueError('页码必须大于 0，每页数量为 1–200')
    clauses,args = where(f)
    sql = BASE + (' WHERE '+' AND '.join(clauses) if clauses else '')
    with store.connect() as db:
        db.create_function('mail_stamp',1,stamp)
        db.execute('BEGIN')
        total = db.execute('SELECT count(*) FROM ('+sql+')',[api_url]+args).fetchone()[0]
        pages = max(1,(total+size-1)//size); number = min(number,pages)
        key = "mail_stamp(e.created_at)" if f['sort']=='created_at' else "CASE WHEN s.status='synced' THEN s.synced_at END"
        ordered = sql + f' ORDER BY ({key}) IS NULL, {key} {f["direction"]}, e.seq DESC'
        cursor = db.execute(ordered+' LIMIT ? OFFSET ?',[api_url]+args+[size,(number-1)*size])
        rows = [dict(zip([c[0] for c in cursor.description],r)) for r in cursor]
        counts = dict(db.execute('SELECT e.account_id,count(*) FROM email_records e JOIN '
                                 '(SELECT max(seq) seq FROM email_records GROUP BY lower(email)) latest '
                                 'ON e.seq=latest.seq GROUP BY e.account_id'))
        ceiling = db.execute('SELECT COALESCE(max(seq),0) FROM email_records').fetchone()[0]
    return {'rows':rows,'total':total,'count':total,'page':number,'page_size':size,'pages':pages,
            'all_count':sum(counts.values()),'account_counts':counts,'snapshot_max_seq':ceiling}


def selected(db, selection):
    if not isinstance(selection,dict): raise ValueError('请选择邮箱')
    sql = 'SELECT lower(e.email) AS email,e.account_id,e.seq FROM email_records e WHERE e.seq IN (SELECT max(seq) FROM email_records GROUP BY lower(email))'
    args = []
    if selection.get('all_matching') is True:
        if not isinstance(selection.get('filters'),dict) or type(selection.get('through_seq')) is not int or not 0 <= selection['through_seq'] <= 2**63-1:
            raise ValueError('全选范围无效，请重新全选')
        clauses,args = where(filters(selection['filters']))
        sql += ' AND e.seq<=?'; args = [selection['through_seq']]+args
        if clauses: sql += ' AND '+' AND '.join(clauses)
        excluded = selection.get('excluded',[])
        if not isinstance(excluded,list) or any(not isinstance(x,str) for x in excluded): raise ValueError('排除列表无效')
        excluded = {x.lower() for x in excluded}
        return [dict(zip(('email','account_id','seq'),r)) for r in db.execute(sql,args) if r[0] not in excluded]
    emails = selection.get('emails')
    if not isinstance(emails,list) or not emails or any(not isinstance(x,str) for x in emails):
        raise ValueError('请选择邮箱')
    # JSON table avoids SQLite's bound-variable limit for large selections.
    sql += ' AND lower(e.email) IN (SELECT value FROM json_each(?))'
    return [dict(zip(('email','account_id','seq'),r)) for r in db.execute(sql,(json.dumps(list({x.lower() for x in emails})),))]
