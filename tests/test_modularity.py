import hashlib
import json
import io
import zipfile
from pathlib import Path
from uuid import uuid4
from fastapi.testclient import TestClient
import pytest
from personalai.app import create_app
from personalai.store import Store, StoreError
from personalai.configuration import ConfigService, connection_vault
from personalai.tracking_models import WriteEntity
from personalai.models import Decision
from personalai.extensions import extension
from personalai.backup import export_backup, restore_backup
from personalai.runtime import load_runtime, DEFAULT_PLUGINS
from personalai.plugins import PluginManager, Plugin

@pytest.fixture
def client(tmp_path):
    app=create_app(tmp_path/'data',port=8765)
    c=TestClient(app,base_url='http://127.0.0.1:8765')
    c.headers['X-CSRF-Token']=c.get('/api/session').json()['csrf_token']
    return c

def post(c,url,data):
    r=c.post(url,json={'request_id':str(uuid4()),**data})
    assert r.status_code==200,r.text
    return r.json()

def save(c,section,data,version=0,accept=True):
    r=post(c,'/api/config/sections/'+section,{'data':data,'expected_version':version})
    if 'change' in r and accept:
        post(c,'/api/config/changes/'+r['change']['id']+'/decision',{'decision':'accept'})
    return r

def sections(c): return c.get('/api/config/sections').json()['sections']

def test_section_isolation_confirmation_and_stale(client):
    initial=sections(client)
    a=save(client,'user',{'name':'A','bio':'','focus':''},accept=False)
    assert sections(client)['user']['data']['name']==''
    ui=initial['ui']['data'];ui['hidden']=['year'];save(client,'ui',ui)
    post(client,'/api/config/changes/'+a['change']['id']+'/decision',{'decision':'accept'})
    assert sections(client)['user']['data']['name']=='A'
    b=save(client,'user',{'name':'B','bio':'','focus':''},1,False)
    save(client,'user',{'name':'C','bio':'','focus':''},1)
    r=client.post('/api/config/changes/'+b['change']['id']+'/decision',json={'request_id':str(uuid4()),'decision':'accept'})
    assert r.status_code==409
    assert sections(client)['ui']['data']['hidden']==['year']
    assert client.get('/api/settings').json()['settings']['name']=='C'

def test_rejected_config_and_repeat_confirm(client):
    r=save(client,'user',{'name':'Rejected','bio':'','focus':''},accept=False)
    request={'request_id':str(uuid4()),'decision':'reject'}
    path='/api/config/changes/'+r['change']['id']+'/decision'
    assert client.post(path,json=request).status_code==200
    assert client.post(path,json=request).status_code==200
    assert sections(client)['user']['data']['name']==''

def test_legacy_settings_remain_and_ui_does_not_change_model(client):
    old=client.get('/api/settings').json()['settings'];old['name']='Original'
    post(client,'/api/settings',{'data':old})
    store=client.app.state.store
    original={p.name:p.read_bytes() for p in store.events_dir.glob('*.md')}
    assert sections(client)['user']['data']['name']=='Original'
    save(client,'user',{'name':'New','bio':'','focus':''})
    for name,raw in original.items(): assert (store.events_dir/name).read_bytes()==raw
    assert client.get('/api/settings').json()['settings']['model']==old['model']
    assert ConfigService(Store(store.root)).combined()['name']=='New'

def test_two_connections_keys_and_bindings(client):
    model={'enabled':True,'base_url':'https://example.com/v1','model':'sample','response_format':'json_schema'}
    value={'connections':[{'id':'one','name':'One',**model},{'id':'two','name':'Two',**model}], 'bindings':{'goal':'one','schedule':'two'}}
    save(client,'models',value)
    for id,key in [('one','key-one'),('two','key-two')]:
        r=client.post('/api/config/connections/'+id+'/key',json={'base_url':model['base_url'],'key':key})
        assert r.status_code==200
    service=ConfigService(client.app.state.store)
    assert service.key(service.model('goal'))=='key-one'
    assert service.key(service.model('schedule'))=='key-two'
    assert client.app.state.scheduler.model()['connection_id']=='two'
    for token in ['key-one','key-two']:
        assert all(token not in p.read_text(encoding='utf-8') for p in client.app.state.store.files)
    value['connections'][0]['base_url']='https://different.example/v1'
    save(client,'models',value,1)
    assert service.key(service.model('goal')) is None
    assert service.key(service.model('schedule'))=='key-two'

def test_schedule_binding_changes_invalidate_consent(client):
    model={'enabled':True,'base_url':'https://example.com/v1','model':'sample','response_format':'json_schema'}
    data={'connections':[{'id':'a','name':'A',**model},{'id':'b','name':'B',**model}], 'bindings':{'goal':'a','schedule':'a'}}
    save(client,'models',data)
    for id in ['a','b']: connection_vault(client.app.state.store,id).save(model['base_url'],'sample-secret')
    preview=client.post('/api/schedule/preview',json={'data':{'enabled':True,'times':['23:59'],'scopes':['records']},'expected_version':0}).json()
    post(client,'/api/schedule/confirm',{'approval_token':preview['approval_token'],'approved':True})
    assert client.get('/api/schedule').json()['authorized']
    save(client,'user',{'name':'Unrelated','bio':'','focus':''})
    assert client.get('/api/schedule').json()['authorized']
    data['bindings']['schedule']='b';save(client,'models',data,1)
    assert not client.get('/api/schedule').json()['authorized']

def test_runtime_precedence_and_validation(tmp_path):
    f=tmp_path/'server.json';f.write_text(json.dumps({'port':19000,'data_dir':'records','plugins':['journal']}))
    r=load_runtime(f,port=19001)
    assert r.port==19001 and r.data_dir==str(tmp_path/'records') and r.plugins==['journal']
    f.write_text('{"host":"0.0.0.0"}')
    with pytest.raises(ValueError):load_runtime(f)

def test_plugin_off_readonly_and_unknown_backup(tmp_path):
    app=create_app(tmp_path/'data',port=8765,enabled_plugins=DEFAULT_PLUGINS+['example'])
    c=TestClient(app,base_url='http://127.0.0.1:8765');c.headers['X-CSRF-Token']=c.get('/api/session').json()['csrf_token']
    assert c.get('/api/plugins/example/hello').status_code==200
    item=post(c,'/api/plugin-data/example/entry',{'data':{'text':'Persist me'}})['entity']
    settings=post(c,'/api/plugin-data/example/settings',{'data':{}})['entity']
    assert settings['data']['heading']=='扩展示例'
    proposal=post(c,'/api/plugin-data/example/entry/'+item['id'],{'data':{'text':'Changed'},'expected_version':1})['change']
    post(c,'/api/plugin-changes/'+proposal['id']+'/decision',{'decision':'reject'})
    off=create_app(tmp_path/'data',port=8765,enabled_plugins=DEFAULT_PLUGINS)
    d=TestClient(off,base_url='http://127.0.0.1:8765');d.headers['X-CSRF-Token']=d.get('/api/session').json()['csrf_token']
    assert d.get('/api/plugins/example/hello').status_code==409
    assert d.post('/api/plugin-data/example/entry',json={'request_id':str(uuid4()),'data':{'text':'No'}}).status_code==409
    assert any(e['id']==item['id'] for e in d.get('/api/plugin-data').json()['entities'])
    store=off.state.store
    orphan=extension('missing/entry',{'a':[1,2],'text':'unknown plugin'},readable='Persisted rendering')
    store.transaction(uuid4(),'unknown',{},lambda:([],[],{},[orphan]),extension=True)
    restored=restore_backup(export_backup(store),tmp_path/'restored')
    assert restored.entities[orphan.id].data==orphan.data
    assert [p.read_bytes() for p in store.files]==[p.read_bytes() for p in restored.files]

def test_plugin_dependencies_and_failure_do_not_stop_core(tmp_path):
    app=create_app(tmp_path/'data',enabled_plugins=['analysis','dashboard'])
    states=app.state.plugins.states
    assert states['analysis']['status']=='blocked' and states['dashboard']['status']=='blocked'
    def fail(ctx):raise RuntimeError('failure')
    m=PluginManager(app,app.state.store,['bad','dependent','wrong'],[Plugin('bad','Bad',start=fail),Plugin('dependent','Dependent',dependencies=('bad',)),Plugin('wrong','Wrong',protocol=99)])
    m.lifecycle('start')
    assert m.states['bad']['status']=='failed' and m.states['dependent']['status']=='blocked' and m.states['wrong']['status']=='blocked'
    c=TestClient(app,base_url='http://127.0.0.1:8765')
    assert c.get('/api/records').status_code==200
    assert c.get('/api/goals').status_code==409

def test_integration_disabled_scoped_revocation_and_restore(client,tmp_path):
    c=client
    assert c.get('/api/integrations/v1/tasks').status_code==401
    token=c.post('/api/integration-settings/tokens',json={'name':'Reader','scopes':['tasks']}).json()['token']
    headers={'Authorization':'Bearer '+token}
    assert c.get('/api/integrations/v1/tasks',headers=headers).status_code==401
    assert c.post('/api/integration-settings',json={'enabled':True}).status_code==200
    assert c.get('/api/integrations/v1/goals',headers=headers).status_code==403
    assert c.get('/api/integrations/v1/tasks',headers=headers).status_code==200
    assert c.get('/api/integrations/v1/tasks?token='+token,headers=headers).status_code==400
    assert c.post('/api/integrations/v1/tasks',headers=headers,json={}).status_code==405
    raw=export_backup(c.app.state.store)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert all('.secrets' not in n for n in z.namelist())
        assert all(token.encode() not in z.read(n) for n in z.namelist())
    restored=restore_backup(raw,tmp_path/'restored')
    from personalai.integrations import IntegrationAccess
    assert IntegrationAccess(restored).read()=={'enabled':False,'tokens':[]}
    identifier=c.get('/api/integration-settings').json()['tokens'][0]['id']
    c.post('/api/integration-settings/tokens/'+identifier+'/revoke')
    assert c.get('/api/integrations/v1/tasks',headers=headers).status_code==401

def test_quick_record_dedup_task_progress_and_read_api(client):
    c=client
    task=post(c,'/api/records',{'text':'Work','date':'2026-10-25','kind':'task','category':'plan'})['record']
    payload={'request_id':str(uuid4()),'text':'Made progress','date':'2026-10-25','task_id':task['id'],'result':'Draft','obstacle':''}
    first=c.post('/api/quick-record',json=payload);assert first.status_code==200,first.text
    assert c.post('/api/quick-record',json=payload).json()==first.json()
    assert c.get('/api/records/'+task['id']).json()['record']['status']=='open'
    assert len(c.get('/api/activity-logs').json()['entities'])==1
    assert len(c.get('/api/records?kind=note').json()['records'])==0
    token=c.post('/api/integration-settings/tokens',json={'name':'Read','scopes':['tasks','logs','reports']}).json()['token']
    c.post('/api/integration-settings',json={'enabled':True});headers={'Authorization':'Bearer '+token}
    items=c.get('/api/integrations/v1/tasks?day=2026-10-25',headers=headers).json()['items']
    assert items[0]['confirmed_progress'] is None and items[0]['id']==task['id']
    logs=c.get('/api/integrations/v1/logs?task_id='+task['id'],headers=headers).json()['items']
    assert logs[0]['text']=='Made progress'
    assert c.get('/api/integrations/v1/tasks?day=2026-10-24',headers=headers).json()['items']==[]

def test_unknown_type_rejects_write_and_bad_versions(client):
    assert client.post('/api/plugin-data/nope/entry',json={'request_id':str(uuid4()),'data':{}}).status_code==409
    assert client.post('/api/config/sections/user',json={'request_id':str(uuid4()),'expected_version':5,'data':{'name':'X'}}).status_code==409
    c=TestClient(client.app,base_url='http://127.0.0.1:8765')
    assert c.post('/api/integration-settings',json={'enabled':True}).status_code==403


def test_model_preview_version_ignores_other_sections(client):
    model={'enabled':False,'base_url':'https://example.com/v1','model':'sample','response_format':'json_schema'}
    value={'connections':[{'id':'one','name':'One',**model},{'id':'two','name':'Two',**model}], 'bindings':{'goal':'one','schedule':'two'}}
    save(client,'models',value)
    service=ConfigService(client.app.state.store)
    version=service.model_version('goal')
    save(client,'user',{'name':'Unrelated','bio':'','focus':''})
    assert service.model_version('goal')==version
    value['connections'][1]['model']='another'
    save(client,'models',value,1)
    assert service.model_version('goal')==version
    value['connections'][0]['model']='changed'
    save(client,'models',value,2)
    assert service.model_version('goal')!=version


def test_old_settings_endpoint_adapts_split_sections(client):
    save(client,'user',{'name':'Split','bio':'','focus':''})
    old=client.get('/api/settings').json()
    old['settings']['name']='Via old API'
    old['settings']['model']['model']='test-model'
    r=post(client,'/api/settings',{'data':old['settings'],'expected_version':old['version']})
    post(client,'/api/changes/'+r['change']['id']+'/decision',{'decision':'accept'})
    assert sections(client)['user']['data']['name']=='Via old API'
    assert ConfigService(client.app.state.store).model('goal')['model']=='test-model'


def test_type_deactivation_retains_history_and_plugin_failure(tmp_path):
    app=create_app(tmp_path/'data')
    def setup(ctx):
        def fail():raise ValueError('not user-facing')
        ctx.add_route('/fail',fail)
    manager=PluginManager(app,app.state.store,['broken'],[Plugin('broken','Broken',setup=setup)])
    app.state.plugins=manager;manager.lifecycle('setup')
    c=TestClient(app,base_url='http://127.0.0.1:8765')
    assert c.get('/api/plugins/broken/fail').status_code==503
    assert c.get('/api/plugins/broken/fail').status_code==409
    assert c.get('/api/records').status_code==200


def test_token_pagination_and_report_no_internal_config(client):
    from personalai.tracking import entity
    c=client;store=c.app.state.store
    for i in range(3):
        post(c,'/api/records',{'text':'Task '+str(i),'kind':'task','date':'2026-10-25','category':'plan'})
    goal=post(c,'/api/goals',{'data':{'title':'Goal','criteria':'Done'}})['entity']
    assessment={'low':None,'high':None,'confidence':'insufficient','explanation':'No evidence','source_ids':[], 'contributions':[], 'missing':['Logs'],'suggestions':['Record progress']}
    item=entity('analysis',{'goal_id':goal['id'],'model':'private-model','base_url':'https://private.example/v1','sources':{goal['id']:1},'assessment':assessment})
    store.transaction(uuid4(),'fixture-analysis',{},lambda:([],[],{},[item]),extension=True)
    token=c.post('/api/integration-settings/tokens',json={'name':'Reader','scopes':['tasks','reports']}).json()['token']
    c.post('/api/integration-settings',json={'enabled':True});headers={'Authorization':'Bearer '+token}
    a=c.get('/api/integrations/v1/tasks?limit=2',headers=headers).json()
    b=c.get('/api/integrations/v1/tasks?limit=2&offset=2',headers=headers).json()
    assert a['total']==3 and a['next_offset']==2 and len(b['items'])==1
    assert {e['id'] for e in a['items']}.isdisjoint({e['id'] for e in b['items']})
    result=c.get('/api/integrations/v1/reports',headers=headers)
    assert 'private-model' not in result.text and 'private.example' not in result.text and '.secrets' not in result.text
    assert result.json()['items'][0]['assessment']['suggestions']==['Record progress']


def test_plugin_lifecycle_stop_reverses_dependency_order(tmp_path):
    app=create_app(tmp_path/'data');calls=[]
    a=Plugin('a','A',start=lambda c:calls.append('start-a'),stop=lambda c:calls.append('stop-a'))
    b=Plugin('b','B',dependencies=('a',),start=lambda c:calls.append('start-b'),stop=lambda c:calls.append('stop-b'))
    m=PluginManager(app,app.state.store,['a','b'],[b,a]);m.lifecycle('start');m.lifecycle('stop')
    assert calls==['start-a','start-b','stop-b','stop-a']


def test_quick_entry_long_combination_reports_input_error(client):
    r=client.post('/api/quick-record',json={'request_id':str(uuid4()),'date':'2026-10-25','text':'a'*10000,'result':'x'})
    assert r.status_code==422
    assert not client.get('/api/records').json()['records']


def test_plugin_accept_and_stale_confirmation(tmp_path):
    app=create_app(tmp_path/'data',enabled_plugins=['example'])
    c=TestClient(app,base_url='http://127.0.0.1:8765');c.headers['X-CSRF-Token']=c.get('/api/session').json()['csrf_token']
    item=post(c,'/api/plugin-data/example/entry',{'data':{'text':'old'}})['entity']
    changes=[post(c,'/api/plugin-data/example/entry/'+item['id'],{'data':{'text':text},'expected_version':1})['change'] for text in ['one','two']]
    post(c,'/api/plugin-changes/'+changes[0]['id']+'/decision',{'decision':'accept'})
    r=c.post('/api/plugin-changes/'+changes[1]['id']+'/decision',json={'request_id':str(uuid4()),'decision':'accept'})
    assert r.status_code==409
    assert c.get('/api/plugin-data?plugin=example').json()['entities'][0]['data']['text']=='one'


def test_disabled_task_plugin_cannot_create_or_confirm_task(client):
    c=client
    task=post(c,'/api/records',{'text':'Task','date':'2026-10-25','kind':'task','category':'plan'})['record']
    proposal=post(c,'/api/records/'+task['id']+'/revisions',{'text':'Revised','date':'2026-10-25','category':'plan','status':'open','expected_version':1,'reason':'Test'})['proposal']
    app=create_app(c.app.state.store.root,enabled_plugins=['journal'])
    d=TestClient(app,base_url='http://127.0.0.1:8765');d.headers['X-CSRF-Token']=d.get('/api/session').json()['csrf_token']
    assert d.post('/api/records',json={'request_id':str(uuid4()),'text':'No','date':'2026-10-25','kind':'task','category':'plan'}).status_code==409
    assert d.post('/api/proposals/'+proposal['id']+'/decision',json={'request_id':str(uuid4()),'decision':'accept'}).status_code==409
    assert d.get('/api/records/'+task['id']).json()['record']['text']=='Task'
