// Isolated component fixtures. These never enter the application's data directory.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Dashboard } from '../src/Dashboard';
import { SettingsPage } from '../src/SettingsPage';
import { AnalysisPanel } from '../src/AnalysisPanel';
import { ExportPanel } from '../src/ExportPanel';
import { ProfilePanel } from '../src/ProfilePanel';
import { Progress } from '../src/trackingUI';
import { api, mutate } from '../src/api';
import type { DashboardData, Entity, Goal, Settings } from '../src/trackingTypes';

vi.mock('../src/TaskEvents', () => ({TaskEvents: () => <h2>任务动态</h2>}));
vi.mock('../src/api', () => ({ api: vi.fn(), mutate: vi.fn() }));
const apiMock = vi.mocked(api), mutateMock = vi.mocked(mutate);
const day = '2026-10-24';
const stamp = day + 'T12:00:00+08:00';
const goal: Entity<Goal> & { progress: number } = { id: 'goal-1', kind: 'goal', version: 1, created_at: stamp, updated_at: stamp, progress: 20,
  data: { title: '阅读计划', criteria: '读完十章并留下笔记', due: null, mode: 'metric', unit: '章', baseline: 0, target: 10, current: 2, milestones: [] } };
const settings: Settings = { name: '', bio: '', focus: '', order: ['profile','state','year','goals','logs','other','checkins','pending'], hidden: [], task_types: [], model: { enabled: false, base_url: '', model: '', response_format: 'json_schema' } };
function fixture(): DashboardData {
  return { date: day, settings: structuredClone(settings), settings_version: 1, year: { year: 2026, remaining_days: 69, elapsed_percent: 81.1 }, goals: [], tasks: [], logs: [], checkins: [], analyses: [], pending: [], decisions: [] };
}
const callbacks = { record: vi.fn(), newTask: vi.fn(), legacyPending: vi.fn(), settings: vi.fn() };
beforeEach(() => { vi.resetAllMocks(); });

it('keeps confirmation first and moves journal work out of the overview', async () => {
  const data = fixture();
  data.settings.name = '不在总览重复显示的资料';
  apiMock.mockResolvedValue(data);
  const { rerender } = render(<Dashboard ready today={day} {...callbacks}/>);
  const pending = await screen.findByRole('region', { name: '待确认事项' });
  const tasks = screen.getByRole('region', { name: '今日任务' });
  expect(pending.compareDocumentPosition(tasks) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.queryByRole('heading', { name: '当前状态' })).toBeNull();
  expect(screen.queryByText(data.settings.name)).toBeNull();
  expect(screen.queryByRole('heading', { name: '早中晚回顾' })).toBeNull();
  expect(screen.queryByRole('heading', { name: '任务与活动日志' })).toBeNull();
  expect(screen.getByRole('progressbar', { name: '年度时间已过' }).getAttribute('aria-valuenow')).toBe('81.1');
  rerender(<Dashboard view="journal" ready today={day} {...callbacks}/>);
  expect(screen.queryByRole('heading', { name: '早中晚回顾' })).toBeNull();
  expect(screen.getByRole('heading', { name: '任务动态' })).toBeTruthy();
  expect(screen.queryByRole('region', { name: '待确认事项' })).toBeNull();
});

describe('recording and approval workflows', () => {
  it('starts empty and creates a goal only when the form is submitted', async () => {
    const user = userEvent.setup(); const data = fixture();
    apiMock.mockImplementation(async () => structuredClone(data));
    mutateMock.mockImplementation(async (_path, body) => { data.goals = [structuredClone(goal)]; return { entity: { ...goal, data: (body as { data: Goal }).data } }; });
    render(<Dashboard ready today={day} {...callbacks}/>);
    await user.click(await screen.findByRole('button', { name: /建立第一个目标/ }));
    await user.type(screen.getByLabelText('目标名称'), '阅读计划');
    await user.type(screen.getByLabelText('完成标准'), '读完十章并留下笔记');
    await user.type(screen.getByLabelText('起点'), '0');
    await user.type(screen.getByLabelText('目标值'), '10');
    await user.type(screen.getByLabelText('当前值'), '2');
    expect(mutateMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '保存／预览修改' }));
    expect(mutateMock).toHaveBeenCalledWith('/api/goals', expect.objectContaining({ expected_version: 0, data: expect.objectContaining({ title: '阅读计划', current: 2 }) }));
    expect(await screen.findByRole('heading', { name: '阅读计划' })).toBeTruthy();
  });

  it('confirms task assignment without changing historical progress', async () => {
    const user = userEvent.setup(); const data = fixture(); data.goals = [structuredClone(goal)];
    const tracking = { id: 'tracking:task-1', kind: 'tracking', version: 1, created_at: stamp, updated_at: stamp, data: { task_id: 'task-1', goal_id: 'goal-1', tags: [], progress: 20 } };
    data.tasks = [{ ...tracking.data, tracking, record: { id: 'task-1', text: '整理第三章笔记', date: day, category: 'skill', status: 'partial', kind: 'task', version: 1, created_at: stamp, updated_at: stamp, source: 'user_input', processing: 'not_analyzed', previous_version: null } }];
    apiMock.mockImplementation(async () => structuredClone(data));
    mutateMock.mockImplementation(async (path, body) => {
      if (path.includes('/decision')) { data.tasks[0].goal_id = null; return {}; }
      return { change: { id: 'change-1', kind: 'change', version: 1, created_at: stamp, updated_at: stamp, data: { target_id: tracking.id, target_kind: 'tracking', expected_version: 1, before: tracking.data, after: (body as {data: object}).data, reason: '调整任务进度', status: 'pending' } } };
    });
    render(<Dashboard ready today={day} {...callbacks}/>);
    await user.click(await screen.findByRole('button', { name: '调整归属' }));
    expect(screen.queryByLabelText('任务自身进度 %')).toBeNull();
    await user.selectOptions(screen.getByLabelText('主要目标'), '');
    await user.click(screen.getByRole('button', { name: '预览归属修改' }));
    const diff = await screen.findByRole('dialog', { name: '确认这次修改' });
    expect(within(diff).getByText('修改前')).toBeTruthy();
    expect(within(diff).getByText('确认后')).toBeTruthy();
    expect(data.tasks[0].progress).toBe(20);
    expect(mutateMock).toHaveBeenCalledTimes(1);
    await user.click(within(diff).getByRole('button', { name: '确认保存' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(data.tasks[0].goal_id).toBeNull();
    expect(data.tasks[0].progress).toBe(20);
    expect(mutateMock.mock.calls[0][1]).toEqual(expect.objectContaining({data: expect.objectContaining({progress: 20, goal_id: null})}));
    expect(mutateMock).toHaveBeenLastCalledWith('/api/changes/change-1/decision', { decision: 'accept' });
  });

  it('records a morning response without inferring other responses', async () => {
    const user = userEvent.setup(); const data = fixture(); apiMock.mockImplementation(async () => structuredClone(data));
    mutateMock.mockImplementation(async (_path, body) => { const item = { id: 'check-1', kind: 'checkin', version: 1, created_at: stamp, updated_at: stamp, data: (body as {data: DashboardData['checkins'][0]['data']}).data }; data.checkins.push(item); return { entity: item }; });
    render(<Dashboard view="review" ready today={day} {...callbacks}/>);
    await user.click(await screen.findByRole('button', { name: '填写早上回应' }));
    await user.type(screen.getByLabelText('进展与回应'), '先阅读，再整理笔记。');
    await user.click(screen.getByRole('button', { name: '保存／预览修改' }));
    expect(await screen.findByText('先阅读，再整理笔记。')).toBeTruthy();
    expect(data.checkins).toHaveLength(1);
    expect(data.checkins[0].data.slot).toBe('morning');
    expect(mutateMock).toHaveBeenCalledWith('/api/check-ins', expect.objectContaining({ data: expect.objectContaining({ slot: 'morning', goal_id: null }) }));
  });

  it('retains a failed form so the user can retry without losing text', async () => {
    const user = userEvent.setup(); apiMock.mockResolvedValue(fixture()); mutateMock.mockRejectedValue(new Error('保存失败，请重试'));
    render(<Dashboard ready today={day} {...callbacks}/>);
    await user.click(await screen.findByRole('button', { name: '建立第一个目标' }));
    await user.type(screen.getByLabelText('目标名称'), '整理资料');
    await user.type(screen.getByLabelText('完成标准'), '资料已分类');
    await user.click(screen.getByRole('button', { name: '保存／预览修改' }));
    const dialog = await screen.findByRole('dialog', { name: '目标与完成标准' });
    expect(within(dialog).getByRole('alert').textContent).toContain('保存失败');
    expect((screen.getByLabelText('目标名称') as HTMLInputElement).value).toBe('整理资料');
  });
});

it('saves layout immediately without submitting an unfinished profile edit', async () => {
  const user = userEvent.setup();
  const state: any={sections:{user:{data:{name:'',bio:'',focus:''},version:0},ui:{data:{order:settings.order,hidden:[]},version:0},types:{data:{task_types:[]},version:0},models:{data:{connections:[],bindings:{goal:null,schedule:null}},version:0}}};
  apiMock.mockImplementation(async path => {
    if(path==='/api/config/sections')return structuredClone(state);
    if(path==='/api/config/connections/status')return {connections:[]};
    if(path==='/api/plugins')return {plugins:[]};
    if(path==='/api/plugin-data')return {entities:[]};
    if(path==='/api/config/changes')return {changes:[]};
    if(path==='/api/integration-settings')return {enabled:false,scopes:[],tokens:[]};
    if(path==='/api/schedule')return {config:{enabled:false,times:[],scopes:[]}};
    if(path==='/api/profile')return {profile:{personality:'',values:'',preferences:'',boundaries:''},version:0};
    return {healthy:true};
  });
  mutateMock.mockImplementation(async (path, body) => { expect(path).toBe('/api/config/sections/ui'); state.sections.ui={data:(body as any).data,version:1};return {entity:{}}; });
  render(<SettingsPage ready backup={vi.fn()}/>);
  await screen.findByRole('heading',{name:'首页布局'});
  expect(screen.queryByLabelText('展示名称')).toBeNull();
  await user.click(screen.getByRole('checkbox',{name:'目标与任务'}));
  await user.click(screen.getByRole('button',{name:'保存首页布局'}));
  await waitFor(()=>expect(state.sections.ui.data.hidden).toEqual(['goals']));
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(screen.queryByRole('heading',{name:'日程提醒'})).toBeNull();
  expect(state.sections.user.data.name).toBe('');
});

it('invalidates export preview when its selection changes', async () => {
  const user = userEvent.setup(); const data = fixture(); data.goals = [structuredClone(goal)];
  apiMock.mockResolvedValue({ filename: 'progress.md', content: '# 进度回顾\n阅读进度 20%' });
  render(<ExportPanel data={data}/>);
  await user.click(screen.getByRole('button', { name: '生成导出预览' }));
  expect(await screen.findByRole('button', { name: '下载文件' })).toBeTruthy();
  await user.selectOptions(screen.getByLabelText('目标'), 'goal-1');
  expect(screen.queryByRole('button', { name: '下载文件' })).toBeNull();
  expect(apiMock).toHaveBeenCalledTimes(1);
});

it('discards an export response when filters change while it is loading', async () => {
  const user = userEvent.setup(); const data = fixture(); data.goals = [structuredClone(goal)];
  let resolve!: (value: unknown) => void;
  apiMock.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  render(<ExportPanel data={data}/>);
  await user.click(screen.getByRole('button', { name: '生成导出预览' }));
  await user.selectOptions(screen.getByLabelText('目标'), 'goal-1');
  await act(async () => { resolve({ filename: 'all.md', content: '先前筛选范围的结果' }); });
  expect(screen.queryByText('先前筛选范围的结果')).toBeNull();
  expect(screen.queryByRole('button', { name: '下载文件' })).toBeNull();
  apiMock.mockResolvedValueOnce({ filename: 'goal.md', content: '当前目标的结果' });
  await user.click(screen.getByRole('button', { name: '生成导出预览' }));
  expect(await screen.findByText('当前目标的结果')).toBeTruthy();
});

it('sends model input only after selection, preview and explicit confirmation', async () => {
  const user = userEvent.setup(); const data = fixture(); data.goals = [structuredClone(goal)]; const done = vi.fn();
  const log = { id: 'log-1', kind: 'log', version: 1, created_at: stamp, updated_at: stamp, data: { text: '整理了第三章笔记', date: day, goal_id: goal.id } };
  apiMock.mockImplementation(async (path) => path === '/api/activity-logs' ? { entities: [log] } : { input: { goal, tasks: [], tracking: [], logs: [log], sources: { 'goal-1': 1, 'log-1': 1 } }, settings_version: 1, ready: true, model: { ...settings.model, model: 'configured-model', base_url: 'https://service.example/v1' } });
  mutateMock.mockResolvedValue({});
  render(<AnalysisPanel goalId={goal.id} data={data} done={done} onBusy={vi.fn()}/>);
  await user.click(await screen.findByRole('checkbox', { name: /整理了第三章笔记/ }));
  await user.click(screen.getByRole('button', { name: '预览将发送的资料' }));
  expect(await screen.findByText('发送前确认')).toBeTruthy();
  expect(mutateMock).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: '确认发送并分析' }));
  expect(mutateMock).toHaveBeenCalledWith('/api/analyses', expect.objectContaining({ approved: true, task_ids: [], log_ids: ['log-1'], sources: { 'goal-1': 1, 'log-1': 1 } }));
  expect(done).toHaveBeenCalledOnce();
});

it('distinguishes unknown progress from explicitly recorded zero', () => {
  render(<><Progress value={null} label="未知目标"/><Progress value={0} label="未开始目标"/></>);
  expect(screen.getByRole('progressbar', { name: '未知目标' }).getAttribute('aria-valuenow')).toBeNull();
  expect(screen.getByRole('progressbar', { name: '未开始目标' }).getAttribute('aria-valuenow')).toBe('0');
  expect(screen.getByText('尚无法计算')).toBeTruthy();
});

it('keeps a self-description pending until the user confirms its diff', async () => {
  const user = userEvent.setup();
  let stored = { personality: '', values: '', preferences: '', boundaries: '' };
  let proposed = stored;
  apiMock.mockImplementation(async () => ({ profile: { ...stored }, version: 0 }));
  mutateMock.mockImplementation(async (path, body) => {
    if (path.includes('/decision')) { stored = proposed; return {}; }
    proposed = (body as { data: typeof stored }).data;
    return { change: { id: 'profile-change', kind: 'change', version: 1, created_at: stamp, updated_at: stamp,
      data: { target_id: 'profile', target_kind: 'profile', expected_version: 0, before: null, after: proposed, reason: '更新个人档案', status: 'pending' } } };
  });
  render(<ProfilePanel/>);
  await user.type(await screen.findByRole('textbox', { name: '个性与自我描述' }), '喜欢先了解整体');
  await user.click(screen.getByRole('button', { name: '预览档案修改' }));
  const dialog = await screen.findByRole('dialog', { name: '确认个人档案修改' });
  expect(stored.personality).toBe('');
  expect(within(dialog).getByText('喜欢先了解整体')).toBeTruthy();
  await user.click(within(dialog).getByRole('button', { name: '确认保存' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(stored.personality).toBe('喜欢先了解整体');
  expect(stored.values).toBe('');
});
