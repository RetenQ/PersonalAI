import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { X } from 'lucide-react';
import type { Change, Entity } from './trackingTypes';

export function Dialog({ title, children, close, busy = false }: { title: string; children: ReactNode; close: () => void; busy?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(close);
  closeRef.current = close;
  const busyRef = useRef(busy);
  busyRef.current = busy;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    ref.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopImmediatePropagation(); if (!busyRef.current) closeRef.current(); }
      if (e.key === 'Tab') {
        const elements = [...(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled):not([hidden]), select:not(:disabled), textarea:not(:disabled), a[href], summary, [tabindex="0"]') ?? [])].filter(e => e.getClientRects().length > 0);
        if (!elements?.length) return;
        const first = elements[0], last = elements[elements.length - 1];
        if (e.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) { e.preventDefault(); last.focus(); }
        if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', key, true);
    return () => { document.removeEventListener('keydown', key, true); document.body.style.overflow = previousOverflow; previous?.focus(); };
  }, []);
  return <div className="modal-backdrop"><div className="modal tracking-dialog" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}><header><h2>{title}</h2><button disabled={busy} onClick={close} aria-label="关闭窗口"><X size={20}/></button></header>{children}</div></div>;
}

export function Progress({ value, label = '已确认进度', estimated = false }: { value: number | null; label?: string; estimated?: boolean }) {
  return <div className={'progress-block' + (estimated ? ' estimated' : '')}><div><span>{label}</span><strong>{value === null ? '尚无法计算' : `${value}%`}</strong></div><div className="progress-track" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value ?? undefined} aria-valuetext={value === null ? '未知' : `${value}%`}><span style={{ width: `${value ?? 0}%` }}/></div></div>;
}

const labels: Record<string, string> = { personality: '个性与自我描述', values: '重视的事情', preferences: '协作与生活偏好', boundaries: '个人边界', goal: '目标', tasks: '任务原文', tracking: '追踪信息', logs: '活动日志', sources: '依据版本', version: '修订版本', kind: '内容类型', created_at: '首次保存时间', updated_at: '最近保存时间', category: '记录类别', status: '状态', source: '记录来源', processing: '理解状态', previous_version: '上一修订', confidence: '置信度', assessment: '分析内容', low: '估计下限', high: '估计上限', explanation: '分析说明', source_ids: '依据编号', contributions: '贡献判断', missing: '缺失信息', suggestions: '建议', analysis_id: '分析编号', target_id: '修改对象', target_kind: '对象类型', expected_version: '依据版本', before: '修改前', after: '修改后', reason: '理由', title: '名称', criteria: '完成标准', due: '目标日期', mode: '计算方式', unit: '单位', baseline: '起点', target: '目标值', current: '当前值', milestones: '里程碑', weight: '权重', progress: '进度', task_id: '任务', goal_id: '目标', tags: '类型', date: '日期', slot: '时段', text: '内容', result: '结果', obstacle: '阻碍', completed: '已完成事项', response: '回应', energy: '精力', mood: '心情', note: '备注', name: '名称', bio: '简介', focus: '近期关注', order: '模块顺序', hidden: '隐藏模块', task_types: '任务类型', model: '模型', enabled: '已启用', base_url: '服务地址', response_format: '输出格式', active: '使用中', id: '编号' };
const values: Record<string, string> = { metric: '数值指标', milestones: '里程碑', morning: '早上', noon: '中午', evening: '晚上', profile: '个人情况', year: '年度时间', goals: '目标与任务', logs: '任务与目标动态', other: '其他已完成事项', checkins: '早中晚回顾', pending: '待确认事项' };
function display(value: unknown, names: Record<string, string>): ReactNode {
  if (value === null || value === '') return '未填写';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (Array.isArray(value)) return value.length ? <ul>{value.map((v, i) => <li key={i}>{display(v, names)}</li>)}</ul> : '无';
  if (typeof value === 'object') return <dl className="data-list">{Object.entries(value as object).map(([k, v]) => <div key={k}><dt>{labels[k] ?? k}</dt><dd>{display(v, names)}</dd></div>)}</dl>;
  return names[String(value)] ?? values[String(value)] ?? String(value);
}
export function DataView({ data, names = {} }: { data: unknown; names?: Record<string, string> }) { return <div className="data-view">{display(data, names)}</div>; }

export function ChangeReview({ change, names, busy, decide }: { change: Entity<Change>; names: Record<string, string>; busy: boolean; decide: (decision: 'accept' | 'reject') => void }) {
  const keys = Object.keys(change.data.after).filter(k => JSON.stringify(change.data.before?.[k]) !== JSON.stringify(change.data.after[k]));
  return <><p className="modal-hint">{change.data.reason}。确认后保存新修订，旧版保留。</p><div className="diff-grid"><div className="diff-before"><h3>修改前</h3><DataView names={names} data={Object.fromEntries(keys.map(k => [k, change.data.before?.[k] ?? null]))}/></div><div className="diff-after"><h3>确认后</h3><DataView names={names} data={Object.fromEntries(keys.map(k => [k, change.data.after[k]]))}/></div></div><div className="modal-actions"><button className="secondary" disabled={busy} onClick={() => decide('reject')}>拒绝修改</button><button className="primary" disabled={busy} onClick={() => decide('accept')}>确认保存</button></div></>;
}

export function download(name: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type: name.endsWith('.json') ? 'application/json;charset=utf-8' : 'text/markdown;charset=utf-8' }));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
