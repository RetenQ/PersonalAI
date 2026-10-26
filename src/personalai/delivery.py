"""Durable, privacy-minimal update notifications; JPush is an optional adapter."""
import json
import threading
import time
from uuid import NAMESPACE_URL, uuid5
import httpx
import portalocker
from fastapi import Request
from pydantic import Field
from .models import StrictModel
from .model_client import SecretVault
from .store import StoreError, decode_event
from .user_files import check_path, atomic_write

ENDPOINT = 'https://api.jpush.cn/v3/push'


class PushConfig(StrictModel):
    enabled: bool = False
    app_key: str = Field(default='', max_length=100)
    secret: str | None = Field(default=None, max_length=500)


class Delivery:
    def __init__(self, app, store):
        self.app, self.store = app, store
        self.path = check_path(store.root, '.delivery/outbox.json')
        self.config_path = check_path(store.root, '.secrets/push.json')
        self.vault = SecretVault(store.root)
        self.vault.path = store.root / '.secrets/jpush-secret.bin'
        self.stop_event = threading.Event()
        self.thread = None
        self.transport = None
        self.last_error = ''

    def config(self):
        if not self.config_path.exists(): return {'enabled': False, 'app_key': ''}
        try: return json.loads(self.config_path.read_bytes())
        except (OSError, ValueError): raise StoreError('推送配置不可读。', 503)

    def save(self, value):
        if value.enabled and not value.app_key.strip():
            raise StoreError('启用推送需要 AppKey。', 422)
        if value.secret:
            self.vault.save(ENDPOINT + '#' + value.app_key, value.secret)
        if value.enabled and not self.vault.read(ENDPOINT + '#' + value.app_key):
            raise StoreError('请保存此 AppKey 对应的推送密钥。', 422)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self.config_path, json.dumps(value.model_dump(exclude={'secret'})).encode())
        self.config_path.chmod(0o600)
        return {'saved': True}

    def queue(self):
        if not self.path.exists(): return {'sequence': self.store.sequence, 'items': []}
        try: return json.loads(self.path.read_bytes())
        except (OSError, ValueError): raise StoreError('推送队列不可读，已停止发送。', 503)

    def persist(self, queue):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self.path, json.dumps(queue).encode())

    def tick(self):
        with portalocker.Lock(str(self.store.root / '.delivery.lock'), timeout=0):
            config = self.config()
            with self.store.mutex:
                self.store.reload(); self.store.require_healthy()
                queue = self.queue()
                if not config['enabled']:
                    self.persist({'sequence': self.store.sequence, 'items': []})
                    return
                devices = [c for c in self.app.state.access.read()['clients'].values()
                           if c['role'] == 'device' and not c['revoked'] and c['notifications'] and c['push_registration']]
                for path in self.store.files[queue['sequence']:]:
                    event = decode_event(path.read_bytes())
                    changed = any(p.status == 'pending' for p in event.proposals) or any(
                        e.kind in {'analysis', 'suggestion'} or e.kind in {'change', 'core/client-change', 'core/config-change'} and e.data.get('status') == 'pending'
                        or e.kind == 'scheduled_run' and e.data.get('status') == 'succeeded'
                        for e in getattr(event, 'entities', []))
                    if changed:
                        for client in devices:
                            identifier = str(uuid5(NAMESPACE_URL, f'{event.request_id}:{client["id"]}'))
                            if not any(i['id'] == identifier for i in queue['items']):
                                queue['items'].append({'id': identifier, 'client_id': client['id'], 'status': 'queued',
                                    'attempts': 0, 'created': time.time(), 'next_attempt': 0})
                queue['sequence'] = self.store.sequence
                queue['items'] = [i for i in queue['items'] if i['created'] > time.time() - 30 * 86400][-5000:]
                self.persist(queue)
            for item in queue['items']:
                if item['status'] == 'sending':
                    item['status'] = 'unknown'  # A crash must not cause an automatic duplicate send.
                if item['status'] != 'queued' or item['next_attempt'] > time.time(): continue
                client = self.app.state.access.read()['clients'].get(item['client_id'])
                if not client or client['revoked'] or not client['notifications'] or not client['push_registration']:
                    item['status'] = 'cancelled'; continue
                item.update(status='sending', attempts=item['attempts'] + 1)
                self.persist(queue)
                payload = {'platform': ['android'], 'audience': {'registration_id': [client['push_registration']]},
                    'notification': {'android': {'title': 'PersonalAI', 'alert': '有新的待确认事项或分析结果，请打开查看。',
                        'extras': {'event_id': item['id']}}}, 'options': {'time_to_live': 3600}}
                try:
                    key = self.vault.read(ENDPOINT + '#' + config['app_key'])
                    if not key: raise StoreError('推送密钥不可用。', 503)
                    with httpx.Client(timeout=15, follow_redirects=False, trust_env=False, transport=self.transport) as http:
                        response = http.post(ENDPOINT, auth=(config['app_key'], key), json=payload)
                    if response.status_code == 429 and item['attempts'] < 3:
                        item.update(status='queued', next_attempt=time.time() + 60 * item['attempts'])
                    else:
                        item['status'] = 'accepted' if response.status_code == 200 else 'failed'
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    item.update(status='queued' if item['attempts'] < 3 else 'failed', next_attempt=time.time() + 60 * item['attempts'])
                except httpx.HTTPError:
                    item['status'] = 'unknown'  # Read timeout: delivery may have happened; no auto retry.
                except Exception:
                    item['status'] = 'failed'
                self.persist(queue)
            self.persist(queue)

    def start(self):
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                try: self.tick(); self.last_error = ''
                except portalocker.exceptions.LockException: pass
                except Exception: self.last_error = '推送服务异常；原始记录不受影响。'
                self.stop_event.wait(10)
        self.thread = threading.Thread(target=loop, daemon=True, name='personalai-delivery')
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=1)


def register_delivery(app, store):
    delivery = Delivery(app, store)
    app.state.delivery = delivery
    def owner(request):
        if not app.state.access.owner_session(request.cookies.get('personalai_login', '')):
            raise StoreError('请先登录管理员。', 401)
    @app.get('/api/client-admin/push')
    def status(request: Request):
        owner(request)
        return {'config': delivery.config(), 'error': delivery.last_error,
                'items': [{k: v for k, v in i.items() if k != 'client_id'} for i in delivery.queue()['items'][-50:]],
                'notice': 'accepted 仅表示推送服务已接收，不代表手机已展示。'}
    @app.post('/api/client-admin/push')
    def configure(request: Request, payload: PushConfig):
        owner(request); return delivery.save(payload)
