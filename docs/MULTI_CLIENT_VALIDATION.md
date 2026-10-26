# v0.4 多端实现验证记录

日期：2026-10-26。环境：Windows、Python 3.12、Node/Vite、JDK 17、Android SDK 35、Gradle 8.11.1。测试使用临时或 `.cache` 独立目录，没有将测试内容写入正式 data/。

## 已验证

| 项目 | 结果 | 范围 |
|---|---|---|
| 后端完整回归 | 151 通过 | 原 136 项 + 多端 15 项；旧记录/备份仍可读取 |
| 多端最后定向回归 | 15 通过 | 登录/来源/CSRF、配对/轮换/撤销、Agent 禁止确认、提案/冲突、游标/范围、提醒/恢复、AES-GCM、推送替身与来源审计 |
| 前端单元测试 | 18 通过 | 既有记录/表单/确认/分析等组件 |
| TypeScript/Vite | 构建通过 | v0.4 新增 AuthGate 与 ClientPanel |
| 浏览器原有回归 | 27 通过 | 8 个配置：桌面、平板、手机、极窄屏、WebKit 桌面、Android Pixel、iPhone、iPad；包括触控/旋转与无横向溢出 |
| 多端浏览器联调 | 2 通过 | 桌面/手机：登录、批准配对、Agent 提案、本人确认、设备与 Agent 读取一致、退出登录 |
| Android JVM | 3 通过 | HTTPS 地址限制、增量合并、持久命令编号/版本/未知值 |
| Android Debug | 构建通过 | 默认无推送 SDK 的 APK |
| 可选推送分支 | 编译和 JVM 测试通过 | JPush 6.2.1，测试 AppKey，仅构建未运行 SDK/未真实投递 |
| Android Lint | 0 错误，7 警告 | 剩余为依赖新版本提示与 KTX 风格建议；修正了网络域名声明、备份排除与广播 action 检查 |

推送替身验证：通用通知中不出现任务正文；同一事件不重复排队；已撤销设备不再发送；读取超时记为 unknown，不自动重试；推送 Master Secret 以密文保存。`accepted` 不冒充设备送达。

浏览器和接口测试使用真实本机 FastAPI 服务，模拟不同调用方的凭据。Android JVM 测试并未运行 Android Keystore、AlarmManager 或真实界面，不替代设备验收。

## 已遇到并解决

- 配对后设备默认提醒状态补入 capabilities，首台与后续设备分别返回状态。
- 增量补充提醒回执与年度时间；后台和前台同步在同一个进程锁内串行合并，避免旧缓存覆盖新缓存。
- 网页命令失败重试保留请求编号；登录恢复后重新建立 CSRF 会话。
- 手机数字输入无效时阻止提交，不能静默采用旧值。正式冲突不自动覆盖，失败提交保留草稿。
- 推送配置表单独立加载，SSE 更新不会清空未保存的推送输入。
- 资料的 origin 从服务器同一原子事件的审计生成，不能由调用方冒充；历史旧记录没有 origin 时保持未知。
- Lint 指出的测试网络配置补上 includeSubdomains=false；Android 12+ 云备份/设备迁移明确排除缓存、草稿和凭据。

## 待实际环境验证

- 本机 `adb devices` 没有真实手机。Android Emulator 缺少硬件加速驱动；尝试无加速模式仍停留 offline，已停止测试实例，未修改系统虚拟化设置。因此 APK 安装启动、交互/旋转/键盘/平板双栏仍待真机或可用模拟器验收。
- 荣耀 Magic7 锁屏、断网、重启、系统省电、通知关闭、精确提醒权限变化；其他安卓品牌和系统版本。
- 真实 HTTPS 域名、证书、Linux 账户/权限/文件锁、长期运行、恢复与回滚。模板已有，未实际部署。
- 实际极光 AppKey/Master Secret、签名包注册与投递，厂商后台条件。没有真实推送调用，不保证全品牌实时到达。
- 本轮没有调用真实模型；既有模型替身测试保留。v0.3 的 DeepSeek 样例结果属于历史，不代替本轮手机/服务器验证或个人资料分析质量。
- 管理员密码轮换/忘记密码恢复流程、大规模初始快照分块、更多移动端可访问性与长时间运行测试属于后续完善。

## 复现与产物

后端 `python -m pytest -q`；前端 `npm test`、`npm run build`。浏览器 `npx playwright test --project desktop --project tablet --project phone --project small-phone --project webkit-desktop --project android-pixel --project iphone-portrait --project ipad-portrait`；新增多端联调 `npx playwright test --config playwright.clients.config.ts`。

APK：`gradlew.bat assembleDebug testDebugUnitTest lintDebug`。产物 `apkProject/app/build/outputs/apk/debug/app-debug.apk`，测试签名；正式使用需自有 Release 签名。构建输出、截图、诊断和工具链在忽略目录，不进入公共 Git。

契约：`python scripts/export_client_contract.py`，仅访问临时空目录。部署接续顺序见 `MULTI_CLIENT_PLAN.md`、根 `AI_READ.MD`；当前代码是否已推送以 Git 实际状态为准。
