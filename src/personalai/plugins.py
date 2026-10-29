"""Trusted in-process plugin protocol v1. Explicit registration, no code discovery."""
from dataclasses import dataclass, field
from functools import wraps
import inspect
from typing import Callable
from uuid import uuid4
from pydantic import Field
from .models import StrictModel, Decision
from .tracking_models import WriteEntity
from .extensions import extension
from .store import StoreError

@dataclass
class Plugin:
    id: str
    name: str
    version: str = '1.0.0'
    protocol: int = 1
    dependencies: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    routes: tuple[str, ...] = ()
    pages: tuple[str, ...] = ()
    modules: tuple[str, ...] = ()
    types: dict = field(default_factory=dict)
    settings: type | None = None
    render: Callable | None = None
    setup: Callable | None = None
    start: Callable | None = None
    stop: Callable | None = None

class PluginContext:
    def __init__(self, manager, plugin):
        self.manager, self.plugin = manager, plugin
    def service(self, name):
        if name not in self.plugin.capabilities:
            raise StoreError('插件未声明所需能力：' + name, 403)
        return self.manager.services[name]
    def read(self):
        if 'data' not in self.plugin.capabilities:
            raise StoreError('插件未声明数据能力。',403)
        with self.manager.store.mutex:
            self.manager.store.reload(); self.manager.store.require_healthy()
            return [e for e in self.manager.store.entities.values() if e.kind.startswith(self.plugin.id+'/')]
    def write(self, kind, payload, identifier=None):
        if 'data' not in self.plugin.capabilities:
            raise StoreError('插件未声明数据能力。',403)
        return self.manager.write(self.plugin.id, kind, payload, identifier)
    def add_route(self, suffix, handler, methods=('GET',)):
        @wraps(handler)
        async def guarded(*args, **kwargs):
            try:
                result = handler(*args, **kwargs)
                return await result if inspect.isawaitable(result) else result
            except StoreError:
                raise
            except Exception as exc:
                self.manager.states[self.plugin.id].update(status='failed',reason='插件运行异常，已停止其入口；核心功能仍可使用。')
                if self.plugin.stop:
                    try: self.plugin.stop(self)
                    except Exception: pass
                raise StoreError('插件运行异常，原始资料未删除。',503) from exc
        self.manager.app.add_api_route('/api/plugins/' + self.plugin.id + suffix, guarded, methods=list(methods))

class PluginManager:
    def __init__(self, app, store, enabled, plugins=None):
        self.app, self.store = app, store
        self.definitions = {p.id:p for p in (plugins if plugins is not None else builtin_plugins())}
        self.requested, self.states, self.services = set(enabled), {}, {}
        self.contexts = {}
        self.started = []
        for identifier in self.definitions:
            self.resolve(identifier, set())
        for identifier in self.requested - self.definitions.keys():
            self.states[identifier] = {'id':identifier,'name':identifier,'status':'unavailable','reason':'插件未注册','pages':[],'modules':[]}
        store.module_ids = [m for p in self.definitions.values() for m in p.modules]
    def resolve(self, identifier, stack):
        if identifier in self.states:
            return self.states[identifier]['status'] == 'active'
        p = self.definitions[identifier]
        reason = ''
        if identifier not in self.requested:
            status = 'disabled'
        elif p.protocol != 1:
            status, reason = 'blocked', '插件协议版本不兼容'
        elif identifier in stack:
            status, reason = 'blocked', '插件依赖循环'
        else:
            status = 'active'
            for dep in p.dependencies:
                if dep not in self.definitions or not self.resolve(dep, stack | {identifier}):
                    status, reason = 'blocked', '依赖不可用：' + dep
                    break
        self.states[identifier] = {'id':p.id,'name':p.name,'version':p.version,'protocol':p.protocol,
            'status':status,'reason':reason,'dependencies':list(p.dependencies),'capabilities':list(p.capabilities),
            'pages':list(p.pages),'modules':list(p.modules),
            'settings_schema':p.settings.model_json_schema() if p.settings else None}
        return status == 'active'
    def active(self, identifier):
        if self.states.get(identifier,{}).get('status') != 'active': return False
        return all(self.active(dep) for dep in self.definitions[identifier].dependencies)
    def blocked_path(self, path):
        for identifier,p in self.definitions.items():
            if any(path == prefix or path.startswith(prefix + '/') for prefix in (*p.routes, '/api/plugins/' + identifier)):
                if not self.active(identifier):
                    return identifier
        return None
    def lifecycle(self, action):
        done = set()
        def visit(identifier):
            if identifier in done or self.states.get(identifier,{}).get('status') != 'active': return
            p = self.definitions[identifier]
            for dep in p.dependencies: visit(dep)
            done.add(identifier)
            if any(not self.active(dep) for dep in p.dependencies):
                self.states[identifier].update(status='blocked',reason='依赖启动失败'); return
            callback = getattr(p, action)
            if callback:
                try: callback(self.contexts.setdefault(identifier,PluginContext(self,p)))
                except Exception:
                    self.states[identifier].update(status='failed',reason='插件启动或停止失败，请检查该插件；原始记录保留。')
                    if action=='start' and p.stop:
                        try: p.stop(self.contexts[identifier])
                        except Exception: pass
            if action=='start' and self.active(identifier): self.started.append(identifier)
        ids = list(self.definitions)
        if action == 'stop':
            # Stop dependents before dependencies, including previously failed plugins.
            for identifier in reversed(self.started):
                p=self.definitions[identifier]
                if p.stop:
                    try: p.stop(self.contexts.setdefault(identifier,PluginContext(self,p)))
                    except Exception: pass
            self.started.clear()
            return
        for identifier in ids: visit(identifier)
    def validate(self, plugin, kind, data):
        if not self.active(plugin): raise StoreError('插件未启用，数据只读。',409)
        p = self.definitions[plugin]
        schema = p.settings if kind == 'settings' else p.types.get(kind)
        if not schema: raise StoreError('未注册的数据类型，只允许读取。',422)
        try: return schema.model_validate(data).model_dump(mode='json')
        except ValueError as exc: raise StoreError('插件数据格式错误。',422) from exc
    def write(self, plugin, kind, request, identifier=None):
        def prepare():
            key = f'plugin:{plugin}:settings' if kind=='settings' else identifier or str(uuid4())
            old = self.store.entities.get(key)
            if old and old.kind != plugin + '/' + kind: raise StoreError('数据类型不匹配。')
            if request.expected_version != (old.version if old else 0): raise StoreError('数据已更新。')
            value = self.validate(plugin,kind,request.data)
            p=self.definitions[plugin]
            if old:
                item=extension('core/plugin-change',{'target_id':key,'target_kind':plugin+'/'+kind,'before':old.data,'after':value,'expected_version':old.version,'status':'pending'})
                result={'change':item.model_dump(mode='json')}
            else:
                item=extension(plugin+'/'+kind,value,key,readable=p.render(kind,value) if p.render else '')
                result={'entity':item.model_dump(mode='json')}
            return [],[],result,[item]
        return self.store.transaction(request.request_id,'plugin-write:'+plugin+'/'+kind+':'+str(identifier),request.model_dump(mode='json'),prepare,extension=True)
    def decide(self, identifier, request):
        def prepare():
            item=self.store.entities.get(identifier)
            if not item or item.kind!='core/plugin-change' or item.data['status']!='pending': raise StoreError('未找到待确认修改。')
            out=[]
            if request.decision=='accept':
                d=item.data; old=self.store.entities.get(d['target_id'])
                if not old or old.version!=d['expected_version']: raise StoreError('修改已过期。')
                plugin,kind=d['target_kind'].split('/',1)
                value=self.validate(plugin,kind,d['after']); p=self.definitions[plugin]
                out.append(extension(old.kind,value,old.id,old,readable=p.render(kind,value) if p.render else ''))
            out.append(extension(item.kind,{**item.data,'status':'accepted' if request.decision=='accept' else 'rejected'},item.id,item))
            return [],[],{'entities':[e.model_dump(mode='json') for e in out]},out
        return self.store.transaction(request.request_id,'plugin-decision:'+identifier,request.model_dump(mode='json'),prepare,extension=True)

class ExampleEntry(StrictModel):
    text: str = Field(min_length=1,max_length=1000)
class ExampleSettings(StrictModel):
    heading: str = Field(default='扩展示例',min_length=1,max_length=80)

def example_setup(ctx):
    def hello(): return {'message':'插件路由已注册，记录通过核心服务保存。'}
    ctx.add_route('/hello',hello)

def builtin_plugins():
    return [
        Plugin('tracking','目标与任务',routes=('/api/goals','/api/task-tracking','/api/tasks'),pages=('plans',),modules=('goals','pending'),capabilities=('tracking',)),
        Plugin('journal','日常与回顾',routes=('/api/activity-logs','/api/check-ins'),pages=('capture','reports'),modules=('profile','year','logs','other','checkins'),capabilities=('tracking',)),
        Plugin('analysis','AI 分析',dependencies=('tracking','journal'),routes=('/api/analyses','/api/schedule','/api/scheduled-reports'),capabilities=('models','scheduler'),start=lambda c:c.service('scheduler').start(),stop=lambda c:c.service('scheduler').stop()),
        Plugin('dashboard','总览',dependencies=('tracking','journal'),routes=('/api/dashboard',),pages=('dashboard','journal')),
        Plugin('exchange','导出与读取',dependencies=('tracking','journal'),routes=('/api/exports','/api/integrations/v1')),
        Plugin('example','扩展示例',capabilities=('data',),pages=('example',),modules=('example',),types={'entry':ExampleEntry},settings=ExampleSettings,
               render=lambda kind,data: '## 扩展示例\n\n'+(data.get('text') or data.get('heading','')),setup=example_setup),
    ]

def register_plugins(app, store, enabled, config_path=None):
    manager=PluginManager(app,store,enabled)
    app.state.plugins=manager
    from .tracking import TrackingService
    from .configuration import ConfigService
    manager.services.update(tracking=TrackingService(store),models=app.state.goal_analysis,scheduler=app.state.scheduler)
    manager.lifecycle('setup')
    @app.get('/api/plugins')
    def plugins():
        for identifier, state in manager.states.items():
            if state['status']=='active' and not manager.active(identifier):
                state.update(status='blocked',reason='依赖运行异常')
        return {'protocol':1,'plugins':list(manager.states.values()),'restart_required':True}
    @app.get('/api/runtime')
    def runtime(): return {'host':'127.0.0.1','port':app.state.port,'data_dir':str(store.root),'config_file':config_path,
        'enabled_plugins':enabled,'restart_required':True,'precedence':'启动参数 > 配置文件 > 默认值'}
    @app.get('/api/plugin-data')
    def data(plugin: str | None=None):
        with store.mutex:
            store.reload(); store.require_healthy()
            return {'entities':[e for e in store.entities.values() if '/' in e.kind and not e.kind.startswith('core/') and (not plugin or e.kind.startswith(plugin+'/'))]}
    @app.get('/api/config/changes')
    def changes():
        with store.mutex:
            store.reload(); store.require_healthy()
            return {'changes':[e for e in store.entities.values() if e.kind in {'core/config-change','core/plugin-change'} and e.data['status']=='pending']}
    @app.post('/api/plugin-data/{plugin}/{kind}')
    def create(plugin:str,kind:str,payload:WriteEntity): return manager.write(plugin,kind,payload)
    @app.post('/api/plugin-data/{plugin}/{kind}/{identifier}')
    def update(plugin:str,kind:str,identifier:str,payload:WriteEntity): return manager.write(plugin,kind,payload,identifier)
    @app.post('/api/plugin-changes/{identifier}/decision')
    def decision(identifier:str,payload:Decision): return manager.decide(identifier,payload)
    return manager
