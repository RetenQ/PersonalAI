# 2026-10-29 服务器更新与 clients/v1 扩展验证

结论：**公网服务器已更新，可供新版 APK 联调。** 后端和网页均已切换并通过实际 HTTPS 检查；设备 Bearer 的五项新能力已在隔离协议测试中验证，尚未用真实 APK 令牌完成新版公网设备验收。不能把管理员 Cookie 检查当成设备验证。

## 实际版本与部署

- 仓库：`RetenQ/PersonalAI`，分支 `main`；fetch 后远端正好是目标 `218c5e7067d98ea498107f8c3675bb121cee08f1`，为本机 `cb404ac` 的后继，无额外更新，使用 `merge --ff-only`。
- 本地 CSS 修改及 14 个未跟踪维护文件升级前保存在 `.cache/upgrade-20261029/local.patch`、`untracked-tools.tar` 与 `baseline.json`；原文件仍保留。没有执行 reset/clean，没有恢复已迁出的 apkProject。
- 发布目录：`/opt/personalai-test/releases/218c5e7-server1`；`/opt/personalai-test/current` 指向该目录。
- 部署窗口：北京时间 **2026-10-29 20:35:11–20:35:20**，服务于 **20:35:19** 启动；短暂停服用于一致性备份及切换。
- Python：`/opt/personalai-test/venv/bin/python`，3.12.13；已将 editable 安装更新到新发布目录，不只是修改符号链接。依赖声明/锁文件未变，`pip check` 通过。
- 服务：`personalai-test.service`，enabled、active/running；审计时 PID 1442176、NRestarts=0，用户 `personalai-test`。PID 是当时观测值，不用于后续启停。
- 服务账户实际导入路径为新目录的 `src/personalai/__init__.py`；运行进程 cwd 同为新发布目录；31 个后端源文件及网页产物与 `deploy/RELEASE_SHA256.json` 一致。基础提交记录在 `deploy/BASE_COMMIT`。
- 仅监听 `127.0.0.1:8765`；浏览器测试用 19765/19766 已退出。继续由原 Nginx 提供 **https://personalai.retenq.cloud**。
- 保留 `/etc/personalai-test/server.json`、服务 unit、Nginx 站点配置、域名/DNS、密钥、管理员密码及原授权。与备份逐项比对通过，现有 35 个事件 SHA-256 均未改变。

## 自动测试与实际检查

所有业务写入测试均使用 pytest 临时目录或 `.cache/browser-e2e`、`.cache/client-e2e` 新目录。未运行会向当前数据追加案例并重启的旧 `validate_test_server.py`。未调用真实模型、启用自动分析/推送或新增提醒。

| 检查 | 结果与范围 |
|---|---|
| Python 3.12 完整回归 | **170 通过，34.61 秒**：上游 164 项加本机 6 项密码维护测试；1 个 Starlette/httpx 弃用警告 |
| 新扩展协议 | 包含 `test_client_extensions.py` 6 项：设备五项 features、角色/范围/插件条件、原子创建/错误目标/幂等/Agent 拒绝、snapshot/changes、动态权限/历史名称、旧修订搜索/来源权限、覆盖日期/安全报告、契约一致性 |
| 其他相关回归 | 原客户端配对/撤销/刷新/旧操作、任务原子事务、同秒历史名称、状态退役、历史搜索、备份/旧事件兼容均包含在完整回归中 |
| 前端组件 | **26 通过，5.77 秒** |
| TypeScript/Vite | 构建通过；产物 `index-DFK7E2dC.js`、`index-CYNCbFYY.css` |
| 隔离网页流程 | **9 通过，45.1 秒**：desktop、phone、small-phone 各跑概述、任务快捷确认和完整记录/回顾/导出流程 |
| 隔离多端网页登录/配对 | **2 通过，8.8 秒**：desktop/phone，真实临时 HTTP 服务、设备 Bearer、Agent 提案和本人确认 |
| 实际 HTTPS 静态资源 | 首页和所有引用的 JS/CSS 内容逐字节等于新发布产物；标准 TLS 信任链，不跳过证书检查 |
| 实际 HTTPS 认证 | 匿名及无效 Bearer 对新读接口和 create_task 写接口返回 401；管理员 Secure/HttpOnly/SameSite 登录、退出通过 |
| 实际 HTTPS 新接口 | 管理员身份的 capabilities、历史查询、任务动态、snapshot/changes、目标创建时间通过；运行时所有模型、请求/参数及成功响应与发布契约匹配 |
| 实际 HTTPS 网页 | **1440px、320px 两种宽度通过**登录、设置、手机配对入口可见、无横向溢出、退出，无页面 JS 异常；退役提醒表单不存在 |
| 运行数据与自动功能 | 新版存储健康；模型 `not_configured`，自动分析未授权/未运行，推送关闭；事件、密码及原设备/Agent 授权未改变 |
| 备份恢复 | 一致性完整快照 + 业务 ZIP；新代码在新目录恢复成功，35 个事件完全一致，业务 ZIP 未恢复认证凭据 |

### 实际 capabilities 的身份边界

公网只读审计使用管理员登录会话，没有生成临时设备或读取/输出用户设备令牌。因此实际返回是 `api_version=1`、`role=owner`：

| feature | 公网 owner 实际值 | 隔离 device Bearer 实际值 |
|---|---|---|
| atomic_task_create_v1 | false（仅 device） | true |
| task_events_v1 | true | true |
| history_search_v1 | true | true |
| report_coverage_v1 | true | true |
| goal_created_at_v1 | true | true |

隔离测试验证 Agent 的 atomic_task_create_v1 为 false、直接 create_task 返回 403，旧 create_record 仍生成待确认提案；tracking/analysis 关闭及范围不足时对应能力变为 false。公网没有可用设备明文凭据，本轮没有新增授权；**真实设备 Bearer 的公网五项 flags、业务写入及撤销验证仍待 APK 端完成**。公网报告当前无样本，补跑覆盖日期/模型名称/地址与密钥不泄露由隔离合成报告测试验证，不将空集合检查说成真实报告验收。

公网请求由本服务器发起，不代表新版已在其他网络或真实手机完成验收。保留上游交接中用户对旧版 APK 基础流程成功的反馈，不要求无故重新配对已有效设备。

### 遇到的问题与处理

1. 首次 Playwright 命令将测试文件误解析为项目名称，测试未启动；修正为 `--project=...` 后 9 项执行通过。
2. 发现旧多端测试和部署网页检查仍引用“回到你的空间”“设备、Agent 与提醒”，而新版为“登录”“设备与 Agent”；更新选择器，退役提醒输入改为明确断言不存在。修复保存在工作区，未删除功能校验或修改业务行为。
3. 首次只读公网审计错误地要求运行时 OpenAPI 与导出 JSON 完全相同，断言失败。检查实现后确认导出器额外增加鉴权说明、错误描述、命令 data schema 等；改为逐项比较全部运行时模型、路由、请求参数/正文和 200 响应，复验通过。完整生成契约一致性已由后端测试单独验证。
4. WebKit 系统依赖不足为既有未验收项，本轮未重复安装或声称通过。后端弃用警告仍保留。

没有为本次上线修改后端业务实现。保留既有 `theme.css` 窄屏修复；新增/修改的仅部署验证工具、测试选择器和交接记录。部署验收阶段未提交或推送；随后用户授权推送，本次提交包含本记录和相关交接文档、CSS 修复、浏览器测试修正以及两份公网验证脚本。旧部署/维护工具继续保留在服务器工作区，运行数据、备份、测试产物及凭据不纳入提交。

## 证据、备份与恢复

受限服务器证据：

- `/var/lib/personalai-test/backups/pre-218c5e7-20261029/deployment.json`：部署时间、代码指向、恢复和配置/事件一致性。
- `/var/lib/personalai-test/validation-upgrade-20261029.json`：20:36:55–20:36:57 的公网只读审计，`success=true`、`events_unchanged=true`、`grants_unchanged=true`、`public_device_bearer_checked=false`。
- `.cache/upgrade-20261029/`：候选源码、原本地修改、固定目标部署/审计脚本；不含明文凭据或运行资料备份。
- `frontend/test-results-upgrade-20261029`、`frontend/test-results-upgrade-clients-20261029`：隔离浏览器产物，忽略 Git；实际公网网页检查不保存截图/trace。
- `scripts/validate_upgrade_readonly.py`：新只读审计工具，仅登录/退出产生认证会话，不写业务数据或创建授权。

升级前备份根目录（root-only）：`/var/lib/personalai-test/backups/pre-218c5e7-20261029/`。

| 内容 | 位置与用途 |
|---|---|
| 完整运行目录快照 | `data/`，包含原身份等私有运行状态，必须按私有备份保护，不上传 Git |
| 业务备份 | `records.zip`，SHA-256 `a22c23d4862886e478e856e31d6172ac845e593e060d1c230baf75974ded881f` |
| 原事件校验 | `events-sha256.json`，35 项 |
| 已恢复副本 | `restored-new-version/`，新代码恢复，仅业务资料，没有认证凭据 |
| 必要配置 | `config/etc/` 下 server.json、systemd unit、Nginx 站点配置 |
| 原 Python 环境 | `venv/`，升级前完整副本 |
| 原可用发布 | `/opt/personalai-test/releases/27c342b-server2`，保留未覆盖 |

主密钥及管理员加密凭据保持原路径不变，不进入业务 ZIP。完整快照含私有授权状态，父目录权限 0700；备份、密钥和凭据限制权限通过审计。

再次校验业务备份（只恢复到临时目录，不切换服务）：

```sh
/opt/personalai-test/venv/bin/python -m personalai.backup \
  /var/lib/personalai-test/backups/pre-218c5e7-20261029/records.zip
```

如需另行恢复，使用 `--restore-to` 指定**尚不存在**的新目录，绝不覆盖 `data/` 或上述已验收恢复目录。

代码回滚：先停止 `personalai-test`，保留故障现场和升级后新增数据，比较当前事件与升级前清单。只有确认无新增事件/兼容性风险后，才用原 venv 执行 `pip install --no-index --no-build-isolation --no-deps -e /opt/personalai-test/releases/27c342b-server2`（安装 umask 022，确保服务账户可读），将 `current` 切回旧目录，启动并复验。不能只改链接。若已有新版写入，不直接退代码继续写当前数据；先备份新增数据，在新目录核验所选代码/数据组合，再明确切换。完整环境副本可供修复损坏 venv，保留故障环境，不直接覆盖唯一副本。本轮验证了备份恢复，没有执行一次真实旧版回切演练。

## APK 下一步

1. 根地址仍为 **https://personalai.retenq.cloud**，协议前缀 `/api/clients/v1/`，OpenAPI 文档版本仍为 **1.0.0**，扩展交接日期 **2026-10-29**，服务器基础提交 **218c5e7**。
2. APK 在独立工程维护（见 `docs/APK_DEVELOPMENT.md`）。复制本提交的 `docs/openapi.clients.v1.json`、`docs/AGENT_API.md`、`docs/APK_CLIENT_EXTENSIONS_2026_10_29.md` 更新协议快照；无需复制后端或恢复 apkProject。
3. 已配对设备先刷新令牌/重新连接，再用 **设备 Bearer** 获取 capabilities。具备相应 scopes、插件启用时五项应为 true；缺字段、缺键或 false 按不支持降级，不能只看 api_version。管理员的 atomic=false 不代表设备功能不可用。
4. 使用独立测试资料验证一次 create_task 原子目标关联、同 request_id 重试、snapshot/changes、历史动态/旧修订检索；确认错误目标不留任务、Agent 不越权。旧客户端保留旧操作；当前状态 states 已退役，旧事件留存归档。
5. 真实设备验证不得混入现有个人记录。先确定独立联调数据环境再执行写入/撤销测试；当前公网主实例本轮只读验收。报告/提醒的真实样本及时间、模型和推送另外授权验收。
6. 回传设备的五项 flags、APK 构建版本、设备/系统与失败步骤（不含令牌）。新版公网设备验证完成后更新本记录，不能提前写“真机已通过”。
