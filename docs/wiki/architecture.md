# 架构与数据流

## 组成

```text
external React portal ─┐
internal React portal ─┼─ typed API client ── SoyMutDB API ── PostgreSQL (唯一权威)
admin React console ───┘         │                       ├─ MinIO (对象存储)
                                 │                       └─ Redis (缓存/队列/限流)
                                 └─ 实例注册表 + 授权 + 审计
                                    └─ 受限实例连接器 ── remote SoyMutDB API (独立数据与权限)

历史 ClickHouse（仅 legacy-migration overlay，不是运行时组件）
```

- 前端（React 19 + Umi Max 4 + Ant Design 6）：`apps/web`（公共站，`external` / `internal`
  两种构建变体）、`apps/admin`（管理端）、`apps/jbrowse`（JBrowse 2 壳，复用
  `@soymutdb/genome-view` + `@soymutdb/genome-data`）。
- 后端：`apps/api`（FastAPI + SQLAlchemy + Alembic）、`apps/worker`（Celery）、
  `apps/mcp-server`（MCP 工具服务）。
- 共享包：`packages/api-client`（typed 客户端 + 生成的 OpenAPI 类型）、
  `packages/ui-react`（设计系统门面）、`packages/charts`（图表运行时）、
  `packages/genome-view` / `packages/genome-data` / `packages/genome-view-model`
  （基因组视图与数据源）、`packages/i18n-core`（en/zh 字典）、`packages/i18n`
  （应用绑定）、`packages/query-keys`（缓存键契约）、`packages/shared`（跨端共享）、
  `packages/import-protocol` / `packages/jobs-py`（导入协议与任务契约）、
  `packages/enrichment-core`（富集分析核心）。

## 权威存储

| 存储 | 职责 | 丢失后果 |
| --- | --- | --- |
| PostgreSQL | 身份、关系、发布、权限、工作流状态、设置、审计、变异事实、匿名分析 | 权威数据丢失，需备份恢复 |
| MinIO | 原始对象（VCF、媒体、导出、JBrowse 数据） | 对象丢失，需按清单恢复 |
| Redis | 缓存、Celery broker、限流计数器 | 可丢弃；缓存降级为直查，限流在非 dev 环境 fail-closed |
| ClickHouse | **仅历史迁移源**（`docker-compose.legacy-clickhouse.yml` + `legacy-migration` profile） | 不影响运行时；无默认 compose 服务 |

禁止引入新的权威存储；前端不得直连数据库。SQLite 只允许离线演示用途，
生产/完整开发路径以 PostgreSQL 为准。

## 隔离边界

- **站点变体**：`external` / `internal` 由构建期环境变量显式选择
  （`VITE_SITE_VARIANT`），产物、origin、CORS、Service Worker、缓存全部隔离；
  服务端对 internal 读取强制鉴权并返回 `private, no-store`。变体绝不从 host/IP/cookie
  推断。
- **公开标识**：公开突变体只使用稳定 `public_id`；`internal_id` 不进入 external 响应、
  URL、日志与 `dist/external`。匿名按内部标识查询不泄露记录是否存在。
- **组装版本**：v4/v5 是独立命名空间。请求、缓存键与 URL 使用稳定 assembly `id`；
  名称/版本只作展示与请求边界转换；名称歧义（v4/v5 同名）显式报错而非静默合并。
- **发布版本**：动态请求携带 `X-SoyMutDB-Release`，页面显示与请求上下文使用同一 release。

## 关键不变量

1. PostgreSQL 是唯一运行时权威；ClickHouse 不参与运行时读写。
2. 生物搜索缓存键包含 site variant、release、assembly、query、filters、分页与权限上下文；
   internal 响应不进入共享缓存。
3. 跨版本基因匹配只允许来自带来源的别名/映射关系，禁止字符串相似度推断。
4. 生产/完整开发路径不使用 SQLite。

契约细节与测试矩阵见 `docs/dev/database-core-contract.md`。
