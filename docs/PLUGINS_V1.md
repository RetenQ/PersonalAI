# 可信代码插件协议 v1

## 接入方式

后端在 `src/personalai/plugins.py` 的显式注册表增加 Plugin，逻辑放在独立 Python 模块；前端在 `frontend/src/plugins.tsx` 的 frontendPlugins 注册页面与卡片，组件可放在独立文件。无需更改核心存储或主页面的业务分支。修改前端后构建，修改服务配置后重启。

Plugin 声明 id、name、version、protocol=1、dependencies、capabilities、routes、pages、modules，以及可选 types、settings、render、setup、start、stop。版本号用于识别发布；目前检查协议整数版本，依赖按插件编号，不提供版本区间求解器。

内置插件：tracking（目标任务）、journal（日常回顾）、analysis（目标分析与定时器）、dashboard（总览）、exchange（导出与外部读取）。核心记录、历史、确认机制、配置、密钥与备份始终保留。基础记录仍可在其他插件异常时使用。

example 默认关闭。启用示例可在服务配置 plugins 数组追加 `example`，构建并重启。它提供独立页面、总览卡片、JSON 设置编辑和带确认的示例记录，适合参考接入流程；不要用测试内容填充真实经历。

## 后端接口

生命周期接收 PluginContext：

- `add_route(suffix, handler, methods)`：注册在 `/api/plugins/{id}` 下，沿用 Host、来源与写会话检查。未捕获异常使该插件入口停止并返回明确错误，其他核心路由保留。
- `service(name)`：只能获取 capabilities 中声明的共享服务。tracking 提供正式写入与修订确认，models 提供目标分析 preview/analyze（沿用资料选择与确认校验），scheduler 提供现有范围授权和调度接口。
- 声明 data 能力后，可用 `read()` 读取本命名空间、`write(kind, WriteEntity, identifier)` 写入。正式修改返回待确认提案，不能跳过版本检查。
- settings 是 Pydantic 设置类型；types 映射本插件类型名到校验模型。数据类型名称为 `插件编号/类型名`。render(kind,data) 可生成 Markdown，结果随实体保存；不得把密钥或外部文件内容放入渲染结果。

通用 API：

| 路径 | 行为 |
|---|---|
| GET `/api/plugins` | 协议、状态、依赖、能力、页面、模块与设置定义 |
| GET `/api/plugin-data?plugin=example` | 本机通用只读查看，保留未安装插件的数据 |
| POST `/api/plugin-data/{plugin}/{kind}` | 新建；settings 为该插件唯一设置实体 |
| POST `/api/plugin-data/{plugin}/{kind}/{id}` | 提出修改，需 expected_version |
| POST `/api/plugin-changes/{id}/decision` | 接受或拒绝；接受时再次检查版本和插件可用性 |

请求沿用 request_id、data、expected_version；响应为 entity 或 change。通用只读接口属于网页内部 API，不是给外部调用者绕过授权的接口。

## 生命周期与故障

按依赖顺序启动；停止时反向收尾。setup 注册扩展路由，start 启动自有工作，stop 必须停止工作并释放资源。启动失败不影响核心启动，依赖它的功能不可用。插件不得自行创建操作系统定时任务或在 setup 中发送模型请求。

停用关闭其路由入口与后台任务，前端隐藏对应扩展入口；原始数据与备份保留。历史数据解码不依赖当前插件注册表。没有对应类型校验器时只允许只读保存与迁移，不自动猜测或转换内容。

前端插件页面和总览组件有错误边界，组件异常时可继续使用其他页面。前后端注册项需要配套；不支持网页动态下载脚本、热加载或插件商店。

这是可信的进程内代码扩展约定，不是权限沙箱。Python 插件与应用同进程，能力声明不能阻止恶意代码直接访问操作系统；只加载审查过的代码。插件不会获得自动更改正式计划或向云端发送个人资料的产品授权。

## 验收要求

新增插件至少验证：默认关闭、显式启用、数据校验、修订前后差异与拒绝、过期确认、重启保留、停用只读、缺失依赖、启动或路由异常、备份恢复以及前端尺寸适配。不可通过修改旧事件模型默认值来升级插件，应添加新的类型或事件兼容路径。
