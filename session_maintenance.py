"""独立的 iCloud 会话保活，不控制注册、分裂或同步任务。"""
import time
import random


class SessionMaintenance:
    def __init__(self, manager, emit, interval=None, clock=time.monotonic, random_interval=random.uniform):
        self.manager, self.emit, self.interval, self.clock = manager, emit, interval, clock
        self.random_interval = random_interval
        self.pending = {}

    def delay(self):
        # 每轮重新抽取 10–20 分钟；固定间隔仅供测试注入。
        return self.interval if self.interval is not None else self.random_interval(600, 1200)

    def tick(self):
        now = self.clock()
        accounts = self.manager.list_accounts()
        self.pending = {key: value for key, value in self.pending.items()
                        if any(a['id'] == key for a in accounts)}
        for account in accounts:
            key = account['id']
            if not account.get('cookies') or account.get('session_requires_login'):
                continue
            due, failures = self.pending.get(key, (0, 0))
            if now < due:
                continue
            try:
                result = self.manager.keep_session_alive(key)
            except Exception:
                # 一个账号故障不能结束其他账号的保活。
                result = {'status': 'error'}
            if result.get('status') == 'active':
                if failures:
                    self.emit('info', f'账号会话已恢复 [{account.get("name", key)}]')
                self.pending[key] = (self.clock() + self.delay(), 0)
            else:
                failures += 1
                delay = min(self.delay() * 2 ** min(failures - 1, 4), 3600)
                self.pending[key] = (self.clock() + delay, failures)
                if result.get('session_requires_login'):
                    self.emit('warn', f'账号需要重新登录 iCloud 并更新 Cookie [{account.get("name", key)}]')
                elif failures == 1:
                    self.emit('warn', f'账号会话保活暂时失败，稍后自动重试 [{account.get("name", key)}]')

    def run(self, stop_event):
        while not stop_event.is_set():
            self.tick()
            if stop_event.wait(30):
                break
