import { beforeEach, expect, it, vi } from 'vitest';
import { render, screen, within, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SchedulePanel } from '../src/SchedulePanel';
import { ScheduledReports } from '../src/ScheduledReports';
import { api, mutate } from '../src/api';

vi.mock('../src/api', () => ({ api: vi.fn(), mutate: vi.fn() }));
const apiMock = vi.mocked(api), mutateMock = vi.mocked(mutate);
const initial = { config: { enabled: false, times: [], scopes: [] }, version: 0, authorized: false, model_ready: true, active: false, leader: true, next_at: null, error: '', notice: '服务运行时自动生成。' };
beforeEach(() => vi.resetAllMocks());

it('requires a scope preview and separate confirmation before enabling recurring disclosure', async () => {
  const user = userEvent.setup();
  apiMock.mockImplementation(async (path, init) => path === '/api/schedule' ? initial : ({ approval_token: 'preview', before: initial.config,
    after: JSON.parse(init!.body as string).data, input: { items: [] }, model: { model: 'example', base_url: 'https://example.test' }, notice: '之后所选范围内的新记录也会自动发送。' }));
  mutateMock.mockResolvedValue({});
  render(<SchedulePanel modelRevision={0}/>);
  await user.click(await screen.findByLabelText('请求启用定时分析'));
  await user.click(screen.getByRole('button', { name: '添加生成时刻' }));
  fireEvent.change(screen.getByLabelText('生成时刻 1'), { target: { value: '12:30' } });
  await user.click(screen.getByLabelText('日常原文'));
  await user.click(screen.getByRole('button', { name: '预览定时设置与数据范围' }));
  const dialog = await screen.findByRole('dialog', { name: '确认自动分析范围' });
  expect(mutateMock).not.toHaveBeenCalled();
  expect(within(dialog).getByText('之后所选范围内的新记录也会自动发送。')).toBeTruthy();
  await user.click(within(dialog).getByRole('button', { name: '确认范围并保存' }));
  expect(mutateMock).toHaveBeenCalledWith('/api/schedule/confirm', { approval_token: 'preview', approved: true });
});

it('cancelling the preview does not enable scheduling', async () => {
  const user = userEvent.setup();
  apiMock.mockImplementation(async path => path === '/api/schedule' ? initial : { approval_token: 'p', before: initial.config, after: initial.config, input: {}, model: {}, notice: '仅预览' });
  render(<SchedulePanel modelRevision={0}/>);
  await user.click(await screen.findByRole('button', { name: '预览定时设置与数据范围' }));
  await user.click(await screen.findByRole('button', { name: '取消' }));
  expect(mutateMock).not.toHaveBeenCalled();
});

it('keeps settings on save failure and blocks activation without a ready model', async () => {
  const user = userEvent.setup();
  apiMock.mockImplementation(async path => path === '/api/schedule' ? { ...initial, model_ready: false } : { approval_token: 'p', before: initial.config, after: { ...initial.config, enabled: true }, input: {}, model: {}, notice: '仅预览' });
  render(<SchedulePanel modelRevision={0}/>);
  await user.click(await screen.findByRole('button', { name: '预览定时设置与数据范围' }));
  expect((await screen.findByRole('button', { name: '确认范围并保存' }) as HTMLButtonElement).disabled).toBe(true);
  expect(mutateMock).not.toHaveBeenCalled();
});

it('pause is an explicit local operation with no automatic run', async () => {
  const user = userEvent.setup();
  apiMock.mockResolvedValue({ ...initial, active: true, config: { ...initial.config, enabled: true } });
  mutateMock.mockResolvedValue({});
  render(<SchedulePanel modelRevision={1}/>);
  await user.click(await screen.findByRole('button', { name: '暂停定时分析' }));
  await waitFor(() => expect(mutateMock).toHaveBeenCalledWith('/api/schedule/pause', {}));
  expect(mutateMock).toHaveBeenCalledTimes(1);
});

it('shows analysis separately from facts and retrieves the cited revision', async () => {
  const user = userEvent.setup();
  const report = { run: { id: 'run-1', data: { status: 'succeeded', message: '建议未执行', scheduled_at: '2026-10-25T09:00:00+08:00', started_at: '2026-10-25T09:01:00+08:00', finished_at: '2026-10-25T09:02:00+08:00', model: 'test', window_start: '2026-10-19', window_end: '2026-10-25', sources: { 'record-1': 1 }, source_labels: { 'record-1': '阅读记录' }, source_kinds: { 'record-1': 'note' }, assessment: { facts: [{ text: '记录了阅读。', source_ids: ['record-1'] }], reflection: [], issues: [], suggestions: [], next_steps: [], long_term: [], missing: ['睡眠未记录'] } } }, stale: true };
  apiMock.mockImplementation(async path => path.startsWith('/api/scheduled-reports?') ? { reports: [report], total: 1 } : path === '/api/records/record-1' ? { history: [{ version: 1, text: '引用的旧原文' }, { version: 2, text: '后来的更正' }] } : report);
  render(<ScheduledReports/>);
  await user.click(await screen.findByRole('button', { name: /已生成/ }));
  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getByText(/依据已变化/)).toBeTruthy();
  await user.click(within(dialog).getByRole('button', { name: /查看依据/ }));
  expect(await within(dialog).findByText('引用的旧原文')).toBeTruthy();
  expect(within(dialog).queryByText('后来的更正')).toBeNull();
  expect(within(dialog).getByRole('link', { name: '下载分析 JSON' }).getAttribute('href')).toContain('format=json');
});
