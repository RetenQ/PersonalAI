# PersonalAI Android

独立安卓工程，Kotlin + Jetpack Compose，minSdk 26（Android 8.0），compile/targetSdk 35。手机底部导航、宽屏侧边导航；正式数据来自服务器，应用本机只保留加密缓存、草稿和提醒。版本 0.4.0。

## 环境与构建

JDK 17、Android SDK Platform 35 / Build Tools 35、Android Studio 或命令行工具。使用仓库 Gradle Wrapper 8.11.1，AGP 8.9.2，Kotlin 2.1.20。SDK/JDK 位置通过 `JAVA_HOME`、`ANDROID_HOME` 或本机 `local.properties` 配置，不提交绝对开发机路径。

```powershell
Set-Location apkProject
.\gradlew.bat assembleDebug testDebugUnitTest
# 可选静态检查
.\gradlew.bat lintDebug
```

输出 `app/build/outputs/apk/debug/app-debug.apk`。这是测试签名安装包；不等于正式发行或已通过真机验收。方便脚本 `Build-Apk.ps1` 优先采用环境变量，本机缺失时可使用根目录忽略的 `.cache/toolchains` 中已有工具链；不会自动下载或修改系统配置。

Linux/macOS 用 `sh gradlew assembleDebug testDebugUnitTest`。Android Studio 直接打开本文件夹，不打开 Python 工程来构建 APK。

## 连接与使用

1. 服务器完成 [HTTPS/账户初始化](../docs/SERVER_DEPLOYMENT.md)，在网页登录。
2. APK 填写 HTTPS 根地址和设备名称，获取八位码，网页“设置 → 设备、Agent 与提醒”批准后，回手机完成配对。
3. 今日页快捷记录；关联任务只生成活动日志，否则保存普通原文。目标/任务进度分开显示，缺失保持未知。
4. 修改目标、归属、进度、画像及旧记录先检查提交内容，再从待确认查看正式差异、接受或拒绝；离线不能正式确认。
5. 失败的提交保留草稿；联网后先刷新版本，由本人重新提交。成功提交后移除草稿。后台同步不自动提交草稿。
6. 我的页维护资料、选择已有模型连接、调整分析安排；模型调用前预览发送范围。模型密钥、安装插件与服务器目录仍在网页/服务器管理。

仅 Debug 包允许 `http://127.0.0.1`、`localhost`、安卓模拟器主机桥 `10.0.2.2`。Release 必须 HTTPS。USB 本机开发可 `adb reverse tcp:8765 tcp:8765` 后连接 `http://127.0.0.1:8765`；该转发只用于本机测试，不开放手机端口。

## 数据与提醒

`files/personalai.enc` 用 Android Keystore AES-GCM 加密，包含令牌、缓存与草稿。禁止系统备份，主界面限制截图。卸载/清除应用数据会丢失本机草稿，服务器资料保留。断开前有明确提示；服务器授权需另行撤销。

前台通过 SSE 提示同步，后台 WorkManager 周期检查（最低 15 分钟，不保证准时）。已同步未来 30 天日程由 AlarmManager 安排，本地提醒不依赖实时网络。通知权限不足会显示提示；精确权限不足降级为系统允许时间，可能延迟。启动、重启、时区变化和权限变化时重新检查安排。离线手机不能即时撤回服务器刚修改的安排。

首台设备默认提醒开启，其他设备默认关闭。所有规则由本人指定时间，不自动把任务日期变成闹钟。已读、十分钟后提醒、完成任务分别处理。收到或打开通知不会完成任务。

## 可选极光适配器

默认构建完全不包含推送 SDK。需要时由本人准备极光应用 **AppKey**，通过本机忽略的 Gradle 配置或参数构建：

```powershell
.\gradlew.bat assembleDebug -PjpushAppKey=YOUR_APP_KEY
```

AppKey 是 SDK 应用标识；**Master Secret 绝不能进入 APK/Gradle/Git**，仅由服务器加密保存。该变体使用 JPush 6.2.1、固定 JCore 5.5.7；不接厂商企业通道。在“我的”明确同意后才初始化推送 SDK。SDK 会处理必要设备标识；通知只含通用文字和不透明事件编号，点击后鉴权获取正式资料。

已用无效测试 AppKey 验证可选分支编译，未启动真实通道。D8 对厂商 JAR 输出 stack map 警告，构建成功；应在真实签名包与真机中继续验证 SDK 行为。后台消息为尽力送达，不保证各品牌实时提醒。参考[极光 Android 集成](https://docs.jiguang.cn/jpush/client/Android/android_guide)、[隐私授权说明](https://docs.jiguang.cn/en/jpush/practice/compliance)、[Android AlarmManager](https://developer.android.com/develop/background-work/services/alarms)。

## Release 签名

`assembleRelease` 生成未签名包。签名私钥保存在仓库外，使用 Android Studio 的签名向导或 `apksigner`，密码交互输入，不放命令历史/源码/普通配置。长期保存相同签名以便覆盖升级；换签名通常需要卸载，会丢失本机草稿。`.jks/.keystore/local.properties/build` 已排除 Git。没有应用商店发布步骤。

## 代码地图

| 文件 | 职责 |
|---|---|
| MainActivity.kt | 五个入口、导航、详情与差异预览 |
| Editor.kt / AnalysisUI.kt | 业务表单、资料选择和分析授权 |
| ClientModel.kt | 页面状态、提交草稿、同步与本人确认 |
| Api.kt / Protocol.kt | HTTPS、令牌刷新、快照/增量合并与固定请求编号 |
| SecureStore.kt | Keystore、加密与原子保存 |
| Reminders.kt | AlarmManager、重启恢复、WorkManager |
| src/jpush/ | 可选 SDK、注册回传和通用更新通知 |
| src/test/ | 纯 JVM 协议测试 |

## 接续验收

本轮状态见 [MULTI_CLIENT_VALIDATION.md](../docs/MULTI_CLIENT_VALIDATION.md)。首台真机荣耀 Magic7；再测试其他安卓品牌、Android 8/13/15、手机与平板尺寸。逐项记录：

- 配对、撤销、令牌轮换；与网页/Agent 同编号同版本。
- 创建目标/任务、活动日志、回顾、画像修改、差异接受/拒绝与过期冲突。
- 飞行模式缓存、手动草稿、进程重启、联网重提不重复，失败输入保留。
- 通知/精确提醒权限开关、锁屏、断网、重启、时区变化、应用升级。
- 普通推送重复/延迟/丢失后补同步；注册失败可重新开启或重启应用，不能声称已收到。
- 字体放大、键盘遮挡、旋转、分屏、平板；读取大数据时内存/响应体上限。

缺少真机或服务器凭据时，只报告编译/模拟验证，不能填写真机“通过”。本阶段不提供多用户、完整离线合并、虚拟角色或所有品牌后台到达保证。
