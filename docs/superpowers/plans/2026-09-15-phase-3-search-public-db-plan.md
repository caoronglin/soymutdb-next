# Phase 3 · 检索与公众数据库

> **父计划：** `plan.md`（主路线图）。执行前先读 §2 冻结决策登记表。
> **前置：** Phase 1 已退出（S 组完成）；Phase 2 的 **D2 分页契约已建立**（P4 依赖它）
> **Wave：** W3
> **退出判据：** §4

---

## 0. 子计划级修订说明

| 二轮审计问题 | 本计划处置 |
|---|---|
| v2 排序为「精确 > 前缀 > 子串 > 别名」（别名排在子串之后） | 冻结为 `exact > curated alias > prefix > substring`（FZ-9）；游标 `rank` 保持 3/2/1 |
| 删 R6 后未说明别名的索引需求 | 归入 R1 的取证清单 |
| R1 预设「必须无 Seq Scan」 | 改为**索引命中判据** + 先取证后建索引 |
| R4「分阶段返回」无传输协议 | 冻结为**同步单响应 + 统一 6s 预算**（FZ-10） |
| R8 返回空列表却标称 fail-closed | 冻结为 **503 `release_context_unavailable`**（FZ-11） |
| R7 的 Top-N 慢查询会泄露检索词并高基数 | 只暴露有限标签指标 + 负向断言 |
| D3 引用不存在的 `check_contract_visibility.py` | 改用真实入口 `scripts/test_contract_visibility.py` |
| D4 的 pytest 选择器未覆盖 DB 集成层；产物层用陈旧 dist | 显式列出集成层文件；层 4 前**强制重建双产物** |
| D5 无法检测 ClickHouse N+1 | 增加 CH client 调用计数断言 |
| D6 无可执行预算 | 冻结 span / results / timeout / 状态码 / 错误码（FZ-13） |
| P4 目标「下降 80%」无依据、Files 缺前端 | 目标由 P1 基线推导；Files 补 `apps/web/src/routes/variants/index.tsx` |

---

## 1. 任务清单

### R3 · 黄金查询集门禁（**先于 R2**）

**Files:** 新增 `scripts/fixtures/search-golden.json`、`scripts/check_search_golden.py`
**Steps:**
1. 在**当前**行为上建立基线（**不修改** `search_service.py`），作为 R2 的回归护栏。
2. 覆盖：精确 accession、**别名等值**、前缀、子串、拼写错误、公开 vs 内部标识符、
   **v4/v5 同名基因不混淆**、跨装配体请求必须显式作用域、零结果、`limit`/`cursor` 边界。
3. 断言每条查询的 Top-N **与 `match_type`**。
4. 门禁需要 DB：**必须显式声明「需 PostgreSQL」**，不得在无 DB 环境下静默跳过
   （否则 R2 的护栏失效）。

**Verify:**
```bash
# 需 PostgreSQL：
(cd apps/api && .venv/bin/python -m pytest tests -q)   # 先确保 DB 可用
apps/api/.venv/bin/python scripts/check_search_golden.py
# 无 DB 时必须 FAIL 并提示，而非 PASS
# 负向用例（三种，均须实测变红）：
#   a) 把 v5 结果混入 v4 请求的期望集   → 期望 FAIL
#   b) 把 alias 用例的 match_type 改成 text → 期望 FAIL
#   c) 断开 DB 后重跑                    → 期望 FAIL（不得静默跳过）
```
**Accept:** 门禁进共享脚本；三种负向用例可复现；DB 不可用时明确失败。

---

### R2 · 排名语义固化

**Files:** `apps/api/app/services/search_service.py`、`docs/dev/database-core-contract.md`（补排名章节）
**依赖：** R3 已完成
**Steps:**
1. **冻结排名（FZ-9）：`exact（accession 等值） > curated alias（别名等值） > prefix（前缀） > substring（子串）`。**
   前缀作为 **`text` 档内的二级排序键**，**不新增第五种 `match_type`**（不改公开契约）。
2. `match_type` 映射保持：exact→`exact`，alias→`alias`，prefix/substring→`text`。
3. 保持游标 `_cursor.rank` 取值集合不变（**3/2/1**），否则破坏既有游标兼容。
4. **不引入 `GREATEST(similarity(...))` 作为排序键**：它不可索引化，会把当前可用的排序
   变成全表函数计算。如需相似度排序，必须单独立项并附 EXPLAIN 证据。
5. 排序稳定性：同档内以 `accession` 为 tie-breaker（与既有实现一致）。

**Verify:**
```bash
apps/api/.venv/bin/python scripts/check_search_golden.py   # 护栏（R3 产出）
(cd apps/api && .venv/bin/python -m pytest tests -q -k "search")   # 需 PostgreSQL
pnpm --filter @soymutdb/web test
```
**Accept:** 排名规则文档化；游标 `rank` 取值不变；黄金集仅在**评审后**同步更新，
更新内容在 PR 中单列 diff。

---

### R1 · 索引覆盖（先取证，后建索引）

**Files:** 新增 `apps/api/migrations/versions/0037_search_index_coverage.py`、`docs/ops/slow-query-log.md`
**Steps:**
1. **先取证**：在真实数据量下对以下谓词跑 `EXPLAIN (ANALYZE, BUFFERS)`，记录 `rows` 与 `actual time`：
   - `genes.accession ILIKE '%…%'`（子串）
   - `genes.accession = $1` 与 `upper(genes.accession) = $2`（等值）
   - `gene_aliases.alias = lower($1)`（R2 的别名等值路径）
   - `mutant_lines.public_id ILIKE '%…%'` 与等值
   - `publications.doi` / `publications.pmid` 等值
2. **按证据选索引类型（且必须含 assembly 作用域）**：

   > **三轮审计 S13（严重）：** v3 建议 `CREATE UNIQUE INDEX ... ON genes (upper(accession))`，
   > **违反仓库的数据契约**。`Gene` 模型自身注释已写明：
   > *"accessions are only unique per assembly (v4 and v5 are distinct namespaces)"*；
   > 现有 `ix_gene_accession` 也是**非唯一**索引。全局唯一索引会在导入第二个装配体时直接失败。

   - **ID 类等值查询**优先**函数 B-tree**，且键必须带作用域：
     - `genes`：`(assembly_id, upper(accession))`（**唯一**，与 v4/v5 命名空间一致）
     - `mutant_lines`：`(release_id, upper(public_id))`（`public_id` 已是全局唯一，见迁移 `0032`；
       仍保留 release 维度以便与检索的 release 作用域对齐）
     - `gene_aliases`：`(gene_id, lower(alias))` 已由 `uq_gene_alias` 覆盖；
       检索的 **alias 等值** 需要的是 **join 侧** 的 `lower(alias)` 索引 ——
       先 EXPLAIN 确认 `ix_gene_alias_alias` 是否已足够；**不足时**才加 `(lower(alias))`，
       并说明为何不能直接用现有非函数索引。
     - `publications`：`doi` / `pmid` 等值 —— **不加唯一约束**（待确认是否有跨 release 重复），
       先加普通 B-tree 并记录选择度。
   - **子串查询**（`ILIKE '%x%'`）才用 `gin (col gin_trgm_ops)`；
     `genes.accession` 若要同时支持前缀与子串，需说明为何不能只保留函数 B-tree。
   - 每种索引必须给出：查询频率、选择度、写放大评估。
   - **未证明收益的索引不建。**
3. 迁移编号固定 **`0037`**（FZ-1）；**必须写 downgrade**；
   对已存在的表用 `CREATE INDEX CONCURRENTLY`（alembic 中 `op.execute` + `autocommit_block`，
   并在注释注明「`CONCURRENTLY` 不能在事务块内执行，失败时索引可能处于 INVALID 状态，需手工清理」）。
4. 把 EXPLAIN 结论写回 `docs/ops/slow-query-log.md`，含**索引命中判据**
   （如 `Bitmap Index Scan` / `Index Scan` 且 `rows` 显著低于表行数），
   **不写「必须无 Seq Scan」**（小表或低选择度下不成立）。
5. **导入回归**：在迁移测试中断言「同一 accession 分别属于两个 assembly 时可共存」——
   这是本轮修正的直接回归用例，不得省略。

**Verify:**
```bash
(cd apps/api && .venv/bin/python -m pytest tests -q -k "search or trigram or assembly")   # 需 PostgreSQL
# EXPLAIN 取证（在仓库根执行；脚本内部走 docker compose exec，需 Docker + PostgreSQL）
make explain-query Q="SELECT id FROM genes WHERE assembly_id = 1 AND upper(accession) = 'GLYMA.01G000100'"
make explain-query Q="SELECT id FROM genes WHERE accession ILIKE '%Glyma.01G%'"
# 迁移双向（需 PostgreSQL）
(cd apps/api && .venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head)
```
**Accept:** 迁移双向可执行；每条新索引都有 EXPLAIN 前后对比；
**v4/v5 同名 accession 共存有回归断言**；未证明收益的索引未建。

---

### R4 · 联邦检索降级可控（冻结为同步单响应）

> **修正二轮审计：** v2 的「主源先返回、远端源在预算内补齐」在普通 HTTP 请求里不可实现
> ——响应一旦发出就无法再补齐。本版冻结为**同步单响应 + 统一预算**，不改传输协议。

**Files:** `apps/api/app/search/aggregator.py`、**`apps/api/app/search/models.py`**、`apps/api/app/api/v1/search.py`

> **三轮审计 S14：** v3 只把总预算从 8s 改成 6s，但**未修真正的缺陷**：
> `aggregator.py:98-118` 在 `wait_for` 超时后会**重建全部 task 并再 `gather` 一次**
> （注释写 "via a fresh shorter gather"），等待时间因此**翻倍**（而非受 6s 约束）。
> 不修这里，6s 预算是假的。

**Steps（**FZ-10**）：**
1. **修超时路径（本任务的核心）：**
   - **保留首次创建的 task 对象**（不要在 except 分支重新 `[_run(...) for s in requested]`）；
   - 超时后：**取消尚未完成的 task**（`task.cancel()` + 等待取消完成），
     **收集已完成 task 的结果**；
   - **禁止重发**：不得对任何源再次发起 HTTP 请求（这与 R5 的外部调用预算同源）；
   - 已取消的任务对应的源标记为 `status=degraded`。
2. **总预算 6.0s 硬墙钟**；per-source 超时按源分别收敛（NCBI/UniProt 3.0s，Ensembl/EBI 2.5s）。
3. **新增字段**（在 `models.py` 的 `ExternalSearchResponse` 上，不改既有字段）：
   `partial: bool`、`degraded_sources: list[str]`。
   `partial=true` 当且仅当至少一个源非 `ok`/`empty`。
4. 缓存 TTL 分级：稳定源（NCBI/UniProt）300s，易变源（Ensembl/EBI）60s。
5. **不在本任务引入流式/轮询/SSE。**

**Verify:**
```bash
(cd apps/api && .venv/bin/python -m pytest tests -q -k "search_federation")
# 负向：注入单源超时 → 断言其余源仍返回、partial=true、degraded_sources 含该源
# 断言：所有源正常时 partial=false 且 degraded_sources 为空
# 关键回归（防止重发）：
#   mock 各 adapter 的 HTTP 客户端，计数调用次数；
#   注入一个 7s 才返回的慢源 → 断言该源的 adapter 被调用**恰好 1 次**（而非 2 次）
# 墙钟断言：
#   注入全源慢响应 → 断言整个 search() 的 wall-clock ≤ 6.0s + 允许误差（如 0.5s）
```
**Accept:** 总耗时受 6s 硬墙钟约束；**超时后不重发**（有调用计数断言）；
降级状态在响应中可见且语义明确。

---

### R5 · 检索缓存键契约审计

**Files:** `apps/api/app/search/cache.py`、`apps/api/app/api/v1/search.py`、`apps/api/app/services/cache.py`、`docs/dev/database-core-contract.md`
**Steps（**FZ-16**）：**
1. **生物检索（SoyMutDB 本地）**：缓存键必须含 `site_variant` / release / assembly / query / filters。
2. **外部联邦检索**（NCBI/UniProt 等）：键只需 `query + sources + ttl` —— 它不涉及 `site_variant`
   与 release 语义，**不得**为「形式统一」加入无意义维度（会降低命中率）。
3. 内部检索必须**不进共享缓存**（现状已是），并补测试。
4. 在 `docs/dev/database-core-contract.md` 中**分别**写明两类键的约定与理由。

**Verify:**
```bash
(cd apps/api && .venv/bin/python -m pytest tests -q -k "cache")   # 需 PostgreSQL
# 断言：改变 site_variant / release / assembly 后本地检索键不同
# 断言：internal 检索结果不写共享缓存
```
**Accept:** 缓存键契约有测试约束；两类约定在文档中分别说明。

---

### R7 · 检索可观测（不含查询内容）

**Files:** `apps/api/app/core/metrics.py`、`infra/monitoring/rules/alerts.yml`、`apps/api/app/services/search_service.py`
**Steps:**
1. Prometheus 只暴露**有限标签**指标：`{endpoint, source, status}` 的 QPS / P50 / P95 /
   零结果计数 / 各源降级率 / 缓存命中率。
2. **不把 query 文本、内部标识符、用户标识写入任何 label。**
3. 慢查询明细走**结构化日志**（`search.slow`），带保留期与采样率；
   日志中的 query 需截断并标注采样，写入 `docs/ops/slow-query-log.md` 的流程说明。
4. 告警：零结果率相对 7 天基线异常升高；某源连续 5 分钟 `degraded`。
5. **负向测试（强制）**：发起一次含唯一标记串的检索，断言 `/metrics` 输出中不含该串。

**Verify:**
```bash
curl -s localhost:8000/metrics | grep search
(cd apps/api && .venv/bin/python -m pytest tests -q -k "analytics_privacy or metrics")
# 负向：断言 /metrics 输出不含测试查询串（唯一标记）
```
**Accept:** 指标无 PII/高基数；负向断言可复现。

---

### R8 · suggest 作用域 fail-closed

> **修正二轮审计：** v2 返回空列表 + `X-Search-Scope: unscoped`，用户会读成「没有匹配结果」，
> 而实际是「缺少 release 上下文」。这不是 fail-closed，是静默降级。

**Files:** `apps/api/app/api/v1/search.py`、`apps/api/app/services/search_service.py`、`apps/web/src/routes/search.tsx`（提示文案）
**Steps（**FZ-11**）：**
1. 无 release 上下文时返回：
   ```http
   HTTP/1.1 503 Service Unavailable
   { "error": { "code": "release_context_unavailable",
                "message": "Search suggestions require a published release context" } }
   ```
   （复用既有统一错误信封，见 `apps/api/app/schemas/error.py`。）
2. 前端 `search.tsx` 捕获该错误码，显示「数据版本暂不可用，请稍后重试」，
   **不得**显示「无匹配结果」。
3. 有 release 时只返回该 release；装配体维度继续用 `metadata.assembly_id` 标注。
4. 补缓存与测试（错误结果**不缓存**）。

**Verify:**
```bash
(cd apps/api && .venv/bin/python -m pytest tests -q -k "suggest or search")   # 需 PostgreSQL
pnpm --filter @soymutdb/web test
# 断言：无 release 时 status=503 且 code=release_context_unavailable
# 断言：该错误响应不被写入缓存
```
**Accept:** 自动补全不再成为跨版本混淆来源；无 release 时语义明确（非「空结果」）。

---

### D3 · release/assembly 上下文可见

> **修正二轮审计：** v2 引用 `scripts/check_contract_visibility.py`（不存在）。
> 实际入口是 `scripts/contract_visibility.py` + `scripts/test_contract_visibility.py`。

**Files:** `apps/api/app/schemas/*.py`、公开读端点
**Steps:** 对照 `AGENTS.md`：公开响应必须携带 assembly/release/版本上下文。
逐端点核查并补齐（`VariantListResponse`、基因列表、mutant 列表、stats、releases）。
**Verify:**
```bash
apps/api/.venv/bin/python -m pytest scripts/test_contract_visibility.py -q
(cd apps/api && .venv/bin/python -m pytest tests -q -k "release_context or contract")   # 需 PostgreSQL
```
**Accept:** 每个公开结果都能回答「哪个装配体、哪个 release」；两个门禁通过。

---

### D4 · 公开边界负向矩阵（5 层，**每层独立可执行**）

**Files:**
- 层 1（API 单测）：`apps/api/tests/test_search_internal_http.py`、`apps/api/tests/test_mutants.py`（扩展）
- 层 2（PG 集成）：`apps/api/tests/test_search_database_integration.py`（扩展）
- 层 3（前端）：`apps/web/src/**/__tests__/`（URL/路由不渲染内部标识符）
- 层 4（产物）：`scripts/check_site_artifact_isolation.py`（扩展，扫 `dist/external`）
- 层 5（E2E）：`e2e/tests/`（扩展，真实浏览器）

**Steps:** 覆盖 external/internal × public/internal identifier × v4/v5；
断言内部标识符与未发布记录**绝不出现在**：响应体、URL、客户端可见日志、`dist/external`。
每层都要有**独立的负向用例**（人为注入泄漏须变红）。

**Verify（五层分别执行，不得用一条命令糊过去）：**
```bash
# 层 1：API 单测（不需 DB）
(cd apps/api && .venv/bin/python -m pytest tests/test_search_internal_http.py tests/test_mutants.py -q)
# 层 2：PG 集成（需 PostgreSQL）—— 显式列出，不用 -k 选择器
(cd apps/api && .venv/bin/python -m pytest tests/test_search_database_integration.py -q)
# 层 3：前端
pnpm --filter @soymutdb/web test
# 层 4：产物 —— 必须先重建，否则会扫描陈旧 dist 造成假通过
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test pnpm --filter @soymutdb/web build:sites
apps/api/.venv/bin/python -m pytest scripts/test_site_artifact_isolation.py -q
# 层 5：真实浏览器（需浏览器）
cd e2e && npx playwright test -c playwright-public.config.ts
```
**Accept:** 五层全绿且**无 skip/xfail**；层 4 的构建步骤在脚本中前置，不依赖调用者手工重建。

---

### D5 · 查询数门禁扩展（含 ClickHouse）

> **修正二轮审计：** `test_query_count.py` 统计的是 SQLAlchemy/PostgreSQL 查询，
> 而 `variants` 走 ClickHouse —— 只看 PG 会漏掉 CH 侧的 N+1。

**Files:** `apps/api/tests/test_query_count.py`（扩展）、`apps/api/tests/conftest.py`（新增 CH 计数夹具）
**Steps:**
1. 扩展 PG 查询数断言到 variants/genes/mutants 列表与详情（含分页边界与过滤组合）。
2. **新增 ClickHouse 调用计数夹具**：包装 `ClickHouseService._get_client()` 返回的 client，
   统计 `query()` 调用次数；断言列表端点每次请求的 CH 调用次数 ≤ 常量
   （例如列表 1 次、详情 1 次，含分页不重复计数）。
3. 分页边界：首页 / 中间页 / 末页 / `has_more=false` 各断言一次。

**Verify:**
```bash
(cd apps/api && .venv/bin/python -m pytest tests/test_query_count.py -q)   # 需 PostgreSQL
# 负向：在列表循环内人为加一次 CH 查询 → 期望 FAIL
```
**Accept:** 列表端点的 PG 与 CH 调用次数均有上界；回归即红。

---

### D6 · 大结果集预算（**数值冻结**）

**Files:** `apps/api/app/api/v1/variants.py`、`apps/api/app/services/clickhouse_service.py`、`apps/api/app/core/config.py`
**Steps（**FZ-13**）：**
1. 冻结预算（写入 `config.py` 作为可配置项，默认值如下）：

   | 项 | 值 |
   |---|---|
   | 区域跨度上限 | **10 Mb**（`variant_region_max_span_bp`） |
   | `max_results` 上限 | **10000**（保持现值） |
   | 服务端超时 | **10s**（`variant_region_timeout_seconds`） |
   | 超限响应 | **HTTP 422**，错误码 **`region_query_too_large`** |

2. 超限时返回统一错误信封，`details` 携带实际跨度与上限，便于客户端调整。
3. 文档写出推荐用法：按染色体或缩小窗口分片。
4. **数值须由 Phase 4 的 P1 数据复核一次**（每 Mb 的行数与耗时）；若需调整，
   在本文件登记「原值 / 新值 / 依据 / 日期」。

**Verify:**
```bash
(cd apps/api && .venv/bin/python -m pytest tests -q -k "region or variant")   # 需 PostgreSQL
# 断言：span > 10Mb → 422 + region_query_too_large + details 含实际跨度
# 断言：timeout 生效（mock 慢查询 → 明确错误，非 500）
```
**Accept:** 单请求不可能拖垮分析投影；超限行为有明确状态码与错误码。

---

### D7 · 下载与导出

**Files:** `apps/api/app/api/v1/*`（导出）、`infra/nginx/*.conf`
**Steps:** 校验 Range/断点续传；导出加配额与过期；确认 `/data/` 的 `proxy_buffering off` 与大文件行为。
**Verify:**
```bash
OBJECT_KEY=${OBJECT_KEY:?需先准备一个基因组对象}
curl -r 0-1023 -sI "http://localhost:8080/data/${OBJECT_KEY}" | head -20   # 期望 206 + Content-Range
# 导出超配额被拒
```
**Accept:** 大文件下载不占用应用内存、可续传；导出有配额与过期。

---

### D8 · 公开 API 使用文档

**Files:** `docs/user/`（新增）
**Steps:** 说明配额、缓存语义（哪些可缓存、如何拿到 304）、分页（cursor 用法与各类上限）、
`site_variant` 与 assembly/release 语义、错误码目录（含 `region_query_too_large`、
`release_context_unavailable`）、建议轮询间隔。
**Verify:** 文档中每条示例实际执行一次并记录结果（含退出码与关键响应头）。
**Accept:** 示例全部可复现；错误码与实现一致。

---

### D9 · 预聚合读取（含**口径扩宽**）

> **三轮审计 S15（严重）：** v3 假设现有 MV 可直接服务 dashboard，但它们**口径不足**：
> `get_dashboard_stats` 需要 `uniqExact(gene_id)` 与 `uniqExact(mutant_line_surrogate_id)`，
> 而 `release_dashboard` 只有 `(release_key, variant_type, impact, consequence, cnt)`；
> `gene_impact_summary` / `mutant_line_summary` 中同一实体也会跨多个 bucket 重复。
> 在 SummingMergeTree 上 `count()` 汇总**不等于**唯一实体数。

**Files:** `apps/api/app/services/clickhouse_service.py`、`infra/clickhouse/init.sql`、
`infra/clickhouse/upgrade_variant_facts_schema.sql`、`infra/clickhouse/test_schema_contract.py`、
新增 `apps/api/migrations/versions/0038_release_entity_summary.py`

**Steps:**
1. **先分类**现有 dashboard 指标，逐项标注可用哪张表，并区分两类：

   | 指标 | 口径 | 可用来源 |
   |---|---|---|
   | `snp/ins/del/mnv/sv_count` | `sum(cnt) GROUP BY variant_type` | `release_dashboard`（**需 GROUP BY，不能直接读行**） |
   | `total_variants` | `sum(cnt)` | `release_dashboard` |
   | `total_genes` | `uniqExact(gene_id)` | **现有 MV 无法精确恢复** |
   | `total_mutant_lines` | `uniqExact(mutant_line_surrogate_id)` | **现有 MV 无法精确恢复** |

2. **口径扩宽（FZ-1，迁移 `0038`）：** 新增一张带聚合状态的汇总表 + MV：
   ```sql
   CREATE TABLE IF NOT EXISTS release_entity_summary (
       release_key  String,
       genes        AggregateFunction(uniqExact, UInt32),
       mutant_lines AggregateFunction(uniqExact, UInt32)
   ) ENGINE = AggregatingMergeTree()
   ORDER BY (release_key);

   CREATE MATERIALIZED VIEW IF NOT EXISTS mv_release_entity
   TO release_entity_summary AS
   SELECT release_key,
          uniqExactState(gene_surrogate_id)        AS genes,
          uniqExactState(mutant_line_surrogate_id) AS mutant_lines
   FROM variant_facts
   GROUP BY release_key;
   ```
   读取时用 `uniqExactMerge(genes)` / `uniqExactMerge(mutant_lines)`。
   **必须写 downgrade**；`test_schema_contract.py` 的表清单同步更新。
3. **SummingMergeTree 读取纪律：** 对 `release_dashboard` / `gene_impact_summary` /
   `mutant_line_summary` 的读取必须 `sum(cnt) ... GROUP BY`，
   **不得**假设背景合并已完成、也不得直接 `count()`。
4. 把 `get_dashboard_stats`、`get_variant_type_distribution` 改为读预聚合 + 缓存；缓存键含 `release_key`。
5. **若某指标无法用任何预聚合精确表达**，保留独立查询 + 缓存，并在注释中说明为何不预聚合——
   **不得用近似口径冒充精确值**。

**Verify:**
```bash
python3 infra/clickhouse/test_schema_contract.py   # 需 ClickHouse
# 双跑比对（在真实数据上）：预聚合结果 vs 实时聚合结果必须逐字段一致，
#   包括 total_genes 与 total_mutant_lines 两个唯一计数
# CH 侧证据：新实现的 read_rows 应显著低于旧实现
# 静态断言：所有读取 release_dashboard 的查询都带 sum()/GROUP BY
```
**Accept:** dashboard 全部指标（含两个唯一计数）与实时聚合一致；
聚合查询不再扫明细表；Summing 表读取均有 `sum+GROUP BY`；
不能精确表达的指标有显式说明而非近似值。

---

## 2. 阶段内任务顺序

| 顺序 | 任务 | 理由 |
|---|---|---|
| 1 | R3 | 先锁行为（含 v4/v5 不混淆），后续排序改动才有护栏 |
| 2 | R2 | 在护栏内改排名 |
| 3 | R1 | 索引需在 R2 定稿后取证（排序/匹配路径已稳定） |
| 4 | R4 | 独立 |
| 5 | R5 | 独立 |
| 6 | R7 | 独立（指标改造） |
| 7 | R8 | 依赖 R2 的 `match_type` 语义 |
| 8 | D3 | 契约可见性 |
| 9 | D4 | 五层矩阵（层 4 需 Phase 2 的产物构建链） |
| 10 | D5 | 查询数门禁（CH 夹具可复用于 D9 验证） |
| 11 | D6 | 区域预算（数值待 Phase 4 P1 复核） |
| 12 | D9 | 预聚合（依赖 D5 的 CH 计数夹具做证据） |
| 13 | D7、D8 | 独立 |

---

## 3. 边界与约束

- **R2 不得改动游标 `rank` 取值集合**（3/2/1）；改集合即破坏既有游标兼容。
- **R1 不得建无证据的索引**；「防御性建索引」在本计划中被明确禁止（写放大成本真实）。
- **R4 不得引入流式/轮询协议**；那是独立变更，需 P1 数据支撑。
- **D4 层 4 必须先重建产物**；扫描陈旧 `dist` 会形成假通过。
- **D4 所有隐私用例不得 skip/xfail**；无 DB 时层 2 必须 FAIL 而非跳过。
- **D6 的数值变更必须登记**，不得静默调整。

---

## 4. 阶段退出判据

```bash
# 1. 检索
apps/api/.venv/bin/python scripts/check_search_golden.py          # 需 PostgreSQL
(cd apps/api && .venv/bin/python -m pytest tests -q -k "search")   # 需 PostgreSQL

# 2. 契约可见性与隐私矩阵（五层）
apps/api/.venv/bin/python -m pytest scripts/test_contract_visibility.py -q
(cd apps/api && .venv/bin/python -m pytest tests/test_search_internal_http.py tests/test_mutants.py -q)
(cd apps/api && .venv/bin/python -m pytest tests/test_search_database_integration.py -q)   # 需 PostgreSQL
pnpm --filter @soymutdb/web test
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test pnpm --filter @soymutdb/web build:sites
apps/api/.venv/bin/python -m pytest scripts/test_site_artifact_isolation.py -q
cd e2e && npx playwright test -c playwright-public.config.ts

# 3. 查询数与预算
(cd apps/api && .venv/bin/python -m pytest tests/test_query_count.py -q)   # 需 PostgreSQL

# 4. 预聚合
python3 infra/clickhouse/test_schema_contract.py

# 5. 未回退
python3 scripts/check_plan_commands.py
python3 scripts/check_pagination_contract.py
SOYMUTDB_SMOKE_PYTHON=apps/api/.venv/bin/python bash scripts/smoke.sh --profile contracts
```

**需环境的判据**（本机不可执行 → CI 补验，标「未验证」）：
`check_search_golden.py`、`tests -k search`、`test_search_database_integration.py`、
`test_query_count.py`、`make explain-query`、`playwright-public`、CH `test_schema_contract.py`。

**DoD 勾选项：**
- [ ] R3 黄金集含 v4/v5 不混淆与 `match_type` 断言，DB 不可用时明确 FAIL
- [ ] R2 排名为 `exact > alias > prefix > substring`，游标 `rank` 仍为 3/2/1
- [ ] R1 迁移 `0037` 双向可执行，每条索引有 EXPLAIN 前后对比
- [ ] R4 冻结为同步单响应 + 6s 预算；`partial`/`degraded_sources` 语义有测试
- [ ] R5 两类缓存键约定分别文档化并有测试
- [ ] R7 `/metrics` 无查询内容；负向断言可复现
- [ ] R8 无 release 返回 503 `release_context_unavailable`，前端显示「版本不可用」
- [ ] D3 使用真实入口 `scripts/test_contract_visibility.py`
- [ ] D4 五层全绿、无 skip/xfail、层 4 前置重建
- [ ] D5 PG + CH 调用次数均有上界
- [ ] D6 冻结数值生效，超限 422 `region_query_too_large`
- [ ] D9 预聚合双跑一致，read_rows 显著下降

---

## 5. 风险与回滚

| 风险 | 触发条件 | 缓解 / 回滚 |
|---|---|---|
| R1 索引锁表 | 大表建索引 | `CREATE INDEX CONCURRENTLY`；失败时索引可能 INVALID，需手工 DROP 后重试 |
| R1 索引无收益 | 低选择度 | 先 EXPLAIN 后建；未证明收益不建 |
| R2 排名变化影响用户预期 | Top-N 变化 | 游标 `rank` 不变；黄金集护栏；变更前后 Top-5 对比记录 |
| R4 预算收紧导致源频繁降级 | 远端慢 | 观察 `degraded_sources` 比例；必要时按源单独放宽，而非整体回退到 8s |
| R8 前端未处理 503 | 文案缺失 | 同 commit 改前端；E2E 断言提示文案 |
| D4 层 4 扫描陈旧产物 | 未重建 | 构建步骤写进层 4 的 Verify，不依赖调用者 |
| D6 预算过紧 | 合法用例被拒 | 用 P1 数据复核一次；登记调整理由 |
| D9 预聚合与实时不一致 | MV 刷新缺口 | 双跑比对为 Accept 前置；不一致即回滚到实时聚合 |

**通用回滚：** 每任务独立 commit；高风险文件（`apps/api/app/services/search_service.py`、
`apps/api/migrations/versions/0037_*.py`、`apps/api/app/services/clickhouse_service.py`、
`apps/web/src/routes/variants/index.tsx`）在 PR 中单列 diff。
