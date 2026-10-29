from uuid import uuid4
from fastapi.testclient import TestClient
from personalai.app import create_app


def test_events_are_derived_only_from_saved_task_versions(tmp_path):
    app = create_app(tmp_path, port=18765)
    with TestClient(app, base_url='http://127.0.0.1:18765') as client:
        client.headers['x-csrf-token'] = client.get('/api/session').json()['csrf_token']
        def post(path, **body):
            r = client.post(path, json={'request_id': str(uuid4()), **body})
            assert r.status_code == 200, r.text
            return r.json()
        post('/api/records', text='尚未决定的想法', date='2026-10-28', kind='idea')
        task = post('/api/records', text='阅读一章', date='2026-10-28', kind='task')['record']
        def events():
            return client.get('/api/task-events').json()['items']
        assert len(events()) == 1 and events()[0]['action'] == '创建任务'
        change = post(f"/api/records/{task['id']}/revisions", text=task['text'], date=task['date'], category=task['category'], status='done', expected_version=1, reason='完成')['proposal']
        assert len(events()) == 1
        post(f"/api/proposals/{change['id']}/decision", decision='reject')
        assert len(events()) == 1
        change = post(f"/api/records/{task['id']}/revisions", text=task['text'], date=task['date'], category=task['category'], status='done', expected_version=1, reason='完成')['proposal']
        post(f"/api/proposals/{change['id']}/decision", decision='accept')
        assert len(events()) == 2
        assert any(e['action'] == '状态：待进行 → 已完成' for e in events())
        assert events() == events()  # Reading the projection never creates another event.
        assert client.get('/api/task-events?day=2000-01-01').json()['items'] == []
        assert client.get('/api/activity-logs').json()['entities'] == []
