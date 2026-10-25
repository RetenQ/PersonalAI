import json
import threading
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field

from .models import Decision, StrictModel, TZ
from .model_client import SecretVault, call_model
from .store import StoreError, canonical, digest
from .tracking import TrackingService, entity, export_snapshot, markdown_export
from .tracking_models import ModelConfig, Profile, WriteEntity
from .configuration import ConfigService


class Selection(StrictModel):
    goal_id: UUID
    task_ids: list[UUID] = Field(default_factory=list, max_length=100)
    log_ids: list[UUID] = Field(default_factory=list, max_length=200)


class Analyze(Selection):
    request_id: UUID
    sources: dict[str, int]
    settings_version: int
    approved: Literal[True]


class SaveKey(StrictModel):
    base_url: str
    key: str = Field(min_length=1, max_length=4000)


def register_tracking(app, store, parse_day):
    service, vault = TrackingService(store), SecretVault(store.root)
    app.state.vault = vault
    app.state.model_transport = None  # Only tests inject a synthetic transport.
    analysis_lock = threading.Lock()
    app.state.model_lock = analysis_lock

    def refresh():
        store.reload()
        store.require_healthy()

    def settings_result():
        settings = service.settings()
        key_error = ''
        try:
            configured = bool(ConfigService(store).key(ConfigService(store).model('goal'), vault))
        except StoreError as exc:
            configured, key_error = False, exc.message
        return {'settings': settings, 'version': ConfigService(store).version(),
                'key_configured': configured, 'key_error': key_error, 'data_directory': str(store.root),
                'model_ready': configured and settings['model']['enabled']}

    @app.get('/api/settings')
    def get_settings():
        with store.mutex:
            refresh()
            return settings_result()

    @app.post('/api/settings')
    def save_settings(payload: WriteEntity):
        return service.write('settings', payload, 'settings')

    @app.get('/api/profile')
    def get_profile():
        with store.mutex:
            refresh()
            item = store.entities.get('profile')
            return {'profile': item.data if item else Profile().model_dump(mode='json'),
                    'version': item.version if item else 0}

    @app.post('/api/profile')
    def save_profile(payload: WriteEntity):
        return service.write('profile', payload, 'profile')

    @app.get('/api/user-files')
    def user_files_status():
        with store.mutex:
            refresh()
            return store.user_files_status()

    @app.post('/api/user-files/rebuild')
    def rebuild_user_files():
        return store.rebuild_user_files()

    @app.post('/api/settings/key')
    def save_key(payload: SaveKey):
        try:
            ModelConfig(base_url=payload.base_url)
        except ValueError:
            raise HTTPException(422, '请填写有效的 HTTPS 服务地址')
        if not payload.base_url or not payload.key.strip() or '\n' in payload.key or '\r' in payload.key:
            raise HTTPException(422, '服务地址或密钥不正确')
        vault.save(payload.base_url, payload.key.strip())
        return {'saved': True}

    @app.post('/api/settings/test')
    def test_model():
        with store.mutex:
            refresh()
            config = ConfigService(store).model('goal')
        # No personal content is read into this synthetic request.
        assessment = call_model(config, ConfigService(store).key(config, vault), {
            'goal': {'id': 'sample-goal', 'title': '连接测试：读完一本示例书', 'criteria': '阅读十章'},
            'tasks': [], 'tracking': [], 'logs': [], 'sources': {'sample-goal': 1}}, app.state.model_transport)
        return {'message': '示例数据连接及格式校验通过；尚未验证真实目标分析质量。', 'assessment': assessment}

    def add_collection(path, kind):
        def listing():
            with store.mutex:
                refresh()
                return {'entities': [e for e in store.entities.values() if e.kind == kind]}
        def create(payload: WriteEntity):
            return service.write(kind, payload)
        def update(identifier: str, payload: WriteEntity):
            with store.mutex:
                refresh()
                service.get(identifier, kind)
            return service.write(kind, payload, identifier)
        app.add_api_route(path, listing, methods=['GET'], name=kind + '_list')
        app.add_api_route(path, create, methods=['POST'], name=kind + '_create')
        app.add_api_route(path + '/{identifier}', update, methods=['POST'], name=kind + '_update')

    for path, kind in [('/api/goals', 'goal'), ('/api/task-tracking', 'tracking'), ('/api/activity-logs', 'log'),
                       ('/api/check-ins', 'checkin'), ('/api/current-state', 'state')]:
        add_collection(path, kind)

    @app.get('/api/entities/{identifier}')
    def get_entity(identifier: str):
        with store.mutex:
            refresh()
            return {'entity': service.get(identifier), 'history': store.entity_history[identifier]}

    @app.post('/api/changes/{identifier}/decision')
    def decide(identifier: str, payload: Decision):
        with store.mutex:
            refresh()
            item=service.get(identifier)
            target=item.data.get('target_kind',item.kind)
            owner={'goal':'tracking','tracking':'tracking','log':'journal','checkin':'journal','state':'journal','suggestion':'analysis'}.get(target)
            if payload.decision=='accept' and owner and not app.state.plugins.active(owner):
                raise StoreError('所属插件未启用，不能接受此修改。',409)
        return service.decide(identifier, payload)

    @app.get('/api/dashboard')
    def dashboard(day: str = '今天', verify_user_files: bool = True):
        with store.mutex:
            refresh()
            return service.snapshot(parse_day(day), include_user_files=verify_user_files)

    @app.get('/api/exports')
    def export(day: str = '今天', goal_id: UUID | None = None,
               slot: Literal['morning', 'noon', 'evening'] | None = None, format: Literal['json', 'markdown'] = 'json'):
        with store.mutex:
            refresh()
            if goal_id:
                service.get(str(goal_id), 'goal')
            snapshot = export_snapshot(service.snapshot(parse_day(day), str(goal_id) if goal_id else None, slot, include_user_files=False))
        return {'filename': f'personalai-progress-{snapshot["date"]}.{"md" if format == "markdown" else "json"}',
                'content': markdown_export(snapshot) if format == 'markdown' else json.dumps(snapshot, ensure_ascii=False, indent=2)}

    def selected(payload):
        return service.analysis_input(str(payload.goal_id), [str(i) for i in payload.task_ids], [str(i) for i in payload.log_ids])

    @app.post('/api/analyses/preview')
    def preview(payload: Selection):
        with store.mutex:
            refresh()
            state = settings_result()
            return {'input': selected(payload), 'settings_version': ConfigService(store).model_version('goal'),
                    'model': ConfigService(store).model('goal'), 'ready': state['model_ready']}

    @app.get('/api/analyses')
    def list_analyses():
        with store.mutex:
            refresh()
            return {'analyses': service.snapshot(datetime.now(TZ).date(), include_user_files=False)['analyses']}

    @app.post('/api/analyses')
    def analyze(payload: Analyze):
        if not analysis_lock.acquire(blocking=False):
            raise StoreError('已有模型请求正在处理，请等待完成。', 409)
        try:
            operation = 'analyze'
            fingerprint = digest(canonical({'operation': operation, 'payload': payload.model_dump(mode='json')}))
            with store.mutex:
                refresh()
                previous = store.requests.get(str(payload.request_id))
                if previous:
                    if previous.fingerprint != fingerprint:
                        raise StoreError('请求编号已用于不同内容。')
                    return previous.result
                inputs = selected(payload)
                state = settings_result()
                if inputs['sources'] != payload.sources or ConfigService(store).model_version('goal') != payload.settings_version:
                    raise StoreError('资料或模型配置已变化，请重新预览后分析。')
                config = ConfigService(store).model('goal')
            assessment = call_model(config, ConfigService(store).key(config, vault), inputs, app.state.model_transport)
            def prepare():
                analysis = entity('analysis', {'goal_id': str(payload.goal_id), 'model': config['model'], 'base_url': config['base_url'],
                    'sources': inputs['sources'], 'assessment': assessment.model_dump(mode='json')})
                suggestions = [entity('suggestion', {'analysis_id': analysis.id, 'goal_id': str(payload.goal_id), 'text': text}) for text in assessment.suggestions]
                return [], [], {'analysis': analysis.model_dump(mode='json')}, [analysis, *suggestions]
            return store.transaction(payload.request_id, operation, payload.model_dump(mode='json'), prepare, extension=True)
        finally:
            analysis_lock.release()

    from types import SimpleNamespace
    app.state.goal_analysis = SimpleNamespace(preview=preview, analyze=analyze)
