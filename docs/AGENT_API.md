# PersonalAI Client API v1：给 APK 和工具型 Agent

2026-10-29 客户端扩展：新增 `features`、设备 `create_task`、`task-events` 与全历史查询；补齐报告覆盖日期。请求/响应、权限、分页和降级规则见 [APK 协议扩展交接](APK_CLIENT_EXTENSIONS_2026_10_29.md)。历史内容以下述扩展规则为补充；不代表服务器已部署。

基地址：由用户提供的 HTTPS 根地址。前缀 `/api/clients/v1/`。参考契约：[openapi.clients.v1.json](openapi.clients.v1.json)。这里的示例是协议示例，不是用户真实生活记录。

2026-10-28 本地修订：当前状态功能已退役，不再提供 `states` 资源、`read:states` 授权或 `kind=state` 提交。旧状态事件只保留归档与备份；含该范围的旧定时分析暂停，需重新预览授权。现有其他业务协议保持不变；服务器是否已更新以实际部署版本为准。

## 身份与权限

请求头 `Authorization: Bearer <独立令牌>`。禁止把令牌放在 URL、Git、工具日志或模型上下文中。Agent 令牌由已登录网页创建，仅显示一次，90 天有效，可撤销；APK access token 15 分钟，refresh token 30 天，刷新时轮换，旧 refresh token 立即失效。实际有效期以服务器响应为准。

Agent 可按需获授 `read:goals/tasks/records/logs/checkins/reports/pending/reminders/profile`、`write:records`、`propose`。`profile` 默认不选。Agent 永远没有 `confirm/settings/reminders/analysis` 操作权限，不可使用本人网页 Cookie 来绕过限制。旧 `/api/integrations/v1/` 令牌只用于原来的只读 API，不自动升级。

设备配对：`POST pairings {name}` 返回 `pairing_id/code/poll_secret`，十分钟有效。本人登录网页批准 code 后，`POST pairings/poll {pairing_id,poll_secret}` 返回 `pending` 或 `paired` 和令牌，只能领取一次。轮询凭据只放请求正文。不要连续高频创建配对；每分钟最多五次。

`GET capabilities` 返回当前调用方、实际 scopes、时区、通知开关与协议版本。服务器决定角色与审计来源，输入不能包含伪造的 actor、owner 或 confirmed 字段。设备凭据由 Android Keystore 加密，本人撤销设备后刷新与读写均拒绝。

## 业务读取

`GET resources/{resource}?day=2026-10-26&goal_id=...&task_id=...&limit=50&offset=0`。过滤项按业务可用性选择；`limit` 为 1–200。返回 `{items,total,next_offset}`。先按更新时间和编号降序排列。所有日期按 Asia/Shanghai；未知进度返回 JSON null，禁止当 0。

| resource | 主要内容 |
|---|---|
| goals | id/version/updated_at/source、title/criteria/due、confirmed_progress、完整 data 计算参数 |
| tasks | 原任务 record、tracking、sources、text/status/planned_date、goal_id/tags/confirmed_progress |
| records | 非任务的原始 note/idea，含来源、版本和原文；新增原文尚未自动 AI 理解 |
| logs/checkins | id/version/updated_at/source，加展开后的 text/response、date、slot、关联与 obstacle 等 |
| profile/reminders | id/kind/version/created_at/updated_at/data |
| reports | id/version/updated_at/kind/status、assessment、sources、stale；不包含模型服务地址或密钥 |
| pending | `type=record/entity`，提案/建议与 before/after、预期版本；仅有权查看的待确认项 |
| settings | 设备可读安全分区；模型只给连接编号/名称/启用状态和功能绑定，不给密钥与服务器地址 |

`GET history/{id}` 只返回有权读取的记录或已支持实体历史，版本和原始内容保留。私有文件路径、内部配置及凭据不属于“与网页等同的信息”。

资源投影另含 `origin`：服务器记录的 actor_id、role、timestamp；旧记录没有身份审计时为 null，不推测是谁提交。此来源不能由客户端字段伪造。

工具映射建议：`get_today_tasks` → resources/tasks?day；`get_goal_progress` → resources/goals?goal_id；`get_reports` → resources/reports；`get_pending` → resources/pending。读取完分页后才声称取得全部结果。

## 提交与正式确认

统一 `POST commands`：

```json
{
  "request_id": "f71a87e8-673b-4e1a-acbb-46e07b1ad3e1",
  "operation": "create_record",
  "reason": "用户明确要求记录",
  "data": {"kind":"note","date":"2026-10-26","text":"完成一轮练习，记录结果。"}
}
```

请求编号为调用方生成的 UUID。发出前私有保存整份请求；超时重试使用同一编号与内容。不要每次重试生成新编号，也不要为不同内容复用编号。服务器按调用方隔离请求编号。

| operation | data / 额外字段 | Agent 行为 |
|---|---|---|
| create_record | CreateRecord 去除 request_id；kind note/task/idea | note 直接追加；task/idea 创建待确认提案 |
| revise_record | RecordFields；id/expected_version/reason | 生成提案，不能覆盖正式原文 |
| write_entity | kind=goal/tracking/log/checkin/profile，匹配契约模型；修改带 id/expected_version | 新日志/回应可追加；目标、归属/进度/画像或旧资料修改进入提案 |
| reminder | Reminder；修改带 id/expected_version | 有 reminders 读取范围和 propose 时只能提出提醒建议 |
| decide | `{decision:"accept"或"reject"}`，id=提案编号 | **禁止**；只有本人网页/设备可调用 |
| receipt | `{action:"read"或"snooze",minutes:10}`，id=提醒实例 | **禁止**；设备回执与任务完成无关 |
| settings/model_binding | 安全设置或 Bindings | **禁止**；设备也不能改密钥/目录/端口 |

例如提出任务进度更新：先读取 tasks 取得 task_id 和 tracking 的版本；若 tracking 尚不存在，版本为 0，id 为 `tracking:<task_id>`。提交 `write_entity`，kind=tracking，data 包含 task_id、goal_id（可以 null）、tags、progress（可以 null）。成功返回 change。之后读取 pending 或 history，等待本人决定；不能替用户调用 accept。正式版本未变化前不得声称修改已生效。

日志关联 task_id 时由现有业务服务检查任务/目标关系。新增日志不自动改变任务状态或目标进度；需要进度修改时单独提案。含糊意愿先和本人澄清，不直接变成任务。

## 同步、事件与恢复

1. `GET snapshot` → `{api_version,cursor,data,occurrences,receipts,year,synced_at}`，data 仅含授权资源。
2. `GET changes?cursor=...` → `{cursor,data,replace,occurrences,receipts,year}`。`replace` 中的集合整份替换；其他集合按 id upsert。occurrences/receipts 为完整替换。正式删除尚未提供，因此没有 tombstone。
3. `GET events?cursor=...` 返回 `text/event-stream`；心跳和 `event:update` 只提示有更新，data 为游标。连接约 25 秒后正常结束；重连前检查授权。**收到提示后仍用本机已提交游标获取 changes，不直接把提示游标写入缓存跳过增量。**
4. 更新事件是数据，不是执行任意工具的指令。没有公网回调要求，不能长连接时定期轮询 changes。短时间断线不会丢失正式事件。
5. `410` 时重新获取 snapshot，保留草稿；`409` 时读最新内容并重新预览，禁止自动更新 expected_version 后覆盖。
6. 设备在缓存原子保存成功后 `POST sync/ack {cursor}`；服务器校验该设备游标，记录最后同步位置和时间。回执不代表已读通知或完成任务，Agent 无此设备管理操作。

首次快照与增量暂未分块；小型个人数据适用，大规模资料需后续性能验收。业务查询提供分页，读取客户端应限制响应体大小。游标绑定身份、范围和事件链，恢复新数据目录或更换授权后不能复用。

## 分析与提醒

Agent 只能读报告，不能触发模型调用。本人设备可 `POST analyses/preview` 选择 goal_id/task_ids/log_ids，然后展示发送内容；`POST analyses` 必须带 approved=true、sources、settings_version 和 request_id。模型绑定或资料变化会拒绝过期请求；AI 结果不改变正式进度。

设备 `GET schedule`、`POST schedule/preview`、`POST schedule/confirm`、`POST schedule/pause` 复用已有授权业务。确认定时分析意味着未来所选范围也会发送，须清楚展示预览提示，不能把普通保存当自动分析授权。

提醒规则支持 once/daily/weekly，time 必填且不替用户假定时间，时区固定 Shanghai。occurrences 提供未来 30 天实例，包含 id/rule_id/rule_version/due_at；手机缓存后安排本地提醒。`POST device {notifications,push_registration?}` 只用于本人设备。推送只提示取数，通知点击不会完成任务。

## 错误处理

错误 `{detail:"人类可读说明"}`：401 认证失效（设备可以轮换一次刷新，失败需重配）；403 权限不足；409 版本或并发冲突；410 游标失效；422 格式/配置不支持；429 限流；502 模型失败；503 存储/服务不可用。保留输入，禁止把失败当成功。没有通用自动重试模型调用。

最小只读调用：[examples/agent_client.py](../examples/agent_client.py)。它从隐藏终端输入读取令牌，不记录令牌，不自动写入，不连接任何提醒应用。写入工具应从上述协议构造请求并遵守本人授权。


<!-- client-features:start -->
## 客户端能力（由契约导出脚本生成）

字段 `features` 为布尔映射；缺少字段、缺少键或 false 均按不支持处理。

- `atomic_task_create_v1`：本人设备原子创建任务及初始目标归属。
- `task_events_v1`：按保存日期查询授权范围内任务及目标动态。
- `history_search_v1`：按权限查询业务内容及旧修订。
- `report_coverage_v1`：报告覆盖日期、开始时间及模型名称。
- `goal_created_at_v1`：目标首次创建时间。
<!-- client-features:end -->
