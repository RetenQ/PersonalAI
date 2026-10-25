"""Opt-in real-provider smoke test. Never collected by pytest; two paid calls.

Run from the repository root with --base-url and --model. The default hidden
prompt keeps credentials out of command arguments. --key-stdin accepts a JSON
object through a private pipe for automation. Never supply a key in argv/files.
All records are synthetic and live in an automatically removed temp directory.
"""
import argparse
import getpass
import io
import json
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from personalai.app import create_app
from personalai.backup import export_backup, restore_backup
from personalai.models import TZ
from personalai.store import Store
from personalai.scheduled_models import DailyAssessment, SECTION_NAMES
from pydantic import ValidationError

DIAGNOSTICS = {}


def run(base_url, model, key):
    calls = []
    DIAGNOSTICS.clear()
    DIAGNOSTICS.update(stage='fixture', requests=calls)

    class ObservedTransport(httpx.HTTPTransport):
        def handle_request(self, request):
            if len(calls) >= 2:
                raise RuntimeError('Two-call budget exhausted')
            calls.append({'status': None})
            start = time.monotonic()
            response = super().handle_request(request)
            calls[-1].update(status=response.status_code,
                             headers_seconds=round(time.monotonic() - start, 2))
            body = json.loads(request.content)
            inputs = json.loads(body['messages'][1]['content'])
            if 'items' in inputs and response.status_code == 200:
                # Test-only diagnostics: read the synthetic response in memory.
                # Output field/error locations only, never headers or raw bodies.
                try:
                    response.read()
                    choice = response.json()['choices'][0]
                    parsed = DailyAssessment.model_validate_json(choice['message']['content'])
                    allowed = set(inputs['sources'])
                    factual = {e['id'] for e in inputs['items'] if e['kind'] in {'note', 'log', 'checkin', 'state'}}
                    goals = {e['id'] for e in inputs['items'] if e['kind'] == 'goal'}
                    DIAGNOSTICS['citation_errors'] = [
                        {'section': section, 'index': index,
                         'unknown_source': not set(item.source_ids) <= allowed,
                         'missing_activity': section == 'facts' and not bool(set(item.source_ids) & factual),
                         'missing_goal': section == 'long_term' and not bool(set(item.source_ids) & goals)}
                        for section in SECTION_NAMES for index, item in enumerate(getattr(parsed, section))
                        if not set(item.source_ids) <= allowed or
                        section == 'facts' and not set(item.source_ids) & factual or
                        section == 'long_term' and not set(item.source_ids) & goals]
                except ValidationError as exc:
                    DIAGNOSTICS['schema_errors'] = [{'field': e['loc'], 'type': e['type']} for e in exc.errors()]
                except Exception:
                    DIAGNOSTICS['response_diagnostic'] = 'Unable to inspect response structure'
            return response

    with tempfile.TemporaryDirectory(prefix='personalai-provider-test-') as folder:
        root = Path(folder)
        app = create_app(root / 'data', port=18765)
        with TestClient(app, base_url='http://127.0.0.1:18765') as client:
            # No background calls. Exercise the report pipeline explicitly below.
            app.state.scheduler.stop()
            app.state.vault.read = lambda url: key if url == base_url.rstrip('/') else None
            client.headers['x-csrf-token'] = client.get('/api/session').json()['csrf_token']

            def post(path, **body):
                response = client.post(path, json={'request_id': str(uuid4()), **body})
                if response.status_code != 200:
                    raise RuntimeError(f'{path}: HTTP {response.status_code}')
                return response.json()

            connection = {'id': 'legacy', 'name': 'Isolated provider test',
                          'enabled': True, 'base_url': base_url, 'model': model,
                          'response_format': 'json_object'}
            change = post('/api/config/sections/models', expected_version=0,
                          data={'connections': [connection],
                                'bindings': {'goal': 'legacy', 'schedule': 'legacy'}})['change']
            post('/api/config/changes/' + change['id'] + '/decision', decision='accept')
            day = datetime.now(TZ).date().isoformat()
            goal = post('/api/goals', data={'title': '示例：阅读十章并留下笔记',
                        'criteria': '十章均阅读并逐章留下笔记', 'baseline': 0,
                        'target': 10, 'current': 2})['entity']
            task = post('/api/records', kind='task', date=day, text='示例：阅读前三章并写笔记')['record']
            change = post('/api/task-tracking', data={'task_id': task['id'],
                          'goal_id': goal['id'], 'progress': None})['change']
            post('/api/changes/' + change['id'] + '/decision', decision='accept')
            log = post('/api/activity-logs', data={'date': day, 'goal_id': goal['id'],
                       'task_id': task['id'], 'text': '示例：读完第一、二章，各写了一页笔记。第三章尚未记录。',
                       'result': '两章已完成并留有笔记', 'obstacle': '第三章部分术语需要查证'})['entity']
            post('/api/check-ins', data={'date': day, 'slot': 'noon', 'goal_id': goal['id'],
                 'response': '示例：记录了两章阅读进展，下一步先查第三章的术语。'})
            before_goal = app.state.store.entities[goal['id']].model_dump(mode='json')
            before_task = app.state.store.records[task['id']].model_dump(mode='json')

            selection = {'goal_id': goal['id'], 'task_ids': [task['id']], 'log_ids': [log['id']]}
            response = client.post('/api/analyses/preview', json=selection)
            assert response.status_code == 200
            preview = response.json()
            request = {**selection, 'sources': preview['input']['sources'],
                       'settings_version': preview['settings_version'],
                       'approved': True, 'request_id': str(uuid4())}
            app.state.model_transport = ObservedTransport()
            DIAGNOSTICS['stage'] = 'goal_analysis'
            analysis = post('/api/analyses', **request)
            DIAGNOSTICS['stage'] = 'goal_deduplication'
            assert post('/api/analyses', **request) == analysis
            assert len(calls) == 1
            assessment = analysis['analysis']['data']['assessment']
            DIAGNOSTICS['goal_estimate'] = {k: assessment[k] for k in ['low', 'high', 'confidence']}

            DIAGNOSTICS['stage'] = 'schedule_configuration'
            version = client.get('/api/schedule').json()['version']
            response = client.post('/api/schedule/preview', json={
                'data': {'enabled': True, 'times': ['23:59'],
                         'scopes': ['goals', 'tasks', 'logs', 'checkins']}, 'expected_version': version})
            assert response.status_code == 200
            post('/api/schedule/confirm', approval_token=response.json()['approval_token'], approved=True)
            app.state.model_transport = ObservedTransport()
            run_id = str(uuid4())
            DIAGNOSTICS['stage'] = 'daily_report'
            report = post('/api/schedule/run', request_id=run_id)
            DIAGNOSTICS['report_status'] = report['run']['data']['status']
            DIAGNOSTICS['report_message'] = report['run']['data']['message']
            assert report['run']['data']['status'] == 'succeeded'
            DIAGNOSTICS['stage'] = 'report_deduplication'
            assert post('/api/schedule/run', request_id=run_id)['run'] == report['run']
            assert len(calls) == 2
            DIAGNOSTICS['stage'] = 'formal_plan_unchanged'
            assert app.state.store.entities[goal['id']].model_dump(mode='json') == before_goal
            assert app.state.store.records[task['id']].model_dump(mode='json') == before_task
            post('/api/schedule/pause')

            DIAGNOSTICS['stage'] = 'backup_restore_and_secret_scan'
            raw = export_backup(app.state.store)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                assert not any('.secrets' in name for name in archive.namelist())
                assert all(key.encode() not in archive.read(name) for name in archive.namelist())
            restored = restore_backup(raw, root / 'restored')
            restarted = Store(root / 'data')
            assert [p.read_bytes() for p in restored.files] == [p.read_bytes() for p in restarted.files]
            for path in root.rglob('*'):
                if path.is_file():
                    assert key.encode() not in path.read_bytes()
            assert restarted.entities[analysis['analysis']['id']].kind == 'analysis'
            assert restarted.entities[report['run']['id']].data['status'] == 'succeeded'
            return {'passed': True, 'real_requests': calls, 'goal_estimate': {
                'low': assessment['low'], 'high': assessment['high'], 'confidence': assessment['confidence']},
                'contribution_count': len(assessment['contributions']),
                'report_sections': {name: len(items) for name, items in report['run']['data']['assessment'].items()},
                'duplicate_requests_no_extra_calls': True, 'formal_plan_unchanged': True,
                'restart_and_backup_restore_equal': True, 'plaintext_key_absent_from_test_files': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--key-stdin', action='store_true')
    args = parser.parse_args()
    credential = json.load(sys.stdin)['key'] if args.key_stdin else getpass.getpass('API key (hidden): ')
    try:
        if not credential.strip():
            raise ValueError('Empty credential')
        print(json.dumps(run(args.base_url, args.model, credential), ensure_ascii=True))
    except Exception as exc:
        # Never print provider bodies, request headers, credentials or tracebacks.
        print(json.dumps({'passed': False, 'error_type': type(exc).__name__, **DIAGNOSTICS}, ensure_ascii=True))
        raise SystemExit(1)
    finally:
        credential = None
