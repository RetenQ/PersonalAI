import { test, expect } from '@playwright/test';

test('触控导航、短屏表单滚动与旋转后保留输入', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '目标与任务', exact: true })).toBeVisible();
  expect(await page.evaluate(() => matchMedia('(pointer: coarse)').matches)).toBe(true);
  // Windows WebKit reports maxTouchPoints=0 even when touch emulation works.
  // Check delivered touch events instead of relying on the reported hardware.
  await page.evaluate(() => {
    document.addEventListener('touchstart', () => {
      document.documentElement.dataset.touchCount = String(Number(document.documentElement.dataset.touchCount ?? 0) + 1);
    });
  });

  // Use touch events, including controls below the fold, instead of mouse clicks.
  for (const name of ['记录', '任务与想法', '历史', '每日回顾', '设置', '总览']) {
    await page.getByRole('navigation', { name: '主要导航' }).getByRole('button', { name, exact: true }).tap();
    await expect(page.locator('.loading')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
  expect(await page.evaluate(() => Number(document.documentElement.dataset.touchCount))).toBeGreaterThanOrEqual(6);

  await page.getByRole('button', { name: '建立目标', exact: true }).tap();
  const dialog = page.getByRole('dialog');
  const title = `旋转与触控检查 · ${info.project.name}`;
  await dialog.getByLabel('目标名称').tap();
  await dialog.getByLabel('目标名称').fill(title);
  await dialog.getByLabel('完成标准').fill('旋转后保留输入，触控保存可达。');
  await dialog.getByLabel('起点', { exact: true }).fill('0');
  await dialog.getByLabel('目标值', { exact: true }).fill('1');
  const original = page.viewportSize()!;
  await page.setViewportSize({ width: original.height, height: original.width });
  await expect(dialog.getByLabel('目标名称')).toHaveValue(title);
  expect(await page.evaluate(() => innerWidth)).toBeLessThanOrEqual(original.height + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  const bounds = await dialog.boundingBox();
  expect(bounds!.y).toBeGreaterThanOrEqual(0);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(original.width + 1);
  await page.screenshot({ path: info.outputPath('rotated-form.png') });
  await page.setViewportSize(original);
  await dialog.getByRole('button', { name: '保存／预览修改' }).tap();
  await expect(dialog).toHaveCount(0);
  await page.reload();
  const card = page.locator('.goal-card').filter({ has: page.getByRole('heading', { name: title, exact: true }) });
  await expect(card).toBeVisible();
  await card.getByRole('button', { name: '修改目标／进度' }).tap();
  await expect(dialog.getByLabel('目标名称')).toHaveValue(title);
  await dialog.getByRole('button', { name: '关闭窗口' }).tap();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('body')).not.toHaveCSS('overflow', 'hidden');
  await page.screenshot({ path: info.outputPath('touch-overview.png'), fullPage: true, scale: 'css' });
  expect(errors).toEqual([]);
});
