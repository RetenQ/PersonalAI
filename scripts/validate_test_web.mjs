// Real deployed HTTPS login/settings on desktop and narrow mobile viewports.
// Public HTTPS uses the normal trust store; validate_upgrade_readonly.py also
// verifies TLS and served assets. The retired loopback endpoint retains SPKI pinning.
import { readFileSync } from 'node:fs';
import { createHash, X509Certificate } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require('playwright');
const { expect } = require('@playwright/test');
const config = JSON.parse(readFileSync('/etc/personalai-test/server.json', 'utf8'));
if (config.data_dir !== '/var/lib/personalai-test/data') throw new Error('Refusing non-test data');
const args = [];
if (config.public_origin === 'https://localhost:18443') {
  const cert = new X509Certificate(readFileSync('/etc/personalai-test/tls/localhost.crt'));
  const pin = createHash('sha256').update(cert.publicKey.export({ type: 'spki', format: 'der' })).digest('base64');
  args.push(`--ignore-certificate-errors-spki-list=${pin}`);
}
const password = execFileSync('systemd-creds', ['decrypt', '--name=owner-password',
  '/etc/personalai-test/owner-password.cred', '-'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
const browser = await chromium.launch({ headless: true, args });
try {
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 320, height: 740 }]) {
    const context = await browser.newContext({ viewport, locale: 'zh-CN', timezoneId: 'Asia/Shanghai' });
    try {
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', () => errors.push('pageerror'));
      await page.goto(config.public_origin);
      await expect(page.getByRole('heading', { name: '登录' })).toBeVisible();
      await page.getByLabel('管理员密码').fill(password);
      await page.getByRole('button', { name: '登录', exact: true }).click();
      await page.getByRole('navigation', { name: '主要导航' }).getByRole('button', { name: '设置', exact: true }).click();
      const panel = page.getByRole('region', { name: '设备与 Agent' });
      await expect(panel.getByRole('heading', { name: '手机配对' })).toBeVisible();
      await expect(panel.getByLabel('提醒时间（上海时间）')).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
      await panel.getByRole('button', { name: '退出登录' }).click();
      await expect(page.getByRole('heading', { name: '登录' })).toBeVisible();
      expect(errors).toEqual([]);
      console.log(`PASS deployed HTTPS browser login/settings/logout ${viewport.width}px; retired reminder form absent`);
    } finally { await context.close(); }
  }
} finally { await browser.close(); }
