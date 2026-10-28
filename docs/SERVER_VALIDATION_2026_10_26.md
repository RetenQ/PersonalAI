# 2026-10-26 服务器部署与验证记录

后续状态：2026-10-27 已完成 DNS、公网可信 HTTPS 和续期演练，并通过真实域名业务验收，见 [次日验证记录](SERVER_VALIDATION_2026_10_27.md)。下文保留 10 月 26 日的执行过程与当时阻塞。

本记录区分目标服务器自动测试、实际服务验收和外部设备验收；不引用 Windows 通过结果作为 Linux 证明。仅使用独立测试资料，不迁移私人资料。

## 阶段 A：接手与环境检查

- 完整仓库 `/root/PersonalAI`，main，提交 `27c342b1829f4b60447b4835f9307faa1530675e`；远端 main 核对一致，初始工作区干净。未发现适用的 AGENTS.md。
- 系统 OpenCloudOS 9.4；原有 `.venv` 为 Python 3.13.9（交接推荐 3.12），Node 24.22.1 / npm 11.19.1。
- 首检根盘可用约 7.5 GiB；内存可用约 776 MiB，保留已有服务，构建与浏览器采用有限并发。
- 现有 Nginx 使用 80/443，已有站点及其他服务；8765、19765、19766 首检未占用。后端保持回环监听。
- 现有 Python 锁定依赖全部匹配，`pip check` 通过；pywin32 平台条件在 Linux 生效。
- 现有依赖下前端 18 项单测通过，TypeScript/Vite 构建通过；后续完成了以下干净安装复核。
- 沙箱不能读取系统 socket/systemd，后端 pytest 沙箱执行未完成，已中止；获准系统环境重跑 Python 3.13：151 passed / 20.91s。新增系统 Python 3.12.13，独立 `.cache/venv312` 回归：151 passed / 24.03s；均有一条上游 TestClient 弃用提示。
- 系统默认腾讯 pip/npm 镜像分别超时/ECONNRESET；显式采用官方源成功，未修改系统镜像配置、依赖锁或版本。Python 3.12 `pip check` 通过；`npm ci` 后前端 18 项 / 3.85s，构建通过。

## 阶段 B：部署

- 已创建系统账户 `personalai-test`（nologin）、代码发布目录 `/opt/personalai-test/releases/27c342b-server1`、`current` 链接及 Python 3.12 独立 venv。完整交接源码通过 git archive 安装，另附构建网页；原工作区和 `.venv` 保留。
- 完成窄屏修复后新建 `27c342b-server2`，`current` 和 venv editable 安装均已切换到该发布目录；保留 server1。发布目录记录基础 commit、CSS 补丁及构建 SHA-256。工作区新增运维/验收脚本和文档，未提交/推送；后端业务源码未改动。
- 已创建 `/var/lib/personalai-test/data` 和 `backups`（0700，服务账户所有）；`/etc/personalai-test/server.json`（0640）及仓库/数据目录外 32 字节 `master.key`（0600，服务账户所有）。
- 随机管理员密码已初始化，原始值仅在进程内存和初始化管道中使用；加密副本为 root-only `/etc/personalai-test/owner-password.cred`，用 systemd host key 保护，不进入日志/文档/Git。该保护不等于磁盘加密；主机 root 可解密。
- 已启用 `personalai-test.service`，专用非特权账户、单进程、ProtectHome/ProtectSystem、UMask 0077；实际监听 `127.0.0.1:8765`，首检 NRestarts=0。
- 新增 Nginx `/etc/nginx/conf.d/personalai-test-local.conf`，仅监听 `127.0.0.1:18443`，保持 SSE 无缓冲，禁用访问日志。`nginx -t` 通过后平滑重载；原有站点配置未修改。
- 当前 `public_origin=https://localhost:18443`，使用 30 天自签名 localhost 证书，仅供服务器本机 TLS 验收；它不是公网/手机可用地址。探测使用显式 CA 校验，未使用 `verify=False`。重载后的首次即时请求连接拒绝，完成就绪后 `/api/auth/status` 返回 configured/required=true。
- 实际域名与访问范围待用户确认，之后才能配置公网证书和 APK 地址。现有站点证书不覆盖子域名，且 2026-10-27 22:59:59 UTC 到期，未擅自修改已有业务证书。

## 阶段 C：服务与浏览器验收

`scripts/validate_test_server.py` 仅允许独立测试目录，凭据内存解密。实际 systemd 服务和 Nginx TLS 入口验证完成；最终 server2 验收时间为北京时间 15:28:44–15:28:48。此项是目标服务器本机真实服务验收，不是外网、真机或实际 Agent 工具接入证明。

| 实际服务检查 | 结果 |
|---|---|
| HTTPS 登录与私有 API | 通过；未登录 401、错误 Host/Origin 403、缺 CSRF 403、Secure/HttpOnly/SameSite Cookie |
| 私有文件/源码静态访问 | 通过；不会下载数据、密钥、源码或 Git 配置 |
| 两台协议设备配对 | 通过；批准前 pending、批准后一次性领取、重复领取拒绝；自动验收设备已撤销 |
| Agent 范围 | 通过；未授权画像/设置、确认、管理接口拒绝；不会绕过本人审批 |
| 追加与确认 | 通过；固定请求编号去重，任务先待确认，拒绝无正式写入，本人批准后双方可读 |
| 版本冲突 | 通过；两个相同预期版本提案，一次成功，另一 409，已确认进度未被覆盖 |
| 同步 | 通过；快照合并增量等同新快照；错误/跨设备游标 410，sync/ack 成功 |
| SSE 经 Nginx HTTPS | 通过；5 秒内收到无缓冲心跳、变更提示、断开后重连；凭据不放 URL |
| 令牌轮换/撤销 | 通过；旧 refresh 拒绝，撤销后读、写、刷新均 401 |
| systemd 重启 | 通过；原文、修订与撤销仍生效，旧 CSRF 拒绝，重新获取会话成功 |
| 备份与恢复 | 通过；真实 HTTP 导出/校验、服务账户新目录恢复、20 个事件逐文件校验一致；无身份/自动调用授权，拒绝覆盖已有目录 |
| 主密钥/权限 | 通过；实际服务账户用独立主密钥 AES-GCM 往返与端点绑定；密文不含测试明文 |
| 安全默认状态 | 通过；模型未配置，推送关闭，定时分析未授权/未启用，时间列表为空；全部测试客户端已撤销 |

最终无密钥验收证据：`/var/lib/personalai-test/validation-SERVER-VALIDATION-7c69e163a80d.json`，`success=true`、`cleanup_ok=true`。恢复产物、校验值和操作命令见 [运维手册](SERVER_TEST_RUNBOOK.md)。

浏览器使用单 worker、独立 19765/19766 数据目录，原配置选用原 `.venv` Python 3.13；另有上面的 3.12 实际服务验收。Playwright 1.64.1 / Chromium 156.0.8078.4（revision 1248）。

| 浏览器批次 | 结果与范围 |
|---|---|
| 首轮 Chromium 5 个设备配置 | 13 通过、3 失败；失败均为 320px 横向溢出，保留 `frontend/test-results-initial-linux/` |
| 真实问题定位 | 长模型选项使 grid/flex 中 label 默认 min-width:auto 撑开；可复现 LABEL/SELECT 宽度 290px 超出容器，另外影响背景表单检查 |
| 修复 | `frontend/src/theme.css`：label min-width:0，表单控件 max-width:100%；未关闭/削弱测试断言 |
| 修复后定向回归 | 10/10，通过原失败 small-phone 3 项、desktop 3 项、android-pixel 4 项（含触控旋转）；`frontend/test-results-linux-fixed/` |
| 多端网页联调 | desktop/phone 2/2，通过登录、批准配对、Agent 提案、本人确认、两种调用方读取一致、退出；`frontend/test-results-linux-clients/` |
| 实际部署 HTTPS 浏览器 | 1440px / 320px 两种尺寸登录、设置、退出均通过，无页面异常，提醒时间保持空；`scripts/validate_test_web.mjs` |
| WebKit | 实际启动失败 1 项，另 2 项未运行；缺 GTK4/GStreamer/libjpeg.so.8/libavif.so.16 等 Ubuntu 回退版本依赖。未计为通过，未禁用依赖检查；`frontend/test-results-linux-webkit/` |

API TLS 验收使用测试 CA 完整校验；本机 Chromium 固定信任该证书的特定公钥。两者都不能证明公网 CA 信任或外网可达。

## 阶段 D：最终状态与交接

- `nginx -t` 通过；PersonalAI、Nginx 和首检已有的业务/浏览器服务仍 active。8765、18443 只监听回环，19765/19766 临时服务已退出。最后检查 NRestarts=0；未对整机做重启测试，未宣称长期稳定性已验收。
- 新服务及代理日志未出现初始密码或 Authorization/Bearer 字段。最终根盘可用约 6.3 GiB，没有删除现有业务资料。
- 启停、管理员密码私有终端领取、备份恢复、公网启用与 APK/Agent 接入步骤已写入 [服务器测试运维手册](SERVER_TEST_RUNBOOK.md)。

## 尚未验收

后续用户已确认允许公网登录；2026-10-26 复核到 DNSPod NS、根域名 A=`118.25.174.125`，`personalai.retenq.cloud` 与 `ai.retenq.cloud` 尚无公共解析。已推荐前者，并准备未启用的 Nginx/public_origin 文件；目前等待域名解析操作，不再把访问范围列为待确认事项。

用户要求代办并继续后：已实际启用该子域名的 HTTP-01 专用入口，本机挑战文件验证通过，其他 HTTP 路径返回 503；Nginx 与 PersonalAI 保持 active。已完成 DNS 授权可用性检查，当前无可用授权；实例角色入口访问被断开，不推断角色实际是否存在。安全终端 DNS 工具及独立 SDK 环境已准备，6 项离线测试通过，真实 DNS 写入/公网证书仍未执行。详见运维手册的隐藏输入命令。

**公网受信任 HTTPS 及外部设备可达仍被实际域名/DNS 缺项阻塞**。最小下一步：为推荐子域名添加 DNS 记录，或提供最终域名，然后安装该域名证书与独立 Nginx 站点、切换 public_origin，并从另一台已授权设备复验。

WebKit、真实 APK/实际 Agent 工具、真机离线/锁屏/重启/提醒、真实推送、模型调用、证书续期、长期运行仍未验收。模型/推送凭据不是当前部署阻塞。没有迁入正式资料或创建周期任务；正式迁移需另行提供私有备份位置并遵循新目录恢复与停写切换流程。
