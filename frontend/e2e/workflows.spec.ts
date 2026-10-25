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
  await page.goto('/');
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
  await page.getByRole('button', { name: '保存正式任务', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('明确创建');
  await navigate(page, '总览');
  const taskRow = page.locator('.task-row').filter({ hasText: task });
  await taskRow.getByRole('button', { name: '调整追踪' }).click();
  await dialog.getByLabel('主要目标').selectOption({ label: goal });
  await dialog.getByLabel('任务自身进度 %').fill('25');
  await dialog.getByRole('button', { name: '预览追踪修改' }).click();
  await dialog.getByRole('button', { name: '确认保存' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(goalCard.getByRole('button', { name: task, exact: true })).toBeVisible();

  await page.getByRole('button', { name: '添加日志', exact: true }).click();
  await dialog.getByLabel('关联任务').selectOption({ label: task });
  await dialog.getByLabel('发生了什么').fill(log);
  await dialog.getByLabel('结果', { exact: true }).fill('记录流程已走通，继续检查导出。');
  await dialog.getByRole('button', { name: '保存／预览修改' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('.timeline-entry').filter({ hasText: log })).toContainText(task);
  await expect(goalCard.getByRole('progressbar', { name: '已确认进度', exact: true })).toHaveAttribute('aria-valuenow', '25');

  await page.getByRole('button', { name: '填写早上回应', exact: true }).click();
  await dialog.getByLabel('关联目标（可选）').selectOption({ label: goal });
  await dialog.getByLabel('进展与回应').fill(`${suffix}：已打开页面并完成记录检查。`);
  await dialog.getByRole('button', { name: '保存／预览修改' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('.checkin-card').filter({ has: page.getByRole('heading', { name: '中午', exact: true }) })).toContainText('未记录');
  await page.reload();
  await expect(goalCard).toBeVisible();
  await expect(page.getByText(`${suffix}：已打开页面并完成记录检查。`, { exact: true })).toBeVisible();

  await page.getByRole('button', { name: '导出回顾', exact: true }).click();
  await dialog.getByLabel('目标').selectOption({ label: goal });
  await dialog.getByRole('button', { name: '生成导出预览' }).click();
  await expect(dialog.locator('pre')).toContainText(log);
  await fits(page);
  const markdown = page.waitForEvent('download');
  await dialog.getByRole('button', { name: '下载文件' }).click();
  const markdownFile = await markdown;
  expect(await readFile((await markdownFile.path())!, 'utf8')).toContain(log);
  await dialog.getByLabel('格式').selectOption('json');
  await expect(dialog.getByRole('button', { name: '下载文件' })).toHaveCount(0);
  await dialog.getByRole('button', { name: '生成导出预览' }).click();
  const json = page.waitForEvent('download');
  await dialog.getByRole('button', { name: '下载文件' }).click();
  const jsonContent = await readFile((await (await json).path())!, 'utf8');
  expect(JSON.parse(jsonContent)).toBeTruthy();
  expect(jsonContent).toContain(log);
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);

  // Actual screenshots and layout bounds on every page at each configured width.
  for (const name of ['总览', '记录', '任务与想法', '历史', '每日回顾', '设置']) {
    await navigate(page, name);
    if (name === '设置') await expect(page.getByLabel('展示名称')).toBeVisible();
    if (name === '每日回顾') await expect(page.locator('.report-grid')).toBeVisible();
    if (name === '总览') await expect(goalCard).toBeVisible();
    await expect(page.locator('.loading')).toHaveCount(0);
    await fits(page);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: info.outputPath(`${name}-viewport.png`) });
    await page.screenshot({ path: info.outputPath(`${name}.png`), fullPage: true, scale: 'css' });
  }
  await page.getByLabel('展示名称').fill(`PersonalAI · ${suffix}`);
  await page.getByRole('button', { name: '保存展示资料' }).click();
  await dialog.getByRole('button', { name: '确认保存' }).click();
  await expect(dialog).toHaveCount(0);
  await page.getByRole('textbox', { name: '近期关注', exact: true }).fill(`完成 ${suffix} 的浏览器验收`);
  await page.getByRole('button', { name: '保存展示资料' }).click();
  await dialog.getByRole('button', { name: '确认保存' }).click();
  await expect(dialog).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('heading', { name: `PersonalAI · ${suffix}`, exact: true })).toBeVisible();
  // Downloads are inspected and uploaded back only to the isolated local service.
  await navigate(page, '设置');
  const profilePanel = page.getByRole('region', { name: '个性与协作偏好', exact: true });
  const description = `先核对 ${suffix} 的页面操作，再检查文件内容。`;
  await profilePanel.getByRole('textbox', { name: '个性与自我描述', exact: true }).fill(description);
  await profilePanel.getByRole('button', { name: '预览档案修改' }).click();
  await expect(dialog).toHaveAccessibleName('确认个人档案修改');
  expect((await (await page.request.get('/api/profile')).json()).profile.personality).not.toBe(description);
  await dialog.getByRole('button', { name: '确认保存' }).click();
  await expect(dialog).toHaveCount(0);
  const filesPanel = page.getByRole('region', { name: '用户资料文件', exact: true });
  await filesPanel.getByRole('button', { name: '重新整理资料' }).click();
  await expect(filesPanel.getByRole('status')).toContainText('已整理至事件版本');
  const files = await (await page.request.get('/api/user-files')).json();
  expect(files.healthy).toBe(true);
  expect(files.directory).toContain('browser-e2e');
  expect(await readFile(join(files.directory, 'profile', 'PROFILE.md'), 'utf8')).toContain(description);
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
