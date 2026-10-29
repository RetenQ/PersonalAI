import { taskStatuses, tasksForDay, currentTasks } from './taskPresentation';
import { TaskEvents } from './TaskEvents';
import { QuickEntry } from './QuickEntry';
import { PluginBoundary, frontendPlugins, usePlugins } from './plugins';
import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowDownToLine, Plus, Sparkles } from 'lucide-react';
import { api, mutate } from './api';
import type { Activity, Change, CheckIn, DashboardData, Entity, Goal, Pending, Slot, Tracking } from './trackingTypes';
import { moduleNames, slots } from './trackingTypes';
import { CheckInForm, GoalForm, TrackingForm } from './trackingForms';
import { ChangeReview, DataView, Dialog, Progress } from './trackingUI';
import { AnalysisPanel } from './AnalysisPanel';
import { ExportPanel } from './ExportPanel';
import { UserFilesWarning } from './UserFilesPanel';

const endpoints: Record<string, string> = { goal: '/api/goals', tracking: '/api/task-tracking', log: '/api/activity-logs', checkin: '/api/check-ins' };
interface Editor { kind: string; initial?: object; id?: string; version?: number }

export function Dashboard({ ready, today, record, newTask, legacyPending, settings, view = 'overview', children, revision = 0, onSaved }: { ready: boolean; today: string; record: (id: string) => void; newTask: () => void; legacyPending: () => void; settings: () => void; view?: 'overview' | 'journal' | 'review'; onSaved?: () => void; children?: ReactNode; revision?: number }) {
  const plugins = usePlugins();
  const [day, setDay] = useState(today), [data, setData] = useState<DashboardData>();
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [editor, setEditor] = useState<Editor>(), [review, setReview] = useState<Pending>();
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [analysisGoal, setAnalysisGoal] = useState<string>(), [exportOpen, setExportOpen] = useState(false);
  const [history, setHistory] = useState<{ entity: Entity<object>; history: Entity<object>[] }>();
  const reload = useCallback(async () => { if (day) { setData(await api<DashboardData>('/api/dashboard?verify_user_files=false&day=' + day)); onSaved?.(); } }, [day]);
  useEffect(() => { if (!day && today) setDay(today); }, [today, day]);
  useEffect(() => { if (ready && day) { let active = true; api<DashboardData>('/api/dashboard?verify_user_files=false&day=' + day).then(r => { if (active) setData(r); }).catch(e => { if (active) setError(e.message); }); return () => { active = false; }; } }, [ready, day, revision]);
  async function run(action: () => Promise<void>) { if (busy) return; setBusy(true); setError(''); setNotice(''); try { await action(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
  function edit(kind: string, item?: Entity<object>, initial?: object) { setError(''); setEditor({ kind, id: item?.id, version: item?.version, initial: item?.data ?? initial }); }
  async function save(value: object, extra: object = {}) { if (!editor) return; await run(async () => { const r = await mutate<{ change?: Pending; related_change?: Pending }>(endpoints[editor.kind] + (editor.id ? '/' + editor.id : ''), { ...extra, data: value, expected_version: editor.version ?? 0, reason: '用户更新追踪记录' }); setEditor(undefined); if (r.change || r.related_change) setReview(r.change ?? r.related_change); else setNotice('已保存。'); await reload(); }); }
  function source(id: string) { if (data?.tasks.some(t => t.task_id === id)) record(id); else run(async () => setHistory(await api('/api/entities/' + id))); }
  if (!data) return <>{view === 'journal' && <><header className="overview-heading"><h1>日志与任务</h1></header>{children}</>}<p role={error ? 'alert' : 'status'}>{error || '正在读取…'}</p></>;
  const names = Object.fromEntries([...data.goals.map(g => [g.id, g.data.title]), ...data.tasks.map(t => [t.task_id, t.record.text]), ...data.settings.task_types.map(t => [t.id, t.name])]);
  const goalName = (id: string | null) => id ? names[id] ?? id : '未关联目标';
  const goalTasks = (goalId: string | null) => currentTasks(data.tasks,goalId).map(t => <div className="task-row" key={t.task_id}><div className="task-title"><button onClick={() => record(t.task_id)}>{t.record.text}</button><button className="text-button" onClick={() => edit('tracking', t.tracking ?? undefined, { task_id: t.task_id, goal_id: t.goal_id, tags: t.tags, progress: t.tracking?.data.progress ?? null })}>调整归属</button></div><span className="task-status">{taskStatuses[t.record.status]}</span><div className="tag-row">{t.tags.map(id => <span className="tag" key={id}>{names[id] ?? id}</span>)}</div></div>);
  const logCard = (l: Entity<Activity>, completed = false) => <article className={completed ? "goal-card completed-card" : "timeline-entry"} key={l.id}><div className="small-label">{l.data.date} · {l.data.slot ? slots[l.data.slot] : '未指定时段'} · 修订 {l.version}</div><div className="module-title"><h3>{l.data.text}</h3>{completed && <span className="tag completed">已完成</span>}</div>{l.data.result && <p className="log-result">结果：{l.data.result}</p>}{l.data.obstacle && <p className="log-obstacle">阻碍：{l.data.obstacle}</p>}<div className="inline-actions">{l.data.task_id && <button className="text-button" onClick={() => record(l.data.task_id!)}>关联任务：{names[l.data.task_id] ?? '查看任务'}</button>}{l.data.goal_id && <button className="text-button" onClick={() => source(l.data.goal_id!)}>目标：{goalName(l.data.goal_id)}</button>}<button className="text-button" onClick={() => source(l.id)}>来源与历史</button></div></article>;
  const modules: Record<string, ReactNode> = {
    goals: <><div className="module-title"><h2>目标与任务</h2><div className="inline-actions"><button className="text-button" onClick={newTask}>新增任务</button><button className="secondary" onClick={() => edit('goal')}><Plus size={14}/>建立目标</button></div></div>{!data.goals.length && <div className="empty"><h3>暂无目标</h3><button className="primary" onClick={() => edit('goal')}>建立第一个目标 <Plus size={14}/></button></div>}{data.goals.map(g => { const analysis = data.analyses.filter(a => a.data.goal_id === g.id).at(-1); const a = analysis?.data.assessment; return <article className="goal-card" id={`goal-${g.id}`} key={g.id}><div className="module-title"><h3>{g.data.title}</h3><button className="text-button" onClick={() => edit('goal', g)}>修改目标／进度</button></div><details className="goal-details"><summary>目标详情与分析</summary><p className="criteria">{g.data.criteria}</p><div className="goal-meta"><span>{g.data.mode === 'metric' ? `当前 ${g.data.current ?? '未知'} / 目标 ${g.data.target ?? '未知'} ${g.data.unit}` : `${g.data.milestones.length} 个里程碑`}</span><span>{g.data.due ? `目标日期 ${g.data.due}` : '未设目标日期'}</span></div>{g.data.mode === 'milestones' && <details><summary>里程碑明细</summary>{g.data.milestones.map((m, i) => <Progress key={i} value={m.progress} label={`${m.title} · 权重 ${m.weight}`}/>)}</details>}<div className="ai-summary"><span><Sparkles size={14}/>AI 估计</span><strong>{a?.low != null ? `${a.low}–${a.high}%` : a ? '证据不足，未估计' : '尚未分析'}</strong>{analysis?.stale && <em>依据已变化</em>}</div>{a && <details className="analysis-detail"><summary>查看分析、证据与建议</summary><p>{a.explanation}</p><p className="module-description">{analysis!.updated_at} · {analysis!.data.model} · 置信度 {({ low: '低', medium: '中', high: '高', insufficient: '证据不足' } as Record<string, string>)[a.confidence]}</p>{a.contributions.map((c, i) => <div key={i}><strong>{names[c.task_id]} · {({ direct: '直接贡献', supporting: '辅助作用', insufficient: '证据不足' } as Record<string, string>)[c.relevance]}</strong><p>{c.reason}</p><div className="inline-actions">{c.source_ids.map(id => <button key={id} className="text-button" onClick={() => source(id)}>查看依据 · v{analysis!.data.sources[id]}</button>)}</div></div>)}<p>缺失信息：{a.missing.join('；') || '未列出'}</p><ul>{a.suggestions.map((s, i) => <li key={i}>{s}</li>)}</ul><div className="inline-actions">{a.source_ids.map(id => <button key={id} className="text-button" onClick={() => source(id)}>来源 {names[id] ?? id.slice(0, 8)} · v{analysis!.data.sources[id]}</button>)}</div></details>}<div className="inline-actions"><button className="text-button" disabled={!plugins.active('analysis')} onClick={() => setAnalysisGoal(g.id)}>选择资料并分析</button><button className="text-button" onClick={() => source(g.id)}>目标来源与历史</button></div></details><Progress value={g.progress}/><div className="task-list">{goalTasks(g.id)}</div></article>; })}{data.tasks.some(t => !t.goal_id && t.record.status !== 'done') && <div className="goal-card"><h3>未关联目标的任务</h3>{goalTasks(null)}</div>}</>,
    logs: <><TaskEvents day={day} revision={revision} record={record}/>{data.logs.length > 0 && <details><summary>历史活动记录</summary>{data.logs.slice().reverse().map(l => logCard(l))}</details>}</>,
    checkins: <><h2>早中晚回顾</h2><div className="checkin-grid">{Object.entries(slots).map(([slot, label]) => <section className="checkin-card" key={slot}><h3>{label}</h3>{data.checkins.filter(c => c.data.slot === slot).map(c => <div key={c.id}><p>{c.data.response}</p>{c.data.obstacle && <p className="log-obstacle">阻碍：{c.data.obstacle}</p>}<span className="quiet">{goalName(c.data.goal_id)}</span><div className="inline-actions"><button className="text-button" onClick={() => edit('checkin', c)}>更正</button><button className="text-button" onClick={() => source(c.id)}>历史</button></div></div>)}{!data.checkins.some(c => c.data.slot === slot) && <p className="module-empty">未记录</p>}<button className="secondary" onClick={() => edit('checkin', undefined, { date: day, slot: slot as Slot, goal_id: null, response: '', obstacle: '' })}>填写{label}回应</button></section>)}</div></>,
    pending: <><div className="module-title"><h2>待确认事项 <span className="tag pending">{data.pending.length + (data.config_pending || 0)}</span></h2><button className="text-button" onClick={legacyPending}>查看记录修改提案</button></div>{!!data.config_pending && <button className="text-button" onClick={settings}>设置与插件修改 · {data.config_pending}</button>}{data.pending.map(p => <button className="pending-card" key={p.id} onClick={() => { setError(''); setReview(p); }}><span className="tag pending">{p.kind === 'suggestion' ? 'AI 建议' : '修改确认'}</span><p>{p.kind === 'suggestion' ? p.data.text : p.data.reason + ' · ' + (names[p.data.target_id] ?? ({ settings: '应用设置', tracking: '任务追踪', goal: '目标', log: '日志', checkin: '回顾', state: '现状', profile: '个人档案' } as Record<string, string>)[p.data.target_kind])}</p></button>)}{!data.pending.length && !data.config_pending && <p className="module-empty">暂无待确认事项。</p>}<details className="help"><summary>已处理事项（{data.decisions.length}）</summary>{[...data.decisions].reverse().map(p => <div className="timeline-entry" key={p.id}><span className="tag">{p.data.status === "accepted" ? "已接受" : "已拒绝"}</span><p>{p.kind === "suggestion" ? p.data.text : p.data.reason}</p><button className="text-button" onClick={() => source(p.id)}>查看处理历史</button></div>)}</details></>,
  };
  for (const p of frontendPlugins) if(plugins.active(p.id)) for(const [id,Component] of Object.entries(p.modules)) modules[id]=<PluginBoundary key={id}><Component/></PluginBoundary>;
  const todaysTasks=tasksForDay(data.tasks,today);
  const visibleModules=[...data.settings.order,...Object.keys(modules).filter(id=>!data.settings.order.includes(id))].filter(id=>!data.settings.hidden.includes(id)&&modules[id]);
  const pageModules = view === 'journal'
    ? (plugins.active('journal') ? ['logs'] : [])
    : view === 'review' ? (plugins.active('journal') ? ['checkins'] : []) : visibleModules.filter(id => !['logs', 'checkins', 'pending', 'other', 'profile'].includes(id));
  return <>
    {view !== 'review' && <header className="overview-heading">
      <h1>{view === 'journal' ? '日志与任务' : '总览'}</h1>
      {view === 'overview' && <div className="year-strip" role="group" aria-label="年度时间">
        <span>{data.year.year}</span>
        <div className="progress-track" role="progressbar" aria-label="年度时间已过" aria-valuemin={0} aria-valuemax={100} aria-valuenow={data.year.elapsed_percent}><span style={{width: `${data.year.elapsed_percent}%`}}/></div>
        <strong>{data.year.elapsed_percent}%</strong>
      </div>}
    </header>}
    {children}
    <UserFilesWarning status={data.user_files}/>
    {error && <p role="alert" className="alert error">{error}</p>}
    {notice && <p role="status" className="alert success">{notice}</p>}
    {view === 'overview' && <>
      <section id="dashboard-pending" className="panel module module-pending" aria-label="待确认事项">{modules.pending}</section>
      <div className="overview-start">
        <section className="next-actions panel" aria-label="今日任务">
          <div className="next-heading"><h2>今日任务</h2><button className="secondary" onClick={newTask}>创建任务</button></div>
          <div className="today-task-list">{todaysTasks.length ? todaysTasks.map(t => <div className="today-task" key={t.task_id}><button className="next-link" onClick={() => record(t.task_id)}>{t.record.text}</button><span className="task-status">{taskStatuses[t.record.status]}</span></div>) : <p className="module-empty">暂无今日任务。</p>}</div>
        </section>
        <QuickEntry today={today} tasks={data.tasks} saved={reload}/>
      </div>
    </>}
    {view !== 'review' && <div className="dashboard-toolbar"><label>回看日期<input required type="date" value={day} onChange={e => { if (e.target.value) setDay(e.target.value); }}/></label><div className="inline-actions"><button className="text-button" onClick={() => setDay(today)}>回到今天</button><button disabled={!plugins.active('exchange')} className="secondary" onClick={() => setExportOpen(true)}><ArrowDownToLine size={15}/>导出回顾</button></div></div>}
    <div className="dashboard-grid">{pageModules.map(id => <section id={`dashboard-${id}`} className={`panel module module-${id}`} key={id} aria-label={moduleNames[id] || plugins.items.find(p=>p.modules.includes(id))?.name || id}>{modules[id]}</section>)}</div>
    {editor && <Dialog title={editor.kind === 'goal' ? '目标与完成标准' : editor.kind === 'tracking' ? '调整任务归属' : editor.kind === 'checkin' ? '填写回顾' : '活动日志'} busy={busy} close={() => setEditor(undefined)}>{editor.kind === 'goal' && <GoalForm initial={editor.initial as Goal | undefined} save={save} busy={busy}/>} {editor.kind === 'tracking' && <TrackingForm initial={editor.initial as Tracking} dashboard={data} save={save} busy={busy}/>} {editor.kind === 'checkin' && <CheckInForm initial={editor.initial as CheckIn} dashboard={data} save={save} busy={busy}/>} {error && <p className="alert error" role="alert">{error}</p>}</Dialog>}
    {review && <Dialog title={review.kind === 'change' ? '确认这次修改' : '处理 AI 建议'} busy={busy} close={() => setReview(undefined)}>{review.kind === 'change' ? <ChangeReview change={review as Entity<Change>} names={names} busy={busy} decide={decision => run(async () => { await mutate(`/api/changes/${review.id}/decision`, { decision }); setReview(undefined); await reload(); setNotice('已处理，历史记录已保留。'); })}/> : <><p>{review.data.text}</p><p className="modal-hint">接受表示保留这条建议，不会自动创建任务或更改计划。关闭窗口可暂留待确认。</p><div className="modal-actions">{(['reject', 'accept'] as const).map(decision => <button key={decision} className={decision === 'accept' ? 'primary' : 'secondary'} disabled={busy} onClick={() => run(async () => { await mutate(`/api/changes/${review.id}/decision`, { decision }); setReview(undefined); await reload(); })}>{decision === 'accept' ? '接受建议' : '拒绝建议'}</button>)}</div></>}{error && <p className="alert error" role="alert">{error}</p>}</Dialog>}
    {history && <Dialog title="来源与修订历史" close={() => setHistory(undefined)} busy={busy}><p className="modal-hint">编号 {history.entity.id} · 当前修订 {history.entity.version}</p>{[...history.history].reverse().map(e => <details key={e.version} open={e.version === history.entity.version}><summary>修订 {e.version} · {e.updated_at}</summary><DataView data={e.data} names={names}/></details>)}</Dialog>}
    {analysisGoal && <Dialog busy={analysisBusy} title="分析目标进展" close={() => setAnalysisGoal(undefined)}><AnalysisPanel onBusy={setAnalysisBusy} goalId={analysisGoal} data={data} done={() => { setAnalysisGoal(undefined); reload().catch(e => setError(e.message)); setNotice('分析已保存；已确认进度保持不变。'); }}/></Dialog>}
    {exportOpen && <Dialog title="导出进度与回应" close={() => setExportOpen(false)}><ExportPanel data={data}/></Dialog>}
  </>;
}
