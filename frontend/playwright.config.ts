import { defineConfig, devices } from '@playwright/test';

const desktopTests = { testIgnore: '**/devices.spec.ts' };
// Optional local installations and a separate Firefox run keep environment
// failures explicit without requiring branded browsers on every machine.
const extraProjects = [
  ...(process.env.PERSONALAI_TEST_FIREFOX === '1' ? [
    { name: 'firefox-desktop', ...desktopTests, use: { browserName: 'firefox' as const, viewport: { width: 1440, height: 1000 } } },
  ] : []),
  ...(process.env.PERSONALAI_TEST_CHANNELS === '1' ? [
    { name: 'chrome-desktop', ...desktopTests, use: { browserName: 'chromium' as const, channel: 'chrome', viewport: { width: 1440, height: 1000 } } },
    { name: 'edge-desktop', ...desktopTests, use: { browserName: 'chromium' as const, channel: 'msedge', viewport: { width: 1440, height: 1000 } } },
  ] : []),
];

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:19765',
    browserName: 'chromium',
    headless: true,
    actionTimeout: 10_000,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', ...desktopTests, use: { viewport: { width: 1440, height: 1000 } } },
    { name: 'tablet', ...desktopTests, use: { viewport: { width: 834, height: 1112 } } },
    { name: 'phone', ...desktopTests, use: { viewport: { width: 390, height: 844 } } },
    { name: 'small-phone', ...desktopTests, use: { viewport: { width: 320, height: 740 } } },
    { name: 'webkit-desktop', ...desktopTests, use: { browserName: 'webkit', viewport: { width: 1440, height: 1000 } } },
    { name: 'android-pixel', use: { ...devices['Pixel 7'], browserName: 'chromium' } },
    { name: 'iphone-portrait', use: { ...devices['iPhone 13'], browserName: 'webkit' } },
    { name: 'iphone-landscape', use: { ...devices['iPhone 13 landscape'], browserName: 'webkit' } },
    { name: 'ipad-portrait', use: { ...devices['iPad Pro 11'], browserName: 'webkit' } },
    { name: 'ipad-landscape', use: { ...devices['iPad Pro 11 landscape'], browserName: 'webkit' } },
    ...extraProjects,
  ],
  webServer: {
    command: (process.platform==='win32'?'".venv/Scripts/python.exe"':'".venv/bin/python"')+' tests/browser_server.py',
    cwd: '..',
    url: 'http://127.0.0.1:19765/api/status',
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
