# APK clients/v1 扩展交接

日期：2026-10-29。状态：本地实现及契约交付；公网尚未部署，APK 工程本轮只读。

## 服务器接续

本次提交同时携带此前已完成的网页精简、任务动态和 APK 目录拆分，作为这些客户端扩展依赖的完整源码。APK 源码已在开发电脑独立目录，不在服务器仓库继续维护。先保留服务器未提交改动、核对提交差异，再按原运维流程构建前端并更新后端；不要只复制契约 JSON 或只更新网页。

本轮未访问正式资料、测试公网、启用模型/推送或部署。上线后由已配对设备检查 capabilities，再由 APK 开发方核对、复制新的协议快照并启用对应 UI。API v1 不变，不依据 api_version 推断新能力。

## 能力发现

`GET /api/clients/v1/capabilities` 保留原字段，新增布尔映射 `features`。本人设备、插件开启且有相应 scopes 时示例：

```json
{"features":{"atomic_task_create_v1":true,"task_events_v1":true,"history_search_v1":true,"report_coverage_v1":true,"goal_created_at_v1":true}}
```

| 稳定名称 | 条件 |
|---|---|
| atomic_task_create_v1 | device；write:records、read:tasks、read:goals；tracking 插件开启 |
| task_events_v1 | read:tasks 或 read:goals；tracking 开启；按各自范围裁剪 |
| history_search_v1 | 至少有一种受支持的业务读取权限及其对应活动插件；不代表可读所有类型 |
| report_coverage_v1 | read:reports，analysis 开启 |
| goal_created_at_v1 | read:goals，tracking 开启 |

旧服务没有 features、缺键、键为 false 时均按不支持降级。每次重新配对/重新连接刷新能力；遇到 401/403/409 不凭缓存继续声称可用。旧只读资源接口保留归档兼容，能力开关控制新功能可用性，不代表删除历史。

## 原子创建并关联任务

`POST /api/clients/v1/commands`，头部 `Authorization: Bearer <设备令牌>`。不使用网页 Cookie 或 CSRF 凭据。

```json
{
  "request_id":"f71a87e8-673b-4e1a-acbb-46e07b1ad3e1",
  "operation":"create_task",
  "data":{"text":"阅读第一章","date":"2026-10-29","category":"uncategorized","status":"open","goal_id":null}
}
```

- 必填：外层 request_id（UUID）、operation、data.text、data.date。category 默认 uncategorized，status 默认 open；可选 kind 只能为 task；goal_id 为目标 UUID 或 null。
- date 是计划日期；状态值 open/partial/done 分别为待进行/部分完成/已完成，不引入任务百分比。
- 返回 `{"record":{...}}`，包含服务器分配的 id、version、created_at、updated_at 等原记录字段。初始 tracking 在同一原子事务中写入，可从 snapshot/changes 的 tasks 读取。
- 即使 goal_id=null 也要求上述三项权限，保持一个明确的设备能力。Agent 一律 403；Agent 继续用旧 create_record 创建待确认提案。
- 找不到目标 404，整个请求失败；相同设备、相同 request_id、相同数据重试返回原结果，换数据 409。不同设备独立命名空间；审计身份由服务器填写。
- 创建不需要 expected_version；修改既有归属继续 write_entity(kind=tracking)+expected_version+decide。状态更新仍 revise_record+decide。
- create_record 保持严格兼容，多塞 goal_id 返回 422，不静默丢弃。

## 自动动态

`GET /api/clients/v1/task-events?day=2026-10-29&offset=0&limit=50`。day 可省略，默认上海今天；显式日期为 YYYY-MM-DD。offset≥0，limit 1–100、默认 50。

```json
{"items":[{"id":"<任务编号>:v2","task_id":"<任务编号>","entity_id":null,"version":2,"time":"2026-10-29T10:00:00+08:00","title":"阅读第一章","action":"状态：待进行 → 已完成","source":{"id":"<任务编号>","version":2}}],"total":1,"next_offset":null,"snapshot_version":12}
```

覆盖任务创建、状态/原文/计划日期/类别更正、目标归属、目标创建和目标指标/规则/进度变化。只读取已保存历史；待确认和拒绝不形成正式动态。没有额外日志写入或 AI 调用。

按 Asia/Shanghai 实际保存时间归日，倒序排列；同一秒以事件顺序及稳定编号打破平局。归属名称按当时事件版本解析，连续快速改名不改写旧动态。单条来源调用 `/history/{source.id}`，再定位 version。

read:tasks 单独授予时只返回任务本身变化；read:goals 单独授予时只返回目标变化；只有两者都具备时才返回含目标名称的归属变化。都没有时 403，tracking 关闭时 409。

每页最多 100 条动态，不宣称是全量结果或固定字节上限。直到 next_offset=null 才完成当次取数。snapshot_version 是读取时事件序号；翻页期间变化则从 offset=0 重新读取。快照/增量仍只同步业务资源；changes 成功且游标变化后，客户端刷新当前日期动态和搜索，SSE 仅提示取数，不把这些投影写入模型授权范围。

## 报告和目标投影

`resources/reports`、snapshot、changes 的报告新增 `window_start/window_end/started_at/model`，非适用字段可为 null；保留 status、assessment、sources、stale 等字段，不返回 endpoint、base_url 或密钥。

- scheduled_run 的 day 筛选严格匹配 window_end，与网页每日回顾一致；window_start 用于显示覆盖范围，不表示区间每一天都返回该报告。
- reports 依 started_at 倒序，同时间按 id 倒序。客户端取指定日期的报告后，选择首个 kind=scheduled_run 作为最近一次；保留其 running/failed 等真实状态，不跳过失败伪装有最新成功结果。
- 手动目标分析 kind=analysis 没有日报覆盖窗口，day 按开始/保存时刻换算上海日期；不能当作每日回顾。
- 补跑历史覆盖日期的报告不按生成日期归入当天。
- goals 新增 created_at，目标颜色按 created_at、id 排序后分配；未知进度仍为 null。

## 全内容与旧修订查询

`GET /api/clients/v1/history?q=阅读&day=2026-10-29&kind=task&offset=0&limit=30`，静态路由先注册，与 `/history/{identifier}` 共存。

- q 为不区分大小写的子串，最多 500 字符；kind 最多 50 字符；offset≥0；limit 默认 30，范围 1–100。q/day/kind 可省略。
- 类型：note、task、idea、goal、tracking、log、checkin、profile、analysis、scheduled_run、suggestion、change、proposal。未知类型结果为空；不检索密钥、内部配置、未知插件负载或退役 state。
- 日期：记录/任务用该版本的 date（计划日期或记录日期）；日志和回顾用业务 date；scheduled_run 用 window_end；其他内容按该版本保存时刻的上海日期。提案按提案保存日期。
- 返回 `items,total,next_offset,snapshot_version`。每项含 id、kind、title、updated_at、version、record、source、matches、history。matches 是命中的旧修订；history 是允许展示的完整历史；title/version 是最新版本，不能把 matches 误认为当前内容。
- 分页按对象计数，最多每页 100 个对象；单对象的历史版本未分块。大量修订时可能响应较大，APK 不应把部分缓存称为全量；现阶段不声称具备大规模分块历史能力。
- 权限按业务类型及关联引用检查；提案还要求 read:pending 和修改对象权限。若任一历史版本包含未授权的关联资料，则保守排除整个对象，避免通过最新标题或命中结果泄露内容。未知来源引用也保守排除。
- 报告历史采用允许字段列表，去掉服务地址、内部哈希等配置后再匹配关键词。单条历史使用相同权限和投影，不通过“打开来源”绕过搜索过滤。
- 未知资源历史 404，已存在但无权读取的历史 403。查询不产生事件。

## 错误与兼容

401：缺少/过期/撤销令牌；403：角色或 scopes 不允许；404：目标/资源不存在或旧服务无路由；409：版本、请求编号内容冲突或插件不可用；410：同步游标失效，需要重取快照并保留草稿；422：字段/日期/分页格式不合法；429：限流；503：存储或服务不可用。

发生 409 不自动换 expected_version 覆盖；发生传输失败保留原请求及 request_id，用户重试保持身份。旧接口不移除、不自动扩大旧 Agent 权限。APK 应先检查 features；旧服务不支持时保留已有分步关联、缓存筛选等明确标注的降级行为。

## 契约源头与验证

源码：`client_api.py`、`client_views.py`、共享 `task_routes.py/history_routes.py`。通过 `scripts/export_client_contract.py` 从隔离空数据生成 `docs/openapi.clients.v1.json`，并更新 `docs/AGENT_API.md` 的能力清单区块。AGENT_API 的其他说明为人工维护。导出契约含新操作、CreateTask、分页响应模型、features 元数据及新增投影字段说明。

APK 端后续只复制协议文档及所需示例，不复制服务器源码或凭据；本轮没有写入 APK 目录。源码对应 Git 提交以本文件所在提交及本次交付提交号为准；JSON 不能独立于实现部署。

验证：完整后端 164 项通过；最终能力范围调整后的客户端扩展定向测试 6 项通过（含生成契约一致性）。前端 26 项通过，TypeScript/Vite 构建成功，桌面/手机浏览器 10 项通过。

首次回归发现同一秒内改名影响历史名称的问题，已用事件序号定位来源并补充固定时钟回归；浏览器首次运行出现选择器同时命中保存与加载状态的问题，已限定保存提示，最终 10 项通过。后端仍有 Starlette/httpx 弃用警告，不影响通过。

未验证公网部署、真机 APK、真实模型和推送。
