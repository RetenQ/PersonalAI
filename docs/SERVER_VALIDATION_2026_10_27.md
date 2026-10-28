# 2026-10-27 公网 HTTPS 部署验收

基础发布版沿用 `27c342b-server2`（v0.4 + 已验证窄屏修复），本轮不更改后端架构或导入正式资料。此前 Linux/本机测试见 [2026-10-26 记录](SERVER_VALIDATION_2026_10_26.md)。

## DNS 与证书

- 用户已授权公网登录及 DNS 代办。已用隐藏终端输入将授权仅用于本次 DNS 操作；没有把凭据写入项目、配置、命令参数或运行日志。由于凭据由用户在聊天中提供，已建议撤销/轮换；后续续期不依赖该凭据。
- DNSPod 成功创建并回查 `personalai.retenq.cloud CNAME retenq.cloud`；公共 DNS 同样确认，TTL 600。根域名 A 为 `118.25.174.125`，没有 AAAA。未修改根域名或其他记录。
- 使用既有 ACME 账户和独立 HTTP-01 webroot `/var/lib/personalai-acme` 签发新证书。证书路径 `/etc/letsencrypt/live/personalai.retenq.cloud/`，SAN 仅新域名，颁发者 Let's Encrypt YE2；有效期 `2026-10-26 23:16:30 UTC` 至 `2027-01-24 23:16:29 UTC`。
- 原站点配置 `/etc/nginx/conf.d/retenq.cloud.conf` 的 SHA-256 切换前后相同。原站点证书未改动。

## 公网配置

- 实际 HTTPS：`https://personalai.retenq.cloud`；`public_origin` 已设为此根地址。HTTP 除 ACME 挑战外均 301 跳转 HTTPS。
- 新站点 `/etc/nginx/conf.d/personalai-test-public.conf` 复用 80/443，后端仍仅 `127.0.0.1:8765`、单进程和专用账户。访问日志关闭、保留 Origin/Host/CSRF、代理禁用 SSE 缓冲。
- 切换前的配置保存在 `/etc/personalai-test/pre-public-20261027`。首次探测在 Nginx 平滑重载完成前见到旧证书，随后重试成功，未禁用 TLS 校验。
- 真实域名 curl（不使用 `--resolve`，不跳过 TLS）返回公开认证状态正常、私有记录 401、HTTP 301；TLS 验证结果 0。本机网络存在代理/Fake-IP（连接地址显示 198.18.0.84），此结果不冒充用户手机直连验收。
- 外部网页抓取工具无法访问该 URL，未取得独立外部 HTTPS 验收证据。HTTP-01 的 CA 验证成功，但它不能代替手机 HTTPS/应用验收。

## 自动续期与业务验收

Certbot 输出自动续期提示，但实际发现系统 `certbot-renew.timer` disabled；不能据输出宣称已启用。已新增仅针对本域名的 `personalai-cert-renew.service/.timer`，每日两次检查并随机延迟；成功续期调用 `/usr/local/libexec/personalai-cert-reload` 校验并平滑重载 Nginx。既有系统通用 timer 未启用，避免接管其他站点证书。

- `certbot renew --cert-name personalai.retenq.cloud --dry-run --run-deploy-hooks --no-directory-hooks --deploy-hook /usr/local/libexec/personalai-cert-reload` 返回成功；staging 验证和重载钩子都执行成功，正式证书未被测试证书替换。Nginx 的成功提示写到 stderr，被 Certbot 标记为 hook error output，但进程退出码为 0，无实际失败。
- 演练默认先随机等待约 135 秒，后续交互演练可加 `--no-random-sleep-on-renew`；自动任务保留自身随机延迟。timer 已 enabled/active，首次计划检查北京时间 2026-10-27 12:37:37。未来实际续期仍需运维观察。
- 旧 localhost:18443 入口已停用并归档，当前只使用新公网域名；8765 仍仅回环监听。原站点配置 SHA-256 再核验一致。

公网 API 验收于北京时间 08:19:59–08:20:05 执行，全部通过：

| 检查 | 结果 |
|---|---|
| 登录、Cookie、Host/Origin/CSRF | 通过；标准 TLS 信任链，匿名私有 API 401、无效来源/CSRF 403 |
| 静态文件保护 | 通过；源码、身份文件、私人目录不可下载 |
| 两台协议设备配对、Agent 最小范围 | 通过；一次性领取、越权读取/确认/管理拒绝 |
| 记录与确认 | 通过；幂等追加、待确认/拒绝/本人批准，竞争确认 409 |
| 同步及 HTTPS SSE | 通过；快照/增量一致、游标隔离与 410、ack、心跳/变更/重连 |
| 令牌撤销 | 通过；刷新轮换、旧令牌拒绝，撤销后读写/刷新全部拒绝 |
| 服务重启 | 通过；历史、撤销持久保留，旧 CSRF 拒绝，重新获取成功 |
| 备份恢复 | 通过；真实 HTTP 导出/校验、服务账户恢复新目录，30 个事件一致，身份/授权不恢复，重复恢复拒绝 |
| 收尾 | 通过；测试设备和 Agent 全部撤销，模型/推送/定时分析保持关闭，无预设提醒时间 |

证据：`/var/lib/personalai-test/validation-SERVER-VALIDATION-6dda9ced5479.json`，`success=true`、`cleanup_ok=true`。备份 `/var/lib/personalai-test/backups/20261027T082004-f242c2.zip`，SHA-256 `00b3dd9025dbe9187ccd4a3c277a228938541d0ce41a1c8dba52ed29948d9557`；恢复目录 `/var/lib/personalai-test/restore-validation-20261027T082004-f242c2`。

收尾复核：远端 main 仍为 `27c342b1829f4b60447b4835f9307faa1530675e`；应用与 Nginx active，应用和专用证书 timer 均 enabled。工作区改动文件中的凭据 ID 扫描、文档链接和 `git diff --check` 通过；没有把本次 DNS 凭据持久化到项目或运行配置。

实际公网域名浏览器：1440px 与 320px 登录、设置、退出均通过，无页面异常，提醒时间保持空。未使用 localhost 公钥例外或 `ignoreHTTPSErrors`。最终 `personalai-test.service` active/running、NRestarts=0，单进程回环监听。

## 交付与尚未完成

### 管理员密码更换补充验收

按本人明确要求新增 `scripts/rotate_test_owner.py`，使用隐藏终端输入，校验原密码后调用现有 `Access.change` 锁定事务更新哈希，不修改运行中的后端业务代码。`tests/test_owner_rotation.py` 的 6 项隔离测试通过（1.24 秒）：新旧密码、旧会话撤销、未完成配对清除、已授权客户端保留、无效输入不修改身份、未初始化账户拒绝。

服务器实际执行退出码 0：真实域名标准 TLS 下新密码登录成功、旧密码返回 401、旧网页登录会话读取返回 401；存储健康、事件文件逐项 SHA-256 不变，root-only 加密凭据已同步并解密比对通过。验证所用新会话已退出，无须服务重启。密码未写入文档、源文件、命令参数或程序输出。操作与中断恢复说明见运维手册；此项不代表新增网页密码更换入口。

可交付网页/APK/Agent 统一根地址 **https://personalai.retenq.cloud**；协议 v1。管理员密码在受保护 SSH 终端通过 systemd-creds 领取，配对及启停/恢复操作见 [运维手册](SERVER_TEST_RUNBOOK.md)。没有迁入正式资料，工作区修改保留未提交/未推送。

真实手机及不同外部网络、实际 Agent 工具接入、WebKit 环境依赖、长期运行和未来自动续期结果仍待验收。没有调用真实模型或推送供应商，不宣称真机运行/通知送达。原站点证书即将到期的问题未纳入本次修改，应另行处理；本域名证书和续期已独立配置。
