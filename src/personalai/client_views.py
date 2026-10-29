"""Scope-aware history projections shared by client search and source lookup."""
from .history_routes import KINDS

RESOURCES = {'note': 'records', 'idea': 'records', 'task': 'tasks', 'goal': 'goals',
             'tracking': 'tasks', 'log': 'logs', 'checkin': 'checkins', 'profile': 'profile',
             'analysis': 'reports', 'scheduled_run': 'reports', 'suggestion': 'reports',
             'change': 'pending', 'proposal': 'pending', 'core/reminder': 'reminders'}
PLUGINS = {'tasks': 'tracking', 'goals': 'tracking', 'logs': 'journal', 'checkins': 'journal', 'reports': 'analysis'}
REPORT_FIELDS = {'goal_id', 'sources', 'assessment', 'status', 'window_start', 'window_end',
                 'started_at', 'scheduled_at', 'finished_at', 'model'}


def permitted(app, principal, kind, value):
    resource = RESOURCES.get(kind)
    if not resource or 'read:' + resource not in principal['scopes']:
        return False
    if resource in PLUGINS and not app.state.plugins.active(PLUGINS[resource]):
        return False
    data = value.get('data', value)
    if kind == 'proposal':
        target = 'task' if data.get('action') == 'create_task' or (data.get('before') or {}).get('kind') == 'task' else 'note'
        if not permitted(app, principal, target, data.get('after', {})):
            return False
    if kind == 'change':
        target = data.get('target_kind')
        if target not in KINDS or not all(permitted(app, principal, target, v or {}) for v in [data.get('before'), data.get('after')]):
            return False
    if data.get('goal_id') and 'read:goals' not in principal['scopes']:
        return False
    if data.get('task_id') and 'read:tasks' not in principal['scopes']:
        return False
    if kind == 'suggestion':
        analysis = app.state.store.entities.get(data.get('analysis_id'))
        if not analysis or not permitted(app, principal, analysis.kind, analysis.model_dump(mode='json')):
            return False
    for key in data.get('sources', {}):
        item = app.state.store.records.get(key) or app.state.store.entities.get(key)
        source_kind = item.kind if item else None
        resource = RESOURCES.get(source_kind)
        if not resource or 'read:' + resource not in principal['scopes']:
            return False
    return True


def project(kind, value):
    if kind == 'change':
        data = value['data']
        return {**value, 'data': {**data, **{key: project(data['target_kind'], {'data': data[key]})['data']
                                           for key in ['before', 'after'] if data.get(key) is not None}}}
    if kind in {'analysis', 'scheduled_run'}:
        return {**value, 'data': {k: v for k, v in value['data'].items() if k in REPORT_FIELDS}}
    return value
