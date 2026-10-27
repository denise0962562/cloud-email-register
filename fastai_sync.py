"""Asynchronous, idempotent iCloud-pool imports into gpt-auto-register."""
import copy
import hashlib
import json
import secrets
import threading
import time
from urllib.parse import urlsplit, urlunsplit
import requests
from inbox_links import is_ready
from email_catalog import stamp

DEFAULTS = {'api_url': 'http://127.0.0.1:8766/api/import', 'enabled': False, 'interval_minutes': 60, 'batch_size': 50, 'include_synced': False, 'api_token': ''}


class ImportErrorDetail(RuntimeError):
    def __init__(self, message, stop=False):
        super().__init__(message)
        self.stop = stop


def normalize_api_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError('请填写有效的 FastAI 接口地址')
    try:
        u = urlsplit(value.strip())
        if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError()
        _ = u.port
    except ValueError:
        raise ValueError('接口须为 http(s) 地址，不能包含用户名、密码、查询参数或片段') from None
    path = u.path.rstrip('/') or '/api/import'
    return urlunsplit((u.scheme.lower(),u.netloc,path,'',''))


class FastAISync:
    def __init__(self, storage, http_factory=requests.Session, clock=time.time):
        self.storage, self.http_factory, self.clock = storage, http_factory, clock
        self.lock = threading.RLock()
        self.wake, self.stop_event = threading.Event(), threading.Event()
        self.thread = None
        self.work_thread = None
        self.cancel_event = threading.Event()
        state = storage.read_document('fastai_sync_state') or {}
        self.config = {**DEFAULTS, **state.get('config', {})}
        # 发送账号固定只发送未同步成功的记录，兼容旧配置但不启用重复发送。
        self.config['include_synced'] = False
        self.next_run = state.get('next_run')
        self.active = state.get('active')
        self.latest = state.get('latest')
        self.logs = state.get('logs', [])
        if self.active:
            job = storage.read_document('fastai_sync_job', self.active)
            if job and job['status'] == 'running':
                with storage.connect() as db:
                    confirmed = {email for email, in db.execute(
                        "SELECT email FROM fastai_sync WHERE job_id=? AND status='synced'", (self.active,))}
                for item in job['items']:
                    if item['status'] == 'running':
                        if item['email'] in confirmed:
                            item.update(status='synced',action='已确认',error='')
                        else:
                            item.update(status='failed',error='服务重启，请重试未同步邮箱')
                job['succeeded'] = sum(item['status']=='synced' for item in job['items'])
                job['failed'] = sum(item['status']=='failed' for item in job['items'])
                job['processed'] = job['succeeded'] + job['failed']
                job.update(status='interrupted',finished_at=clock(),message='服务重启，已成功记录保留，未完成的邮箱可重新同步')
                self._save_job(job)
                with storage.connect() as db:
                    db.execute("UPDATE fastai_sync SET status='failed',last_error=? WHERE job_id=? AND status='running'",
                               ('服务重启，请重试未同步邮箱',self.active))
            self.active = None
            if self.config['enabled']: self.next_run = clock() + self.config['interval_minutes'] * 60
        if self.config['enabled'] and self.next_run is None:
            self.next_run = clock() + self.config['interval_minutes'] * 60
        self._persist_state()

    def _persist_state(self):
        self.storage.write_document('fastai_sync_state', {'config':self.config,'next_run':self.next_run,
                                    'active':self.active,'latest':self.latest,'logs':self.logs})

    def _log(self, level, message):
        self.logs.append({'time':self.clock(),'level':level,'message':message})
        self.logs = self.logs[-300:]

    def _save_job(self, job):
        self.storage.write_document('fastai_sync_job',job,job['id'])

    def records(self, api_url=None):
        with self.storage.connect() as db:
            return {email: {'inbox_url':url,'status':status,'synced_at':stamp,'error':error}
                    for email,url,status,stamp,error in db.execute(
                        'SELECT email,inbox_url,status,synced_at,last_error FROM fastai_sync WHERE api_url=?',
                        (api_url or self.config['api_url'],))}

    def pending(self, api_url=None, include_synced=False):
        links, states, rows = self.storage.load_links(), self.records(api_url), []
        unique = {}
        for index, source in enumerate(self.storage.emails()):
            unique[source['email'].lower()] = (index, source)
        # 先按注册时间从早到晚排列，再截取本轮数量；相同时间按写入顺序，缺失时间排最后。
        ordered = sorted(unique.values(), key=lambda item: (
            stamp(item[1].get('created_at')) is None,
            stamp(item[1].get('created_at')) or 0, item[0]))
        for _, source in ordered:
            email = source['email'].lower()
            link, record = links.get(email,{}), states.get(email,{})
            if not is_ready(link): continue
            url = link['inbox_url']
            if not include_synced and record.get('status') == 'synced' and record.get('inbox_url') == url: continue
            rows.append({'email':email,'inbox_url':url})
        return rows

    def snapshot(self):
        with self.lock:
            job = self.storage.read_document('fastai_sync_job',self.active or self.latest) if (self.active or self.latest) else None
            with self.storage.connect() as db:
                history = [json.loads(row[0]) for row in db.execute(
                    "SELECT data FROM documents WHERE kind='fastai_sync_job' ORDER BY json_extract(data,'$.started_at') DESC,rowid DESC LIMIT 40")]
            history = [{k:v for k,v in entry.items() if k != 'items'} for entry in history]
            # 对外仅返回凭据状态，避免轮询接口回传 Token。
            public_config = {k:v for k,v in self.config.items() if k != 'api_token'}
            public_config['api_token_configured'] = bool(self.config['api_token'])
            return {'history':history,'logs':copy.deepcopy(self.logs),'current':job if self.active else None,'config':public_config,'next_run':self.next_run,
                    'server_time':self.clock(),'pending':len(self.pending()),
                    'eligible':len(self.pending()),'job':job}

    def configure(self, data):
        with self.lock:
            if not isinstance(data,dict) or set(data) - set(DEFAULTS): raise ValueError('同步配置字段无效')
            config = {**self.config, **data}
            config['api_url'] = normalize_api_url(config['api_url'])
            token = config['api_token']
            if not isinstance(token, str) or len(token) > 8192:
                raise ValueError('Token 必须是长度不超过 8192 的字符串')
            token = token.strip()
            if token.lower().startswith('bearer '):
                token = token[7:].strip()
            if token and any(ord(char) < 33 or ord(char) > 126 for char in token):
                raise ValueError('Token 不能包含空格、换行或非 ASCII 字符')
            config['api_token'] = token
            if type(config['enabled']) is not bool: raise ValueError('自动同步开关必须为布尔值')
            if type(config['interval_minutes']) is not int or not 1 <= config['interval_minutes'] <= 10080:
                raise ValueError('同步间隔应为 1–10080 分钟的整数')
            if type(config['batch_size']) is not int or not 1 <= config['batch_size'] <= 10000:
                raise ValueError('每轮同步数量应为 1–10000 的整数')
            if type(config['include_synced']) is not bool: raise ValueError('包含已同步开关必须为布尔值')
            config['include_synced'] = False
            self.config = config
            self._log('info','配置已保存：自动同步%s，每 %d 分钟，每轮最多 %d 个' % ('开启' if config['enabled'] else '关闭',config['interval_minutes'],config['batch_size']))
            if not config['enabled']: self.next_run = None
            elif self.next_run is None: self.next_run = self.clock() + config['interval_minutes'] * 60
            self._persist_state()
            self.wake.set()
            return self.snapshot()

    def get_job(self, key):
        with self.lock:
            return self.storage.read_document('fastai_sync_job',key)

    def start(self, scheduled=False, emails=None, all_pending=False, selected_only=False, trigger=None):
        with self.lock:
            if emails is not None and (not isinstance(emails,list) or not emails or any(not isinstance(e,str) for e in emails)):
                raise ValueError('邮箱列表必须是非空字符串列表')
            if type(all_pending) is not bool: raise ValueError('同步全部参数必须为布尔值')
            if self.active:
                if selected_only: raise RuntimeError('已有 FastAI 同步任务运行中，请等待完成')
                return self.get_job(self.active)
            endpoint = self.config['api_url']
            pending = self.pending(endpoint,include_synced=selected_only)
            if emails is not None:
                selected={e.lower() for e in emails}
                pending=[row for row in pending if row['email'] in selected]
            if not all_pending and not selected_only: pending = pending[:self.config['batch_size']]
            self.cancel_event.clear()
            job = {'id':secrets.token_hex(12),'status':'running' if pending else 'completed',
                   'api_url':endpoint,'include_synced':selected_only,'trigger':trigger or ('scheduled' if scheduled else 'manual'),
                   'started_at':self.clock(),'finished_at':None if pending else self.clock(),
                   'total':len(pending),'processed':0,'succeeded':0,'failed':0,
                   'message':'正在同步' if pending else '没有可同步的未同步邮箱',
                   'items':[{'email':r['email'],'status':'pending','error':''} for r in pending]}
            self._log('info',('注册后同步' if trigger == 'registration' else '分裂后同步' if trigger == 'split' else '自动' if scheduled else '手动')+'任务启动，计划同步 %d 个邮箱' % len(pending))
            self.latest = job['id']
            self.active = job['id'] if pending else None
            if scheduled: self.next_run = None
            if not pending and self.config['enabled'] and scheduled:
                self.next_run = self.clock() + self.config['interval_minutes'] * 60
            self._save_job(job)
            self._persist_state()
            response = copy.deepcopy(job)
            if pending:
                self.work_thread = threading.Thread(target=self._run,args=(job,pending,self.config['api_token']),daemon=True)
                self.work_thread.start()
            return response

    def enqueue_registration(self, emails, source_job):
        return self.enqueue_split(emails, source_job, trigger='registration')

    def handoff_status(self, source_job):
        """只返回该轮交接的邮箱状态，供注册日志查询，不暴露配置凭据。"""
        with self.lock, self.storage.connect() as db:
            entries = [json.loads(row[0]) for row in db.execute(
                "SELECT data FROM documents WHERE kind='split_fastai_outbox' AND json_extract(data,'$.source_job')=?",
                (source_job,))]
            for entry in entries:
                if entry.get('job_id'):
                    job = self.get_job(entry['job_id']) or {}
                    item = next((i for i in job.get('items', []) if i['email'] == entry['email']), {})
                    if item.get('status') in ('synced', 'failed'):
                        entry.update(status=item['status'], error=item.get('error', ''))
            return entries

    def enqueue_split(self, emails, source_job, *, trigger='split'):
        """持久化交接成功的分裂邮箱；忙时等待，重复交接不会重复入队。"""
        with self.lock:
            endpoint = self.config['api_url']
            eligible = {r['email']: r for r in self.pending(endpoint)}
            with self.storage.connect() as db:
                for email in dict.fromkeys(e.lower() for e in emails):
                    if email not in eligible:
                        continue
                    key = hashlib.sha256((source_job + '\n' + endpoint + '\n' + email).encode()).hexdigest()
                    entry = {**eligible[email], 'api_url': endpoint, 'source_job': source_job,
                             'status': 'pending', 'created_at': self.clock(), 'trigger': trigger}
                    db.execute('INSERT OR IGNORE INTO documents(kind,key,data) VALUES (?,?,?)',
                               ('split_fastai_outbox', key, json.dumps(entry)))
            self.wake.set()

    def _dispatch_split(self):
        # 此队列与周期同步共用单一工作线程，不因已有同步任务而漏掉邮箱。
        with self.storage.connect() as db:
            entries = [(key, json.loads(data)) for key, data in db.execute(
                "SELECT key,data FROM documents WHERE kind='split_fastai_outbox' "
                "AND json_extract(data,'$.status') IN ('pending','submitted') ORDER BY rowid")]
        records = {}
        pending = []
        for key, entry in entries:
            endpoint = entry['api_url']
            if endpoint not in records:
                records[endpoint] = self.records(endpoint)
            state = records[endpoint].get(entry['email'], {})
            confirmed = state.get('status') == 'synced' and state.get('inbox_url') == entry['inbox_url']
            if confirmed:
                entry['status'] = 'synced'
            elif entry['status'] == 'submitted':
                job = self.get_job(entry['job_id']) or {}
                if job.get('status') == 'running' and self.active == entry['job_id']:
                    continue
                entry['status'] = 'failed'
                self._set_status(entry, {'id': entry['job_id'], 'api_url': endpoint}, 'failed',
                                 '后台发送未完成，请在邮箱列表重试')
            elif endpoint == self.config['api_url']:
                pending.append((key, entry))
                continue
            else:
                continue  # 接口切换后不擅自将已排队的邮箱发往另一目标。
            self.storage.write_document('split_fastai_outbox', entry, key)
        if self.active or not pending:
            return
        eligible = {row['email']: row for row in self.pending()}
        selected = []
        # 按来源分组，注册完成后的任务使用独立日志标签。
        trigger = pending[0][1].get('trigger', 'split') if pending else 'split'
        for key, entry in pending[:10000]:
            if entry.get('trigger', 'split') != trigger:
                continue
            if entry['email'] not in eligible or eligible[entry['email']]['inbox_url'] != entry['inbox_url']:
                entry['status'] = 'skipped'
                self.storage.write_document('split_fastai_outbox', entry, key)
            else:
                selected.append((key, entry))
        if selected:
            job = self.start(emails=list(dict.fromkeys(e['email'] for _, e in selected)),
                             selected_only=True, trigger=trigger)
            for key, entry in selected:
                entry.update(status='submitted', job_id=job['id'])
                self.storage.write_document('split_fastai_outbox', entry, key)

    def cancel(self, job_id):
        with self.lock:
            if self.active != job_id: return False
            self.cancel_event.set()
            return True

    def _set_status(self, row, job, status, error=''):
        with self.storage.connect() as db:
            # A failed resend must retain the previous confirmation for this exact destination/link.
            if status != 'synced' and db.execute(
                "SELECT 1 FROM fastai_sync WHERE email=? AND api_url=? AND inbox_url=? AND status='synced'",
                (row['email'],job['api_url'],row['inbox_url'])).fetchone():
                return
            db.execute('''INSERT INTO fastai_sync VALUES (?,?,?,?,?,?,?) ON CONFLICT(email,api_url)
                DO UPDATE SET inbox_url=excluded.inbox_url,status=excluded.status,synced_at=excluded.synced_at,
                last_error=excluded.last_error,job_id=excluded.job_id''',
                (row['email'],job['api_url'],row['inbox_url'],status,
                 self.clock() if status=='synced' else None,error,job['id']))

    @staticmethod
    def _import(http, endpoint, row, api_token=''):
        try:
            headers = {'Authorization': 'Bearer ' + api_token} if api_token else {}
            # 禁止跳转，避免目标端点将导入数据或凭据带往其他地址。
            response = http.post(endpoint,headers=headers,allow_redirects=False,json={'kind':'icloud_relay','text':row['email']+'----'+row['inbox_url']},timeout=(5,20))
        except requests.RequestException:
            raise ImportErrorDetail('无法确认导入结果：连接失败或超时，重试会由目标接口去重',stop=True) from None
        if response.status_code != 200:
            stop = response.status_code in (401,403,404,429) or response.status_code >= 500
            raise ImportErrorDetail('导入接口返回 HTTP '+str(response.status_code),stop=stop)
        try: data = response.json()
        except ValueError: raise ImportErrorDetail('导入接口未返回有效 JSON',stop=True) from None
        if not isinstance(data,dict): raise ImportErrorDetail('导入接口响应格式无效',stop=True)
        counts = [data.get(k) for k in ('inserted','updated','skipped')]
        if data.get('ok') is not True or data.get('parsed') != 1 or any(type(v) is not int or v<0 for v in counts) or sum(counts) != 1:
            raise ImportErrorDetail('导入接口未确认本条邮箱导入成功')
        return '新增' if counts[0] else '更新' if counts[1] else '已存在'

    def _run(self, job, rows, api_token=''):
        http = self.http_factory()
        http.trust_env = False
        try:
            for row,item in zip(rows,job['items']):
                if self.cancel_event.is_set(): break
                with self.lock:
                    item['status']='running'
                    self._set_status(row,job,'running')
                    job['message']='正在同步 '+row['email']
                    self._save_job(job)
                stop = False
                try:
                    action = self._import(http,job['api_url'],row,api_token)
                    with self.lock:
                        self._set_status(row,job,'synced')
                        item.update(status='synced',action=action)
                        job['succeeded']+=1
                except ImportErrorDetail as error:
                    with self.lock:
                        self._set_status(row,job,'failed',str(error))
                        item.update(status='failed',error=str(error))
                        job['failed']+=1
                    stop = error.stop
                with self.lock:
                    item['finished_at']=self.clock()
                    job['processed']+=1
                    self._log('info' if item['status']=='synced' else 'error',row['email']+'：'+(item.get('action','同步成功') if item['status']=='synced' else item['error']))
                    self._save_job(job)
                    self._persist_state()
                if stop: break
            job['status']='cancelled' if self.cancel_event.is_set() else ('completed' if job['processed']==job['total'] else 'failed')
            job['message']='同步结束：成功 %d，失败 %d，未尝试 %d' % (job['succeeded'],job['failed'],job['total']-job['processed'])
        except Exception:
            job.update(status='failed',message='同步任务异常中止；已成功记录保留，可重试未同步邮箱')
        finally:
            http.close()
            with self.lock:
                self._log('info' if job['status']=='completed' and not job['failed'] else 'error',job['message'])
                job['finished_at']=self.clock()
                self._save_job(job)
                self.active=None
                if self.config['enabled'] and job['trigger'] not in ('split', 'registration') and (job['trigger']=='scheduled' or job['succeeded']>0 or self.next_run is None):
                    self.next_run=self.clock()+self.config['interval_minutes']*60
                self._persist_state()
                self.wake.set()

    def tick(self):
        with self.lock:
            self._dispatch_split()
            if self.config['enabled'] and self.next_run is not None and self.clock()>=self.next_run and not self.active:
                self.start(scheduled=True)

    def start_scheduler(self):
        if self.thread and self.thread.is_alive(): return
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                self.wake.clear()
                try: self.tick()
                except Exception:
                    with self.lock:
                        self.next_run=self.clock()+self.config['interval_minutes']*60
                        self._persist_state()
                self.wake.wait(1)
        self.thread=threading.Thread(target=loop,daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        self.wake.set()
