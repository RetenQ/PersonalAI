import { test, expect, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';

async function navigate(page: Page, name: string) {
  await page.getByRole('navigation', { name: '主要导航' }).getByRole('button', { name, exact: true }).click();
}

async function fits(page: Page) {
  expect(await page.evaluate(() => innerWidth)).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
  const overflow = await page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    return [...document.querySelectorAll<HTMLElement>('body *')].filter(e => {
      const r = e.getBoundingClientRect();
      return r.width && r.height && !e.closest('.sr-only') && (r.right > width + 1 || r.left < -1);
    }).slice(0, 12).map(e => `${e.tagName}.${e.className}: ${Math.round(e.getBoundingClientRect().right)}`);
  });
  expect(overflow, 'Visible content must fit the viewport').toEqual([]);
  await expect(page.getByRole('alert')).toHaveCount(0);
}

test('真实服务上的记录、确认、回顾、导出与响应式布局', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  const suffix = info.project.name;
  const goal = `PersonalAI 浏览器验收 · ${suffix}`;
  const task = `检查 ${suffix} 窗口的记录与导出流程`;
  const log = `正在执行 ${suffix} 浏览器交互验收`;
  await page.goto('/'); await page.getByRole('navigation',{name:'主要导航'}).getByRole('button',{name:'总览',exact:true}).click();
  await expect(page.getByRole('heading', { name: '目标与任务', exact: true })).toBeVisible();
  await fits(page);

  // Create a goal with no invented current progress.
  await page.getByRole('button', { name: '建立目标', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(page.locator('body')).toHaveCSS('overflow', 'hidden');
  await expect(dialog).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(dialog.getByRole('button', { name: '保存／预览修改' })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(dialog.getByRole('button', { name: '关闭窗口' })).toBeFocused();
  await dialog.getByLabel('目标名称').fill(goal);
  await dialog.getByLabel('完成标准').fill('逐项验证本地记录、修改确认、回应和下载，并保留截图。');
  await dialog.getByLabel('起点', { exact: true }).fill('0');
  await dialog.getByLabel('目标值', { exact: true }).fill('4');
  await fits(page);
  await dialog.getByRole('button', { name: '保存／预览修改' }).click();
  await expect(dialog).toHaveCount(0);
  const goalCard = page.locator('.goal-card').filter({ has: page.getByRole('heading', { name: goal, exact: true }) });
  await expect(goalCard.getByRole('progressbar', { name: '已确认进度', exact: true })).toHaveAttribute('aria-valuetext', '未知');

  // A rejected correction cannot change the confirmed value.
  await goalCard.getByRole('button', { name: '修改目标／进度' }).click();
  await dialog.getByLabel('当前值', { exact: true }).fill('1');
  await dialog.getByRole('button', { name: '保存／预览修改' }).click();
  await expect(dialog.getByText('修改前', { exact: true })).toBeVisible();
  await expect(goalCard.getByRole('progressbar', { name: '已确认进度', exact: true })).toHaveAttribute('aria-valuetext', '未知');
  await dialog.getByRole('button', { name: '拒绝修改' }).click();
  await expect(dialog).toHaveCount(0);
  await goalCard.getByRole('button', { name: '修改目标／进度' }).click();
  await dialog.getByLabel('当前值', { exact: true }).fill('1');
  await dialog.getByRole('button', { name: '保存／预览修改' }).click();
  await dialog.getByRole('button', { name: '确认保存' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(goalCard.getByRole('progressbar', { name: '已确认进度', exact: true })).toHaveAttribute('aria-valuenow', '25');

  await goalCard.getByText('目标详情与分析', { exact: true }).click();
  await goalCard.getByRole('button', { name: '目标来源与历史' }).click();
  await expect(dialog).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(dialog.getByRole('button', { name: '关闭窗口' })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(dialog.locator('summary').first()).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);

  await goalCard.getByRole('button', { name: '选择资料并分析' }).click();
  await dialog.getByRole('button', { name: '预览将发送的资料' }).click();
  await expect(dialog.getByRole('button', { name: '确认发送并分析' })).toBeDisabled();
  await expect(dialog).toContainText('请先在设置中保存模型配置与密钥');
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);

  await page.getByRole('button', { name: '新增任务', exact: true }).click();
  await page.getByRole('textbox', { name: '记录内容', exact: true }).fill(task);
  await page.getByRole('button', { name: '保存任务', exact: true }).click();
  await expect(page.getByRole('status').filter({hasText:'明确创建'})).toBeVisible();
  await page.getByText('历史查询', { exact: true }).click();
  await page.getByRole('textbox', { name: '搜索所有内容' }).fill(task);
  await expect(page.locator('.journal-history .record-card').filter({ hasText: task })).toBeVisible();
  await navigate(page, '总览');
  const taskRow = page.locator('.task-row').filter({ hasText: task });
  await taskRow.getByRole('button', { name: '调整归属' }).click();
  await dialog.getByLabel('主要目标').selectOption({ label: goal });
  await expect(dialog.getByLabel('任务自身进度 %')).toHaveCount(0);
  await dialog.getByRole('button', { name: '预览归属修改' }).click();
  await dialog.getByRole('button', { name: '确认保存' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(goalCard.getByRole('button', { name: task, exact: true })).toBeVisible();

  await navigate(page, '日志与任务');
  await expect(page.getByRole('button', { name: '添加日志', exact: true })).toHaveCount(0);
  await expect(page.locator('.timeline-entry').filter({ hasText: task }).filter({hasText:'创建任务'})).toContainText('创建任务');
  await navigate(page, '总览');
  await expect(goalCard.getByRole('progressbar', { name: '已确认进度', exact: true })).toHaveAttribute('aria-valuenow', '25');
  await navigate(page, '日志与任务');

  await navigate(page, '每日回顾');
  await page.getByRole('button', { name: '填写早上回应', exact: true }).click();
  await dialog.getByLabel('关联目标（可选）').selectOption({ label: goal });
  await dialog.getByLabel('进展与回应').fill(`${suffix}：已打开页面并完成记录检查。`);
  await dialog.getByRole('button', { name: '保存／预览修改' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('.checkin-card').filter({ has: page.getByRole('heading', { name: '中午', exact: true }) })).toContainText('未记录');
  await page.reload();
  await navigate(page, '总览');
  await expect(goalCard).toBeVisible();
  await navigate(page, '每日回顾');
  await expect(page.locator('.checkin-card').getByText(`${suffix}：已打开页面并完成记录检查。`, { exact: true })).toBeVisible();
  await navigate(page, '日志与任务');

  await page.getByRole('button', { name: '导出回顾', exact: true }).click();
  await dialog.getByLabel('目标').selectOption({ label: goal });
  await dialog.getByRole('button', { name: '生成导出预览' }).click();
  await expect(dialog.locator('pre')).toContainText(task);
  await fits(page);
  const markdown = page.waitForEvent('download');
  await dialog.getByRole('button', { name: '下载文件' }).click();
  const markdownFile = await markdown;
  expect(await readFile((await markdownFile.path())!, 'utf8')).toContain(task);
  await dialog.getByLabel('格式').selectOption('json');
  await expect(dialog.getByRole('button', { name: '下载文件' })).toHaveCount(0);
  await dialog.getByRole('button', { name: '生成导出预览' }).click();
  const json = page.waitForEvent('download');
  await dialog.getByRole('button', { name: '下载文件' }).click();
  const jsonContent = await readFile((await (await json).path())!, 'utf8');
  expect(JSON.parse(jsonContent)).toBeTruthy();
  expect(jsonContent).toContain(task);
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);

  // Actual screenshots and layout bounds on every page at each configured width.
  for (const name of ['总览', '日志与任务', '每日回顾', '设置']) {
    await navigate(page, name);
    if (name === '设置') await expect(page.getByRole('heading', {name:'首页布局'})).toBeVisible();
    if (name === '每日回顾') await expect(page.locator('.daily-review-grid')).toBeVisible();
    if (name === '总览') await expect(goalCard).toBeVisible();
    await expect(page.locator('.loading')).toHaveCount(0);
    await fits(page);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: info.outputPath(`${name}-viewport.png`) });
    await page.screenshot({ path: info.outputPath(`${name}.png`), fullPage: true, scale: 'css' });
  }
  await expect(page.getByLabel('展示名称')).toHaveCount(0);
  await expect(page.getByRole('heading', {name:'日程提醒'})).toHaveCount(0);
  const filesPanel = page.getByRole('region', { name: '用户资料文件', exact: true });
  await filesPanel.getByRole('button', { name: '重新整理资料' }).click();
  await expect(filesPanel.getByRole('status')).toContainText('已整理至事件版本');
  const files = await (await page.request.get('/api/user-files')).json();
  expect(files.healthy).toBe(true);
  expect(files.directory).toContain('browser-e2e');
  await fits(page);
  await page.locator('.settings-page').getByRole('button', { name: '备份与恢复校验', exact: true }).click();
  const backup = page.waitForEvent('download');
  await dialog.getByRole('button', { name: '导出备份', exact: true }).click();
  const backupPath = (await (await backup).path())!;
  const chooser = page.waitForEvent('filechooser');
  await dialog.getByRole('button', { name: '选择备份文件', exact: true }).click();
  await (await chooser).setFiles({ name: 'backup.zip', mimeType: 'application/zip', buffer: await readFile(backupPath) });
  await expect(dialog.getByRole('status')).toContainText('个修订事件');
  await fits(page);
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  expect(errors).toEqual([]);
});
