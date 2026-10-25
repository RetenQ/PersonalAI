"""Independent, versioned settings with lazy, lossless legacy projections."""
from copy import deepcopy
from uuid import UUID
from typing import Literal
from pydantic import Field, model_validator
from fastapi import HTTPException
from .models import StrictModel, Decision
from .tracking_models import Settings, ModelConfig, TaskType, WriteEntity, MODULES
from .extensions import extension
from .store import StoreError
from .model_client import SecretVault, call_model

class UserSettings(StrictModel):
    name: str = Field(default='', max_length=100)
    bio: str = Field(default='', max_length=3000)
    focus: str = Field(default='', max_length=3000)

class UISettings(StrictModel):
    order: list[str] = Field(default_factory=lambda: MODULES.copy())
    hidden: list[str] = Field(default_factory=list)
    @model_validator(mode='after')
    def valid(self):
        if len(set(self.order)) != len(self.order) or not set(self.hidden) <= set(self.order):
            raise ValueError('重复或未知模块')
        return self

class TypeSettings(StrictModel):
    task_types: list[TaskType] = Field(default_factory=list, max_length=100)
    @model_validator(mode='after')
    def valid(self):
        if len({t.id for t in self.task_types}) != len(self.task_types):
            raise ValueError('重复类型')
        return self

class Connection(ModelConfig):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    name: str = Field(min_length=1, max_length=100)

class Bindings(StrictModel):
    goal: str | None = None
    schedule: str | None = None

class ModelSettings(StrictModel):
    connections: list[Connection] = Field(default_factory=list, max_length=30)
    bindings: Bindings = Field(default_factory=Bindings)
    @model_validator(mode='after')
    def valid(self):
        ids = {c.id for c in self.connections}
        if len(ids) != len(self.connections) or any(x and x not in ids for x in [self.bindings.goal, self.bindings.schedule]):
            raise ValueError('重复连接或无效绑定')
        return self

SCHEMAS = {'user': UserSettings, 'ui': UISettings, 'types': TypeSettings, 'models': ModelSettings}

class ConfigService:
    def __init__(self, store):
        self.store = store
    def legacy(self):
        e = self.store.entities.get('settings')
        return deepcopy(e.data if e else Settings().model_dump(mode='json'))
    def get(self, section):
        if section not in SCHEMAS:
            raise StoreError('未知设置分区', 404)
        item = self.store.entities.get('config:' + section)
        if item:
            return {'data': deepcopy(item.data), 'version': item.version, 'origin': 'section'}
        old = self.legacy()
        if section == 'models':
            data = {'connections': [{'id': 'legacy', 'name': '原有模型连接', **old['model']}],
                    'bindings': {'goal': 'legacy', 'schedule': 'legacy'}}
        else:
            data = {k: old[k] for k in SCHEMAS[section].model_fields}
        return {'data': data, 'version': 0, 'origin': 'legacy'}
    def combined(self):
        result = self.legacy()
        for section in ['user', 'ui', 'types']:
            result.update(self.get(section)['data'])
        result['model'] = {k:v for k,v in self.model('goal').items() if k in ModelConfig.model_fields}
        return result
    def version(self):
        if any('config:' + k in self.store.entities for k in SCHEMAS):
            return self.store.sequence
        old = self.store.entities.get('settings')
        return old.version if old else 0
    def model_version(self, feature):
        if 'config:models' not in self.store.entities:
            old=self.store.entities.get('settings')
            return old.version if old else 0
        from .store import digest, canonical
        return int(digest(canonical(self.model(feature)))[:12],16)
    def model(self, feature):
        # Preserve fingerprints and key lookup before first model-section write.
        if 'config:models' not in self.store.entities:
            return self.legacy()['model']
        section = self.get('models')['data']
        chosen = section['bindings'][feature]
        conn = next((c for c in section['connections'] if c['id'] == chosen), None)
        if not conn:
            return {**ModelConfig().model_dump(), 'connection_id': None}
        return {**{k:conn[k] for k in ModelConfig.model_fields}, 'connection_id': conn['id']}
    def key(self, config, legacy_vault=None):
        if 'connection_id' not in config or config['connection_id'] == 'legacy':
            return (legacy_vault or SecretVault(self.store.root)).read(config['base_url'])
        if not config['connection_id']:
            return None
        return connection_vault(self.store, config['connection_id']).read(config['base_url'])
    def validate(self, section, data):
        try:
            value = SCHEMAS[section].model_validate(data).model_dump(mode='json')
        except (ValueError, KeyError) as exc:
            raise StoreError('设置格式不正确，请检查字段、连接与绑定。', 422) from exc
        if section == 'types':
            old = {t['id'] for t in self.get('types')['data']['task_types']}
            if not old <= {t['id'] for t in value['task_types']}:
                raise StoreError('已有类型请停用，不要删除。', 422)
        if section == 'ui':
            available = set(getattr(self.store, 'module_ids', MODULES))
            if set(value['order']) != available:
                raise StoreError('模块已变化，请刷新设置后重试。', 409)
        return value
    def save(self, section, request):
        def prepare():
            current = self.get(section)
            if current['version'] != request.expected_version:
                raise StoreError('该分区已有更新，请刷新后重试。')
            value = self.validate(section, request.data)
            if section == 'ui':
                item = extension('core/config', value, 'config:' + section, self.store.entities.get('config:' + section))
                return [], [], {'entity': item.model_dump(mode='json')}, [item]
            item = extension('core/config-change', {'sections': {section: {'before': current['data'],
                'after': value, 'expected_version': current['version']}}, 'status': 'pending', 'reason': request.reason})
            return [], [], {'change': item.model_dump(mode='json')}, [item]
        return self.store.transaction(request.request_id, 'config:' + section, request.model_dump(mode='json'), prepare, extension=True)
    def legacy_save(self, request):
        def prepare():
            if request.expected_version != self.version():
                raise StoreError('设置已更新，请刷新。')
            compatible = deepcopy(request.data)
            compatible['order'] = MODULES.copy()
            compatible['hidden'] = [x for x in request.data.get('hidden',[]) if x in MODULES]
            try:
                legacy = Settings.model_validate(compatible).model_dump(mode='json')
            except ValueError as exc:
                raise StoreError('设置格式错误。',422) from exc
            legacy.update({k:request.data[k] for k in ['order','hidden']})
            changes = {}
            for section in ['user', 'ui', 'types']:
                current = self.get(section)
                value = {k:legacy[k] for k in SCHEMAS[section].model_fields}
                if value != current['data']:
                    changes[section] = {'before': current['data'], 'after': self.validate(section,value), 'expected_version': current['version']}
            if legacy['model'] != self.combined()['model']:
                current = self.get('models'); value = deepcopy(current['data'])
                selected = value['bindings']['goal']
                if not selected:
                    raise StoreError('目标分析未绑定连接，请先在模型分区选择。',409)
                for conn in value['connections']:
                    if conn['id']==selected: conn.update(legacy['model'])
                changes['models']={'before':current['data'],'after':self.validate('models',value),'expected_version':current['version']}
            item = extension('core/config-change', {'sections': changes, 'status': 'pending', 'reason': request.reason})
            return [], [], {'change': item.model_dump(mode='json')}, [item]
        return self.store.transaction(request.request_id, 'config:legacy', request.model_dump(mode='json'), prepare, extension=True)
    def decide(self, key, request):
        def prepare():
            item = self.store.entities.get(key)
            if not item or item.kind != 'core/config-change' or item.data['status'] != 'pending':
                raise StoreError('未找到待确认设置。')
            output = []
            if request.decision == 'accept':
                for section, change in item.data['sections'].items():
                    current = self.get(section)
                    if current['version'] != change['expected_version'] or current['data'] != change['before']:
                        raise StoreError('该分区已变化，不能覆盖新内容。')
                    value = self.validate(section, change['after'])
                    output.append(extension('core/config', value, 'config:' + section, self.store.entities.get('config:' + section)))
            output.append(extension(item.kind, {**item.data, 'status': 'accepted' if request.decision == 'accept' else 'rejected'}, item.id, item))
            return [], [], {'entities': [e.model_dump(mode='json') for e in output]}, output
        return self.store.transaction(request.request_id, 'config-decision:' + key, request.model_dump(mode='json'), prepare, extension=True)

def connection_vault(store, identifier):
    vault = SecretVault(store.root)
    if identifier != 'legacy':
        from .store import digest
        vault.path = store.root / '.secrets' / ('connection-' + digest(identifier.encode()) + '.bin')
    return vault

class KeyInput(StrictModel):
    base_url: str
    key: str = Field(min_length=1, max_length=4000)

class ConnectionRequest(StrictModel):
    connection_id: str

def register_configuration(app, store):
    service = ConfigService(store)
    @app.get('/api/config/sections')
    def sections():
        with store.mutex:
            store.reload(); store.require_healthy()
            result = {k: service.get(k) for k in SCHEMAS}
            modules = list(getattr(store, 'module_ids', MODULES))
            ui = result['ui']['data']
            ui['order'] = [i for i in ui['order'] if i in modules] + [i for i in modules if i not in ui['order']]
            ui['hidden'] = [i for i in ui['hidden'] if i in modules]
            return {'sections': result, 'modules': modules}
    @app.post('/api/config/sections/{section}')
    def save(section: str, payload: WriteEntity):
        return service.save(section, payload)
    @app.post('/api/config/changes/{identifier}/decision')
    def decide(identifier: str, payload: Decision):
        return service.decide(identifier, payload)
    @app.post('/api/config/connections/{identifier}/key')
    def key(identifier: str, payload: KeyInput):
        with store.mutex:
            store.reload(); store.require_healthy()
            conn = next((c for c in service.get('models')['data']['connections'] if c['id'] == identifier), None)
            if not conn or conn['base_url'] != payload.base_url or not payload.key.strip() or any(x in payload.key for x in ['\n','\r']):
                raise StoreError('连接已变化或密钥格式无效，请刷新。',422)
            connection_vault(store, identifier).save(conn['base_url'], payload.key.strip())
            return {'saved': True}
    @app.get('/api/config/connections/status')
    def statuses():
        with store.mutex:
            store.reload(); store.require_healthy()
            result = []
            for c in service.get('models')['data']['connections']:
                error = ''
                try:
                    ready = bool(connection_vault(store,c['id']).read(c['base_url']))
                except StoreError as exc:
                    ready, error = False, exc.message
                result.append({'id': c['id'], 'key_configured': ready, 'ready': ready and c['enabled'], 'error': error})
            return {'connections': result}
    @app.post('/api/config/connections/test')
    def test(payload: ConnectionRequest):
        with store.mutex:
            store.reload(); store.require_healthy()
            conn = next((c for c in service.get('models')['data']['connections'] if c['id'] == payload.connection_id), None)
            if not conn:
                raise HTTPException(404,'连接不存在')
            key = connection_vault(store, conn['id']).read(conn['base_url'])
        if not app.state.model_lock.acquire(blocking=False):
            raise StoreError('已有模型请求正在处理。')
        try:
            call_model(conn,key,{'goal': {'id':'sample-goal','title':'连接示例'},'tasks':[],'tracking':[],'logs':[],'sources':{'sample-goal':1}}, app.state.model_transport)
            return {'message':'示例连接通过，实际分析质量仍需验证。'}
        finally:
            app.state.model_lock.release()
