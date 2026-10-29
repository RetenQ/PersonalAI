from uuid import uuid4
from fastapi.testclient import TestClient
from personalai.tracking import entity
from personalai.plugins import PluginManager
from test_clients import env, device, agent, command, P


def goal(owner, title='授权目标'):
    r = owner.post('/api/goals', json={'request_id': str(uuid4()), 'data': {'title': title, 'criteria':'十章', 'baseline':0, 'target':10}})
    assert r.status_code == 200, r.text
    return r.json()['entity']


def test_atomic_command_sync_identity_and_authorization(env):
    app, owner, _ = env
    c, tokens = device(app, owner)
    g = goal(owner)
    cursor = c.get(P+'/snapshot').json()['cursor']
    sequence = app.state.store.sequence
    made, payload = command(c, 'create_task', {'text':'原子任务','date':'2026-10-29','goal_id':g['id']})
    assert c.post(P+'/commands', json=payload).json() == made
    assert app.state.store.sequence == sequence+1
    task = made['record']
    delta = c.get(P+'/changes', params={'cursor':cursor}).json()
    row = next(r for r in delta['data']['tasks'] if r['id']==task['id'])
    assert row['goal_id']==g['id'] and row['origin']['actor_id']==tokens['client_id']
    assert row['tracking']['data']['progress'] is None
    assert c.get(P+'/snapshot').json()['data']['tasks'] == delta['data']['tasks']
    assert c.post(P+'/commands',json={**payload,'data':{**payload['data'],'text':'different'}}).status_code==409
    bad={**payload,'request_id':str(uuid4()),'data':{**payload['data'],'goal_id':str(uuid4())}}
    assert c.post(P+'/commands',json=bad).status_code==404
    assert app.state.store.sequence==sequence+1
    assert c.post(P+'/commands',json={**bad,'operation':'create_record'}).status_code==422
    other,_=device(app,owner,'tablet')
    assert other.post(P+'/commands',json=payload).json()['record']['id']!=task['id']
    a,_=agent(app,owner,['read:tasks','read:goals','write:records','propose'])
    assert not a.get(P+'/capabilities').json()['features']['atomic_task_create_v1']
    assert a.post(P+'/commands',json=payload).status_code==403
    proposal,_=command(a,'create_record',{'kind':'task','text':'待确认任务','date':'2026-10-29'})
    assert proposal['proposal']['status']=='pending'


def test_features_revocation_plugin_and_unauthenticated(env):
    app,owner,_=env
    c,tokens=device(app,owner)
    assert all(c.get(P+'/capabilities').json()['features'].values())
    reminder_only,_=agent(app,owner,['read:reminders'])
    assert not reminder_only.get(P+'/capabilities').json()['features']['history_search_v1']
    assert reminder_only.get(P+'/history').status_code==403
    anon=TestClient(app,base_url='http://127.0.0.1:8765')
    for path in ['/capabilities','/history','/task-events']:
        assert anon.get(P+path).status_code==401
    app.state.plugins=PluginManager(app,app.state.store,['journal'])
    flags=c.get(P+'/capabilities').json()['features']
    assert not flags['atomic_task_create_v1'] and not flags['task_events_v1'] and not flags['goal_created_at_v1'] and not flags['report_coverage_v1']
    assert c.get(P+'/task-events').status_code==409
    assert c.post(P+'/commands',json={'request_id':str(uuid4()),'operation':'create_task','data':{'text':'x','date':'2026-10-29'}}).status_code==409
    assert owner.post('/api/client-admin/'+tokens['client_id']+'/revoke').status_code==200
    assert c.get(P+'/history').status_code==401
    assert c.get(P+'/task-events').status_code==401


def test_events_scope_time_names_pagination_and_read_only(env,monkeypatch):
    app,owner,_=env
    c,_=device(app,owner)
    stamp=['2026-10-28T16:30:00+00:00']  # Shanghai Oct 29, different from planned day.
    for module in ['personalai.tracking','personalai.task_routes','personalai.store']:
        monkeypatch.setattr(module+'.now',lambda:stamp[0])
    g=goal(owner,'旧目标名称')
    made,_=command(c,'create_task',{'text':'原文','date':'2000-01-01','goal_id':g['id']})
    task=made['record']
    url=P+'/task-events?day=2026-10-29'
    original=c.get(url).json()
    assert original['total']==3
    assert c.get(P+'/task-events?day=2000-01-01').json()['total']==0
    p,_=command(c,'revise_record',{**{k:task[k] for k in ['text','date','category']},'status':'done'},id=task['id'],expected_version=1)
    assert c.get(url).json()['items']==original['items']
    command(c,'decide',{'decision':'reject'},id=p['proposal']['id'])
    assert c.get(url).json()['items']==original['items']
    stamp[0]='2026-10-30T10:00:00+08:00'
    change,_=command(c,'write_entity',{**g['data'],'title':'新名称'},kind='goal',id=g['id'],expected_version=1)
    command(c,'decide',{'decision':'accept'},id=change['change']['id'])
    assert c.get(url).json()['items']==original['items']
    task_only,_=agent(app,owner,['read:tasks'])
    limited=task_only.get(url).json()
    assert limited['total']==1 and '旧目标名称' not in str(limited)
    goal_only,_=agent(app,owner,['read:goals'])
    assert goal_only.get(url).json()['total']==1
    assert c.get(url+'&limit=1').json()['next_offset']==1
    assert c.get(url+'&limit=101').status_code==422
    seq=app.state.store.sequence
    c.get(url); c.get(url)
    assert app.state.store.sequence==seq


def test_history_old_versions_scopes_and_source_lookup(env):
    app,owner,_=env
    c,_=device(app,owner)
    g=goal(owner,'秘密目标')
    r,_=command(c,'create_record',{'text':'旧关键词','date':'2026-10-28'})
    record=r['record']
    p,_=command(c,'revise_record',{'text':'新内容','date':'2026-10-29','category':'uncategorized','status':'open'},id=record['id'],expected_version=1)
    command(c,'decide',{'decision':'accept'},id=p['proposal']['id'])
    made,_=command(c,'create_task',{'text':'关联任务','date':'2026-10-29','goal_id':g['id']})
    records,_=agent(app,owner,['read:records'])
    result=records.get(P+'/history',params={'q':'旧关键词','day':'2026-10-28'}).json()
    assert result['total']==1
    assert result['items'][0]['matches'][0]['version']==1
    assert result['items'][0]['history'][-1]['text']=='新内容'
    assert result['items'][0]['source']['id']==record['id']
    assert records.get(P+'/history?kind=goal').json()['total']==0
    assert records.get(P+'/history/'+g['id']).status_code==403
    tasks,_=agent(app,owner,['read:tasks'])
    assert tasks.get(P+'/history?kind=tracking').json()['total']==0
    assert tasks.get(P+'/history/tracking:'+made['record']['id']).status_code==403
    assert c.get(P+'/history?limit=1').json()['next_offset']==1
    assert c.get(P+'/history?offset=999').json()['items']==[]
    assert c.get(P+'/history',params={'q':'x'*501}).status_code==422
    assert c.get(P+'/history?kind=note&day=2026-10-27').json()['total']==0


def test_report_backfill_coverage_safe_history_and_goal_creation_time(env):
    app,owner,_=env
    c,_=device(app,owner)
    g=goal(owner)
    assert c.get(P+'/resources/goals').json()['items'][0]['created_at']==g['created_at']
    def run(start):
        data={'scheduled_at':start,'started_at':start,'finished_at':None,'schedule_version':1,'trigger':'manual','status':'skipped','message':'',
              'window_start':'2026-10-20','window_end':'2026-10-26','sampled_at':start,'model':'test-model','base_url':'https://private-endpoint.example/v1',
              'sources':{},'source_labels':{},'source_kinds':{},'input_hash':'hash','assessment':None}
        item=entity('scheduled_run',data)
        app.state.store.transaction(uuid4(),'test-report',data,lambda:([],[],{},[item]),extension=True)
        return item
    older=run('2026-10-29T09:00:00+08:00')
    latest=run('2026-10-29T10:00:00+08:00')
    reports=c.get(P+'/resources/reports?day=2026-10-26').json()['items']
    assert [x['id'] for x in reports]==[latest.id,older.id]
    assert reports[0]['model']=='test-model' and reports[0]['window_start']=='2026-10-20'
    assert c.get(P+'/resources/reports?day=2026-10-29').json()['items']==[]
    for path in ['/history?kind=scheduled_run&day=2026-10-26','/history/'+latest.id]:
        response=c.get(P+path)
        assert response.status_code==200
        assert 'private-endpoint' not in response.text and 'base_url' not in response.text
    assert c.get(P+'/history?q=private-endpoint').json()['total']==0


def test_generated_contract_matches_runtime_source():
    import json
    import runpy
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    module = runpy.run_path(str(root/'scripts/export_client_contract.py'))
    actual = module['contract']()
    assert actual == json.loads((root/'docs/openapi.clients.v1.json').read_text(encoding='utf-8'))
    assert P+'/history' in actual['paths'] and P+'/history/{identifier}' in actual['paths']
    assert 'create_task' in actual['components']['schemas']['Command']['properties']['operation']['enum']
    assert 'TaskEventPage' in actual['components']['schemas']
