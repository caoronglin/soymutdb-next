# Phase 0 · 事实发现（强制前置门，第二轮审计版）

> **已归档（2026-10-01）**：已被现行计划取代的历史实施计划。继任：`docs/aegis/plans/` 与 `docs/aegis/INDEX.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

> **父计划：** `plan.md`（第二轮审计版 §3、§19、§21）。
> **性质：** 事实发现 + 夹具 + 基线脚本 + 待决策清单，**不修改业务代码**。
> **前置：** 无。**必须早于：** Gate A、Phase 1–6、Phase R 的一切改动。
> **Wave：** W0
> **退出判据：** §3（每个候选问题有 State + Evidence + locator + reproduction + owner + next gate）
> **本文件自身定级：** 其中每条结论在执行、连库核验前均按 Evidence/State 重新定级，**不得因"已写成文件"就当事实**。

---

## 0. 为什么单独成阶段

两轮审计的核心修正是：**证据强度（Evidence E0–E4）不等于缺陷生命周期（State S0–S5）。**
Phase 0 的目标不是"强行证明所有项达到某等级"，而是把每个候选问题放到
**双轨登记册（issue register）**里，并给出定位、复现方法与下一道门。

**本阶段红线：** 不改 `apps/api`、`apps/worker`、迁移、OpenAPI、nginx、CI workflow。
只允许新增：登记册、只读核验脚本、夹具/测试骨架、基线脚本、ADR 草案。
P0 相关隔离/身份场景**不得 skip/xfail**；runtime-only 项允许停留在 E0/E1，
**但必须已有可执行的 reproduction/benchmark plan**。

---

## 1. 任务清单

### T0-1 · 锁定目标上下文

**Files:** 产出写入 `docs/ops/phase-0-fact-baseline-2026-09-20.md`（§CONTEXT）
**Steps:**
1. 记录：
   ```bash
   git rev-parse HEAD; git branch --show-current; git status --short; git log -1 --oneline
   ```
2. 登记：`target_branch` / `target_sha` / `dirty_tree` / `database_schema_version` /
   `clickhouse_version` / `postgres_version` / `python_version` / `node/pnpm_version` / `deployment topology`。
3. 判定原声明基线 `54532ed` 与当前 HEAD 关系（相同 / 前移 N commit / 分叉）。

**Verify:**
```bash
git rev-parse HEAD; git branch --show-current; git log -1 --oneline
```
**Accept:** §CONTEXT 含上述全部字段；明确 `54532ed` 是否仍可参考。

---

### T0-2 · 重新读取当前约束文档

**Files:** `docs/ops/phase-0-fact-baseline-2026-09-20.md`（§CONSTRAINTS）
**依赖：** T0-1
**Steps:**
1. 按当前目标分支确认五份约束文档，并记录各自最新改动 commit：
   `AGENTS.md`、`docs/dev/database-core-contract.md`、`docs/dev/pi-agent-hard-constraints.md`、
   `docs/dev/rust-rewrite-and-architecture-evaluation.md`、`docs/design/full-stack-upgrade-2026-08.md`。
2. 旧计划引用的约束内容**全部从 E0 重新升级**为 E1（以当前分支文本为准）。

**Verify:**
```bash
git log -1 --oneline -- AGENTS.md docs/dev/database-core-contract.md docs/dev/rust-rewrite-and-architecture-evaluation.md docs/design/full-stack-upgrade-2026-08.md
```
**Accept:** §CONSTRAINTS 列五份文档当前版本 commit；凡与原计划引用不一致处已标注。

---

### T0-3 · 按符号重新定位 D1–D8（不用旧路径）

**Files:** `docs/ops/phase-0-fact-baseline-2026-09-20.md`（§LOCATORS）
**依赖：** T0-1
**Steps:**
1. 用**符号/契约**（非旧路径）重新定位每条候选问题的当前位置：
   ```bash
   git grep -n "resolve_release_context"; git grep -n "module_data_rows"
   git grep -n "UnsupportedImportError";  git grep -n "total_count"
   git grep -n "gin_trgm_ops";            git grep -n "variant_facts"
   git grep -n "record_event";            git grep -n "public_id"; git grep -n "internal_id"
   ```
2. 每个符号记录：当前 `文件:行号`（若有）/ 是否已移动 / 是否已消失。
3. 旧路径仅作 E0 提示；若已移动，用新定位覆盖。

**Verify:**
```bash
git grep -n "gin_trgm_ops"; git grep -n "total_count"; git grep -n "UnsupportedImportError"
```
**Accept:** §LOCATORS 每条符号有当前定位或明确"未找到"；无残留旧路径误用。

---

### T0-4 · 建立问题登记册（State + Evidence）

**Files:** `docs/ops/phase-0-fact-baseline-2026-09-20.md`（§ISSUE-REGISTER）
**依赖：** T0-3
**Steps:**
1. 对 D1–D8 每条建立双轨登记：`State`（S0–S5）+ `Evidence`（E0–E4）+ `current locator` +
   `owner-domain` + `reproduction method` + `next gate`。
2. Phase 0 初始一律 `S0/E0`；核验后按证据升级，**严重度由当前契约 + 当前行为决定，不继承旧计划**。
3. 分类提示（非定论）：D1→P1 性能；D2→P1 性能/架构；D3→P1 API 契约；D4→P1/P2 性能；
   D5→P0 数据可用性**或**合法保护机制（§5.3）；D6→P0/P1 视真实角色；D7→P1 成本/吞吐；
   D8→若违反上游身份契约则 P0。

**Verify:**
```bash
rg -n "State|Evidence|S0|S1|E0|E1" docs/ops/phase-0-fact-baseline-2026-09-20.md
```
**Accept:** 登记册每条六字段齐全；runtime-only 项已附 reproduction/benchmark plan（哪怕未跑）。

---

### T0-5 · PostgreSQL 版本/扩展/索引核查

**Files:** `docs/ops/phase-0-fact-baseline-2026-09-20.md`（§PG）
**依赖：** T0-1；需要 PostgreSQL
**Steps:**
1. 记录版本与扩展：
   ```sql
   SELECT version();
   SELECT extname, extversion FROM pg_extension WHERE extname IN ('pg_trgm','pg_stat_statements');
   SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes WHERE indexdef ILIKE '%trgm%';
   ```
2. 记录现有 trigram 索引定义（单列 or 表达式）与所在表。
3. 无法连库：标 `RUNTIME_ONLY`，仅记录静态迁移中的索引 DDL（`migrations/versions/*`）。
4. **不创建/修改任何索引**——只核查。索引选型留给 Phase 4 按 query class 决定。

**Verify:**
```bash
# 可连库时逐条执行上述 SQL；不可用时：
rg -n "gin_trgm_ops|CREATE INDEX" apps/api/migrations/versions/*.py
```
**Accept:** §PG 含 PG 版本、`pg_trgm`/`pg_stat_statements` 是否安装、trigram 索引清单（或标 RUNTIME_ONLY）；无索引改动。

---

### T0-6 · ClickHouse 版本 + `SHOW CREATE TABLE variant_facts`

**Files:** `docs/ops/phase-0-fact-baseline-2026-09-20.md`（§CH）
**依赖：** T0-1；需要 ClickHouse
**Steps:**
1. 记录：
   ```sql
   SELECT version();
   SHOW CREATE TABLE variant_facts;
   ```
2. 若定位到真实 staging 表名，再 `SHOW CREATE TABLE <actual_staging_table>`——
   **不使用 `<staging>` 占位符直接运行**。
3. 确认：engine / replication / partition key / ORDER BY / materialized views / async insert /
   dedup settings / cluster topology。
4. 无法连库：标 `RUNTIME_ONLY`，仅记录静态 schema（`infra/clickhouse/*`）。

**Verify:**
```bash
rg -n "ENGINE|PARTITION BY|ORDER BY|PRIMARY KEY|ON CLUSTER" infra/clickhouse/*.sql
# 可连库时：clickhouse-client --query "SHOW CREATE TABLE variant_facts"
```
**Accept:** §CH 含 CH 版本、`variant_facts` 引擎/topology（或标 RUNTIME_ONLY）、staging 表真实表名（若有）；为 §9 幂等方案提供引擎事实。

---

### T0-7 · `public_id` / `internal_id` 全链路追踪（P0）

**Files:** `docs/ops/phase-0-fact-baseline-2026-09-20.md`（§IDENTITY）
**依赖：** T0-1
**Steps:**
1. 逐层确认 mutant 公开身份现状，**不依赖"某迁移可能已覆盖"的推测**：
   model / migration / API schema / route parameter / search hit / URL / frontend routing /
   cache key / analytics / logs。
2. 重点字段：`public_id` / `internal_id` / `release_id` / `assembly_id`。
3. 判定 external API 是否仍直接暴露内部自增主键；若是 → 维持 **P0**，引用 `database-core-contract.md` §3。
4. 记录现有相关测试覆盖到哪一层。

**Verify:**
```bash
git grep -n "public_id" -- apps/api/app apps/api/migrations | head -40
git grep -n "internal_id" -- apps/api/app | head -20
cd apps/api && .venv/bin/python -m pytest tests/test_public_id_service.py tests/test_mutants.py -q
```
**Accept:** §IDENTITY 全链路每层现状 + `文件:行号`；P0-2 判定明确；测试覆盖边界与缺口已列。

---

### T0-8 · `module_data_rows` writer/reader/lifecycle 追踪（P0 子项）

**Files:** `docs/ops/phase-0-fact-baseline-2026-09-20.md`（§MODULE-ROWS）
**依赖：** T0-1
**Steps:**
1. 全仓列出 writer 与 reader：
   ```bash
   git grep -n "module_data_rows"
   ```
2. 判定角色（raw landing / staging / audit / extension storage / canonical domain），
   并回答两个关键问题：**谁拥有 schema evolution？数据保留多久？**
3. 给出 ADR-DATA-01 决策所需的证据（不决策，只呈证）。若确为 write-only，维持 P0/P1（视角色）。

**Verify:**
```bash
git grep -n "module_data_rows"
```
**Accept:** §MODULE-ROWS 含 writer 列表、reader 列表（或明确"无 reader"）、门户实际读取表、角色判定 + schema 归属 + 保留期证据。

---

### T0-9 · 采集可执行处的 pre-change 基线（分域）

**Files:** 新增 `scripts/perf/baseline-search.sh`、`scripts/perf/baseline-analytics.sh`、`scripts/perf/baseline-ci.sh`（或扩展现存 `scripts/slow-query-report.sh`）；产出报告 §BASELINES
**依赖：** T0-1、T0-5、T0-6
**Steps:**
1. **分域采集**（每个 domain 第一次改动前必须有 snapshot）：
   - Search：p50/p95/p99、query classes、EXPLAIN、DB RTT、pool wait；
   - Analytics：events/s、insert calls/s、parts/s、merge pressure；
   - CI：median/p90/p95、queue time、job critical path、cache hit。
2. **Import 当前路径若不可执行 → 不存在有效 before baseline**，明确记录
   "baseline starts only after correctness path is enabled"，**不制造假对照**。
3. 不可执行的域标 `RUNTIME_ONLY`，脚本仍入库供 Phase 3 复跑。

**Verify:**
```bash
bash scripts/perf/baseline-search.sh    # 需 PG；不可用须报告 SKIPPED + 原因
bash scripts/perf/baseline-analytics.sh # 需 CH；不可用须报告 SKIPPED + 原因
bash scripts/slow-query-report.sh
```
**Accept:** §BASELINES 每个可执行域有 snapshot；不可执行域明确标注且无假对照；脚本入库。

---

### T0-10 · 搜索 query-class 夹具

**Files:** 新增 `scripts/perf/search-query-class-fixture.sql`（或等价）；产出报告 §QUERY-CLASS
**依赖：** T0-5
**Steps:**
1. 按 §6 Query Class 建夹具：Exact ID / Prefix / Short(1–2) / Substring / Natural text / Fuzzy typo。
2. Benchmark Matrix 至少含：`exact identifier` / `prefix` / `1-char` / `2-char` / `3-char` /
   `middle substring` / `common term` / `rare term` / `literal %` / `literal _` / `mixed case` /
   `multi-word` / `not found`。
3. 记录：query class / pattern / rows / selectivity / plan / estimated vs actual rows / buffers /
   execution time / result count。
4. **验收不用"index=成功/seq=失败"**（§6.2）；短查询产品策略（§6.3）列为待决策，不擅自实现。
5. 无法连库：夹具入库，标 `RUNTIME_ONLY`。

**Verify:**
```bash
bash scripts/perf/search-query-class-fixture.sql   # 需 PG；不可用须报告 SKIPPED + 原因
```
**Accept:** §QUERY-CLASS 夹具覆盖全部 query class + matrix；短查询策略已登记为待决策；无索引改动。

---

### T0-11 · 导入 retry/crash/ambiguous-ACK 夹具（先红）

**Files:** 新增 `apps/worker/tests/test_import_idempotency_fixture.py`（遵循 `test_*.py`）
**依赖：** T0-6
**Steps:**
1. 建夹具骨架，覆盖 §10 的**期望结果表**（每条都有明确期望，不只"全绿"）：
   same file+same release+same assembly+same config / same content+diff filename /
   diff release / diff assembly / parser-config version changed / crash before first batch /
   crash mid-write / crash after write before publish / CH timeout after ambiguous ACK /
   invalid record / checksum mismatch / duplicate batch / row count mismatch。
2. 因导入链路当前或 fail-closed（待 T0-3/§5.3 判定），夹具预期表现为「明确失败/拒绝」而非「静默重复」。
3. 涉身份/assembly/release 边界场景**不得 skip/xfail**；当前无法构造的标 `TODO(phase-2)` 并登记。

**Verify:**
```bash
cd apps/worker && .venv/bin/python -m pytest tests/test_import_idempotency_fixture.py -q
```
**Accept:** 夹具入库并运行；每个 case 有明确期望断言（通过/明确失败，非 skip）；当前 fail-closed 行为已记录为基线。

---

### T0-12 · external/internal 负向泄漏套件（P0）

**Files:** 扩展现存 `scripts/check_site_artifact_isolation.py` / `scripts/test_site_artifact_isolation.py`；产出报告 §LEAK
**依赖：** T0-1
**Steps:**
1. 确认并补齐 §5.2 全部载体：HTTP body / HTTP headers / error responses / redirect Location /
   URL / SSR payload / HTML / JS / JSON / source maps / OpenAPI examples / logs / analytics payload /
   cache key+value / generated artifacts。
2. 用带唯一哨兵值的未发布突变体验证：哨兵与 `internal_id` 在 external 侧零命中。
3. **不得 skip/xfail**；当前未覆盖载体登记为缺口，不冒充通过。
4. 无构建产物：标 `SKIPPED（缺 dist）`，不计通过（`scripts/smoke.sh` 语义）。

**Verify:**
```bash
python3 -m unittest scripts.test_site_artifact_isolation -v
pnpm --filter @soymutdb/web build:sites   # 若需产物
python3 scripts/check_site_artifact_isolation.py \
  --external-root apps/web/dist/external --internal-root apps/web/dist/internal \
  --sentinel "$UNRELEASED_SENTINEL"
```
**Accept:** §LEAK 现有覆盖 + 缺口清单；`internal_id`/哨兵 external 零命中有证据；无 skip/xfail 伪装。

---

### T0-13 · Gate A ADR 决策准备

**Files:** 产出 `docs/ops/phase-0-fact-baseline-2026-09-20.md`（§GATE-A）+ ADR 草案（按需落 `docs/adr/`）
**依赖：** T0-1~T0-12
**Steps:**
1. 汇总 Gate A 待决策项，逐项给证据 + 选项 + 推荐 + 待拍板人：
   - `ADR-DATA-01 module_data_rows role`（来自 T0-8）
   - `ADR-DATA-02 import visibility + idempotency contract`（来自 T0-6/T0-11）
   - `ADR-API-01 total_count compatibility semantics`（来自 T0-3/T0-4）
   - `ADR-OPS-01 supported deployment architectures`（来自 T0-1）
2. 若已有正式契约/ADR，则引用现有，不重复造文档。
3. **本任务只准备决策材料，不自行拍板。** 业务/权限/不可逆项列"需负责人确认"。

**Verify:**
```bash
rg -n "ADR-DATA-01|ADR-DATA-02|ADR-API-01|ADR-OPS-01" docs/ops/phase-0-fact-baseline-2026-09-20.md
```
**Accept:** §GATE-A 四项各有证据 + 选项 + 推荐 + 拍板人；无自行决策项；引用现有 ADR 处已标注。

---

## 2. 证据落点汇总

| 任务 | 产出 | 目标 Evidence / State |
|---|---|---|
| T0-1 | §CONTEXT | E1 |
| T0-2 | §CONSTRAINTS | E1 |
| T0-3 | §LOCATORS | E1 |
| T0-4 | §ISSUE-REGISTER | 每条 S0→S1/E0→E1；runtime-only 允许停留 + 复现计划 |
| T0-5 | §PG | 可连库 E1；否则 RUNTIME_ONLY |
| T0-6 | §CH | 可连库 E1；否则 RUNTIME_ONLY |
| T0-7 | §IDENTITY | E1（P0-2 判定） |
| T0-8 | §MODULE-ROWS | E1（ADR-DATA-01 输入） |
| T0-9 | §BASELINES + scripts | 可执行域 E3；不可执行 RUNTIME_ONLY |
| T0-10 | §QUERY-CLASS + fixture | 可连库 E3；否则 RUNTIME_ONLY |
| T0-11 | fixture 测试 | E2（夹具断言） |
| T0-12 | §LEAK + isolation 扩展 | E2（有产物则） |
| T0-13 | §GATE-A + ADR 草案 | 决策材料 |

---

## 3. 阶段退出判据（Gate-0）

```bash
# 1) 登记册存在，且每条候选问题六字段齐全（State/Evidence/locator/owner/repro/next gate）
test -f docs/ops/phase-0-fact-baseline-2026-09-20.md
rg -c "State|Evidence|locator|reproduction|next gate" docs/ops/phase-0-fact-baseline-2026-09-20.md

# 2) 本阶段新增/扩展测试与夹具必须绿（无 skip/xfail 伪装 P0）
cd apps/worker && .venv/bin/python -m pytest tests/test_import_idempotency_fixture.py -q
python3 -m unittest scripts.test_site_artifact_isolation -v
python3 -m unittest scripts.test_ci_job_contracts -v

# 3) 未触碰被禁文件（只允许新增：报告/只读脚本/夹具/ADR 草案）
git status --short
```

**DoD 勾选项：**
- [ ] §CONTEXT / §CONSTRAINTS / §LOCATORS 齐全（T0-1/2/3）
- [ ] §ISSUE-REGISTER 每条六字段齐全，runtime-only 项附复现/基准计划（T0-4）
- [ ] §PG / §CH 引擎与版本事实已记录或标 RUNTIME_ONLY（T0-5/6）
- [ ] §IDENTITY 全链路每层现状 + P0-2 判定（T0-7）
- [ ] §MODULE-ROWS 角色 + schema 归属 + 保留期（T0-8）
- [ ] §BASELINES 分域 snapshot；Import 无假对照（T0-9）
- [ ] §QUERY-CLASS 夹具覆盖全部 query class；短查询策略待决策（T0-10）
- [ ] 导入 fixture 每个 case 有期望断言，无 skip/xfail 伪装（T0-11）
- [ ] §LEAK 覆盖 P0-3 全部载体，缺口登记（T0-12）
- [ ] §GATE-A 四项 ADR 决策材料就绪（T0-13）
- [ ] **未修改** `apps/api`、`apps/worker`（除新增夹具）、迁移、OpenAPI、nginx、CI workflow

**未验证项披露（强制）：** 凡因缺 PG/CH/dist/CI 历史无法实测的任务，显式标 `RUNTIME_ONLY` 或 `SKIPPED（原因）`，并**阻断**依赖该数字的后续门判定（遵循 `scripts/smoke.sh`：前提缺失报 SKIPPED，绝不算通过）。

---

## 4. 风险与回滚

| 风险 | 触发条件 | 缓解 |
|---|---|---|
| 无数据库/产物，基线为空 | 开发机缺 PG/CH/dist | 脚本仍入库；数字标 RUNTIME_ONLY；阻断依赖数字的后续门 |
| 误把静态阅读/旧文件当事实 | 未重新核验 | T0-3 按符号定位；T0-4 双轨登记；无 `文件:行号` 不结项 |
| 夹具被 skip/xfail 伪装 | 场景难构造 | P0 场景禁 skip；未构造项标 `TODO(phase-2)` 并登记 |
| 顺手"修复"缺陷 | 范围蔓延 | 本阶段禁改被禁文件；`git status` 只允许新增项 |
| 把证据等级当修复状态 | 双轨混用 | §ISSUE-REGISTER 强制 State 与 Evidence 分列 |

**本阶段不产出缺陷修复**，无功能回滚风险；唯一"回滚"是删除新增的只读脚本/夹具/报告/ADR 草案。

---

## 5. 交付后的下一步

本阶段完成后进入 **Gate A**（拍板 §GATE-A 四项 ADR），再生成 **Phase 1（P0 正确性）** 子计划，
以登记册为输入：`S1/E1+` 项进入修复，`RUNTIME_ONLY` 项进入 Phase 3 基线，`S0` 项继续补证。
