import { defineConfig } from '@playwright/test';
export default defineConfig({
 testDir:'./client-e2e',workers:1,timeout:90000,reporter:'list',
 use:{baseURL:'http://127.0.0.1:19766',headless:true,locale:'zh-CN',timezoneId:'Asia/Shanghai',screenshot:'only-on-failure',trace:'retain-on-failure'},
 projects:[{name:'desktop',use:{viewport:{width:1440,height:1000}}},{name:'phone',use:{viewport:{width:390,height:844}}}],
 webServer:{command:(process.platform==='win32'?'".venv/Scripts/python.exe"':'".venv/bin/python"')+' tests/client_browser_server.py',cwd:'..',url:'http://127.0.0.1:19766/api/auth/status',reuseExistingServer:false},
});
