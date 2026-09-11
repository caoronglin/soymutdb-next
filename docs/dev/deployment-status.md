# 部署现状核对（D0）与状态记录

> 状态：D0 交付。日期 2026-09-09，HEAD `6592dfd8e`，工作树含大量既有未提交修改（约 357 项，归属既有工作）。
> 本文档执行 `docs/dev/pi-website-deployment-handoff.md` 的 D0 工作包：核对部署脚本、Compose、CI、迁移、
> 双站构建与健康接口，逐项给出文件或运行证据。历史材料（pi-overall-2026-09-08 等）仅作线索，不作为完成证据。
> 状态取值：NOT_STARTED / IN_PROGRESS / IMPLEMENTED_UNVERIFIED / BLOCKED_ENVIRONMENT / FAILED / VERIFIED。

## D0 能力与缺口表

### A. 已存在能力（有文件证据）

| 能力 | 证据 | 结论 |
| --- | --- | --- |
| 生产 Compose 拓扑（API/worker×4/beat/migrate 一次性服务/PG/CH/MinIO/Redis×2/nginx/MCP） | `docker-compose.yml`：镜像要求 digest 引用（`API_IMAGE_REF` 等）；`migrate` 服务 `service_completed_successfully`；fail-fast 安全配置校验；Redis 双实例（cache allkeys-lru / celery noeviction+AOF） | 已有且契约测试覆盖 |
| 开发 Compose overlay | `docker-compose.dev.yml`：postgres/clickhouse/redis×2/minio/api/worker×4/beat/web/admin/nginx + pnpm store 卷；`scripts/test_development_compose_contract.py` 断言 overlay 替换生产镜像要求、补齐基础凭据 | 已有 |
| 生产发布主路径 | `deploy/scripts/upgrade.sh`：compose config 校验 → 安全预检 → 镜像 manifest 预检 → 拉镜像 → 备份 → 一次性迁移（alembic + migrate-clickhouse）→ up → readiness 轮询（失败自动回滚旧镜像）→ 业务 smoke → 记录 `.release-state.json`（OCI digest、迁移版本、时间） | 已有 |
| 蓝绿双槽发布 | `deploy/scripts/blue-green-{common,deploy,rollback}.sh`：签名 release manifest 校验、`acquire_blue_green_lock` 环境级互斥锁、失败恢复原 slot | 已有 |
| 备份/恢复/演练 | `backup.sh`/`restore.sh`/`verify-restore.sh`/`baseline-*`（backup/restore/rollback/healthcheck/upgrade）+ `scripts/test_backup_restore_contracts.py` | 已有 |
| 健康检查 | `apps/api/app/api/v1/health.py`：`/health/live`（进程存活）、`/health/ready`（必需依赖，可选能力分别报告，不以单点可选故障退出）；`deploy/scripts/healthcheck.sh` 汇总各服务 | 已有 |
| 双站构建与 release manifest | `apps/web/scripts/build-sites.ts`：`VARIANTS = ["external","internal"]` 显式两树构建；`release-manifest.ts`：非生产模式跳过、生产强制 `SOYMUTDB_RELEASE_ID`，产出 manifest + sha256 | 已有 |
| 部署/交付契约测试 | `scripts/test_deployment_workflows.py`、`test_development_compose_contract.py`、`test_kubernetes_delivery_contracts.py`、`test_backup_restore_contracts.py`、`test_cloudflare_tunnel_contract.py` | 已有 |
| 隔离 PostgreSQL 验证环境 | `.mamba-root/envs/postgres16`（PG16，端口 55432，trust）；`docs/dev/mamba-validation-environment.md`；本日用它运行了 API/worker 全套与迁移测试（见下"运行证据"） | 已有且已运行验证 |
| CI | `.github/workflows/ci.yml`：frontend / api-tests / dependency-governance / docker-build / kubernetes-kind / publish-images / clickhouse-migration；另有 `e2e-smoke.yml`、`baseline-validation.yml`、`pages.yml` | 已有 |

### B. 缺口（对照 handoff 拟定入口）

| 缺口 | 说明 | 归属 |
| --- | --- | --- |
| 统一部署入口 `scripts/deploy/{preflight,build,verify,migrate,deploy,smoke,rollback}.sh` | 不存在（已核对）。须复用 `deploy/scripts/upgrade.sh`、`blue-green-*`、`healthcheck.sh`、`build-sites.ts` 等既有入口适配，不得另建平行体系 | D1/D4 |
| 显式环境参数与环境互斥 | `upgrade.sh` 面向生产（root、`/opt/soymutdb`）；无 `--environment development --dry-run` 语义。蓝绿锁存在，但开发环境无统一锁入口 | D4 |
| 部署文档四件套 | `docs/dev/deployment-{design,hard-constraints,runbook,verification}.md` 均不存在；现有 `docs/dev/architecture-and-deployment.md`、`deploy/cloudflare.md` 为架构/边缘方案文档 | D0/D7 文档阶段合并 |
| Docker 环境不可用 | 本工作区无 Docker 守护进程：`docker compose config`、真实容器冒烟、kubernetes-kind 均无法在本机执行。隔离开发验证改用 mamba PostgreSQL + 原生 uvicorn（见下） | BLOCKED_ENVIRONMENT |
| Worker 版本兼容验证 | Worker 新旧版本共存的消息/结果/库结构兼容验证无现成测试；`test_module_tsv_postgres_integration.py` 已支持外部隔离 PG | D4/D6 |
| 双站负向泄漏扫描运行证据 | `scripts/check_site_artifact_isolation.py` 存在；本轮未构建双站制品，`dist/external` 零泄漏扫描未取得新证据 | D5 |

### C. 运行证据（本轮实际执行，隔离环境）

- 工具链：Node 24.19.0 / pnpm 11.21.0 / Python 3.14.6（`apps/api/.venv`）；Docker 不可用（`docker info` 失败）。
- 隔离 PG：mamba PostgreSQL 16，`initdb`+`postgres -p 55432` 已在 `.validation/postgres16` 就绪，`pg_isready` 接受连接。
- 迁移链：Alembic head = `0034_gene_crosswalks`；`apps/api` `test_migrations.py` 8 passed（真实 PG upgrade/降级拒绝）。
- API 全套（隔离 PG，仓库根运行）：1445 passed / 33 failed——31 例归属既有未提交工作改造模块（expression/homolog keyset、exppattern/seqfetch gene_pk 重构），2 例为本轮修复的 release_service fake 断言（现 4/4 passed）。
- Worker 全套：301 passed / 4 skipped；启用 PG gate 后 module_tsv 集成 3 passed + gene_resolution 4 passed。
- Web/Admin：`pnpm typecheck` 6/6 通过；`pnpm test` 中 admin 22 failed 均归属既有未提交工作（14 个未跟踪新文件 + HEAD 遗留）。
- E2E / 双站构建 / 对象存储集成：本轮未运行，记录为 IMPLEMENTED_UNVERIFIED。
- 泄漏扫描器自测：`python3 -m unittest scripts.test_site_artifact_isolation` → 6 tests OK（扫描器机制验证；非真实制品扫描，不替代 Gate 4）。

## 工作包状态

| 工作包 | 状态 | 交付物 | 下一步 |
| --- | --- | --- | --- |
| D0 现状核对 | VERIFIED | 本文档 A/B 表 + 运行证据 | 逐缺口进入 D1+ |
| D1 预检 | VERIFIED | `scripts/deploy/preflight.sh`（显式环境必需，拒绝缺失/未知值；工具链/本地 FS/H07/工作区保护/docker/mamba PG 检测；无 secrets 输出） | 接入 D4 入口 |
| D2 核心验收 | PARTIAL：API/Worker/契约已在隔离 PG 验证（见上）；双站与 E2E 未跑 | 分层 CI 检查沿用 ci.yml | 双站 build:sites + 泄漏扫描 |
| D3 发布 manifest | PARTIAL | release-manifest.ts + upgrade.sh 记录已有；**发现并修复迁移/模型漂移（0035）** | 逐迁移兼容范围核对 |
| D4 开发部署入口 | PARTIAL（原生路径 VERIFIED） | 新增 `scripts/deploy/smoke.sh --environment development`：一次性 PG Alembic upgrade → 真实 uvicorn → /health/live、/health/ready（baseline 模式仅 PG 就绪语义，可选依赖 disabled）→ 真实公开搜索链（空库 503 fail-closed 确认） | Docker 化冒烟待环境 |
| D5 预发布验收 | PARTIAL | **双站构建 + 泄漏扫描已运行**（demo 制品，原生路径）：build:sites 两树成功；扫描器正向检出自测（污染→1/缺目录→2/干净→0）；真实制品扫描 OK（内部哨兵在 internal 命中 1、external 128 文件零命中）；internal 含 noindex、external 无 noindex | 真实 release 制品需可达 release API（含 CH 投影） |
| D2 双站/扫描 | PARTIAL→增强 | 见上；注记：本地构建的 origin（127.0.0.1:8765）会烧入制品——含构建时 origin 的制品不可跨环境复用（H05），本机制品仅限本机验证 | — |
| D6 生产发布/回滚准备 | NOT_STARTED | 蓝绿/upgrade.sh 已有；缺生产隔离演练（另授权） | 演练仅隔离环境 |
| D6 迁移兼容 | PARTIAL：扩展/收缩模式在 0033 显式拒绝降级有测试；expand/backfill/shrink 分阶段设计待逐迁移评估 | — | — |

### D4 阶段证据（原生冒烟，2026-09-10）

```text
bash scripts/deploy/smoke.sh --environment development   # exit 0，SMOKE PASS
1) Alembic upgrade head：0001→0035 全链成功（一次性 soymutdb_validation 库）
2) uvicorn（真实 app.main:app）启动成功
3) /health/live → {"status":"ok"}
   /health/ready → {"status":"ok","checks":{"postgres":{"healthy":true},
                     "clickhouse":{"status":"disabled","required":false},
                     "redis":{"status":"disabled","required":false}}}
4) GET /api/v1/search?query=Glyma → 503 + "No active data release is available"
   （空库 fail-closed release-context 解析确认，非缺陷）
```

### D3 缺陷修复：releases 模型/迁移漂移（迁移 0035）

原生冒烟在真实迁移库上首次暴露：模型 `Release` 的 `assembly_id`、`variant_count`、
`gene_count`、`mutant_line_count`、`published_at`、`published_by`、`approved_by`、
`notes` 从未进入迁移链（`create_all` 测试环境掩盖了该漂移），公开搜索端点在
Alembic 库上 500（`UndefinedColumnError`）。修复：

- 新增 `apps/api/migrations/versions/0035_release_assembly_id.py`（纯 expand：
  全部缺失列 + 零默认计数器 + `ix_releases_assembly_id`；可逆 downgrade）。
- 升降级再升验证：downgrade 0034 → upgrade head → current = 0035，列存在确认。
- `pytest tests/test_migrations.py tests/test_release_service.py tests/test_openapi_contract.py`
  → 32 passed。

### D5 运行证据（2026-09-10，demo 双站制品）

```bash
# 构建需显式 origin + GOMAXPROCS=2（esbuild newosproc 线程限制规避）
GOMAXPROCS=2 VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=http://127.0.0.1:8765   VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test   pnpm --filter @soymutdb/web build:sites
# → external built in 13.49s；internal built in 13.48s；both artifacts ready

# 扫描器自测（污染/缺目录/干净三态）
python3 scripts/check_site_artifact_isolation.py --external-root /tmp/iso-test/external   --internal-root /tmp/iso-test/internal --sentinel SENTINEL-X9   # exit 1（必须失败）
python3 scripts/check_site_artifact_isolation.py --external-root /tmp/iso-test/clean   --internal-root /tmp/iso-test/internal --sentinel SENTINEL-X9   # exit 0

# 真实制品扫描：哨兵 "Internal Research Workspace for SoyMutDB"
#   注入证明：dist/internal 命中 1；dist/external 128 文件命中 0
python3 scripts/check_site_artifact_isolation.py --external-root apps/web/dist/external   --internal-root apps/web/dist/internal --sentinel "Internal Research Workspace for SoyMutDB"
# → OK: external artifact contains no supplied protected values (exit 0)
```

附带核验：internal index.html 含 noindex；external 无 noindex（正确——noindex 非鉴权，仅区分）。
注记：VITE_API_BASE_URL 烧入制品（external 也含 127.0.0.1:8765）——符合构建时绑定设计，
但该制品仅限本机验证，不得部署到其他环境（H05 制品标识）。

### 带数据的真实 API 链路（D2 补充，合成 fixture，隔离 PG）

一次性 `soymutdb_validation` 库（Alembic 迁移链全量升级）播种：published release +
active 指针 + v4 assembly + 基因 Glyma.01G000100(gene_pk 710001) + 突变体 SMV4TEST01 +
2 条变异摘要。真实 uvicorn (127.0.0.1:8765) 验证：

- `GET /api/v1/search?query=SMV4TEST01` → 200，exact 命中，`url=/mutants/SMV4TEST01`，无内部键
- `GET /api/v1/search?query=Glyma` → 200，gene 命中带 `assembly_id=7101`、`url=/genes/…?assembly=7101`（assembly/release 上下文可见）
- `GET /api/v1/mutants/SMV4TEST01` → 200，仅 public_id（无 internal_id/id）
- `GET /api/v1/genes/Glyma.01G000100?assembly_id=7101` → 200
- `GET /api/v1/variants` → **500（ClickHouse 不可达）**：变异查询为 CH 投影依赖，
  baseline 环境下的已知边界；生产 extended 模式 CH required。建议（未实施）：
  CH 不可达时返回 503 + 明确能力状态，而非 500 栈回溯。

### variants 503 修复（D2 补充）

`app/services/variant_service.py`：CH 投影全部 4 个调用点经 `_ch_query` 包装，
`ClickHouseError` → `503 service_unavailable`（"Variant analytics projection
(ClickHouse) is unavailable"），无栈/主机泄漏。真实 uvicorn 验证：variants=503、
search=200、mutant detail=200（其余链路不受影响）；
`pytest tests/test_variants.py tests/test_migrate_clickhouse.py` → 22 passed。

### E2E 首次运行（playwright-public，demo 静态制品）

```bash
GOMAXPROCS=2 VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test   VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test pnpm --filter @soymutdb/web build
cd e2e && npx playwright test -c playwright-public.config.ts
# → 7 passed / 2 skipped / 20 failed（4.9m）
```

- 通过：homepage 等离线用例；skipped：2 例标记为需要真实后端。
- **根因已定位（构建配置，非产品回归）**：静态服务器把 dist 挂在
  `/soymutdb-next` 前缀下，而首次构建未设 `VITE_BASE_URL=/soymutdb-next/`，
  且 API origin 指向远端 `api.soymutdb.test`（离线不可达、也错过了
  static-server 的同源 mock `/soymutdb-next/api/v1/*`）。表现：index.html
  以 `/assets/*` 请求 → 404 → SPA 引导失败；以及 assemblies/chromosomes
  数据缺失导致表单无法提交。`git stash` 对照证明与工作树 diff 无关。

```bash
# 正确配置（base + 同源 mock API）
GOMAXPROCS=2 VITE_DEPLOYMENT_MODE=demo VITE_BASE_URL=/soymutdb-next/ \
  VITE_API_BASE_URL=http://localhost:4173/soymutdb-next/api/v1 \
  VITE_JBROWSE_BASE_URL=http://localhost:4173/soymutdb-next/jbrowse/ \
  pnpm --filter @soymutdb/web build
cd e2e && npx playwright test -c playwright-public.config.ts
# → 23 passed / 4 failed / 2 skipped (2.0m)   [修复前：7 passed / 20 failed]
```

- 剩余 4 例：`blast.spec` 2 例（表单渲染/空 FASTA 校验，离线路径）、
  `public-login` 1 例（POST+401 状态，需同源 mock 细节）、`search.spec`
  1 例（window.open 提交需 assemblies mock 数据）。
- 结论：E2E 在**无 Docker** 下可运行；主阻断是构建参数而非产品缺陷。
  剩余 4 例为独立缺陷，需逐个排查（下一任务）。

## 环境就绪标签

- DEV_READY：未授予。数据库集成与原生冒烟已通过（隔离 PG + uvicorn），但真实代理/双站制品/Worker 冒烟未通过——不满足"核心冒烟通过"全量语义。
- STAGING_READY / PRODUCTION_READY / DEPLOYED：未授予；生产部署、生产迁移与真实数据发布未获授权，不在本轮执行。

## 下一条可复现命令

```bash
# 隔离 PG 启动 + fixture 库（cwd: 仓库根）
PG_BIN=$PWD/.mamba-root/envs/postgres16/bin
$PG_BIN/postgres -D $PWD/.validation/postgres16 -p 55432 -c listen_addresses=127.0.0.1 \
  -c shared_preload_libraries=pg_stat_statements &
$PG_BIN/dropdb -p 55432 -h 127.0.0.1 -U soymutdb --if-exists soymutdb_testfixtures
$PG_BIN/createdb -p 55432 -h 127.0.0.1 -U soymutdb soymutdb_testfixtures

# 迁移 + API 全套（隔离 PG）
cd apps/api
SOYMUTDB_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_validation' \
  /mnt/data02/T25ronglin/.miniforge3/envs/soymutdb-test/bin/python -m alembic upgrade head
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_testfixtures' \
  apps/api/.venv/bin/python -m pytest apps/api/tests -q --rootdir=.   # cwd: 仓库根
```

---

# 第二轮接续（2026-09-11）：T1–T5 交付

> 起点 HEAD `2e0688dee`（`main`），工作树干净。本节记录本轮实际执行的命令与结果；
> 历史材料仅作线索，不作为完成证据。环境：本容器无 Docker、无 mamba、无预置 venv，
> 已按等价方式补齐（见"环境重建"）。
>
> 状态取值：NOT_STARTED / IN_PROGRESS / IMPLEMENTED_UNVERIFIED / BLOCKED_ENVIRONMENT / FAILED / VERIFIED。

## 环境重建（本容器，等价于 mamba 方案）

| 组件 | 方式 | 结果 |
| --- | --- | --- |
| PostgreSQL | apt `postgresql-15`，`initdb --auth=trust` 到 `.validation/postgres16`，端口 55432，用户 `soymutdb` | `pg_isready` 接受连接 |
| Python | uv 0.11.x + CPython **3.14.7**，`apps/api/.venv`、`apps/worker/.venv` | HTTP Client OK |
| Node/pnpm | Node 24.21.0、pnpm 11.21.0；`pnpm install --frozen-lockfile` | 46s 完成 |
| Playwright | chromium + headless shell 已安装 | `npx playwright test` 可运行 |
| 对象存储 | 下载 MinIO RELEASE.2025-09-07 单二进制，`127.0.0.1:9000` | `/minio/health/live` → 200 |

一次性库：`soymutdb_validation`（迁移/冒烟）、`soymutdb_testfixtures`（pytest fixture，
**每次运行前 drop/create**——否则 roles 唯一约束残留会让 1496 例中的 116 例报 IntegrityError）。

## 工作包状态（本轮）

| 工作包 | 状态 | 交付物 / 证据 | 下一步 |
| --- | --- | --- | --- |
| T1 公开站 E2E | **VERIFIED** | 27 passed / 0 failed / 2 skipped；`e2e/README.md` 补正确构建命令 | 2 例 live-backend 用例仍 skip（需真实后端） |
| T2 API 回归债 | **VERIFIED** | **1496 passed / 0 failed**（原 1447/31）；产品代码 `apps/api/app/**` 零改动（除 T4 修复） | — |
| T2 admin | **VERIFIED** | lint 0 error / 53 warning；typecheck OK；test 47 文件 / 119 passed | — |
| T2 worker | **VERIFIED** | 308 passed / 1 skipped（含 PG 集成 7 例） | — |
| T2 web | **VERIFIED** | 36 文件 / 172 passed（分批运行避 OOM）；typecheck OK；lint 0 error | 全量单进程在本容器会 OOM，已用 `NODE_OPTIONS=--max-old-space-size=2048` 分批 |
| T3 对象存储隔离 R07 | **VERIFIED** | 真实 MinIO 集成验证 PASS（4 对象互不覆盖 + 未发布对象不存在 + 匿名公开 GET 403）；`gene_object_key()` 纯函数 + 9 单测 | 生产 bucket 策略/签名 URL 待运维 |
| T4 CH 能力不可用 | **VERIFIED** | 真实 uvicorn：CH 端点 6/6 → 503，**0 个 500**；PG 统计端点 200 降级；新增 4+3 回归 | extended 模式需真实 CH 投影（另环境） |
| T5 文档与门禁 | **VERIFIED** | 本文档；`bash scripts/acceptance.sh --profile contracts` → ACCEPTANCE PASS | — |

## T1：公开站 E2E 4 例失败修复（根因 → 归属 → 处置）

构建命令（正确绑定 base + 同源 mock origin）：

```bash
cd <repo-root>
GOMAXPROCS=2 VITE_DEPLOYMENT_MODE=demo \
  VITE_BASE_URL=/soymutdb-next/ \
  VITE_API_BASE_URL=http://localhost:4173/soymutdb-next/api/v1 \
  VITE_JBROWSE_BASE_URL=http://localhost:4173/soymutdb-next/jbrowse/ \
  pnpm --filter @soymutdb/web build
cd e2e && npx playwright test -c playwright-public.config.ts
# → 27 passed / 0 failed / 2 skipped
```

| 用例 | 根因 | 归属 | 处置 |
| --- | --- | --- | --- |
| `blast.spec.ts` `/blast renders the full form` | `getByLabel(/sequence/i)` 同时命中 "Input Sequence" 与 "Reference sequence type" → strict mode violation | 测试选择器过期 | 改为 `getByRole("textbox", { name: "Input Sequence" })`；**断言未削弱** |
| `blast.spec.ts` 空 FASTA 被拒 | 提交按钮文案是 `blast.submit = "BLAST"`，测试找 `/submit\|run blast/i` → 45s 超时 | 测试选择器过期 | 改为 `getByRole("button", { name: "BLAST", exact: true })` |
| `public-login.spec.ts` 401 / 成功跳转 | **产品缺陷**：SSG 静态标记是惰性的，React 提交（handoff）前点击被静默丢弃 | 产品缺陷 | 新增就绪信号 `data-app-ready`；测试用 `waitForAppReady()` 等待 |
| `search.spec.ts` window.open 未触发 | **产品缺陷**：assembly 未解析时提交被静默丢弃（`formAssemblyId` 为空直接 return） | 产品缺陷 | 提交按钮在 assembly 上下文就绪前 `disabled` + 提示；测试等待 `toBeEnabled()` |

### 产品修复：交互就绪信号（`apps/web`）

web 制品是 **replacement-render SPA**（非 hydration）：构建期 SSG 标记与 React 树无关，
仅当 React 首次提交后才可交互。此前没有任何机制能让调用方等待该边界，导致交互竞态。

- `apps/web/scripts/ssg-runtime.ts`：handoff 开始时置 `<html data-app-ready="false">`（明确惰性窗口起点）。
- `apps/web/src/main.tsx`：新增 `AppReadySignal`，位于 `<React.Suspense>` 内、
  `DesignSystemProvider` 之后，提交时置 `data-app-ready="true"`。
  放在 Suspense 外会过早（懒加载设计系统仍挂起，点击仍丢失）。
- 回归：`apps/web/scripts/__tests__/build-release-contracts.test.ts` 断言
  handoff 置 false、无 fallback 文档不隐藏 root；`e2e/tests/helpers.ts` 提供
  `gotoReady/waitForAppReady`。

### 产品修复：基因组版本上下文未就绪的禁用态（`apps/web/src/routes/search/genes.tsx`）

`/search/genes` 提交在 assembly 解析前会静默丢弃请求。现改为：`formAssemblyId === undefined`
时提交按钮 `disabled` 并给出可读 title（缺少 assembly 的查询在 v4/v5 命名空间下是歧义的，
不得静默回落）。回归：`genes-assembly-context.test.tsx` 新增 2 例（未就绪禁用 → 就绪可用 → 提交产出参数化 URL）。

## T2：API 回归债 31 例（全部为"测试未随契约更新"）

产品代码零改动（T4 的 CH/release 修复除外）。逐组：

| 测试文件 | 例数 | 根因 | 归属 | 处置 |
| --- | --- | --- | --- | --- |
| `test_exppattern.py` | 10 | 服务新增 accession→`gene_pk` 解析（第 3 次 `execute`），测试桩只备了 2 次 → `StopAsyncIteration` | 测试过期 | `_setup_data` 补 accession 解析结果；`_make_expr` 用解析后的 `gene_pk`；**加** 歧义 assembly 拒绝 + unknown accession 回归 |
| `test_seqfetch.py` | 6 | `Gene(id=...)` 关键字已改为 `gene_pk` + `accession` | 测试过期 | `_make_gene` 改用 `gene_pk`/`accession` |
| `test_homolog.py` | 6 | 端点先解析 accession 再查 `gene_pk`；响应经 `h.gene.accession` | 测试过期 | 新增 `_gene_then` 序列化桩；`mock_homolog.gene.accession`；**加** unknown→404 + 歧义→422 回归 |
| `test_expression.py` | 5 | 同上（expression 端点） | 测试过期 | 同上；`mock_expression_data.gene.accession` |
| `test_module_import_service.py` | 1 | `data_sets.release_id` 有 FK，测试未播种 release | 测试桩缺口 | 测试内 `Release(id=1, …)` + flush |
| `test_popgen_api.py` | 1 | `MissingGeneDb` 桩缺 `scalars()` | 测试过期 | 补齐桩的 `scalars().all()` |
| `test_query_count.py` | 1 | `get_gene` 现用 `result.scalars().all()`；gene 桩用旧 `id` | 测试过期 | 改用 `scalars_list` + `gene_pk/accession` |
| `test_release_bound_queries.py` | 1 | `encode_cursor(accession, gene_pk, …)`、`decode_cursor` 返回二元组 | 测试过期 | 更新调用与断言（锁并列键语义） |

结果：`1496 passed / 0 failed`。每个失败均给出根因与归属，**无删除断言、无 skip/xfail、无削弱匹配**。

## T3：对象存储隔离（R07，真实 MinIO）

对象键命名空间为 `{release_id}/{assembly_id}/genes/{accession}.{json,html}.gz`。
本轮把内联拼接抽为纯函数 `gene_object_key()`（`apps/worker/src/soymutdb_worker/tasks/static_pages.py`），
任务改用该函数，并新增 `apps/worker/tests/test_static_page_object_keys.py`（9 passed：
跨 assembly/跨 release/json-html 不碰撞、release 省略回退、空 accession 与路径分隔符拒绝、扩展名白名单）。

真实存储集成（MinIO RELEASE.2025-09-07，127.0.0.1:9000，bucket `soymutdb-static`）：

```text
KEYS {'v4-r7-json': '7/1/genes/Glyma.01G000100.json.gz',
      'v4-r7-html': '7/1/genes/Glyma.01G000100.html.gz',
      'v5-r7-json': '7/2/genes/Glyma.01G000100.json.gz',
      'v4-r8-json': '8/1/genes/Glyma.01G000100.json.gz'}   # 4 键互不相同
OK bidirectional overwrite isolation       # 同名 accession 跨 v4/v5、跨 release 互不覆盖，回读字节一致
OK unpublished object absent               # 未写入对象不可读
OK anonymous public GET refused (403)      # 匿名公开 GET 被拒
MINIO ISOLATION PASS
```

## T4：CH 依赖端点统一"能力不可用 → 503"

真实 uvicorn + 隔离 PG（迁移至 0035 + 播种 published release + active 指针），
`SOYMUTDB_DEPLOYMENT_MODE=baseline`（无 ClickHouse）。

**实测 0 个 500**：

| 端点 | 修复前 | 修复后 |
| --- | --- | --- |
| `GET /variants` | 503 | 503 |
| `GET /variants/region` | 500 | **503** |
| `GET /stats/density` | **500** | **503** |
| `POST /tools/{diversity,allelefreq,ld}` | **500** | **503** |
| `GET /stats/{dashboard,variant-types,homepage,discovery-trend,releases,mutagens}` | 200 降级 | 200 降级 |
| `GET /releases`、`GET /releases/{id}` | **500** | **200** |

两处真实产品缺陷：

1. **CH 驱动异常逃逸为 500**（`/variants/region`、`/tools/*`）。
   `clickhouse_connect` 的 `OperationalError` 是 `ClickHouseError` 子类，但仅
   `variant_service._ch_query` 做了包装，`ClickHouseService` 与 popgen 调用链未包装。
   修复：在 `ClickHouseService` 增加 `_capability_guarded` 装饰器，9 个公开查询方法统一
   把驱动/传输失败翻译为 `503 service_unavailable`（消息只含能力名，无 host/port/栈）。
   回归：`tests/test_clickhouse_capability_503.py`（4 passed）。
2. **`/stats/density` 降级路径违反自身响应模型**（`chromosome_length` 契约 `>= 1`，
   降级时构造 `0`）。修复：density 完全依赖 CH 投影，不可用时按能力不可用处理（503）；
   正常路径由 bins 推导 `chromosome_length`。回归：`tests/test_stats_contract.py` 新增 3 例。
3. **顺带发现并修复 `/releases` 500**：`app/schemas/content.py` 自行声明了一套与数据库
   enum 不一致的 `ReleaseStatus`（`draft/staging/active/archived`），而模型/DB 为
   `draft/validated/ready/published/rolled_back`；任何已发布 release 序列化即 500。
   修复：schema 改从 `app.models.content` 再导出（单一词汇表），重新导出 OpenAPI 与
   TS 生成类型；回归：`tests/test_release_status_contract.py`（7 passed）。

## 质量门禁（本轮实测）

```text
bash scripts/deploy/preflight.sh --environment development         # PREFLIGHT PASS
bash scripts/deploy/smoke.sh --environment development             # SMOKE PASS（迁移 0001→0035 + live/ready + 搜索链）
SOYMUTDB_SMOKE_PYTHON=<api venv python> bash scripts/acceptance.sh --profile contracts
                                                                   # ACCEPTANCE PASS
python3 scripts/check_site_artifact_isolation.py \
  --external-root apps/web/dist/external --internal-root apps/web/dist/internal \
  --sentinel "Internal Research Workspace for SoyMutDB"            # OK, exit 0
```

- API：1496 passed / 0 failed（`pytest apps/api/tests -q --rootdir=.`）
- Worker：308 passed / 1 skipped（`SOYMUTDB_RUN_POSTGRES_INTEGRATION=1`）
- Web：172 passed（36 文件）+ `tsc --noEmit` OK + eslint 0 error
- Admin：119 passed / lint 0 error / `tsc --noEmit` OK
- E2E：27 passed / 0 failed / 2 skipped

未纳入门禁的环境绑定套件（`scripts/smoke.sh` 明确标注 non-gating）：
`test_worker_image_boundary.py`、`test_contract_visibility.py` **均 3/3、2/2 通过**；
`test_cloudflare_tunnel_contract.py` 2 例失败为**既有** compose/测试漂移（`api` 服务块
正则命中截断片段），本轮未触及且不在交付范围。

## 环境就绪判定（本轮）

- **DEV_READY：授予（限隔离开发环境）**。依据：迁移全链 + 原生冒烟 SMOKE PASS；
  API/Worker/Web/Admin 全绿；公开站 E2E 27 passed；双站制品构建 + 零泄漏扫描 OK；
  真实 MinIO 对象命名空间隔离验证 PASS；CH 能力不可用统一 503（0 个 500）。
  仅限本机（制品烧入本机 origin，不得跨环境复用）。
- **STAGING_READY：未授予**。缺真实 CH 投影、真实 release 数据、代理/边缘与容器化冒烟。
- **PRODUCTION_READY：未授予**。生产部署/迁移/真实数据发布未获授权。

## 遗留项（需业务或环境输入）

| 项 | 需要什么 |
| --- | --- |
| 2 例 live-backend E2E（BLAST 完成后交叉链接、genes JBrowse 深链） | 可达后端（含 CH 投影 + BLAST 数据库） |
| extended 模式端到端（CH + MinIO + Redis） | 真实服务集群；生产发布另行授权 |
| 生产 bucket 策略与签名 URL | 运维决定（对象默认私有已由 MinIO 匿名 GET 403 验证） |
| `public_id` 最终格式/签发语义、内部角色与审计保留期、v4↔v5 映射展示规则 | 产品负责人（不得自行拍板） |

## 下一条可复现命令

```bash
# cwd: 仓库根；fixture 库每次运行前重建（避免 roles 唯一约束残留）
PG_BIN=/usr/lib/postgresql/15/bin
$PG_BIN/dropdb -p 55432 -h 127.0.0.1 -U soymutdb --if-exists soymutdb_testfixtures
$PG_BIN/createdb -p 55432 -h 127.0.0.1 -U soymutdb soymutdb_testfixtures
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_testfixtures' \
  apps/api/.venv/bin/python -m pytest apps/api/tests -q --rootdir=.     # 1496 passed
```

## 回滚方法

- 本轮无数据库迁移变更（沿用到 0035 的既有迁移链）。
- API schema 变更（`ReleaseStatus` 再导出）可整体回滚本次 PR 的文件 diff；回滚后
  需 `pnpm --filter @soymutdb/api-client generate:api-client` 重新导出 OpenAPI/TS 类型。
- web 就绪信号为增量：回滚 `src/main.tsx` + `scripts/ssg-runtime.ts` 即恢复原行为，
  但会重新引入交互竞态（E2E 4 例失败）。
- 对象键函数回滚会恢复内联拼接，命名空间语义不变（函数与内联等价）。
- 适用范围：仅本 PR 触及的文件；不影响已部署制品与生产环境。
