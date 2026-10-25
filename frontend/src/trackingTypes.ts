import type { Entry } from './api';

export interface Entity<T> { id: string; kind: string; version: number; created_at: string; updated_at: string; data: T }
export interface Milestone { title: string; weight: number; progress: number | null }
export interface Goal { title: string; criteria: string; due: string | null; mode: 'metric' | 'milestones'; unit: string; baseline: number | null; target: number | null; current: number | null; milestones: Milestone[] }
export interface Tracking { task_id: string; goal_id: string | null; tags: string[]; progress: number | null }
export interface Task extends Tracking { record: Entry; tracking: Entity<Tracking> | null }
export type Slot = 'morning' | 'noon' | 'evening';
export interface Activity { date: string; slot: Slot | null; task_id: string | null; goal_id: string | null; text: string; result: string; obstacle: string; completed: boolean }
export interface CheckIn { date: string; slot: Slot; goal_id: string | null; response: string; obstacle: string }
export interface CurrentState { date: string; energy: string; mood: string; obstacle: string; note: string }
export interface ModelConfig { enabled: boolean; base_url: string; model: string; response_format: 'json_schema' | 'json_object' }
export interface Settings { name: string; bio: string; focus: string; order: string[]; hidden: string[]; task_types: { id: string; name: string; active: boolean }[]; model: ModelConfig }
export interface Assessment { low: number | null; high: number | null; confidence: string; explanation: string; source_ids: string[]; contributions: { task_id: string; relevance: string; reason: string; source_ids: string[] }[]; missing: string[]; suggestions: string[] }
export interface Analysis { goal_id: string; model: string; base_url: string; sources: Record<string, number>; assessment: Assessment }
export interface Change { target_id: string; target_kind: string; expected_version: number; before: Record<string, unknown> | null; after: Record<string, unknown>; reason: string; status: string }
export interface Suggestion { text: string; analysis_id: string; goal_id: string; status: string }
export type Pending = Entity<Change> & { kind: 'change' } | Entity<Suggestion> & { kind: 'suggestion' };
export interface DashboardData {
  config_pending?: number;
  user_files?: import('./UserFilesPanel').UserFilesStatus;
  date: string; settings: Settings; settings_version: number;
  year: { year: number; remaining_days: number; elapsed_percent: number };
  goals: (Entity<Goal> & { progress: number | null })[]; tasks: Task[]; logs: Entity<Activity>[];
  checkins: Entity<CheckIn>[]; states: Entity<CurrentState>[];
  analyses: (Entity<Analysis> & { stale: boolean })[]; pending: Pending[]; decisions: Pending[];
}
export const moduleNames: Record<string, string> = { profile: '个人情况', state: '当前状态', year: '年度时间', goals: '目标与任务', logs: '任务日志', other: '其他已完成事项', checkins: '早中晚回顾', pending: '待确认事项' };
export const slots: Record<Slot, string> = { morning: '早上', noon: '中午', evening: '晚上' };
