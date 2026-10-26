"""Isolated owner/device/agent contract and cross-client conflict tests."""
import json
from datetime import datetime
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from personalai.app import create_app
from personalai.backup import export_backup, restore_backup
from personalai.models import TZ
from personalai.model_client import SecretVault
from personalai.reminders import occurrences, Reminder
from personalai.store import StoreError

P = '/api/clients/v1'

@pytest.fixture
def env(tmp_path):
    app = create_app(tmp_path / 'data', port=8765)
    app.state.access.initialize('test-owner-password-123')
    owner = TestClient(app, base_url='http://127.0.0.1:8765')
    assert owner.post('/api/auth/login', json={'password': 'test-owner-password-123'}).status_code == 200
    owner.headers['X-CSRF-Token'] = owner.get('/api/session').json()['csrf_token']
    yield app, owner, tmp_path

def device(app, owner, name='phone'):
    c = TestClient(app, base_url='http://127.0.0.1:8765')
    pending = c.post(P + '/pairings', json={'name': name}).json()
    poll = {'pairing_id': pending['pairing_id'], 'poll_secret': pending['poll_secret']}
    assert c.post(P + '/pairings/poll', json=poll).json()['status'] == 'pending'
    assert owner.post('/api/client-admin/pairings/approve', json={'code': pending['code']}).status_code == 200
    tokens = c.post(P + '/pairings/poll', json=poll).json()
    c.headers['Authorization'] = 'Bearer ' + tokens['access_token']
    return c, tokens

def agent(app, owner, scopes):
    r = owner.post('/api/client-admin/agents', json={'name': 'test-agent', 'scopes': scopes})
    assert r.status_code == 200, r.text
    token = r.json()
    c = TestClient(app, base_url='http://127.0.0.1:8765')
    c.headers['Authorization'] = 'Bearer ' + token['token']
    return c, token

def command(c, operation, data, **kwargs):
    payload = {'request_id': str(uuid4()), 'operation': operation, 'data': data, **kwargs}
    response = c.post(P + '/commands', json=payload)
    assert response.status_code == 200, response.text
    return response.json(), payload

def test_auth_private_reads_csrf_and_origin(env):
    app, owner, _ = env
    c = TestClient(app, base_url='http://127.0.0.1:8765')
    for path in ['/api/records', '/api/status', '/api/session', '/api/settings', '/api/client-admin']:
        assert c.get(path).status_code == 401
    assert c.post('/api/auth/login', json={'password': 'wrong'}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert c.post('/api/auth/login', json={'password': 'wrong'}).status_code == 401
    assert owner.post('/api/auth/logout', headers={'x-csrf-token': ''}).status_code == 403
    assert owner.post('/api/auth/logout').status_code == 200
    assert owner.get('/api/records').status_code == 401

def test_server_origin_fails_closed_before_initialization(tmp_path):
    app = create_app(tmp_path / 'server', public_origin='https://personal.example')
    c = TestClient(app, base_url='https://personal.example')
    assert c.get('/api/status').status_code == 401
    assert c.get('/api/auth/status').json()['required']
    app.state.access.initialize('test-owner-password-123')
    r = c.post('/api/auth/login', json={'password': 'test-owner-password-123'})
    assert r.status_code == 200 and 'Secure' in r.headers['set-cookie']
    assert c.get('/api/status').status_code == 200
    assert c.get('/api/status', headers={'Host': 'evil.example'}).status_code == 403

def test_pairing_rotation_revoke_and_no_internal_api_access(env):
    app, owner, _ = env
    c, tokens = device(app, owner)
    assert c.get(P + '/capabilities').json()['role'] == 'device'
    assert c.get('/api/settings').status_code == 401
    rotated = c.post(P + '/auth/refresh', json={'refresh_token': tokens['refresh_token']})
    assert rotated.status_code == 200
    assert c.post(P + '/auth/refresh', json={'refresh_token': tokens['refresh_token']}).status_code == 401
    assert owner.post('/api/client-admin/' + tokens['client_id'] + '/revoke').status_code == 200
    assert c.get(P + '/snapshot').status_code == 401
    assert c.post(P + '/auth/refresh', json={'refresh_token': rotated.json()['refresh_token']}).status_code == 401
    serialized = app.state.access.path.read_text()
    assert tokens['access_token'] not in serialized and tokens['refresh_token'] not in serialized

def test_pairing_secret_expiry_and_agent_scopes(env):
    app, owner, _ = env
    pending = owner.post(P + '/pairings', json={'name': 'pending'}).json()
    body = {'pairing_id': pending['pairing_id'], 'poll_secret': 'wrong-secret-with-sufficient-length'}
    assert owner.post(P + '/pairings/poll', json=body).status_code == 401
    assert owner.post('/api/client-admin/agents', json={'name': 'bad', 'scopes': ['confirm']}).status_code == 422
    c, token = agent(app, owner, ['read:tasks'])
    assert set(c.get(P + '/snapshot').json()['data']) == {'tasks'}
    assert c.get(P + '/resources/profile').status_code == 403
    assert c.post(P + '/commands', json={'request_id': str(uuid4()), 'operation': 'decide', 'id': 'anything', 'data': {'decision': 'accept'}}).status_code == 403
    assert c.post('/api/client-admin/agents', json={'name': 'bad', 'scopes': ['read:tasks']}).status_code == 401

def test_agent_task_proposal_confirm_audit_and_idempotency(env):
    app, owner, _ = env
    a, _ = agent(app, owner, ['read:tasks', 'read:pending', 'write:records', 'propose'])
    result, payload = command(a, 'create_record', {'kind': 'task', 'text': 'Example task', 'date': '2026-10-26'})
    assert not app.state.store.records
    assert a.post(P + '/commands', json=payload).json() == result
    c, _ = device(app, owner)
    result, confirm = command(c, 'decide', {'decision': 'accept'}, id=result['proposal']['id'])
    assert c.post(P + '/commands', json=confirm).json() == result
    assert len(app.state.store.records) == 1
    roles = {e.data['role'] for e in app.state.store.entities.values() if e.kind == 'core/client-audit'}
    assert {'agent', 'device'} <= roles
    assert a.get(P + '/resources/tasks').json()['items'][0]['text'] == 'Example task'
    assert a.get(P + '/resources/tasks').json()['items'][0]['origin']['role'] == 'device'

def test_device_goal_conflict_and_scope_filtered_sync(env):
    app, owner, _ = env
    c, _ = device(app, owner)
    a, _ = agent(app, owner, ['read:goals'])
    baseline = a.get(P + '/snapshot').json()['cursor']
    value = {'title': 'Read', 'criteria': 'Ten chapters', 'baseline': 0, 'target': 10, 'current': None}
    created, _ = command(c, 'write_entity', value, kind='goal')
    key = created['entity']['id']
    proposals = []
    for progress in [2, 3]:
        result, _ = command(c, 'write_entity', {**value, 'current': progress}, kind='goal', id=key, expected_version=1)
        proposals.append(result['change']['id'])
    command(c, 'decide', {'decision': 'accept'}, id=proposals[0])
    assert c.post(P + '/commands', json={'request_id': str(uuid4()), 'operation': 'decide', 'id': proposals[1], 'data': {'decision': 'accept'}}).status_code == 409
    delta = a.get(P + '/changes', params={'cursor': baseline}).json()
    assert set(delta['data']) == {'goals'} and delta['data']['goals'][0]['confirmed_progress'] == 20
    assert a.get(P + '/changes', params={'cursor': 'broken'}).status_code == 410
    assert c.get(P + '/changes', params={'cursor': baseline}).status_code == 410

def test_agent_cannot_create_goal_without_proposal(env):
    app, owner, _ = env
    a, _ = agent(app, owner, ['read:goals', 'read:pending', 'propose'])
    result, _ = command(a, 'write_entity', {'title': 'Read', 'criteria': 'Ten chapters'}, kind='goal')
    assert 'change' in result and not any(e.kind == 'goal' for e in app.state.store.entities.values())

def test_reminders_conflict_occurrences_and_backup_without_credentials(env):
    app, owner, tmp = env
    c, token = device(app, owner)
    reminder = {'title': 'Check in', 'start_date': '2026-10-26', 'time': '08:00', 'repeat': 'weekly', 'weekdays': [0]}
    saved, body = command(c, 'reminder', reminder)
    assert c.post(P + '/commands', json=body).json() == saved
    at = datetime(2026, 10, 26, 7, tzinfo=TZ)
    items = occurrences(app.state.store, at)
    assert len(items) == 5 and items == occurrences(app.state.store, at)
    assert len({e['id'] for e in items}) == 5
    key = saved['entity']['id']
    proposed, _ = command(c, 'reminder', {**reminder, 'enabled': False}, id=key, expected_version=1)
    command(c, 'decide', {'decision': 'accept'}, id=proposed['entity']['id'])
    assert not occurrences(app.state.store, at)
    restored = restore_backup(export_backup(app.state.store), tmp / 'restored')
    assert restored.entities[key].data['enabled'] is False
    assert not (restored.root / '.secrets/access.json').exists()
    assert [p.read_bytes() for p in restored.files] == [p.read_bytes() for p in app.state.store.files]

def test_encrypted_server_vault_separate_master_and_bound_connection(tmp_path, monkeypatch):
    master = tmp_path / 'master.key'; master.write_bytes(bytes(range(32))); master.chmod(0o600)
    monkeypatch.setenv('PERSONALAI_MASTER_KEY_FILE', str(master))
    vault = SecretVault(tmp_path / 'data')
    vault.save('https://provider.example', 'isolated-test-secret')
    assert b'isolated-test-secret' not in vault.path.read_bytes()
    assert vault.read('https://provider.example') == 'isolated-test-secret'
    assert vault.read('https://other.example') is None
    master.write_bytes(bytes(reversed(range(32))))
    with pytest.raises(StoreError): vault.read('https://provider.example')

def test_schema_and_forged_actor(env):
    app, owner, _ = env
    c, _ = device(app, owner)
    assert '/api/clients/v1/commands' in c.get(P + '/openapi.json').json()['paths']
    response = c.post(P + '/commands', json={'request_id': str(uuid4()), 'operation': 'create_record',
        'actor': 'owner', 'data': {'text': 'test', 'date': '2026-10-26'}})
    assert response.status_code == 422


def test_delta_receipts_history_and_analysis_scope(env):
    app, owner, _ = env
    c, _ = device(app, owner)
    a, _ = agent(app, owner, ['read:records', 'write:records'])
    made, _ = command(a, 'create_record', {'text': 'A short factual log', 'date': '2026-10-26'})
    key = made['record']['id']
    assert a.get(P + '/resources/records').json()['items'][0]['origin']['role'] == 'agent'
    assert a.get(P + '/history/' + key).json()['items'][0]['text'] == 'A short factual log'
    assert a.get(P + '/schedule').status_code == 403
    assert c.get(P + '/schedule').status_code == 200
    assert 'model_fingerprint' not in c.get(P + '/schedule').text
    cursor = c.get(P + '/snapshot').json()['cursor']
    command(c, 'receipt', {'action': 'read'}, id='message-1')
    delta = c.get(P + '/changes', params={'cursor': cursor}).json()
    assert delta['receipts'][0]['data']['message_id'] == 'message-1'
    assert 'year' in delta
    assert c.post(P + '/sync/ack', json={'cursor': delta['cursor']}).json()['acknowledged']
    assert c.post(P + '/sync/ack', json={'cursor': 'broken'}).status_code == 410
    assert a.post(P + '/sync/ack', json={'cursor': delta['cursor']}).status_code == 403


def test_model_binding_change_pauses_existing_consent(env):
    from personalai.configuration import ConfigService
    from personalai.tracking_models import WriteEntity
    from personalai.models import Decision
    app, owner, _ = env
    c, _ = device(app, owner)
    config = ConfigService(app.state.store)
    connections = [{'id': x, 'name': x, 'enabled': False, 'base_url': 'https://provider.example', 'model': 'test'} for x in ['one', 'two']]
    change = config.save('models', WriteEntity(request_id=uuid4(), data={'connections': connections, 'bindings': {'goal': 'one', 'schedule': 'one'}}))
    config.decide(change['change']['id'], Decision(request_id=uuid4(), decision='accept'))
    current = config.get('models')
    result, _ = command(c, 'model_binding', {'goal': 'two', 'schedule': 'two'}, expected_version=current['version'])
    assert config.get('models')['data']['bindings']['goal'] == 'one'
    command(c, 'decide', {'decision': 'accept'}, id=result['entity']['id'])
    assert config.get('models')['data']['bindings']['goal'] == 'two'
    assert not app.state.scheduler.status()['authorized']
    assert 'base_url' not in c.get(P + '/resources/settings').text


def test_optional_push_minimal_payload_duplicate_and_revoke(env, monkeypatch):
    import httpx
    from personalai.delivery import PushConfig
    app, owner, tmp = env
    key = tmp / 'master.key'; key.write_bytes(bytes(range(32))); key.chmod(0o600)
    monkeypatch.setenv('PERSONALAI_MASTER_KEY_FILE', str(key))
    c, tokens = device(app, owner)
    c.post(P + '/device', json={'notifications': True, 'push_registration': 'test-registration'})
    d = app.state.delivery
    d.save(PushConfig(enabled=True, app_key='test-app', secret='test-master'))
    d.tick()  # Establish the queue baseline before new events.
    received = []
    def transport(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={'msg_id': 'test'})
    d.transport = httpx.MockTransport(transport)
    a, _ = agent(app, owner, ['read:tasks', 'propose', 'write:records'])
    command(a, 'create_record', {'text': 'Never send this private title', 'kind': 'task', 'date': '2026-10-26'})
    d.tick(); d.tick()
    assert len(received) == 1
    assert 'Never send' not in json.dumps(received)
    extras = received[0]['notification']['android']['extras']
    assert set(extras) == {'event_id'}
    assert d.queue()['items'][0]['status'] == 'accepted'
    command(a, 'create_record', {'text': 'Second task', 'kind': 'task', 'date': '2026-10-26'})
    owner.post('/api/client-admin/' + tokens['client_id'] + '/revoke')
    d.tick()
    assert len(received) == 1
    assert b'test-master' not in d.vault.path.read_bytes()


def test_push_uncertain_delivery_never_automatically_retries(env, monkeypatch):
    import httpx
    from personalai.delivery import PushConfig
    app, owner, tmp = env
    key = tmp / 'master.key'; key.write_bytes(bytes(range(32))); key.chmod(0o600)
    monkeypatch.setenv('PERSONALAI_MASTER_KEY_FILE', str(key))
    c, _ = device(app, owner)
    c.post(P + '/device', json={'notifications': True, 'push_registration': 'test-registration'})
    d = app.state.delivery; d.save(PushConfig(enabled=True, app_key='test-app', secret='test-master')); d.tick()
    calls = []
    def timeout(request):
        calls.append(1); raise httpx.ReadTimeout('test timeout')
    d.transport = httpx.MockTransport(timeout)
    a, _ = agent(app, owner, ['read:tasks', 'propose', 'write:records'])
    command(a, 'create_record', {'text': 'Task', 'kind': 'task', 'date': '2026-10-26'})
    d.tick(); d.tick()
    assert calls == [1] and d.queue()['items'][0]['status'] == 'unknown'


def test_private_static_paths_and_pair_limits(env):
    app, owner, _ = env
    for path in ['/data/.secrets/access.json', '/.secrets/access.json', '/personal/USER_PROFILE.md', '/src/personalai/access.py']:
        response = owner.get(path)
        assert response.status_code in {404, 200}
        assert 'password_hash' not in response.text and 'scrypt' not in response.text
    for _ in range(5): assert owner.post(P + '/pairings', json={'name': 'one'}).status_code == 200
    assert owner.post(P + '/pairings', json={'name': 'six'}).status_code == 429
