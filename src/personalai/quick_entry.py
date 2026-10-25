from datetime import date
from uuid import UUID
from pydantic import Field
from .models import StrictModel, CreateRecord
from .tracking_models import WriteEntity
from .tracking import TrackingService
from .store import StoreError

class QuickEntry(StrictModel):
    request_id: UUID
    text: str = Field(min_length=1,max_length=10000)
    date: date
    task_id: UUID | None = None
    result: str = Field(default='',max_length=3000)
    obstacle: str = Field(default='',max_length=3000)

def register_quick_entry(app,store):
    @app.post('/api/quick-record')
    def quick(payload:QuickEntry):
        if not payload.text.strip(): raise StoreError('请填写内容。',422)
        if payload.task_id:
            if not app.state.plugins.active('journal') or not app.state.plugins.active('tracking'):
                raise StoreError('任务日志插件未启用。',409)
            with store.mutex:
                store.reload(); store.require_healthy()
                tracking=store.entities.get('tracking:'+str(payload.task_id))
                goal=tracking.data['goal_id'] if tracking else None
            return TrackingService(store).write('log',WriteEntity(request_id=payload.request_id,data={
                'date':payload.date.isoformat(),'task_id':str(payload.task_id),'goal_id':goal,
                'text':payload.text,'result':payload.result,'obstacle':payload.obstacle}))
        text=payload.text
        if payload.result: text+='\n\n结果：'+payload.result
        if payload.obstacle: text+='\n\n阻碍：'+payload.obstacle
        if len(text)>10000: raise StoreError('普通记录与补充内容合计不能超过 10000 字，请缩短后重试。',422)
        return store.create(CreateRecord(request_id=payload.request_id,text=text,date=payload.date,kind='note',category='uncategorized'))
