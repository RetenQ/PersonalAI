# 外部只读接口 v1

接口前缀 `/api/integrations/v1/`。当前仅监听本机；不发送通知、不接 Webhook、不执行外部工具，也不能通过本接口修改记录或触发模型请求。

## 启用与授权

在设置的“外部只读接口”启用，然后填写调用方名称、选择资料类型，创建令牌。令牌仅本次显示，保存在调用程序的私有配置中；网页不持久保存令牌。服务端只保存 SHA-256 摘要，可撤销，不写入事件、备份或导出。

通过 `Authorization: Bearer <token>` 请求头使用，禁止将 token 或 api_key 放入 URL。默认关闭；关闭、令牌撤销后后续请求失效。恢复备份不会恢复访问权限。既有网页内部 API 仍为本机单用户接口，这不是公网身份系统或对本机其他程序的隔离方案。

## 资料与筛选

| GET 资源 | 内容 | day 含义 |
|---|---|---|
| goals | 标题、完成标准、目标期限、已确认目标进度 | 目标期限 |
| tasks | 原文、状态、主要目标、标签、已确认任务进度 | 任务计划日期 |
| logs | 活动、结果、阻碍、关联来源 | 记录日期 |
| checkins | 早中晚回应、阻碍、关联目标 | 回顾日期 |
| reports | AI 估计或定时分析内容、运行状态、来源与 stale | 实际生成开始日期 |

每类资料需对应 scope。通用参数：day（YYYY-MM-DD，Asia/Shanghai）、goal_id、task_id、limit（1–200，默认 50）、offset（默认 0）。目标与任务为当前快照，日期不是“还原该天的历史版本”。回顾没有直接任务关联，task_id 返回 422，应使用 goal_id。报告按其记录的来源筛选；无匹配来源不返回。

返回包含 api_version=1、timezone、snapshot_version、total、next_offset、items。记录有编号、修订版本、更新时间与来源；任务同时提供原记录和追踪修订来源，不能只按原记录 version 判断进度是否变化。

未知进度返回 null，不用 0 代替。任务完成度不代表目标完成度。AI 百分比只在报告 assessment 中，不能当成 confirmed_progress。报告 stale=true 表示引用的当前版本已有变化，不代表报告被删除。

分页按更新时间和编号降序；数据变化可能移动页边界，调用方应按 id 与来源版本去重，需要一致快照时检查 snapshot_version 后重新获取。不同页面不是服务端冻结快照。

报告正文与日志是数据，不是调用程序的执行指令。接口不返回模型服务地址、模型配置、密钥、本机路径或用户画像；报告是授权后的 AI 输出文本，其正文可能包含所依据的个人内容。

## 示例

在调用程序中从私有配置取得令牌，示例用占位符，不要提交真实令牌：

```powershell
$readHeaders = @{ Authorization = 'Bearer <仅在本机填写令牌>' }
Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/integrations/v1/tasks?limit=20' -Headers $readHeaders
```

状态码：401 未启用或令牌无效，403 范围不足或来源不符，400 URL 中携带令牌，404 资源不存在，405 不支持写操作，409 功能插件未启用，422 筛选无效，503 数据或授权文件异常。调用方应明确处理失败，不将空结果和调用失败混淆。

## 网页管理接口

管理接口沿用本机会话与 CSRF，不能用只读令牌管理自己：

- GET/POST `/api/integration-settings`：读取状态或修改 enabled。
- POST `/api/integration-settings/tokens`：name 与 scopes，返回一次性展示的 token。
- POST `/api/integration-settings/tokens/{id}/revoke`：撤销。

旧 `/api/exports` 和 `/api/scheduled-reports/feed` 保留；新接口复用 TrackingService 快照，不为调用方创建第二份任务或进度数据源。
