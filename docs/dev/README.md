# SoyMutDB 开发者文档

使用 PI AGENT 执行时，见 [`pi-agent-runbook.md`](pi-agent-runbook.md)，其中提供系统提示词、硬性约束及启动/续跑模板。

数据库核心能力交给智能体实施时，先读 [`database-execution-handoff.md`](database-execution-handoff.md)：
包含当前缺口、执行约束、三个执行者的职责、依赖顺序及验收标准（2026-09-08）。

当前主链由 Web 门户、Web-only Admin、FastAPI、Celery、PostgreSQL/ClickHouse、MinIO、Redis、MCP 和
GitHub Pages 组成。架构、状态机、契约、CI 和部署见 [`architecture-and-deployment.md`](architecture-and-deployment.md)。

生物信息学数据库优先的产品契约、突变体公开/内部双 ID 边界、v4/v5 assembly 搜索语义，以及强制测试与
验收流程见 [`database-core-contract.md`](database-core-contract.md)。修改突变体、基因、变异、搜索、release
或 external/internal 站点行为时，应先读这份文档。

Admin 页面、API 绑定、数据库关系、Page Builder 模板和性能配置见 [`admin-architecture.md`](admin-architecture.md)。
人类可读的服务、包、数据库、队列与插件关系图，以及 CI 机器依赖图合同见
[`../design/dependency-graphs.md`](../design/dependency-graphs.md)。

## 优化与设计方案

**入口**：[`optimization-master-plan.md`](optimization-master-plan.md)（v6.0 总纲）——优先级、依赖、冲突裁决、勘误与任务清单都在这里。**先读它**，再按需查阅子文档。

五份子文档各有边界，只负责详细设计，不写优先级：

| 文档 | 主题 | 关键内容 |
| --- | --- | --- |
| [`optimization-plan.md`](optimization-plan.md) | 工程化改造（v1.0） | Vite chunk 匹配、CI Turbo 远程缓存、CSRF 统一、重试策略、antd-theme 去重、测试补全、nginx 安全头 |
| [`performance-optimization-plan.md`](performance-optimization-plan.md) | 性能与动效（v2.0） | 首屏体积、antd 拆桶、字体子集化、ClickHouse 批量写入、动效 T0–T4 分级与统一调度 |
| [`desktop-client-plan.md`](desktop-client-plan.md) | Tauri 桌面客户端（v3.0） | 免安装分发、跨站认证、本地工具箱、本地/远程调度边界 |
| [`platform-optimization-plan.md`](platform-optimization-plan.md) | 架构收口 · 查询性能 · 前端 · 管理后台（v4.0） | 横切管线化、`pg_trgm` 索引、游标分页、前端状态边界、Admin 巨型页拆分 |
| [`content-template-plan.md`](content-template-plan.md) | 内容管理 · 模板生成 · SSG 管线（v5.0） | 三套内容源收敛、StaticPage 进 SSG、模板数据化、组件契约单一真相、编辑器拖拽 |
| [`rust-rewrite-and-architecture-evaluation.md`](rust-rewrite-and-architecture-evaluation.md) | 架构优化 · Rust 重写评估（v7.0，2026-09-11） | 搜索执行计划收口、导入写入器闭环、CI 关键路径压缩；Rust 逐项否决与 Go/No-Go 门槛 |

> **勘误（2026-08-29）**：此前本表及 v4.0、v5.0 曾把 v1.0 描述为"正确性审计"，并往其名下归因了"导入只计数不落库""nginx 正则误路由 admin/jbrowse"等条目。经回溯核实**这些说法不成立**——v1.0 实为工程化改造清单；`import_studio_service.py` 不落库是设计使然；nginx 的 `/admin/`、`/samples/` 路由已正确使用 `location ^~`，是范例而非 bug。详见 [总纲 §1 勘误表](optimization-master-plan.md)。

```bash
pnpm --filter @soymutdb/web build
pnpm --filter @soymutdb/admin build:web
pnpm --filter @soymutdb/jbrowse build
python3 -m pytest -q scripts/test_development_compose_contract.py  # Docker-free dev Compose contract
docker compose --env-file /dev/null -f docker-compose.yml -f docker-compose.dev.yml --profile core config
```

开发时以 OpenAPI、后端状态机和审计为权威；UI 不应自行推断发布状态或绕过校验。
