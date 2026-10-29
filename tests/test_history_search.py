from uuid import uuid4
from fastapi.testclient import TestClient
from personalai.app import create_app


def test_all_business_history_and_revisions(tmp_path):
    app = create_app(tmp_path, port=18765)
    with TestClient(app, base_url='http://127.0.0.1:18765') as client:
        client.headers['x-csrf-token'] = client.get('/api/session').json()['csrf_token']
        def post(path, **data):
            r = client.post(path, json={'request_id': str(uuid4()), **data})
            assert r.status_code == 200, r.text
            return r.json()
        record = post('/api/records', text='旧关键词阅读', date='2026-10-28', kind='note')['record']
        proposal = post(f"/api/records/{record['id']}/revisions", text='新内容', date='2026-10-28', category='uncategorized', status='open', expected_version=1, reason='更正')['proposal']
        post(f"/api/proposals/{proposal['id']}/decision", decision='accept')
        post('/api/goals', data={'title':'阅读目标', 'criteria':'十章', 'baseline':0, 'target':10})
        post('/api/activity-logs', data={'text':'阅读日志', 'date':'2026-10-28'})
        post('/api/check-ins', data={'response':'阅读回应', 'date':'2026-10-28', 'slot':'morning'})
        result = client.get('/api/history?q=阅读').json()
        assert {'note','goal','log','checkin','proposal'} <= {x['kind'] for x in result['items']}
        found = next(x for x in result['items'] if x['id'] == record['id'])
        assert found['version'] == 2 and len(found['history']) == 2
        assert found['matches'][0]['version'] == 1
        page = client.get('/api/history?limit=1').json()
        assert len(page['items']) == 1 and page['next_offset'] == 1
        assert client.get('/api/history?kind=checkin&day=2026-10-27').json()['total'] == 0
        assert client.get('/api/history?kind=checkin&day=2026-10-28').json()['total'] == 1
        assert not {'settings','schedule','core/config-models'} & {x['kind'] for x in result['items']}
        assert client.get('/api/history?limit=1000').status_code == 422


def test_public_history_requires_owner_login(tmp_path):
    app = create_app(tmp_path, port=18765, public_origin='https://personal.example')
    with TestClient(app, base_url='https://personal.example') as client:
        assert client.get('/api/history').status_code == 401
