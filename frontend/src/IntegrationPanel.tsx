import { useEffect, useState } from 'react';
import { api } from './api';
const names: Record<string,string>={goals:'目标',tasks:'任务',logs:'活动日志',checkins:'早中晚回顾',reports:'AI 报告'};
interface Access { enabled:boolean; scopes:string[]; tokens:{id:string;name:string;scopes:string[]}[] }
export function IntegrationPanel(){
 const [state,setState]=useState<Access>(),[name,setName]=useState(''),[scopes,setScopes]=useState<string[]>([]),[token,setToken]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function load(){setState(await api('/api/integration-settings'));}
 useEffect(()=>{load().catch(e=>setError(e.message));},[]);
 async function run(fn:()=>Promise<void>){if(busy)return;setBusy(true);setError('');try{await fn();await load();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <section className="panel module"><h2>外部只读接口</h2><p className="module-description">仅限本机。按资料类型授权，不能修改任务或触发 AI。授权文件不进入备份，恢复后默认关闭。</p>{error&&<p role="alert">{error}</p>}{state&&<>
 <label className="check-label"><input type="checkbox" checked={state.enabled} disabled={busy} onChange={e=>{const enabled=e.target.checked;const previous=state;setState({...state,enabled});run(async()=>{try{await api('/api/integration-settings',{method:'POST',body:JSON.stringify({enabled})});}catch(error){setState(previous);throw error;}});}}/>启用外部只读接口</label>
 <form onSubmit={e=>{e.preventDefault();run(async()=>{const r=await api<{token:string}>('/api/integration-settings/tokens',{method:'POST',body:JSON.stringify({name,scopes})});setToken(r.token);setName('');setScopes([]);});}}><label>调用方名称<input required maxLength={80} value={name} onChange={e=>setName(e.target.value)}/></label><div className="scope-grid">{state.scopes.map(s=><label key={s} className="check-label"><input type="checkbox" checked={scopes.includes(s)} onChange={e=>setScopes(e.target.checked?[...scopes,s]:scopes.filter(x=>x!==s))}/>{names[s]}</label>)}</div><button className="secondary" disabled={busy||!scopes.length}>创建只读令牌</button></form>
 {token&&<div className="alert success"><p>令牌仅本次显示，请保存在调用程序的私有配置中。</p><code className="path-text">{token}</code><button className="text-button" onClick={()=>setToken('')}>隐藏令牌</button></div>}
 {state.tokens.map(t=><div className="access-token" key={t.id}><div><strong>{t.name}</strong><small>{t.scopes.map(s=>names[s]).join('、')}</small></div><button disabled={busy} className="secondary" onClick={()=>run(async()=>{await api('/api/integration-settings/tokens/'+t.id+'/revoke',{method:'POST'});setToken('');})}>撤销</button></div>)}
 <details><summary>读取接口说明</summary><p>使用 Authorization: Bearer 请求头；接口前缀 /api/integrations/v1/，资料名为 goals、tasks、logs、checkins、reports。支持 day、goal_id、task_id、limit 和 offset；回顾按目标筛选。完整说明见 docs/INTEGRATIONS_V1.md。</p></details></>}</section>;
}
