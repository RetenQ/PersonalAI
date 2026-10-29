import { beforeEach, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { DailyReviewPage, previousDay, reportsForDays, summaryText } from '../src/DailyReviewPage';
import { api } from '../src/api';

vi.mock('../src/Dashboard', () => ({ Dashboard: () => <div>早中晚回顾</div> }));
vi.mock('../src/api', () => ({ api: vi.fn() }));
const mock = vi.mocked(api);
beforeEach(() => vi.resetAllMocks());

it('uses calendar dates across leap days and years', () => {
  expect(previousDay('2024-03-01')).toBe('2024-02-29');
  expect(previousDay('2026-01-01')).toBe('2025-12-31');
});

it('summarizes recorded facts without treating planned tasks as completed', () => {
  expect(summaryText({ day: '2026-10-28', notes: [], logs: [], checkins: [], tasks: [{ text: '计划阅读' }] as any })).toBe('当天暂无记录。');
});

it('refreshes confirmed task events when a task is changed from this page', async () => {
  let completed = false;
  mock.mockImplementation(async path => {
    if (path.startsWith('/api/task-events')) return {items: completed && path.endsWith('28') ? [{id:'t:v2', title:'阅读', action:'状态：待进行 → 已完成', version:2}] : []};
    if (path.startsWith('/api/scheduled-reports')) return {reports:[], next_offset:null};
    if (path.startsWith('/api/dashboard')) return {logs:[], checkins:[]};
    return {groups:[], uncategorized:[], tasks:[]};
  });
  const props = {day:'2026-10-28', setDay:vi.fn(), ready:true, record:vi.fn()};
  const view = render(<DailyReviewPage {...props} dataRevision={0}/>);
  await screen.findByRole('region', {name:'当日回顾'});
  completed = true;
  view.rerender(<DailyReviewPage {...props} dataRevision={1}/>);
  expect(await screen.findByText('阅读：状态：待进行 → 已完成。')).toBeTruthy();
  expect(within(screen.getByRole('region', {name:'前一天回顾'})).getByText('当天暂无记录。')).toBeTruthy();
});

it('finds reports across pages and retains the latest run per day', async () => {
  const report = (id: string, day: string) => ({run: {id, data: {window_end: day}}});
  mock.mockResolvedValueOnce({reports: [report('new', '2026-10-28')], next_offset: 200})
    .mockResolvedValueOnce({reports: [report('old', '2026-10-28'), report('previous', '2026-10-27')], next_offset: null});
  const result = await reportsForDays(['2026-10-28', '2026-10-27'], new AbortController().signal);
  expect(result['2026-10-28'].run.id).toBe('new');
  expect(result['2026-10-27'].run.id).toBe('previous');
  expect(mock).toHaveBeenCalledTimes(2);
});

it('shows both days with explicit missing analysis and makes only read requests', async () => {
  mock.mockImplementation(async path => path.startsWith('/api/scheduled-reports') ? {reports: [], next_offset: null} : path.startsWith('/api/dashboard') ? {logs: [], checkins: []} : {groups: [{records: [{id: path, text: path.endsWith('28') ? '今天读了两章' : '昨天整理笔记'}]}], uncategorized: [], tasks: []});
  render(<DailyReviewPage day="2026-10-28" setDay={vi.fn()} ready record={vi.fn()}/>);
  const today = await screen.findByRole('region', {name: '当日回顾'});
  expect(within(today).getAllByText('今天读了两章').length).toBeGreaterThan(0);
  expect(within(today).getByText('尚未生成分析。')).toBeTruthy();
  expect(within(screen.getByRole('region', {name: '前一天回顾'})).getAllByText('昨天整理笔记').length).toBeGreaterThan(0);
  expect(mock.mock.calls.every(([, options]) => !options?.method || options.method === 'GET')).toBe(true);
});

it('keeps factual review visible when analysis retrieval fails', async () => {
  mock.mockImplementation(async path => {
    if (path.startsWith('/api/scheduled-reports')) throw new Error('连接中断');
    return path.startsWith('/api/dashboard') ? {logs: [], checkins: []} : {groups: [], uncategorized: [], tasks: []};
  });
  render(<DailyReviewPage day="2026-10-28" setDay={vi.fn()} ready record={vi.fn()}/>);
  const today = await screen.findByRole('region', {name: '当日回顾'});
  expect(within(today).getByText('当天暂无记录。')).toBeTruthy();
  expect(within(today).getByRole('alert').textContent).toContain('连接中断');
});
