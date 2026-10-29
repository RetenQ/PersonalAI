# 测试服务器运维与多端交接

更新时间：2026-10-28。这是已经安装的独立测试实例，不是正式资料环境。手机浏览器本人实测确认见 [10 月 28 日记录](SERVER_VALIDATION_2026_10_28.md)，公网部署进展见 [10 月 27 日记录](SERVER_VALIDATION_2026_10_27.md)，Linux 回归见 [10 月 26 日记录](SERVER_VALIDATION_2026_10_26.md)。

## 实际入口与版本

| 项目 | 实际值 |
|---|---|
| 当前 HTTPS | `https://personalai.retenq.cloud`，允许公网登录；Let's Encrypt 可信证书 |
| DNS | `personalai.retenq.cloud CNAME retenq.cloud`，已添加并公共查询确认 |
| 基础代码 | main / `27c342b1829f4b60447b4835f9307faa1530675e`，接手时远端一致 |
| 部署版本 | `27c342b-server2`，基础代码加 `frontend/src/theme.css` 的窄屏修复；后端业务代码未修改 |
| 工作区 | `/root/PersonalAI`；本次 GitHub 同步交接文档，源码修复、部署模板、维护脚本和测试仍未提交 |
| 当前源码 | `/opt/personalai-test/current` → `/opt/personalai-test/releases/27c342b-server2` |
| 前版保留 | `/opt/personalai-test/releases/27c342b-server1` |
| 运行环境 | `/opt/personalai-test/venv`，系统 Python 3.12.13；editable 安装完整源码，含构建网页 |
| 服务 | `personalai-test.service`，开机自启，账户 `personalai-test`，单进程 |
| 后端监听 | `127.0.0.1:8765` |
| 配置 | `/etc/personalai-test/server.json`，`public_origin=https://personalai.retenq.cloud` |
| 数据 | `/var/lib/personalai-test/data`，0700；只含标记为 SERVER-VALIDATION 的测试案例 |
| 备份 | `/var/lib/personalai-test/backups`，0700；没有周期任务/预设保留期限 |
| 主密钥 | `/etc/personalai-test/master.key`，32 字节，0600，服务账户所有；单独保管 |
| 管理员凭据 | `/etc/personalai-test/owner-password.cred`，root-only 的 systemd host-key 加密副本 |
| Nginx | `/etc/nginx/conf.d/personalai-test-public.conf`，80 → HTTPS，443 → 回环后端；原有站点未改写 |
| HTTPS 证书 | `/etc/letsencrypt/live/personalai.retenq.cloud/`；到期 2027-01-24 23:16:29 UTC |
| 证书续期 | `personalai-cert-renew.timer`；每日两次检查，仅处理本域名；成功后校验并重载 Nginx |
| 系统服务文件 | `/etc/systemd/system/personalai-test.service` |
| 构建校验/补丁 | 当前发布目录的 `deploy/BUILD_SHA256`、`deploy/BASE_COMMIT`、`deploy/server-layout.patch` |

未导入私人画像或正式资料；没有安装 Android 工具链。当前管理员已初始化，密码没有写入 Git、文档、请求 URL 或日志。

本文中的新增维护脚本及部署模板位于服务器工作区，本次文档提交未包含这些实现文件；仅从 GitHub 拉取本次提交不会获得它们。已有服务继续使用当前发布目录，不因文档同步重启或切换。

## 登录凭据领取

由服务器管理员在**自己的私有 SSH 终端**运行下列命令，把输出保存到密码管理器。不要把输出发给 AI、复制到聊天、提交文件或录屏日志。

```sh
sudo systemd-creds decrypt --name=owner-password /etc/personalai-test/owner-password.cred -
```

该加密文件绑定本机 `/var/lib/systemd/credential.secret`，不等于磁盘加密，也不是应用备份的一部分。主机 root 能解密。应用仍只有密码哈希；现有管理员初始化工具拒绝覆盖账户。当前没有密码轮换/忘记密码网页界面，不能手改身份文件绕过认证。将来正式环境应在新的正式数据目录单独初始化本人选择的密码。

2026-10-27 已按本人要求更换测试实例密码；新密码通过公网 HTTPS 登录验收，旧密码和旧网页登录会话失效，加密副本已同步。密码值不记录于此。后续可在私有 SSH 终端运行维护脚本，隐藏输入两次新密码：

```sh
cd /root/PersonalAI
sudo /opt/personalai-test/venv/bin/python scripts/rotate_test_owner.py
```

脚本仅用于当前测试实例，读取加密保存的旧密码并验证，以服务账户在应用原有身份锁和原子写事务内更换哈希；清除网页登录会话及未完成配对，保留已授权设备/Agent。无须重启服务。至少 12 位，最多 256 位；不会把密码写入参数、普通文件或日志。

若进程中断留下 `/etc/personalai-test/owner-password.pending.cred`，脚本会拒绝再次执行。该文件是新密码的主机加密副本；保留它与当前 `.cred`，由维护人员在私有终端验证哪份凭据可登录，再将对应加密文件原子切换为 `owner-password.cred`。不删除身份文件、不重新初始化账户、不向日志输出解密结果。

## 启停、健康与日志

```sh
sudo systemctl start personalai-test
sudo systemctl stop personalai-test
sudo systemctl restart personalai-test
sudo systemctl status personalai-test --no-pager
sudo journalctl -u personalai-test -n 50 --no-pager
sudo nginx -t
```

本机 HTTPS 存活探测必须校验证书：

```sh
curl --noproxy '*' --fail --silent --show-error \
  https://personalai.retenq.cloud/api/auth/status
```

此状态只证明认证入口存活。数据健康还需登录后读取 `/api/status`，确认 `storage.healthy=true`，并核对实际记录。重启后网页刷新获取新的 CSRF 会话。服务加载时可能短暂出现 502，须等就绪再验收；不要用同时运行第二个后端进程来规避。

Nginx 访问日志关闭，错误日志为 `/var/log/nginx/personalai-test-error.log`。最终检查未发现初始密码或 Authorization/Bearer 字段。不要开启带请求正文/授权头的调试日志。

## 备份与恢复

正常使用已登录网页的“备份与恢复校验”导出，并把下载文件移至受保护目录。备份是明文资料，不能放入公网静态目录。应用导出会在临时目录恢复校验；它不含 `.secrets`、`.scheduler`、`.delivery`，不会恢复管理员/设备/Agent 凭据、模型/推送密钥或自动调用许可。

本轮已验证的备份：`/var/lib/personalai-test/backups/20261027T082004-f242c2.zip`。

- SHA-256：`00b3dd9025dbe9187ccd4a3c277a228938541d0ce41a1c8dba52ed29948d9557`
- 已恢复到 `/var/lib/personalai-test/restore-validation-20261027T082004-f242c2`，30 个事件逐文件 SHA-256 一致。
- 再次恢复到同一目录被拒绝；身份和自动调用授权未恢复。

手动复核与另行恢复（恢复目标必须尚不存在）：

```sh
cd /opt/personalai-test/current
sudo -u personalai-test /opt/personalai-test/venv/bin/python -m personalai.backup \
  /var/lib/personalai-test/backups/20261027T082004-f242c2.zip
sudo -u personalai-test /opt/personalai-test/venv/bin/python -m personalai.backup \
  /var/lib/personalai-test/backups/20261027T082004-f242c2.zip \
  --restore-to /var/lib/personalai-test/restored-manual-new
```

恢复不会自动切换当前服务。正式迁移必须按 [AI_READ.MD 第 5 节](../AI_READ.MD#5-正式资料迁移与回滚) 保留原件、核验新目录、初始化正式账户、明确停写点后切换；不把测试目录当正式资料。加密主密钥要独立安全保存，不能加入普通资料 ZIP；Windows DPAPI 密文不能直接迁来解密。

## 公网 DNS、证书与续期

公网入口已完成：`https://personalai.retenq.cloud`。DNSPod 的 CNAME `personalai` → `retenq.cloud` 已创建并回查，公共 DNS 同样确认；根域名 A 为 `118.25.174.125`，没有 AAAA。网页、APK 与 Agent 共用这个 HTTPS 根地址。

实际配置源码为 `deploy/personalai-public.nginx.conf`、`deploy/personalai-public.server.json`，对应已安装的独立 Nginx 站点和 public_origin。HTTP-01 webroot `/var/lib/personalai-acme` 继续开放；其他 HTTP 路径跳转 HTTPS。旧 `localhost:18443` 自签名入口已停用并归档到 `/etc/personalai-test/pre-public-20261027/local-https.conf.disabled`，该目录也保留切换前配置及原站点校验值。

证书续期通过 HTTP-01 完成，不需要 DNS API 密钥。系统原有 `certbot-renew.timer` 未启用，本次新增仅处理 PersonalAI 证书的 `personalai-cert-renew.timer`，每日两次检查、随机延迟，错过的检查可补执行。成功更新后 `/usr/local/libexec/personalai-cert-reload` 校验并平滑重载 Nginx。真实 staging 续期演练与重载钩子已经通过；未来每次续期仍应查看实际状态。

```sh
sudo systemctl list-timers personalai-cert-renew.timer
sudo systemctl status personalai-cert-renew.service --no-pager
sudo journalctl -u personalai-cert-renew.service -n 50 --no-pager
sudo certbot renew --cert-name personalai.retenq.cloud --dry-run \
  --no-random-sleep-on-renew --run-deploy-hooks --no-directory-hooks \
  --deploy-hook /usr/local/libexec/personalai-cert-reload
```

本次 DNS 授权仅在隐藏终端和进程内存中使用，未写入配置、项目或运行日志；凭据在聊天中出现过，用户应撤销/轮换。撤销该 API 密钥不会影响已创建的解析或 HTTP-01 续期。DNS 工具 `scripts/configure_public_dns.py` 和独立 `.cache/dns-venv` 可保留作为运维工具，没有保存授权。

原 `retenq.cloud` 业务配置校验一致，证书和续期设置未修改。原证书仍于北京时间 **2026-10-28 06:59:59** 到期，需另行处理；它与 PersonalAI 独立证书的有效期无关。

已通过服务器发起的真实域名请求及浏览器验收；服务器网络存在代理/Fake-IP。2026-10-28 本人确认手机浏览器验证通过；设备型号、浏览器版本及网络类型未提供，不推定使用手机流量，不扩展为所有外部网络或完整真机业务流程通过。下一步为实际 APK 配对与同步联调。

## APK 配对与 Agent 接入

向本机开发方交付 **HTTPS 根地址 `https://personalai.retenq.cloud`**，协议为 `v1`，前缀 `/api/clients/v1/`。APK 在本机 `E:\CodexProject\PersonalAI_Apk` 开发/构建，不把服务器管理员密码放入 APK。

1. APK 填 HTTPS 根地址并申请配对，显示八位配对码。
2. 本人登录网页 → 设置 → 设备、Agent 与提醒 → 填入码并批准。
3. APK 轮询领取一次性结果并安全保存设备令牌；验证 `capabilities`、`snapshot`，提交一条明确标记的测试日志，在网页核对。
4. 用测试任务检查差异确认、拒绝及冲突；撤销设备后读写/刷新应失败。验收后不继续使用本轮自动测试生成的凭据，它们已全部撤销。

Agent 在网页单独创建最小范围授权，起步只选所需的 `read:*`；确有需要才加入 `write:records` 与 `propose`，默认不授权私人画像。令牌只通过调用方的私有凭据入口保存，使用 `Authorization: Bearer ...`，禁止放进 URL/模型上下文。参阅 [Agent 协议](AGENT_API.md)、[OpenAPI](openapi.clients.v1.json)、[只读示例](../examples/agent_client.py)。Agent 可以追加允许的记录和提出修改，不能批准提案、管理密钥或触发模型。

写入使用固定 UUID 请求编号；相同提交重试不变更编号/正文。修改带 `expected_version`，409 重新预览；410 重新快照并保留离线草稿。SSE 只提示取数，不能把通知游标直接写进缓存而跳过增量。

真机安装、离线缓存/草稿、软键盘、锁屏/重启、通知权限及厂商后台行为仍待本机开发方与真实设备共同验收。没有预设提醒时间、开启真实推送或模型调用。

## 复验与升级

工作区回归：

```sh
cd /root/PersonalAI
.cache/venv312/bin/python -m pytest -q
cd frontend
npm ci --registry=https://registry.npmjs.org
npm test
npm run build
npx playwright test --project desktop --project tablet --project phone --project small-phone --project android-pixel
npx playwright test --config playwright.clients.config.ts
```

Playwright 自带配置目前使用原 `.venv`（Python 3.13），后端 3.12 回归与实际 systemd 验收单独执行。WebKit 因本系统库依赖不足启动失败，不能计入通过项；可在受支持的独立测试环境补验，不能关闭依赖校验冒充通过。

实际部署验收（会向测试目录追加案例、临时授权并重启测试服务）：

```sh
cd /root/PersonalAI
sudo /opt/personalai-test/venv/bin/python scripts/validate_test_server.py
sudo node scripts/validate_test_web.mjs
```

现在两种验收均使用真实公网域名和标准证书信任链，不传 localhost CA，不跳过 TLS 错误。脚本读取实际 `public_origin`；服务器发起的浏览器模拟不代替用户手机/实际 Agent 联调。

升级前保留工作区差异、记录当前发布目录与数据备份；新版本在新的发布目录构建/测试。当前 editable 安装实际指向某个发布目录，**只改 current 链接不够**，须把 venv 的 editable 安装切换到新源码并重启。前版留存仅表示可供核验，不能忽略事件版本兼容性直接退代码。故障时先停止写入，保留新增事件，在新目录验证备份，再切到已核验的代码/数据组合。
