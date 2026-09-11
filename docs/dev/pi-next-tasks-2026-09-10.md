# PI 接续任务包：站点核心验收与部署流程（第二轮）

> 用法：把本文件作为任务输入交给 PI Agent：
>
> ```bash
> pi @docs/dev/pi-next-tasks-2026-09-10.md
> ```
>
> 本文件是自包含任务说明，不依赖上一轮会话上下文。历史状态仅作线索，**不作为当前完成证据**。

## 0. 起点状态（已提交、已推送到两个远端）

| 项 | 值 |
| --- | --- |
| 基线提交 | `d8d73fa57`（chore(baseline): consolidate working tree as main-repository baseline） |
| 分支 | `main` |
| 远端 | `cnb` = https://cnb.cool/crl-code/mutlidb ；`origin` = https://github.com/caoronglin/soymutdb-next.git |
| 一致性 | local == cnb/main == origin/main == `d8d73fa57` |
| 工作树 | 干净 |
| 规模 | 427 文件 / +32625 −4037（含既有未提交工作快照 + 上一轮修复） |

开工前必须自行复核：`git rev-parse HEAD`、`git status --short`、`git remote -v`。若 HEAD 不是 `d8d73fa57` 或存在未提交修改，先记录差异再继续，**不得清理用户工作树**。

## 1. 必读文档（按顺序）

1. 根 `AGENTS.md` —— 仓库结构与质量门禁。
2. `docs/dev/database-core-contract.md` —— **规范**（双 ID、v4/v5、内外站、搜索缓存上下文、测试矩阵 ID-01～ID-05 / ASM-01～ASM-05 / CTX-01～CTX-03 / UI-01～UI-02 / E2E-01～E2E-02）。
3. `docs/dev/pi-website-deployment-handoff.md` —— 部署工作包 D0–D6 与硬约束 H01–H16。
4. `docs/dev/deployment-status.md` —— 上一轮 D0–D5 现状核对、缺口表、运行证据与遗留项。
5. `docs/dev/mamba-validation-environment.md` —— **无 Docker 环境的隔离 PostgreSQL 验证方案**（本任务默认用它）。
6. `docs/dev/pi-overall-2026-09-08/execution-status.md` —— R01–R07 / V01–V03 的既有证据（历史，需重验）。

## 2. 环境约束与环境事实（重要）

- **默认无 Docker**：`docker info` 常不可用。不要把容器化验收当作唯一路径，也不要因为没有 Docker 就降低验收标准。
- **隔离 PostgreSQL（已可用）**：mamba PostgreSQL 16，端口 `55432`，trust 认证，数据目录 `.validation/postgres16`，二进制 `.mamba-root/envs/postgres16/bin`。一次性库：`soymutdb_validation`（迁移/冒烟）、`soymutdb_testfixtures`（pytest fixture，每次运行前 drop/create）。**禁止连接生产库**。
- **Python**：`apps/api/.venv/bin/python`（3.14.x）运行 API 测试与 alembic；worker 用 `apps/worker/.venv/bin/python`（需 `pytest`、`alembic`、`asyncpg`、`pydantic-settings`，以及本地 editable 的 `packages/jobs-py`）。
- **Node/pnpm**：Node 24.x（`.nvmrc`）、pnpm 11.21.0。
- **已知环境坑（务必遵守）**：
  - 大量并行构建会触发 esbuild 的 Go 运行时 `newosproc` 崩溃 → 构建时设 `GOMAXPROCS=2`。
  - `pnpm --filter <pkg> <script>` 会因工作区原因丢失 `CI` 之外的 env 传递顺序；需要时直接在包目录内用 `node_modules/.bin/<tool>` 运行。
  - CI 中 `CI=true` 会令 `isProduction()` 为真并要求 deployment origin（见 §4 构建命令）。
  - **不要用 `pkill -f "uvicorn app.main:app"`**：该模式会匹配到执行命令自身的 shell 并自杀；改用 `pgrep` 过滤后精确 kill，或直接在单条命令内完成启动与验证。
  - 后台进程可能随命令结束被回收：需要常驻服务时把「启动 + 验证」放在同一条命令里，或用 `setsid`。
  - 从仓库根运行 API 全套测试（`tools/` 包需要仓库根在 sys.path）：`apps/api/.venv/bin/python -m pytest apps/api/tests -q --rootdir=.`。

### 隔离 PG 启动 / 冒烟（复制可用）

```bash
cd <repo-root>
PG_BIN=$PWD/.mamba-root/envs/postgres16/bin
$PG_BIN/pg_ctl -D $PWD/.validation/postgres16 -l /tmp/pg-run.log -o "-p 55432 -h 127.0.0.1" start
$PG_BIN/pg_isready -p 55432 -h 127.0.0.1

# 一次性验证库
$PG_BIN/dropdb  -p 55432 -h 127.0.0.1 -U soymutdb --if-exists soymutdb_validation
$PG_BIN/createdb -p 55432 -h 127.0.0.1 -U soymutdb soymutdb_validation

# 部署预检 + 原生冒烟（迁移 → 真实 uvicorn → 健康 → 真实搜索链）
bash scripts/deploy/preflight.sh --environment development
bash scripts/deploy/smoke.sh --environment development      # 期望末行 SMOKE PASS
```

## 3. 上一轮已验证（复用以避免重复劳动，但需自行复跑确认）

| 能力 | 证据位置 | 复跑命令 |
| --- | --- | --- |
| 迁移 0035（补齐 releases 缺失列） | `apps/api/migrations/versions/0035_release_assembly_id.py` | `cd apps/api && .venv/bin/python -m pytest tests/test_migrations.py -q` |
| public_id 签发 + 发布缺号守卫 | `apps/api/app/services/public_id_service.py`、`release_service.publish_release` | `pytest tests/test_public_id_service.py -q` |
| worker assembly+accession 解析 | `apps/worker/src/soymutdb_worker/tasks/gene_resolution.py` | `SOYMUTDB_RUN_POSTGRES_INTEGRATION=1 SOYMUTDB_TEST_DATABASE_URL=... pytest tests/test_gene_resolution.py -q` |
| 内部响应 `private, no-store` | `apps/api/app/core/exceptions.py`、`app/api/v1/search.py` | `pytest tests/test_search_internal_http.py -q` |
| CH 不可达 → 503（非 500） | `apps/api/app/services/variant_service.py::_ch_query` | 起 uvicorn 后 `curl -w '%{http_code}' /api/v1/variants` |
| 双站构建 + 泄漏扫描 | `scripts/check_site_artifact_isolation.py` | 见 §4 |
| 原生部署冒烟 | `scripts/deploy/{preflight,smoke}.sh` | 见 §2 |

## 4. 双站构建与泄漏扫描（正确命令，勿再踩坑）

**关键**：E2E 静态服务器把 dist 挂在 `/soymutdb-next` 前缀下，并同源提供 mock API。构建必须绑定 base 与同源 mock origin，否则 SPA 资源 404（曾导致 20/29 E2E 失败）。

```bash
cd <repo-root>

# A) 双站制品（Gate 4 扫描对象）
GOMAXPROCS=2 VITE_DEPLOYMENT_MODE=demo \
  VITE_BASE_URL=/soymutdb-next/ \
  VITE_API_BASE_URL=http://localhost:4173/soymutdb-next/api/v1 \
  VITE_JBROWSE_BASE_URL=http://localhost:4173/soymutdb-next/jbrowse/ \
  pnpm --filter @soymutdb/web build:sites          # → dist/external + dist/internal

# B) 泄漏扫描（哨兵必须真实存在于 internal 且不得出现在 external）
python3 scripts/check_site_artifact_isolation.py \
  --external-root apps/web/dist/external \
  --internal-root apps/web/dist/internal \
  --sentinel "Internal Research Workspace for SoyMutDB"
# 期望：OK, exit 0

# C) 单站制品（E2E 用，必须落在 apps/web/dist）
GOMAXPROCS=2 VITE_DEPLOYMENT_MODE=demo \
  VITE_BASE_URL=/soymutdb-next/ \
  VITE_API_BASE_URL=http://localhost:4173/soymutdb-next/api/v1 \
  VITE_JBROWSE_BASE_URL=http://localhost:4173/soymutdb-next/jbrowse/ \
  pnpm --filter @soymutdb/web build

# D) 公开站 E2E（无 Docker 可运行）
cd e2e && npx playwright test -c playwright-public.config.ts
# 上一轮结果：23 passed / 4 failed / 2 skipped
```

## 5. 本轮任务（按优先级）

只改必要文件，保持现有技术栈与目录结构；每完成一项立即在本文件对应位置或 `docs/dev/deployment-status.md` 追加证据（命令、cwd、退出码、pass/fail/skip/xfail）。

### T1（P0）修复公开站 E2E 剩余 4 个失败

| 用例 | 现象 |
| --- | --- |
| `tests/blast.spec.ts:14` `/blast renders the full form` | 表单未渲染（1.3s 失败） |
| `tests/blast.spec.ts:28` `empty FASTA is rejected client-side` | 45s 超时 |
| `tests/public-login.spec.ts:77` `POSTs JSON and keeps a generic, healthy 401` | 45s 超时 |
| `tests/search.spec.ts:37` `submit opens a parameterized result view in a new tab` | `window.open` 未被调用（`__opened` 为 null） |

要求：
- 先用 §4 的正确构建命令复现，再定位。**不得**通过删除断言、放宽匹配或 skip 通过。
- `search.spec.ts:37` 的根因很可能是页面提交依赖 `getAssemblies()` 数据（`formAssemblyId` 为空时直接 `return`），而离线 mock `/genes/assemblies` 未被命中或未提供内容 —— 请核实请求实际落点与 mock 路由前缀是否一致；若属产品缺陷（例如无 assembly 时也应给出可理解的禁用/提示态），修产品代码并补回归。
- `blast` 与 `public-login` 同样先判断「离线 mock 缺口」还是「真实回归」，分别记录。
- 完成后把本轮正确构建命令写入 `e2e/README.md`（避免他人重复踩坑）。

### T2（P0）既有未提交工作的回归债清理

在 **隔离 PG** 下运行并逐个定位（这些失败在 `d8d73fa57` 之前即存在，需判断「真缺陷」还是「测试未随契约更新」）：

```bash
cd <repo-root>
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_testfixtures' \
  apps/api/.venv/bin/python -m pytest apps/api/tests -q --rootdir=.
# 上一轮：1445 passed / 31 failed，集中在
#   test_exppattern.py(10) test_seqfetch.py(6) test_homolog.py(6) test_expression.py(5)
#   test_release_bound_queries.py test_query_count.py test_popgen_api.py test_module_import_service.py
```

```bash
cd apps/worker && .venv/bin/python -m pytest tests -q     # 上一轮：301 passed / 4 skipped
cd apps/admin  && pnpm lint && pnpm test                  # 上一轮：lint 30 文件报错 / test 22 failed
```

要求：每个失败给出「根因 → 归属（产品缺陷 / 测试过期 / 环境缺失）→ 处置（修代码并补回归 / 更新断言并说明契约冲突 / 记录 BLOCKED）」。**禁止**为了让门禁变绿而削弱断言或跳过。

### T3（P1）对象存储隔离（R07，需真实对象存储）

验证 worker 静态页对象键命名空间：`{release_id}/{assembly_id}/genes/{accession}`（`apps/worker/src/soymutdb_worker/tasks/static_pages.py`）。

- 若环境有 MinIO/S3 兼容存储：写两个 release/assembly 下的同名 accession，断言互不覆盖、读取内容正确、未发布对象不可经公开 URL 获取。
- 若确无对象存储：保持 `IMPLEMENTED_UNVERIFIED`，写明精确复现步骤与所需环境，**不得**用内存 mock 冒充集成验收。

### T4（P1）真实 release 制品与 deployment_mode

- `apps/api/app/api/v1/variants` 等 CH 依赖端点在 `baseline` 模式下已返回 503；请核对 `/variants/region`、导出、统计等其他 CH 消费路径是否有同类 500，统一为「能力不可用 → 503 + 明确状态」。
- 生产 release 模式制品需要可达的 release API 与 CH 投影；若环境不具备，记录 BLOCKED 并给出所需服务清单。

### T5（P2）文档与门禁固化

- 更新 `docs/dev/deployment-status.md`：各工作包状态（NOT_STARTED / IN_PROGRESS / IMPLEMENTED_UNVERIFIED / BLOCKED_ENVIRONMENT / FAILED / VERIFIED）、运行证据、遗留项。
- 明确区分：**实现完成 / 测试通过 / 环境就绪（DEV_READY / STAGING_READY / PRODUCTION_READY）/ 已部署**。
- 不新增重复的部署脚本体系：复用 `deploy/scripts/upgrade.sh`、`blue-green-*`、`healthcheck.sh`、`scripts/deploy/{preflight,smoke}.sh`。

## 6. 不可违反的约束（与 database-core-contract.md、H01–H16 一致）

1. **双 ID**：外部契约只用 `public_id`；`internal_id` 不得出现在外部响应/URL/制品/日志；匿名用内部键查询不得确认存在性（现存与不存在返回同形响应）。
2. **v4/v5**：独立命名空间；查询/详情/序列/表达/JBrowse/缓存/对象键必须携带 assembly 上下文；未指定且歧义时分组或显式消歧，**不得静默回落默认**。
3. **release 与 assembly 独立**；不得把软件版本写入数据 `release_id`。
4. **external/internal**：显式构建与部署，制品/origin/CORS/Service Worker/缓存分离；内部响应 `private, no-store`；`noindex` 不是鉴权。
5. **缓存与 cursor** 必须包含 site_variant、release、assembly、query、filters、sort、分页；上下文切换不得复用旧结果或旧 cursor。
6. **PostgreSQL 权威**；ClickHouse 是投影，MinIO 存对象，Redis 可丢弃。迁移按扩展/回填/收缩设计，**生产降级不得自动执行**。
7. **测试纪律**：不得删除/skip/xfail 必需用例、削弱断言、吞错、伪造计数。隐私/身份/assembly 关键矩阵的 skip 不算通过。
8. **范围纪律**：不清理用户工作树、不重置 `node_modules`/虚拟环境/数据库、不擅自升级依赖、不 force push。
9. **安全**：不打印 token、密码、完整连接串或未公开科研数据；凭据只经环境变量或一次性 600 权限文件传递并及时删除。
10. **授权边界**：本轮仅限隔离开发/测试环境；生产部署、生产迁移、真实数据发布需**另行明确授权**。

## 7. 交付报告格式

```text
一、完成范围（T1–T5 逐项：状态 / 改了哪些文件 / 行为变化）
二、验证证据（命令 + cwd + 退出码 + pass/fail/skip/xfail 计数 + 证据路径）
三、未完成项（BLOCKED 的具体原因、需要什么环境/授权/业务输入）
四、环境就绪判定（DEV_READY / STAGING_READY / PRODUCTION_READY 分别是否授予，说明依据）
五、下一条可复现命令
六、回滚方法（迁移降级命令、脚本清理方式、适用范围）
```

## 8. 已知业务输入缺口（不得自行拍板）

- `public_id` 最终格式与签发语义：当前工程默认 `SM` + Crockford-Base32（`apps/api/app/core/public_ids.py`），**待产品负责人确认**；密钥碰撞与历史 URL 兼容策略同。
- 哪些内部角色可查看/按 `internal_id` 搜索，审计保留期。
- 无 assembly 查询采用「多版本分组」还是「要求先选版本」。
- v4↔v5 一对多/多对一/无映射的展示规则与证据等级。
- 真实科研数据来源、许可与样本对应关系。
