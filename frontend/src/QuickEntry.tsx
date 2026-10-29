import { useEffect, useState } from 'react';
import { mutate } from './api';
import type { Task } from './trackingTypes';
export function QuickEntry({ today, tasks, saved, selectedTask }: { today:string;tasks:Task[];saved:()=>Promise<void>;selectedTask?:string }){
 const [text,setText]=useState(''),[task,setTask]=useState(selectedTask||''),[day,setDay]=useState(today),[result,setResult]=useState(''),[obstacle,setObstacle]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 useEffect(()=>{if(selectedTask){setTask(selectedTask);document.getElementById('quick-text')?.focus();}},[selectedTask]);
 return <section className="panel quick-entry"><div><h2>快捷记录</h2></div><form onSubmit={async e=>{e.preventDefault();if(busy)return;setBusy(true);setError('');setNotice('');try{await mutate('/api/quick-record',{text,date:day,task_id:null,result:'',obstacle:''});setText('');setResult('');setObstacle('');setNotice('已保存到本机。');try{await saved();}catch{setNotice('已保存；总览刷新失败，请稍后刷新。');}}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}><label className="visually-hidden" htmlFor="quick-text">快捷记录内容</label><textarea id="quick-text" required maxLength={10000} placeholder="做了什么，或有什么需要记住？" value={text} onChange={e=>setText(e.target.value)}/><button className="primary" disabled={busy||!text.trim()}>{busy?'正在保存…':'保存这条记录'}</button></form>{error&&<p role="alert" className="alert error">{error}</p>}{notice&&<p role="status" className="alert success">{notice}</p>}</section>;
}
