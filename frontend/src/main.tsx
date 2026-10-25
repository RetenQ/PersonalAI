import { ScheduledReports } from './ScheduledReports';
import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { LayoutDashboard, SlidersHorizontal, ArrowDownToLine, ArrowRight, ArrowUpRight, Check, CheckCheck, ChevronRight, CircleHelp, Clock3, FileText, History, Leaf, ListTodo, LoaderCircle, LockKeyhole, MessageSquare, Plus, Search, ShieldCheck, Sparkles, X } from 'lucide-react';
import { api, connect, exportBackup, mutate, verifyBackup } from './api';
import type { AppStatus, Daily, Entry, Fields, Kind, Proposal, RecordStatus } from './api';
import './style.css';
import './tracking.css';
import './theme.css';
import { SpaceMark } from './SpaceMark';
import { Dashboard } from './Dashboard';
import { SettingsPage } from './SettingsPage';
import { UserFilesWarning } from './UserFilesPanel';

type Page = 'dashboard' | 'settings' | 'capture' | 'history' | 'plans' | 'reports';
const navigation: { id: Page; label: string; subtitle: string; icon: typeof MessageSquare }[] = [
  { id: 'dashboard', label: '总览', subtitle: '看见目标和日常', icon: LayoutDashboard },
  { id: 'capture', label: '记录', subtitle: '留住日常的片刻', icon: MessageSquare },
  { id: 'plans', label: '任务与想法', subtitle: '按自己的节奏前进', icon: ListTodo },
  { id: 'history', label: '历史', subtitle: '让经历有迹可循', icon: History },
  { id: 'reports', label: '每日回顾', subtitle: '回看真实的今天', icon: FileText },
  { id: 'settings', label: '设置', subtitle: '管理你的空间', icon: SlidersHorizontal },
];
const kinds: Record<Kind, string> = { note: '日常记录', task: '正式任务', idea: '想法' };
const statuses: Record<RecordStatus, string> = { open: '待进行', partial: '部分完成', done: '已完成' };
const time = (s: string) => new Date(s).toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false });

function App() {
  const [page, setPage] = useState<Page>('dashboard');
  const [status, setStatus] = useState<AppStatus>();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [revision, refresh] = useState(0);
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [text, setText] = useState('');
  const [day, setDay] = useState('');
  const [category, setCategory] = useState('uncategorized');
  const [kind, setKind] = useState<Kind>('note');
  const [query, setQuery] = useState('');
  const [filterDay, setFilterDay] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [reportDay, setReportDay] = useState('');
  const [report, setReport] = useState<Daily>();
  const [selected, setSelected] = useState<{ record: Entry; history: Entry[] }>();
  const [edit, setEdit] = useState<Fields>();
  const [reason, setReason] = useState('更正记录');
  const [review, setReview] = useState<Proposal>();
  const [planTab, setPlanTab] = useState<'task' | 'idea' | 'pending'>('task');
  const [backupOpen, setBackupOpen] = useState(false);
  const upload = useRef<HTMLInputElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const categories = status?.categories ?? {};
  const pending = proposals.filter(p => p.status === 'pending');

  useEffect(() => {
    connect().then(() => api<AppStatus>('/api/status')).then(s => {
      setStatus(s); setDay(s.today); setReportDay(s.today); setReady(true);
    }).catch(e => { setError(e.message); setLoading(false); });
  }, []);

  useEffect(() => {
    if (!ready) return;
    let active = true;
    setLoading(true);
    const parameters = new URLSearchParams();
    if (page === 'history') {
      if (query) parameters.set('q', query);
      if (filterDay) parameters.set('day', filterDay);
      if (filterCategory) parameters.set('category', filterCategory);
    }
    Promise.all([api<{ records: Entry[] }>('/api/records?' + parameters), api<{ proposals: Proposal[] }>('/api/proposals'), api<AppStatus>('/api/status')])
      .then(([r, p, s]) => { if (active) { setEntries(r.records); setProposals(p.proposals); setStatus(s); } })
      .catch(e => { if (active) { setError(e.message); setEntries([]); setProposals([]); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [ready, page, revision, query, filterDay, filterCategory]);

  useEffect(() => {
    if (!ready || page !== 'reports' || !reportDay) return;
    let active = true;
    setReport(undefined);
    api<Daily>('/api/reports/daily?day=' + reportDay).then(r => { if (active) setReport(r); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [ready, page, reportDay, revision]);

  useEffect(() => {
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) { setSelected(undefined); setReview(undefined); setBackupOpen(false); }
    };
    document.addEventListener('keydown', onEscape);
    return () => document.removeEventListener('keydown', onEscape);
  }, [busy]);

  async function perform(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : '操作失败，请重试。'); }
    finally { setBusy(false); }
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    await perform(async () => {
      await mutate('/api/records', { text, date: day, category, kind, status: 'open' });
      setText(''); setNotice(kind === 'note' ? '原文已保存到本机。尚未进行 AI 理解。' : `${kinds[kind]}已由你明确创建。`);
      refresh(v => v + 1);
    });
  }

  async function openEntry(id: string) {
    await perform(async () => {
      const result = await api<{ record: Entry; history: Entry[] }>('/api/records/' + id);
      setSelected(result); setEdit(undefined); setReason('更正记录');
    });
  }

  async function propose(event: React.FormEvent) {
    event.preventDefault();
    if (!selected || !edit) return;
    await perform(async () => {
      const result = await mutate<{ proposal: Proposal }>(`/api/records/${selected.record.id}/revisions`, { ...edit, expected_version: selected.record.version, reason });
      setSelected(undefined); setEdit(undefined); setReview(result.proposal); refresh(v => v + 1);
    });
  }

  async function decide(proposal: Proposal, decision: 'accept' | 'reject') {
    await perform(async () => {
      await mutate(`/api/proposals/${proposal.id}/decision`, { decision });
      setReview(undefined); setNotice(decision === 'accept' ? '已确认并保存，历史版本已保留。' : '已拒绝提案，原记录保持不变。');
      refresh(v => v + 1);
    });
  }

  function newItem(type: Kind) { setKind(type); setPage('capture'); setNotice(''); setTimeout(() => composer.current?.focus(), 20); }
  function fieldsEditor(value: Fields, update: (fields: Fields) => void) {
    return <><label>记录内容<textarea required maxLength={10000} rows={6} value={value.text} onChange={e => update({ ...value, text: e.target.value })}/></label>
      <div className="form-row"><label>日期<input required type="date" value={value.date} onChange={e => update({ ...value, date: e.target.value })}/></label>
        <label>类别<select value={value.category} onChange={e => update({ ...value, category: e.target.value })}>{Object.entries(categories).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
      {selected?.record.kind === 'task' && <label>执行状态<select value={value.status} onChange={e => update({ ...value, status: e.target.value as RecordStatus })}>{Object.entries(statuses).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>}</>;
  }
  function card(entry: Entry) {
    return <button className="record-card" key={entry.id} onClick={() => openEntry(entry.id)}>
      <div className="record-icon">{entry.kind === 'task' ? <ListTodo size={18}/> : entry.kind === 'idea' ? <Sparkles size={18}/> : <FileText size={18}/>}</div>
      <div className="record-copy"><div className="record-meta"><span>{categories[entry.category]}</span><span>·</span><span>{entry.date}</span><span>{time(entry.created_at)}</span>{entry.version > 1 && <span>修订 {entry.version}</span>}</div>
        <p>{entry.text}</p><span className="record-foot">{entry.kind === 'note' ? '原文已保存 · 未进行 AI 理解' : `${kinds[entry.kind]} · ${entry.kind === 'task' ? statuses[entry.status] : '保留灵感，不构成承诺'}`}</span></div>
      <ChevronRight size={17} className="muted"/>
    </button>;
  }
  function empty(title: string, subtitle: string) {
    return <div className="empty"><div className="empty-icon"><Leaf size={26}/></div><h3>{title}</h3><p>{subtitle}</p></div>;
  }
  const todayEntries = entries.filter(e => e.date === status?.today && e.kind === 'note');

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={e => { e.preventDefault(); setPage('dashboard'); }}><span className="brand-mark"><span className="brand-glyph"/></span><span>Personal<span className="brand-ai">AI</span><small>个人生活与成长</small></span></a>
      <div className="sidebar-label">我的空间</div>
      <nav aria-label="主要导航">{navigation.map(({ id, label, icon: Icon }) => <button key={id} className={page === id ? 'nav-item active' : 'nav-item'} onClick={() => { setPage(id); setError(''); }}><Icon size={19}/><span>{label}</span>{id === 'plans' && pending.length > 0 && <span className="count">{pending.length}</span>}</button>)}</nav>
      <div className="sidebar-note"><span className="tiny-line"/><p>记录当下。<br/>走向想去的地方。</p><small>A SPACE FOR YOUR LIFE.</small></div>
      <div className="sidebar-bottom"><button onClick={() => setBackupOpen(true)}><ArrowDownToLine size={17}/>备份与恢复校验<ArrowUpRight size={14}/></button><div className="local-status"><span className="status-dot"/>本机空间 <span>v0.2</span></div></div>
    </aside>
    <div className="workspace">
      <header className="topbar"><div><span className="breadcrumb">我的空间</span><ChevronRight size={14}/><span>{navigation.find(n => n.id === page)?.label}</span></div><div className="topbar-actions"><button className="compact-backup" onClick={() => setBackupOpen(true)} aria-label="备份与恢复校验"><ArrowDownToLine size={15}/><span>备份</span></button><span className="privacy"><LockKeyhole size={13}/>本地优先</span></div></header>
      <main>
        <div className={page === 'dashboard' ? 'page-heading dashboard-heading' : 'page-heading'}><div><div className="eyebrow">{page === 'dashboard' ? 'YOUR LIFE, IN VIEW.' : page === 'settings' ? 'MAKE IT YOURS.' : page === 'capture' ? 'A LITTLE MOMENT, KEPT.' : page === 'history' ? 'YOUR DAYS, REMEMBERED.' : page === 'plans' ? 'AT YOUR OWN PACE.' : 'LOOK BACK, GENTLY.'}</div><h1>{page === 'dashboard' ? '让每一步，都有迹可循。' : page === 'settings' ? '你的空间，由你定义。' : page === 'capture' ? '留下一点，今天的生活。' : page === 'history' ? '每一小步，都有迹可循。' : page === 'plans' ? '计划由你，节奏也由你。' : '回看今天发生的事。'}</h1><p>{page === 'dashboard' ? '目标、任务与日常记录，在这里连成一条清晰的线。' : page === 'settings' ? '展示内容、模块与模型服务，都由你决定。' : page === 'capture' ? '吃了什么、做了什么、感觉如何。想到哪里，就记到哪里。' : page === 'history' ? '回到记录发生的地方，查看原文、来源与每一次更正。' : page === 'plans' ? '分清要做的事和想做的事，让每一次调整都经过你的确认。' : '只呈现已有记录，不用空白推测你的生活。'}</p></div>{page === 'dashboard' && <SpaceMark/>}<div className="date-stamp"><span>{status?.today.replaceAll('-', ' / ') ?? '本机时间'}</span><small>Asia / Shanghai</small></div></div>
        {error && <div className="alert error" role="alert"><CircleHelp size={18}/><span>{error}</span><button aria-label="关闭错误提示" onClick={() => setError('')}><X size={16}/></button></div>}
        {notice && <div className="alert success" role="status"><Check size={18}/><span>{notice}</span><button aria-label="关闭成功提示" onClick={() => setNotice('')}><X size={16}/></button></div>}
        {status && !status.storage.healthy && <div className="alert error" role="alert">{status.storage.errors.join('；')}</div>}

        {page !== 'dashboard' && page !== 'settings' && <UserFilesWarning status={status?.user_files}/>}
        {page === 'dashboard' && <Dashboard ready={ready} today={status?.today ?? ''} record={openEntry} newTask={() => newItem('task')} legacyPending={() => { setPage('plans'); setPlanTab('pending'); }} settings={() => setPage('settings')}/>}
        {page === 'settings' && <SettingsPage ready={ready} backup={() => setBackupOpen(true)}/>}
        {page === 'capture' && <div className="content-grid"><div>
          <form className="composer panel" onSubmit={save}><div className="panel-header"><span><span className="teal-dot"/>新记录</span><span className="quiet">不必完整，也不必完美</span></div>
            <div className="kind-switch" aria-label="记录类型">{Object.entries(kinds).map(([key, label]) => <button type="button" className={kind === key ? 'selected' : ''} key={key} onClick={() => setKind(key as Kind)}>{label}</button>)}</div>
            <label className="sr-only" htmlFor="capture-text">记录内容</label><textarea id="capture-text" ref={composer} required maxLength={10000} placeholder={kind === 'note' ? '今天有什么想记住的？\n比如：午饭后散步了 20 分钟，下午读完一节课程，精神还不错。' : kind === 'task' ? '写下一件你明确决定要做的事…' : '留住一个想法，不急着把它变成任务…'} value={text} onChange={e => setText(e.target.value)}/>
            <div className="composer-fields"><label>记录日期<input type="date" required value={day} onChange={e => setDay(e.target.value)}/></label><label>手动分类<select value={category} onChange={e => setCategory(e.target.value)}>{Object.entries(categories).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label></div>
            <div className="composer-footer"><span><LockKeyhole size={13}/>{kind === 'task' ? '保存即明确创建正式任务' : kind === 'idea' ? '仅保存想法，不进入正式待办' : '保存原文，不自动生成任务'}</span><button className="primary" disabled={busy || !ready || !text.trim() || !status?.storage.healthy}>{busy ? <LoaderCircle size={16} className="spin"/> : <Plus size={16}/>}保存{kind === 'note' ? '记录' : kinds[kind]}</button></div>
          </form>
          <div className="section-heading"><h2>今天的记录 <span>{todayEntries.length}</span></h2><button className="text-button" onClick={() => setPage('history')}>查看全部<ArrowRight size={14}/></button></div>
          <div className="record-list">{loading ? <div className="loading"><LoaderCircle className="spin" size={20}/>正在读取本地记录</div> : todayEntries.length ? todayEntries.map(card) : empty('今天还没有记录', '从一句话开始。你不需要填满所有类别。')}</div>
        </div><aside className="right-column"><div className="guide-card"><div className="guide-icon"><Leaf size={22}/></div><h3>记录是为了理解自己</h3><p>不用追求漂亮的数字。<br/>一次休息、一点进展，<br/>都是生活的一部分。</p><div className="guide-rule"/><div className="small-label">可以从这些开始</div><div className="prompt-chips">{['今天的精神状态', '一点学习进展', '吃饭与运动', '休息与小确幸'].map(v => <button key={v} onClick={() => { setText(prev => prev ? prev + '\n' + v + '：' : v + '：'); composer.current?.focus(); }}>{v}<Plus size={12}/></button>)}</div></div>
          <div className="model-note"><span className="model-icon"><Sparkles size={16}/></span><div><h4>记录原文，分析另行确认</h4><p>此处保存原文和手动分类。若你另行授权定时分析，范围内的记录会按时发送给模型。</p><span>目标分析请前往总览</span></div></div><div className="subtle-note"><ShieldCheck size={15}/><p>修改保留历史，重要调整由你确认。</p></div></aside></div>}

        {page === 'history' && <><div className="filters panel"><label className="search-box"><Search size={17}/><input aria-label="搜索记录" placeholder="搜索记录内容…" value={query} onChange={e => setQuery(e.target.value)}/></label><label>日期<input type="date" value={filterDay} onChange={e => setFilterDay(e.target.value)}/></label><label>类别<select value={filterCategory} onChange={e => setFilterCategory(e.target.value)}><option value="">全部类别</option>{Object.entries(categories).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><button className="text-button" onClick={() => { setQuery(''); setFilterDay(''); setFilterCategory(''); }}>清除筛选</button></div><div className="section-heading"><h2>已保存记录 <span>{entries.length}</span></h2><span className="quiet">点击记录查看来源与修订</span></div><div className="record-list">{loading ? <p className="loading">正在读取…</p> : entries.length ? entries.map(card) : empty('没有符合条件的记录', '可以调整筛选条件，或开始记录新的片刻。')}</div></>}

        {page === 'plans' && <><div className="section-heading"><div className="tabs">{([['task', '正式任务'], ['idea', '想法库'], ['pending', `待确认 · ${pending.length}`]] as const).map(([key, label]) => <button key={key} className={planTab === key ? 'active' : ''} onClick={() => setPlanTab(key)}>{label}</button>)}</div><button className="primary" onClick={() => newItem(planTab === 'idea' ? 'idea' : 'task')}><Plus size={16}/>新增{planTab === 'idea' ? '想法' : '任务'}</button></div>
          <div className="info-strip"><ShieldCheck size={17}/>{planTab === 'pending' ? '确认前，提案不会改变原记录。每次确认都会检查版本是否仍有效。' : planTab === 'idea' ? '想法可以先放在这里。只有你明确决定，才成为正式任务。' : '任务由你明确创建。更改日期、内容或执行状态时，会先展示拟修改内容。'}</div>
          {planTab === 'pending' ? <div className="record-list">{pending.length ? pending.map(p => <button className="record-card" key={p.id} onClick={() => setReview(p)}><div className="record-icon"><Clock3 size={19}/></div><div className="record-copy"><div className="record-meta">{p.action === 'revise' ? '修改确认' : '意图确认'} · {p.created_at.slice(0, 10)}</div><p>{p.after.text}</p><span className="record-foot">{p.reason}</span></div><span className="tag pending">待确认</span><ChevronRight size={17}/></button>) : empty('暂时没有待确认事项', '需要你决定的修改和建议，会出现在这里。')}</div> : <div className="record-list">{entries.filter(e => e.kind === planTab).length ? entries.filter(e => e.kind === planTab).map(card) : empty(planTab === 'task' ? '给真正决定的事留个位置' : '灵感可以慢慢生长', planTab === 'task' ? '点击“新增任务”，记录你明确要做的事情。' : '点击“新增想法”，先收藏，不急着行动。')}</div>}
          <details className="past-proposals"><summary>查看已处理的确认事项（{proposals.length - pending.length}）</summary>{proposals.filter(p => p.status !== 'pending').map(p => <div key={p.id}><span className="tag">{p.status === 'accepted' ? '已接受' : '已拒绝'}</span><span>{p.reason}</span><small>{p.created_at.slice(0, 10)}</small></div>)}</details></>}

        {page === 'reports' && <><ScheduledReports/><div className="report-toolbar"><label>查看日期<input type="date" value={reportDay} onChange={e => setReportDay(e.target.value)}/></label><span className="tag">本地事实汇总 · 非 AI 日报</span></div><div className="info-strip"><CircleHelp size={18}/>{report?.notice ?? '正在读取当日记录…'}</div>{report && <><div className="report-grid">{report.groups.map(group => <section className="panel report-group" key={group.category}><div className="panel-header"><h3>{group.label}</h3><span className={group.state === 'unknown' ? 'quiet' : 'recorded'}>{group.state === 'unknown' ? '未记录' : '有记录'}</span></div>{group.records.length ? group.records.map(r => <button className="report-source" key={r.id} onClick={() => openEntry(r.id)}><p>{r.text}</p><span>查看来源记录<ArrowUpRight size={12}/></span></button>) : <p className="unknown">暂无记录，无法判断。</p>}</section>)}</div>{report.uncategorized.length > 0 && <section className="panel report-extra"><h3>未分类的原文</h3>{report.uncategorized.map(card)}</section>}<section className="panel report-extra"><h3>当天任务 <span className="quiet">单独呈现，不视为已发生事实</span></h3>{report.tasks.length ? report.tasks.map(card) : <p className="unknown">没有为这一天记录任务。</p>}</section></>}</>}
        <footer className="page-footer"><Leaf size={13}/><span>记录真实的生活，保留自己的节奏。</span><span className="footer-right">本地优先 · 由你掌控</span></footer>
      </main>
    </div>

    {selected && <Modal title={edit ? '提出更正' : '记录详情'} close={() => setSelected(undefined)} busy={busy}>
      {edit ? <form onSubmit={propose}>{fieldsEditor(edit, setEdit)}<label>修改原因<input required maxLength={1000} value={reason} onChange={e => setReason(e.target.value)}/></label><p className="modal-hint">下一步展示修改前后内容。确认前不会改动记录。</p><div className="modal-actions"><button type="button" className="secondary" onClick={() => setEdit(undefined)}>取消</button><button className="primary" disabled={busy || !edit.text.trim()}>预览修改<ArrowRight size={15}/></button></div></form> : <><div className="detail-meta"><span className="tag">{kinds[selected.record.kind]}</span><span>{selected.record.date}</span><span>{categories[selected.record.category]}</span>{selected.record.kind === 'task' && <span>{statuses[selected.record.status]}</span>}</div><p className="detail-text">{selected.record.text}</p><div className="source-box"><ShieldCheck size={17}/><div>来源：{selected.record.source === 'user_input' ? '用户直接输入' : '用户确认的建议'}<small>保存于 {selected.record.created_at.replace('T', ' ')}<br/>记录编号 {selected.record.id}<br/>修订 {selected.record.version} · 尚未进行 AI 理解</small></div></div><h3 className="history-title">修订历史</h3><div className="version-list">{[...selected.history].reverse().map(r => <details key={r.version}><summary>修订 {r.version} · {r.updated_at.replace('T', ' ')}{r.version === selected.record.version && <span>当前</span>}</summary><div className="quiet">{r.date} · {categories[r.category]} · {r.kind === 'task' ? statuses[r.status] : kinds[r.kind]}</div><p>{r.text}</p></details>)}</div><div className="modal-actions"><button className="secondary" onClick={() => setSelected(undefined)}>关闭</button><button className="primary" onClick={() => setEdit({ text: selected.record.text, date: selected.record.date, category: selected.record.category, status: selected.record.status })}>提出更正<ArrowRight size={15}/></button></div></>}
      {error && <div className="alert error" role="alert">{error}</div>}
    </Modal>}
    {review && <Modal title="确认这次修改" close={() => setReview(undefined)} busy={busy}><p className="modal-hint">{review.reason}。只有点击“确认保存”后才会生效。</p><div className="diff-grid"><div className="diff-before"><h4>修改前{review.before && ` · 修订 ${review.before.version}`}</h4>{review.before ? <FieldPreview value={review.before} categories={categories} showStatus={review.before.kind === 'task'}/> : <p>尚未创建记录</p>}</div><div className="diff-after"><h4>拟保存内容</h4><FieldPreview value={review.after} categories={categories} showStatus={review.before?.kind === 'task' || review.action === 'create_task'}/></div></div><div className="modal-actions"><button className="secondary" disabled={busy} onClick={() => decide(review, 'reject')}>拒绝修改</button><button className="primary" disabled={busy} onClick={() => decide(review, 'accept')}><CheckCheck size={16}/>确认保存</button></div>{error && <div className="alert error" role="alert">{error}</div>}</Modal>}
    {backupOpen && <Modal title="备份与恢复校验" close={() => setBackupOpen(false)} busy={busy}><div className="source-box"><ShieldCheck size={22}/><div>把自己的记录，留一份在安全的地方。<small>备份包含网页维护的档案、记录、修订与可读资料；不包含旧访谈原件、程序或密钥。</small></div></div><div className="backup-choice"><div><h3>导出本地备份</h3><p>导出前自动验证恢复。请将下载的文件保存到独立位置。</p></div><button className="primary" disabled={busy} onClick={() => perform(async () => { await exportBackup(); setNotice('备份已通过恢复校验并开始下载，请确认浏览器下载结果。'); })}><ArrowDownToLine size={16}/>导出备份</button></div><div className="backup-choice"><div><h3>校验已有备份</h3><p>在独立临时目录恢复并核对，不覆盖当前数据。上传限 32 MB，仅发送到本机。</p></div><button className="secondary" disabled={busy} onClick={() => upload.current?.click()}>选择备份文件</button><input hidden ref={upload} type="file" accept=".zip" onChange={e => { const file = e.target.files?.[0]; if (file) perform(async () => { const result = await verifyBackup(file); setNotice(result.message + ` 共 ${result.records} 条记录、${result.events} 个修订事件。`); }); e.target.value = ''; }}/></div><p className="modal-hint">周期自动备份尚未配置。本阶段不提供覆盖当前数据的恢复按钮。</p>{notice && <div className="alert success" role="status">{notice}</div>}{error && <div className="alert error" role="alert">{error}</div>}</Modal>}
  </div>;
}

function FieldPreview({ value, categories, showStatus }: { value: Fields; categories: Record<string, string>; showStatus: boolean }) {
  return <><div className="quiet">{value.date} · {categories[value.category]}{showStatus ? ` · ${statuses[value.status]}` : ''}</div><p>{value.text}</p></>;
}

function Modal({ title, children, close, busy }: { title: string; children: React.ReactNode; close: () => void; busy: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    ref.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = previousOverflow; previous?.focus(); };
  }, []);
  function trap(event: React.KeyboardEvent) {
    if (event.key !== 'Tab') return;
    const elements = ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not([hidden]), select, textarea, summary, [tabindex="0"]');
    if (!elements?.length) return;
    const first = elements[0], last = elements[elements.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
  return <div className="modal-backdrop" onClick={e => { if (e.target === e.currentTarget && !busy) close(); }}><div className="modal" ref={ref} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} onKeyDown={trap}><header><h2>{title}</h2><button aria-label="关闭对话框" disabled={busy} onClick={close}><X size={20}/></button></header>{children}</div></div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
