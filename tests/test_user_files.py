"""Isolated storage acceptance; never reads the real user's profile or data."""
import io
import json
import re
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from personalai.app import create_app
from personalai.backup import export_backup, restore_backup, validate_archive
from personalai.models import CreateRecord, Decision, ProposeRevision
from personalai.store import Store, StoreError, digest
from personalai.tracking import TrackingService
from personalai.tracking_models import WriteEntity
from personalai.user_files import render_user_files, safe_id


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'data')


def write(store, kind, data, identifier=None, version=0):
    return TrackingService(store).write(kind, WriteEntity(request_id=uuid4(), data=data, expected_version=version), identifier)


def decide(store, change, decision='accept'):
    return TrackingService(store).decide(change['id'], Decision(request_id=uuid4(), decision=decision))


def note(store, **kwargs):
    return store.create(CreateRecord(request_id=uuid4(), date='2026-10-24', text='记录存储验收过程', **kwargs))['record']


def read(store, relative):
    return (store.root / 'user' / relative).read_text(encoding='utf-8')


def archive(files, version):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        for path, raw in files.items():
            z.writestr(path, raw)
        z.writestr('manifest.json', json.dumps({'format': version, 'files': {k: digest(v) for k, v in files.items()}}))
    return buffer.getvalue()


def test_initial_directory_has_readable_unknown_profile_without_import(tmp_path):
    private = tmp_path / 'personal'
    private.mkdir()
    (private / 'USER_PROFILE.md').write_text('仅旧访谈中的敏感内容', encoding='utf-8')
    store = Store(tmp_path / 'data')
    assert store.sequence == 0 and store.user_files_status()['healthy']
    body = read(store, 'profile/PROFILE.md')
    assert '个性与自我描述' in body and '未记录' in body and 'L1' in body
    assert all('仅旧访谈中的敏感内容' not in raw.decode('utf-8') for raw in render_user_files(store).values())
    assert 'goals/README.md' in read(store, 'README.md')


def test_profile_requires_confirmation_and_preserves_history(store):
    change = write(store, 'profile', {'personality': '喜欢先看整体，再处理细节'})['change']
    assert 'profile' not in store.entities
    assert '喜欢先看整体' not in read(store, 'profile/PROFILE.md')
    assert '喜欢先看整体' in read(store, f'confirmations/{change["id"]}.md')
    decide(store, change)
    assert '喜欢先看整体' in read(store, 'profile/PROFILE.md')
    before = {p.name: p.read_bytes() for p in store.files}
    rejected = write(store, 'profile', {'personality': '待拒绝的描述'}, 'profile', 1)['change']
    decide(store, rejected, 'reject')
    assert '待拒绝的描述' not in read(store, 'profile/PROFILE.md')
    accepted = write(store, 'profile', {'personality': '更新后的自我描述'}, 'profile', 1)['change']
    decide(store, accepted)
    assert store.entities['profile'].version == 2
    assert len(store.entity_history['profile']) == 2
    assert all((store.events_dir / name).read_bytes() == raw for name, raw in before.items())
    assert '更新后的自我描述' in read(store, 'profile/PROFILE.md')


def test_stale_profile_confirmation_cannot_replace_current_file(store):
    one = write(store, 'profile', {'personality': '第一份描述'})['change']
    two = write(store, 'profile', {'personality': '过期描述'})['change']
    decide(store, one)
    with pytest.raises(StoreError, match='过期'):
        decide(store, two)
    assert '第一份描述' in read(store, 'profile/PROFILE.md')
    assert '过期描述' not in read(store, 'profile/PROFILE.md')


def test_goal_task_links_only_follow_confirmed_changes(store):
    goal = write(store, 'goal', {'title': '本地记录验收', 'criteria': '完成四项检查', 'baseline': 0, 'target': 4})['entity']
    task = note(store, kind='task', status='partial')
    path = f'tasks/{task["id"]}.md'
    assert '任务自身进度：未知' in read(store, path)
    change = write(store, 'tracking', {'task_id': task['id'], 'goal_id': goal['id'], 'progress': 25})['change']
    assert f'../goals/{goal["id"]}.md' not in read(store, path)
    decide(store, change)
    assert f'../goals/{goal["id"]}.md' in read(store, path)
    assert '任务自身进度：25.0%' in read(store, path)
    assert '已确认进度：尚无法计算' in read(store, f'goals/{goal["id"]}.md')
    assert f'../tasks/{task["id"]}.md' in read(store, f'goals/{goal["id"]}.md')


def test_record_rename_keeps_file_path_and_all_source_links(store):
    record = note(store)
    proposal = store.propose_revision(record['id'], ProposeRevision(request_id=uuid4(), expected_version=1,
        date='2026-10-24', text='更正后的原始表述', reason='更正事实'))['proposal']
    store.decide(proposal['id'], Decision(request_id=uuid4(), decision='accept'))
    path = store.root / 'user' / 'records' / (record['id'] + '.md')
    body = path.read_text(encoding='utf-8')
    assert '更正后的原始表述' in body and '修订／处理 1' in body and '修订／处理 2' in body
    for relative in re.findall(r'\]\(([^)]+)\)', body):
        assert (path.parent / relative).resolve().exists()
    assert len(list(path.parent.glob('*.md'))) == 2  # one record and its index


def test_logs_checkins_and_state_have_distinct_readable_sections(store):
    log = write(store, 'log', {'date': '2026-10-24', 'text': '完成一项整理', 'completed': True})['entity']
    checkin = write(store, 'checkin', {'date': '2026-10-24', 'slot': 'morning', 'response': '继续检查'})['entity']
    state = write(store, 'state', {'date': '2026-10-24', 'energy': '尚可'})['entity']
    assert '已完成事项：是' in read(store, f'logs/{log["id"]}.md')
    assert '早上回顾' in read(store, f'checkins/{checkin["id"]}.md')
    assert 'L2' in read(store, f'states/{state["id"]}.md')
    assert '## 心情\n\n未记录' in read(store, f'states/{state["id"]}.md')


def test_readable_generation_failure_does_not_lose_or_duplicate_saved_record(store, monkeypatch):
    import personalai.user_files as module
    request = CreateRecord(request_id=uuid4(), date='2026-10-24', text='原文必须保留')
    with monkeypatch.context() as patch:
        patch.setattr(module, 'publish', lambda *_: (_ for _ in ()).throw(OSError('disk full')))
        result = store.create(request)
    assert store.sequence == 1 and not store.user_files_status()['healthy']
    assert store.get(result['record']['id']).text == '原文必须保留'
    assert store.create(request) == result  # retry repairs projection without a second event
    assert store.sequence == 1 and store.user_files_status()['healthy']


def test_manifest_is_committed_last_and_restart_repairs(store, monkeypatch):
    import personalai.user_files as module
    original = module.atomic_write
    def fail_manifest(path, raw):
        if path.name == '.manifest.json':
            raise OSError('interrupted after document writes')
        return original(path, raw)
    with monkeypatch.context() as patch:
        patch.setattr(module, 'atomic_write', fail_manifest)
        r = note(store)
    assert store.user_files_status()['sequence'] == 0
    assert store.get(r['id'])
    reopened = Store(store.root)
    assert reopened.user_files_status()['healthy']
    assert len(reopened.records) == 1


def test_manual_file_edits_are_preserved_before_refresh(store):
    r = note(store)
    target = store.root / 'user' / 'records' / (r['id'] + '.md')
    target.write_text('用户在外部编辑器留下的内容', encoding='utf-8')
    assert not store.user_files_status()['healthy']
    store.rebuild_user_files()
    preserved = list((store.root / 'user-edits').rglob('*.md'))
    assert any(p.read_text(encoding='utf-8') == '用户在外部编辑器留下的内容' for p in preserved)
    assert target.read_bytes() == render_user_files(store)[f'records/{r["id"]}.md']
    assert store.user_files_status()['preserved_count'] == 1
    assert store.get(r['id']).text == '记录存储验收过程'


@pytest.mark.parametrize('content', [b'broken', b'[]', b'{"files": []}'])
def test_deleted_file_and_corrupt_manifest_can_be_rebuilt(store, content):
    r = note(store)
    (store.root / 'user' / 'records' / (r['id'] + '.md')).unlink()
    (store.root / 'user' / '.manifest.json').write_bytes(content)
    assert not store.user_files_status()['healthy']
    assert store.rebuild_user_files()['healthy']
    assert read(store, f'records/{r["id"]}.md')


def test_corrupt_event_never_overwrites_last_readable_snapshot(store):
    r = note(store)
    old = read(store, f'records/{r["id"]}.md')
    store.files[0].write_bytes(b'broken event')
    reopened = Store(store.root)
    assert reopened.errors and not reopened.user_files_status()['healthy']
    assert read(store, f'records/{r["id"]}.md') == old


def test_backup_contains_readable_files_and_restores_identically(store, tmp_path):
    note(store)
    decide(store, write(store, 'profile', {'preferences': '先说结论'})['change'])
    files = validate_archive(export_backup(store))
    assert 'user/profile/PROFILE.md' in files and 'user/README.md' in files
    restored = restore_backup(export_backup(store), tmp_path / 'restored')
    assert render_user_files(store) == render_user_files(restored)
    assert all((restored.root / 'user' / name).read_bytes() == raw for name, raw in render_user_files(store).items())


def test_legacy_backup_still_restores_and_builds_readable_directory(store, tmp_path):
    note(store)
    original = {f'events/{p.name}': p.read_bytes() for p in store.files}
    restored = restore_backup(archive(original, 1), tmp_path / 'legacy')
    assert restored.user_files_status()['healthy']
    assert [p.read_bytes() for p in restored.files] == [p.read_bytes() for p in store.files]


def test_rehashed_but_inconsistent_readable_backup_is_rejected(store, tmp_path):
    note(store)
    files = validate_archive(export_backup(store))
    files['user/profile/PROFILE.md'] = b'contradicts events'
    with pytest.raises(StoreError, match='不一致'):
        restore_backup(archive(files, 2), tmp_path / 'tampered')
    assert not (tmp_path / 'tampered').exists()


@pytest.mark.parametrize('name', ['user/../secret.md', 'user/profile/../../secret.md', 'user/.secrets/key.md'])
def test_readable_backup_paths_are_restricted(name):
    with pytest.raises(StoreError):
        validate_archive(archive({'user/README.md': b'ok', name: b'bad'}, 2))


def test_settings_model_details_and_secret_files_not_in_readable_directory(store):
    write(store, 'settings', {'name': '本地档案', 'model': {'base_url': 'https://private-provider.example/v1'}})
    vault = store.root / '.secrets'
    vault.mkdir()
    (vault / 'model-key.bin').write_bytes(b'private-credential-value')
    docs = b'\n'.join(render_user_files(store).values())
    assert b'private-credential-value' not in docs and b'private-provider' not in docs
    assert all('.secrets' not in k for k in validate_archive(export_backup(store)))


def test_api_profile_permissions_and_private_readable_path(tmp_path):
    app = create_app(data_dir=tmp_path / 'data')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        assert client.post('/api/user-files/rebuild').status_code == 403
        assert client.post('/api/profile', json={}).status_code == 403
        token = client.get('/api/session').json()['csrf_token']
        client.headers['X-CSRF-Token'] = token
        assert client.get('/api/profile').json()['version'] == 0
        assert client.post('/api/user-files/rebuild').json()['healthy']
        for path in ['/data/user/README.md', '/data/user/profile/PROFILE.md', '/user/README.md']:
            assert client.get(path).status_code == 404
        response = client.post('/api/profile', json={'request_id': str(uuid4()), 'data': {'personality': '手动填写'}})
        assert response.status_code == 200 and 'change' in response.json()
        assert client.get('/api/profile').json()['profile']['personality'] == ''


def test_generated_identifiers_cannot_escape_directory():
    assert '/' not in safe_id('../../outside') and '\\' not in safe_id('..\\outside')
    assert safe_id('CON') != 'CON'


def test_linked_directory_is_refused_without_losing_event(store, monkeypatch):
    original = Path.is_junction
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'is_junction', lambda p: p == store.root / 'user' or original(p))
        r = note(store)
        assert not store.user_files_status()['healthy']
    assert store.get(r['id'])
    assert store.rebuild_user_files()['healthy']


def test_profile_is_not_automatically_included_in_goal_analysis(store):
    decide(store, write(store, 'profile', {'personality': '只在个人档案中保留的描述'})['change'])
    goal = write(store, 'goal', {'title': '本地记录验收', 'criteria': '完成检查'})['entity']
    inputs = TrackingService(store).analysis_input(goal['id'], [], [])
    assert '只在个人档案中保留的描述' not in json.dumps(inputs, ensure_ascii=False)
    assert 'profile' not in inputs['sources']
