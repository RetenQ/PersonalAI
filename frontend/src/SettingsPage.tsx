import { usePlugins } from './plugins';
import { useEffect, useState, type ReactNode } from 'react';
import { api, mutate } from './api';
import { Dialog, DataView } from './trackingUI';
import { moduleNames } from './trackingTypes';
import { UserFilesPanel } from './UserFilesPanel';
import { SchedulePanel } from './SchedulePanel';
import { IntegrationPanel } from './IntegrationPanel';
import { ClientPanel } from './ClientPanel';
import { PluginPanel } from './plugins';

type Data = Record<string, any>;
interface SectionValue { data: Data; version: number; origin: string }
interface ConfigResult { sections: Record<string, SectionValue>; modules: string[] }
function Section({ name, title, initial, children, saved }: { name: string; title: string; initial: SectionValue; children: (value: Data, set: (value: Data) => void) => ReactNode; saved?: () => void }) {
  const [current, setCurrent] = useState(initial), [value, set] = useState(initial.data);
  const [review, setReview] = useState<any>(), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  async function reload() { const r = await api<ConfigResult>('/api/config/sections'); setCurrent(r.sections[name]); set(r.sections[name].data); saved?.(); }
  async function run(fn: () => Promise<void>) { if (busy) return; setBusy(true); setError(''); setNotice(''); try { await fn(); } catch(e) { setError((e as Error).message); } finally { setBusy(false); } }
  return <section className="panel module settings-section"><h2>{title}</h2><p className="module-description">独立保存本分区；其他分区未保存的输入会保留。</p>
    <form onSubmit={e => { e.preventDefault(); run(async () => { const r = await mutate<any>('/api/config/sections/' + name, { data: value, expected_version: current.version, reason: '修改' + title }); if (r.change) setReview(r.change); else { await reload(); setNotice('已保存。'); } }); }}>
      <fieldset disabled={busy}>{children(value, set)}<button className="primary">保存{title}</button></fieldset>
    </form>{error && <p role="alert" className="alert error">{error}</p>}{notice && <p role="status" className="alert success">{notice}</p>}
    {review && <Dialog title={'确认' + title + '修改'} busy={busy} close={() => setReview(undefined)}><h3>修改前</h3><DataView data={review.data.sections[name].before}/><h3>修改后</h3><DataView data={review.data.sections[name].after}/><div className="modal-actions">{['reject','accept'].map(decision => <button key={decision} disabled={busy} className={decision === 'accept' ? 'primary' : 'secondary'} onClick={() => run(async () => { await mutate('/api/config/changes/' + review.id + '/decision', { decision }); setReview(undefined); await reload(); setNotice(decision === 'accept' ? '已确认保存。' : '修改已拒绝。'); })}>{decision === 'accept' ? '确认保存' : '拒绝修改'}</button>)}</div>{error && <p role="alert">{error}</p>}</Dialog>}
  </section>;
}

function ModelConnections({ initial, changed }: { initial: SectionValue; changed: () => void }) {
  return <Section name="models" title="模型连接" initial={initial} saved={changed}>{(v,set) => <>
    <p className="modal-hint">各连接独立保存密钥。修改定时分析使用的连接后，需要重新确认分析授权。不会自动切换供应商。</p>
    {v.connections.map((c: Data, index: number) => { const update = (changes: Data) => set({ ...v, connections: v.connections.map((x: Data,i: number) => i === index ? {...x,...changes} : x) }); return <div className="connection-card" key={c.id}>
      <label>连接名称<input required maxLength={100} value={c.name} onChange={e => update({name:e.target.value})}/></label>
      <label className="check-label"><input type="checkbox" checked={c.enabled} onChange={e => update({enabled:e.target.checked})}/>启用模型分析</label>
      <label>服务地址（包含版本路径，例如 /v1）<input type="url" value={c.base_url} placeholder="https://服务商地址/v1" onChange={e => update({base_url:e.target.value})}/></label>
      <label>模型名称<input maxLength={200} value={c.model} onChange={e => update({model:e.target.value})}/></label>
      <label>结构化输出<select value={c.response_format} onChange={e => update({response_format:e.target.value})}><option value="json_schema">严格结构化输出</option><option value="json_object">JSON 模式</option></select></label>
    </div>; })}
    <button type="button" className="secondary" onClick={() => set({...v,connections:[...v.connections,{id:crypto.randomUUID(),name:'新连接',enabled:false,base_url:'',model:'',response_format:'json_schema'}]})}>添加模型连接</button>
    <div className="config-grid">{[['goal','目标分析使用'],['schedule','定时分析使用']].map(([id,label]) => <label key={id}>{label}<select value={v.bindings[id] || ''} onChange={e => set({...v,bindings:{...v.bindings,[id]:e.target.value || null}})}><option value="">不使用模型</option>{v.connections.map((c:Data) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>)}</div>
  </>}</Section>;
}
function ConnectionKeys({ revision, changed }: { revision: number; changed: () => void }) {
  const [connections,setConnections] = useState<Data[]>([]), [selected,setSelected] = useState(''), [key,setKey] = useState('');
  const [statuses,setStatuses] = useState<Data[]>([]), [busy,setBusy] = useState(false), [message,setMessage] = useState(''), [error,setError] = useState('');
  async function load() { const [r,s] = await Promise.all([api<ConfigResult>('/api/config/sections'),api<{connections:Data[]}>('/api/config/connections/status')]); setConnections(r.sections.models.data.connections); setStatuses(s.connections); setSelected(old => r.sections.models.data.connections.some((c:Data) => c.id===old) ? old : r.sections.models.data.connections[0]?.id || ''); }
  useEffect(() => { load().catch(e=>setError(e.message)); },[revision]);
  const conn=connections.find(c=>c.id===selected), state=statuses.find(c=>c.id===selected);
  async function run(fn:()=>Promise<void>) { if(busy)return; setBusy(true);setError('');setMessage('');try{await fn();}catch(e){setError((e as Error).message);}finally{setBusy(false);} }
  return <section className="panel module"><h2>密钥与连接测试</h2><p className="module-description">针对已确认保存的连接操作。密钥仅由当前 Windows 账户保护，不回显，不进入备份。</p>
    <label>选择已保存的连接<select value={selected} onChange={e=>{setSelected(e.target.value);setKey('');setMessage('');}}>{connections.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
    <p>{state?.ready ? '配置就绪 · 仍需实际连接测试' : state?.key_configured ? '已有密钥 · 模型未启用' : '尚未保存匹配的密钥'}</p>{state?.error && <p role="alert">{state.error}</p>}
    <form onSubmit={e=>{e.preventDefault();run(async()=>{await api('/api/config/connections/'+selected+'/key',{method:'POST',body:JSON.stringify({base_url:conn?.base_url,key})});setKey('');await load();setMessage('密钥已保存。'); changed();});}}><label>API 密钥<input type="password" autoComplete="new-password" value={key} required onChange={e=>setKey(e.target.value)}/></label><button className="secondary" disabled={busy || !conn?.base_url}>单独保存密钥</button></form>
    <p className="modal-hint">测试只发送内置示例，可能产生费用；不自动重试。</p><button className="secondary" disabled={busy || !state?.ready} onClick={()=>run(async()=>{const r=await api<{message:string}>('/api/config/connections/test',{method:'POST',body:JSON.stringify({connection_id:selected})});setMessage(r.message);})}>测试模型连接</button>
    {error && <p role="alert" className="alert error">{error}</p>}{message && <p role="status">{message}</p>}
  </section>;
}
function LayoutFields({ value, set }: { value: Data; set: (value: Data) => void }) {
  const adjustable = (value.order as string[]).filter(id => !['profile', 'state', 'year', 'logs', 'checkins', 'pending', 'other'].includes(id));
  return <>{adjustable.map((id, index) => <div className="module-setting" key={id}>
    <label className="check-label"><input type="checkbox" checked={!value.hidden.includes(id)} onChange={e => set({...value, hidden: e.target.checked ? value.hidden.filter((x:string) => x !== id) : [...value.hidden, id]})}/>{moduleNames[id] || id}</label>
    <div>{[-1, 1].map(direction => <button key={direction} type="button" aria-label={(direction < 0 ? '上移' : '下移') + (moduleNames[id] || id)} disabled={index + direction < 0 || index + direction >= adjustable.length} onClick={() => {
      const order = [...value.order], from = order.indexOf(id), to = order.indexOf(adjustable[index + direction]);
      [order[from], order[to]] = [order[to], order[from]];
      set({...value, order});
    }}>{direction < 0 ? '↑' : '↓'}</button>)}</div>
  </div>)}</>;
}
export function SettingsPage({ ready, backup }: { ready: boolean; backup: () => void }) {
  const [result,setResult]=useState<ConfigResult>(), [error,setError]=useState(''), [revision,setRevision]=useState(0), [filesRevision,setFilesRevision]=useState(0);
  const plugins=usePlugins();
  useEffect(()=>{if(ready)api<ConfigResult>('/api/config/sections').then(setResult).catch(e=>setError(e.message));},[ready]);
  if(!result)return <p role={error?'alert':undefined}>{error || '正在读取设置…'}</p>;
  return <div className="settings-page"><nav className="settings-jump" aria-label="设置分区">{[['preferences','界面与功能'],['models','模型连接'],['extensions','插件与接口']].map(([id,label])=><a key={id} href={'#settings-'+id}>{label}</a>)}</nav>
    <div id="settings-preferences"><Section name="ui" title="首页布局" initial={result.sections.ui} saved={()=>setFilesRevision(v=>v+1)}>{(v,set)=><><LayoutFields value={v} set={set}/></>}</Section>
    <Section name="types" title="任务类型" initial={result.sections.types} saved={()=>setFilesRevision(v=>v+1)}>{(v,set)=><>{v.task_types.map((t:Data,i:number)=><div className="type-setting" key={t.id}><label>类型 {i+1}<input required maxLength={80} value={t.name} onChange={e=>set({...v,task_types:v.task_types.map((x:Data)=>x.id===t.id?{...x,name:e.target.value}:x)})}/></label><label className="check-label"><input type="checkbox" checked={t.active} onChange={e=>set({...v,task_types:v.task_types.map((x:Data)=>x.id===t.id?{...x,active:e.target.checked}:x)})}/>启用</label></div>)}<button type="button" className="secondary" onClick={()=>set({...v,task_types:[...v.task_types,{id:crypto.randomUUID(),name:'',active:true}]})}>添加任务类型</button></>}</Section></div>
    <div id="settings-models"><ModelConnections initial={result.sections.models} changed={()=>{setRevision(v=>v+1);setFilesRevision(v=>v+1);}}/><ConnectionKeys revision={revision} changed={()=>setRevision(v=>v+1)}/>{plugins.active('analysis') && <SchedulePanel modelRevision={revision}/>}</div>
    <div id="settings-extensions"><PluginPanel/><IntegrationPanel/><ClientPanel/></div>
    <section className="panel module"><h2>数据与使用帮助</h2><p>资料在网页维护，Markdown 文件自动整理。服务配置修改后需手动重启；不提供公网开关。</p><button className="secondary" onClick={backup}>备份与恢复校验</button></section><UserFilesPanel revision={filesRevision}/>
  </div>;
}
