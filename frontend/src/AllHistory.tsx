import { useEffect, useState } from 'react';
import { api } from './api';
import { DataView, Dialog } from './trackingUI';

const labels: Record<string, string> = {note:'日常记录',task:'任务',idea:'待定任务（原想法）',goal:'目标',tracking:'任务归属',log:'活动日志',checkin:'早中晚回顾',analysis:'目标分析',scheduled_run:'分析报告',suggestion:'AI 建议',change:'修改提案',proposal:'记录提案',profile:'个人资料'};
interface Item {id:string; kind:string; title:string; updated_at:string; version?:number; record:boolean; matches:any[]; history:any[]}
export function AllHistory({revision, record}:{revision:number;record:(id:string)=>void}) {
  const [refresh,setRefresh]=useState(0);
  const [open,setOpen]=useState(false),[q,setQ]=useState(''),[day,setDay]=useState(''),[kind,setKind]=useState('');
  const [offset,setOffset]=useState(0),[items,setItems]=useState<Item[]>([]),[total,setTotal]=useState(0),[next,setNext]=useState<number|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[selected,setSelected]=useState<Item>();
  useEffect(()=>{
    if(!open)return;
    const controller=new AbortController(); setBusy(true);setError('');setItems([]);
    const timer=setTimeout(()=>{
      const params=new URLSearchParams({q,kind,offset:String(offset),limit:'30'});if(day)params.set('day',day);
      api<{items:Item[];total:number;next_offset:number|null}>('/api/history?'+params,{signal:controller.signal}).then(r=>{if(!controller.signal.aborted){setItems(r.items);setTotal(r.total);setNext(r.next_offset);}}).catch(e=>{if(!controller.signal.aborted)setError(e.message);}).finally(()=>{if(!controller.signal.aborted)setBusy(false);});
    },200);
    return()=>{clearTimeout(timer);controller.abort();};
  },[open,q,day,kind,offset,revision,refresh]);
  return <details className="journal-history panel" onToggle={e=>setOpen(e.currentTarget.open)}><summary>历史查询</summary><button className="text-button" onClick={()=>setRefresh(v=>v+1)}>刷新查询</button>
    <div className="filters"><label>关键词<input aria-label="搜索所有内容" value={q} onChange={e=>{setQ(e.target.value);setOffset(0);}} placeholder="搜索内容与修订…"/></label><label>日期<input type="date" value={day} onChange={e=>{setDay(e.target.value);setOffset(0);}}/></label><label>内容类型<select value={kind} onChange={e=>{setKind(e.target.value);setOffset(0);}}><option value="">全部内容</option>{Object.entries(labels).map(([k,v])=><option value={k} key={k}>{v}</option>)}</select></label><button className="text-button" onClick={()=>{setQ('');setDay('');setKind('');setOffset(0);}}>清除筛选</button></div>
    {error?<p role="alert">{error}</p>:busy?<p role="status">正在查询…</p>:<><p className="quiet">{total} 条结果</p><div className="record-list">{items.map(item=><button className="record-card" key={item.id} onClick={()=>setSelected(item)}><div className="record-copy"><span className="record-meta">{labels[item.kind]||item.kind} · {item.updated_at.slice(0,10)}</span><p>{item.title === item.kind ? labels[item.kind] || item.kind : item.title}</p><span className="quiet">匹配 {item.matches.length} 个版本</span></div></button>)}</div><div className="inline-actions"><button className="secondary" disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-30))}>上一页</button><button className="secondary" disabled={next===null} onClick={()=>setOffset(next!)}>下一页</button></div></>}
    {selected&&<Dialog title="查询结果与历史" close={()=>setSelected(undefined)}><p>{labels[selected.kind]} · {selected.id}</p>{selected.history.slice().reverse().map((v,i)=><details key={i} open={selected.matches.some(m=>m.version===v.version)}><summary>修订 {v.version??1} · {selected.matches.some(m=>m.version===v.version)?'匹配内容':'其他版本'}</summary><DataView data={v.data??v}/></details>)}{selected.record&&<button className="primary" onClick={()=>{record(selected.id);setSelected(undefined);}}>打开记录与更正</button>}</Dialog>}
  </details>;
}
