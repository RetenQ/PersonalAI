"""Export public client schemas without reading any real user data."""
import json
import tempfile
from pathlib import Path
from fastapi.openapi.utils import get_openapi
from personalai.app import create_app
from personalai.client_api import PREFIX, FEATURES
from personalai.task_routes import CreateTask
from personalai.models import RecordFields, CreateRecord, ProposeRevision
from personalai.reminders import Reminder
from personalai.tracking_models import Goal, Tracking, Activity, CheckIn, Profile
from personalai.configuration import UserSettings, UISettings, TypeSettings, Bindings


def contract():
    with tempfile.TemporaryDirectory(prefix='personalai-contract-') as directory:
        app = create_app(Path(directory))
        routes = [r for r in app.routes if getattr(r, 'path', '').startswith(PREFIX)]
        schema = get_openapi(title='PersonalAI Client API', version='1.0.0', routes=routes)
        components = schema.setdefault('components', {})
        components['securitySchemes'] = {'ClientBearer': {'type': 'http', 'scheme': 'bearer', 'description': 'Independent revocable device or scoped Agent token. Never in URL.'}}
        for path, methods in schema['paths'].items():
            for value in methods.values():
                if path not in {PREFIX + '/pairings', PREFIX + '/pairings/poll', PREFIX + '/auth/refresh'}:
                    value['security'] = [{'ClientBearer': []}]
                value['responses'].update({str(code): {'description': message} for code, message in {
                    401: 'Missing, expired or revoked credential', 403: 'Scope or source denied', 404: 'Resource not found',
                    409: 'Version conflict; reload and preview again', 410: 'Cursor invalid; get a new snapshot',
                    422: 'Invalid input', 429: 'Rate limited', 503: 'Storage or service unavailable'}.items()})
        for model in [RecordFields, CreateRecord, CreateTask, ProposeRevision, Goal, Tracking, Activity, CheckIn, Profile, Reminder, UserSettings, UISettings, TypeSettings, Bindings]:
            value = model.model_json_schema(ref_template='#/components/schemas/{model}')
            components['schemas'].update(value.pop('$defs', {}))
            components['schemas'][model.__name__] = value
        schema['info']['description'] = 'See docs/AGENT_API.md for command data-kind mapping, projection shapes, cursor semantics and owner confirmation rules. Web admin routes are deliberately excluded.'
        schema['x-client-features'] = FEATURES
        schema['x-command-data-schemas'] = {'create_task': 'CreateTask (request_id belongs to the command envelope)'}
        schema['x-resource-added-fields'] = {'goals': ['created_at'], 'reports': ['window_start', 'window_end', 'started_at', 'model']}
        return schema


if __name__ == '__main__':
    destination = Path(__file__).resolve().parents[1] / 'docs' / 'openapi.clients.v1.json'
    destination.write_text(json.dumps(contract(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    guide = destination.with_name('AGENT_API.md')
    begin, end = '<!-- client-features:start -->', '<!-- client-features:end -->'
    section = begin + '\n## 客户端能力（由契约导出脚本生成）\n\n字段 `features` 为布尔映射；缺少字段、缺少键或 false 均按不支持处理。\n\n' + '\n'.join(f'- `{key}`：{value}。' for key, value in FEATURES.items()) + '\n' + end
    text = guide.read_text(encoding='utf-8')
    if begin in text:
        start, tail = text.split(begin, 1)
        text = start + section + tail.split(end, 1)[1]
    else:
        text += '\n\n' + section + '\n'
    guide.write_text(text, encoding='utf-8')
    print('Client contract exported without real user data.')
