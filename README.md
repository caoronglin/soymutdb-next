# SoyMutDB Next

> Comprehensive multi-species mutant database (soybean as the first/default species) — public SSG portal, native desktop admin, Rust-accelerated hotpaths.

## Architecture (three-tier isolation)

```
┌─────────────────────────────────────────────────────────────┐
│  Nginx (gzip + gzip_static + sendfile)                      │
│                                                             │
│  /             ──► SSG static HTML (apps/web/dist/)          │
│  /samples/*.html                                              │
│  /sra, /compare, ...   (static shells, client-side hydration)│
│                                                             │
│  /api/v1/*     ──► FastAPI (apps/api)                         │
│                     ├─ /widget/{name}   → sanitized HTML     │
│                     ├─ /search          → sanitized HTML     │
│                     ├─ /track.gif       → analytics pixel    │
│                     ├─ /admin/*         → admin API (JWT)    │
│                     └─ /sra/*           → SRA JSON API       │
│                                                             │
│  /core/*       ──► Rust hotpath (apps/core-rs)  [internal]   │
│                     Axum on 127.0.0.1:8001                  │
│                     ├─ widget rendering (Tera + ammonia)     │
│                     ├─ search aggregation (parallel fan-out) │
│                     └─ analytics ingestion (batch ClickHouse)│
│                                                             │
│  /admin/       ──► localhost/intranet ONLY                    │
│                  ├─ Nginx allowlist (RFC1918 + localhost)    │
│                  └─ Or: native Tauri desktop app              │
│                       (apps/admin/src-tauri, no browser)      │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────┐    ┌─────────┐    ┌───────────┐
│  PostgreSQL     │    │  Redis  │    │ ClickHouse│
│  users/widgets  │    │  cache  │    │ analytics │
└─────────────────┘    └─────────┘    └───────────┘
```

### Strict isolation guarantees

| Tier          | Technology       | Boundary                                |
|---------------|------------------|-----------------------------------------|
| Public Web    | SSG HTML + React | Static files; no server-rendered HTML   |
| API           | FastAPI (Python) | Sanitized HTML fragments + JSON only    |
| Admin         | React + Tauri    | Desktop app OR localhost-only web       |
| Rust Hotpath  | Axum (Rust)      | 127.0.0.1 only; benchmark-gated         |

No frontend code directly connects to databases. All data flows through API/widget/search/analytics layers.

## Quick start

### Prerequisites

- Node.js ≥ 20 (pnpm ≥ 10)
- Python ≥ 3.10 (with uv or pip + venv)
- Rust ≥ 1.75 (for core-rs hotpath and Tauri; optional for web-only dev)

### Install

```bash
pnpm install
```

### Run development servers

```bash
# Public web portal (SSG + Vite dev)
pnpm dev:web

# Admin console (web mode, localhost only)
pnpm dev:admin

# Admin console (native Tauri desktop, no browser window)
pnpm dev:admin-desktop

# Rust hotpath service
pnpm dev:core

# FastAPI backend
cd apps/api && uvicorn app.main:app --reload --port 8000
```

### Build

```bash
# Build web SSG
pnpm build:web
pnpm build:ssg           # generates static pages + samples
gzip -krf apps/web/dist/ # pre-compress

# Build admin web bundle
pnpm build:admin

# Build Tauri admin desktop app
pnpm build:admin-desktop # produces native binary in apps/admin/src-tauri/target/release

# Build Rust hotpath
pnpm build:core
```

### Code review

The deterministic code review pipeline (inspired by alibaba/open-code-review)
runs security/perf/correctness rules across the codebase:

```bash
pnpm review
# → tools/code-review/reports/manual/review-report.html
```

## Deployment

> 完整部署架构（拓扑图 / 访问入口矩阵 / 环境变量矩阵 / 从零部署步骤 / 故障排查 / 备份恢复）见
> **[docs/design/deployment-architecture.md](docs/design/deployment-architecture.md)**。

**当前生产部署现状（2026-08）：**

| 面 | 方式 | 入口 |
| --- | --- | --- |
| 前端（web 门户） | GitHub Pages 静态托管（push main → CI 自动发布到 gh-pages 分支） | https://caoronglin.github.io/soymutdb-next/ |
| 后端 + 数据面 | docker compose（api / worker×3 / beat / postgres / clickhouse / redis×2 / minio / mcp-server / nginx / prometheus / grafana） | `http://<HOST>:8080`（nginx）→ `/api/v1/*`、`/mcp/*`（SSE） |

**快速上手（生产服务器）：**

```bash
sudo bash deploy/linux/install.sh             # 安装布局 /opt/soymutdb + .env 模板
# 编辑 /opt/soymutdb/.env（模板：deploy/.env.example；必填镜像 tag/JWT/CORS/全部凭据）
sudo bash deploy/scripts/upgrade.sh           # 预检 → 拉镜像 → 迁移 → 启动 → 健康检查
bash deploy/scripts/healthcheck.sh            # 服务健康检查
bash deploy/scripts/backup.sh                 # 数据备份（PG+CH+S3，upgrade 前自动执行）
```

**备选路径（conda 裸进程，无 docker / 离线 / 本地开发）：**

- 指南：[`deploy/conda/README.md`](deploy/conda/README.md)；推荐组合：docker 起数据层（postgres/clickhouse/redis/redis-celery/minio）+ conda 跑应用层（api/worker/beat）。
- 一键准备：`bash deploy/scripts/conda-deploy.sh`（创建/更新 `soymutdb-api`、`soymutdb-worker` 环境 → 装应用代码 → 生成/校验 `.env` → 输出启动命令）。

**非主路径（已废弃/已放弃，仅保留参考）：**

- `deploy/cloudflare.md` — 旧 Cloudflare Pages 静态托管方案（已改为 GitHub Pages）。
- `deploy/windows/` — Windows 服务部署（已废弃，docker compose 为主路径）。

## Project layout

```
apps/
├── web/             # Public SSG portal (React + Vite + TanStack Router)
│   ├── src/
│   │   ├── routes/          # File-based routes (/sra, /compare, /search, ...)
│   │   ├── components/      # React components + Custom Elements
│   │   ├── lib/             # widget-loader, view-transitions, perf, motion-config
│   │   └── workers/         # Web Workers (off-main-thread search)
│   ├── scripts/             # SSG build scripts (TypeScript, runs via tsx)
│   └── dist/                # Generated static output (committed selectively)
│
├── admin/           # Admin console (React + Vite + TanStack Table)
│   ├── src/
│   │   ├── routes/          # Admin pages (widgets, layouts, analytics)
│   │   └── lib/tauri-api.ts # Dual-mode API (Tauri IPC or fetch)
│   └── src-tauri/           # Tauri v2 native desktop wrapper
│       ├── src/main.rs      # Native window, IPC commands, file import
│       ├── Cargo.toml
│       └── tauri.conf.json  # CSP locked to localhost only
│
├── api/             # FastAPI backend (Python 3.10+)
│   └── app/
│       ├── api/v1/           # REST endpoints (sra, genes, variants, ...)
│       ├── widgets/          # Widget registry + rendering + cache
│       ├── search/           # External adapters (NCBI/UniProt/Ensembl)
│       ├── analytics/        # track.gif pixel + ClickHouse ingestion
│       ├── core/             # Database, config, auth, compatibility
│       └── services/         # Business logic
│
├── core-rs/         # Rust hotpath (optional, benchmark-gated)
│   └── src/
│       ├── widgets.rs        # Tera rendering + ammonia sanitization
│       ├── search.rs         # Parallel fan-out with circuit breakers
│       ├── analytics.rs      # High-throughput pixel + batched writes
│       ├── cache.rs          # L1 LRU + L2 Redis + single-flight
│       └── server.rs         # Axum router (127.0.0.1:8001)
│
├── jbrowse/         # JBrowse 2 genome browser static assets
└── worker/          # Celery workers

packages/
├── ui/              # Shared shadcn/ui component library
├── motion/          # GSAP/Lenis animation hooks (useReveal, useSmoothScroll)
├── api-client/      # Typed Fetch API client
└── i18n/            # English + Chinese translations

infra/
├── nginx/           # Nginx config: gzip, static, reverse proxy, admin allowlist
├── docker/          # Docker Compose stack
└── monitoring/      # Prometheus metrics

tools/
└── code-review/     # Deterministic code review engine (Open Code Review style)
```

## Security layers

XSS is defended in depth:

1. **Server templates**: Jinja2 `autoescape=True` on all renders
2. **Server sanitization**: `bleach.clean()` on all external/HTML content
3. **Client inline loader**: `<template>` DOM parse + Trusted Types policy
4. **Client TypeScript**: DOMPurify before all dynamic insertions
5. **Web Component**: DOMPurify + Trusted Types + Shadow DOM isolation

Additional:
- SQL parameterization everywhere (no f-strings in queries)
- CSP headers lock script/style sources
- Admin bound to 127.0.0.1; Nginx `/admin/` RFC1918 allowlist
- Tauri admin CSP restricts connect-src to 127.0.0.1/localhost
- Rate limiting + circuit breakers on all external API calls
- Secrets via environment variables only (`.env.example` provided)

## HTML5 modern features

- **View Transitions API** — smooth route navigations
- **Web Components** — `<soymutdb-widget>` Custom Element with Shadow DOM
- **Web Workers** — search filter/sort off main thread
- **IntersectionObserver** — lazy widget loading, scroll-triggered animations
- **PerformanceObserver** — LCP/FID/CLS/INP Core Web Vitals reporting
- **requestIdleCallback** — non-critical initialization
- **OffscreenCanvas** — high-performance track viewer (with fallback)
- **Trusted Types** — CSP-safe HTML assignment
- **CSS Container Queries** — `.widget-container` adaptive layouts
- **CSS :has()** — parent state styling
- **CSS @layer** — explicit cascade control
- **Navigator Network Information API** — `saveData` → reduced animations

## Performance targets

| Endpoint              | Target         |
|-----------------------|----------------|
| Static page TTFB      | < 10 ms (Nginx)|
| Cached widget render  | P95 < 50 ms    |
| Internal API          | P95 < 200 ms   |
| Hot Widget/search     | > 80% cache hit|
| Core Web Vitals       | All "Good"     |

## Scripts reference

```bash
pnpm dev:web              # Vite dev server for public portal
pnpm dev:admin            # Vite dev server for admin (web)
pnpm dev:admin-desktop    # Tauri dev (native window)
pnpm build:web            # Build web → dist/
pnpm build:ssg            # SSG pages + samples
pnpm build:admin          # Admin web bundle
pnpm build:admin-desktop  # Native binary (requires Rust)
pnpm build:core           # Rust hotpath binary (requires Rust)
pnpm review               # Run code review engine
pnpm lint                 # Turbo lint
pnpm typecheck            # Turbo typecheck
pnpm test                 # Turbo test
```

## License

CC-BY 4.0 (database content), MIT (code). See consortium for details.
