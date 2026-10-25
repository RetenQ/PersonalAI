import { test, expect } from '@playwright/test';

test('定时设置预览、取消、保存关闭状态与报告入口', async ({ page }, info) => {
  await page.goto('/');
  const nav = page.getByRole('navigation', { name: '主要导航' });
  await nav.getByRole('button', { name: '设置', exact: true }).click();
  const panel = page.getByRole('region', { name: '定时分析与建议' });
  await expect(panel.getByRole('button', { name: '预览定时设置与数据范围' })).toBeVisible();
  while (await panel.getByRole('button', { name: /移除生成时刻/ }).count()) {
    await panel.getByRole('button', { name: /移除生成时刻/ }).first().click();
  }
  await panel.getByRole('button', { name: '添加生成时刻' }).click();
  await panel.getByLabel('生成时刻 1', { exact: true }).fill('09:30');
  await panel.getByRole('button', { name: '添加生成时刻' }).click();
  await panel.getByLabel('生成时刻 2', { exact: true }).fill('20:30');
  await panel.getByLabel('日常原文', { exact: true }).check();
  await panel.getByRole('button', { name: '预览定时设置与数据范围' }).click();
  const dialog = page.getByRole('dialog', { name: '确认自动分析范围' });
  await expect(dialog).toContainText('包括以后新增的记录');
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  await panel.getByRole('button', { name: '预览定时设置与数据范围' }).click();
  await dialog.getByRole('button', { name: '确认范围并保存' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(panel.getByRole('status')).toContainText('保持关闭');
  await page.reload();
  await nav.getByRole('button', { name: '设置', exact: true }).click();
  await expect(panel.getByLabel('生成时刻 1', { exact: true })).toHaveValue('09:30');
  await expect(panel.getByLabel('请求启用定时分析')).not.toBeChecked();
  await expect(panel.getByRole('button', { name: '按已授权范围立即生成' })).toBeDisabled();
  await panel.scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => innerWidth)).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: info.outputPath('schedule-settings.png') });
  await nav.getByRole('button', { name: '每日回顾', exact: true }).click();
  const reports = page.getByRole('region', { name: 'AI 定时分析', exact: true });
  await expect(reports).toContainText('尚无定时分析');
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect((await (await page.request.get('/api/scheduled-reports/feed')).json()).items).toEqual([]);
});
