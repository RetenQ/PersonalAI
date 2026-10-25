"""Tracking operations share the original atomic, idempotent event writer."""
from datetime import date
from uuid import uuid4

from pydantic import ValidationError

from .models import now
from .store import StoreError
from .tracking_models import Entity, KINDS, Settings, goal_progress, year_time


def entity(kind, data, identifier=None, before=None):
    return Entity(id=identifier or str(uuid4()), kind=kind, data=data,
                  version=before.version + 1 if before else 1,
                  created_at=before.created_at if before else now(), updated_at=now())


class TrackingService:
    def __init__(self, store):
        self.store = store

    def get(self, key, kind=None):
        self.store.require_healthy()
        item = self.store.entities.get(key)
        if not item or (kind and item.kind != kind):
            raise StoreError('未找到对应内容', 404)
        return item

    def settings(self):
        item = self.store.entities.get('settings')
        return item.data if item else Settings().model_dump(mode='json')

    def validate(self, kind, data, before=None):
        try:
            data = KINDS[kind].model_validate(data).model_dump(mode='json')
        except (ValidationError, KeyError) as exc:
            raise StoreError('字段格式不正确，请检查必填内容、数值、模块和模型地址。', 422) from exc
        if kind in {'tracking', 'log', 'checkin'}:
            if data.get('goal_id'):
                self.get(data['goal_id'], 'goal')
            if data.get('task_id'):
                if self.store.get(data['task_id']).kind != 'task':
                    raise StoreError('只能关联正式任务', 422)
            if kind == 'log' and data.get('task_id'):
                tracking = self.store.entities.get('tracking:' + data['task_id'])
                linked = tracking.data.get('goal_id') if tracking else None
                if data.get('goal_id') != linked:
                    raise StoreError('日志目标必须与任务当前目标一致，请刷新后重试。', 409)
        if kind == 'tracking':
            types = {t['id']: t for t in self.settings()['task_types']}
            previous_tags = before.data['tags'] if before else []
            if any(t not in types or (not types[t]['active'] and t not in previous_tags) for t in data['tags']):
                raise StoreError('请选择有效的任务类型', 422)
        if kind == 'settings':
            old = {t['id'] for t in self.settings()['task_types']}
            if not old <= {t['id'] for t in data['task_types']}:
                raise StoreError('已有任务类型请停用，不要删除历史引用。', 422)
        return data

    def write(self, kind, request, identifier=None):
        def prepare():
            key = identifier or str(uuid4())
            if kind in {'settings', 'profile'}:
                key = kind
            if kind == 'tracking':
                key = 'tracking:' + str(request.data.get('task_id', ''))
                if identifier and key != identifier:
                    raise StoreError('不能改变任务追踪所属记录', 422)
            before = self.store.entities.get(key)
            if before and before.kind != kind:
                raise StoreError('记录类型不匹配', 422)
            if request.expected_version != (before.version if before else 0):
                raise StoreError('内容已更新，请刷新并基于最新版本修改。')
            data = self.validate(kind, request.data, before)
            if kind in {'tracking', 'profile'} or before:
                item = entity('change', {'target_id': key, 'target_kind': kind,
                    'expected_version': request.expected_version, 'before': before.data if before else None,
                    'after': data, 'reason': request.reason})
                result = {'change': item.model_dump(mode='json')}
            else:
                item = entity(kind, data, key)
                result = {'entity': item.model_dump(mode='json')}
            output = [item]
            if request.progress_update:
                if kind != 'log' or before or data.get('task_id') != str(request.progress_update.task_id):
                    raise StoreError('进度建议只能附在新建的关联任务日志上。', 422)
                tracking_key = 'tracking:' + str(request.progress_update.task_id)
                previous_tracking = self.store.entities.get(tracking_key)
                if request.tracking_expected_version != (previous_tracking.version if previous_tracking else 0):
                    raise StoreError('任务追踪已更新，请刷新后重试。')
                tracking_data = self.validate('tracking', request.progress_update.model_dump(mode='json'), previous_tracking)
                proposal = entity('change', {'target_id': tracking_key, 'target_kind': 'tracking',
                    'expected_version': request.tracking_expected_version, 'before': previous_tracking.data if previous_tracking else None,
                    'after': tracking_data, 'reason': '根据新活动日志提出进度修改；日志来源 ' + item.id})
                output.append(proposal)
                result['related_change'] = proposal.model_dump(mode='json')
            return [], [], result, output
        return self.store.transaction(request.request_id, f'write:{kind}:{identifier}', request.model_dump(mode='json'), prepare, extension=True)

    def decide(self, key, request):
        def prepare():
            item = self.get(key)
            if item.kind not in {'change', 'suggestion'} or item.data['status'] != 'pending':
                raise StoreError('这个事项已经处理或不是确认事项。')
            output = []
            if item.kind == 'change' and request.decision == 'accept':
                change = item.data
                before = self.store.entities.get(change['target_id'])
                if change['expected_version'] != (before.version if before else 0):
                    raise StoreError('提案已过期，不能覆盖新版本。请拒绝后重新提出。')
                data = self.validate(change['target_kind'], change['after'], before)
                output.append(entity(change['target_kind'], data, change['target_id'], before))
            output.append(entity(item.kind, {**item.data, 'status': 'accepted' if request.decision == 'accept' else 'rejected'}, item.id, item))
            return [], [], {'entities': [e.model_dump(mode='json') for e in output]}, output
        return self.store.transaction(request.request_id, 'tracking-decision:' + key, request.model_dump(mode='json'), prepare, extension=True)

    def snapshot(self, day: date, goal_id=None, slot=None):
        self.store.require_healthy()
        values = list(self.store.entities.values())
        goals = [e for e in values if e.kind == 'goal' and (not goal_id or e.id == goal_id)]
        tasks = []
        for record in self.store.records.values():
            if record.kind != 'task':
                continue
            tracking = self.store.entities.get('tracking:' + str(record.id))
            linked = tracking.data if tracking else {'task_id': str(record.id), 'goal_id': None, 'tags': [], 'progress': None}
            if goal_id and linked['goal_id'] != goal_id:
                continue
            tasks.append({'record': record.model_dump(mode='json'), 'tracking': tracking.model_dump(mode='json') if tracking else None,
                          **linked, 'progress': linked['progress'] if tracking else (100 if record.status == 'done' else None)})
        versions = {e.id: e.version for e in values}
        versions.update({str(r.id): r.version for r in self.store.records.values()})
        def selected(e):
            return e.data.get('date') == day.isoformat() and (not goal_id or e.data.get('goal_id') == goal_id) and (not slot or e.data.get('slot') == slot)
        analyses = [{**e.model_dump(mode='json'), 'stale': any(versions.get(k) != v for k, v in e.data['sources'].items())}
                    for e in values if e.kind == 'analysis' and (not goal_id or e.data['goal_id'] == goal_id)]
        return {'schema_version': 2, 'generated_at': now(), 'date': day.isoformat(), 'slot': slot, 'timezone': 'Asia/Shanghai',
                'year': year_time(day), 'settings': self.settings(), 'user_files': self.store.user_files_status(),
                'settings_version': self.store.entities['settings'].version if 'settings' in self.store.entities else 0,
                'goals': [{**e.model_dump(mode='json'), 'progress': goal_progress(e.data)} for e in goals], 'tasks': tasks,
                'logs': [e.model_dump(mode='json') for e in values if e.kind == 'log' and selected(e)],
                'checkins': [e.model_dump(mode='json') for e in values if e.kind == 'checkin' and selected(e)],
                'states': [e.model_dump(mode='json') for e in values if e.kind == 'state' and e.data['date'] == day.isoformat()],
                'analyses': analyses, 'pending': [e.model_dump(mode='json') for e in values if e.kind in {'change', 'suggestion'} and e.data['status'] == 'pending'],
                'decisions': [e.model_dump(mode='json') for e in values if e.kind in {'change', 'suggestion'} and e.data['status'] != 'pending']}

    def analysis_input(self, goal_id, task_ids, log_ids):
        goal = self.get(goal_id, 'goal')
        if len(set(task_ids)) != len(task_ids) or len(set(log_ids)) != len(log_ids):
            raise StoreError('来源不能重复', 422)
        inputs = [goal]
        tasks = []
        for key in task_ids:
            record = self.store.get(key)
            tracking = self.get('tracking:' + key, 'tracking')
            if record.kind != 'task' or tracking.data['goal_id'] != goal_id:
                raise StoreError('只能分析选中目标的关联任务', 422)
            tasks.append(record)
            inputs.append(tracking)
        logs = []
        for key in log_ids:
            log = self.get(key, 'log')
            if log.data['goal_id'] != goal_id:
                raise StoreError('日志不属于选中目标', 422)
            logs.append(log)
        sources = {e.id: e.version for e in inputs + logs}
        sources.update({str(t.id): t.version for t in tasks})
        return {'goal': goal.model_dump(mode='json'), 'tasks': [t.model_dump(mode='json') for t in tasks],
                'tracking': [e.model_dump(mode='json') for e in inputs[1:]], 'logs': [e.model_dump(mode='json') for e in logs], 'sources': sources}


def export_snapshot(snapshot):
    # Display preferences, API configuration and unselected personal status never enter a progress export.
    return {k: v for k, v in snapshot.items() if k not in {'settings', 'settings_version', 'states', 'pending', 'decisions', 'user_files'}}


def markdown_export(snapshot):
    lines = [f"# 进度回顾 · {snapshot['date']}", '', f"生成：{snapshot['generated_at']} · Asia/Shanghai", '目标与任务为导出时的当前快照；日期和时段筛选日志与回应。', '', '## 目标进度']
    for g in snapshot['goals']:
        progress = '尚无法计算' if g['progress'] is None else f"{g['progress']}%"
        lines += [f"- {g['data']['title']}：{progress}（已确认；来源 {g['id']} v{g['version']}）"]
    lines += ['', '## 任务']
    for t in snapshot['tasks']:
        progress = '未知' if t['progress'] is None else f"{t['progress']}%"
        lines += [f"- {t['record']['text']}：{progress}（来源 {t['record']['id']} v{t['record']['version']}）"]
        lines += [f"  - 目标：{t['goal_id'] or '未关联'}；类型：{'、'.join(t['tags']) or '未设置'}"]
        if t['tracking']:
            lines += [f"  - 追踪来源：{t['tracking']['id']} v{t['tracking']['version']}"]
    for key, title in [('logs', '活动日志'), ('checkins', '早中晚回应')]:
        lines += ['', '## ' + title]
        for e in snapshot[key]:
            d = e['data']
            lines += [f"- {d.get('text', d.get('response', ''))}", f"  - 结果：{d.get('result') or '未记录'}；阻碍：{d.get('obstacle') or '未记录'}",
                      f"  - 时段：{d.get('slot') or '未指定'}；来源：{e['id']} v{e['version']}"]
            lines += [f"  - 目标：{d.get('goal_id') or '未关联'}；任务：{d.get('task_id') or '未关联'}"]
    lines += ['', '## AI 估计与待澄清信息']
    for e in snapshot['analyses']:
        a = e['data']['assessment']
        lines += [f"- {a['low']}–{a['high']}%" if a['low'] is not None else '- 证据不足，未估计',
                  f"  - {a['explanation']}；{'依据已变化' if e['stale'] else '依据版本未变化'}；分析 {e['id']} v{e['version']}",
                  '  - 缺失信息：' + '；'.join(a['missing']), '  - 建议（尚未改变计划）：' + '；'.join(a['suggestions']),
                  '  - 来源：' + '、'.join(a['source_ids'])]
    return '\n'.join(lines) + '\n'
