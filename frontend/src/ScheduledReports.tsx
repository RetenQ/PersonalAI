import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';
import { DataView, Dialog } from './trackingUI';

const sections = { facts: '记录中的事实', reflection: '进展分析', issues: '问题与阻碍', suggestions: '改善建议', next_steps: '下一步参考', long_term: '与长期目标的关系' };
const statuses: Record<string, string> = { running: '生成中', succeeded: '已生成', failed: '处理失败', skipped: '资料不足 · 未调用', interrupted: '运行中断' };
interface Cited { text: string; source_ids: string[] }
export interface Report { run: { id: string; data: { status: string; message: string; scheduled_at: string; started_at: string; finished_at: string | null; model: string; window_start: string; window_end: string; sources: Record<string, number>; source_labels: Record<string, string>; source_kinds: Record<string, string>; assessment: (Record<keyof typeof sections, Cited[]> & { missing: string[] }) | null } }; stale: boolean }

export function ScheduledReports() {
  const [items, setItems] = useState<Report[]>([]), [total, setTotal] = useState(0), [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Report>();
  const [error, setError] = useState('');
  const listRequest = useRef(0), selection = useRef(0);
  const load = useCallback(async () => {
    const request = ++listRequest.current;
    try {
      const result = await api<{ reports: Report[]; total: number }>(`/api/scheduled-reports?limit=20&offset=${offset}`);
      if (request !== listRequest.current) return;
      setItems(result.reports); setTotal(result.total); setError('');
      setSelected(previous => previous ? result.reports.find(r => r.run.id === previous.run.id) ?? previous : undefined);
    } catch (e) { if (request === listRequest.current) setError((e as Error).message); }
  }, [offset]);
  useEffect(() => {
    load(); const timer = setInterval(load, 15000);
    return () => { listRequest.current++; clearInterval(timer); };
  }, [load]);
  useEffect(() => () => { selection.current++; }, []);
  async function openReport(id: string) {
    const request = ++selection.current;
    try {
      const result = await api<Report>('/api/scheduled-reports/' + id);
      if (request === selection.current) { setSelected(result); setError(''); }
    } catch (e) { if (request === selection.current) setError((e as Error).message); }
  }
  return <section className="panel module scheduled-reports" aria-label="AI 定时分析">
    <div className="module-title"><h2>AI 定时分析</h2><button className="text-button" onClick={() => load().catch(e => setError(e.message))}>刷新分析列表</button></div>

    {error && <p role="alert" className="alert error">{error}</p>}
    {!items.length && <p className="module-empty">尚无定时分析。未配置模型或未启用时，不会生成模拟结果。</p>}
    {items.map(r => <button className="scheduled-report-row" key={r.run.id} onClick={() => openReport(r.run.id)}><span className="tag">{statuses[r.run.data.status]}</span><span>{r.run.data.window_end} · {r.run.data.model || '未配置模型'}<small>计划：{r.run.data.scheduled_at} · 实际开始：{r.run.data.started_at}</small></span>{r.stale && <span className="tag pending">依据已变化</span>}</button>)}
    {total > 20 && <div className="inline-actions"><button className="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>上一页分析</button><span>{offset + 1}–{offset + items.length} / {total}</span><button className="secondary" disabled={offset + items.length >= total} onClick={() => setOffset(offset + 20)}>下一页分析</button></div>}

    {selected && <ReportDialog report={selected} close={() => { selection.current++; setSelected(undefined); }}/>}
  </section>;
}

export function ReportDialog({ report: selected, close }: { report: Report; close: () => void }) {
  const [source, setSource] = useState<object>(), [error, setError] = useState('');
  const selection = useRef(0);
  useEffect(() => () => { selection.current++; }, []);
  async function openSource(id: string) {
    const request = ++selection.current;
    try {
      const kind = selected.run.data.source_kinds[id];
      const result = await api<{ history: { version: number; data?: object }[] }>((kind === 'note' || kind === 'task' ? '/api/records/' : '/api/entities/') + id);
      const revision = result.history.find(r => r.version === selected.run.data.sources[id]);
      if (!revision) throw new Error('依据版本不可用，请检查资料完整性。');
      if (request === selection.current) { setSource(revision.data ?? revision); setError(''); }
    } catch (e) { if (request === selection.current) setError((e as Error).message); }
  }
  const data = selected?.run.data;
  return <Dialog title="定时分析详情" close={close}>
      <p className="tag">{statuses[data.status]}{selected.stale ? ' · 依据已变化' : ''}</p>
      <p className="modal-hint">资料日期：{data.window_start} 至 {data.window_end}（Asia/Shanghai）。计划：{data.scheduled_at}；开始：{data.started_at}；完成：{data.finished_at || '尚未完成'}。</p>
      <p>{data.message}</p>
      {data.assessment && <>{Object.entries(sections).map(([key, label]) => <section className="report-analysis-section" key={key}><h3>{label}</h3>{data.assessment![key as keyof typeof sections].length ? data.assessment![key as keyof typeof sections].map((x, i) => <div key={i}><p>{x.text}</p><div className="inline-actions">{x.source_ids.map(id => <button className="text-button" key={id} onClick={() => openSource(id)}>查看依据 · {data.source_labels[id] || id} · v{data.sources[id]}</button>)}</div></div>) : <p className="quiet">证据不足，未给出结论。</p>}</section>)}<h3>缺失信息</h3><ul>{data.assessment.missing.map((x, i) => <li key={i}>{x}</li>)}</ul></>}
      {source && <details open><summary>所引用版本的原始资料</summary><DataView data={source} names={{}}/></details>}
      <div className="modal-actions"><a className="secondary" href={`/api/scheduled-reports/${selected.run.id}/export?format=markdown`}>下载分析 Markdown</a><a className="secondary" href={`/api/scheduled-reports/${selected.run.id}/export?format=json`}>下载分析 JSON</a></div>
      {error && <p role="alert" className="alert error">{error}</p>}
    </Dialog>;
}
