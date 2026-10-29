import { taskStatuses } from './taskPresentation';
import type { TaskEvent } from './TaskEvents';
import { Dashboard } from './Dashboard';
import { useEffect, useState } from 'react';
import { api, type Daily, type Entry } from './api';
import type { DashboardData } from './trackingTypes';
import { usePlugins } from './plugins';
import { ScheduledReports, ReportDialog, type Report } from './ScheduledReports';

export function previousDay(day: string) {
  // Calendar arithmetic on an ISO date, independent of the browser's timezone/DST.
  const date = new Date(day + 'T12:00:00Z');
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}

interface DayReview { events?: TaskEvent[]; day: string; notes: Entry[]; logs: DashboardData['logs']; checkins: DashboardData['checkins']; tasks: Entry[] }
export function summaryText(review: DayReview) {
  const facts = [
    ...(review.events??[]).map(e=>e.title+'：'+e.action),
    ...review.notes.map(r => r.text),
    ...review.logs.map(r => r.data.text + (r.data.result ? '；结果：' + r.data.result : '')),
    ...review.checkins.map(r => r.data.response),
  ];
  if (!facts.length) return '当天暂无记录。';
  const text = facts.map(text => text.replace(/[。；;\s]+$/u, '')).filter(Boolean).join('；') + '。';
  return text.length > 320 ? text.slice(0, 320) + '…' : text;
}

// The existing endpoint is ordered by actual start time, not the report's date.
// Follow pagination until both dates have a latest run, or the list is exhausted.
export async function reportsForDays(days: string[], signal: AbortSignal) {
  const found: Record<string, Report> = {};
  let offset = 0;
  while (!signal.aborted) {
    const page = await api<{ reports: Report[]; next_offset: number | null; total: number }>(`/api/scheduled-reports?limit=200&offset=${offset}`, { signal });
    for (const report of page.reports) {
      const day = report.run.data.window_end;
      if (days.includes(day) && !found[day]) found[day] = report;
    }
    if (days.every(day => found[day]) || page.next_offset == null) break;
    if (page.next_offset <= offset) throw new Error('分析列表分页异常，请刷新重试。');
    offset = page.next_offset;
  }
  return found;
}

export function DailyReviewPage({ day, setDay, ready, record, dataRevision = 0 }: { day: string; setDay: (day: string) => void; ready: boolean; record: (id: string) => void; dataRevision?: number }) {
  const plugins = usePlugins();
  const analysisEnabled = plugins.active('analysis'), journalEnabled = plugins.active('dashboard');
  const [reviews, setReviews] = useState<DayReview[]>(), [reports, setReports] = useState<Record<string, Report>>({});
  const [error, setError] = useState(''), [analysisError, setAnalysisError] = useState(''), [analysisLoading, setAnalysisLoading] = useState(false);
  const [revision, refresh] = useState(0), [selected, setSelected] = useState<Report>(), [showHistory, setShowHistory] = useState(false);
  useEffect(() => {
    if (!ready || !day) return;
    const controller = new AbortController(), signal = controller.signal;
    const days = [day, previousDay(day)];
    setReviews(undefined); setReports({}); setError(''); setAnalysisError(''); setAnalysisLoading(analysisEnabled);
    Promise.all(days.map(async date => {
      const [daily, events, dashboard] = await Promise.all([
        api<Daily>('/api/reports/daily?day=' + date, { signal }),
        api<{items:TaskEvent[]}>('/api/task-events?day='+date,{signal}),
        journalEnabled ? api<DashboardData>('/api/dashboard?verify_user_files=false&day=' + date, { signal }) : Promise.resolve(null),
      ]);
      return { day: date, events:events.items, notes: [...daily.groups.flatMap(g => g.records), ...daily.uncategorized], logs: dashboard?.logs ?? [], checkins: dashboard?.checkins ?? [], tasks: daily.tasks };
    })).then(value => { if (!signal.aborted) setReviews(value); }).catch(e => { if (!signal.aborted) setError(e.message); });
    if (analysisEnabled) reportsForDays(days, signal).then(value => { if (!signal.aborted) setReports(value); })
      .catch(e => { if (!signal.aborted) setAnalysisError(e.message); }).finally(() => { if (!signal.aborted) setAnalysisLoading(false); });
    return () => controller.abort();
  }, [ready, day, revision, dataRevision, analysisEnabled, journalEnabled]);

  const runStates: Record<string, string> = { running: '分析生成中', failed: '分析失败', interrupted: '分析中断', skipped: '资料不足，未生成分析' };
  return <div className="daily-review-page">
    <div className="report-toolbar"><label>查看日期<input type="date" required value={day} onChange={e => { if (e.target.value) setDay(e.target.value); }}/></label><button className="secondary" onClick={() => refresh(v => v + 1)}>刷新回顾</button></div>
    {error && <p className="alert error" role="alert">{error}</p>}
    {!reviews && !error && <p role="status">正在读取回顾…</p>}
    <div className="daily-review-grid">{reviews?.map((review, index) => {
      const report = reports[review.day], assessment = report?.run.data.assessment;
      const analysis = assessment ? [...assessment.reflection, ...assessment.suggestions].map(x => x.text).join(' ') : '';
      return <section className="panel daily-review-card" key={review.day} aria-label={index === 0 ? '当日回顾' : '前一天回顾'}>
        <header className="module-title"><h2>{index === 0 ? '当日回顾' : '前一天'}</h2><time dateTime={review.day}>{review.day}</time></header>
        <p className="daily-summary">{summaryText(review)}</p>
        <div className="daily-analysis"><h3>分析</h3>
          {analysisError ? <p role="alert">分析读取失败：{analysisError}</p> : analysisLoading ? <p role="status">正在读取分析…</p> : <>
            <p>{(analysis.length > 480 ? analysis.slice(0, 480) + '…' : analysis) || (report ? runStates[report.run.data.status] || '暂无分析结论。' : '尚未生成分析。')}</p>
            {report && <><div className="analysis-meta"><span>{report.run.data.model}</span>{report.stale && <span className="tag pending">依据已变化</span>}</div><button className="text-button" onClick={() => setSelected(report)}>查看分析与依据</button></>}
          </>}
        </div>
        {!!((review.events?.length??0) + review.notes.length + review.logs.length + review.checkins.length + review.tasks.length) && <details className="review-sources"><summary>查看记录与计划</summary>
          {review.events?.map(e=><p key={e.id}>{e.title}：{e.action} · 修订 {e.version}</p>)}
          {review.notes.map(r => <button key={r.id} className="review-source" onClick={() => record(r.id)}>{r.text}</button>)}
          {review.logs.map(r => <p key={r.id}>{r.data.text}{r.data.result && '；结果：' + r.data.result}</p>)}
          {review.checkins.map(r => <p key={r.id}>{r.data.response}</p>)}
          {!!review.tasks.length && <><h3>计划任务</h3>{review.tasks.map(r => <button key={r.id} className="review-source" onClick={() => record(r.id)}>{r.text} · {taskStatuses[r.status]}</button>)}</>}
        </details>}
      </section>;
    })}</div>
    {journalEnabled && <Dashboard key={day} view="review" ready={ready} today={day} record={record} newTask={() => {}} legacyPending={() => {}} settings={() => {}} onSaved={() => refresh(v => v + 1)}/>}
    {analysisEnabled && <details className="report-history" onToggle={e => setShowHistory(e.currentTarget.open)}><summary>分析历史</summary>{showHistory && <ScheduledReports/>}</details>}
    {selected && <ReportDialog report={selected} close={() => setSelected(undefined)}/>}
  </div>;
}
