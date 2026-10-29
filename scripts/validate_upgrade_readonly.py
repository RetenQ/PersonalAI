"""Validate the installed release over HTTPS without business writes or new grants.

The owner credential stays in memory. No device token is inferred from stored
hashes. Device-only features are covered by isolated protocol tests, not by the
owner-cookie check here. Existing grants and records remain unchanged.
"""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess
from uuid import uuid4

import httpx

ROOT = Path('/var/lib/personalai-test/data')
RELEASE = Path('/opt/personalai-test/releases/218c5e7-server1')
P = '/api/clients/v1'


def expect(response, status=200):
    if response.status_code != status:
        raise RuntimeError(f'HTTP status {response.status_code}, expected {status}')
    return response


def events():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'events').glob('*.md')}


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    config = json.loads(Path('/etc/personalai-test/server.json').read_text())
    assert config['data_dir'] == str(ROOT)
    origin = config['public_origin']
    assert origin == 'https://personalai.retenq.cloud'
    report = {'started_at':datetime.now().astimezone().isoformat(),'origin':origin,'checks':[],
              'public_device_bearer_checked':False,'business_writes':False}
    before = events()
    identity_before = json.loads((ROOT/'.secrets/access.json').read_text())
    secret = subprocess.run(['systemd-creds','decrypt','--name=owner-password',
                             '/etc/personalai-test/owner-password.cred','-'],capture_output=True,check=True).stdout.decode()
    with httpx.Client(base_url=origin, trust_env=False, timeout=30) as anonymous, \
         httpx.Client(base_url=origin, headers={'Origin':origin}, trust_env=False, timeout=30) as owner:
        status = expect(anonymous.get('/api/auth/status')).json()
        assert status['configured'] and status['required'] and not status['authenticated']
        page = expect(anonymous.get('/'))
        assert page.content == (RELEASE/'frontend/dist/index.html').read_bytes()
        assets = re.findall(r'(?:src|href)="(/assets/[^"?#]+)"',page.text)
        assert len(assets) >= 2
        for asset in assets:
            response = expect(anonymous.get(asset))
            assert response.content == (RELEASE/'frontend/dist'/asset.lstrip('/')).read_bytes()
        report['checks'].append('HTTPS certificate trusted; index and JS/CSS exactly match new release')
        for route in ['/api/records',P+'/capabilities',P+'/history',P+'/task-events',P+'/snapshot']:
            expect(anonymous.get(route),401)
            expect(anonymous.get(route,headers={'Authorization':'Bearer invalid-upgrade-probe'}),401)
        command = {'request_id':str(uuid4()),'operation':'create_task','data':{'text':'UNSAVED AUTH CHECK','date':'2026-10-29'}}
        expect(anonymous.post(P+'/commands',json=command),401)
        expect(anonymous.post(P+'/commands',json=command,headers={'Authorization':'Bearer invalid-upgrade-probe'}),401)
        report['checks'].append('Unauthenticated and invalid Bearer reads/writes return 401')
        login=expect(owner.post('/api/auth/login',json={'password':secret}))
        assert all(value in login.headers['set-cookie'].lower() for value in ['secure','httponly','samesite=strict'])
        csrf=expect(owner.get('/api/session')).json()['csrf_token']
        try:
            health=expect(owner.get('/api/status')).json()
            assert health['storage']['healthy']
            report['model_status']=health['model']['status']
            caps=expect(owner.get(P+'/capabilities')).json()
            assert caps['role']=='owner'
            expected={'atomic_task_create_v1':False,'task_events_v1':True,'history_search_v1':True,
                      'report_coverage_v1':True,'goal_created_at_v1':True}
            assert caps['features']==expected
            assert 'read:states' not in caps['scopes']
            report['capabilities']={'api_version':caps['api_version'],'role':caps['role'],'features':caps['features']}
            contract=expect(owner.get(P+'/openapi.json')).json()
            published=json.loads((RELEASE/'docs/openapi.clients.v1.json').read_text())
            # Export adds auth/error descriptions and command-data schemas to the
            # runtime OpenAPI; compare every live schema and operation shape.
            assert set(contract['paths'])==set(published['paths'])
            for name, schema in contract['components']['schemas'].items():
                assert published['components']['schemas'][name]==schema
            for path, methods in contract['paths'].items():
                for method, operation in methods.items():
                    documented=published['paths'][path][method]
                    for key in ['requestBody','parameters']:
                        assert operation.get(key)==documented.get(key)
                    assert operation['responses']['200']==documented['responses']['200']
            assert 'create_task' in contract['components']['schemas']['Command']['properties']['operation']['enum']
            report['checks'].append('Owner capability flags reflect role; runtime API shapes match published 218c5e7 contract')
            for route in [P+'/history?limit=1',P+'/task-events?limit=1']:
                value=expect(owner.get(route)).json()
                assert all(k in value for k in ['items','total','next_offset','snapshot_version'])
            snapshot=expect(owner.get(P+'/snapshot')).json()
            assert 'states' not in snapshot['data']
            expect(owner.get(P+'/changes',params={'cursor':snapshot['cursor']}))
            goals=expect(owner.get(P+'/resources/goals?limit=1')).json()['items']
            assert all('created_at' in item for item in goals)
            reports=expect(owner.get(P+'/resources/reports?limit=1')).json()['items']
            assert all(all(k in item for k in ['window_start','window_end','started_at','model']) for item in reports)
            assert all(not any(k in item for k in ['base_url','endpoint','api_key']) for item in reports)
            schedule=expect(owner.get('/api/schedule')).json()
            push=expect(owner.get('/api/client-admin/push')).json()
            assert not schedule['authorized'] and not schedule['active'] and not push['config']['enabled']
            report['checks'].append('New read routes, snapshot/changes and storage healthy; auto-analysis/push disabled')
            report['report_samples_present']=bool(reports)
        finally:
            expect(owner.post('/api/auth/logout',headers={'X-CSRF-Token':csrf}))
        expect(owner.get('/api/records'),401)
    after=json.loads((ROOT/'.secrets/access.json').read_text())
    assert all(after[k]==identity_before[k] for k in ['owner','clients','tokens','pairings'])
    assert events()==before
    report.update(success=True,events_unchanged=True,grants_unchanged=True,
                  finished_at=datetime.now().astimezone().isoformat())
    output=Path('/var/lib/personalai-test/validation-upgrade-20261029.json')
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        import traceback
        frames=traceback.extract_tb(error.__traceback__)
        print('Read-only deployment verification failed:',type(error).__name__,
              [(Path(frame.filename).name,frame.lineno) for frame in frames])
        raise SystemExit(1)
