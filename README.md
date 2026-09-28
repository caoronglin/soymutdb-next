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
│                     ├─ /admin/* → 管理 API（JWT，设置/导入/发布等） │
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
| Public Web | React 19 + Umi Max 4、TanStack Router/Query、Ant Design 6；external/internal 分离 SSG | 纯静态双站制品；迁移和交付契约尚未验收（`apps/web/package.json`） |
| API | FastAPI（Python） | 消毒 HTML 片段 + JSON；OpenAPI 是唯一契约 |
| Admin | React 19 + Umi Max 4、Ant Design 6 + ProComponents v3 | 静态托管 + 受保护 Admin API（JWT）（`apps/admin/package.json`） |
| JBrowse | React + Umi Max 4 壳，使用 `@jbrowse/react-linear-genome-view` | 静态托管于 `/soymutdb-jbrowse/`；core profile 下可选 |
| Worker | Celery（多队列） | ingest/export/stats/cleanup/blast/analyses；直连数据层（窄 SQLAlchemy Core） |

前端代码不直连数据库；数据统一经 API / worker 层。Tauri 桌面壳与 Rust 热路径（`core-rs`）已清理移除，当前仅保留 Web-only Admin。

## 构建与交付

交付链路由 **CNB 主链路** 定义（`.cnb.yml`），GitHub Actions 作为镜像保留，两者
调用同一批脚本，因此不存在"两边行为不一致"的可能。

```bash
pnpm ci:jobs                                  # 列出可用交付任务
pnpm ci:verify                                # 前端门禁
pnpm ci:api                                   # 后端门禁（需一次性 PostgreSQL）
pnpm ci:images                                # 镜像构建/冒烟/扫描/SBOM（不发布）
pnpm ci:release                               # 签名并发布 OCI release

bash scripts/smoke.sh                         # 统一冒烟：contracts/static/runtime/e2e/images
bash scripts/smoke.sh --list                  # 查看可用 layer

bash scripts/acceptance.sh --profile full     # 平台验收：contracts + backend + static + runtime
```

### 在 CNB 上启动与验收

| 想做的事 | 入口 |
| --- | --- |
| 起一个可运行的开发环境 | 分支页「启动 SoyMutDB 开发环境」按钮（`vscode` 事件）；进入后直接是门户预览页 |
| 手动要预览环境 | 「启动门户预览环境」按钮（`web_trigger_workspace-preview`） |
| 判断某个修订能不能收 | 「运行验收」按钮（`web_trigger_acceptance`）或 `pnpm accept` |

```bash
pnpm dev:cloud                                # 本地起云开发环境（等于 CNB 上的启动按钮）
pnpm accept --profile contracts               # 验收：交付契约（默认，无外部依赖）
pnpm accept --profile backend                 # 验收：API + Worker（需 PostgreSQL）
pnpm accept --profile static                  # 验收：静态制品 + 字节校验
```

* 完整架构、流水线拓扑、镜像打包发布流程与冒烟分层：`docs/ops/ci-cd.md`
* 启动与验收入口、验收清单（evidence）与两种"分层姿态"的区别：`docs/ops/cnb-startup-acceptance.md`
* 迁移对照、保留项、验证证据与前置缺陷：`docs/dev/pipeline-migration.md`

> 冒烟约定：前置条件缺失时输出 `SKIPPED: <原因>` 并计入 summary，**不会冒充通过**。
> 验收约定：必需层的前置条件缺失输出 `BLOCKED: <原因>` 并**判定失败**——在平台上
> 前置条件是流水线定义的属性，缺了应修流水线，而不是把这一层放行。

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
cd apps/api && uvicorn app.main:app --reload --port 8010

# Celery worker（按队列；见 deploy/conda/README.md §6）
cd apps/worker && celery -A soymutdb_worker.main:celery_app worker --loglevel=info
```

Docker 开发拓扑使用生产基础文件加开发 overlay：`docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile core up --build`。它会启动 API、workers、PostgreSQL、ClickHouse、Redis、MinIO，以及 Vite web/admin（端口 5173/5174）。只需数据层时可在同一命令后指定 `postgres clickhouse redis redis-celery minio minio-init`。

只想用「当前 checkout」构建并运行**生产编排**（不需要 release 制品、不需要 registry）：

```bash
bash scripts/compose-local.sh build   # 按 scripts/list-images.sh 构建 8 个 release 镜像
bash scripts/compose-local.sh up -d   # 用这些镜像启动生产拓扑
bash scripts/compose-local.sh down
```

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
# 编辑 /opt/soymutdb/.env（模板：deploy/.env.example；必填 6 个镜像 digest/JWT/CORS/凭据）
sudo bash deploy/scripts/upgrade.sh           # 预检 → 拉镜像 → 迁移 → 启动 → 健康检查
bash deploy/scripts/healthcheck.sh            # 服务健康检查
bash deploy/scripts/backup.sh                 # 数据备份（PG+CH+S3，upgrade 前自动执行）
bash deploy/scripts/verify-restore.sh <backup> # 恢复演练校验
```

**备选路径（conda 裸进程，无 docker / 离线 / 本地开发）：**

- 指南：[`deploy/conda/README.md`](deploy/conda/README.md)；推荐：docker 起数据层（postgres/clickhouse/redis/redis-celery/minio）+ conda 跑应用层（api/worker/beat）。
- 一键准备：`bash deploy/scripts/conda-deploy.sh`。

**核心功能部署（不部署 JBrowse 等可选服务）：**

SoyMutDB 是数据库产品：`core` profile 即可提供搜索、实体详情、下载与内容；基因组浏览器、BLAST、按需分析与 MCP 各自独立为可选 profile，核心部署不需要它们。

```bash
# 只起核心数据面与后端（不含 jbrowse / blast / analyses / mcp）
docker compose --profile core up --build

# 需要某个可选服务时再叠加对应 profile
docker compose --profile core --profile jbrowse up -d
```

前端与静态制品同样支持“无 JBrowse”：

```bash
VITE_JBROWSE_ENABLED=0 pnpm --filter @soymutdb/web build        # 门户隐藏浏览器入口与链接
SOYMUTDB_JBROWSE_ENABLED=0 bash scripts/build-pages-artifact.sh  # Pages 制品省略 jbrowse 子应用
```

关闭时：门户隐藏浏览器导航，`/browser`、`/gbrowse` 落到明确说明页而非 404；Pages 制品以 `.no-jbrowse` 标记声明缺失并通过校验。详见 **[核心功能部署](docs/ops/core-only-deployment.md)**。

## 文档入口

- [科研用户指南](docs/user/README.md)
- [项目 Wiki](docs/wiki/README.md)（架构、应用状态、API/端口、部署运维、多实例信任）
- [项目状态](docs/dev/project-status.md)（部署、门禁、功能与缺口单一视图）
- [运维与 Admin 手册](docs/ops/README.md)
- [核心功能部署（JBrowse 可选）](docs/ops/core-only-deployment.md)
- [CNB 启动与验收](docs/ops/cnb-startup-acceptance.md)
- [开发者架构与部署](docs/dev/README.md)
- [历史部署设计（仅参考）](docs/design/deployment-architecture.md)

## 非主路径（已废弃/已放弃，仅保留参考）

- `deploy/cloudflare.md` — Cloudflare Pages 可选静态托管手册；GitHub Pages 仅承载公开 demo。
- `deploy/conda/no-docker-data-layer.md` — 完全无 Docker 数据层探索（conda 裸进程备选）。

## Project layout

```
apps/
├── web/               # React 19 + Umi Max 4 公共 SSG 门户（external/internal）
│   ├── src/routes/          # TanStack Router file routes
│   ├── src/components/      # React 页面组件与可复用 UI
│   ├── src/lib/             # deployment、i18n、query/cache、SSG 客户端
│   ├── scripts/             # 双站 build、静态路由、CSP、SW、release manifest
│   └── dist/{external,internal}/ # 隔离的静态输出
│
├── admin/             # React 19 + Umi Max 4 管理控制台
│   └── src/
│       ├── routes/          # React 管理页（dashboard、导入、发布、内容、设置）
│       ├── components/      # 可复用 UI 组件
│       └── lib/             # api-client 封装、实例上下文、主题等
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
├── jbrowse/           # React + Umi 壳，使用 @jbrowse/react-linear-genome-view（src/App.tsx）
└── mcp-server/        # MCP server（Python）

packages/
├── api-client/        # 类型化 Fetch API client（+ 生成的 openapi.d.ts）
├── charts/            # React/ECharts 图表 facade
├── genome-data/       # 基因组数据源/适配器（@soymutdb/genome-data）
├── genome-view/       # 旧 Vue 基因组视图组件（待迁移清理）
├── genome-view-model/ # 浏览器 viewport 状态模型
├── i18n-core/         # en/zh 字典与 i18next 绑定
├── import-protocol/   # 导入任务契约
├── jobs-py/           # 共享 jobs 契约（Python，API 与 worker 共用）
├── query-keys/        # 查询缓存键契约
├── shared/            # 共享 DTO 与工具
└── ui-vue/            # 共享 Vue 设计系统门面

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
pnpm smoke      # 统一冒烟（contracts/static/runtime/e2e/images）
pnpm accept     # 平台验收（contracts/backend/static/runtime/…）
pnpm dev:cloud  # 云原生开发环境启动（与 CNB 启动按钮同一脚本）
```

## License

CC-BY 4.0（数据内容）、MIT（代码）。详见 consortium。
