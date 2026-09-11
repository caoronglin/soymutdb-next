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
