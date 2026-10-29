"""Versioned shared client API. All mutations pass through core transactions."""
import asyncio
import hashlib
import json
from datetime import date, datetime
from typing import Literal
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field, ValidationError

from .access import AGENT_SCOPES, RESOURCES, actor_context
from .configuration import ConfigService
from .task_routes import CreateTask, create_task_with_tracking
from .history_routes import search_history, task_event_items
from .client_views import permitted, project, RESOURCES as HISTORY_RESOURCES, PLUGINS
from .extensions import extension
from .integrations import integration_items
from .models import StrictModel, CreateRecord, RecordFields, ProposeRevision, Decision, TZ
from .reminders import validate_reminder, occurrences
from .store import StoreError, decode_event, digest
from .tracking import TrackingService, entity
from .tracking_models import WriteEntity, goal_progress, year_time
from .tracking_routes import Selection, Analyze
from .scheduling import PreviewSchedule, ConfirmSchedule, RunRequest

PREFIX = '/api/clients/v1'
KINDS = {'goal': 'goals', 'tracking': 'tasks', 'log': 'logs', 'checkin': 'checkins', 'profile': 'profile', 'core/reminder': 'reminders'}

FEATURES = {
    'atomic_task_create_v1': '本人设备原子创建任务及初始目标归属',
    'task_events_v1': '按保存日期查询授权范围内任务及目标动态',
    'history_search_v1': '按权限查询业务内容及旧修订',
    'report_coverage_v1': '报告覆盖日期、开始时间及模型名称',
    'goal_created_at_v1': '目标首次创建时间',
}


class ClientCapabilities(StrictModel):
    api_version: int
    client_id: str
    role: str
    scopes: list[str]
    offline: str
    reminder_days: int
    timezone: str
    notifications: bool
    features: dict[str, bool] = Field(description='Missing or false means unsupported. Stable names: ' + ', '.join(FEATURES))


class HistorySource(StrictModel):
    id: str
    version: int | None


class TaskEventItem(StrictModel):
    id: str
    task_id: str | None
    entity_id: str | None = None
    version: int
    time: str
    title: str
    action: str
    source: HistorySource


class HistoryItem(StrictModel):
    id: str
    kind: str
    title: str
    updated_at: str
    version: int | None
    matches: list[dict]
    history: list[dict]
    record: bool
    source: HistorySource


class TaskEventPage(StrictModel):
    items: list[TaskEventItem]
    total: int
    next_offset: int | None
    snapshot_version: int


class HistoryPage(TaskEventPage):
    items: list[HistoryItem]


class Login(StrictModel):
    password: str = Field(min_length=1, max_length=256)


class PairStart(StrictModel):
    name: str = Field(min_length=1, max_length=100)


class PairPoll(StrictModel):
    pairing_id: str = Field(max_length=80)
    poll_secret: str = Field(min_length=20, max_length=200)


class PairApprove(StrictModel):
    code: str = Field(pattern=r'^\d{8}$')


class Refresh(StrictModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class AgentGrant(PairStart):
    scopes: list[str] = Field(min_length=1, max_length=20)


class Command(StrictModel):
    request_id: UUID
    operation: Literal['create_task', 'create_record', 'revise_record', 'write_entity', 'decide', 'settings', 'model_binding', 'reminder', 'receipt']
    id: str | None = Field(default=None, max_length=200)
    kind: str | None = Field(default=None, max_length=50)
    expected_version: int = Field(default=0, ge=0)
    reason: str = Field(default='客户端提交', min_length=1, max_length=1000)
    data: dict


class DeviceOptions(StrictModel):
    notifications: bool
    push_registration: str | None = Field(default=None, max_length=200, pattern=r'^[A-Za-z0-9_-]+$')


class SyncAck(StrictModel):
    cursor: str = Field(min_length=1, max_length=300)


def require(principal, scope):
    if scope not in principal['scopes']:
        raise StoreError('没有这项操作的授权。', 403)


def read_items(store, principal, resource):
    items = _read_items(store, principal, resource)
    # Source labels come from server-authored audit entries in the same atomic event.
    # Cache only against the fully verified event-chain hash; no client-supplied actor.
    cached = getattr(store, '_client_origins', None)
    if not cached or cached[0] != store.last_hash:
        origins = {}
        for path in store.files:
            event = decode_event(path.read_bytes())
            audit = next((e for e in getattr(event, 'entities', []) if e.kind == 'core/client-audit'), None)
            if audit:
                for item in [*event.records, *event.proposals, *getattr(event, 'entities', [])]:
                    origins[str(item.id)] = {'actor_id': audit.data['actor_id'], 'role': audit.data['role'], 'timestamp': event.timestamp}
        store._client_origins = (store.last_hash, origins)
    return [{**item, 'origin': store._client_origins[1].get(item['id'])} for item in items]


def _read_items(store, principal, resource):
    if resource not in RESOURCES:
        raise StoreError('未知资料类型。', 404)
    require(principal, 'read:' + resource)
    if resource in {'goals', 'tasks', 'logs', 'checkins', 'reports'}:
        # Reports use the same redaction as integrations, excluding model endpoints.
        result = integration_items(store, resource)
        if resource == 'goals':
            for item in result:
                item['data'] = store.entities[item['id']].data
                item['created_at'] = store.entities[item['id']].created_at
        if resource == 'tasks':
            for item in result:
                record = store.records[item['id']]
                item['record'] = record.model_dump(mode='json')
                tracking = store.entities.get('tracking:' + item['id'])
                item['tracking'] = tracking.model_dump(mode='json') if tracking else None
        if resource == 'reports':
            for item in result:
                entity = store.entities[item['id']]
                item.update({k: entity.data.get(k) for k in ['window_start', 'window_end', 'started_at', 'model']})
        return result
    if resource == 'records':
        return [r.model_dump(mode='json') for r in store.records.values() if r.kind != 'task']
    if resource in {'profile', 'reminders'}:
        kind = {'profile': 'profile', 'reminders': 'core/reminder'}[resource]
        return [e.model_dump(mode='json') for e in store.entities.values() if e.kind == kind]
    if resource == 'settings':
        service = ConfigService(store)
        models = service.get('models')
        return [{'id': name, **service.get(name)} for name in ['user', 'ui', 'types']] + [{
            'id': 'models', 'version': models['version'], 'data': {
                'bindings': models['data']['bindings'],
                'connections': [{'id': c['id'], 'name': c['name'], 'enabled': c['enabled']} for c in models['data']['connections']]}}]
    if resource == 'pending':
        items = []
        for p in store.proposals.values():
            target = 'tasks' if p.action == 'create_task' or p.before and p.before.kind == 'task' else 'records'
            if p.status == 'pending' and 'read:' + target in principal['scopes']:
                items.append({'type': 'record', **p.model_dump(mode='json')})
        for e in store.entities.values():
            if e.data.get('target_kind') == 'state':
                continue
            if e.kind not in {'change', 'suggestion', 'core/client-change', 'core/config-change'} or e.data.get('status') != 'pending':
                continue
            if e.kind == 'core/config-change':
                # Model connection editing remains in the web administration UI.
                if principal['role'] == 'agent' or not set(e.data['sections']) <= {'user', 'ui', 'types'}:
                    continue
            elif e.kind == 'suggestion':
                if 'read:reports' not in principal['scopes']:
                    continue
            else:
                resource = KINDS.get(e.data.get('target_kind'), 'settings')
                if 'read:' + resource not in principal['scopes']:
                    continue
            items.append({'type': 'entity', **e.model_dump(mode='json')})
        return items
    raise StoreError('未知资料类型。', 404)


def cursor_tag(access, principal):
    owner = access.read()['owner']
    return hashlib.sha256((owner['salt'] + principal['id'] + ','.join(sorted(principal['scopes']))).encode()).hexdigest()[:24]


def cursor_for(store, access, principal):
    return f'{cursor_tag(access, principal)}:{store.sequence}:{store.last_hash or "empty"}'


def check_cursor(store, access, principal, cursor):
    try:
        tag, sequence, checksum = cursor.split(':')
        sequence = int(sequence)
        expected = digest(store.files[sequence - 1].read_bytes()) if sequence > 0 and sequence <= len(store.files) else 'empty'
        if tag != cursor_tag(access, principal) or sequence < 0 or sequence > store.sequence or checksum != expected:
            raise ValueError()
        return sequence
    except (ValueError, IndexError):
        raise StoreError('同步游标已失效，请重新获取快照。', 410)


def execute_command(app, store, principal, command):
    service = TrackingService(store)
    request_id = uuid5(NAMESPACE_URL, principal['id'] + ':' + str(command.request_id))
    data = command.data
    operation = command.operation
    def custom(kind, value, identifier, before=None):
        def prepare():
            item = extension(kind, value, identifier, before)
            return [], [], {'entity': item.model_dump(mode='json')}, [item]
        return store.transaction(request_id, 'client:' + operation, command.model_dump(mode='json'), prepare, extension=True)
    if operation == 'create_task':
        if principal['role'] != 'device':
            raise StoreError('原子创建任务仅对本人设备开放。', 403)
        require(principal, 'write:records')
        require(principal, 'read:tasks')
        require(principal, 'read:goals')
        if not app.state.plugins.active('tracking'):
            raise StoreError('任务插件未启用。', 409)
        return create_task_with_tracking(store, CreateTask.model_validate({**data, 'request_id': request_id}))
    if operation == 'create_record':
        require(principal, 'write:records')
        request = CreateRecord.model_validate({**data, 'request_id': request_id})
        if request.kind == 'task' and not app.state.plugins.active('tracking'):
            raise StoreError('任务插件未启用。', 409)
        if principal['role'] == 'agent' and request.kind != 'note':
            require(principal, 'propose')
            return store.propose_intent(request_id, RecordFields.model_validate(request.model_dump(exclude={'request_id', 'kind'})),
                                        'create_task' if request.kind == 'task' else 'create_idea', command.reason)
        return store.create(request)
    if operation == 'revise_record':
        require(principal, 'propose')
        before = store.get(command.id)
        require(principal, 'read:' + ('tasks' if before.kind == 'task' else 'records'))
        return store.propose_revision(command.id, ProposeRevision.model_validate({**data,
            'request_id': request_id, 'expected_version': command.expected_version, 'reason': command.reason}))
    if operation in {'write_entity', 'reminder'}:
        kind = 'core/reminder' if operation == 'reminder' else command.kind
        if kind not in KINDS:
            raise StoreError('不允许写入此资料类型。', 403)
        require(principal, 'read:' + KINDS[kind])
        owner = {'goal': 'tracking', 'tracking': 'tracking', 'log': 'journal', 'checkin': 'journal'}.get(kind)
        if owner and not app.state.plugins.active(owner):
            raise StoreError('所属插件未启用。', 409)
        important = kind in {'goal', 'tracking', 'profile', 'core/reminder'} or command.id
        require(principal, 'propose' if important else 'write:records')
        if kind == 'core/reminder':
            value = validate_reminder(store, data)
            before = store.entities.get(command.id)
            if before and before.kind != kind:
                raise StoreError('资料类型不匹配。', 422)
            if command.expected_version != (before.version if before else 0):
                raise StoreError('提醒已有更新，请重新预览。', 409)
            target_id = command.id or str(uuid4())
            if before or principal['role'] == 'agent':
                return custom('core/client-change', {'target_id': target_id, 'target_kind': kind, 'expected_version': command.expected_version,
                    'before': before.data if before else None, 'after': value, 'reason': command.reason, 'status': 'pending'}, str(uuid4()))
            return custom(kind, value, target_id)
        request = WriteEntity(request_id=request_id, data=data, expected_version=command.expected_version, reason=command.reason)
        if principal['role'] == 'agent' and kind == 'goal' and not command.id:
            value = service.validate(kind, data)
            if command.expected_version:
                raise StoreError('新目标版本应为零。', 409)
            def prepare():
                change = entity('change', {'target_id': str(uuid4()), 'target_kind': kind,
                    'expected_version': 0, 'before': None, 'after': value, 'reason': command.reason})
                return [], [], {'change': change.model_dump(mode='json')}, [change]
            return store.transaction(request_id, 'client:new-goal', command.model_dump(mode='json'), prepare, extension=True)
        return service.write(kind, request, command.id)
    if operation == 'settings':
        require(principal, 'settings')
        if command.kind not in {'user', 'ui', 'types'}:
            raise StoreError('此设置只能在网页管理。', 403)
        return ConfigService(store).save(command.kind, WriteEntity(request_id=request_id, data=data,
            expected_version=command.expected_version, reason=command.reason))
    if operation == 'model_binding':
        require(principal, 'settings')
        from .configuration import Bindings
        value = Bindings.model_validate(data).model_dump()
        current = ConfigService(store).get('models')
        if current['version'] != command.expected_version:
            raise StoreError('模型连接已有变化。', 409)
        ConfigService(store).validate('models', {**current['data'], 'bindings': value})
        return custom('core/client-change', {'target_kind': 'binding', 'target_id': 'config:models',
            'before': current['data']['bindings'], 'after': value, 'expected_version': command.expected_version,
            'reason': command.reason, 'status': 'pending'}, str(uuid4()))
    if operation == 'decide':
        require(principal, 'confirm')
        pending = next((p for p in read_items(store, principal, 'pending') if p['id'] == command.id), None)
        # Idempotent retries are checked by each core transaction before prepare.
        decision = Decision.model_validate({**data, 'request_id': request_id})
        if command.id in store.proposals:
            target = store.proposals[command.id]
            if (target.action == 'create_task' or target.before and target.before.kind == 'task') and not app.state.plugins.active('tracking'):
                raise StoreError('任务插件未启用。', 409)
            return store.decide(command.id, decision)
        item = store.entities.get(command.id)
        if not item:
            raise StoreError('未找到提案。', 404)
        if item.kind == 'core/client-change':
            def prepare():
                change = service.get(command.id)
                if change.data['status'] != 'pending':
                    raise StoreError('提案已经处理。', 409)
                output = []
                if decision.decision == 'accept':
                    d = change.data
                    before = store.entities.get(d['target_id'])
                    version = before.version if before else 0
                    if version != d['expected_version']:
                        raise StoreError('提案已过期，请重新预览。', 409)
                    if d['target_kind'] == 'core/reminder':
                        output.append(extension('core/reminder', validate_reminder(store, d['after']), d['target_id'], before))
                    elif d['target_kind'] == 'binding':
                        current = ConfigService(store).get('models')['data']
                        value = ConfigService(store).validate('models', {**current, 'bindings': d['after']})
                        output.append(extension('core/config', value, 'config:models', before))
                    else:
                        raise StoreError('不支持此提案。', 403)
                output.append(extension(item.kind, {**item.data, 'status': 'accepted' if decision.decision == 'accept' else 'rejected'}, item.id, item))
                return [], [], {'entities': [e.model_dump(mode='json') for e in output]}, output
            return store.transaction(request_id, 'client:decision:' + command.id, decision.model_dump(mode='json'), prepare, extension=True)
        if not pending and item.data.get('status') == 'pending':
            raise StoreError('此提案需要在网页管理界面确认。', 403)
        target_kind = item.data.get('target_kind', item.kind)
        owner = {'goal': 'tracking', 'tracking': 'tracking', 'log': 'journal', 'checkin': 'journal', 'suggestion': 'analysis'}.get(target_kind)
        if owner and not app.state.plugins.active(owner):
            raise StoreError('所属插件未启用。', 409)
        return service.decide(command.id, decision)
    if operation == 'receipt':
        require(principal, 'reminders')
        action = data.get('action')
        if action not in {'read', 'snooze'} or not command.id:
            raise StoreError('提醒操作无效。', 422)
        minutes = data.get('minutes', 10)
        if not isinstance(minutes, int) or not 1 <= minutes <= 1440:
            raise StoreError('稍后提醒应为 1–1440 分钟。', 422)
        key = 'receipt:' + digest((command.id + (principal['id'] if action == 'snooze' else '')).encode())
        return custom('core/receipt', {'message_id': command.id, 'action': action, 'minutes': minutes,
                      'device_id': principal['id'] if action == 'snooze' else None}, key, store.entities.get(key))
    raise StoreError('未知操作。', 422)


def register_clients(app, store):
    access = app.state.access
    def owner(request):
        if not access.owner_session(request.cookies.get('personalai_login', '')):
            raise StoreError('请先登录管理员。', 401)
    def principal(request):
        value = getattr(request.state, 'principal', None)
        if not value:
            owner(request)
            from .access import DEVICE_SCOPES
            return {'id': 'owner', 'role': 'owner', 'scopes': sorted(DEVICE_SCOPES)}
        return {**value, 'scopes': [s for s in value['scopes'] if s != 'read:states']}
    def reload():
        store.reload(); store.require_healthy()

    @app.get('/api/auth/status')
    def auth_status(request: Request):
        return {'required': access.configured() or bool(app.state.public_origin), 'configured': access.configured(),
                'authenticated': access.owner_session(request.cookies.get('personalai_login', ''))}

    @app.post('/api/auth/login')
    def login(payload: Login):
        token = access.login(payload.password)
        response = JSONResponse({'authenticated': True})
        response.set_cookie('personalai_login', token, httponly=True, samesite='strict', secure=bool(app.state.public_origin), max_age=43200)
        return response

    @app.post('/api/auth/logout')
    def logout(request: Request):
        access.logout(request.cookies.get('personalai_login', ''))
        response = JSONResponse({'authenticated': False}); response.delete_cookie('personalai_login')
        return response

    @app.get('/api/client-admin')
    def clients(request: Request):
        owner(request)
        return {**access.listing(), 'agent_scopes': sorted(AGENT_SCOPES)}

    @app.post('/api/client-admin/pairings/approve')
    def approve(request: Request, payload: PairApprove):
        owner(request); return access.approve(payload.code)

    @app.post('/api/client-admin/agents')
    def agent(request: Request, payload: AgentGrant):
        owner(request); return access.agent(payload.name, payload.scopes)

    @app.post('/api/client-admin/{identifier}/revoke')
    def revoke(identifier: str, request: Request):
        owner(request); return access.revoke(identifier)

    @app.post(PREFIX + '/pairings')
    def pair(payload: PairStart): return access.pair(payload.name)

    @app.post(PREFIX + '/pairings/poll')
    def poll(payload: PairPoll): return access.poll(payload.pairing_id, payload.poll_secret)

    @app.post(PREFIX + '/auth/refresh')
    def refresh(payload: Refresh): return access.refresh(payload.refresh_token)

    @app.get(PREFIX + '/capabilities', response_model=ClientCapabilities)
    def capabilities(request: Request):
        p = principal(request)
        return {'api_version': 1, 'client_id': p['id'], 'role': p['role'], 'scopes': p['scopes'],
                'offline': 'cache-and-drafts', 'reminder_days': 30, 'timezone': 'Asia/Shanghai',
                'notifications': p.get('notifications', False), 'features': {
                    'atomic_task_create_v1': p['role'] == 'device' and {'write:records','read:tasks','read:goals'} <= set(p['scopes']) and app.state.plugins.active('tracking'),
                    'task_events_v1': bool({'read:tasks','read:goals'} & set(p['scopes'])) and app.state.plugins.active('tracking'),
                    'history_search_v1': any('read:' + r in p['scopes'] and (r not in PLUGINS or app.state.plugins.active(PLUGINS[r])) for r in set(HISTORY_RESOURCES.values()) - {'reminders'}),
                    'report_coverage_v1': 'read:reports' in p['scopes'] and app.state.plugins.active('analysis'),
                    'goal_created_at_v1': 'read:goals' in p['scopes'] and app.state.plugins.active('tracking')}}

    @app.get(PREFIX + '/snapshot')
    def snapshot(request: Request):
        p = principal(request)
        with store.mutex:
            reload()
            result = {r: read_items(store, p, r) for r in sorted(RESOURCES) if 'read:' + r in p['scopes']}
            return {'api_version': 1, 'cursor': cursor_for(store, access, p), 'data': result,
                    'occurrences': occurrences(store) if 'read:reminders' in p['scopes'] else [],
                    'year': year_time(datetime.now(TZ).date()), 'synced_at': datetime.now(TZ).isoformat(),
                    'receipts': [e.model_dump(mode='json') for e in store.entities.values() if e.kind == 'core/receipt'
                                 and e.data.get('device_id') in {None, p['id']}] if 'read:reminders' in p['scopes'] else []}

    @app.get(PREFIX + '/changes')
    def changes(request: Request, cursor: str = Query(max_length=300)):
        p = principal(request)
        with store.mutex:
            reload(); sequence = check_cursor(store, access, p, cursor)
            changed_ids = set()
            for path in store.files[sequence:]:
                event = decode_event(path.read_bytes())
                changed_ids.update(str(e.id) for e in [*event.records, *event.proposals, *getattr(event, 'entities', [])])
            # Return changed entities plus replacement collections for derived views.
            result = {r: [e for e in read_items(store, p, r) if e['id'] in changed_ids or r in {'tasks', 'reports', 'settings', 'pending'}]
                      for r in sorted(RESOURCES) if 'read:' + r in p['scopes']}
            return {'cursor': cursor_for(store, access, p), 'data': result,
                    'replace': [r for r in ['tasks', 'reports', 'settings', 'pending'] if r in result],
                    'year': year_time(datetime.now(TZ).date()),
                    'receipts': [e.model_dump(mode='json') for e in store.entities.values() if e.kind == 'core/receipt'
                                 and e.data.get('device_id') in {None, p['id']}] if 'read:reminders' in p['scopes'] else [],
                    'occurrences': occurrences(store) if 'read:reminders' in p['scopes'] else []}

    @app.get(PREFIX + '/events')
    async def events(request: Request, cursor: str = Query(max_length=300)):
        p = principal(request)
        with store.mutex:
            reload(); check_cursor(store, access, p, cursor)
        async def stream():
            for _ in range(25):
                if await request.is_disconnected(): return
                try: principal(request) if p['id'] == 'owner' else access.authenticate(request.headers.get('authorization', '')[7:])
                except StoreError: return
                with store.mutex:
                    reload(); current = cursor_for(store, access, p)
                if current != cursor:
                    yield 'event: update\ndata: ' + json.dumps({'cursor': current}) + '\n\n'
                    return
                yield ': heartbeat\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})

    @app.get(PREFIX + '/resources/{resource}')
    def resource(resource: str, request: Request, day: str | None = None, goal_id: str | None = None,
                 task_id: str | None = None, limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
        p = principal(request)
        with store.mutex:
            reload(); items = read_items(store, p, resource)
            if day:
                parsed = app.state.parse_day(day).isoformat()
                items = [e for e in items if ((e.get('window_end') if e.get('kind') == 'scheduled_run' else datetime.fromisoformat(e.get('started_at') or e['updated_at']).astimezone(TZ).date().isoformat()) if resource == 'reports' else (e.get('date') or e.get('planned_date') or e.get('due') or e.get('data', {}).get('date') or str(e.get('updated_at', ''))[:10])) == parsed]
            if goal_id: items = [e for e in items if e['id'] == goal_id or e.get('goal_id') == goal_id or e.get('data', {}).get('goal_id') == goal_id or goal_id in e.get('sources', {})]
            if task_id: items = [e for e in items if e['id'] == task_id or e.get('task_id') == task_id or task_id in e.get('sources', {})]
            items.sort(key=lambda e: (datetime.fromisoformat(e.get('started_at') or e['updated_at']).timestamp() if resource == 'reports' else str(e.get('updated_at', '')), e['id']), reverse=True)
            return {'items': items[offset:offset + limit], 'total': len(items), 'next_offset': offset + limit if offset + limit < len(items) else None}

    @app.post(PREFIX + '/commands')
    def command(request: Request, payload: Command):
        p = principal(request)
        token = actor_context.set({'id': p['id'], 'role': p['role']})
        try:
            with store.mutex:
                reload()
                try: return execute_command(app, store, p, payload)
                except ValidationError: raise StoreError('字段格式不正确。', 422)
        finally: actor_context.reset(token)

    @app.post(PREFIX + '/device')
    def device(request: Request, payload: DeviceOptions):
        p = principal(request); require(p, 'reminders')
        return access.update_device(p['id'], **payload.model_dump())

    @app.post(PREFIX + '/sync/ack')
    def sync_ack(request: Request, payload: SyncAck):
        p = principal(request)
        if p['role'] != 'device': raise StoreError('仅设备可提交同步回执。', 403)
        with store.mutex:
            reload(); sequence = check_cursor(store, access, p, payload.cursor)
            access.update_device(p['id'], last_cursor=payload.cursor, last_sequence=sequence)
        return {'acknowledged': True, 'cursor': payload.cursor}

    @app.get(PREFIX + '/openapi.json')
    def schema(request: Request):
        principal(request)
        from fastapi.openapi.utils import get_openapi
        routes = [r for r in app.routes if getattr(r, 'path', '').startswith(PREFIX)]
        return get_openapi(title='PersonalAI Client API', version='1.0.0', routes=routes)

    def analysis_user(request):
        p = principal(request); require(p, 'analysis')
        if not app.state.plugins.active('analysis'):
            raise StoreError('分析插件未启用。', 409)
        return p

    def public_result(value):
        if isinstance(value, dict):
            return {k: public_result(v) for k, v in value.items() if k not in {'base_url', 'model_fingerprint'}}
        if isinstance(value, list): return [public_result(v) for v in value]
        return value

    @app.post(PREFIX + '/analyses/preview')
    def analysis_preview(request: Request, payload: Selection):
        analysis_user(request)
        return public_result(app.state.goal_analysis.preview(payload))

    @app.post(PREFIX + '/analyses')
    def analyze(request: Request, payload: Analyze):
        p = analysis_user(request)
        payload = payload.model_copy(update={'request_id': uuid5(NAMESPACE_URL, p['id'] + ':' + str(payload.request_id))})
        return public_result(app.state.goal_analysis.analyze(payload))

    @app.get(PREFIX + '/schedule')
    def schedule_status(request: Request):
        analysis_user(request)
        return public_result(app.state.scheduler.status())

    @app.post(PREFIX + '/schedule/preview')
    def schedule_preview(request: Request, payload: PreviewSchedule):
        analysis_user(request)
        return public_result(app.state.scheduler.preview(payload))

    @app.post(PREFIX + '/schedule/confirm')
    def schedule_confirm(request: Request, payload: ConfirmSchedule):
        p = analysis_user(request)
        payload = payload.model_copy(update={'request_id': uuid5(NAMESPACE_URL, p['id'] + ':' + str(payload.request_id))})
        return public_result(app.state.scheduler.confirm(payload))

    @app.post(PREFIX + '/schedule/pause')
    def schedule_pause(request: Request, payload: RunRequest):
        p = analysis_user(request)
        return public_result(app.state.scheduler.pause(payload.model_copy(update={'request_id': uuid5(NAMESPACE_URL, p['id'] + ':' + str(payload.request_id))})))

    @app.get(PREFIX + '/task-events', response_model=TaskEventPage)
    def task_events(request: Request, day: date | None = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
        p = principal(request)
        if not {'read:tasks','read:goals'} & set(p['scopes']):
            raise StoreError('没有动态读取权限。', 403)
        if not app.state.plugins.active('tracking'):
            raise StoreError('任务插件未启用。', 409)
        allowed = set()
        if 'read:tasks' in p['scopes']: allowed.add('task')
        if 'read:goals' in p['scopes']: allowed.add('goal')
        if {'task','goal'} <= allowed: allowed.add('tracking')
        with store.mutex:
            items = task_event_items(store, day or datetime.now(TZ).date(), allowed)['items']
            for item in items:
                item['source'] = {'id': item.get('entity_id') or item['task_id'], 'version': item['version']}
            return {'items': items[offset:offset+limit], 'total': len(items), 'next_offset': offset+limit if offset+limit<len(items) else None, 'snapshot_version': store.sequence}

    @app.get(PREFIX + '/history', response_model=HistoryPage)
    def history_search(request: Request, q: str = Query('', max_length=500), day: date | None = None,
                       kind: str = Query('', max_length=50), offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)):
        p = principal(request)
        if not any('read:' + r in p['scopes'] for r in set(HISTORY_RESOURCES.values()) - {'reminders'}):
            raise StoreError('没有历史读取权限。', 403)
        with store.mutex:
            result = search_history(store, q, day, kind, offset, limit,
                                    lambda k,v: permitted(app,p,k,v), project)
            for item in result['items']:
                item['source'] = {'id': item['id'], 'version': item['version']}
            return {**result, 'snapshot_version': store.sequence}

    @app.get(PREFIX + '/history/{identifier}')
    def history(identifier: str, request: Request):
        p = principal(request)
        with store.mutex:
            reload()
            record = store.records.get(identifier)
            item = record or store.entities.get(identifier) or store.proposals.get(identifier)
            if not item: raise StoreError('未找到可读取的历史。', 404)
            kind = item.kind if hasattr(item, 'kind') else 'proposal'
            if kind == 'core/config' and identifier == 'config:user': kind = 'profile'
            versions = store.history[identifier] if record else store.entity_history.get(identifier, [item])
            if not all(permitted(app, p, kind, v.model_dump(mode='json')) for v in versions):
                raise StoreError('没有这项历史读取授权。', 403)
            return {'items': [project(kind, v.model_dump(mode='json')) for v in versions]}
