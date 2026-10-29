import type { RecordStatus } from './api';
import type { Task } from './trackingTypes';

export const taskStatuses: Record<RecordStatus, string> = {open: '待进行', partial: '部分完成', done: '已完成'};
// A task's date is its planned date, not the date its status last changed.
export const tasksForDay = (tasks: Task[], day: string) => tasks.filter(t => t.record.date === day);
export const currentTasks = (tasks: Task[], goalId: string | null) => tasks.filter(t => t.goal_id === goalId && t.record.status !== 'done');
