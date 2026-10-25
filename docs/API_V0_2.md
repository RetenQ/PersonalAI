# v0.2 接口与扩展约定

所有接口只供本机页面使用。先 GET `/api/session`，保留 cookie；POST 同时提交返回的 `csrf_token` 为 `X-CSRF-Token`。不开放跨站 CORS，不提供外部应用绕过会话的接口。

## 写入与确认

新增／更正请求：`{request_id: UUID, data: object, expected_version: integer, reason?: string}`。新增版本为 0；更正使用 GET 返回的当前版本。相同请求 UUID 和内容可安全重试，不同内容复用 UUID 返回 409。

一般新增返回 `{entity}`；更正、首次设置任务追踪、首次填写个人档案返回 `{change}`，不立即修改原实体。确认 POST `/api/changes/{id}/decision`，请求 `{request_id, decision: "accept" | "reject"}`。确认时再次检查版本；已处理或过期返回 409。关掉确认窗口等于暂留。

Entity 为 `{id,kind,version,created_at,updated_at,data}`。原有 `/api/records` 与 `/api/proposals` 的 v0.1 请求和返回结构保持兼容。

| 接口 | 用途 |
|---|---|
| GET/POST `/api/goals`，POST `/api/goals/{id}` | 目标、数值指标或里程碑；新建／更正 |
| GET/POST `/api/task-tracking`，POST `/api/task-tracking/{id}` | 关联正式任务编号、单一主要目标、多类型、独立进度 |
| GET/POST `/api/activity-logs`，POST `/api/activity-logs/{id}` | 日期、时段、任务／目标、原文、结果、阻碍、是否已完成事项 |
| GET/POST `/api/check-ins`，POST `/api/check-ins/{id}` | 日期、早中晚、可选目标、回应与阻碍 |
| GET/POST `/api/current-state`，POST `/api/current-state/{id}` | 带日期的现状；精力、心情、阻碍和备注 |
| GET `/api/entities/{id}` | 当前扩展实体与修订历史 |
| GET/POST `/api/settings` | 展示资料、模块、任务类型及非敏感模型配置 |
| GET/POST `/api/profile` | GET 返回 `{profile,version}`；POST 沿用 WriteEntity，返回待确认提案；个人档案独立于 settings |
| GET `/api/user-files` | 可读目录与入口、来源／生成版本、完整性状态、错误和外部改动保留数；不返回文件原文 |
| POST `/api/user-files/rebuild` | 在原有锁内重新整理可读资料，返回整理状态，不新增业务事件 |
| POST `/api/settings/key` | `{base_url,key}`，仅保存受 Windows 账户保护的密钥，不进入事件 |
| POST `/api/settings/test` | 虚构样例连接与格式测试，不读真实目标作为模型输入 |
| GET `/api/dashboard?day=YYYY-MM-DD` | 当前目标／任务／设置，选定日期的日志／回应／状态，年度时间及分析 |
| GET `/api/exports?day=...&goal_id=...&slot=...&format=json` | 返回 `{filename,content}`；format 支持 json/markdown |
| POST `/api/analyses/preview` | `{goal_id,task_ids,log_ids}`；返回完整发送资料、来源版本、配置版本和就绪状态，不联网 |
| POST `/api/analyses` | 以上选择 + `{request_id,sources,settings_version,approved:true}`，版本匹配才调用模型 |
| GET `/api/analyses` | 分析历史及来源过期标记 |

`day` 支持 ISO、今天、昨天、明天和中文年月日。日期按 Asia/Shanghai 解释。时段为 morning/noon/evening，空值表示未指定，没有对应的提醒时刻。

新建任务日志可额外提交 `progress_update: {task_id,goal_id,tags,progress}` 和 `tracking_expected_version`。日志和待确认的追踪修改在一个事务中追加，返回 `{entity,related_change}`。拒绝进度修改不会删除日志。

## 导出格式

JSON 包含 schema_version=2、生成时间、时区、日期／时段、年度时间、goals、tasks、logs、checkins、analyses。各项包含编号与版本。任务追踪编号为 `tracking:{原记录UUID}`。目标和任务为生成时快照，不表示所选日期的历史状态；日期／时段只筛选日志和回应。

不导出个人展示设置、当前心情精力、密钥或未选目标的日志。AI 分析包括其所选来源版本、缺失信息、建议、贡献判断及过期状态。进度导出不同于完整备份：备份包含所有应用事件，包括设置和已拒绝提案，仍不包含密钥。

## 模型约定

已实现手动目标分析，以及 2026-10-25 新增的定时综合分析 Chat Completions 适配；原文自动理解仍未启用。定时分析、授权、报告与外部提醒读取接口见 [定时分析说明](SCHEDULED_ANALYSIS.md)。接口后缀 `/chat/completions`，HTTPS、不跟随重定向、不读取环境代理，连接超时 10 秒，网络读写超时 60 秒，响应最大 2 MB。不存在自动工具调用或自动重试。

结果必须匹配 Assessment：估计区间或 null、置信度、解释、真实来源编号、任务贡献、缺失信息和建议。估计百分比至少需要引用一条本次选中的日志。来源有效只能说明可追溯，不等同于语义判断一定正确。估计和正式进度不会合并。

同时只处理一个分析请求。已保存的相同请求 UUID 返回原结果；若远端已收到请求而本地进程中断，无法保证供应商未计费，手动重试可能再次计费。

密钥单独使用 Windows DPAPI 保存并绑定服务地址。非敏感服务地址和模型名属于设置事件，会包含在完整备份中；密钥不会包含在模型输入消息、响应、事件、备份或导出中。

## 存储与扩展

v0.1 Event 和 Record 类型保持原样。v0.2 使用 EventV2 添加 entities，两个版本共用同一序列与哈希链、跨进程写入锁和原子替换。重放时按 schema_version 选择编码器，不批量迁移或重新编码旧文件。

新增 profile 实体使用固定编号 `profile`，字段为 personality、values、preferences、boundaries（均为最大 6000 字符的可留空文本）。现有实体字段与默认值不变；profile 不自动进入 analysis_input 或进度导出。

可读目录位于 `<store.root>/user/`，写入权威事件后同步生成；生成失败不撤销已保存事件。`/api/status` 与 `/api/dashboard` 新增 `user_files` 状态字段，进度导出排除此本机目录信息。设置提供重新整理入口。详见 [存储规范](USER_DATA_STORAGE.md)。

ZIP 备份格式 2 包含 events/ 与确定性生成的 user/；当前恢复工具兼容格式 1，并检查格式 2 的可读内容与事件重建结果一致。密钥、旧访谈与 user-edits/ 不进入备份。后续修改实体模型默认值或固定模块集合时，必须新增对应版本或保留旧版解码器，不能破坏历史文件的精确校验。

前端总览模块是固定注册表；页面、编辑表单、分析、导出和通用确认展示分开。未来外网部署需独立设计身份认证、TLS、反向代理和数据授权，当前不能直接暴露端口。
