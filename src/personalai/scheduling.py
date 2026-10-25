"""Local, consent-scoped scheduling. No OS jobs, notifications or automatic retries."""
import json
import threading
import time
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import portalocker
from pydantic import Field
from typing import Literal

from .models import StrictModel, TZ
from .model_client import call_model
from .configuration import ConfigService
from .scheduled_models import Schedule, ScheduleOptions, report_markdown
from .store import StoreError, canonical, digest
from .tracking import TrackingService, entity
from .user_files import atomic_write, check_path


class PreviewSchedule(StrictModel):
    data: ScheduleOptions
    expected_version: int = Field(ge=0)


class ConfirmSchedule(StrictModel):
    request_id: UUID
    approval_token: str
    approved: Literal[True]


class RunRequest(StrictModel):
    request_id: UUID


class Scheduler:
    def __init__(self, app, store):
        self.app, self.store = app, store
        self.service = TrackingService(store)
        self.clock = lambda: datetime.now(TZ)
        self.previews = {}
        self.guard = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.last_error = ''
        self.leader = False

    def refresh(self):
        self.store.reload()
        self.store.require_healthy()

    def config(self):
        item = self.store.entities.get('schedule')
        return (item.data if item else Schedule().model_dump(mode='json'), item.version if item else 0)

    def model(self):
        return ConfigService(self.store).model('schedule')

    def arm_path(self):
        return check_path(self.store.root, '.scheduler/consent.json')

    def authorized(self, config, version):
        if not config['enabled'] or config['model_fingerprint'] != digest(canonical(self.model())):
            return False
        try:
            return json.loads(self.arm_path().read_text('utf-8')) == {'version': version, 'fingerprint': digest(canonical(config))}
        except (OSError, ValueError):
            return False

    def inputs(self, scopes, at):
        end, start = at.date(), at.date() - timedelta(days=6)
        items = []
        for r in self.store.records.values():
            if r.kind == 'note' and 'records' in scopes and start <= r.date <= end:
                items.append(r.model_dump(mode='json'))
            elif r.kind == 'task' and 'tasks' in scopes and r.date <= end and (r.status != 'done' or r.date >= start):
                items.append(r.model_dump(mode='json'))
        task_ids = {i['id'] for i in items if i['kind'] == 'task'}
        for e in self.store.entities.values():
            if e.kind == 'goal' and 'goals' in scopes or e.kind == 'tracking' and e.data['task_id'] in task_ids:
                items.append(e.model_dump(mode='json'))
            elif e.kind in {'log', 'checkin', 'state'}:
                scope = {'log': 'logs', 'checkin': 'checkins', 'state': 'states'}[e.kind]
                if scope in scopes and start.isoformat() <= e.data['date'] <= end.isoformat():
                    items.append(e.model_dump(mode='json'))
        inputs = {'timezone': 'Asia/Shanghai', 'window_start': start.isoformat(), 'window_end': end.isoformat(),
                  'sampled_at': at.isoformat(timespec='seconds'), 'items': items,
                  'sources': {i['id']: i['version'] for i in items}}
        if len(items) > 300 or len(canonical(inputs)) > 128 * 1024:
            raise StoreError('本次资料超过 300 项或 128 KiB，请缩小授权资料类型；未发送、未截断。', 422)
        return inputs

    def status(self):
        with self.guard, self.store.mutex:
            self.refresh()
            config, version = self.config()
            consent = self.authorized(config, version)
            try:
                ready = self.model()['enabled'] and bool(ConfigService(self.store).key(self.model(), self.app.state.vault))
            except StoreError:
                ready = False
            at = self.clock()
            upcoming = [datetime.combine(at.date() + timedelta(days=d), datetime.strptime(t, '%H:%M').time(), TZ)
                        for d in [0, 1] for t in config['times']]
            next_at = min((x for x in upcoming if x > at), default=None)
            return {'config': config, 'version': version, 'authorized': consent, 'model_ready': ready,
                    'active': consent and ready, 'leader': self.leader, 'error': self.last_error,
                    'next_at': next_at.isoformat() if next_at and consent and ready else None,
                    'notice': '服务运行时按时开始生成；关闭后只补最近一次。提醒发送由外部应用承担。'}

    def preview(self, payload):
        with self.guard, self.store.mutex:
            self.refresh()
            before, version = self.config()
            if payload.expected_version != version:
                raise StoreError('定时设置已变化，请刷新后预览。')
            at = self.clock()
            inputs = self.inputs(payload.data.scopes, at)
            token = str(uuid4())
            self.previews = {k: v for k, v in self.previews.items() if time.monotonic() - v['created'] < 600}
            if len(self.previews) >= 50:
                raise StoreError('预览过多，请稍后再试。', 429)
            self.previews[token] = {'data': payload.data.model_dump(), 'version': version,
                                    'model': self.model(), 'created': time.monotonic()}
            return {'approval_token': token, 'before': before, 'after': payload.data.model_dump(),
                    'input': inputs, 'model': self.model(),
                    'notice': '确认启用后，将自动发送所选类型的当天及近七天资料（包括以后新增的记录），无需逐次确认。未选类型、私人画像和访谈档案不发送。可能产生模型费用；可随时暂停。'}

    def confirm(self, payload):
        with self.guard, self.store.mutex:
            def prepare():
                preview = self.previews.get(payload.approval_token)
                if not preview or time.monotonic() - preview['created'] >= 600:
                    raise StoreError('预览已过期，请重新预览。')
                _, version = self.config()
                if version != preview['version'] or self.model() != preview['model']:
                    raise StoreError('定时设置或模型已变化，请重新预览。')
                config = Schedule(**preview['data'], model_fingerprint=digest(canonical(self.model())),
                                  effective_from=self.clock().isoformat(timespec='seconds')).model_dump()
                if config['enabled'] and (not self.model()['enabled'] or not ConfigService(self.store).key(self.model(), self.app.state.vault)):
                    raise StoreError('请先保存并启用模型配置与匹配密钥；不会自动启用。', 422)
                item = entity('schedule', config, 'schedule', self.store.entities.get('schedule'))
                return [], [], {'entity': item.model_dump(mode='json')}, [item]
            result = self.store.transaction(payload.request_id, 'schedule-confirm', payload.model_dump(mode='json'), prepare, extension=True)
            # Local arming is deliberately outside backup; a restored schedule cannot send data.
            current, version = self.config()
            if version == result['entity']['version'] and current['enabled'] and not self.authorized(current, version):
                preview = self.previews.get(payload.approval_token)
                if (not preview or time.monotonic() - preview['created'] >= 600
                        or preview['model'] != self.model() or preview['version'] + 1 != version):
                    raise StoreError('设置已保存，但本机启用授权已失效，请重新预览并确认。')
                try:
                    atomic_write(self.arm_path(), canonical({'version': version, 'fingerprint': digest(canonical(current))}))
                except OSError as exc:
                    raise StoreError('设置已保存，但本机授权文件保存失败；定时分析未启用，请重试。', 503) from exc
            return result

    def pause(self, payload):
        with self.guard, self.store.mutex:
            def prepare():
                config, _ = self.config()
                item = entity('schedule', {**config, 'enabled': False}, 'schedule', self.store.entities.get('schedule'))
                return [], [], {'entity': item.model_dump(mode='json')}, [item]
            return self.store.transaction(payload.request_id, 'schedule-pause', payload.model_dump(mode='json'), prepare, extension=True)

    def update_run(self, identifier, changes):
        def prepare():
            before = self.store.entities[identifier]
            item = entity('scheduled_run', {**before.data, **changes}, identifier, before)
            return [], [], {'run': item.model_dump(mode='json')}, [item]
        return self.store.transaction(uuid4(), 'schedule-result', {'id': identifier, **changes}, prepare, extension=True)

    def execute(self, manual_id=None):
        # Across processes, hold this lock through the network call and final commit.
        try:
            with portalocker.Lock(str(check_path(self.store.root, '.scheduled-run.lock')), timeout=0):
                return self._execute(manual_id)
        except portalocker.exceptions.LockException:
            if manual_id:
                raise StoreError('已有定时分析正在处理，请稍后查看结果。')
            return None

    def _execute(self, manual_id=None):
        if not self.app.state.model_lock.acquire(blocking=False):
            if manual_id:
                raise StoreError('已有模型分析正在处理，请稍后再试。')
            return None
        try:
            with self.guard, self.store.mutex:
                self.refresh()
                at = self.clock()
                # No live scheduler can own a running job while this process holds the run lock.
                for old in list(self.store.entities.values()):
                    if old.kind == 'scheduled_run' and old.data['status'] == 'running':
                        self.update_run(old.id, {'status': 'interrupted', 'finished_at': at.isoformat(),
                            'message': '上次运行中断，供应商是否完成调用未知；为避免重复费用，没有自动重试。'})
                config, version = self.config()
                if manual_id:
                    identifier = 'manual-' + digest(str(manual_id).encode())
                    if identifier in self.store.entities:
                        return self.detail(identifier)
                if not self.authorized(config, version):
                    if manual_id:
                        raise StoreError('请先预览并确认启用定时分析；模型变更或备份恢复后需重新确认。', 422)
                    return None
                slots = [datetime.combine(at.date() - timedelta(days=d), datetime.strptime(t, '%H:%M').time(), TZ)
                         for d in [0, 1] for t in config['times']]
                effective = datetime.fromisoformat(config['effective_from'])
                due = at if manual_id else max((x for x in slots if effective <= x <= at), default=None)
                if due is None:
                    return None
                if not manual_id and any(e.kind == 'scheduled_run' and e.data['trigger'] == 'scheduled'
                        and e.data['schedule_version'] == version
                        and datetime.fromisoformat(e.data['scheduled_at']) >= due for e in self.store.entities.values()):
                    return None  # Earlier missed slots stay coalesced even after clock rollback.
                identifier = ('manual-' + digest(str(manual_id).encode())) if manual_id else 'scheduled-' + digest(f'{version}:{due.isoformat()}'.encode())
                if identifier in self.store.entities:
                    return None
                model = self.model()
                failure = ''
                try:
                    inputs = self.inputs(config['scopes'], at)
                except StoreError as exc:
                    failure = exc.message
                    inputs = {'window_start': (at.date() - timedelta(days=6)).isoformat(), 'window_end': at.date().isoformat(),
                              'sampled_at': at.isoformat(), 'sources': {}, 'items': []}
                data = {'scheduled_at': due.isoformat(), 'started_at': at.isoformat(), 'schedule_version': version,
                        'trigger': 'manual' if manual_id else 'scheduled', 'status': 'running',
                        'window_start': inputs['window_start'], 'window_end': inputs['window_end'], 'sampled_at': inputs['sampled_at'],
                        'model': model['model'], 'base_url': model['base_url'], 'sources': inputs['sources'],
                        'source_labels': {i['id']: (i.get('text') or i.get('data', {}).get('title') or i.get('data', {}).get('text') or i.get('data', {}).get('response') or i['kind'])[:120] for i in inputs['items']},
                        'source_kinds': {i['id']: i['kind'] for i in inputs['items']}, 'input_hash': digest(canonical(inputs))}
                def prepare():
                    item = entity('scheduled_run', data, identifier)
                    return [], [], {'run': item.model_dump(mode='json')}, [item]
                self.store.transaction(uuid4(), 'schedule-start', {'id': identifier}, prepare, extension=True)
            try:
                if failure:
                    raise StoreError(failure, 422)
                if not inputs['items']:
                    return self.update_run(identifier, {'status': 'skipped', 'finished_at': self.clock().isoformat(),
                        'message': '授权范围内没有资料，未调用模型；未记录不等于未完成。'})
                # Recheck consent immediately before handing data to the provider.
                with self.guard, self.store.mutex:
                    self.refresh()
                    current, current_version = self.config()
                    if current_version != version or not self.authorized(current, current_version):
                        raise StoreError('设置或授权已变化，未发送资料。')
                    key = ConfigService(self.store).key(model, self.app.state.vault)
                assessment = call_model(model, key, inputs, self.app.state.model_transport, report=True)
                return self.update_run(identifier, {'status': 'succeeded', 'finished_at': self.clock().isoformat(),
                    'message': 'AI 分析已生成；建议未执行。补跑以实际执行日为当天，不回填过去的事实。',
                    'assessment': assessment.model_dump(mode='json')})
            except StoreError as exc:
                return self.update_run(identifier, {'status': 'failed', 'finished_at': self.clock().isoformat(), 'message': exc.message})
            except Exception:
                # Never store provider payloads, credentials or arbitrary exception strings.
                return self.update_run(identifier, {'status': 'failed', 'finished_at': self.clock().isoformat(),
                    'message': '分析发生内部错误，未自动重试；原始记录不受影响。'})
        finally:
            self.app.state.model_lock.release()

    def detail(self, identifier):
        item = self.service.get(identifier, 'scheduled_run')
        versions = {**{str(r.id): r.version for r in self.store.records.values()},
                    **{e.id: e.version for e in self.store.entities.values()}}
        return {'run': item.model_dump(mode='json'), 'stale': any(versions.get(k) != v for k, v in item.data['sources'].items())}

    def runs(self, limit=50, offset=0):
        with self.store.mutex:
            self.refresh()
            # Dict insertion order is the persistent creation order when timestamps tie.
            indexed = [(i, e) for i, e in enumerate(self.store.entities.values()) if e.kind == 'scheduled_run']
            items = [e for _, e in sorted(indexed, key=lambda pair: (pair[1].data['started_at'], pair[0]), reverse=True)]
            return {'reports': [self.detail(e.id) for e in items[offset:offset + limit]], 'total': len(items),
                    'next_offset': offset + limit if offset + limit < len(items) else None}

    def start(self):
        self.stop_event.clear()
        def loop():
            try:
                with portalocker.Lock(str(check_path(self.store.root, '.scheduler.lock')), timeout=0):
                    self.leader = True
                    while not self.stop_event.is_set():
                        try:
                            self.execute()
                            self.last_error = ''
                        except Exception:
                            self.last_error = '调度暂不可用，请检查数据完整性、目录权限和本机磁盘。'
                        self.stop_event.wait(15)
            except (OSError, portalocker.exceptions.LockException):
                self.last_error = '此实例未取得调度锁；其他实例可能正在调度。'
            finally:
                self.leader = False
        self.thread = threading.Thread(target=loop, name='personalai-scheduler', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1)


def register_scheduling(app, store):
    from fastapi import Query
    scheduler = Scheduler(app, store)
    app.state.scheduler = scheduler

    @app.get('/api/schedule')
    def status():
        return scheduler.status()

    @app.post('/api/schedule/preview')
    def preview(payload: PreviewSchedule):
        return scheduler.preview(payload)

    @app.post('/api/schedule/confirm')
    def confirm(payload: ConfirmSchedule):
        return scheduler.confirm(payload)

    @app.post('/api/schedule/pause')
    def pause(payload: RunRequest):
        return scheduler.pause(payload)

    @app.post('/api/schedule/run')
    def run(payload: RunRequest):
        return scheduler.execute(payload.request_id)

    @app.get('/api/scheduled-reports')
    def reports(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
        return scheduler.runs(limit, offset)

    @app.get('/api/scheduled-reports/feed')
    def feed(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
        results = scheduler.runs(limit, offset)
        return {'schema_version': 1, 'timezone': 'Asia/Shanghai', 'total': results['total'], 'next_offset': results['next_offset'], 'items': [
            {'id': r['run']['id'], 'version': r['run']['version'], 'status': r['run']['data']['status'],
             'scheduled_at': r['run']['data']['scheduled_at'], 'finished_at': r['run']['data']['finished_at'],
             'message': r['run']['data']['message'], 'stale': r['stale'],
             'suggestion_summary': (r['run']['data']['assessment']['suggestions'][0]['text']
                if r['run']['data']['assessment'] and r['run']['data']['assessment']['suggestions'] else ''),
             'report_url': '/api/scheduled-reports/' + r['run']['id']} for r in results['reports']]}

    @app.get('/api/scheduled-reports/{identifier}')
    def report(identifier: str):
        with store.mutex:
            scheduler.refresh()
            return scheduler.detail(identifier)

    @app.get('/api/scheduled-reports/{identifier}/export')
    def export(identifier: str, format: Literal['json', 'markdown'] = 'markdown'):
        from fastapi.responses import Response
        with store.mutex:
            scheduler.refresh()
            result = scheduler.detail(identifier)
        content = json.dumps({'schema_version': 1, **result}, ensure_ascii=False, indent=2) if format == 'json' else report_markdown(identifier, result['run']['data']) + ('\n> 依据已变化。\n' if result['stale'] else '')
        # IDs created by this module are fixed ASCII; avoid reflecting untrusted file names.
        filename = 'personalai-report-' + digest(identifier.encode())[:16] + ('.json' if format == 'json' else '.md')
        return Response(content, media_type='application/json' if format == 'json' else 'text/markdown; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename="{filename}"'})
