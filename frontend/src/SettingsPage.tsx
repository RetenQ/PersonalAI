import { useEffect, useState } from 'react';
import { api, mutate } from './api';
import type { Change, Entity, Settings } from './trackingTypes';
import { moduleNames } from './trackingTypes';
import { ChangeReview, Dialog } from './trackingUI';
import { ProfilePanel } from './ProfilePanel';
import { UserFilesPanel } from './UserFilesPanel';
import { SchedulePanel } from './SchedulePanel';

interface Result { settings: Settings; version: number; key_configured: boolean; key_error: string; model_ready: boolean; data_directory: string }
export function SettingsPage({ ready, backup }: { ready: boolean; backup: () => void }) {
  const [original, setOriginal] = useState<Result>();
  const [s, set] = useState<Settings>();
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [review, setReview] = useState<Entity<Change>>();
  const [filesRevision, setFilesRevision] = useState(0);
  async function load() { const r = await api<Result>('/api/settings'); setOriginal(r); set(r.settings); setFilesRevision(v => v + 1); }
  useEffect(() => { if (ready) load().catch(e => setError(e.message)); }, [ready]);
  async function run(action: () => Promise<void>) { if (busy) return; setBusy(true); setError(''); setMessage(''); try { await action(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
  if (!s || !original) return <p role={error ? 'alert' : undefined}>{error || '正在读取设置…'}</p>;
  const settings = s;
  return <div className="settings-page">{error && <p role="alert" className="alert error">{error}</p>}{message && <p role="status" className="alert success">{message}</p>}<form onSubmit={e => { e.preventDefault(); run(async () => { const result = await mutate<{ change?: Entity<Change> }>('/api/settings', { data: settings, expected_version: original.version, reason: '更新展示资料与应用设置' }); if (result.change) setReview(result.change); else { await load(); setMessage('设置已保存。'); } }); }}>
    <section className="panel module"><h2>个人展示资料</h2><p className="module-description">只展示你在这里填写的内容。不会自动导入私人访谈档案。</p><label>展示名称<input maxLength={100} value={s.name} onChange={e => set({ ...s, name: e.target.value })}/></label><label>个人简介<textarea maxLength={3000} value={s.bio} onChange={e => set({ ...s, bio: e.target.value })}/></label><label>近期关注<textarea maxLength={3000} value={s.focus} onChange={e => set({ ...s, focus: e.target.value })}/></label></section>
    <section className="panel module"><h2>首页模块</h2><p className="module-description">调整顺序或隐藏模块，已有数据仍保留。</p>{s.order.map((id, index) => <div className="module-setting" key={id}><label className="check-label"><input type="checkbox" checked={!s.hidden.includes(id)} onChange={e => set({ ...s, hidden: e.target.checked ? s.hidden.filter(k => k !== id) : [...s.hidden, id] })}/>{moduleNames[id]}</label><div><button type="button" aria-label={`上移${moduleNames[id]}`} disabled={!index} onClick={() => { const order = [...s.order]; [order[index - 1], order[index]] = [order[index], order[index - 1]]; set({ ...s, order }); }}>↑</button><button type="button" aria-label={`下移${moduleNames[id]}`} disabled={index === s.order.length - 1} onClick={() => { const order = [...s.order]; [order[index + 1], order[index]] = [order[index], order[index + 1]]; set({ ...s, order }); }}>↓</button></div></div>)}</section>
    <section className="panel module"><h2>任务类型</h2><p className="module-description">一个任务可以有多种类型；停用类型不会改变历史。</p>{s.task_types.map((t, index) => <div className="type-setting" key={t.id}><label>类型 {index + 1}<input required maxLength={80} value={t.name} onChange={e => set({ ...s, task_types: s.task_types.map(x => x.id === t.id ? { ...x, name: e.target.value } : x) })}/></label><label className="check-label"><input type="checkbox" checked={t.active} onChange={e => set({ ...s, task_types: s.task_types.map(x => x.id === t.id ? { ...x, active: e.target.checked } : x) })}/>启用</label></div>)}<button type="button" className="secondary" onClick={() => set({ ...s, task_types: [...s.task_types, { id: crypto.randomUUID(), name: '', active: true }] })}>添加任务类型</button></section>
    <section className="panel module"><h2>模型服务</h2><p className="module-description">目标分析逐次预览确认；定时分析需在下方单独授权。仅保存模型配置不会启用定时分析。</p><label className="check-label"><input type="checkbox" checked={s.model.enabled} onChange={e => set({ ...s, model: { ...s.model, enabled: e.target.checked } })}/>启用模型分析</label><label>服务地址（包含版本路径，例如 /v1）<input type="url" placeholder="https://服务商地址/v1" value={s.model.base_url} onChange={e => set({ ...s, model: { ...s.model, base_url: e.target.value } })}/></label><label>模型名称<input maxLength={200} value={s.model.model} onChange={e => set({ ...s, model: { ...s.model, model: e.target.value } })}/></label><label>结构化输出<select value={s.model.response_format} onChange={e => set({ ...s, model: { ...s.model, response_format: e.target.value as Settings['model']['response_format'] } })}><option value="json_schema">严格结构化输出（优先）</option><option value="json_object">JSON 模式（服务商不支持严格模式时）</option></select></label><p className="modal-hint">采用 Chat Completions 协议。不同供应商需要分别测试兼容性。</p></section>
    <div className="settings-save"><button className="primary" disabled={busy}>保存／预览设置修改</button></div></form>
    <section className="panel module"><h2>密钥与连接测试</h2>{original.key_error && <p className="alert error">{original.key_error}</p>}<p className="module-description">先保存服务地址。密钥绑定已保存的地址，由当前 Windows 账户保护；备份不包含密钥。</p><p className="tag">{original.model_ready ? '配置就绪 · 仍需实际连接测试' : original.key_configured ? '已有密钥 · 模型未启用' : '尚未保存匹配的密钥'}</p><form onSubmit={e => { e.preventDefault(); run(async () => { await api('/api/settings/key', { method: 'POST', body: JSON.stringify({ base_url: original.settings.model.base_url, key }) }); setKey(''); await load(); setMessage('密钥已安全保存，不会回显。'); }); }}><label>API 密钥<input type="password" required autoComplete="new-password" value={key} onChange={e => setKey(e.target.value)}/></label><button className="secondary" disabled={busy || !original.settings.model.base_url}>单独保存密钥</button></form><p className="modal-hint">连接测试只发送内置示例数据，可能产生一次模型调用费用，不自动重试。</p><button className="secondary" disabled={busy || !original.model_ready} onClick={() => run(async () => { const r = await api<{ message: string }>('/api/settings/test', { method: 'POST' }); setMessage(r.message); })}>测试模型连接</button></section>
    <section className="panel module"><h2>数据与使用帮助</h2><p className="module-description">数据目录：<span className="path-text">{original.data_directory}</span></p><button className="secondary" onClick={backup}>备份与恢复校验</button><details className="help"><summary>使用方法与边界</summary><ol><li>先建立目标，填写完成标准和计算方式。</li><li>在“对话记录”明确创建任务，再到总览调整关联目标和追踪进度。</li><li>收到外部应用提醒后，回到总览填写早中晚回应和活动日志。</li><li>正式修改先预览再确认；AI 结果独立展示，不自动改计划。</li><li>通过“导出回顾”下载 Markdown 或 JSON，交给其他应用使用。</li></ol><p>时间按 Asia/Shanghai 解释。当前仅本机访问，无自动推送和同步。完整安装、备份恢复及接口说明见项目 README.md。</p></details></section>
    {review && <Dialog title="确认设置修改" busy={busy} close={() => setReview(undefined)}><ChangeReview change={review} names={moduleNames} busy={busy} decide={decision => run(async () => { await mutate(`/api/changes/${review.id}/decision`, { decision }); setReview(undefined); await load(); setMessage(decision === 'accept' ? '设置已更新。' : '已拒绝修改。'); })}/>{error && <p className="alert error" role="alert">{error}</p>}</Dialog>}
    <SchedulePanel modelRevision={original.version}/>
    <ProfilePanel changed={() => setFilesRevision(v => v + 1)}/>
    <UserFilesPanel revision={filesRevision}/>
  </div>;
}
