import { useEffect, useState } from 'react';
import { api, mutate } from './api';
import { Dialog } from './trackingUI';

const scopes = { records: '日常原文', goals: '目标及完成标准', tasks: '任务及追踪', logs: '活动日志', checkins: '早中晚回应' };
type Scope = keyof typeof scopes;
interface Options { enabled: boolean; times: string[]; scopes: Scope[] }
interface Status { config: Options; version: number; authorized: boolean; model_ready: boolean; active: boolean; leader: boolean; next_at: string | null; error: string; notice: string }
interface Preview { approval_token: string; before: Options; after: Options; input: unknown; model: { base_url: string; model: string }; notice: string }

export function SchedulePanel({ modelRevision }: { modelRevision: number }) {
  const [status, setStatus] = useState<Status>();
  const [form, setForm] = useState<Options>();
  const [preview, setPreview] = useState<Preview>();
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  async function load(preserveDraft = false) {
    const result = await api<Status>('/api/schedule');
    setStatus(result);
    const next = { enabled: result.config.enabled, times: result.config.times, scopes: result.config.scopes };
    setForm(old => preserveDraft && old ? old : next);
  }
  useEffect(() => { setPreview(undefined); load(true).catch(e => setError(e.message)); }, [modelRevision]);
  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const describe = (o: Options) => `${o.enabled ? '启用' : '关闭'}；时刻：${o.times.join('、') || '未设置'}；资料：${o.scopes.map(s => scopes[s]).join('、') || '未选择'}`;
  return <section className="panel module schedule-panel" aria-label="定时分析与建议">
    <h2>定时分析与建议</h2>
    <p className="module-description">当天为主，近七个自然日（含今天）作背景。可设置多个生成时刻；提醒发送交给你的其他应用。</p>
    {error && <p role="alert" className="alert error">{error}</p>}
    {notice && <p role="status" className="alert success">{notice}</p>}
    {status && form && <>
      <p className="tag">{status.active ? '已授权自动分析' : status.config.enabled ? '待重新授权或配置模型' : '定时分析已关闭'}</p>
      <p className="module-description">下一计划时刻：{status.next_at || '尚未启用'}（Asia/Shanghai）。这是开始生成的时间，结果需等待模型返回。</p>
      {status.error && <p className="alert error">{status.error}</p>}
      {!status.model_ready && <p className="modal-hint">请先保存并启用模型配置与匹配密钥。现在可保存关闭状态的时间和范围设置。</p>}
      <form onSubmit={e => { e.preventDefault(); run(async () => setPreview(await api<Preview>('/api/schedule/preview', { method: 'POST', body: JSON.stringify({ data: form, expected_version: status.version }) }))); }}>
        <label className="check-label"><input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })}/>请求启用定时分析</label>
        <div className="schedule-times">{form.times.map((value, index) => <div className="inline-actions" key={index}><label>生成时刻 {index + 1}<input type="time" required value={value} onChange={e => setForm({ ...form, times: form.times.map((t, i) => i === index ? e.target.value : t) })}/></label><button type="button" className="text-button" aria-label={`移除生成时刻 ${index + 1}`} onClick={() => setForm({ ...form, times: form.times.filter((_, i) => i !== index) })}>移除</button></div>)}</div>
        <button type="button" className="secondary" disabled={form.times.length >= 24} onClick={() => setForm({ ...form, times: [...form.times, ''] })}>添加生成时刻</button>
        <fieldset className="schedule-scopes"><legend>允许自动发送的资料类型</legend>{Object.entries(scopes).map(([key, label]) => <label className="check-label" key={key}><input type="checkbox" checked={form.scopes.includes(key as Scope)} onChange={e => setForm({ ...form, scopes: e.target.checked ? [...form.scopes, key as Scope] : form.scopes.filter(s => s !== key) })}/>{label}</label>)}</fieldset>
        <p className="modal-hint">只发送勾选类型；任务以当前计划为背景，不当作已发生事实。不读取私人访谈、个性档案、想法库、未确认提案或模型密钥。</p>
        <button className="primary" disabled={busy}>预览定时设置与数据范围</button>
      </form>
      <div className="inline-actions schedule-actions"><button className="secondary" disabled={busy || !status.config.enabled} onClick={() => run(async () => { await mutate('/api/schedule/pause', {}); setPreview(undefined); await load(); setNotice('已暂停后续自动调用；已经发送的请求可能仍会完成。'); })}>暂停定时分析</button><button className="secondary" disabled={busy || !status.active} onClick={() => run(async () => { await mutate('/api/schedule/run', {}); setNotice('本次处理已结束，请在“每日回顾 → AI 定时分析”查看结果或失败原因。'); await load(); })}>{busy ? '正在处理…' : '按已授权范围立即生成'}</button></div>
      <p className="module-description">{status.notice} 启动后仅补最近一次错过的时刻；补跑以实际执行日为当天。模型更换或备份恢复后须重新预览授权。失败不自动重试。</p>
    </>}
    {preview && <Dialog title="确认自动分析范围" busy={busy} close={() => setPreview(undefined)}>
      <div className="diff-grid"><div><h4>修改前</h4><p>{describe(preview.before)}</p></div><div><h4>修改后</h4><p>{describe(preview.after)}</p></div></div>
      <p className="modal-hint">{preview.notice}</p><p className="path-text">模型：{preview.model.model || '未配置'} · {preview.model.base_url || '未配置地址'}</p>
      <details><summary>查看当前会发送的完整样本（仅预览，尚未调用）</summary><pre className="schedule-preview">{JSON.stringify(preview.input, null, 2)}</pre></details>
      <div className="modal-actions"><button className="secondary" disabled={busy} onClick={() => setPreview(undefined)}>取消</button><button className="primary" disabled={busy || (preview.after.enabled && !status?.model_ready)} onClick={() => run(async () => { await mutate('/api/schedule/confirm', { approval_token: preview.approval_token, approved: true }); setPreview(undefined); await load(); setNotice(preview.after.enabled ? '已确认自动分析范围与时刻。' : '设置已保存，定时分析保持关闭。'); })}>确认范围并保存</button></div>
      {error && <p role="alert" className="alert error">{error}</p>}
    </Dialog>}
  </section>;
}
