# APK 已迁至独立工程

2026-10-29，按用户要求，Android 工程从本仓库 `apkProject/` 迁至：

**`E:\CodexProject\PersonalAI_Apk`**

- AI 接手入口：该目录的 `AI_READ.MD`。
- 构建与安装说明：该目录的 `README.md`。
- APK 用户实测记录：该目录的 `docs/APK_VALIDATION_2026_10_28.md`。
- 迁移及本轮构建验证：该目录的 `docs/EXTRACTION_2026_10_29.md`。

新目录直接是 Android 工程根目录，不再包含 apkProject 层。Android Studio 打开新目录；PowerShell 在新目录运行 `.\Build-Apk.ps1 -Lint`。

源码、本地安卓工具链、Gradle 缓存、AVD 和安卓诊断日志一并迁出。新目录尚未创建远端仓库；本次拆分提交并推送后，服务器 clone 本仓库将不再获得 APK 源码；目前未推送，远端仍保留原目录。历史 Git 版本中的 apkProject 不主动改写。

本仓库继续负责 Web、正式数据、认证、设备授权、`/api/clients/v1/`、提醒与投递服务、客户端协议生成及后端契约测试。`docs/AGENT_API.md` 与 `docs/openapi.clients.v1.json` 保持权威来源；APK 工程保留迁移日期的只读参考快照，协议改变后需同步并联调。

本次没有修改业务协议、应用包名、版本号或服务器配置；既有网页调整也没有自动移植到 APK。构建成功不代表安装、提醒或推送重新验收。
