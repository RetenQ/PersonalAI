"""Single-owner web authentication and independently revocable client grants.

Credentials are random opaque tokens. Only hashes are persisted. No grant is
restored from an event backup. This is deliberately a single-process service.
"""
import hashlib
import json
import secrets
import time
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4

import portalocker

from .store import StoreError
from .user_files import atomic_write, check_path

actor_context = ContextVar('personalai_actor', default=None)
RESOURCES = {'goals', 'tasks', 'records', 'logs', 'checkins', 'reports', 'pending', 'reminders', 'settings', 'profile'}
AGENT_SCOPES = {f'read:{x}' for x in RESOURCES - {'settings'}} | {'write:records', 'propose'}
DEVICE_SCOPES = {f'read:{x}' for x in RESOURCES} | {'write:records', 'propose', 'confirm', 'settings', 'reminders', 'analysis'}


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Access:
    def __init__(self, store):
        self.store = store
        self.path = check_path(store.root, '.secrets/access.json')
        self.failures = {}
        self.clock = time.time

    def read(self):
        if not self.path.exists():
            return {'owner': None, 'sessions': {}, 'clients': {}, 'tokens': {}, 'pairings': {}}
        try:
            value = json.loads(self.path.read_bytes())
            if not all(k in value for k in ['owner', 'sessions', 'clients', 'tokens', 'pairings']):
                raise ValueError()
            return value
        except (OSError, ValueError):
            raise StoreError('身份资料不可读取，已拒绝访问。', 503)

    def change(self, function):
        with self.store.mutex, portalocker.Lock(str(self.store.root / '.access.lock'), timeout=10):
            data = self.read()
            result = function(data)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(self.path, json.dumps(data).encode())
            self.path.chmod(0o600)
            return result

    def configured(self):
        return bool(self.read()['owner'])

    def initialize(self, password):
        if len(password) < 12 or len(password) > 256:
            raise StoreError('管理员密码需为 12–256 个字符。', 422)
        salt = secrets.token_bytes(16)
        password_hash = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex()
        def apply(data):
            if data['owner']:
                raise StoreError('管理员已初始化；不允许覆盖。', 409)
            data['owner'] = {'salt': salt.hex(), 'hash': password_hash}
        self.change(apply)

    def throttle(self, key, limit=10):
        now = self.clock()
        self.failures = {k: v for k, v in self.failures.items() if v[0] > now - 60}
        start, count = self.failures.get(key, (now, 0))
        if count >= limit:
            raise StoreError('请求过于频繁，请一分钟后重试。', 429)
        self.failures[key] = (start, count + 1)

    def login(self, password):
        self.throttle('login')
        def apply(data):
            owner = data['owner']
            if not owner:
                raise StoreError('请先在服务器初始化管理员。', 503)
            candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(owner['salt']), n=16384, r=8, p=1).hex()
            if not secrets.compare_digest(candidate, owner['hash']):
                raise StoreError('登录失败。', 401)
            token = secrets.token_urlsafe(40)
            data['sessions'] = {k: v for k, v in data['sessions'].items() if v > self.clock()}
            data['sessions'][hashed(token)] = self.clock() + 12 * 3600
            return token
        return self.change(apply)

    def owner_session(self, token):
        return bool(token) and self.read()['sessions'].get(hashed(token), 0) > self.clock()

    def logout(self, token):
        self.change(lambda d: d['sessions'].pop(hashed(token), None))

    def pair(self, name):
        self.throttle('pair', 5)
        identifier, verifier = str(uuid4()), secrets.token_urlsafe(40)
        code = ''.join(secrets.choice('0123456789') for _ in range(8))
        def apply(data):
            if not data['owner']:
                raise StoreError('管理员尚未初始化。', 503)
            data['pairings'] = {k: v for k, v in data['pairings'].items() if v['expires'] > self.clock()}
            while any(p['code'] == code for p in data['pairings'].values()):
                raise StoreError('配对码冲突，请重新申请。', 409)
            data['pairings'][identifier] = {'name': name, 'verifier': hashed(verifier), 'code': code,
                                           'expires': self.clock() + 600, 'approved': False}
            return {'pairing_id': identifier, 'poll_secret': verifier, 'code': code, 'expires_in': 600}
        return self.change(apply)

    def approve(self, code):
        def apply(data):
            item = next((p for p in data['pairings'].values() if p['code'] == code and p['expires'] > self.clock()), None)
            if not item:
                raise StoreError('配对码无效或已过期。', 404)
            item['approved'] = True
            return {'approved': True, 'name': item['name']}
        return self.change(apply)

    def issue(self, data, client):
        data['tokens'] = {k: v for k, v in data['tokens'].items() if v['expires'] > self.clock()}
        access, refresh = secrets.token_urlsafe(40), secrets.token_urlsafe(48)
        data['tokens'][hashed(access)] = {'client_id': client['id'], 'expires': self.clock() + 900, 'purpose': 'access'}
        data['tokens'][hashed(refresh)] = {'client_id': client['id'], 'expires': self.clock() + 30 * 86400, 'purpose': 'refresh'}
        return {'access_token': access, 'refresh_token': refresh, 'expires_in': 900, 'client_id': client['id']}

    def poll(self, identifier, verifier):
        def apply(data):
            item = data['pairings'].get(identifier)
            if not item or item['expires'] <= self.clock() or not secrets.compare_digest(item['verifier'], hashed(verifier)):
                raise StoreError('配对失效，请重新开始。', 401)
            if not item['approved']:
                return {'status': 'pending'}
            key = str(uuid4())
            client = {'id': key, 'name': item['name'], 'role': 'device', 'scopes': sorted(DEVICE_SCOPES),
                      'revoked': False, 'notifications': not any(c['role'] == 'device' and not c['revoked'] for c in data['clients'].values()),
                      'push_registration': None, 'created_at': self.clock(), 'last_seen': None}
            data['clients'][key] = client
            del data['pairings'][identifier]
            return {'status': 'paired', **self.issue(data, client)}
        return self.change(apply)

    def refresh(self, token):
        def apply(data):
            entry = data['tokens'].get(hashed(token))
            client = data['clients'].get(entry['client_id']) if entry else None
            if not entry or entry['purpose'] != 'refresh' or entry['expires'] <= self.clock() or not client or client['revoked']:
                raise StoreError('设备授权已失效，请重新配对。', 401)
            del data['tokens'][hashed(token)]
            return self.issue(data, client)
        return self.change(apply)

    def agent(self, name, scopes):
        if not scopes or not set(scopes) <= AGENT_SCOPES:
            raise StoreError('Agent 权限范围无效。', 422)
        def apply(data):
            key, token = str(uuid4()), secrets.token_urlsafe(48)
            data['clients'][key] = {'id': key, 'name': name, 'role': 'agent', 'scopes': sorted(set(scopes)),
                'revoked': False, 'notifications': False, 'push_registration': None, 'created_at': self.clock(), 'last_seen': None}
            data['tokens'][hashed(token)] = {'client_id': key, 'expires': self.clock() + 90 * 86400, 'purpose': 'access'}
            return {'client_id': key, 'token': token, 'expires_in': 90 * 86400}
        return self.change(apply)

    def authenticate(self, token):
        data = self.read()
        entry = data['tokens'].get(hashed(token))
        client = data['clients'].get(entry['client_id']) if entry else None
        if not entry or entry['purpose'] != 'access' or entry['expires'] <= self.clock() or not client or client['revoked']:
            raise StoreError('访问授权失效。', 401)
        return client.copy()

    def revoke(self, identifier):
        def apply(data):
            client = data['clients'].get(identifier)
            if not client:
                raise StoreError('未找到设备或 Agent。', 404)
            client.update(revoked=True, push_registration=None)
            data['tokens'] = {k: v for k, v in data['tokens'].items() if v['client_id'] != identifier}
            return {'revoked': True}
        return self.change(apply)

    def update_device(self, identifier, **updates):
        def apply(data):
            client = data['clients'].get(identifier)
            if not client or client['revoked'] or client['role'] != 'device':
                raise StoreError('设备不可用。', 401)
            client.update(updates, last_seen=self.clock())
            return {'saved': True}
        return self.change(apply)

    def listing(self):
        data = self.read()
        return {'clients': [{k: v for k, v in c.items() if k != 'push_registration'} for c in data['clients'].values()],
                'pairings': [{'code': p['code'], 'name': p['name'], 'expires': p['expires'], 'approved': p['approved']}
                             for p in data['pairings'].values() if p['expires'] > self.clock()]}
