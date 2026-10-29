import { test, expect } from '@playwright/test';

test('概述默认首页仅展示任务与目标，保留总览操作入口', async ({page}) => {
  await page.goto('/');
  const nav=page.getByRole('navigation',{name:'主要导航'});
  await expect(nav.getByRole('button',{name:'概述',exact:true})).toHaveAttribute('aria-current','page');
  await expect(page.getByRole('heading',{name:'概述',exact:true})).toBeVisible();
  await expect(page.getByRole('region',{name:'今日任务',exact:true})).toBeVisible();
  await expect(page.getByRole('region',{name:'目标与任务',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'快捷记录'})).toHaveCount(0);
  await expect(page.getByRole('region',{name:'待确认事项'})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'建立目标',exact:true})).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await nav.getByRole('button',{name:'总览',exact:true}).click();
  await expect(page.getByRole('button',{name:'建立目标',exact:true})).toBeVisible();
});
