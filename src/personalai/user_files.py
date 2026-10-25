"""Human-readable local projections. Events remain the authoritative history."""
import hashlib
import json
import os
import posixpath
import tempfile
from pathlib import Path
from uuid import uuid4

from .models import CATEGORIES
from .tracking_models import Profile, Settings, goal_progress

FORMAT = 1
FOLDERS = {
    'profile': '个人档案', 'goals': '目标', 'tasks': '正式任务', 'ideas': '想法',
    'records': '日常记录', 'logs': '活动日志', 'checkins': '早中晚回顾',
    'states': '当前状态', 'analyses': 'AI 分析', 'confirmations': '待确认与处理历史',
}
KINDS = {'goal': 'goals', 'log': 'logs', 'checkin': 'checkins', 'state': 'states',
         'schedule': 'states', 'scheduled_run': 'analyses',
         'analysis': 'analyses', 'change': 'confirmations', 'suggestion': 'confirmations'}
STATUS = {'open': '待进行', 'partial': '部分完成', 'done': '已完成',
          'pending': '待确认', 'accepted': '已接受', 'rejected': '已拒绝'}
SLOTS = {'morning': '早上', 'noon': '中午', 'evening': '晚上'}
LABELS = {
    'title': '名称', 'criteria': '完成标准', 'due': '目标日期', 'mode': '计算方式',
    'unit': '单位', 'baseline': '起点', 'target': '目标值', 'current': '当前值',
    'milestones': '里程碑', 'weight': '权重', 'progress': '进度', 'task_id': '关联任务',
    'goal_id': '关联目标', 'tags': '任务类型', 'date': '日期', 'slot': '时段',
    'text': '内容', 'result': '结果', 'obstacle': '阻碍', 'completed': '已完成事项',
    'response': '回应', 'energy': '精力', 'mood': '心情', 'note': '备注',
    'name': '展示名称', 'bio': '简介', 'focus': '近期关注', 'order': '模块顺序',
    'hidden': '隐藏模块', 'task_types': '任务类型', 'active': '启用', 'id': '编号',
    'personality': '个性与自我描述', 'values': '重视的事情', 'preferences': '协作与生活偏好',
    'boundaries': '个人边界', 'status': '状态', 'category': '类别',
}
VALUES = {'metric': '数值指标', 'milestones': '里程碑', **STATUS, **SLOTS, **CATEGORIES,
          'profile': '个人情况', 'state': '当前状态', 'year': '年度时间', 'goals': '目标与任务',
          'logs': '任务日志', 'other': '其他已完成事项', 'checkins': '早中晚回顾', 'pending': '待确认事项'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def text(value):
    return '未记录' if value is None or value == '' else str(value)


def caption(value):
    return str(value).replace('\n', ' ').replace('\r', ' ').replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]')


def safe_id(value):
    # Even an imported, valid event may contain an arbitrary entity identifier.
    value = str(value)
    reserved = {'con', 'prn', 'aux', 'nul', *[f'{p}{i}' for p in ['com', 'lpt'] for i in range(1, 10)]}
    if value and value.lower() not in reserved and len(value) <= 100 and all(c in '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_' for c in value):
        return value
    return sha(value.encode('utf-8'))


def render_user_files(store) -> dict[str, bytes]:
    """Deterministic, location-independent documents, reproducible after restore."""
    store.require_healthy()
    settings = store.entities.get('settings')
    config = settings.data if settings else Settings().model_dump(mode='json')
    profile = store.entities.get('profile')
    profile_data = profile.data if profile else Profile().model_dump(mode='json')
    records = {str(r.id): r for r in store.records.values()}
    entities = store.entities
    paths, names = {'profile': 'profile/PROFILE.md'}, {'profile': '个人档案', 'settings': '应用设置'}
    for key, r in records.items():
        folder = {'task': 'tasks', 'idea': 'ideas', 'note': 'records'}[r.kind]
        paths[key] = f'{folder}/{safe_id(key)}.md'
        names[key] = r.text.splitlines()[0][:90]
    for key, e in entities.items():
        if e.kind in KINDS:
            paths[key] = f'{KINDS[e.kind]}/{safe_id(key)}.md'
            names[key] = e.data.get('title') or e.data.get('text') or e.data.get('response') or e.data.get('reason') or FOLDERS[KINDS[e.kind]]
        elif e.kind == 'profile':
            paths[key], names[key] = 'profile/PROFILE.md', '个人档案'
        elif e.kind == 'tracking':
            paths[key] = paths.get(e.data['task_id'], '')
            names[key] = '任务追踪'
    names.update({t['id']: t['name'] for t in config['task_types']})
    sources = {}
    last_time = '尚无记录'
    for event in store.requests.values():
        last_time = event.timestamp
        file = f'../events/{event.sequence:012d}_{event.request_id}.md'
        for item in [*event.records, *getattr(event, 'entities', [])]:
            sources.setdefault(str(item.id), []).append((item.version, file, event.timestamp))
        for proposal in event.proposals:
            sources.setdefault(str(proposal.id), []).append((proposal.status, file, event.timestamp))

    def link(key, current, version=None):
        if not key:
            return '未关联'
        path = paths.get(str(key))
        label = caption(names.get(str(key), key))
        value = f'[{label}]({posixpath.relpath(path, posixpath.dirname(current))})' if path else label
        return value + (f'（依据修订 {version}）' if version is not None else '')

    def section(label, value):
        return [f'## {label}', '', text(value), '']

    def fields(data, current, depth=0):
        lines = []
        for key, value in data.items():
            if key == 'model':
                lines += ['- 模型配置：请在网页设置中查看；不写入本资料目录。']
                continue
            label = LABELS.get(key, key)
            if key in {'goal_id', 'task_id'}:
                value = link(value, current)
            if isinstance(value, dict):
                lines += [f'- {label}：', *['  ' + line for line in fields(value, current, depth + 1)]]
            elif isinstance(value, list):
                lines += [f'- {label}：' + ('无' if not value else '')]
                for item in value:
                    if isinstance(item, dict):
                        lines += ['  - 项目：', *['    ' + line for line in fields(item, current, depth + 1)]]
                    else:
                        lines += ['  - ' + names.get(str(item), VALUES.get(str(item), text(item)))]
            else:
                display = ('是' if value else '否') if isinstance(value, bool) else VALUES.get(str(value), text(value)) if key in {'mode', 'status', 'slot', 'category'} else text(value)
                lines += [f'- {label}：{display.replace(chr(10), chr(10) + "  ")}']
        return lines

    docs, indexes = {}, {folder: [] for folder in FOLDERS}

    def document(path, title, body, source_keys=(), kind='', version=None, layer='L3', source='用户记录', identifier=None):
        metadata = {'schema_version': FORMAT, 'kind': kind, 'id': identifier or (str(source_keys[0]) if source_keys else None),
                    'version': version, 'layer': layer, 'source': source, 'timezone': 'Asia/Shanghai',
                    'event_sequence': store.sequence, 'created_at': None, 'updated_at': None}
        source_entries = [(key, row) for key in source_keys for row in sources.get(str(key), [])]
        if source_entries:
            metadata['created_at'] = min(row[2] for _, row in source_entries)
            metadata['updated_at'] = max(row[2] for _, row in source_entries)
        lines = ['---', *[f'{key}: {json.dumps(value, ensure_ascii=False)}' for key, value in metadata.items()],
                 '---', '', '# ' + caption(title), '', '> 此文件由网页数据自动整理。请在网页中修改；不要直接编辑本文件。', '', *body,
                 '## 来源与修订', '']
        for key, (v, file, timestamp) in source_entries:
            target = posixpath.relpath(file, posixpath.dirname(path))
            lines += [f'- [{caption(key)} · 修订／处理 {caption(v)}]({target}) · {timestamp}']
        if not source_entries:
            lines += ['尚未在网页填写；不从访谈档案自动导入，也不推断缺失信息。']
        lines += ['', '[返回资料目录](' + posixpath.relpath('README.md', posixpath.dirname(path)) + ')', '']
        docs[path] = '\n'.join(lines).encode('utf-8')
        indexes[path.split('/')[0]].append((path, title))

    body = section('展示名称', config['name']) + section('个人简介', config['bio'])
    body += ['以下内容仅表示用户自述，不是 AI 推断、人格测评或诊断。', '']
    for key, value in profile_data.items():
        body += section(LABELS[key], value)
    document('profile/PROFILE.md', '个人档案', body, [k for k in ['settings', 'profile'] if k in entities],
             kind='profile', version=profile.version if profile else None, layer='L1', source='用户明确填写与确认', identifier='profile')
    document('states/FOCUS.md', '近期关注', section('当前关注点', config['focus']),
             ['settings'] if settings else [], kind='focus', version=settings.version if settings else None, layer='L2', identifier='focus')

    for key, r in records.items():
        path = paths[key]
        body = [f'- 日期：{r.date}', f'- 类别：{CATEGORIES[r.category]}',
                f'- 来源：{"用户直接输入" if r.source == "user_input" else "用户确认的建议"}',
                '- AI 理解：尚未进行', '', *section('原始表述', r.text)]
        keys = [key]
        if r.kind == 'task':
            tracking = entities.get('tracking:' + key)
            t = tracking.data if tracking else {'goal_id': None, 'tags': [], 'progress': 100 if r.status == 'done' else None}
            body += [f'## 任务追踪', '', f'- 执行状态：{STATUS[r.status]}', f'- 主要目标：{link(t["goal_id"], path)}',
                     '- 任务类型：' + ('、'.join(names.get(tag, tag) for tag in t['tags']) or '未设置'),
                     '- 任务自身进度：' + ('未知' if t['progress'] is None else f'{t["progress"]}%'),
                     '', '任务进度独立于目标进度；日志数量不等于完成比例。', '']
            if tracking:
                keys.append(tracking.id)
            body += ['## 关联日志', '', *[f'- {link(e.id, path)}' for e in entities.values() if e.kind == 'log' and e.data['task_id'] == key], '']
        elif r.kind == 'idea':
            body += ['这是一条想法，尚不构成正式任务。', '']
        document(path, names[key], body, keys, kind=r.kind, version=r.version, layer='计划' if r.kind == 'task' else 'L3')

    for key, e in entities.items():
        if e.kind not in KINDS:
            continue
        path, d = paths[key], e.data
        title, body, layer, source = names[key], [], 'L3', '用户明确填写与确认'
        if e.kind == 'scheduled_run':
            from .scheduled_models import report_markdown
            title = '定时综合分析 · ' + d['window_end'] + ' · ' + d['status']
            body = [report_markdown(key, d), '## 资料链接', '', *[f'- {link(k, path, v)}' for k, v in d['sources'].items()]]
            layer, source = 'L4', 'AI 分析与运行状态，不自动执行建议'
        elif e.kind == 'schedule':
            from .scheduled_models import SCOPE_NAMES
            title = '定时分析设置'
            body = ['本机启用授权不包含在备份中；恢复后需在网页重新确认。', '',
                    '- 请求启用：' + ('是' if d['enabled'] else '否'),
                    '- 每日时刻：' + ('、'.join(d['times']) or '尚未设置'),
                    '- 允许资料：' + ('、'.join(SCOPE_NAMES[s] for s in d['scopes']) or '尚未选择'),
                    '- 时区：Asia/Shanghai；当天为主，近七天作背景；提醒发送由外部应用承担。']
            layer = 'L2'
        elif e.kind == 'goal':
            progress = goal_progress(d)
            body = section('完成标准', d['criteria']) + [f'- 目标日期：{text(d["due"])}',
                    '- 已确认进度：' + ('尚无法计算' if progress is None else f'{progress}%'), '', '## 计算依据', '',
                    *fields({k: v for k, v in d.items() if k not in {'title', 'criteria', 'due'}}, path), '',
                    '## 关联任务', '', *[f'- {link(t.data["task_id"], path)}' for t in entities.values() if t.kind == 'tracking' and t.data['goal_id'] == key], '',
                    '## 相关日志与分析', '', *[f'- {link(t.id, path)}' for t in entities.values() if t.kind in {'log', 'analysis'} and t.data['goal_id'] == key], '']
            layer = '计划'
        elif e.kind in {'log', 'checkin', 'state'}:
            title = f'{d["date"]} · ' + (SLOTS[d['slot']] + '回顾' if e.kind == 'checkin' else '当前状态' if e.kind == 'state' else title.splitlines()[0][:90])
            for field, value in d.items():
                if field in {'task_id', 'goal_id'}:
                    body += [f'- {LABELS[field]}：{link(value, path)}', '']
                elif field in {'date', 'slot', 'completed'}:
                    body += fields({field: value}, path) + ['']
                else:
                    body += section(LABELS[field], value)
            if e.kind == 'log':
                body += ['关联关系记录发生时的情况，不随任务之后重新归属而改写。', '']
            layer = 'L2' if e.kind == 'state' else 'L3'
        elif e.kind == 'analysis':
            a = d['assessment']
            current = {**{k: r.version for k, r in records.items()}, **{k: t.version for k, t in entities.items()}}
            stale = any(current.get(k) != v for k, v in d['sources'].items())
            title = '目标分析 · ' + names.get(d['goal_id'], d['goal_id'])
            body = [f'- 目标：{link(d["goal_id"], path)}', f'- 模型：{d["model"]}',
                    '- 依据状态：' + ('依据已变化' if stale else '依据版本未变化'),
                    '- AI 估计：' + ('证据不足，未输出百分比' if a['low'] is None else f'{a["low"]}–{a["high"]}%'),
                    '', 'AI 估计不是已确认进度，不会自动修改目标或任务。', '', *section('分析说明', a['explanation']), '## 任务相关性', '']
            for c in a['contributions']:
                body += [f'- {link(c["task_id"], path)}：' + {'direct': '直接贡献', 'supporting': '辅助作用', 'insufficient': '证据不足'}[c['relevance']],
                         f'  - {c["reason"]}', '  - 依据：' + '、'.join(link(i, path, d['sources'].get(i)) for i in c['source_ids'])]
            body += ['', *section('缺失信息', '\n'.join('- ' + x for x in a['missing']) or '未列出'),
                     *section('建议（不自动执行）', '\n'.join('- ' + x for x in a['suggestions']) or '未列出'),
                     '## 分析依据', '', *[f'- {link(k, path, v)}' for k, v in d['sources'].items()], '']
            layer, source = 'L4', 'AI 分析，未经核实的估计与建议'
        elif e.kind == 'change':
            title = STATUS[d['status']] + ' · ' + d['reason']
            body = [f'- 状态：{STATUS[d["status"]]}', f'- 对象：{link(d["target_id"], path)}',
                    f'- 依据版本：{d["expected_version"]}', '', '待确认或已拒绝的提案不属于正式资料。', '',
                    '## 修改前', '', *fields(d['before'] or {}, path), '', '## 拟修改为', '', *fields(d['after'], path), '']
            layer = 'L4'
        else:
            title = STATUS[d['status']] + ' · AI 建议'
            body = [f'- 状态：{STATUS[d["status"]]}', f'- 目标：{link(d["goal_id"], path)}',
                    f'- 分析来源：{link(d["analysis_id"], path)}', '', *section('建议内容', d['text']),
                    '接受建议仅保留接受状态，不代表已经创建或执行任务。', '']
            layer, source = 'L4', 'AI 建议'
        document(path, title, body, [key], kind=e.kind, version=e.version, layer=layer, source=source)

    for key, p in store.proposals.items():
        path = f'confirmations/{safe_id(key)}.md'
        title = STATUS[p.status] + ' · ' + p.reason
        body = [f'- 状态：{STATUS[p.status]}', f'- 对象：{link(str(p.target_id), path) if p.target_id else "拟新增记录"}',
                f'- 依据版本：{text(p.expected_version)}', '', '待确认或已拒绝的内容不会成为正式任务或覆盖原文。', '',
                '## 修改前', '', *fields(p.before.model_dump(mode='json', include={'text', 'date', 'category', 'status'}) if p.before else {}, path),
                '', '## 拟保存内容', '', *fields(p.after.model_dump(mode='json'), path), '']
        document(path, title, body, [key], kind='proposal', layer='L4', source='用户修改或待确认意图')

    for folder, title in FOLDERS.items():
        lines = ['# ' + title, '', '由网页自动整理；请通过网页维护。', '']
        lines += [f'- [{caption(title)}]({posixpath.basename(path)})' for path, title in sorted(indexes[folder])]
        if not indexes[folder]:
            lines += ['尚未记录。缺少信息不表示没有执行或进度为零。']
        docs[f'{folder}/README.md'] = ('\n'.join([*lines, '', '[返回资料目录](../README.md)', ''])).encode('utf-8')
    docs['README.md'] = ('\n'.join([
        '# 用户资料目录', '', f'格式版本：{FORMAT} · 事件版本：{store.sequence} · 最近记录时间：{last_time} · Asia/Shanghai', '',
        '这里是网页记录的可读版本。正文使用中文栏目，文件以稳定编号命名，修改名称不会改变文件位置。', '',
        '## 从这里阅读', '', *[f'- [{title}]({folder}/README.md)（{len(indexes[folder])} 份资料文件）' for folder, title in FOLDERS.items()], '',
        '## 维护规则', '',
        '- 在网页填写和确认修改后自动整理；个性内容只来自用户自述，不自动读取已有访谈或生成性格判断。',
        '- L1 为长期档案，L2 为带日期状态，L3 为历史记录，L4 为分析、待确认内容；目标和正式任务单独管理。',
        '- 未记录、未知、AI 估计与已确认进度分别表示。提案通过确认前不会覆盖正式资料。',
        '- events/ 是权威修订历史；每个文件提供相对来源链接。整个 data/ 可以迁移；仅复制本目录适合阅读，不足以完整恢复应用。',
        '- 请勿直接编辑这些生成文件。整理时发现被改动的文件，会先保留到同级 user-edits/ 再更新；手改内容不会自动导入网页。',
        '- 设置中的“重新整理资料”可重建这些文件；若失败，原始记录仍保留，网页会显示状态。',
        '- 使用网页备份导出会同时包含记录历史和本可读目录。密钥、个人访谈原件及 user-edits/ 不包含在应用备份内。',
        '- 文件为本机明文，不提交公开仓库；静态网页服务不开放此目录。', ''])).encode('utf-8')
    return docs


def check_path(root: Path, relative: str) -> Path:
    parts = Path(relative).parts
    if Path(relative).is_absolute() or any(p in {'.', '..'} or ':' in p for p in parts):
        raise OSError('invalid managed path')
    current = root
    for part in ('', *parts):
        if part:
            current = current / part
        if current.is_symlink() or current.is_junction():
            raise OSError('linked paths are not supported')
    return current


def atomic_write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def publish(store):
    """Called under the same process/file lock as the event writer."""
    root = check_path(store.root, 'user')
    manifest_path = check_path(root, '.manifest.json')
    previous, invalid_manifest = {}, False
    if manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_bytes())
            if not isinstance(previous, dict) or not isinstance(previous.get('files'), dict) or not isinstance(previous.get('preserved', []), list):
                raise ValueError('invalid manifest')
        except (ValueError, TypeError):
            previous, invalid_manifest = {}, True
    docs = render_user_files(store)
    preserved = list(previous.get('preserved', []))
    archive_name = str(uuid4())

    def preserve(relative, raw):
        destination = check_path(store.root, f'user-edits/{archive_name}/{relative}')
        atomic_write(destination, raw)
        preserved.append(destination.relative_to(store.root).as_posix())

    if invalid_manifest:
        preserve('.manifest.json', manifest_path.read_bytes())
    for name, raw in docs.items():
        target = check_path(root, name)
        old = target.read_bytes() if target.exists() else None
        if old == raw:
            continue
        if old is not None and sha(old) != previous.get('files', {}).get(name):
            preserve(name, old)
        atomic_write(target, raw)
    # Written last: an interrupted projection cannot advertise a newer complete snapshot.
    manifest = {'format': FORMAT, 'sequence': store.sequence, 'source_hash': store.last_hash,
                'files': {k: sha(v) for k, v in docs.items()}, 'preserved': preserved}
    atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))


def status(store):
    result = {'directory': str(store.root / 'user'), 'entry': str(store.root / 'user' / 'README.md'),
              'healthy': False, 'sequence': None, 'source_sequence': store.sequence,
              'error': store.user_files_error, 'preserved_count': 0}
    try:
        manifest = json.loads(check_path(store.root, 'user/.manifest.json').read_bytes())
        if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), dict):
            raise ValueError('invalid manifest')
        result.update(sequence=manifest['sequence'], preserved_count=len(manifest.get('preserved', [])))
        result['healthy'] = not store.errors and not store.user_files_error and manifest.get('format') == FORMAT and manifest['sequence'] == store.sequence and manifest['source_hash'] == store.last_hash
        if result['healthy']:
            for name, checksum in manifest['files'].items():
                if sha(check_path(store.root, 'user/' + name).read_bytes()) != checksum:
                    result['healthy'] = False
                    break
    except (OSError, ValueError, KeyError, TypeError):
        result['healthy'] = False
    if not result['healthy'] and not result['error']:
        result['error'] = '可读资料尚未与记录同步，请在设置中重新整理。'
    return result
