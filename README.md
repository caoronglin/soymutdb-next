# SoyMutDB Next

> 多物种突变数据库（默认物种为大豆），提供科研门户、Web-only Admin、数据发布与基因组浏览。

## 当前架构

```
┌─────────────────────────────────────────────────────────────┐
│  GitHub Pages（静态托管：web 根、soymutdb-admin/、soymutdb-jbrowse/）  │
│                                                             │
│  /             ──► SSG 静态 HTML（apps/web/dist/，注入 release 元数据）│
│  /soymutdb-admin/ ──► Web-only Admin（apps/admin/dist/）      │
│  /soymutdb-jbrowse/ ──► JBrowse 2 基因组浏览器（apps/jbrowse/dist/） │
└─────────────────────────────────────────────────────────────┘
          │ HTTPS（API/数据面走自管后端）
          ▼
┌─────────────────────────────────────────────────────────────┐
│  Nginx（/api/v1/*、/mcp/*、/data/* 反代）                     │
│                                                             │
│  /api/v1/*     ──► FastAPI（apps/api）                        │
│                     ├─ /content/snapshot → 内容快照（release 感知） │
│                     ├─ /page-definitions/{route} → PageDefinition │
│                     ├─ /admin/* → 管理 API（JWT，Page Builder 等） │
│                     ├─ /widget/{name} → 消毒 HTML             │
│                     └─ /search、/genes、/blast … JSON API     │
│                                                             │
│  /mcp/*        ──► MCP server（apps/mcp-server，SSE）         │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────┐ ┌────────────┐ ┌────────────┐ ┌─────────┐
│PostgreSQL│ │ClickHouse  │ │MinIO(S3)   │ │  Redis  │
│ 权威数据 │ │ 分析/变体  │ │ 对象存储    │ │cache/限流│
└──────────┘ └────────────┘ └────────────┘ └─────────┘
```

### 隔离边界

| 层 | 技术 | 边界 |
|----|------|------|
| Public Web | SSG HTML + React（TanStack Router + PageDefinition 渲染器） | 纯静态；无服务端渲染 HTML |
| API | FastAPI（Python） | 消毒 HTML 片段 + JSON；OpenAPI 是唯一契约 |
| Admin | React + Vite（Web-only，部署于 `/soymutdb-admin/`） | 静态托管 + 受保护 Admin API（JWT） |
| Worker | Celery（多队列） | ingest/export/stats/cleanup/blast/analyses；直连数据层（窄 SQLAlchemy Core） |

前端代码不直连数据库；数据统一经 API / worker 层。Tauri 桌面壳与 Rust 热路径（`core-rs`）已清理移除，当前仅保留 Web-only Admin。

## Quick start

### Prerequisites

- Node.js ≥ 20（pnpm ≥ 10，锁定 `pnpm@11.21.0`）
- Python ≥ 3.13（API 与 worker 各自 venv：`apps/api/.venv`、`apps/worker/.venv`）
- Docker（数据层与生产部署；可选，另见 conda 裸进程备选路径）

### Install

```bash
pnpm install
```

### Run development servers

```bash
# Public web portal（SSG + Vite dev）
pnpm dev:web

# Admin console（web mode）
pnpm dev:admin

# FastAPI backend
cd apps/api && uvicorn app.main:app --reload --port 8000

# Celery worker（按队列；见 deploy/conda/README.md §6）
cd apps/worker && celery -A soymutdb_worker.main:celery_app worker --loglevel=info
```

数据层可用 `docker compose -f docker-compose.dev.yml up -d` 起 PostgreSQL/ClickHouse/Redis/MinIO。

### Build

```bash
pnpm build:web     # 构建 web → dist/（含 SSG 页面 + samples + 内容快照）
pnpm build:admin   # 构建 admin web bundle
# 完整构建链（单体）：
pnpm --filter @soymutdb/web build
pnpm --filter @soymutdb/jbrowse build
```

## Deployment

> 架构、状态机、接口契约与 Pages 拓扑见 **[开发者文档](docs/dev/architecture-and-deployment.md)**；
> Admin 数据导入（Module 数据支持 `.tsv`/`.txt`/`.csv`/`.xlsx` 多格式 + 模板下载）、Release、
> 不可变静态发布、回滚与备份恢复见 **[运维手册](docs/ops/README.md)**。

**当前生产部署现状：**

| 面 | 方式 | 入口 |
| --- | --- | --- |
| 前端（web、Admin、JBrowse） | GitHub Pages，单次 workflow 组装到 gh-pages | https://caoronglin.github.io/soymutdb-next/、`/soymutdb-admin/`、`/soymutdb-jbrowse/` |
| 后端 + 数据面 | Docker Compose（API、worker×4、beat、数据库、对象存储、MCP、nginx） | `http://<HOST>:8080` → `/api/v1/*`、`/mcp/*`（SSE） |

**快速上手（生产服务器）：**

```bash
sudo bash deploy/linux/install.sh             # 安装布局 /opt/soymutdb + .env 模板
# 编辑 /opt/soymutdb/.env（模板：deploy/.env.example；必填镜像 tag/JWT/CORS/凭据）
sudo bash deploy/scripts/upgrade.sh           # 预检 → 拉镜像 → 迁移 → 启动 → 健康检查
bash deploy/scripts/healthcheck.sh            # 服务健康检查
bash deploy/scripts/backup.sh                 # 数据备份（PG+CH+S3，upgrade 前自动执行）
bash deploy/scripts/verify-restore.sh <backup> # 恢复演练校验
```

**备选路径（conda 裸进程，无 docker / 离线 / 本地开发）：**

- 指南：[`deploy/conda/README.md`](deploy/conda/README.md)；推荐：docker 起数据层（postgres/clickhouse/redis/redis-celery/minio）+ conda 跑应用层（api/worker/beat）。
- 一键准备：`bash deploy/scripts/conda-deploy.sh`。

## 文档入口

- [科研用户指南](docs/user/README.md)
- [运维与 Admin 手册](docs/ops/README.md)
- [开发者架构与部署](docs/dev/README.md)
- [历史部署设计（仅参考）](docs/design/deployment-architecture.md)

## 非主路径（已废弃/已放弃，仅保留参考）

- `deploy/cloudflare.md` — 旧 Cloudflare Pages 静态托管方案（已改为 GitHub Pages）。
- `deploy/conda/no-docker-data-layer.md` — 完全无 Docker 数据层探索（conda 裸进程备选）。

## Project layout

```
apps/
├── web/               # 公共 SSG 门户（React + Vite + TanStack Router）
│   ├── src/
│   │   ├── routes/          # 文件路由（/search、/blast、/genes、/downloads、...）
│   │   ├── components/      # React 组件（site-header 五导航等）
│   │   ├── page-builder/    # PageDefinition 渲染器/registry/seed/loader
│   │   ├── lib/             # widget-loader、deployment、view-transitions 等
│   │   └── workers/         # Web Workers（离主线程搜索）
│   ├── scripts/             # SSG 构建脚本（tsx）：ssg-build/ssg-content/build-manifest/validate-static-tree…
│   └── dist/                # 生成静态输出（含 dist/releases/<release-id>/<digest>/）
│
├── admin/             # Admin 控制台（React + Vite，Web-only）
│   └── src/
│       ├── routes/          # 管理页（page-builder 三栏编辑器、widgets、content、...）
│       ├── components/      # page-builder 编辑器组件等
│       └── lib/             # widget-api、page-builder-api（fetch）
│
├── api/               # FastAPI 后端（Python 3.13+）
│   └── app/
│       ├── api/v1/          # REST 端点（admin/*、page-definitions、content、genes、blast、...）
│       ├── page_builder/    # 服务端组件 registry（allowlist）+ service
│       ├── widgets/         # Widget registry + 渲染 + 缓存
│       ├── search/          # 外部适配器（NCBI/UniProt/Ensembl/EBI）
│       ├── core/            # 数据库、配置、鉴权、任务契约
│       ├── models/          # ORM（content、publication、page_builder、data_publishing、...）
│       ├── services/        # 业务逻辑（publication_service、content_snapshot_service、release_service…）
│       └── migrations/      # Alembic（versions/0001…0017）
│
├── worker/            # Celery workers（多队列）
│   └── src/soymutdb_worker/
│       ├── tasks/           # ingest/export/stats/blast/analyses/static_publish…
│       ├── publication/     # 三适配器（local/github_pages/cloudflare_pages）
│       ├── repositories.py / tables.py / utils/
│
├── jbrowse/           # JBrowse 2 基因组浏览器静态资产
└── mcp-server/        # MCP server（Python）

packages/
├── api-client/        # 类型化 Fetch API client（+ 生成的 openapi.d.ts）
├── i18n/              # 英/中翻译
├── jobs-py/           # 共享 jobs 契约（任务名/队列/状态机，API 与 worker 共用）
├── shared/            # 共享 DTO（page-builder 等）
├── motion/            # GSAP/Lenis 动画 hooks
└── ui/                # 共享 shadcn/ui 组件库

infra/
├── nginx/             # Nginx 配置：gzip、静态、反代、admin allowlist
├── docker/            # Dockerfile（api/worker/mcp-server）+ compose
├── clickhouse/        # ClickHouse schema/迁移
└── monitoring/        # Prometheus 指标

tools/
├── code-review/       # 确定性代码评审引擎
└── a0/                # A0 工具链（gate 契约）
```

## 安全分层

XSS 纵深防御：

1. 服务端模板：Jinja2 `autoescape=True`
2. 服务端消毒：`bleach.clean()` + Page Builder 组件 allowlist（拒绝未知组件/props/inline handler/raw script）
3. 客户端内联 loader：`<template>` DOM 解析 + Trusted Types policy
4. 客户端 TS：DOMPurify before 动态插入；SSG `ssg-content.ts` 统一属性转义 + URL 协议白名单（拒绝 `javascript:`）
5. Web Component：DOMPurify + Trusted Types + Shadow DOM

附加：

- SQL 全参数化（无 f-string 拼接查询）
- CSP 头锁定 script/style 来源
- 管理端点 JWT 鉴权 + 角色校验；凭据只存 env，API 响应与审计日志 redact 敏感字段
- 速率限制 + 外部 API 调用断路器
- 不可变静态发布：目标作用域单调 `publication_id` + 租约 + 陈旧任务 superseded，失败/陈旧绝不替换当前指针

## HTML5 现代特性

- **View Transitions API** — 平滑路由导航
- **Web Components** — `<soymutdb-widget>` 自定义元素 + Shadow DOM
- **Web Workers** — 搜索过滤/排序离主线程
- **IntersectionObserver** — 懒加载 widget、滚动动画
- **PerformanceObserver** — LCP/FID/CLS/INP Core Web Vitals 上报
- **requestIdleCallback** — 非关键初始化
- **OffscreenCanvas** — 高性能轨道视图（含 fallback）
- **Trusted Types** — CSP 安全的 HTML 赋值
- **CSS Container Queries / :has() / @layer** — 自适应与显式层叠

## Performance targets

| Endpoint              | Target         |
|-----------------------|----------------|
| 静态页 TTFB           | < 10 ms（Nginx/静态托管）|
| 缓存 widget 渲染      | P95 < 50 ms    |
| 内部 API              | P95 < 200 ms   |
| Hot Widget/search     | > 80% 缓存命中 |
| Core Web Vitals       | 全部 "Good"    |

## Scripts reference

```bash
pnpm dev        # Turbo 并行 dev
pnpm build      # Turbo 构建
pnpm lint       # Turbo lint
pnpm typecheck  # Turbo typecheck
pnpm test       # Turbo test
pnpm dev:web    # web 开发服务器
pnpm dev:admin  # admin 开发服务器
pnpm build:web  # web → dist/
pnpm build:admin # admin web bundle
pnpm build:ssg  # SSG 页面 + samples
```

## License

CC-BY 4.0（数据内容）、MIT（代码）。详见 consortium。
