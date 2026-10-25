import { Component, createContext, useContext, useEffect, useState, type ComponentType, type ReactNode } from 'react';
import { api, mutate } from './api';
import { Dialog, DataView } from './trackingUI';
export interface PluginStatus { id:string; name:string; status:string; reason:string; modules:string[]; pages:string[]; settings_schema?:object }
const defaults=['tracking','journal','analysis','dashboard','exchange'].map(id=>({id,name:id,status:'active',reason:'',modules:[],pages:[]}));
const Context=createContext<PluginStatus[]>(defaults);
export function PluginProvider({children}:{children:ReactNode}){const [items,setItems]=useState<PluginStatus[]>(defaults);useEffect(()=>{api<{plugins:PluginStatus[]}>('/api/plugins').then(r=>setItems(r.plugins)).catch(()=>setItems([]));},[]);return <Context.Provider value={items}>{children}</Context.Provider>;}
export function usePlugins(){const items=useContext(Context);return {items,active:(id:string)=>items.some(p=>p.id===id&&p.status==='active')};}
export class PluginBoundary extends Component<{children:ReactNode}, {failed:boolean}> {
 state={failed:false};
 static getDerivedStateFromError(){return {failed:true};}
 render(){return this.state.failed?<p role="alert" className="alert error">此插件页面发生错误。资料仍保留，可从导航继续使用其他功能。</p>:this.props.children;}
}
export interface FrontendPlugin {id:string; pages:{id:string;label:string;component:ComponentType}[]; modules:Record<string,ComponentType>}
// Explicit build-time registration. Plugin page code is bundled, never downloaded at runtime.
export const frontendPlugins:FrontendPlugin[]=[{id:'example',pages:[{id:'example',label:'扩展示例',component:ExamplePage}],modules:{example:ExampleModule}}];
export function ExampleModule(){return <><h2>扩展示例</h2><p>此卡片由插件注册。可从扩展示例页面管理记录。</p></>;}
export function ExamplePage(){
 const [text,setText]=useState(''),[items,setItems]=useState<any[]>([]),[editing,setEditing]=useState<any>(),[review,setReview]=useState<any>(),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 async function load(){setItems((await api<{entities:any[]}>('/api/plugin-data?plugin=example')).entities.filter(e=>e.kind==='example/entry'));}
 useEffect(()=>{load().catch(e=>setError(e.message));},[]);
 async function run(fn:()=>Promise<void>){if(busy)return;setBusy(true);setError('');try{await fn();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <section className="panel module"><h2>扩展示例</h2><p>这是默认关闭的插件开发示例，保存内容仍写入本机事件与 Markdown。</p><form onSubmit={e=>{e.preventDefault();run(async()=>{const r=await mutate<any>('/api/plugin-data/example/entry'+(editing?'/'+editing.id:''),{data:{text},expected_version:editing?.version||0});if(r.change)setReview(r.change);else{setText('');setEditing(undefined);await load();}});}}><label>示例内容<textarea required value={text} onChange={e=>setText(e.target.value)}/></label><button disabled={busy} className="primary">{editing?'预览修改':'保存示例记录'}</button></form>{items.map(e=><article key={e.id}><p>{e.data.text}</p><button className="text-button" onClick={()=>{setEditing(e);setText(e.data.text);}}>更正</button></article>)}{error&&<p role="alert">{error}</p>}
 {review&&<Dialog title="确认插件修改" busy={busy} close={()=>setReview(undefined)}><h3>修改前</h3><DataView data={review.data.before}/><h3>修改后</h3><DataView data={review.data.after}/>{['reject','accept'].map(decision=><button key={decision} onClick={()=>run(async()=>{await mutate('/api/plugin-changes/'+review.id+'/decision',{decision});setReview(undefined);setEditing(undefined);setText('');await load();})}>{decision==='accept'?'确认保存':'拒绝'}</button>)}</Dialog>}</section>;
}
function PluginSettings({plugin}:{plugin:PluginStatus}){
 const [value,setValue]=useState('{}'),[version,setVersion]=useState(0),[error,setError]=useState(''),[review,setReview]=useState<any>();
 useEffect(()=>{api<{entities:any[]}>('/api/plugin-data?plugin='+plugin.id).then(r=>{const e=r.entities.find(e=>e.kind===plugin.id+'/settings');if(e){setValue(JSON.stringify(e.data,null,2));setVersion(e.version);}}).catch(e=>setError(e.message));},[plugin.id]);
 return <details><summary>{plugin.name}设置</summary><p>开发者设置，填写符合下方结构的 JSON；首次保存采用协议默认值。</p><pre>{JSON.stringify(plugin.settings_schema,null,2)}</pre><form onSubmit={async e=>{e.preventDefault();setError('');try{const r=await mutate<any>('/api/plugin-data/'+plugin.id+'/settings',{data:JSON.parse(value),expected_version:version});if(r.change)setReview(r.change);else{setVersion(r.entity.version);setValue(JSON.stringify(r.entity.data,null,2));}}catch(e){setError((e as Error).message);}}}><textarea aria-label={plugin.name+'设置 JSON'} value={value} onChange={e=>setValue(e.target.value)}/><button className="secondary">保存插件设置</button></form>{review&&<><h4>修改前</h4><DataView data={review.data.before}/><h4>修改后</h4><DataView data={review.data.after}/>{['accept','reject'].map(decision=><button key={decision} onClick={async()=>{try{const r=await mutate<any>('/api/plugin-changes/'+review.id+'/decision',{decision});const e=r.entities.find((x:any)=>x.kind===plugin.id+'/settings');if(e)setVersion(e.version);setReview(undefined);}catch(e){setError((e as Error).message);}}}>{decision==='accept'?'确认插件设置':'拒绝修改'}</button>)}</>}{error&&<p role="alert">{error}</p>}</details>;
}
export function PluginPanel(){
 const [items,setItems]=useState<PluginStatus[]>([]),[runtime,setRuntime]=useState<any>(),[error,setError]=useState(''),[unknown,setUnknown]=useState<any[]>([]),[changes,setChanges]=useState<any[]>([]);
 async function load(){const [p,r,d,c]=await Promise.all([api<{plugins:PluginStatus[]}>('/api/plugins'),api('/api/runtime'),api<{entities:any[]}>('/api/plugin-data'),api<{changes:any[]}>('/api/config/changes')]);setItems(p.plugins);setRuntime(r);setUnknown(d.entities.filter(e=>!p.plugins.some(p=>p.id===e.kind.split('/')[0]&&p.status==='active')));setChanges(c.changes);}
 useEffect(()=>{load().catch(e=>setError(e.message));},[]);
 return <section className="panel module"><h2>插件与服务配置</h2><p className="module-description">代码插件重启生效；页面代码修改后重新构建。停用保留数据，依赖不足会阻止相关功能运行。</p>{error&&<p role="alert">{error}</p>}{items.map(p=><div className="plugin-card" key={p.id}><strong>{p.name}</strong><span className="tag">{({active:'已启用',disabled:'已停用',blocked:'依赖或版本不满足',failed:'启动失败',unavailable:'未安装'} as Record<string,string>)[p.status]}</span>{p.reason&&<p>{p.reason}</p>}{p.status==='active'&&p.settings_schema&&<PluginSettings plugin={p}/>}</div>)}
 {runtime&&<details><summary>当前服务配置</summary><p>监听：{runtime.host}:{runtime.port}</p><p className="path-text">数据：{runtime.data_dir}</p><p className="path-text">配置文件：{runtime.config_file || '使用启动参数与默认值'}</p><p>{runtime.precedence}。修改端口、目录或插件后，手动停止并重新启动服务。</p></details>}
 {unknown.length>0&&<details><summary>未启用插件的历史资料（只读）</summary>{unknown.map(e=><article key={e.id}><h4>{e.kind} · v{e.version}</h4><DataView data={e.data}/></article>)}</details>}
 {changes.length>0&&<details><summary>尚未处理的设置与插件修改（{changes.length}）</summary>{changes.map(c=><article key={c.id}><DataView data={c.data}/>{['accept','reject'].map(decision=><button key={decision} onClick={async()=>{try{await mutate((c.kind==='core/config-change'?'/api/config/changes/':'/api/plugin-changes/')+c.id+'/decision',{decision});await load();}catch(e){setError((e as Error).message);}}}>{decision==='accept'?'确认保存':'拒绝修改'}</button>)}</article>)}</details>}</section>;
}
