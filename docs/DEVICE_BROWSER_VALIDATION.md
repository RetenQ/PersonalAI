# 设备模拟与跨浏览器验收

日期：2026-10-24。依据用户要求，以本机设备模拟补充手机、平板和其他浏览器的页面验证。没有开放局域网或公网，没有连接真实手机。

## 环境和范围

使用项目的 Playwright、真实 FastAPI 服务及生产构建，不模拟业务接口。每次运行在 `.cache/browser-e2e/run-*/` 新建独立数据，服务固定为 `127.0.0.1:19765`，退出后停止。正式 `data/` 不参与测试；不调用外部模型。

| 项目 | 引擎 | CSS 视口 | 模拟方式 |
|---|---|---|---|
| desktop | Chromium | 1440 × 1000 | 桌面 |
| tablet | Chromium | 834 × 1112 | 原有平板宽度回归 |
| phone | Chromium | 390 × 844 | 原有手机宽度回归 |
| small-phone | Chromium | 320 × 740 | 极窄屏回归 |
| firefox-desktop（可选） | Firefox | 1440 × 1000 | 环境阻塞，未完成页面验收 |
| chrome-desktop（可选） | 本机 Chrome | 1440 × 1000 | 桌面 |
| edge-desktop（可选） | 本机 Edge | 1440 × 1000 | 桌面 |
| webkit-desktop | WebKit | 1440 × 1000 | 桌面 |
| android-pixel | Chromium | 412 × 839 | Pixel 7 参数，触控 |
| iphone-portrait | WebKit | 390 × 664 | iPhone 13 竖屏参数，触控 |
| iphone-landscape | WebKit | 750 × 342 | iPhone 13 横屏参数，触控 |
| ipad-portrait | WebKit | 834 × 1194 | iPad Pro 11 竖屏参数，触控 |
| ipad-landscape | WebKit | 1194 × 834 | iPad Pro 11 横屏参数，触控 |

设备项目使用 Playwright 预置的 User-Agent、像素密度、移动视口和触摸参数；CSS 视口不等于硬件屏幕尺寸。WebKit 是测试引擎，不是安装在苹果设备上的 Safari。

## 检查内容

- 每个项目执行完整流程：目标创建、未知进度、修改拒绝与确认、历史查看、任务关联、日志、早间回应、刷新回查、设置与个人档案确认、资料文件生成、导出下载、备份下载及上传校验。
- 检查六个页面与弹窗的横向溢出、页面实际宽度、键盘焦点、JavaScript 异常和未配置模型时禁止发送；保存页面截图。
- 五个设备项目额外用真实触摸事件执行导航、打开表单、保存与关闭。旋转模拟通过交换视口宽高，检查未保存输入仍在、弹窗没有超出屏幕、保存按钮能滚动到达；刷新后核对保存内容。
- 所有修订仍由测试显式确认，不跳过应用权限流程。

## 复现

首次下载测试浏览器，在项目的 frontend 目录运行：

```powershell
npx.cmd playwright install chromium webkit
npm.cmd run test:e2e
```

只运行某个设备，可使用：

```powershell
npm.cmd run test:e2e -- --project=iphone-landscape
```

默认运行 10 个配置、15 项测试。已安装 Chrome 和 Edge 时，开启品牌浏览器测试：

```powershell
$env:PERSONALAI_TEST_CHANNELS = '1'
npm.cmd run test:e2e
$env:PERSONALAI_TEST_CHANNELS = $null
```

Firefox 独立启用，启动失败不会被静默跳过：

```powershell
npx.cmd playwright install firefox
$env:PERSONALAI_TEST_FIREFOX = '1'
npm.cmd run test:e2e -- --project=firefox-desktop
$env:PERSONALAI_TEST_FIREFOX = $null
```

截图、失败跟踪等保存在 `frontend/test-results/`，下一次运行会刷新该输出目录。独立测试数据保留供排查，不写入正式记录。

## 本轮发现与修复

最终在修复后的同一生产构建上分两批执行：WebKit 9 项通过，Chromium／Chrome／Edge 8 项通过，合计 **12 个配置、17 项测试通过**，没有跳过这些配置的业务检查。TypeScript／Vite 构建通过。本轮没有变更后端业务逻辑；此前后端 87 项、前端组件 10 项结果不作为本轮重跑结果。

实际运行版本：Chromium 156.0.8078.4、WebKit 27.2、本机 Chrome 156.0.8078.47、本机 Edge 156.0.4314.42，均为无头模式。默认配置的 15 项包含在这 17 项中；另外两项是本机 Chrome 和 Edge。Firefox 的失败单独记录，没有计入 17 项通过。

最终截图及结果分别保存在 `frontend/test-results/webkit/` 和 `frontend/test-results/chromium-channels/`，两批 `.last-run.json` 均为 passed。已人工查看 Android 记录页、Android／iPhone 旋转表单、iPhone 横屏设置和 iPad 竖屏总览截图。

- iPhone 横屏 750 × 342 下，原来的固定侧栏内容超出屏幕高度，底部导航不可点击。已让桌面式侧栏独立纵向滚动、保留子项高度；六个页面的导航与触控流程作为回归检查。
- Windows WebKit 在启用触控后仍报告 `navigator.maxTouchPoints = 0`，但实际能派发触摸事件。测试改为确认粗指针模式，并检查每次触控导航实际产生的 `touchstart`，没有用鼠标操作代替触控测试。
- Firefox 157.0（Playwright build 1555）在进入页面前失败。Windows SideBySide 事件明确报告无法加载 `mozglue` 从属程序集；重新下载官方测试浏览器后仍复现。该项保留为环境阻塞，不计入通过数量，不修改系统组件或浏览器二进制来绕过问题。

## 模拟边界

这里验证浏览器引擎、视口、触控事件和应用流程。没有覆盖真实移动设备的软键盘弹出、系统文件选择／下载管理、浏览器地址栏伸缩、安全区域、低内存与性能、真实屏幕旋转传感器、Safari 品牌发行版或 Codex 内置浏览器。Chrome／Edge 也以无头模式运行，不包含操作系统窗口交互。旋转测试只改变视口，不宣称模拟了操作系统和浏览器全部行为。后续开放跨设备访问时再补充真机使用反馈。

模拟参数与能力参考 [Playwright 设备模拟说明](https://playwright.dev/docs/emulation)；本页通过／失败结论来自本机实际测试。
