import { useEffect, useState } from 'react';
import { DataView, Dialog } from './trackingUI';
import { api } from './api';
export interface TaskEvent {id:string;task_id:string|null;entity_id?:string;version:number;time:string;title:string;action:string}
export function TaskEvents({day,revision,record}:{day:string;revision:number;record:(id:string)=>void}) {
 const [history,setHistory]=useState<any>();
 const [items,setItems]=useState<TaskEvent[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(true);
 useEffect(()=>{const controller=new AbortController();setBusy(true);setError('');api<{items:TaskEvent[]}>('/api/task-events?day='+day,{signal:controller.signal}).then(r=>{if(!controller.signal.aborted)setItems(r.items);}).catch(e=>{if(!controller.signal.aborted)setError(e.message);}).finally(()=>{if(!controller.signal.aborted)setBusy(false);});return()=>controller.abort();},[day,revision]);
 return <><h2>任务与目标动态</h2>{error?<p role="alert">{error}</p>:busy?<p role="status">正在读取…</p>:items.length?items.map(e=><article className="timeline-entry" key={e.id}><p className="quiet">{new Date(e.time).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})} · 修订 {e.version}</p><p>{e.action}</p><button className="text-button" onClick={()=>{if(e.entity_id)api('/api/entities/'+e.entity_id).then(setHistory).catch(e=>setError(e.message));else if(e.task_id)record(e.task_id);}}>{e.title}</button></article>):<p className="module-empty">当天暂无变更。</p>}{history&&<Dialog title="来源与修订历史" close={()=>setHistory(undefined)}>{history.history.slice().reverse().map((v:any)=><details key={v.version}><summary>修订 {v.version}</summary><DataView data={v.data}/></details>)}</Dialog>}</>;
}
