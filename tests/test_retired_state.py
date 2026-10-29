"""Retired current-state inputs cannot reappear through old clients or consent."""
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from personalai.app import create_app
from personalai.backup import export_backup, restore_backup
from personalai.models import Decision, TZ
from personalai.store import StoreError, canonical, digest
from personalai.tracking import TrackingService, entity
from personalai.tracking_models import WriteEntity


def test_retired_state_boundaries_and_archive(tmp_path):
    app = create_app(tmp_path / 'data', port=8765)
    store = app.state.store
    service = TrackingService(store)
    # Historical event fixture, using the frozen event model (not an active API).
    old = entity('state', {'date': '2026-10-28', 'energy': '历史样例'})
    change = entity('change', {'target_id': old.id, 'target_kind': 'state',
        'expected_version': 1, 'before': old.data, 'after': {**old.data, 'energy': '修改'},
        'reason': '旧版提案'})
    schedule = entity('schedule', {'enabled': True, 'times': ['08:00'], 'scopes': ['states', 'logs'],
        'model_fingerprint': digest(canonical(app.state.scheduler.model()))}, 'schedule')
    store.transaction(uuid4(), 'historical-fixture', {}, lambda: ([], [], {}, [old, change, schedule]), extension=True)
    original = [p.read_bytes() for p in store.files]
    # Even an existing consent file must not reactivate retired input.
    arm = app.state.scheduler.arm_path()
    arm.parent.mkdir(parents=True, exist_ok=True)
    arm.write_bytes(canonical({'version': 1, 'fingerprint': digest(canonical(schedule.data))}))

    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        client.headers['x-csrf-token'] = client.get('/api/session').json()['csrf_token']
        assert client.get('/api/current-state').status_code == 404
        assert client.post('/api/current-state', json={'request_id': str(uuid4()), 'data': old.data}).status_code == 404
        dashboard = client.get('/api/dashboard').json()
        assert 'states' not in dashboard
        assert 'state' not in dashboard['settings']['order']
        assert not any(p['id'] == change.id for p in dashboard['pending'])
        assert 'state' not in client.get('/api/config/sections').json()['modules']
        status = client.get('/api/schedule').json()
        assert not status['active'] and not status['authorized']
        assert status['config']['scopes'] == ['logs']
        assert client.post('/api/schedule/preview', json={'expected_version': 1,
            'data': {'enabled': True, 'times': ['08:00'], 'scopes': ['states']}}).status_code == 422
        assert old.id not in app.state.scheduler.inputs(['states'], datetime(2026, 10, 28, tzinfo=TZ))['sources']
        with pytest.raises(StoreError) as error:
            service.write('state', WriteEntity(request_id=uuid4(), data=old.data))
        assert error.value.status == 410
        with pytest.raises(StoreError):
            service.decide(change.id, Decision(request_id=uuid4(), decision='accept'))

        app.state.access.initialize('isolated-owner-test-password')
        assert client.post('/api/auth/login', json={'password': 'isolated-owner-test-password'}).status_code == 200
        mobile = TestClient(app, base_url='http://127.0.0.1:8765')
        pairing = mobile.post('/api/clients/v1/pairings', json={'name': 'test-device'}).json()
        assert client.post('/api/client-admin/pairings/approve', json={'code': pairing['code']}).status_code == 200
        tokens = mobile.post('/api/clients/v1/pairings/poll', json={k: pairing[k] for k in ['pairing_id', 'poll_secret']}).json()
        mobile.headers['Authorization'] = 'Bearer ' + tokens['access_token']
        assert 'read:states' not in mobile.get('/api/clients/v1/capabilities').json()['scopes']
        assert 'states' not in mobile.get('/api/clients/v1/snapshot').json()['data']
        assert mobile.get('/api/clients/v1/resources/states').status_code == 404
        assert mobile.post('/api/clients/v1/commands', json={'request_id': str(uuid4()),
            'operation': 'write_entity', 'kind': 'state', 'data': old.data}).status_code >= 400

        restored = restore_backup(export_backup(store), tmp_path / 'restored')
        assert restored.entities[old.id].data == old.data
        assert [p.read_bytes() for p in restored.files][:len(original)] == original
        assert [p.read_bytes() for p in store.files][:len(original)] == original
