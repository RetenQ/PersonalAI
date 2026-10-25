"""Isolated fake-clock/provider tests; no private data or external requests."""
import json
from datetime import datetime, timedelta
from uuid import uuid4

import httpx
import portalocker
import pytest
from fastapi.testclient import TestClient

from personalai.app import create_app
from personalai.backup import export_backup, restore_backup
from personalai.models import TZ, CreateRecord
from personalai.scheduled_models import ScheduleOptions
from personalai.scheduling import Scheduler
from personalai.store import StoreError, Store
from personalai.tracking import entity
from personalai.tracking_models import Settings


def post(client, path, **data):
    response = client.post(path, json={'request_id': str(uuid4()), **data})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def env(tmp_path):
    app = create_app(tmp_path / 'data', port=18765)
    with TestClient(app, base_url='http://127.0.0.1:18765') as client:
        client.headers['x-csrf-token'] = client.get('/api/session').json()['csrf_token']
        scheduler = app.state.scheduler
        scheduler.stop()
        clock = [datetime(2026, 10, 25, 8, tzinfo=TZ)]
        scheduler.clock = lambda: clock[0]
        calls = []
        def transport(request):
            inputs = json.loads(json.loads(request.content)['messages'][1]['content'])
            calls.append(inputs)
            refs = list(inputs['sources'])[:1]
            assessment = {k: [] for k in ['facts', 'reflection', 'issues', 'suggestions', 'next_steps', 'long_term']}
            assessment.update({'facts': [{'text': '记录中提到阅读进展。', 'source_ids': refs}],
                               'suggestions': [{'text': '可以继续上次阅读。', 'source_ids': refs}], 'missing': ['睡眠情况未记录。']})
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(assessment)}}]})
        app.state.model_transport = httpx.MockTransport(transport)
        app.state.vault.read = lambda url: 'test-key'
        settings = Settings(model={'enabled': True, 'base_url': 'https://model.example/v1', 'model': 'test'}).model_dump(mode='json')
        post(client, '/api/settings', data=settings)
        yield app, client, scheduler, clock, calls


def note(client, date='2026-10-25', text='读了两页书。'):
    return post(client, '/api/records', text=text, date=date, kind='note')['record']


def enable(client, scopes=None, times=None, enabled=True):
    version = client.get('/api/schedule').json()['version']
    preview = client.post('/api/schedule/preview', json={'data': {'enabled': enabled,
        'times': times or ['09:00', '13:00', '20:00'], 'scopes': scopes or ['records']}, 'expected_version': version})
    assert preview.status_code == 200, preview.text
    token = preview.json()['approval_token']
    return post(client, '/api/schedule/confirm', approval_token=token, approved=True)


def test_disabled_and_no_implicit_schedule(env):
    app, client, scheduler, clock, calls = env
    status = client.get('/api/schedule').json()
    assert status['config']['times'] == [] and not status['active']
    scheduler.execute()
    assert not calls and not scheduler.runs()['reports']
    assert client.post('/api/schedule/run', json={'request_id': str(uuid4())}).status_code == 422


def test_preview_is_local_and_empty_enable_needs_no_fabricated_records(env):
    _, client, scheduler, clock, calls = env
    enable(client)
    assert client.get('/api/schedule').json()['active']
    clock[0] = clock[0].replace(hour=10)
    scheduler.execute()
    assert not calls
    assert scheduler.runs()['reports'][0]['run']['data']['status'] == 'skipped'


@pytest.mark.parametrize('times', [['25:00'], ['9:00'], ['09:00', '09:00'], []])
def test_invalid_schedule(times):
    with pytest.raises(ValueError):
        ScheduleOptions(enabled=True, times=times, scopes=['records'])


def test_seven_calendar_days_and_scope_exclusion(env):
    app, client, scheduler, clock, calls = env
    note(client, '2026-10-18', '不在窗口')
    older = note(client, '2026-10-19', '六天前')
    today = note(client)
    note(client, '2026-10-26', '未来记录')
    post(client, '/api/records', text='未授权的想法', date='2026-10-25', kind='idea')
    post(client, '/api/records', text='未授权的任务', date='2026-10-25', kind='task')
    profile = post(client, '/api/profile', data={'personality': '不发送的自述'})['change']
    post(client, f'/api/changes/{profile["id"]}/decision', decision='accept')
    enable(client)
    clock[0] = clock[0].replace(hour=14)
    scheduler.execute()
    assert set(calls[0]['sources']) == {older['id'], today['id']}
    assert '不发送的自述' not in json.dumps(calls, ensure_ascii=False)
    assert calls[0]['window_start'] == '2026-10-19'
    assert scheduler.runs()['reports'][0]['run']['data']['status'] == 'succeeded'


def test_only_latest_due_once_and_next_slot(env):
    _, client, scheduler, clock, calls = env
    note(client); enable(client)
    assert scheduler.execute() is None
    clock[0] = clock[0].replace(hour=14)
    scheduler.execute(); scheduler.execute()
    assert len(calls) == 1
    assert '13:00' in scheduler.runs()['reports'][0]['run']['data']['scheduled_at']
    clock[0] = clock[0].replace(hour=21)
    scheduler.execute()
    assert len(calls) == 2
    clock[0] = clock[0].replace(hour=12)  # wall clock moving backwards must not replay
    scheduler.execute()
    # Earlier slots were coalesced, not a backlog to execute after clock rollback.
    assert len(calls) == 2


def test_restart_catchup_and_restore_requires_consent(env, tmp_path):
    app, client, scheduler, clock, calls = env
    note(client); enable(client)
    other_app = create_app(app.state.store.root, port=18765)
    other_app.state.vault.read = lambda _: 'test-key'
    other_app.state.model_transport = app.state.model_transport
    other = other_app.state.scheduler
    other.clock = lambda: datetime(2026, 10, 26, 8, tzinfo=TZ)
    other.execute(); other.execute()
    assert len(calls) == 1
    data = other.runs()['reports'][0]['run']['data']
    assert '2026-10-25T20:00' in data['scheduled_at'] and data['window_end'] == '2026-10-26'
    raw = export_backup(other_app.state.store)
    restored = restore_backup(raw, tmp_path / 'restored')
    restored_app = create_app(restored.root, port=18765)
    restored_app.state.vault.read = lambda _: 'test-key'
    restored_app.state.model_transport = app.state.model_transport
    assert not restored_app.state.scheduler.status()['authorized']
    assert restored_app.state.scheduler.execute() is None
    assert len(calls) == 1
    assert (restored.root / 'user' / 'analyses' / (other.runs()['reports'][0]['run']['id'] + '.md')).is_file()


def test_model_change_revokes_and_pause_blocks(env):
    app, client, scheduler, clock, calls = env
    note(client); enable(client)
    clock[0] = clock[0].replace(hour=14)
    state = client.get('/api/settings').json()
    state['settings']['model']['model'] = 'other-model'
    change = post(client, '/api/settings', data=state['settings'], expected_version=state['version'])['change']
    post(client, f'/api/changes/{change["id"]}/decision', decision='accept')
    assert not client.get('/api/schedule').json()['active']
    scheduler.execute(); assert not calls
    enable(client)
    post(client, '/api/schedule/pause')
    scheduler.execute(); assert not calls


def test_stale_preview_and_explicit_approval(env):
    app, client, scheduler, clock, _ = env
    preview = client.post('/api/schedule/preview', json={'data': {'enabled': True, 'times': ['12:00'], 'scopes': ['records']}, 'expected_version': 0}).json()
    assert client.post('/api/schedule/confirm', json={'request_id': str(uuid4()), 'approval_token': preview['approval_token'], 'approved': False}).status_code == 422
    post(client, '/api/schedule/pause')
    assert client.post('/api/schedule/confirm', json={'request_id': str(uuid4()), 'approval_token': preview['approval_token'], 'approved': True}).status_code == 409


def test_request_idempotency_export_stale_and_source_integrity(env):
    app, client, scheduler, clock, calls = env
    recorded = note(client); enable(client)
    request = {'request_id': str(uuid4())}
    first = client.post('/api/schedule/run', json=request).json()
    second = client.post('/api/schedule/run', json=request).json()
    identifier = first['run']['id']
    assert second['run']['id'] == identifier and len(calls) == 1
    exported = client.get(f'/api/scheduled-reports/{identifier}/export?format=json').json()
    assert exported['run']['data']['sources'][recorded['id']] == 1
    assert b'test-key' not in client.get(f'/api/scheduled-reports/{identifier}/export?format=markdown').content
    change = post(client, f'/api/records/{recorded["id"]}/revisions', text='读了三页', date='2026-10-25', expected_version=1, reason='更正页数')['proposal']
    post(client, f'/api/proposals/{change["id"]}/decision', decision='accept')
    assert client.get(f'/api/scheduled-reports/{identifier}').json()['stale']
    feed = client.get('/api/scheduled-reports/feed').json()
    assert feed['schema_version'] == 1 and feed['items'][0]['stale']
    assert client.get('/data/.scheduler/consent.json').status_code == 404


@pytest.mark.parametrize('failure', ['timeout', 'quota', 'invalid-json', 'bad-source', 'refusal'])
def test_failure_never_retries_or_modifies_records(env, failure):
    app, client, scheduler, clock, calls = env
    recorded = note(client); enable(client)
    before = {p.name: p.read_bytes() for p in app.state.store.files}
    attempts = []
    def fail(request):
        attempts.append(1)
        if failure == 'timeout':
            raise httpx.ReadTimeout('timeout')
        if failure == 'quota':
            return httpx.Response(429)
        assessment = {k: [] for k in ['facts', 'reflection', 'issues', 'suggestions', 'next_steps', 'long_term']}
        assessment.update(missing=[], facts=[{'text': '没有依据', 'source_ids': ['absent']}])
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
            'refusal': 'no' if failure == 'refusal' else None,
            'content': 'invalid' if failure == 'invalid-json' else json.dumps(assessment)}}]})
    app.state.model_transport = httpx.MockTransport(fail)
    clock[0] = clock[0].replace(hour=14)
    scheduler.execute(); scheduler.execute()
    assert len(attempts) == 1
    assert scheduler.runs()['reports'][0]['run']['data']['status'] == 'failed'
    assert client.get('/api/records/' + recorded['id']).json()['record']['version'] == 1
    for filename, content in before.items():
        assert (app.state.store.events_dir / filename).read_bytes() == content


def test_missing_key_and_large_input_no_network(env):
    app, client, scheduler, clock, calls = env
    note(client); enable(client)
    app.state.vault.read = lambda _: None
    clock[0] = clock[0].replace(hour=14)
    scheduler.execute()
    assert scheduler.runs()['reports'][0]['run']['data']['status'] == 'failed' and not calls
    app.state.vault.read = lambda _: 'test-key'
    for _ in range(5): note(client, text='字' * 10000)
    clock[0] = clock[0].replace(hour=21)
    scheduler.execute()
    assert '128 KiB' in scheduler.runs()['reports'][0]['run']['data']['message'] and not calls


def test_inflight_recovery_and_competing_process_lock(env):
    app, client, scheduler, clock, calls = env
    note(client); enable(client)
    clock[0] = clock[0].replace(hour=14)
    with portalocker.Lock(str(app.state.store.root / '.scheduled-run.lock'), timeout=0):
        assert scheduler.execute() is None
    assert not calls
    scheduler.execute()
    item = scheduler.runs()['reports'][0]['run']
    scheduler.update_run(item['id'], {'status': 'running', 'assessment': None, 'finished_at': None})
    scheduler.execute()
    assert len(calls) == 1
    assert scheduler.runs()['reports'][0]['run']['data']['status'] == 'interrupted'


def test_schedule_writes_need_session(env):
    _, client, _, _, _ = env
    client.headers.pop('x-csrf-token')
    assert client.post('/api/schedule/pause', json={'request_id': str(uuid4())}).status_code == 403


@pytest.mark.parametrize('citation', ['goal', 'task', 'tracking', 'log'])
def test_real_provider_regression_plans_cannot_be_reported_as_activity(citation):
    from personalai.model_client import call_model
    inputs = {'items': [{'id': kind, 'kind': kind} for kind in ['goal', 'task', 'tracking', 'log']],
              'sources': {kind: 1 for kind in ['goal', 'task', 'tracking', 'log']}}
    result = {section: [] for section in ['facts', 'reflection', 'issues', 'suggestions', 'next_steps', 'long_term', 'missing']}
    result['facts'] = [{'text': '已阅读两章', 'source_ids': [citation]}]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}]}))
    config = {'enabled': True, 'base_url': 'https://provider.example', 'model': 'sample', 'response_format': 'json_object'}
    if citation == 'log':
        assert call_model(config, 'sample-key', inputs, transport, report=True).facts[0].source_ids == ['log']
    else:
        with pytest.raises(StoreError, match='来源校验失败'):
            call_model(config, 'sample-key', inputs, transport, report=True)


@pytest.mark.parametrize('stamp', ['2027-01-01T00:00:00+08:00', '2028-03-01T00:00:00+08:00'])
def test_midnight_year_and_leap_boundaries(env, stamp):
    _, client, scheduler, clock, calls = env
    target = datetime.fromisoformat(stamp)
    clock[0] = target - timedelta(minutes=1)
    note(client, date=target.date().isoformat())
    enable(client, times=['00:00'])
    clock[0] = target
    scheduler.execute(); scheduler.execute()
    assert len(calls) == 1
    assert calls[0]['window_start'] == (target.date() - timedelta(days=6)).isoformat()


def test_scheduler_lifespan_runs_without_browser_request(env):
    import time
    _, client, scheduler, clock, calls = env
    note(client); enable(client)
    clock[0] = clock[0].replace(hour=14)
    scheduler.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            reports = scheduler.runs()['reports']
            if reports and reports[0]['run']['data']['status'] == 'succeeded':
                break
            time.sleep(.02)
        assert len(calls) == 1
        assert scheduler.runs()['reports'][0]['run']['data']['status'] == 'succeeded'
    finally:
        scheduler.stop()


def test_schedule_confirmation_idempotent_and_no_key_blocks_enable(env):
    app, client, scheduler, _, _ = env
    preview = client.post('/api/schedule/preview', json={'data': {'enabled': True, 'times': ['12:00'], 'scopes': ['records']}, 'expected_version': 0}).json()
    body = {'request_id': str(uuid4()), 'approval_token': preview['approval_token'], 'approved': True}
    app.state.vault.read = lambda _: None
    assert client.post('/api/schedule/confirm', json=body).status_code == 422
    assert client.get('/api/schedule').json()['version'] == 0
    app.state.vault.read = lambda _: 'test-key'
    first = client.post('/api/schedule/confirm', json=body).json()
    second = client.post('/api/schedule/confirm', json=body).json()
    assert first == second
    assert client.get('/api/schedule').json()['version'] == 1
    scheduler.arm_path().unlink()
    scheduler.previews.clear()  # A restored/restarted host must not re-arm by replaying the old POST.
    assert client.post('/api/schedule/confirm', json=body).status_code == 409
    assert not client.get('/api/schedule').json()['authorized']


def test_missing_consent_and_model_busy_make_no_network_call(env):
    app, client, scheduler, clock, calls = env
    note(client); enable(client)
    clock[0] = clock[0].replace(hour=14)
    with app.state.model_lock:
        assert scheduler.execute() is None
    # Only a test's temporary consent file is removed, simulating a restore.
    scheduler.arm_path().unlink()
    assert scheduler.execute() is None and not calls


def test_plan_cannot_be_cited_as_completed_fact(env):
    app, client, scheduler, clock, calls = env
    post(client, '/api/records', text='以后读两页书', date='2026-10-25', kind='task')
    enable(client, scopes=['tasks'])
    clock[0] = clock[0].replace(hour=14)
    scheduler.execute()
    assert len(calls) == 1
    assert scheduler.runs()['reports'][0]['run']['data']['status'] == 'failed'
    assert scheduler.runs()['reports'][0]['run']['data']['assessment'] is None
