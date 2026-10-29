from uuid import uuid4

from fastapi.testclient import TestClient

from personalai.app import create_app
from personalai.backup import export_backup, restore_backup
from personalai.store import Store


def session(client):
    client.headers['x-csrf-token'] = client.get('/api/session').json()['csrf_token']


def post(client, path, **body):
    response = client.post(path, json={'request_id': str(uuid4()), **body})
    assert response.status_code == 200, response.text
    return response.json()


def test_linked_creation_is_atomic_idempotent_and_restorable(tmp_path):
    app = create_app(tmp_path / 'data', port=18765)
    with TestClient(app, base_url='http://127.0.0.1:18765') as client:
        session(client)
        goal = post(client, '/api/goals', data={'title': '阅读', 'criteria': '读完十章', 'baseline': 0, 'target': 10})['entity']
        payload = {'request_id': str(uuid4()), 'text': '阅读第一章', 'date': '2026-10-29', 'goal_id': goal['id']}
        sequence = app.state.store.sequence
        first = client.post('/api/tasks', json=payload)
        assert first.status_code == 200, first.text
        assert client.post('/api/tasks', json=payload).json() == first.json()
        assert app.state.store.sequence == sequence + 1
        task_id = first.json()['record']['id']
        reloaded = Store(app.state.store.root)
        assert len(reloaded.records) == 1
        assert reloaded.entities['tracking:' + task_id].data['goal_id'] == goal['id']
        assert reloaded.entities['tracking:' + task_id].data['progress'] is None
        restored = restore_backup(export_backup(reloaded), tmp_path / 'restore')
        assert [f.read_bytes() for f in reloaded.files] == [f.read_bytes() for f in restored.files]
        bad = client.post('/api/tasks', json={**payload, 'request_id': str(uuid4()), 'goal_id': str(uuid4())})
        assert bad.status_code == 404
        assert app.state.store.sequence == sequence + 1
        assert len(app.state.store.records) == 1


def test_task_creation_requires_session_and_active_plugin(tmp_path):
    app = create_app(tmp_path, port=18765, enabled_plugins=[])
    with TestClient(app, base_url='http://127.0.0.1:18765') as client:
        payload = {'request_id': str(uuid4()), 'text': '阅读', 'date': '2026-10-29'}
        assert client.post('/api/tasks', json=payload).status_code == 403
        session(client)
        assert client.post('/api/tasks', json=payload).status_code == 409
        assert not app.state.store.records


def test_confirmed_goal_and_assignment_events_keep_historical_names(tmp_path, monkeypatch):
    from personalai.models import now
    stamp = now()
    for module in ['personalai.tracking', 'personalai.task_routes', 'personalai.store']:
        monkeypatch.setattr(module + '.now', lambda: stamp)
    app = create_app(tmp_path, port=18765)
    with TestClient(app, base_url='http://127.0.0.1:18765') as client:
        session(client)
        goal = post(client, '/api/goals', data={'title': '阅读', 'criteria': '十章', 'baseline': 0, 'target': 10})['entity']
        task = post(client, '/api/tasks', text='第一章', date='2026-10-29', goal_id=goal['id'])['record']
        events = lambda: client.get('/api/task-events').json()['items']
        original = events()
        assert len(original) == 3  # Goal, task and initial association; no duplicated log facts.
        change = post(client, '/api/goals/' + goal['id'], data={**goal['data'], 'current': 2}, expected_version=1)['change']
        assert events() == original
        post(client, '/api/changes/' + change['id'] + '/decision', decision='reject')
        assert events() == original
        change = post(client, '/api/goals/' + goal['id'], data={**goal['data'], 'title': '精读', 'current': 2}, expected_version=1)['change']
        post(client, '/api/changes/' + change['id'] + '/decision', decision='accept')
        latest = events()
        assert len(latest) == 4
        assert '目标进度：未计算 → 20%' in latest[0]['action']
        assert next(e for e in latest if e.get('entity_id') == 'tracking:' + task['id'])['action'] == '目标归属：未关联目标 → 阅读'
        sequence = app.state.store.sequence
        assert events() == latest
        assert app.state.store.sequence == sequence
        assert client.get('/api/activity-logs').json()['entities'] == []
