import { useRef, useState } from 'react';
import { api } from './api';
import type { DashboardData } from './trackingTypes';
import { slots } from './trackingTypes';
import { download } from './trackingUI';

export function ExportPanel({ data }: { data: DashboardData }) {
  const [day, setDay] = useState(data.date), [goal, setGoal] = useState(''), [slot, setSlot] = useState(''), [format, setFormat] = useState('markdown');
  const [result, setResult] = useState<{ filename: string; content: string }>();
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const revision = useRef(0);
  const reset = () => { revision.current++; setResult(undefined); setError(''); };
  return <><p className="modal-hint">目标和任务导出当前快照；日期与时段筛选日志和回应。包含选中范围的 AI 分析及来源，不含展示资料、私人档案和密钥。</p><form onSubmit={async e => { e.preventDefault(); reset(); const requestedRevision = revision.current; setBusy(true); try { const value = await api<{ filename: string; content: string }>('/api/exports?' + new URLSearchParams({ day, format, ...(goal ? { goal_id: goal } : {}), ...(slot ? { slot } : {}) })); if (requestedRevision === revision.current) setResult(value); } catch (e) { if (requestedRevision === revision.current) setError((e as Error).message); } finally { setBusy(false); } }}><div className="form-row"><label>日期<input type="date" required value={day} onChange={e => { setDay(e.target.value); reset(); }}/></label><label>回顾时段<select value={slot} onChange={e => { setSlot(e.target.value); reset(); }}><option value="">全天</option>{Object.entries(slots).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label></div><label>目标<select value={goal} onChange={e => { setGoal(e.target.value); reset(); }}><option value="">全部目标及未关联事项</option>{data.goals.map(g => <option key={g.id} value={g.id}>{g.data.title}</option>)}</select></label><label>格式<select value={format} onChange={e => { setFormat(e.target.value); reset(); }}><option value="markdown">Markdown · 便于阅读</option><option value="json">JSON · 便于其他应用读取</option></select></label><button className="secondary" disabled={busy}>生成导出预览</button></form>{error && <p role="alert" className="alert error">{error}</p>}{result && <><pre className="export-preview">{result.content}</pre><button className="primary" onClick={() => download(result.filename, result.content)}>下载文件</button></>}</>;
}
