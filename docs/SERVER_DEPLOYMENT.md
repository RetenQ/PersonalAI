# 单用户服务器部署交接

2026-10-28 服务器接续状态：独立测试环境已上线 **https://personalai.retenq.cloud**，DNS/可信证书及续期演练完成；通过真实域名的登录、配对/授权/确认/同步/SSE/备份恢复/重启与浏览器检查。本人已确认手机浏览器验证通过，真实 APK 仍待配对联调。实际路径和操作见 [运维交接](SERVER_TEST_RUNBOOK.md)，证据和边界见 [公网验证记录](SERVER_VALIDATION_2026_10_27.md) 与 [手机验证记录](SERVER_VALIDATION_2026_10_28.md)。下文通用模板不能代替实际验收结果。

下文保留通用部署模板；当前已安装实例以运维交接记录为准，真实推送未开通。

## 环境与路径

Python 3.12、Node 20.19+ 或 22.12+、HTTPS 反向代理（模板使用 Caddy）。保持一个后端进程、一个服务账户，不启用多个 worker。事件写入有锁，身份/预览/CSRF 等状态不支持跨进程负载均衡。

推荐目录：代码 `/opt/personalai`，正式数据 `/var/lib/personalai/data`，保护密钥 `/etc/personalai/master.key`，实际配置 `/etc/personalai/server.json`。这些路径是部署示例，须按服务器实际情况创建并授权，不能直接把开发机私有文件上传 Git。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m pip install -e . --no-deps
cd frontend
npm ci
npm run build
cd ..
# 以将来运行服务的账户执行，交互输入密码，不写在命令参数/文件中
.venv/bin/python -m personalai.admin --data-dir /var/lib/personalai/data
# 父目录须事先存在；该命令拒绝覆盖已有密钥、拒绝放在仓库内
.venv/bin/python -m personalai.admin --generate-master-key /etc/personalai/master.key
```

密钥文件为 32 字节，Linux 权限 600，只让服务账户读取。它保护各连接与推送密钥，必须另行安全保管；不要放进普通数据备份。丢失后重新填写供应商密钥。Windows 默认继续用当前账户 DPAPI；Windows 加密文件不能直接在 Linux 解密。

实际 `server.json`：

```json
{
  "host": "127.0.0.1",
  "port": 8765,
  "data_dir": "/var/lib/personalai/data",
  "plugins": ["tracking", "journal", "analysis", "dashboard", "exchange"],
  "public_origin": "https://personal.example.com"
}
```

将域名替换为本人控制的域名，设置 DNS。`public_origin` 启用后，即使管理员未初始化也拒绝读取私有 API。代理只转发该域名；Caddy 负责证书与 HTTPS，Python 继续监听回环地址。不要将后端端口转发公网，不信任非回环代理传来的转发头。

模板见 `deploy/Caddyfile.example`、`deploy/personalai.service.example`。部署前逐项核对路径与账户，再安装模板。Caddy 长连接关闭缓冲；服务重启后网页刷新重新建立 CSRF 会话。令牌、密码不得出现在访问日志和 URL 中；模板不启用请求日志。

## 首次配置

1. HTTPS 打开网页并登录，确认未登录读取被拒绝。
2. 在设置保存模型连接和密钥；连接测试只发送内置测试资料。不要默认启用定时分析。
3. APK 填写 HTTPS 根地址，获取八位配对码，在网页设置批准。首台设备默认提醒开启，后续设备默认关闭；仍需手机通知权限。
4. Agent 在网页分别创建范围令牌，独立保管；仅显示一次，可撤销。旧只读令牌不会自动获得新权限。
5. 如需推送，再创建极光应用、构建带 AppKey 的 APK，并在网页保存 Master Secret。服务器默认关闭；服务端密钥不进入 APK。SDK 推送仅尽力送达。

## 恢复与回滚

导出与恢复继续用原备份工具，先恢复到独立目录，校验后再切换配置。备份含正式资料和阅读副本，不含 `.secrets`、`.scheduler`、`.delivery`。恢复后初始化账户、重新配对、重填密钥、重新预览授权自动分析。不可把旧客户端游标当新服务的游标；客户端 410 时重新快照。

部署上线前跑后端与浏览器测试，再以真实 HTTPS 地址验证登录、配对、撤销、SSE、安卓联网和备份；Linux 实际运行、证书续期、运维备份位置与周期、管理员忘记密码的操作流程尚须在服务器上确认。当前无远程密码重置接口，不直接编辑授权文件来绕过校验。
