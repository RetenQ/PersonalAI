import { useEffect, useState } from 'react';
import { api, mutate } from './api';
import type { Activity, DashboardData, Entity, ModelConfig } from './trackingTypes';
import { DataView } from './trackingUI';

interface Preview { input: { sources: Record<string, number>; goal: unknown; tasks: unknown[]; tracking: unknown[]; logs: unknown[] }; settings_version: number; model: ModelConfig; ready: boolean }
export function AnalysisPanel({ goalId, data, done, onBusy }: { goalId: string; data: DashboardData; done: () => void; onBusy: (busy: boolean) => void }) {
  const [logs, setLogs] = useState<Entity<Activity>[]>([]);
  const [taskIds, setTaskIds] = useState<string[]>([]);
  const [logIds, setLogIds] = useState<string[]>([]);
  const [preview, setPreview] = useState<Preview>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { api<{ entities: Entity<Activity>[] }>('/api/activity-logs').then(r => setLogs(r.entities.filter(l => l.data.goal_id === goalId))).catch(e => setError(e.message)); }, [goalId]);
  const selection = { goal_id: goalId, task_ids: taskIds, log_ids: logIds };
  async function run(action: () => Promise<void>) { if (busy) return; setBusy(true); onBusy(true); setError(''); try { await action(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); onBusy(false); } }
  return <><p className="modal-hint">默认不选任何任务或日志。只将此目标与勾选的资料发送到配置的服务，未选中的个人资料不会发送。</p><fieldset disabled={busy}><legend>选择任务</legend>{data.tasks.filter(t => t.goal_id === goalId).map(t => <label className="check-label" key={t.task_id}><input type="checkbox" checked={taskIds.includes(t.task_id)} onChange={e => { setTaskIds(e.target.checked ? [...taskIds, t.task_id] : taskIds.filter(id => id !== t.task_id)); setPreview(undefined); }}/>{t.record.text}</label>)}</fieldset><fieldset disabled={busy}><legend>选择活动日志（所有日期）</legend>{logs.map(l => <label className="check-label" key={l.id}><input type="checkbox" checked={logIds.includes(l.id)} onChange={e => { setLogIds(e.target.checked ? [...logIds, l.id] : logIds.filter(id => id !== l.id)); setPreview(undefined); }}/>{l.data.date} · {l.data.text}</label>)}{!logs.length && <p className="modal-hint">尚无目标日志；证据不足时不会估计百分比。</p>}</fieldset>
    <button className="secondary" disabled={busy} onClick={() => run(async () => setPreview(await api<Preview>('/api/analyses/preview', { method: 'POST', body: JSON.stringify(selection) })))}>预览将发送的资料</button>
    {preview && <div className="analysis-preview"><h3>发送前确认</h3><p className="modal-hint">服务：{preview.model.base_url || '未配置'}<br/>模型：{preview.model.model || '未配置'}<br/>一次分析可能产生服务商费用。不会自动重试。</p><details open><summary>目标、任务、日志及来源版本</summary><DataView data={preview.input}/></details>{!preview.ready && <p className="alert error">请先在设置中保存模型配置与密钥。</p>}<button disabled={busy || !preview.ready} className="primary" onClick={() => run(async () => { await mutate('/api/analyses', { ...selection, sources: preview.input.sources, settings_version: preview.settings_version, approved: true }); done(); })}>{busy ? '正在分析，请等待…' : '确认发送并分析'}</button></div>}{error && <p role="alert" className="alert error">{error}</p>}
  </>;
}
