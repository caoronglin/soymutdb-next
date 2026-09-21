# Phase 0 · 事实基线报告（W0 执行记录）

> **父计划：** `plan.md`（第二轮审计版）+ `docs/superpowers/plans/2026-09-20-phase-0-fact-baseline-plan.md`
> **执行日期：** 2026-09-20 ｜ **状态：** 静态部分完成；DB 相关项 RUNTIME_ONLY
> **证据纪律：** 每条结论标 Evidence(E0–E4) + State(S0–S5)；无 `文件:行号` 不结项；runtime-only 不冒充事实。

---

## ⚠️ 环境阻塞记录（影响执行，必须披露）

| 问题 | 现象 | 影响 | 处置 |
|---|---|---|---|
| **harness cwd 指向错误目录** | cwd=`/home/rlcao/Documents/mutliedb`（多一个字母 `e`）仅含 `docs/`；真项目在 `/home/rlcao/Documents/mutlidb`（无 `e`，inode 4222082） | 相对路径命令落到空目录 | 全部改用**绝对路径** `/home/rlcao/Documents/mutlidb` |
| **GVFS 挂载间歇性掉线** | `git`/`rg`/`ls` 对 `apps/`、`.git` 时可见时不可见；幻影 `.new` 文件 | 读取不稳定 | 重试 + 绝对路径；本报告所有 `文件:行号` 均在可见窗口取得 |
| **write 工具覆盖不落盘** | write 报成功、read 可见，但 bash/git 看到的磁盘文件未变（md5/mtime 不变） | 覆盖类编辑丢失 | 落盘一律用 bash heredoc，并以 `md5sum`/`git status` 复核 |
| **无数据库客户端** | 无 `docker`/`psql`/`pg_isready`/`clickhouse-client` | 无法连库实测 | T0-5/6/9/10 标 RUNTIME_ONLY，脚本/夹具交付待有库环境复跑 |
| **Node 版本不匹配** | 环境 `node v26.8.1`，仓库钉死 `24.19.0`（`check-toolchain-pins.py` 会拒） | JS 质量门禁无法原样跑 | 跑 `pnpm lint/typecheck/test/build` 前须切到 24.19.0 |

> 交付物（plan.md、本报告、Phase 0 子计划）已确认落在**真项目**：`git -C /home/rlcao/Documents/mutlidb status` 可见。

---

## §CONTEXT（T0-1）

| 字段 | 值 | Evidence |
|---|---|---|
| target_sha | `54532ede97790308be454e44d622b4c3d9a022e9` | E1 |
| target_branch | `codex/fix-compose-preview-data-layer` | E1 |
| 与原声明基线 `54532ed` 关系 | **相同**（0 commit 差，基线仍当前有效） | E1 |
| dirty_tree | `M plan.md`、`M pnpm-lock.yaml`（预先存在，非本次）、`?? phase-0-fact-baseline-plan.md` | E1 |
| python | 3.14.6（满足 ≥3.14） | E1 |
| node / pnpm | v26.8.1（**不符钉版 24.19.0**）/ 11.21.0（符合） | E1 |
| postgres / clickhouse | **不可达**（无客户端） | — |

## §CONSTRAINTS（T0-2）

| 文档 | 最新 commit | 日期 |
|---|---|---|
| `AGENTS.md` | `79e5d89` | 2026-09-11 |
| `docs/dev/database-core-contract.md` | `d8d73fa` | 2026-09-11 |
| `docs/dev/pi-agent-hard-constraints.md` | `d8d73fa` | 2026-09-11 |
| `docs/dev/rust-rewrite-and-architecture-evaluation.md` | `77889a4` | 2026-09-11 |
| `docs/design/full-stack-upgrade-2026-08.md` | `cab1154` | 2026-08-13 |

全部存在且早于当前 HEAD；引用以当前分支文本为准。

## §LOCATORS（T0-3，按符号）

| 符号 | 当前位置（真项目） |
|---|---|
| `gin_trgm_ops` | `apps/api/migrations/versions/0024_search_trigram_indexes.py:21`、`0027_expand_search_trigram_indexes.py:29` |
| `escape=`（ILIKE） | `apps/api/app/services/search_service.py`（17 处） |
| `total_count=len` | `search_service.py:550,595` |
| `func.count()` 子查询 | `apps/api/app/services/gene_service.py:126` |
| `UnsupportedImportError` | `apps/worker/.../tasks/ingest.py:448`、`data_adapters.py:125/135/148/158/171` |
| `module_data_rows` | `apps/api/migrations/versions/0015_module_tsv_imports.py`、`apps/worker/src/soymutdb_worker/tables.py:170`、`apps/worker/tests/test_module_tsv_postgres_integration.py` |
| `record_event`/`client.insert` | `apps/api/app/services/analytics_service.py:58/87/123/140` |
| `public_id` | `apps/api/migrations/versions/0032_mutant_line_public_id.py`、`apps/api/app/services/public_id_service.py`、`apps/api/app/services/search_service.py` |

---

## §ISSUE-REGISTER（T0-4，双轨：State + Evidence）

> 初始一律 `S0/E0`；下表为 Phase 0 静态核验后的定级。严重度按当前契约+行为判定，不继承旧计划。

| 原项 | State | Evidence | Locator | 现状描述 | Owner-domain | Reproduction | Next gate |
|---|---|---|---|---|---|---|---|
| **D1** 搜索 trigram 可用性 | **S1** | **E1**（查询/索引代码事实） | `search_service.py` escape×17；`0024:21`/`0027:29` 单列 `gin(col gin_trgm_ops)` | 索引为**单列**，查询用 `ILIKE ... escape="\\"`；是否命中索引**未实测** | search/db | `EXPLAIN (ANALYZE,BUFFERS)` 三类查询 × query-class | Phase 3（RUNTIME_ONLY） |
| **D2** 全局搜索串行往返 | **S1** | **E1** | `search_service.py:291,350`（注释"sequentially"），`db.execute`@715/818/895/951/1003/1008/1075/1124 | 多查询在同一 AsyncSession 顺序执行；RTT 计数未实测 | search | 计数单次搜索 DB round-trip | Phase 4 |
| **D3** `total_count` 语义 | **S1** | **E1** | `search_service.py:550`(`len(hits)`)、`:595`(`len(mutants)+len(genes)`) | 返回**页内计数**，非 null/真总数；契约兼容性未评估 | api-contract | 读 OpenAPI + 前端/generated client 用法 | **Gate A（ADR-API-01）** |
| **D4** `list_genes` COUNT 子查询 | **S1** | **E1** | `gene_service.py:126` | 分页走 `COUNT(*)` 子查询；是否进慢查询未实测（缺表规模） | search/db | 表行数 + `EXPLAIN` + 慢查询日志 | Phase 3（RUNTIME_ONLY） |
| **D5** 导入 fail-closed | **S1** | **E1** | `features.py:51-70`（7 开关默认 False）；`ingest.py:448`、`data_adapters.py:125/135/148/158/171` | 7 类导入 fail-closed。按 §5.3 **判为合法保护机制，非缺陷本身**；真正缺口=缺写入器/幂等协议 | data-path | 触发各 adapter 观察 `UnsupportedImportError` | **Gate A（ADR-DATA-02）→ Phase 2** |
| **D6** `module_data_rows` 只写 | **S1** | **E1** | 表定义 `0015`；写 `worker/tables.py:170`；**apps/api 无 reader** | 门户读取路径（apps/api）无 reader；有唯一约束 `uq_module_data_rows_module_release_row`、按 `(module_key,release_id,row)` → 像 landing/staging | data | `rg module_data_rows` 全仓（已做） | **Gate A（ADR-DATA-01）→ Phase 2** |
| **D7** 埋点单行 INSERT | **S1** | **E1** | `analytics_service.py:87,140` | 逐事件单行 `client.insert`；耐久性等级未定 | analytics | 记 events/s、insert calls/s 基线 | Phase 3 基线 → Phase 4 |
| **D8** 突变体公开身份 | **S1** | **E1（部分）** | `0032_mutant_line_public_id.py`（`public_id` VARCHAR(32) unique nullable）；`search_service.py` 用 `public_id`；`mutants.py` 路由用 `ln` | **命名/链路不一致疑点**：全局搜索按 `public_id`（合规），但详情路由 `/mutants/{ln}` 按 `MutantLine.ln`；`ln` 与 `public_id` 关系未定（详见 §IDENTITY） | identity | 全链路 trace（部分完成） | **Gate A / P0-2（需 T0-7 补全 + ID-01/02 测试）** |

---

## §IDENTITY（T0-7，部分完成，发现需拍板）

**已核验（E1）：**
- `mutant_lines.public_id`：`0032` 增加，`VARCHAR(32)`，**唯一索引**（非约束，允许未发布行 NULL）→ 符合契约"已发布非空唯一"。
- **全局搜索**（`search_service.py` `_search_mutant_lines`）：按 `public_id.is_not(None)` 过滤、`public_id.ilike`/`normalize_public_id` 匹配、按 `public_id` 排序/游标 → **合规使用 public_id**。
- **内部搜索**（`_internal_search_mutants`，:853-948）：按 `MutantLine.id`（内部代理键）+ `name` → 合规（内部授权路径）。
- **详情路由**（`mutants.py` `@router.get("/{ln}")`）：按 `func.upper(MutantLine.ln)==normalize_ln(ln)` 查询；文档称"``ln`` is the canonical external identity"，且"内部 id 与 ln 一律视为 not found（无存在性预言）"（满足 ID-02）。

**未决（P0-2，需 Gate A/负责人）：**
1. `ln` 与 `public_id` 是同一值还是两个不同公开标识？详情路由按 `ln`、搜索返回 `public_id`——**若二者不同，搜索→详情的链接会断**。
2. 契约要求公开身份为 `public_id`；若 `ln` 才是对外 canonical identity，则 `public_id` 的角色需澄清（冗余？内部？）。
3. 需跑 `ID-01`（external 按 public_id 命中、响应无 internal_id）、`ID-02`（external 按 internal_id 不确认存在性）确认边界——**当前无库，标 RUNTIME_ONLY**。

**建议：** Gate A 增补 `ADR-ID-01`：冻结 mutant 公开 canonical identity（`public_id` vs `ln`）及搜索/详情/URL 的统一取值，再动任何代码。

---

## §MODULE-ROWS（T0-8）

- writer：`apps/worker`（module_tsv 导入 → `tables.py:170`）。
- reader：**apps/api（门户读取路径）无 reader**；仅 `apps/worker/tests/test_module_tsv_postgres_integration.py` 在测试中断言其结构/内容。
- 结构线索：唯一约束 `uq_module_data_rows_module_release_row`、索引按 `module_key`/`release_id` → 倾向 **raw landing / normalized staging**，非 canonical。
- **待 Gate A（ADR-DATA-01）定角色**：若 staging→需 retention/consumer/promotion/cleanup；若 extension→需 schema/version/reader 契约；若无长期用途→删 writer+表+migration。

---

## §PG / §CH（T0-5 / T0-6）——RUNTIME_ONLY

无 `docker`/`psql`/`clickhouse-client`，**无法连库**。仅静态记录：

- **PG trigram 索引（静态 DDL）**：`0024:21`、`0027:29` 均为 `USING gin ({column} gin_trgm_ops)` **单列**索引。是否被 `ILIKE+escape` 查询利用 = **RUNTIME_ONLY**，须 Phase 3 跑 `EXPLAIN`。
- **CH `variant_facts` 引擎（静态）**：见 `infra/clickhouse/upgrade_variant_facts_schema.sql`、`init.sql`。引擎/topology/partition/order key = **RUNTIME_ONLY**，须 `SHOW CREATE TABLE variant_facts` 确认后选幂等方案。

**待交付脚本（有库环境复跑）：** `scripts/perf/search-query-class-fixture.sql`、`scripts/perf/baseline-*.sh`（见子计划 T0-9/T0-10，尚未创建）。

---

## §GATE-A 输入（T0-13，供拍板）

| ADR | 待决问题 | 证据来源 |
|---|---|---|
| **ADR-ID-01**（新增） | mutant 公开 canonical identity：`public_id` vs `ln`；搜索/详情/URL 统一取值 | §IDENTITY |
| **ADR-DATA-01** | `module_data_rows` 角色 + schema 归属 + 保留期 | §MODULE-ROWS |
| **ADR-DATA-02** | 导入可见性 + 幂等协议（manifest/fingerprint/publish） | D5/§CH |
| **ADR-API-01** | `total_count` 兼容语义（真总数/null/page_count）+ 是否 breaking | D3 |
| **ADR-OPS-01** | 支持的部署架构（amd64/arm64；单节点/集群） | §CONTEXT + §CH |

---

## 阶段退出自评（对照子计划 §3 DoD）

- [x] §CONTEXT / §CONSTRAINTS / §LOCATORS（T0-1/2/3）
- [x] §ISSUE-REGISTER 每条六字段（T0-4）
- [~] §PG / §CH：静态记录，实测 RUNTIME_ONLY（T0-5/6，缺库）
- [~] §IDENTITY：部分完成，发现 ln/public_id 疑点待 Gate A（T0-7）
- [x] §MODULE-ROWS（T0-8）
- [ ] §BASELINES：RUNTIME_ONLY，脚本未建（T0-9）
- [ ] §QUERY-CLASS 夹具：RUNTIME_ONLY，未建（T0-10）
- [ ] 导入 retry/crash 夹具：未建（T0-11）
- [ ] 泄漏套件扩展：未建（T0-12）
- [x] §GATE-A 输入（T0-13 材料）

**结论：** 静态事实发现完成（D1–D8 全部 S1/E1，D8 附 P0-2 疑点）。DB 实测、夹具、基线脚本因**环境阻塞（无库客户端 + cwd/挂载不稳）**未执行，已逐项标 RUNTIME_ONLY/未建，**未冒充完成**。**建议先恢复环境（切 node 24.19.0、起 PG/CH、修正 cwd）再继续 T0-5/6/9/10/11/12。**

---

## §LIVE-EVIDENCE（mamba PostgreSQL 环境，2026-09-20 追加）

> 执行者按用户要求用 mamba 建成本工作区 PostgreSQL 验证环境，并完成可连库的 T0-5 与身份/搜索测试。

### 环境澄清（修正上文"挂载抖动"误判）

**不是挂载故障**，是两个名字只差一个字母 `e` 的目录：

| 路径 | inode | 内容 |
|---|---|---|
| `/home/rlcao/Documents/mutliedb`（**带 e**，harness `$PWD` 指向此处） | 3147541 | 仅 `docs/`（空壳） |
| `/home/rlcao/Documents/mutlidb`（**无 e**，真项目） | 4222082 | 完整项目，git HEAD `54532ed` |

**数据未丢失、挂载正常**。先前"时好时坏"是命令落到了不同目录。**所有交付物已确认在真项目（无 e）**。后续命令一律用通配符锁定带 `.git` 的目录：`for p in /home/rlcao/Documents/mutli*/; do [ -d "${p}.git" ] && R="${p%/}"; done`。

### 已创建的组件（均 gitignore，不会误提交）

- **PostgreSQL 16.15**（conda-forge）：`.mamba-root/envs/postgres16/bin`；数据 `.validation/postgres16`；端口 `55432`，用户 `soymutdb`，`auth=trust`。
- **API 测试 venv**：`apps/api/.venv`（`uv sync --extra dev`，Python 3.14.6，asyncpg 0.31.0 / alembic 1.19.1 / pytest 9.1.1）。
- `.gitignore` 已覆盖 `.mamba-root/`、`.validation/`、`apps/api/.venv`。

### T0-5 实测（升级为 E3）

| 项 | 实测值 |
|---|---|
| PG 版本 | `PostgreSQL 16.15 on x86_64-conda-linux-gnu` |
| 扩展 | `pg_trgm 1.6`、`pg_stat_statements 1.10`（均已装） |
| alembic head | `0036`（迁移链干净应用到 head） |
| trigram 索引 | **9 个，全单列** `gin(col gin_trgm_ops)` |

**D1 细化（E3）：** 搜索对 `genes.accession`、`mutant_lines.public_id` 也做 `ILIKE`，但**这两列无 trigram 索引**：

```
genes:         description, name                         ← 缺 accession
mutant_lines:  cultivar, description, mutagen, name      ← 缺 public_id
publications:  abstract, authors, title
```

→ 标识符/公开 ID 检索缺少索引支撑（比原"escape 抵消索引"更具体）。**下一步**：用 query-class 夹具 + 种子数据跑 `EXPLAIN`（T0-10），确认 accession/public_id 查询的 planner 选择。

### 身份/搜索契约测试（升级为 E2）

```
SOYMUTDB_TEST_DATABASE_URL=.../soymutdb_testfixtures pytest \
  tests/test_search_database_integration.py tests/test_mutants.py \
  tests/test_public_id_service.py tests/test_search_contract.py -q
→ 34 passed, 1 warning in 4.71s
```

- `test_public_id_service`（5）、`test_mutants`（9）、`test_search_contract`（11）、`test_search_database_integration`（9）全绿。
- **D8 修正：** 公开身份 `public_id` 有迁移(0032)+服务(public_id_service)+测试且全绿；**搜索层确认用 `public_id`**。§IDENTITY 中"详情路由 `/mutants/{ln}` 用 `ln`"的疑点仍在（未由这些测试覆盖），维持 **P0-2 待 Gate A（ADR-ID-01）**。

### 仍受阻/待办

| 任务 | 状态 | 原因 / 下一步 |
|---|---|---|
| T0-6 ClickHouse 引擎 | RUNTIME_ONLY | mamba 验证环境**不含 CH**（见文档 Scope）；需单独起 CH 或装 clickhouse 后 `SHOW CREATE TABLE variant_facts` |
| T0-9 分域基线 | 部分 RUNTIME_ONLY | 迁移后表**无种子数据**，空表 `EXPLAIN` 不具代表性；需先跑 `scripts/seed_release_data.py` 或有库种子 |
| T0-10 query-class 夹具 | 未建 | 依赖 T0-9 种子数据；PG 已就绪，可建脚本后复跑 |
| T0-11 导入 retry/crash 夹具 | 未建 | 纯测试骨架，可建（不依赖 CH 的部分） |
| T0-12 泄漏套件扩展 | 未建 | 需 web 构建产物（node 需切 24.19.0） |

**复现命令（PG 生命周期需与使用命令同一 shell，后台进程会被回收）：**

```bash
R=$(for p in /home/rlcao/Documents/mutli*/; do [ -d "${p}.git" ] && echo "${p%/}"; done)
PG_BIN="$R/.mamba-root/envs/postgres16/bin"
"$PG_BIN/postgres" -D "$R/.validation/postgres16" -p 55432 \
  -c listen_addresses=127.0.0.1 -c shared_preload_libraries=pg_stat_statements &
PG_PID=$!; trap "kill $PG_PID 2>/dev/null" EXIT; sleep 2
# ... 使用 ...
```

---

## ⚠️ CORRECTION（2026-09-20，结论反转 —— 废止先前 D8/§IDENTITY/ADR-ID-01）

**先前记录有误。** 本文 §IDENTITY 与 §ISSUE-REGISTER 的 D8、§GATE-A 的 `ADR-ID-01` 曾断言：
"突变体详情路由 `/mutants/{ln}` 按 `MutantLine.ln` 查询，与 `public_id` 关系未定，疑违反身份契约（P0-2）"。
**该结论为误报，现予废止。**

**误报根因：** 那次 grep 用硬编码路径 `/home/rlcao/Documents/mutliedb`（**带 e 的空壳/过期副本**）执行，
读到的是**重构前的旧代码**（彼时用 `ln`）。在文件系统目录混淆窗口（见 §LIVE-EVIDENCE 环境澄清）读到了过期内容。

**决定性反证（对真项目 `mutlidb`，glob 锁定带 `.git` 的目录，多种手段交叉验证）：**

| 判据 | 结果 |
|---|---|
| `MutantLine` 模型列（venv 内省） | `id, public_id, name, ...`，**无 `ln`**；`hasattr(MutantLine,'ln')=False` |
| 当前 `mutants.py` 逐模式计数 | `MutantLine.ln`=0、`core.lns`=0、`normalize_ln`=0、`{ln}`=0；`MutantLine.public_id`=4、`normalize_public_id`=3 |
| 当前路由 | `@router.get("")`、`@router.get("/{public_id}")`、`@router.get("/{public_id}/phenotypes")` |
| 导入 | `from ...core.public_ids import normalize_public_id`（**非** core.lns） |
| app 注册 | `api_router.include_router(mutants.router)`，运行期路由 `/mutants/{public_id}` |
| 全仓残留 | `core.lns`/`normalize_ln`/`MutantLine.ln`/`lns.py` **均无** |
| 测试 | `test_mutants`(9)+`test_public_id_service`(5)+`test_search_contract`(11)+`test_search_database_integration`(9)=**34 passed** |

**修正后判定：**
- **D8 → 合规（COMPLIANT）**，State 记为 **S4 / E2**（代码 + 迁移 0032 + 路由 `/{public_id}` + 搜索用 `public_id` + 34 测试绿 + 全仓无 `ln` 残留）。**不再是 P0-2，不进 Phase 1 修复范围。**
- **§IDENTITY 以此条为准**（上方旧 §IDENTITY 正文作废）。
- **§GATE-A 删除 `ADR-ID-01`**（无需拍板 ln/public_id——已统一为 public_id）。Gate A 剩余：ADR-DATA-01（module_data_rows 角色）、ADR-DATA-02（导入幂等/可见性）、ADR-API-01（total_count 语义）、ADR-OPS-01（部署架构）。

**教训（入 error-ledger）：** 目录名近似 + 文件系统视图不一致时，**任何 grep/read 结论都必须先用通配符锁定带 `.git` 的真项目目录并交叉验证**（内省模型列 / 测导入 / 全仓符号扫描），单点 grep 不足以定论。本次靠三处独立反证才避免把一个假 P0 带进 Phase 1。

---

## §D1-EXPLAIN（搜索 query 实测，E3，2026-09-20 追加）

合成数据（genes 5000 / mutant_lines 5000 / publications 2000，ANALYZE 后），对真实查询形态跑 `EXPLAIN (ANALYZE, BUFFERS)`：

| # | 查询形态 | 相关索引 | planner 选择 | 耗时 |
|---|---|---|---|---|
| G1 | `genes.accession ILIKE '%000123%'` | **无** trigram | Seq Scan | 1.05 ms |
| G2 | `genes.name ILIKE '%gene42%'` | trigram(name) | Seq Scan（表小） | 0.99 ms |
| G3 | `genes.description ILIKE '%kinase%'` | trigram(description) | Seq Scan（选择率 10%） | 1.06 ms |
| **M1** | `upper(mutant_lines.public_id)=upper('MUT000123')` | btree unique(public_id) | **Seq Scan（索引被 upper() 包裹废掉）** | 0.77 ms |
| **M1b** | `mutant_lines.public_id='MUT000123'`（裸等值） | btree unique(public_id) | **Index Scan** | **0.033 ms** |
| M2 | `mutant_lines.public_id ILIKE '%MUT0001%'` | **无** trigram | Seq Scan | 1.26 ms |
| M3 | `mutant_lines.name ILIKE '%line 42%'` | trigram(name) | Seq Scan（表小） | 0.83 ms |

**结论（E3，进入 Phase 4 依据）：**

1. **精确 ID 查找被 `upper()` 包裹废掉索引（最高价值、与数据量无关）：**
   `search_service.py` 精确分支用 `func.upper(MutantLine.public_id) == normalize_public_id(...)`，
   导致本可走 `ix_mutant_lines_public_id` 的等值查询退化为 Seq Scan（M1 0.77ms vs M1b 0.033ms，~23×）。
   **修复候选：** 若 `public_id` 入库即规范化（大写），查询改裸等值；否则建**表达式索引** `gin/btree ON upper(public_id)`。
   genes 精确 accession 同理需核查是否被 `func.upper(...)` 包裹。
2. **子串检索缺索引：** `genes.accession`、`mutant_lines.public_id` 无 trigram 索引（G1/M2 Seq Scan）。
3. **规模效应待验：** name/description 的 trigram 在 5 千行未启用（planner 选 Seq Scan 合理，§6.2）。
   **须在更大数据量（≥ 生产量级）复测**才能确认 trigram 是否启用——标 **RUNTIME_ONLY（需种子数据扩量）**。

**限制声明：** 合成数据 5k 行，仅够确认"索引存在性 + upper() 包裹效应 + planner 选择性逻辑"；
trigram 规模效应、真实 p95 需 Phase 1.5/Phase 3 的生产等价数据基线。未改任何索引/查询。

### §D1-EXPLAIN 规模复核（200k 行，关闭"规模效应待验"）

扩到 genes/mutant_lines 各 200k、ANALYZE 后复测：

| # | 查询 | 索引 | planner @200k | 耗时 |
|---|---|---|---|---|
| G2 | `name ILIKE '%gene42000%'` | trigram(name) | **Bitmap Index Scan** ✓ | 1.74 ms |
| G3 | `description ILIKE '%kinase%'`(10%) | trigram(description) | **Bitmap Index Scan** ✓ | 16.5 ms |
| G1 | `accession ILIKE '%0000123%'` | **无** | **Parallel Seq Scan** | 17.97 ms（0 命中仍全表扫） |
| M2 | `public_id ILIKE '%MUT00001%'` | **无** | **Seq Scan** | 32.4 ms |
| M1b | `public_id='MUT000123'` | btree | Index Scan | 0.045 ms |

**定论（E3）：**
1. 既有 trigram（name/description）**在生产量级确实启用**——不是问题，勿动。
2. **真正的 D1 瓶颈 = `genes.accession` 与 `mutant_lines.public_id` 缺 trigram 索引**：子串检索退化为全表/并行扫（18–32ms）。→ Phase 4 补索引（query-class 路由：exact 走 btree、substring 走新 trigram）。
3. **精确 ID 的 `upper()` 包裹废 btree**（M1 vs M1b，与数据量无关）→ Phase 4 改裸等值或建 `upper()` 表达式索引。

至此 D1 从"缺索引 + escape 疑虑"细化为三条可执行、有实测支撑的 Phase 4 项。

---

## §GLOSSARY · "ln" 一词多义澄清（避免再次误报）

Phase 0 的 D8 误报根因是 **"ln" 在本仓有两种完全无关的含义**，且错误目录里有过一份用 `ln` 作突变体身份的旧代码：

| 含义 | 位置 | 现状 |
|---|---|---|
| **基因跨版本链接** `GeneLn`/`GeneAlias`（gene cross-version link） | `app/models/genomic.py`、迁移 `0034 gene_crosswalks` | **当前真实存在**，即契约 DB-CORE-4 的显式 crosswalk；测试 `test_ln_data_is_explicit_and_linked`(H08)、`test_similar_genes_without_ln_stay_unrelated`(ASM-05) 已覆盖且通过 |
| ~~突变体身份 `ln`~~ | 仅存在于**错误目录的旧副本** `mutants.py` | **当前真项目不存在**；突变体公开身份是 `public_id` |

**结论：** 见到 `ln` 先分辨是 `GeneLn`（基因跨版本映射，合法）还是旧突变体身份（已废弃）。本次 D8 更正不受影响。

## §D8 精确化（Review 补充）

经 api-client 契约测试补充取证，D8 合规性从"API 层"扩展到"客户端契约层"：
- `packages/api-client/src/mutant-lines.test.ts`：`getMutantLine("SM7K3ZQ9P2A")` → `GET /mutants/SM7K3ZQQ9P2A`；"accepts canonical public_id formats" → **客户端用 `public_id`（如 `SM7K3ZQ9P2A`）调 `/mutants/{public_id}`**。

**残余两项（非阻断，纳入 Phase 1 P1-3 收尾）：**
1. `apps/web/src/routeTree.gen.ts` 仍引用 `$ln`（实际路由文件是 `$id.tsx`）——**过期生成产物**，重新生成路由树即可；传值本身是 public_id，非缺陷。
2. **UI-01**（突变体列表/详情只显示 public_id、不显示内部 id）尚缺显式断言——P1-3 应补一条前端断言。

**因此 D8 定级：合规（contract/client/route 三层已证），残余为过期生成文件 + UI-01 断言，均非 P0。**

---

## §MATRIX-COVERAGE（Phase 1 / P1-3，2026-09-20）

对 mamba PostgreSQL 实跑身份/上下文/assembly/搜索相关 API 测试：
**8 文件 / 69 用例全绿**（test_search_database_integration 9、test_search_contract 11、
test_search_internal_http 3、test_mutants 9、test_public_id_service 5、test_genes 10、
test_search 11、test_search_keyset 11），零 skip/xfail。

| 矩阵 ID | 层级 | 覆盖测试（证据） | 状态 |
|---|---|---|---|
| ID-01 external 按 public_id 命中、无 internal_id | API+PG | `test_search_database_integration.py:312`、`test_mutants.py:4` | ✅ |
| ID-02 external 按 internal_id 不确认存在性 | API+PG | `test_mutants.py:108`、`test_search_database_integration.py:312` | ✅ |
| ID-03 internal 未授权 401/403 无数据 | API | `test_search_internal_http.py`（anonymous→401 @93；under-privileged→403 @110，均 private,no-store） | ✅ |
| ID-04 internal 授权按任一 ID 定位同一实体 | API+PG | `test_search_database_integration.py:396` | ✅ |
| ID-05 external 制品零内部泄漏 | artifact | `scripts/check_site_artifact_isolation.py` + `test_site_artifact_isolation.py` | ✅（脚本层；制品扫描需 node24 构建，见下） |
| ASM-01/02 v4/v5 各自精确 | API+PG | `test_search_database_integration.py:183/193` | ✅ |
| ASM-03 无版本歧义不静默默认 | API+PG | `test_search_database_integration.py:203`、`:164` | ✅ |
| ASM-04 v4 exact + crosswalk 标 v5 关联 | API+PG | `test_search_database_integration.py:268`（crosswalk explicit+linked） | ✅ |
| ASM-05 相似但未映射不生成跨版本 | API+PG | `test_search_database_integration.py:243` | ✅ |
| CTX-01 缓存不跨 site variant | cache | `test_search_internal_http.py`（internal private,no-store）、`test_search_contract.py:188/217` | ✅ |
| CTX-02/03 缓存不跨 release/assembly | cache | `test_search_contract.py:91`（cache bound to release+assembly） | ✅ |
| UI-01 external 只显示 public_id | Vitest | `mutants-discovery.test.tsx:115`（链接=/mutants/SM7K3ZQ9P2A）、`:116`（哨兵 absent） | ✅ |
| UI-02 internal 授权显示两种 ID | Vitest | 待确认（web internal 视图） | ⚠️ 待核 |
| **E2E-01** external 匿名 突变体 search→detail→JBrowse | Playwright | `search.spec.ts` 仅覆盖**基因**检索表单，**无突变体 search→detail** | ❌ **缺口** |
| **E2E-02** internal 登录 按 internal-ID 搜索 | Playwright | 未见对应 spec | ❌ **缺口** |

**缺口登记（阻断项，未冒充通过）：**
1. **E2E-01/02（突变体维度）缺 Playwright 覆盖**：现有 `search.spec.ts` 是基因检索，未覆盖"突变体 search→detail→JBrowse 的 ID/assembly/release 全程一致"与"internal 登录按 internal-ID 搜索"。需补 spec；运行需完整栈 + **node 24.19.0** + 构建产物 → 环境门控。
2. **UI-02** 待确认 internal 视图是否区分并显示两种 ID。
3. **ID-05 制品扫描**脚本已在，但"构建 external/internal 双制品后零泄漏"的完整证据需 node 24.19.0 构建（P1-1 同此门）。

**结论：** API/单元/前端层的身份·上下文·assembly 契约**覆盖完整且 69 测试全绿（E2）**；残余缺口集中在 **E2E 突变体链路**与 **node24 构建门**，已登记为 Phase 1 阻断项（依赖环境：node 24.19.0 + 完整栈）。

---

## §P1-EXECUTION（Phase 1 执行记录，2026-09-20）

### P1-2 · fail-closed 导入能力收口 —— API 侧已正确，补了回归锁定

**实测结论（E1+E2）：API 侧能力收口早已正确实现，不存在"入队后失败"。**
- `admin_imports.py:44-56` `_require_import_type_enabled`：未映射类型→`ValidationError`；开关关闭类型→`ValidationError("X imports are currently disabled")`。
- `admin_imports.py:231` 在**派发 Celery 之前**调用该门（注释明写"gets a clear 422 rather than a worker fail-closed after dispatch"）。
- `import_studio_service.py` 已拒 script/HTML/URL/公式/超大单元格（SEC-3 输入卫生已在）。

**新增回归测试** `apps/api/tests/test_import_capability_closure.py`（对 mamba PG 实跑 **9 passed**）：
7 类关闭类型 → `ValidationError`；`module_tsv` → 通过；未知类型 → `ValidationError`。

**残余（UX，非正确性）：** Admin 有 Features 管理页可开关 `imports.*`，但**导入提交表单未见按开关隐藏/禁用类型**——用户可能选到关闭类型后才得 422。建议前端提交表单按 flag 过滤类型（UX 改进，不影响"无 fail-closed 任务"的正确性结论）。

### Phase 1 当前状态

| 任务 | 状态 |
|---|---|
| P1-3 身份/上下文/assembly 矩阵 | ✅ API/单元/前端层覆盖完整，**69 测试全绿**；缺口=E2E-01/02(突变体)、UI-02，已登记 |
| P1-2 导入能力收口 | ✅ API 侧已正确 + 回归测试 9 绿；残余=Admin 提交表单 UX 隐藏 |
| P1-1 external/internal 泄漏负向套件 | ⏸ 需 node 24.19.0 + web 构建（环境门控） |

**环境门控项（未冒充完成）：** P1-1 制品泄漏扫描、E2E-01/02、ID-05 完整证据 —— 均需 **node 切 24.19.0** + 构建/完整栈。

---

## §P1-1 · 泄漏隔离（node 门已除，完整证据待全栈）

**进展（E2）：**
- 用 mamba 建 **node 24.19.0** 环境（`.mamba-root/envs/node24`）+ corepack pnpm 11.21.0，与仓库钉版一致。
- `build:sites` 的 **vite build + ssg-build 成功**产出 dist/external（index.html + 9 页 + 28 资源）——**node 工具链门已清除**。
- 隔离**检查器单测 6 全绿**（`scripts.test_site_artifact_isolation`：symlink 拒绝、哨兵脱敏、配置 fail-closed、多哨兵确定性）。

**确切阻塞点（非 node，是全栈）：** `generate-samples.ts` 需 fetch 真实 API `GET /api/v1/variants`（"production sample generation requires available API release data"）；占位 origin 下失败，构建在 gen-sw / finalize-csp / gzip / release-manifest 之前中断。故：
- **完整双制品**（external + internal，含 SW/manifest/gzip）需**运行中的 API + 已种子 release 数据**；
- **制品级 ID-05 零泄漏证据**还需数据里带**未发布哨兵**，扫描断言其在 external 零命中。
- 这些超出 mamba PostgreSQL 验证环境范围（该环境按设计不提供 API 运行时/浏览器，见 `docs/dev/mamba-validation-environment.md` Scope）。

**结论：** P1-1 的**工具与 node 门已就绪**；**完整 artifact 级泄漏证据**阻塞于"运行中的 API + 种子数据 + 未发布哨兵"这一全栈环境，登记为环境门控项，**未冒充完成**。
