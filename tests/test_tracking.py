"""All fixtures are invented; no private profiles or external API calls."""
import io
import json
import zipfile
from datetime import date
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from personalai.app import create_app
from personalai.backup import export_backup, restore_backup
from personalai.models import CreateRecord, Decision
from personalai.model_client import SecretVault, call_model
from personalai.store import Store, StoreError
from personalai.tracking import TrackingService
from personalai.tracking_models import Goal, ModelConfig, Settings, WriteEntity, goal_progress, year_time


@pytest.fixture
def env(tmp_path):
    app = create_app(tmp_path / 'data', port=18765)
    with TestClient(app, base_url='http://127.0.0.1:18765') as client:
        token = client.get('/api/session').json()['csrf_token']
        client.headers['x-csrf-token'] = token
        yield app, client


def post(client, path, **body):
    response = client.post(path, json={'request_id': str(uuid4()), **body})
    assert response.status_code == 200, response.text
    return response.json()


def create_goal(client, **overrides):
    return post(client, '/api/goals', data={'title': '虚构：阅读示例书', 'criteria': '读完十章并留下笔记',
                'baseline': 0, 'target': 10, 'current': 2, **overrides})['entity']


def decide(client, change, choice='accept'):
    return post(client, '/api/changes/' + change['id'] + '/decision', decision=choice)


def configure(app, client):
    settings = Settings().model_dump(mode='json')
    settings['model'] = {'enabled': True, 'base_url': 'https://fictional.example/v1', 'model': 'synthetic', 'response_format': 'json_schema'}
    post(client, '/api/settings', data=settings)
    # In-memory test vault; production never produces a fake result.
    app.state.vault.read = lambda url: 'fictional-secret'
    return settings


def analysis_fixture(app, client):
    goal = create_goal(client)
    task = post(client, '/api/records', text='虚构：读第一章', date='2026-10-23', kind='task')['record']
    change = post(client, '/api/task-tracking', data={'task_id': task['id'], 'goal_id': goal['id']})['change']
    decide(client, change)
    log = post(client, '/api/activity-logs', data={'date': '2026-10-23', 'goal_id': goal['id'], 'task_id': task['id'], 'text': '虚构：读完第一章并写笔记'})['entity']
    configure(app, client)
    selection = {'goal_id': goal['id'], 'task_ids': [task['id']], 'log_ids': [log['id']]}
    preview = client.post('/api/analyses/preview', json=selection).json()
    request = {**selection, 'sources': preview['input']['sources'], 'settings_version': preview['settings_version'], 'approved': True, 'request_id': str(uuid4())}
    result = {'low': 10, 'high': 25, 'confidence': 'low', 'explanation': '虚构：仅依据一章的日志估计',
              'source_ids': [log['id']], 'contributions': [{'task_id': task['id'], 'relevance': 'direct', 'reason': '有阅读笔记', 'source_ids': [log['id']]}],
              'missing': ['其他章节情况'], 'suggestions': ['检查下一章的笔记']}
    return goal, task, log, request, result


def transport(result, seen=None):
    def respond(request):
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result, ensure_ascii=False)}}]})
    return httpx.MockTransport(respond)


@pytest.mark.parametrize('data,expected', [
    ({'baseline': 0, 'target': 10, 'current': 3}, 30),
    ({'baseline': 80, 'target': 60, 'current': 75}, 25),
    ({'baseline': 0, 'target': 10, 'current': 11}, 100),
    ({'baseline': 0, 'target': 10, 'current': None}, None),
    ({'baseline': -1e308, 'target': 1e308, 'current': 0}, 50),
    ({'mode': 'milestones', 'milestones': [{'title': 'A', 'weight': 3, 'progress': 100}, {'title': 'B', 'progress': 0}]}, 75),
    ({'mode': 'milestones', 'milestones': [{'title': 'A', 'progress': None}]}, None),
])
def test_progress(data, expected):
    assert goal_progress({'title': '虚构', 'criteria': '验收', **data}) == expected


def test_invalid_goal_and_year_boundaries():
    with pytest.raises(ValueError):
        Goal(title='x', criteria='y', baseline=10, target=10)
    with pytest.raises(ValueError):
        Goal(title='x', criteria='y', baseline=float('inf'))
    assert year_time(date(2024, 1, 1))['remaining_days'] == 366
    assert year_time(date(2024, 12, 31))['remaining_days'] == 1
    assert year_time(date(2025, 1, 1))['elapsed_percent'] == 0


def test_v1_unchanged_mixed_backup(env, tmp_path):
    app, c = env
    r = post(c, '/api/records', text='虚构旧记录', date='2026-10-23')['record']
    old_file = app.state.store.files[0]
    old_bytes = old_file.read_bytes()
    g = create_goal(c)
    post(c, '/api/check-ins', data={'date': '2026-10-23', 'slot': 'morning', 'response': '虚构早间回应'})
    assert old_file.read_bytes() == old_bytes
    reloaded = Store(app.state.store.root)
    assert not reloaded.errors and reloaded.get(r['id']).text == '虚构旧记录'
    assert reloaded.entities[g['id']].version == 1
    restored = restore_backup(export_backup(reloaded), tmp_path / 'restore')
    assert [p.read_bytes() for p in reloaded.files] == [p.read_bytes() for p in restored.files]


def test_goal_revisions_reject_stale_and_idempotent(env):
    app, c = env
    goal = create_goal(c)
    request = {'request_id': str(uuid4()), 'data': {**goal['data'], 'current': 3}, 'expected_version': 1}
    path = '/api/goals/' + goal['id']
    change = c.post(path, json=request).json()['change']
    assert c.post(path, json=request).json()['change'] == change
    stale = post(c, path, data={**goal['data'], 'current': 4}, expected_version=1)['change']
    assert app.state.store.entities[goal['id']].data['current'] == 2
    decide(c, change)
    assert c.post('/api/changes/' + stale['id'] + '/decision', json={'request_id': str(uuid4()), 'decision': 'accept'}).status_code == 409
    decide(c, stale, 'reject')
    assert app.state.store.entities[goal['id']].data['current'] == 3
    assert len(app.state.store.entity_history[goal['id']]) == 2


def test_logs_checkins_exports_and_unknown_task_progress(env):
    app, c = env
    goal = create_goal(c)
    task = post(c, '/api/records', text='虚构部分完成任务', kind='task', status='partial', date='2026-10-23')['record']
    assert c.get('/api/dashboard').json()['tasks'][0]['progress'] is None
    change = post(c, '/api/task-tracking', data={'task_id': task['id'], 'goal_id': goal['id'], 'progress': 30})['change']
    decide(c, change, 'reject')
    assert not any(e.kind == 'tracking' for e in app.state.store.entities.values())
    log = post(c, '/api/activity-logs', data={'date': '2026-10-23', 'text': '虚构：做完一顿饭', 'completed': True})['entity']
    response = post(c, '/api/check-ins', data={'date': '2026-10-23', 'slot': 'noon', 'response': '虚构：午间回应', 'goal_id': goal['id']})['entity']
    day = c.get('/api/dashboard?day=2026-10-23').json()
    assert day['logs'][0]['id'] == log['id'] and len(day['checkins']) == 1
    assert day['tasks'][0]['progress'] is None
    export = json.loads(c.get('/api/exports?day=2026-10-23&goal_id=' + goal['id']).json()['content'])
    assert not export['logs'] and export['checkins'][0]['id'] == response['id']
    assert 'settings' not in export and 'states' not in export
    noon = json.loads(c.get('/api/exports?day=2026-10-23&slot=morning').json()['content'])
    assert not noon['checkins']
    markdown = c.get('/api/exports?day=2026-10-23&format=markdown').json()['content']
    assert log['id'] in markdown and '虚构：午间回应' in markdown


def test_settings_approval_modules_and_archived_types(env):
    app, c = env
    settings = Settings(name='虚构展示名', hidden=['year'], order=list(reversed(Settings().order)), task_types=[{'id': 'reading', 'name': '阅读'}]).model_dump(mode='json')
    post(c, '/api/settings', data=settings)
    task = post(c, '/api/records', text='虚构任务', date='2026-10-23', kind='task')['record']
    change = post(c, '/api/task-tracking', data={'task_id': task['id'], 'tags': ['reading']})['change']
    decide(c, change)
    changed = {**settings, 'task_types': [{'id': 'reading', 'name': '阅读', 'active': False}]}
    change = post(c, '/api/settings', data=changed, expected_version=1)['change']
    assert c.get('/api/settings').json()['settings']['task_types'][0]['active']
    decide(c, change)
    assert not c.get('/api/settings').json()['settings']['task_types'][0]['active']
    assert c.post('/api/settings', json={'request_id': str(uuid4()), 'data': {**changed, 'task_types': []}, 'expected_version': 2}).status_code == 422
    assert Store(app.state.store.root).entities['settings'].data['hidden'] == ['year']


def test_analysis_explicit_selection_evidence_and_deduplication(env):
    app, c = env
    goal, task, log, request, result = analysis_fixture(app, c)
    post(c, '/api/records', text='不能发送的虚构私人记录', date='2026-10-23')
    seen = []
    app.state.model_transport = transport(result, seen)
    response = c.post('/api/analyses', json=request)
    assert response.status_code == 200, response.text
    analysis = response.json()['analysis']
    assert c.post('/api/analyses', json=request).json() == response.json()
    assert len(seen) == 1 and '不能发送' not in json.dumps(seen, ensure_ascii=False)
    assert app.state.store.entities[goal['id']].data['current'] == 2
    suggestion = next(e for e in app.state.store.entities.values() if e.kind == 'suggestion')
    decide(c, suggestion.model_dump(mode='json'), 'reject')
    assert len(app.state.store.records) == 2
    change = post(c, '/api/activity-logs/' + log['id'], data={**log['data'], 'text': '虚构更正'}, expected_version=1)['change']
    decide(c, change)
    assert c.get('/api/analyses').json()['analyses'][0]['stale']
    assert app.state.store.entities[analysis['id']].data['sources'][log['id']] == 1


def test_analysis_preview_stale_and_unconfigured(env):
    app, c = env
    goal = create_goal(c)
    selection = {'goal_id': goal['id']}
    preview = c.post('/api/analyses/preview', json=selection).json()
    assert not preview['ready']
    request = {**selection, 'request_id': str(uuid4()), 'approved': True, 'sources': preview['input']['sources'], 'settings_version': 0}
    assert c.post('/api/analyses', json=request).status_code == 422
    change = post(c, '/api/goals/' + goal['id'], data={**goal['data'], 'current': 3}, expected_version=1)['change']
    decide(c, change)
    assert c.post('/api/analyses', json=request).status_code == 409


@pytest.mark.parametrize('failure', ['source', 'no_log_evidence', 'interval', 'bad_json', 'refusal', '429', 'timeout', 'redirect'])
def test_model_failures_never_update_goal(env, failure):
    app, c = env
    goal, task, log, request, result = analysis_fixture(app, c)
    if failure == 'source':
        result['source_ids'] = ['invented']
    if failure == 'no_log_evidence':
        result['source_ids'] = [goal['id']]
    if failure == 'interval':
        result['low'], result['high'] = 80, 10
    def respond(req):
        if failure == 'timeout':
            raise httpx.ReadTimeout('synthetic')
        if failure == '429':
            return httpx.Response(429, text='Do not expose provider error')
        if failure == 'redirect':
            return httpx.Response(302, headers={'Location': 'https://unrelated.example'})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'refusal': 'refused' if failure == 'refusal' else None,
            'content': 'bad' if failure == 'bad_json' else json.dumps(result)}}]})
    app.state.model_transport = httpx.MockTransport(respond)
    assert c.post('/api/analyses', json=request).status_code in {502, 504}
    assert not any(e.kind == 'analysis' for e in app.state.store.entities.values())
    assert app.state.store.entities[goal['id']].data['current'] == 2


def test_key_protection_endpoint_binding_and_exclusion(env):
    app, c = env
    key = 'fictional-key-please-never-use'
    assert c.post('/api/settings/key', json={'base_url': 'https://fictional.example/v1', 'key': key}).status_code == 200
    vault = SecretVault(app.state.store.root)
    assert key.encode() not in vault.path.read_bytes()
    assert vault.read('https://fictional.example/v1') == key
    assert vault.read('https://other.example/v1') is None
    raw = export_backup(app.state.store)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert not any('.secrets' in name for name in z.namelist())
        assert all(key.encode() not in z.read(name) for name in z.namelist())
    for path in ['/data/.secrets/model-key.bin', '/.secrets/model-key.bin', '/personal/USER_PROFILE.md', '/README.md']:
        assert c.get(path).status_code == 404
    assert c.post('/api/goals', json={}, headers={'origin': 'https://evil.example'}).status_code == 403
    assert c.post('/api/settings/key', json={}, headers={'x-csrf-token': 'wrong'}).status_code == 403


def test_settings_reject_non_https_or_credential_urls():
    for url in ['http://example.com', 'https://secret@example.com', 'https://example.com?key=secret', 'https://example.com:bad', 'https://exam ple.com/v1']:
        with pytest.raises(ValueError):
            ModelConfig(base_url=url)


def test_extension_atomic_write_failure_and_corruption(tmp_path, monkeypatch):
    store = Store(tmp_path / 'data')
    service = TrackingService(store)
    request = WriteEntity(request_id=uuid4(), data={'title': '虚构', 'criteria': '验收'})
    with monkeypatch.context() as m:
        m.setattr('personalai.store.os.replace', lambda *args: (_ for _ in ()).throw(OSError('synthetic interruption')))
        with pytest.raises(StoreError):
            service.write('goal', request)
    assert not Store(store.root).entities
    result = service.write('goal', request)
    assert service.write('goal', request) == result
    path = store.files[0]
    path.write_bytes(path.read_bytes().replace('虚构'.encode(), '损坏'.encode()))
    assert Store(store.root).errors


def test_log_with_progress_proposal_is_atomic_and_separate(env):
    app, c = env
    task = post(c, '/api/records', text='虚构：阅读', date='2026-10-23', kind='task')['record']
    result = post(c, '/api/activity-logs', data={'date': '2026-10-23', 'task_id': task['id'], 'text': '虚构：完成一节'},
                  progress_update={'task_id': task['id'], 'progress': 25}, tracking_expected_version=0)
    assert result['entity']['kind'] == 'log' and result['related_change']['kind'] == 'change'
    assert 'tracking:' + task['id'] not in app.state.store.entities
    decide(c, result['related_change'], 'reject')
    assert app.state.store.entities[result['entity']['id']].data['text'] == '虚构：完成一节'
    assert 'tracking:' + task['id'] not in app.state.store.entities
    path = '/api/activity-logs'
    count = app.state.store.sequence
    response = c.post(path, json={'request_id': str(uuid4()), 'data': {'date': '2026-10-23', 'task_id': task['id'], 'text': '不可保存的虚构日志'},
                                 'progress_update': {'task_id': task['id'], 'progress': 50}, 'tracking_expected_version': 99})
    assert response.status_code == 409 and app.state.store.sequence == count


def test_test_connection_uses_only_synthetic_input(env):
    app, c = env
    configure(app, c)
    create_goal(c, title='不能发送的虚构真实目标')
    result = {'low': None, 'high': None, 'confidence': 'insufficient', 'explanation': '没有活动证据',
              'source_ids': [], 'contributions': [], 'missing': ['日志'], 'suggestions': []}
    seen = []
    app.state.model_transport = transport(result, seen)
    response = c.post('/api/settings/test')
    assert response.status_code == 200
    assert '不能发送' not in json.dumps(seen, ensure_ascii=False)
    assert not any(e.kind == 'analysis' for e in app.state.store.entities.values())


def test_unreadable_key_does_not_block_local_settings(env):
    app, c = env
    settings = Settings().model_dump(mode='json')
    settings['model'] = {'enabled': True, 'base_url': 'https://fictional.example/v1', 'model': 'synthetic', 'response_format': 'json_schema'}
    post(c, '/api/settings', data=settings)
    app.state.vault.path.parent.mkdir(parents=True, exist_ok=True)
    app.state.vault.path.write_bytes(b'invalid-DPAPI-data')
    assert c.get('/api/status').status_code == 200
    response = c.get('/api/settings').json()
    assert not response['model_ready'] and response['key_error']
    assert c.get('/api/dashboard').status_code == 200
