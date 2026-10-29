import { useEffect, useState } from 'react';
import type { CSSProperties } from 'react';
import { api } from './api';
import { taskStatuses, tasksForDay, currentTasks } from './taskPresentation';
import type { DashboardData, Task } from './trackingTypes';

const colors = ['#356bb0', '#287e6b', '#a66728', '#986477'];
const statuses = taskStatuses;

export function SummaryPage({ready,day,revision,record}:{ready:boolean;day:string;revision:number;record:(id:string)=>void}) {
  const [data,setData]=useState<DashboardData>(),[error,setError]=useState(''),[retry,setRetry]=useState(0);
  useEffect(()=>{
    if(!ready||!day)return;
    const controller=new AbortController();setError('');setData(undefined);
    api<DashboardData>('/api/dashboard?verify_user_files=false&day='+day,{signal:controller.signal})
      .then(value=>{if(!controller.signal.aborted)setData(value);})
      .catch(e=>{if(!controller.signal.aborted)setError(e.message);});
    return()=>controller.abort();
  },[ready,day,revision,retry]);
  if(error)return <div role="alert" className="alert error">{error}<button className="secondary" onClick={()=>setRetry(v=>v+1)}>重试</button></div>;
  if(!data)return <p role="status">正在读取…</p>;
  const colorMap=Object.fromEntries([...data.goals].sort((a,b)=>a.created_at.localeCompare(b.created_at)||a.id.localeCompare(b.id)).map((g,i)=>[g.id,colors[i%colors.length]]));
  const tasks=tasksForDay(data.tasks,day);
  const row=(task:Task)=> <button className={'summary-task '+(task.record.status==='done'?'is-done':'')} key={task.task_id} onClick={()=>record(task.task_id)}>
    <span className="summary-task-mark" aria-hidden="true" style={{background:task.goal_id?colorMap[task.goal_id]??'#777d87':'#777d87'}}/>
    <span className="summary-task-text">{task.record.text}</span><span className="summary-task-status">{statuses[task.record.status]}</span>
  </button>;
  const unlinked=currentTasks(data.tasks,null);
  return <div className="summary-page">
    <section className="summary-today" aria-label="今日任务"><header><h2>今日任务</h2><time dateTime={day}>{day.replaceAll('-',' / ')}</time></header>
      {tasks.length?<div>{tasks.map(row)}</div>:<p className="summary-empty">暂无任务</p>}
    </section>
    <section className="summary-goals" aria-label="目标与任务"><h2>目标与任务</h2>
      <div className="summary-goal-grid">{data.goals.map(goal=>{
        const current=currentTasks(data.tasks,goal.id);
        const progress=goal.progress;
        return <article className="summary-goal" key={goal.id} style={{'--goal-color':colorMap[goal.id]} as CSSProperties}>
          <header><h3>{goal.data.title}</h3><strong>{progress==null?'未计算':`${Number(progress.toFixed(1))}%`}</strong></header>
          <div className={'summary-progress'+(progress==null?' is-unknown':'')} role="progressbar" aria-label={goal.data.title+'：目标进度'} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress??undefined} aria-valuetext={progress==null?'未知':`${progress}%`}><span style={{width:Math.max(0,Math.min(100,progress??0))+'%'}}/></div>
          <div className="summary-goal-tasks">{current.length?current.map(row):<p className="summary-empty">暂无未完成任务</p>}</div>
        </article>;
      })}</div>
      {!data.goals.length&&<p className="summary-empty">暂无目标</p>}
      {!!unlinked.length&&<div className="summary-unlinked"><h3>未关联目标的任务</h3>{unlinked.map(row)}</div>}
    </section>
  </div>;
}
