"""Explicitly scoped, local-only read API. Tokens are never part of event backups."""
import hashlib
import json
import secrets
from datetime import datetime
from uuid import uuid4, UUID
import portalocker
from fastapi import Request, Query, HTTPException
from pydantic import Field
from .models import StrictModel, TZ
from .store import StoreError
from .tracking import TrackingService
from .user_files import atomic_write, check_path

SCOPES = {'goals','tasks','logs','checkins','reports'}
class AccessSettings(StrictModel):
    enabled: bool
class NewToken(StrictModel):
    name: str = Field(min_length=1,max_length=80)
    scopes: list[str] = Field(min_length=1,max_length=5)

class IntegrationAccess:
    def __init__(self, store):
        self.store=store
    def path(self): return check_path(self.store.root,'.secrets/integrations.json')
    def read(self):
        path=self.path()
        if not path.exists(): return {'enabled':False,'tokens':[]}
        try:
            value=json.loads(path.read_bytes())
            if not isinstance(value['enabled'],bool) or not isinstance(value['tokens'],list): raise ValueError()
            return value
        except (OSError,ValueError,KeyError): raise StoreError('接口授权文件不可读，已拒绝外部访问。',503)
    def mutate(self, change):
        with self.store.mutex, portalocker.Lock(str(check_path(self.store.root,'.integrations.lock')),timeout=10):
            value=self.read(); result=change(value)
            atomic_write(self.path(),json.dumps(value,ensure_ascii=False).encode())
            return result
    def authorize(self,request,scope):
        if request.query_params.get('token') or request.query_params.get('api_key'):
            raise HTTPException(400,'请通过 Authorization 请求头提供令牌。')
        value=self.read()
        header=request.headers.get('authorization','')
        if not value['enabled'] or not header.startswith('Bearer '): raise HTTPException(401,'外部读取未启用或缺少令牌。')
        hashed=hashlib.sha256(header[7:].encode()).hexdigest()
        token=next((t for t in value['tokens'] if secrets.compare_digest(t['hash'],hashed)),None)
        if not token: raise HTTPException(401,'令牌无效或已撤销。')
        if scope not in token['scopes']: raise HTTPException(403,'令牌未授权此类资料。')

def integration_items(store,resource,day=None,goal_id=None,task_id=None):
    service=TrackingService(store)
    snapshot=service.snapshot(day or datetime.now(TZ).date(),goal_id,include_user_files=False)
    if resource=='goals':
        items=[{'id':e['id'],'version':e['version'],'updated_at':e['updated_at'],'source':{'id':e['id'],'version':e['version']},
            'title':e['data']['title'],'criteria':e['data']['criteria'],'due':e['data']['due'],'confirmed_progress':e['progress']} for e in snapshot['goals']]
        if task_id:
            linked=store.entities.get('tracking:'+task_id)
            items=[e for e in items if linked and e['id']==linked.data['goal_id']]
        if day: items=[e for e in items if e['due']==day.isoformat()]
        return items
    if resource=='tasks':
        return [{'id':t['record']['id'],'version':t['record']['version'],'updated_at':max(t['record']['updated_at'],t['tracking']['updated_at'] if t['tracking'] else ''),
            'sources':{t['record']['id']:t['record']['version'],**({t['tracking']['id']:t['tracking']['version']} if t['tracking'] else {})},
            'text':t['record']['text'],'status':t['record']['status'],'planned_date':t['record']['date'],'goal_id':t['goal_id'],
            'tags':t['tags'],'confirmed_progress':t['progress']} for t in snapshot['tasks'] if (not task_id or t['task_id']==task_id) and (not day or t['record']['date']==day.isoformat())]
    if resource in {'logs','checkins'}:
        kind='log' if resource=='logs' else 'checkin'
        if task_id and resource=='checkins': raise HTTPException(422,'回顾关联目标，不直接关联任务，请使用 goal_id。')
        return [{'id':e.id,'version':e.version,'updated_at':e.updated_at,'source':{'id':e.id,'version':e.version},**e.data}
            for e in store.entities.values() if e.kind==kind and (not day or e.data['date']==day.isoformat())
            and (not goal_id or e.data.get('goal_id')==goal_id) and (not task_id or e.data.get('task_id')==task_id)]
    versions={e.id:e.version for e in store.entities.values()}
    versions.update({str(r.id):r.version for r in store.records.values()})
    items=[]
    for e in store.entities.values():
        if e.kind not in {'analysis','scheduled_run'}: continue
        d=e.data; sources=d['sources']
        if day and datetime.fromisoformat(d.get('started_at',e.created_at)).astimezone(TZ).date()!=day: continue
        if goal_id and d.get('goal_id')!=goal_id and goal_id not in sources: continue
        if task_id and task_id not in sources: continue
        items.append({'id':e.id,'version':e.version,'updated_at':e.updated_at,'kind':e.kind,'sources':sources,
            'stale':any(versions.get(k)!=v for k,v in sources.items()),'status':d.get('status','succeeded'),
            'scheduled_at':d.get('scheduled_at'),'finished_at':d.get('finished_at'),
            'assessment':d.get('assessment'),'message':d.get('message','')})
    return items

def register_integrations(app,store):
    access=IntegrationAccess(store)
    @app.get('/api/integration-settings')
    def settings():
        value=access.read()
        return {'enabled':value['enabled'],'scopes':sorted(SCOPES),'tokens':[{k:v for k,v in t.items() if k!='hash'} for t in value['tokens']]}
    @app.post('/api/integration-settings')
    def configure(payload:AccessSettings):
        def apply(value): value['enabled']=payload.enabled; return {'enabled':payload.enabled}
        return access.mutate(apply)
    @app.post('/api/integration-settings/tokens')
    def create(payload:NewToken):
        if len(set(payload.scopes))!=len(payload.scopes) or not set(payload.scopes)<=SCOPES: raise HTTPException(422,'资料范围无效。')
        token=secrets.token_urlsafe(36)
        entry={'id':str(uuid4()),'name':payload.name,'scopes':payload.scopes,'hash':hashlib.sha256(token.encode()).hexdigest()}
        def apply(value):
            if len(value['tokens'])>=50: raise StoreError('最多保留 50 个令牌，请先撤销不用的令牌。',422)
            value['tokens'].append(entry)
            return {'id':entry['id'],'token':token,'notice':'只显示本次；请保存在调用程序的私有配置中。'}
        return access.mutate(apply)
    @app.post('/api/integration-settings/tokens/{identifier}/revoke')
    def revoke(identifier:UUID):
        def apply(value): value['tokens']=[t for t in value['tokens'] if t['id']!=str(identifier)]; return {'revoked':True}
        return access.mutate(apply)
    @app.get('/api/integrations/v1/{resource}')
    def query(resource:str,request:Request,day:str|None=None,goal_id:UUID|None=None,task_id:UUID|None=None,
              limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0)):
        if resource not in SCOPES: raise HTTPException(404,'未知资料类型。')
        access.authorize(request,resource)
        try: date=datetime.strptime(day,'%Y-%m-%d').date() if day else None
        except ValueError: raise HTTPException(422,'日期请使用 YYYY-MM-DD。')
        with store.mutex:
            store.reload(); store.require_healthy()
            items=integration_items(store,resource,date,str(goal_id) if goal_id else None,str(task_id) if task_id else None)
            sequence=store.sequence
        items.sort(key=lambda e:(e['updated_at'],e['id']),reverse=True)
        end=offset+limit
        return {'api_version':1,'timezone':'Asia/Shanghai','snapshot_version':sequence,'total':len(items),
            'next_offset':end if end<len(items) else None,'items':items[offset:end]}
