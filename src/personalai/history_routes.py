"""Shared history projections; web owners and scoped clients supply their access policy."""
import json
from datetime import datetime
from fastapi import Query
from .models import TZ
from .tracking_models import goal_progress
from .store import decode_event

KINDS = {'goal', 'tracking', 'log', 'checkin', 'profile', 'analysis', 'scheduled_run', 'suggestion'}


def task_event_items(store, day, allowed=None):
    selected = day
    statuses = {'open': '待进行', 'partial': '部分完成', 'done': '已完成'}
    with store.mutex:
        store.reload()
        store.require_healthy()
        # Timestamps have second precision. Event order disambiguates rapid renames.
        order = {}
        for path in store.files:
            event = decode_event(path.read_bytes())
            for item in [*event.records, *getattr(event, 'entities', [])]:
                order[(str(item.id), item.version)] = event.sequence
        items = []
        for identifier, versions in store.history.items():
            for index, value in enumerate(versions):
                if (allowed is not None and 'task' not in allowed) or value.kind != 'task' or datetime.fromisoformat(value.updated_at).astimezone(TZ).date() != selected:
                    continue
                previous = versions[index - 1] if index else None
                changes = []
                if previous is None:
                    changes.append('创建任务')
                    if value.status != 'open':
                        changes.append('状态：' + statuses[value.status])
                else:
                    if previous.status != value.status:
                        changes.append(f'状态：{statuses[previous.status]} → {statuses[value.status]}')
                    for field, label in [('text', '内容'), ('date', '计划日期'), ('category', '类别')]:
                        if getattr(previous, field) != getattr(value, field):
                            changes.append('修改任务' + label)
                items.append({'id': f'{identifier}:v{value.version}', 'task_id': identifier,
                              'version': value.version, 'time': value.updated_at, 'title': value.text,
                              'action': '；'.join(changes) or '确认任务修订'})
        def at_event(versions, sequence):
            return next((v for v in reversed(versions) if order[(str(v.id), v.version)] <= sequence), None)

        def goal_name(key, sequence):
            goal = at_event(store.entity_history.get(key, []), sequence)
            return goal.data['title'] if goal and goal.kind == 'goal' else '未关联目标'
        for identifier, versions in store.entity_history.items():
            for index, value in enumerate(versions):
                if (allowed is not None and value.kind not in allowed) or value.kind not in {'goal', 'tracking'} or datetime.fromisoformat(value.updated_at).astimezone(TZ).date() != selected:
                    continue
                before = versions[index - 1].data if index else None
                data = value.data
                task_id = data.get('task_id')
                if value.kind == 'tracking':
                    old = before.get('goal_id') if before else None
                    if old == data.get('goal_id'):
                        continue
                    sequence = order[(identifier, value.version)]
                    action = f"目标归属：{goal_name(old, sequence)} → {goal_name(data.get('goal_id'), sequence)}"
                    task = at_event(store.history.get(task_id, []), sequence)
                    title = task.text if task else '任务归属'
                else:
                    title = data['title']
                    if before is None:
                        action = '创建目标'
                    else:
                        changes = []
                        old, new = goal_progress(before), goal_progress(data)
                        fmt = lambda v: '未计算' if v is None else f'{v:g}%'
                        if old != new:
                            changes.append(f'目标进度：{fmt(old)} → {fmt(new)}')
                        for field, label in [('title','名称'),('criteria','完成标准'),('due','目标日期'),('mode','计算方式'),('baseline','起点'),('target','目标值'),('current','当前值'),('milestones','里程碑')]:
                            if before.get(field) != data.get(field):
                                changes.append('修改目标' + label)
                        action = '；'.join(changes) or '确认目标修订'
                items.append({'id': f'{identifier}:v{value.version}', 'task_id': task_id,
                              'entity_id': identifier, 'version': value.version, 'time': value.updated_at,
                              'title': title, 'action': action})
        items.sort(key=lambda x: (datetime.fromisoformat(x['time']), order[(x.get('entity_id') or x['task_id'], x['version'])], x['id']), reverse=True)
        return {'items': items}


def search_history(store, q='', day=None, kind='', offset=0, limit=30, allow=None, project=None):
    selected_day = str(day) if day else None
    needle = q.strip().casefold()
    with store.mutex:
        store.reload()
        store.require_healthy()
        rows = []

        def add(identifier, item_kind, versions, record=False):
            if kind and kind != item_kind:
                return
            if allow and not all(allow(item_kind, v.model_dump(mode='json')) for v in versions):
                return
            matches = []
            for value in versions:
                data = project(item_kind, value.model_dump(mode='json')) if project else value.model_dump(mode='json')
                content = data if record else data.get('data', data)
                stamp = value.updated_at if hasattr(value, 'updated_at') else value.created_at
                if isinstance(stamp, str):
                    stamp = datetime.fromisoformat(stamp)
                date = content.get('date') or content.get('window_end') or str(stamp.astimezone(TZ).date())
                if selected_day and selected_day != date:
                    continue
                if needle and needle not in json.dumps(content, ensure_ascii=False).casefold():
                    continue
                matches.append(data)
            if not matches:
                return
            current = project(item_kind, versions[-1].model_dump(mode='json')) if project else versions[-1].model_dump(mode='json')
            content = current if record else current.get('data', current)
            rows.append({'id': identifier, 'kind': item_kind,
                         'title': content.get('text') or content.get('title') or content.get('response') or content.get('reason') or item_kind,
                         'updated_at': current.get('updated_at', current['created_at']),
                         'version': current.get('version'), 'matches': matches,
                         'history': [project(item_kind, v.model_dump(mode='json')) if project else v.model_dump(mode='json') for v in versions], 'record': record})

        for identifier, versions in store.history.items():
            add(identifier, versions[-1].kind, versions, True)
        for identifier, versions in store.entity_history.items():
            item = versions[-1]
            # Never search configuration, authorizations, tokens or arbitrary plugin payloads.
            if item.kind == 'core/config' and identifier == 'config:user':
                add(identifier, 'profile', versions)
            elif item.kind in KINDS or (item.kind == 'change' and item.data.get('target_kind') in KINDS):
                add(identifier, item.kind, versions)
        for identifier, proposal in store.proposals.items():
            add(identifier, 'proposal', [proposal])
        rows.sort(key=lambda r: (r['updated_at'], r['id']), reverse=True)
        return {'items': rows[offset:offset + limit], 'total': len(rows),
                'next_offset': offset + limit if offset + limit < len(rows) else None}

def register_history(app, store, parse_day):
    @app.get('/api/task-events')
    def task_events(day: str = '今天'):
        return task_event_items(store, parse_day(day))

    @app.get('/api/history')
    def history(q: str = Query('', max_length=500), day: str | None = None,
                kind: str = '', offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)):
        return search_history(store, q, parse_day(day) if day else None, kind, offset, limit)
