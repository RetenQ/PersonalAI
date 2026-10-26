"""Export public client schemas without reading any real user data."""
import json
import tempfile
from pathlib import Path
from fastapi.openapi.utils import get_openapi
from personalai.app import create_app
from personalai.client_api import PREFIX
from personalai.models import RecordFields, CreateRecord, ProposeRevision
from personalai.reminders import Reminder
from personalai.tracking_models import Goal, Tracking, Activity, CheckIn, CurrentState, Profile
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
                    401: 'Missing, expired or revoked credential', 403: 'Scope or source denied',
                    409: 'Version conflict; reload and preview again', 410: 'Cursor invalid; get a new snapshot',
                    422: 'Invalid input', 429: 'Rate limited', 503: 'Storage or service unavailable'}.items()})
        for model in [RecordFields, CreateRecord, ProposeRevision, Goal, Tracking, Activity, CheckIn, CurrentState, Profile, Reminder, UserSettings, UISettings, TypeSettings, Bindings]:
            value = model.model_json_schema(ref_template='#/components/schemas/{model}')
            components['schemas'].update(value.pop('$defs', {}))
            components['schemas'][model.__name__] = value
        schema['info']['description'] = 'See docs/AGENT_API.md for command data-kind mapping, projection shapes, cursor semantics and owner confirmation rules. Web admin routes are deliberately excluded.'
        return schema


if __name__ == '__main__':
    destination = Path(__file__).resolve().parents[1] / 'docs' / 'openapi.clients.v1.json'
    destination.write_text(json.dumps(contract(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Client contract exported without real user data.')
