# PersonalAI：服务器端 AI 接手入口

更新时间：2026-10-29。应用 v0.4.0；客户端协议 v1 / OpenAPI 1.0.0。

**当前结论：公网服务器已更新，可供新版 APK 联调。** 目标提交 `218c5e7067d98ea498107f8c3675bb121cee08f1` 已于北京时间 **2026-10-29 20:35** 部署到 **https://personalai.retenq.cloud**。后端与网页一起更新，发布目录 `/opt/personalai-test/releases/218c5e7-server1`，服务 `personalai-test.service` active/running、开机自启、单进程、仅回环监听。运行进程目录、服务账户 Python 导入指向、源码/网页校验值和实际 HTTPS 返回均已核对，不能只凭 Git 提交或重启推定部署。

**先读本轮 [部署验证记录](docs/SERVER_VALIDATION_2026_10_29.md) 和 [APK clients/v1 扩展协议](docs/APK_CLIENT_EXTENSIONS_2026_10_29.md)**，再看 [运维交接](docs/SERVER_TEST_RUNBOOK.md)、[Agent/API 说明](docs/AGENT_API.md) 与 [OpenAPI](docs/openapi.clients.v1.json)。此前各网页改版、状态退役和协议扩展已经随本次提交部署；其他历史文档里的“未发布”描述属于当时状态。

本轮 Linux Python 3.12 后端 **170 项**（上游 164 + 本机维护 6）、前端 **26 项**、构建、隔离网页 **9 项**及多端 **2 项**通过。实际公网网页 1440px/320px 登录、设置和退出通过；首页和资源逐字节匹配新发布。没有为本次上线修改后端业务实现；保留旧 CSS 修复并适配了测试选择器。

**设备验收边界**：隔离设备 Bearer 协议测试中五项 features 均为 true。实际公网只读检查使用管理员会话，role=owner，`atomic_task_create_v1=false`，其余四项 true，符合角色限制。没有可用真实设备令牌，本轮不新增授权、不向现有记录写测试任务；**新版真实设备 Bearer 的公网五项能力与业务流程仍待 APK 端验证**。不把 Cookie、隔离测试或旧版手机反馈当成本轮新接口真机通过。

用户在此前本机接续中已反馈 APK 安装配对、双向同步、修改接受/拒绝、离线缓存及草稿提交成功，见 [APK 职责与反馈](docs/APK_DEVELOPMENT.md)；不重复要求首次安装或无故撤销现有设备。新版应先刷新连接并请求 capabilities，按 features 决定功能，不仅检查 api_version。

**APK 已迁出**：工程位于开发电脑 `E:\CodexProject\PersonalAI_Apk`，入口为该目录的 AI_READ.MD。本仓库不再维护 apkProject；服务器不恢复安卓源码、不安装安卓工具链、不修改 APK。下一步由 APK AI 更新协议快照和能力判断，完成真实设备联调；没有模型/推送密钥不阻止基础接入。

升级前已有 **35 个事件**，全部保留且 SHA-256 不变。账号、密码、密钥、既有设备/Agent 授权、域名/DNS、Nginx 和服务配置未改变。没有迁移正式资料、自动导入画像、启用模型/自动分析/推送或新增提醒。升级前完整快照、原配置、原 Python 环境与经新代码恢复验证的业务 ZIP 均保存在 `/var/lib/personalai-test/backups/pre-218c5e7-20261029/`，原 `27c342b-server2` 发布目录保留。备份不进 Git，回滚须先核对升级后新增数据。

本轮用户明确授权更新、必要重启和验证，已完成；随后授权推送，本次 Git 同步包含部署记录、CSS 修复、浏览器测试修正及两份公网验证脚本。后续应保留本机修改，先读本轮记录再行动，不重新初始化管理员、改密码/DNS或重跑会向现有目录写测试资料的旧脚本。

## 0. 先读这里：当前处于哪一步

### 0.1 已完成与验证边界

| 项目 | 已有结果 | 下一步或边界 |
|---|---|---|
| Linux 依赖、后端与网页 | 本轮 Python 3.12 后端 170 项、前端 26 项及 TypeScript/Vite 构建通过 | 不等于新接口 Android 真机通过 |
| 网页兼容 | 本轮 desktop/phone/small-phone 9 项、多端 2 项通过；公网 1440px/320px 登录、设置、退出通过 | WebKit 既有依赖问题，本轮未重验、不计通过 |
| 公网 HTTPS 与服务 | DNS、可信证书、专用自动续期任务及续期演练通过；单账户、单进程、回环后端、开机自启 | 持续运行和未来实际续期仍需观察 |
| 登录、权限与业务 | 公网域名下登录、CSRF/Origin、协议设备配对、Agent 最小权限、记录/提案确认、版本冲突、撤销、同步/SSE、重启验证通过 | 协议模拟客户端不等于实际 APK/Agent 工具 |
| 备份恢复 | 停服一致性快照与业务 ZIP；新代码在新目录恢复，35 个事件逐文件一致 | 原版保留，业务 ZIP 不恢复身份/自动调用许可；完整私有快照另行保护 |
| 管理员密码 | 已按本人要求更换；新密码 HTTPS 登录成功，旧密码/旧会话失效，加密副本同步；维护脚本 6 项隔离测试通过 | 不记录明文，不再次初始化或擅自更改密码 |
| 手机浏览器 | 2026-10-28 本人明确反馈“手机浏览器完成验证” | 型号、系统、浏览器和网络类型未提供，不推定使用移动流量或所有手机流程通过 |
| 安卓 APK | 用户确认安装配对、双向同步、修改接受/拒绝、离线缓存及草稿提交成功 | 冲突、撤销、系统重启和提醒等仍待实测；详见 APK 用户实测记录 |
| 实际 Agent、模型和推送 | Agent 协议及服务端边界已验证；模型、定时分析和真实推送未启用 | 实际工具、供应商和通知送达未验收；不默认开启或预设提醒时间 |

本轮已重新执行完整后端 170 项及上表前端/浏览器检查，证据日期为 10 月 29 日；旧版手机反馈来自 10 月 28 日。完整测试中的 6 项密码维护测试只用隔离数据，没有改动现有密码。实际公网查询当前没有报告样本，补跑报告覆盖/安全投影由隔离合成报告验证。

### 0.2 运行位置、版本与已有修改

| 内容 | 实际位置或状态 |
|---|---|
| 工作区 | `/root/PersonalAI`，分支 `main`；部署基础提交 `218c5e7067d98ea498107f8c3675bb121cee08f1`；Git HEAD 随本次交接同步前进，以 `git rev-parse HEAD` 为准，仍有本机未跟踪工具 |
| 远端 | 2026-10-29 fetch 后 main 正好为目标 218c5e7，快进更新；后续先核对关系，不强制回退 |
| 发布源码 | `/opt/personalai-test/current` → `/opt/personalai-test/releases/218c5e7-server1`；旧 `27c342b-server2` 和 `server1` 保留 |
| 服务/账户 | `personalai-test.service` / `personalai-test`；后端只监听 `127.0.0.1:8765` |
| 运行 Python | `/opt/personalai-test/venv/bin/python`，Python 3.12.13；本地测试环境 `.cache/venv312` |
| 系统 | OpenCloudOS 9.4 x86_64；部署时 Node 24.22.1、npm 11.19.1 |
| 运行配置 | `/etc/personalai-test/server.json`；`public_origin=https://personalai.retenq.cloud` |
| 测试数据/备份 | `/var/lib/personalai-test/data`、`/var/lib/personalai-test/backups`；没有正式资料迁入 |
| 加密主密钥 | `/etc/personalai-test/master.key`，仅受限账户可读，不打印、不复制进 Git |
| 管理员凭据 | `/etc/personalai-test/owner-password.cred`，root-only 主机加密副本；私有 SSH 领取方法见运维手册 |
| Nginx | `/etc/nginx/conf.d/personalai-test-public.conf`，独立子域名，原根站点配置未改写 |
| 证书/续期 | `/etc/letsencrypt/live/personalai.retenq.cloud/`；`personalai-cert-renew.timer`；专用 reload hook |

**此前 cb404ac 只同步交接文档；本次在 218c5e7 之上同步部署记录、既有 CSS 修复、浏览器选择器修正、validate_test_web.mjs 和 validate_upgrade_readonly.py。旧部署模板、初始化/DNS/密码维护工具、写入式验收脚本及密码维护测试仍只保留在服务器工作区，未纳入本次提交。** 不清空未跟踪文件，不以 `git reset/clean` 恢复“干净环境”。主要改动：

- `frontend/src/theme.css`：既有表单最大宽度和 label 最小宽度修复，已保留到新发布目录。后端业务代码未改写。
- `frontend/client-e2e/clients.spec.ts`、`scripts/validate_test_web.mjs`：按新版登录标题/设备面板更新选择器，明确检查退役提醒表单不存在；隔离和实际公网验证通过。
- `scripts/validate_upgrade_readonly.py`：新实际 HTTPS 只读审计，验证源码对应的静态资源、新路由与身份边界，不写业务事件或新增授权。
- `deploy/`：实际测试服务、Nginx/public_origin、证书续期模板；`docs/SERVER_TEST_RUNBOOK.md` 与三天验证记录及相关入口更新。
- `scripts/bootstrap_test_owner.py`、`validate_test_server.py`、`validate_test_web.mjs`：初始化与实际服务验证；后端验收脚本会创建测试资料、恢复目录并重启测试服务，不作为无副作用的健康探测。
- `scripts/configure_public_dns.py`、`test_public_dns.py`：已完成的 DNS 配置工具与隔离测试；运行和 HTTP-01 续期不依赖 DNS API 凭据。
- `scripts/rotate_test_owner.py`、`tests/test_owner_rotation.py`：核验旧密码后轮换的维护脚本，已实际执行；使用隐藏终端输入，密码不在源码/文档/普通文件中。

后续更新以 `/root/PersonalAI/AI_READ.MD` 和工作区文档为准，部署目录的文档副本可能较旧。本机另一位 AI 可通过本次提交获取进度、验收记录、CSS 修复、浏览器测试修正与两份公网验证脚本；旧部署模板、初始化/DNS/密码维护工具、写入式验收脚本及密码维护测试仍未提交，对应路径指服务器工作区文件。需要同步剩余实现时先检查差异，不假定远端已有这些文件。运行环境为 editable 安装，代码升级须核对安装指向，不能只切换 `current` 符号链接。

最近升级备份：`/var/lib/personalai-test/backups/pre-218c5e7-20261029/records.zip`，35 个事件；已恢复到同目录的 `restored-new-version/`，完整快照在 `data/`，原环境在 `venv/`。旧备份保留。校验值、回滚条件见本轮部署记录，不覆盖任何现有目录或唯一原件。

### 0.3 APK 职责（2026-10-29 已迁出）

安卓工程位于 `E:\CodexProject\PersonalAI_Apk`，入口为该目录 `AI_READ.MD`、`README.md`；源码、工具链及 APK 专属验证记录已迁出，见 [目录与职责](docs/APK_DEVELOPMENT.md)。本次拆分提交中已不再包含 APK 工程，不需要安装 JDK/Android SDK，也不从历史 apkProject 路径构建。

服务器端继续维护客户端认证、配对/撤销、确认冲突、同步及提醒投递；与 APK 联调时提供测试地址与协议版本。协议修改后先运行客户端契约测试、重新生成 OpenAPI，并通知安卓开发方更新快照。APK 的后续版本冲突、撤销和提醒实测由独立工程记录，不因拆分重做已经成功的基础配对，不自动启用推送或迁移正式资料。

### 0.4 尚未完成及独立运维事项

- APK 冲突与撤销、实际 Agent、锁屏/系统重启、通知权限和供应商送达仍未验收；WebKit 缺系统依赖、长期运行和未来自动续期仍需跟踪。
- 正式资料迁移、自动备份周期/保留策略、独立密钥保管尚未制定执行，不擅自增加周期任务。
- 之前用户发到聊天的 DNS API 密钥已建议撤销/轮换，未确认其完成；不得将旧值重新写入文件，站点运行及续期不需要该密钥。
- 原根站点 `retenq.cloud` 的旧证书曾观察到将于北京时间 2026-10-28 06:59:59 到期；本轮未复核是否已续期，不能把旧观察写成当前事实。它与 PersonalAI 子域名证书独立，必要时先只读核验并单独处理，保留原业务配置。

### 0.5 原 Windows 交接背景（历史）

2026-10-26 原交接记录：后端 151 项、前端 18 项、浏览器 27 项既有回归及 2 项多端联调通过；安卓 3 项 JVM 测试、Debug 构建、Lint 通过（0 错误、7 项依赖/风格警告）。这些是 **Windows 本地结果**，不是 Linux、手机或推送送达证明。

当时 Windows 本机未连接真机，安卓模拟器缺少硬件加速，软件模式未进入可操作状态。荣耀 Magic7 为计划中的首台实测机，不能据此认定用户本轮实际使用该机型；设计面向通用安卓手机/平板。完整证据与限制见 [多端验证记录](docs/MULTI_CLIENT_VALIDATION.md)。

**本文件随完整 v0.4 源码一并提交，服务器应获取完整仓库。** 公开仓库：[RetenQ/PersonalAI](https://github.com/RetenQ/PersonalAI)。实际拿到哪个提交必须重新核实，不要用版本字符串代替文件与提交核对；代码已发布也不代表服务器已部署。

首次获取（目标目录尚不存在时）：

```sh
git clone --branch main https://github.com/RetenQ/PersonalAI.git
cd PersonalAI
git rev-parse HEAD
```

已有 checkout 时先检查工作区，保留本机配置和修改；确认可快进后再更新，不用重新 clone 覆盖现有目录。

## 1. 接手后的第一轮行动

先做只读检查和隔离测试，已有授权范围内持续推进；只有缺失信息会阻止下一步时才询问，不重新访谈个人目标。

1. 阅读本文件和当前目录实际存在的 AGENTS.md；检查 `git status --short`、`git rev-parse HEAD`、`git remote -v`。保留已有修改，不执行清空工作区或强制覆盖。记录实际提交与未提交状态。
2. 确认至少包含 `src/personalai/access.py`、`client_api.py`、`delivery.py`、`admin.py`、`frontend/src/AuthGate.tsx`和 `docs/openapi.clients.v1.json`（APK 已迁至独立工程，服务器无需该目录）。缺少时先取得完整 v0.4 源码，不在旧版上照抄部署步骤。
3. 检查操作系统、架构、可用磁盘、Python/Node、运行账户、现有代理/站点/服务和监听端口。先确认是否已有实例与正式数据，避免把现有服务当空机器处理。
4. 阅读 [服务器部署说明](docs/SERVER_DEPLOYMENT.md)、[多端计划](docs/MULTI_CLIENT_PLAN.md)、[Agent 协议](docs/AGENT_API.md)。需要修改哪个模块，再读对应实现。
5. 用独立测试数据安装依赖、构建网页、运行测试。不要向正式目录写验收案例，不先导入完整私人画像。
6. 形成简短环境结论：拿到的代码版本、可复用设施、拟用路径/端口、下一步和必要缺项；随后执行已获授权的部署工作。

必须由实际环境或用户提供的信息：实际域名/DNS与允许的访问范围；服务器操作权限及现有服务限制；是否迁移已有资料、私有备份位置；模型/推送凭据是否已准备。不要猜域名、密码、资料或通知时间。凭据通过受保护的配置入口或隐藏终端输入提供，不要求用户把它们粘贴进交接文档。

没有域名/证书时，仍可完成回环地址的安装、构建和测试；没有模型/推送凭据时，仍可验收记录、确认、同步和备份。这些缺项只阻止相应接入步骤。

## 2. 已确定架构与权限边界

- **单人、多设备、一个后端进程**。FastAPI 统一提供构建后的 React 网页；服务器是正式数据唯一来源。APK 保存加密缓存、草稿和已同步提醒，不建立另一套正式资料。
- APK 在本机 `E:\CodexProject\PersonalAI_Apk` 开发，Kotlin + Jetpack Compose，Android 8.0 起。服务器无需安装 Android SDK/JDK 来运行网页和 API；安卓构建与签名由本机开发方完成。
- Agent 使用通用 HTTP 工具协议，不绑定具体 OpenClaw 版本，不要求 MCP 服务或公网回调。不能长连接时按游标轮询。
- 已登录网页/本人设备可以确认重要修改；Agent 只能读取所授权资料、追加允许的记录、提出修改，不能批准提案、管理权限或读取密钥。私人画像独立授权，默认不向 Agent 开放。
- 正式目标、归属、进度、画像及重要历史修改遵守“预览差异 → 本人确认 → 保留旧版”。模型不能直接写文件、执行工具或修改正式计划。部署用的 AI 编程助手可在本次授权范围内修改工程代码，这与产品内 Agent 的业务权限不同。
- 未记录表示未知；任务进度、目标可核实进度、AI 估计分别展示。日志不自动改变任务状态；已读、稍后提醒、任务完成分别处理。
- 目标分析逐次预览确认；定时分析明确授权数据范围，模型连接/范围变化后需重新授权。不得因服务上线自动启用分析或真实推送。
- 不自动导入访谈、完整私人画像，不编造真实记录。不迁移聊天中曾出现的凭据。
- 代码插件属于可信代码，不宣称恶意插件隔离。本阶段不引入多用户、数据库、多服务、插件商店或完整离线编辑合并。

## 3. 服务器执行顺序与检查点

### A. 安装与隔离验证

需要 Python 3.12、Node 20.19+ 或 22.12+。保留完整源码目录，以 editable 安装运行；当前不能假设单独安装 wheel 会包含网页。

在核实无冲突的代码目录执行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m pip install -e . --no-deps
.venv/bin/python -m pytest -q
cd frontend
npm ci
npm test
npm run build
cd ..
```

`requirements.lock.txt` 已给 pywin32 添加平台条件并加入 cryptography，但锁定依赖仍需在实际 Linux 验证。若某包安装失败，记录具体平台/版本原因，检查 `pyproject.toml` 约束后处理；不要删除校验、跳过失败测试或无记录地整体升级依赖以宣称通过。`tests/conftest.py` 在非 Windows 测试中生成独立临时主密钥，不使用生产凭据。

检查点：后端测试、前端测试/构建通过；`frontend/dist/index.html` 存在；测试结果确实来自当前服务器。只访问登录页不能证明私有 API 或存储健康。

### B. 确定目录与账户

下列路径均是**示例**，按实际服务器选择并记录：

| 内容 | 示例路径 | 要求 |
|---|---|---|
| 代码 | `/opt/personalai` | 保留源码与构建网页；不对外提供整目录 |
| 测试数据 | `/var/lib/personalai/test-data` | 与正式数据独立 |
| 正式数据 | `/var/lib/personalai/data` | 服务账户可写，其他账户受限；不进 Git |
| 服务配置 | `/etc/personalai/server.json` | 显式指定，不含模型/API 密钥 |
| 加密主密钥 | `/etc/personalai/master.key` | 仓库及数据目录外；32 字节；权限 600，仅服务账户可读 |
| 私有备份 | 待按实际环境确定 | 不在公开静态目录；周期/保留策略未预设 |

使用专用非特权服务账户，核对父目录访问权限。**不能对不存在的账户直接套 systemd 模板，也不能为解决权限问题把整个数据目录设为所有人可写。** 模板路径和账户必须与实际配置一致。

### C. 初始化或恢复，再配置身份与密钥

**全新测试环境**：使用新的测试目录初始化管理员。**已有正式资料迁移**：先完成第 5 节的恢复，再对恢复出的目录初始化管理员；不能先初始化目标目录，再把备份覆盖上去。

以下命令需要父目录已准备好、以实际服务账户运行：

```sh
.venv/bin/python -m personalai.admin --data-dir /var/lib/personalai/test-data
.venv/bin/python -m personalai.admin --data-dir /var/lib/personalai/test-data --generate-master-key /etc/personalai/master.key
```

第一条交互输入管理员密码，不通过命令参数/日志保存；已有账户会拒绝覆盖。第二条生成主密钥，拒绝覆盖已有文件；同时传数据目录可检查密钥没有放进该目录。不要因重复部署重新生成主密钥。已有账户/密钥直接核验并复用。

配置环境变量 `PERSONALAI_MASTER_KEY_FILE=/etc/personalai/master.key`。在终端手动运行测试服务时也要设置，不只写进 systemd。Windows 默认 DPAPI 密文不能复制到 Linux 解密；模型和推送服务凭据在受保护的服务器网页重新填写。主密钥另行安全保管，不进入普通资料备份。

### D. 配置回环服务和 HTTPS

实际配置示例（替换域名和路径，首次用测试目录）：

```json
{
  "host": "127.0.0.1",
  "port": 8765,
  "data_dir": "/var/lib/personalai/test-data",
  "plugins": ["tracking", "journal", "analysis", "dashboard", "exchange"],
  "public_origin": "https://personal.example.com"
}
```

```sh
.venv/bin/python -m personalai --config /etc/personalai/server.json
```

配置优先级：显式 CLI 参数 > 指定 JSON > 默认。未传 `--config` 不自动发现配置文件。相对 data_dir 按配置文件目录解析；CLI 相对路径按工作目录解析。换配置/目录需重启，不自动迁移数据。CLI 支持 `--config/--port/--data-dir`，不要杜撰 `--host/--workers` 参数。

后端始终只允许监听 `127.0.0.1`；由可信 HTTPS 代理对外提供服务。`public_origin` 是无路径、无凭据的 HTTPS 根地址，须与浏览器实际来源一致。代理保留正确 Host/Origin，不靠伪造本机来源绕过校验。程序只信任来自回环代理的转发头；不要将后端端口直接映射公网。

初始化账户后，私有网页 API 要登录；配置 `public_origin` 后，即使账户未初始化也拒绝私有读取。客户端 Bearer 不能替代旧网页认证。保留 Secure/SameSite Cookie、Host/Origin、CSRF 与静态目录限制，不为排错删掉保护。

[Caddy 模板](deploy/Caddyfile.example)与 [systemd 模板](deploy/personalai.service.example)是示例，不是已经安装的配置。若服务器已有代理，沿用实际设施完成等价配置，不覆盖其他站点。先校验配置再启用；保留 SSE 长连接，不在日志中记录 Authorization、密码或含凭据的请求正文。

只运行一个后端进程：认证预览、CSRF 和部分锁存在进程内，不支持多个 worker/多节点负载均衡。模板中的服务重启策略也不等于备份策略。切换正式目录前必须通过下列验收。

## 4. 按顺序验收，不用“页面能打开”代替通过

所有写入先用独立测试资料。不要在自动回归中调用真实模型或推送供应商。

| 检查 | 预期结果 |
|---|---|
| 公开登录状态 | `/api/auth/status` 返回状态；不包含私有资料。它只能用于存活探测，不能证明数据健康 |
| 未登录读取 | `/api/records`、`/api/settings`、`/api/status`、备份等私有入口拒绝；客户端无令牌也拒绝 |
| 登录后读取/写入 | 正常读取；网页经 `/api/session` 建立 CSRF 后才能写；缺失校验/伪造跨站来源被拒绝 |
| 静态文件 | 私人档案、`.secrets`、事件、源码路径不能被当作静态文件下载 |
| 新记录与确认 | 原文保存、重启可读；修改预览、拒绝不生效；竞争确认返回冲突，不覆盖新版本 |
| 设备配对与撤销 | 网页批准一次性配对码；APK/设备接口读写成功；撤销后读写及刷新令牌失败 |
| Agent 边界 | 只能读取已授权范围；新增任务/重要修改待确认；确认、密钥、内部管理接口被拒绝 |
| 同步与事件 | 快照→增量结果一致；SSE 经 HTTPS 代理可连接/重连；失效游标重新快照；回执不等于完成任务 |
| 备份恢复 | 新目录恢复后事件一致；设备令牌、密钥和自动调用授权不恢复 |
| 服务运行 | 实际服务账户运行；重启后资料保留；出错可诊断且日志无凭据 |

浏览器自动验收（在 frontend 内；需先安装 Playwright 浏览器，系统依赖按实际 Linux 安装）：

```sh
npx playwright install chromium webkit
npx playwright test
npx playwright test --config playwright.clients.config.ts
```

配置会选择 Linux `.venv/bin/python`；测试分别使用 19765/19766 端口、独立目录，不接管已存在的服务。浏览器环境不足时明确标为未验证，不把跳过计为通过。首次公网验收还应从另一台已授权设备访问真实 HTTPS 地址，不能只在服务器本机请求回环地址。

APK/真实 Agent 联调可能跨会话进行：先交付可用的测试地址、协议版本、配对步骤和本轮验证记录给本机开发方，再共同完成手机的离线、锁屏、重启和权限测试。当前 APK 仅构建/单测通过，运行故障需要如实修复与记录。

## 5. 正式资料迁移与回滚

服务器首选继续保存可追溯的 Markdown，不导入为新数据库。权威数据是 `events/*.md` 校验链；`user/` 是自动生成阅读副本，不作为双向编辑源。v1/v2 事件解码保留，v3 承载插件命名空间及 core/* 审计/提醒；不批量重写旧事件。

迁移顺序：

1. 在原环境导出备份，通过私有渠道传输；核对来源和完整性。Git 中没有真实资料是正常情况，不用测试案例填补。
2. 保留原目录与备份。恢复目标必须是尚不存在的新目录，避免覆盖唯一原件。
3. 在服务器执行校验/独立恢复：

```sh
.venv/bin/python -m personalai.backup /private/path/backup.zip
.venv/bin/python -m personalai.backup /private/path/backup.zip --restore-to /var/lib/personalai/restored-data
```

4. 核对事件数量、校验与阅读副本，再对恢复目录初始化管理员、配置服务器密钥。保留备份中的原始记录，不手工改校验和。
5. 暂停旧服务写入，明确切换点；将运行配置指向核验后的目录，重启并回查关键记录。不要让本地旧服务和服务器同时维护两套正式资料。
6. 重新填写模型/推送密钥、配对设备、创建 Agent 令牌；自动分析须重新预览授权，不沿用测试日程或测试授权。

备份不含 `.secrets`、`.scheduler`、`.delivery`；不会恢复设备/Agent 凭据、推送配置或自动调用许可。恢复后的游标可能失效，客户端应重新获取快照。

回滚必须同时考虑代码和数据版本：新备份/事件不保证被旧程序理解。变更前记录代码版本、配置位置和有效备份；失败时先停写，保留故障现场与新增数据，在独立目录验证恢复，再切回已核验的代码/数据组合。禁止只退代码却让不兼容的旧代码继续写新事件。

自动备份的位置、周期、保留期限和独立密钥保管仍须按实际环境确定；不要因为看到了需求就擅自创建周期任务。

## 6. 安卓、Agent、模型和推送的对接约定

| 对接方 | 服务器需提供 | 不应交给对接方 |
|---|---|---|
| 本机 APK 开发 | HTTPS 根地址、API v1、测试账号操作入口/配对流程、验证结果 | 管理员密码写入 APK、模型密钥、推送 Master Secret、服务器目录 |
| Agent 工具调用方 | 本人创建的最小范围令牌、[HTTP 协议](docs/AGENT_API.md)、[OpenAPI](docs/openapi.clients.v1.json) | 本人 Cookie、确认能力、密钥/服务管理权限 |
| 实际模型 | 经本人预览或明确范围授权的最小资料 | 整个私人档案、设备令牌、推送凭据 |
| 极光推送 | 注册标识、通用通知和不透明事件编号 | 目标/日志/报告正文、访问令牌 |

- API 前缀 `/api/clients/v1/`；原网页接口及 `/api/integrations/v1/` 保留兼容，旧只读令牌不会自动升级权限。
- 所有写入带固定请求编号；重试不换编号/内容。更新带预期版本，409 重新预览，410 重新快照。SSE/推送只提示取数，不能当作任意执行指令。
- APK 离线只读缓存、保存草稿；回到联网后本人提交。服务器正式确认不离线执行。模型或推送故障不能丢失原始日志。
- 本地提醒和服务器消息分别验收；任务只有日期时不补造提醒时刻。默认 Shanghai 时区、未来 30 天实例；设备离线无法即时撤销旧提醒。
- 极光默认关闭。APK 的 AppKey 是应用标识，Master Secret 仅服务器加密保存；APK 签名私钥留在本机仓库之外。`accepted` 只表示供应商接收，不表示手机展示；`unknown` 不自动重发。真实厂商后台条件需逐设备验证。
- 真实模型验证属于显式、可能付费的调用，不在 pytest/CI 自动执行。历史 DeepSeek 样例通过不代表当前服务器密钥、手机或持续运行已验收。参考 [安卓独立工程说明](docs/APK_DEVELOPMENT.md)、[多端计划](docs/MULTI_CLIENT_PLAN.md)。

## 7. 代码导航：遇到问题先看哪里

以下 Python 文件路径均相对 `src/personalai/`：

| 文件/目录 | 职责 |
|---|---|
| app.py、__main__.py、runtime.py | FastAPI、CLI、配置优先级、回环监听、Host/Origin/CSRF、登录保护 |
| access.py、admin.py | 密码/令牌哈希、配对、刷新、撤销、初始化/生成主密钥 |
| client_api.py | 客户端查询、命令、历史、同步/SSE/回执、分析与定时授权适配 |
| model_client.py | DPAPI/AES-GCM、模型调用、结构和来源校验 |
| reminders.py、delivery.py | 提醒规则/实例、持久队列、可选极光适配 |
| store.py、models.py、tracking_models.py、extensions.py | Markdown 事件、锁/原子写、幂等、版本与旧格式兼容 |
| tracking.py、tracking_routes.py、configuration.py | 追踪、进度、提案、分区设置及模型绑定 |
| scheduling.py、scheduled_models.py | 定时分析授权、运行锁、报告与来源 |
| plugins.py、integrations.py、quick_entry.py | 可信插件协议、旧只读接口、快捷记录 |
| user_files.py、backup.py | 阅读副本、备份校验与独立恢复 |
| 根目录 frontend/src/AuthGate.tsx、ClientPanel.tsx | 登录、设备/Agent、提醒与推送设置 |
| 根目录 frontend/src/ | 原有总览、记录、设置、分析/报告与插件页面 |
| 外部 PersonalAI_Apk 工程 | 安卓端源码已迁出，见 docs/APK_DEVELOPMENT.md |
| 根目录 scripts/export_client_contract.py | 在临时空目录导出公开契约，不读取真实资料 |
| 根目录 examples/agent_client.py | HTTPS 只读工具示例；隐藏输入令牌，不放 argv/URL |
| 根目录 deploy/ | Caddy/systemd 示例，需按实际环境调整 |

其他设计入口：[配置/兼容](docs/MODULARITY_V0_3.md)、[插件协议](docs/PLUGINS_V1.md)、[旧只读接口](docs/INTEGRATIONS_V1.md)、[资料存储](docs/USER_DATA_STORAGE.md)、[定时分析](docs/SCHEDULED_ANALYSIS.md)、[原有 API](docs/API_V0_2.md)。历史文档中的“未来功能”和测试数量按其日期理解，以当前实现及新的验证证据为准。

## 8. 常见阻碍与处理方向

| 现象 | 首先检查 |
|---|---|
| 只有旧界面/缺少认证接口 | 实际提交是否含 v0.4、前端是否重建、服务是否仍是旧进程 |
| 页面可打开但 API 403 | 实际 Host/Origin 与 public_origin、代理保留的头、网页 CSRF 会话；不要直接关闭检查 |
| 登录后仍 401 | Cookie Secure/SameSite、实际 HTTPS、是否使用了同一个数据目录和已初始化账户 |
| 模型密钥无法解密 | 服务进程的环境变量、主密钥路径/权限、Windows DPAPI 迁移、绑定端点是否变化 |
| 服务启动失败 | 端口占用、账户/父目录权限、配置路径、模板路径是否真实存在 |
| SSE 经代理不更新 | 代理缓冲/超时、凭据、客户端是否按已保存游标补取增量，而非跳过变化 |
| 备份恢复拒绝 | 目标是否已存在、备份是否完整/兼容；不要覆写或修改校验链 |
| 未收到通知 | 先查本地规则/权限/最后同步，再查注册标识、队列与实际供应商结果；不能仅看 accepted |

管理员密码轮换/忘记密码恢复界面、大规模初始快照分块、持续运维和真机体验仍需完善。测试服务器已新增验证旧密码的终端维护脚本 `scripts/rotate_test_owner.py`，并实际完成一次密码更换及 HTTPS 验证；使用与中断恢复见运维手册。遇到相关需求先依据当前代码设计可恢复流程，不手改身份文件绕过认证，不顺带扩展多用户系统。

## 9. 每阶段结束时留下什么

更新 [部署说明](docs/SERVER_DEPLOYMENT.md)、[阶段计划](docs/MULTI_CLIENT_PLAN.md)及带日期的验证记录，并回写本文件的状态。交付内容至少包括：

- 实际代码提交/工作区状态、服务器系统与依赖版本。
- 实际 HTTPS 地址、运行账户、代码/配置/数据/备份路径、服务名称；**不包含密码、令牌、密钥值**。
- 启停、查看脱敏日志、升级、备份、恢复和回滚方法。
- 逐项通过的服务器/跨端检查，使用的测试环境；未验证项、阻碍与最小下一步。
- 正式资料是否迁入，旧环境何时停止写入；哪些设备/Agent 已实际接通。

报告时分别标注“代码已实现”“本地自动验证”“目标服务器验证”“真机/实际供应商验证”。到达当前可验证边界时说明缺少的具体条件，不能用模拟结果补填实际验收，也不要只留一句“继续完善”。
