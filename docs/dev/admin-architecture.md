# Admin 管理端架构、API 绑定与数据库关系

> **已归档（2026-10-01）**：一次性任务笔记与旧状态视图（结论已进入现状视图与计划）。继任：docs/dev/project-status.md；任务级进度见 `docs/aegis/plans/`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

> 本文描述当前代码实现，而不是未来愿景。接口路径使用前端 client 的逻辑路径；实际 HTTP 前缀由 @soymutdb/api-client 的 VITE_API_BASE_URL 决定，生产环境通常为 /api/v1。

> **2026-09-27 前端重平台状态**：方向改为 React 19 + Umi Max 4、Ant Design 6、ProComponents v3；三应用 React 入口与构建配置已接线，但功能差距、双站制品和安全/交付合同仍在迁移中，尚未测试或构建验收。遗留 Vue source/tests 暂留作参考，不代表生产新功能入口。Page Builder/Widgets 管理面按 ADR-0009 有意退役；下文 §3.3、§5 中相关 API 记录是历史/服务端边界，不能据此认为当前 React UI 提供管理闭环。

## 1. 分层边界

~~~text
Admin React 19 + Umi Max 4
  ├─ routes/                 TanStack Router 页面（dashboard、导入、发布、内容、设置）
  ├─ components/             可复用 UI（表格、编辑器、使用说明）
  └─ lib/                    API client、主题、Query、实例上下文
          │ 只通过 HTTP，不访问 ORM/数据库
          ▼
FastAPI /api/v1
  ├─ api/v1/                 鉴权、参数、响应模型、HTTP 错误
  ├─ services/               事务、状态机、缓存失效、outbox
  ├─ models/                 SQLAlchemy ORM 与外键/索引
  ├─ page_builder/           服务端组件注册表与定义校验
  └─ migrations/             Alembic schema 变更
          │
          ├─ PostgreSQL       权威状态、内容、发布、审计
          ├─ Redis            短期缓存、限流/队列辅助，不是权威数据
          ├─ MinIO/S3        上传文件、分析制品、静态构建制品
          ├─ ClickHouse      分析查询与聚合
          └─ Celery worker    导入、分析、发布等长任务
~~~

**禁止的反向依赖**：Admin 不导入 apps/api/app/models；公共前台不直连 PostgreSQL；模板不接受任意 renderer、SQL、URL endpoint 或脚本。所有可写值必须经过 FastAPI schema、RBAC、事务与审计。

## 2. 当前项目结构

~~~text
apps/
  admin/                    React 19 + Umi Max 4 管理控制台（迁移中）
    src/App.tsx              React Router tree 与鉴权外壳
    src/routes/              React 页面；src/views 与 Vue router 暂留作迁移参考
    src/lib/                 API/主题/Query/实例上下文
    config/config.ts         Umi base/publicPath、CSP、proxy、构建环境
  web/                      React 19 + Umi Max 4 SSG 门户（external/internal，迁移中）
    src/routes/              TanStack React Router file routes
    src/lib/                 搜索 query/cache context 与 deployment adapter
    scripts/                 双站 build、静态路由、CSP、SW、manifest
  jbrowse/                  React + Umi 壳，复用官方 @jbrowse/react-linear-genome-view
    src/App.tsx              assembly-aware JBrowse config、bridge 与 deep links
  api/                      FastAPI + SQLAlchemy
    app/api/v1/              HTTP transport
    app/services/            业务事务与跨存储协调
    app/models/              PostgreSQL ORM
    app/page_builder/        安全组件 registry/schema/service
    migrations/              Alembic migrations
  worker/                   Celery 长任务执行器
packages/
  api-client/               共享 HTTP client 与前端 DTO
  ui-react/                 React 19 + Ant Design 6 / ProComponents v3 facade 与品牌 tokens
  shared/                   deployment、CSP 与其他前后端共享契约
  i18n/                     en/zh 翻译资源
  jobs-py/                  worker/API 作业契约

迁移说明：三个应用的生产入口和构建由 Umi Max 管理；遗留 Vue 页面/测试仍留在
工作区，尚未清理，也不代表 React 页面功能或双站制品已通过验收。

deploy/                     Compose、Cloudflare、CI、镜像与运行手册
e2e/                        Playwright smoke、视觉与布局审计
docs/dev/                   架构、开发、验收与运维文档
~~~

新增功能的推荐落点：页面交互放 apps/admin/src/routes，跨页面 UI 放 components，协议调用放 lib 或 packages/api-client，数据库行为放 API service/model/migration，禁止把业务逻辑塞进页面组件。

## 3. Admin 页面到 API/数据库映射

| 管理页面 | 前端绑定 | 服务端权威实体 | 关系/副作用 |
| --- | --- | --- | --- |
| Dashboard | GET /admin/dashboard-stats、GET /admin/dashboard-series | 聚合查询 | 只读统计；不写入业务表 |
| System Settings | GET/PUT /admin/settings/{section}、GET /admin/settings/schema | system_settings、system_setting_revisions | registry 决定可写 key、类型、权限；修订关联 users.id |
| Content / Static Pages | GET/POST/PUT/DELETE /admin/content/pages、publish/unpublish、versions | static_pages → content_versions | 一页多版本；版本 page_id 外键级联；发布状态由服务端控制 |
| News | /admin/news CRUD、排序与发布 | news_articles | 双语正文、状态和首推排序由 API 保存；封面优先引用 media_assets |
| Media Library | /admin/media、/admin/uploads/presign、/admin/uploads/complete | media_assets → news_articles.cover_asset_id / rich HTML URL references | S3/MinIO 只存对象；API 校验字节、摘要、MIME 和尺寸后才登记 READY；归档受所有新闻引用保护 |
| Publications | /admin/publications CRUD | publications | 前台读取公开字段或 release-aware snapshot；中英文独立字段 |
| Page Builder | /admin/page-builder/registry、pages、draft、preview、publish-request | page_definitions → page_definition_versions | 组件 props 由服务端 registry 校验；发布请求写 outbox_events，不直接写静态文件 |
| Imports | GET/POST/DELETE /admin/imports、retry、status | import_tasks → data_sets / releases | idempotency_key 防重复；文件在对象存储；worker 更新进度 |
| Widget Manager | /admin/widgets CRUD、preview、health | widgets、page_layouts | HTML 预览可缓存到 Redis；更新/删除必须失效相关 cache |
| Layout Editor | GET/PUT /admin/layout/{page} | page_layouts | 只保存已存在 widget name 和顺序/config，不删除 widget 定义 |
| Audit Logs | GET /admin/audit | audit_logs | 只读合规记录；按 resource/user/timestamp 索引 |
| Notifications | /notifications/unread-count、列表、read-all | notifications | 用户范围查询；读操作更新已读状态 |

### 3.1 内容与发布数据流

~~~text
Admin form
  → api-client (JSON + access token)
  → FastAPI dependency (session + administrator role)
  → Pydantic schema / sanitizer / registry
  → service transaction
  → PostgreSQL commit + audit/outbox
  → worker / snapshot / SSG
  → public site reads published snapshot only
~~~

### 3.2 媒体库上传、引用与生命周期

媒体库采用“数据库权威、对象存储承载内容”的边界：

1. Admin 先向 `POST /admin/uploads/presign` 请求带尺寸、MIME、SHA-256 和 purpose 约束的 POST 表单。
2. 浏览器把文件直接提交到公共 S3/MinIO bucket；API 不代理大文件。
3. 上传成功后调用 `POST /admin/uploads/complete`。服务端重新 HEAD/读取对象，核对大小、SHA-256、文件魔数、实际 MIME 和图片尺寸。
4. 验证通过才创建 `media_assets(status=ready)`。失败的对象不进入选择器，后续由对象存储垃圾回收任务清理。
5. 新闻只保存 `cover_asset_id` 外键和兼容性的 `cover_url` 快照；使用资产时 URL 由服务端从 ready 资产派生，前台 alt 使用编辑者的 `cover_alt_text`，再回退到标题。
6. 删除是归档而不是硬删除；被任何新闻引用的资产（封面外键或 rich HTML 中的 URL）必须先解除引用。PostgreSQL 计算引用计数，Redis 不参与正确性判断。

~~~text
presign → direct S3/MinIO POST → server verification → media_assets READY
                                                     ↓
                                      news_articles.cover_asset_id
                                                     ↓
                                           public snapshot / SSG
~~~

### 3.3 Page Builder 数据源边界

data_sources 是页面定义中的**受约束引用元数据**，其 id/kind/config 经过服务端 schema 校验；它不是可执行 adapter，也不是让管理员填写 endpoint 的入口。组件实际如何取数必须在公共 renderer、API client 或服务端 registry 中增加固定实现，并附带权限、超时、分页和空状态。

## 4. 性能配置与使用规则

### 浏览器

- Admin QueryClient：staleTime=30s、gcTime=5min、关闭窗口聚焦重复请求；变更后按资源 key 精确失效。
- Router：defaultPreload="intent"、预加载新鲜期 30s，避免鼠标悬停导致重复加载。
- 重型功能应按 Umi/TanStack Router 页面边界 lazy-load；图表、富文本编辑器和 genome browser 不进入首屏入口。当前迁移中的 chunk 输出与运行时行为仍待构建验证。
- 列表默认分页，不以一次性拉取 100/200 条掩盖缺少分页；搜索和排序由 API 承担。
- 颜色、主题和轻量偏好使用受校验的 localStorage；业务内容、权限和发布状态不能只存浏览器。

### API/数据库

- SQLAlchemy async engine 默认连接池为 5 + 5 overflow，pool_pre_ping=true、pool_recycle=1800s、池等待 30s。
- PostgreSQL statement timeout 默认 30s；Redis connect/read socket timeout 默认 2s；ClickHouse connect timeout 默认 10s。
- 列表接口必须分页并设置上限；聚合/版本列表避免 N+1。本轮 Page Builder 与静态页面列表已将“逐页读取最新版本”改为批量查询。
- 慢导入、分析、静态发布交给 worker；API 只创建任务、返回状态并提供轮询/事件查询。
- Redis 不可用时可降级到数据库读取，但必须保留超时和明确监控；缓存命中不能改变业务正确性。

### 发布前自检

1. 浏览器 Network：只出现预期 endpoint；无 ORM import、无直接 DB 请求。
2. API：请求经过 RBAC、schema、事务；失败时 UI 保留基线并展示可操作错误。
3. 数据库：检查外键、唯一约束、状态索引和版本/审计记录。
4. 性能：列表分页、请求有 timeout、缓存有失效、长任务不阻塞 API worker。
5. 发布：只发布 validated/ready/published 数据，构建产物做 placeholder、内链和 hash 检查。

## 5. Page Builder 模板策略

创建页面时可选择以下服务端注册表兼容模板：

- **空白内容**：单栏 rich text，适合从零设计。
- **科研首页**：提示语、说明正文、资源卡、新闻和科研工具入口。
- **数据探索**：组装版本选择、基因搜索、位置搜索和结果表格，查询入口优先于结果上下文。
- **帮助中心**：说明正文、Getting started/Data policy/Contact 标签页和安全提示。

模板只是安全起点，不绕过 Page Builder registry。保存前使用 Preview；发布请求由 outbox 进入静态发布流水线。未知组件、危险 URL、脚本、越界 props 和不符合响应式约束的定义必须被拒绝。

## 6. 参考技术文档

- [Vite Performance](https://vite.dev/guide/performance)：依赖预构建、代码分割和避免不必要转换。
- [Vite Build Options](https://v6.vite.dev/config/build-options)：target、Rollup output 与生产构建选项。
- [TanStack Query Render Optimizations](https://tanstack.com/query/latest/docs/framework/react/guides/render-optimizations)：结构共享、精确订阅和避免无效重渲染。
- [SQLAlchemy Relationship Loading](https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html)：批量关系加载和避免隐式查询。
- [FastAPI Server Workers](https://fastapi.tiangolo.com/deployment/server-workers/)：API worker 与容器部署边界。
- [Ant Design ColorPicker](https://ant.design/components/color-picker/) 与 [Customize Theme](https://ant.design/docs/react/customize-theme)：颜色选择器、ConfigProvider token 及主题覆盖。

修改 API、模型、页面定义或部署配置时，请同时更新本文对应映射，并在 .ai-memory/YYYYMMDD/daily.md 记录决策与验证结果。
