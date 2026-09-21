# SoyMutDB 技术审计、数据协议与 UI/UX 优化执行计划（第四轮研究工作流收敛版）

> **文档类型：** 技术审计 + 执行路线图 + Go/No-Go 门禁
> **状态：** 计划，不等于实施授权
> **原始计划日期：** 2026-09-18 ｜ **第一轮审计：** 2026-09-20 ｜ **第二轮审计：** 2026-09-20 ｜ **第三轮执行收敛：** 2026-09-21 ｜ **第四轮 UI/UX 与竞品复核：** 2026-09-21
> **原计划声明基线：** `54532ed` / `codex/fix-compose-preview-data-layer`
> **当前执行基线：** `main@29b416af`（`docs(plan): harden Phase 2 staging and finalize constraints`）
> **仓库状态：** 已重新核验当前私有仓库、`main`、最近提交、开发分支、ADR 与 Phase 2 代码路径；历史 `文件:行号` 仍只作为 locator hint，当前事实以本文件末尾“执行状态真源”及对应代码/测试证据为准。
> **选用技能：** `dev-expert`（证据纪律 / 根因 / 威胁建模 / 生产就绪 / 反过度工程）、
> `systematic-debugging`（先复现后修）、`receiving-code-review`（结论须可核验，不橡皮章）
> **外部技术复核：** PostgreSQL / ClickHouse 数据语义，以及 Ant Design 6 / Ant Design Pro v6 / TanStack Router+Query / JBrowse 2 / ECharts 官方资料已复核；同时对照 SoyBase Fast Neutron Mutant 与 MaizeGDB 的突变体研究入口和信息架构。

---

# 0. 第二轮审计结论

第一轮已修正两个主要误判：

1. 不能仅凭 `ILIKE + ESCAPE` 断言 trigram 索引失效；
2. ClickHouse `MergeTree` 不能按 PostgreSQL 的"唯一约束 + 普通事务"思维直接设计幂等。

第二轮进一步发现 10 个结构问题：

1. **E0–E4 把"证据强度"和"缺陷生命周期"混在一起。**
2. `E2=复现已验证` 与 `E2=修复已验证` 语义冲突。
3. Phase 0 要求"所有高优先级项至少 E1"，但 runtime-only 问题天然不能靠静态代码达到 E1。
4. "SLO 由性能基线推导"逻辑不完整；SLO 应由业务需求/容量目标定义，基线用于验证可达性。
5. PostgreSQL 搜索计划仍缺少**查询类型路由**，exact ID、短字符串、substring 不应强行走同一路径。
6. ClickHouse import identity 缺少 parser/schema/config 等"语义变换版本"。
7. ClickHouse insert deduplication token 不应被当作永久 exactly-once 保证。
8. Analytics batching 缺少"事件是否允许丢失"的业务耐久性等级。
9. Rust "永久排除"过度约束；合理表述应是**本轮计划 No-Go**。
10. "100% fixture 一致性"应改为 **100% 契约级一致性**，不能要求内部实现/错误文本逐字一致。

本版执行逻辑改为：

```text
约束锁定 → 事实发现 → 问题确认 → P0 修复 → 数据协议闭环
        → 分域性能基线 → 针对性优化 → 容量/故障验证 → 可选 Rust PoC → 发布观察
```

---

# 1. 两套正交状态：证据等级 + 问题生命周期

## 1.1 证据等级 Evidence

| 等级 | 定义 | 可支持的声明 |
|---|---|---|
| **E0** | 历史计划/文档/旧行号/未复核记录 | 仅能说"待核验" |
| **E1** | 当前目标分支静态代码/配置/schema 已核验 | 可说"代码事实存在" |
| **E2** | 可重复的测试/运行时复现证据 | 可说"行为已确认" |
| **E3** | 生产等价环境 benchmark / EXPLAIN / 故障注入 | 可说"性能/可靠性结论已验证" |
| **E4** | staging/production 观察窗口确认 | 可关闭生产风险项 |

> **Evidence 只说明证据强度，不说明问题当前处于"未修/已修"。**

## 1.2 生命周期 State

| 状态 | 定义 |
|---|---|
| **S0 SUSPECTED** | 怀疑存在，仅有线索 |
| **S1 CONFIRMED** | 已确认问题存在 |
| **S2 FIX_READY** | 根因明确、修复方案与测试已准备 |
| **S3 FIXED** | 代码已修改，回归测试通过 |
| **S4 VERIFIED** | 生产等价环境验证通过 |
| **S5 CLOSED** | 发布观察完成，可关闭 |

示例 `D1: S1 / E2` 表示"已通过运行时证据确认 D1 存在，但尚未修复"，**而不是**"E2 所以已经修好"。

---

# 2. Merge Gate 与 Release Gate 分离

**Merge Gate（一个修复 PR 可合并至少需要）：** 静态事实 E1；失败复现或回归测试；修复后测试通过；相关契约测试不 skip/xfail；migration / rollback / observability 已说明。

**Release Gate（P0 进入生产必须额外满足）：** staging / production-equivalent 验证；negative leakage 测试；failure injection（若涉及数据/依赖服务）；回滚或 forward-fix 路径明确；关键指标/告警存在。

```text
P0 merge:   S3 + E2
P0 release: 至少 S4 + E3
P0 close:   S5 + E4
```

不再使用"P0 到 E2 即解除所有阻断"的模糊规则。

---

# 3. Phase 0：事实发现，而不是"强行证明所有项"

> Phase 0 **不修改业务代码**，只建立事实、夹具、测量脚本和待决策清单。

## 3.1 锁定目标上下文

```bash
git rev-parse HEAD; git branch --show-current; git status --short; git log -1 --oneline
```

记录：`target_branch` / `target_sha` / `dirty_tree` / `database_schema_version` / `clickhouse_version` / `postgres_version` / `python_version` / `node/pnpm_version` / `deployment topology`。

## 3.2 约束文档重新读取

按当前目标分支确认：`AGENTS.md`、`docs/dev/database-core-contract.md`、`docs/dev/pi-agent-hard-constraints.md`、`docs/dev/rust-rewrite-and-architecture-evaluation.md`、`docs/design/full-stack-upgrade-2026-08.md`。旧计划引用的内容全部从 E0 重新升级。

## 3.3 路径只作为 locator hint

旧路径（`apps/api/app/services/search_service.py`、`apps/worker/src/...`、`migrations/versions/*`）只作 E0 定位提示。若已移动，用**符号和契约**重新定位：

```bash
git grep -n "resolve_release_context"; git grep -n "module_data_rows"
git grep -n "UnsupportedImportError";  git grep -n "total_count"
git grep -n "gin_trgm_ops";            git grep -n "variant_facts"
git grep -n "record_event";            git grep -n "public_id"; git grep -n "internal_id"
```

## 3.4 Phase 0 Exit

不是"所有高优先级项 E1"。正确 Exit：每个候选问题必须有 `State` / `Evidence` / `current locator` / `owner-domain` / `reproduction method` / `next gate`。对 runtime-only 问题：**允许仍为 E0/E1，但必须已有可执行的 reproduction/benchmark plan。**

---

# 4. D1–D8 重新建模

| 原项 | Phase 0 初始状态 | 核验后可能归类 |
|---|---|---|
| D1 搜索索引 | S0/E0 | P1 性能 |
| D2 3 次 DB RTT | S0/E0 | P1 性能/架构 |
| D3 `total_count` | S0/E0 | P1 API 契约 |
| D4 `COUNT(*)` | S0/E0 | P1/P2 性能 |
| D5 import fail-closed | S0/E0 | P0 数据可用性**或**合法保护机制（见 §5.3） |
| D6 `module_data_rows` | S0/E0 | P0/P1，取决于其真实角色 |
| D7 analytics 单行 insert | S0/E0 | P1 成本/吞吐 |
| D8 mutant public identity | S0/E0 | 若违反上游身份契约则 P0 |

> **严重度必须由当前契约 + 当前行为决定，不由旧计划永久继承。**

---

# 5. P0：正确性、身份和边界

## 5.1 身份契约

重新核验全链路：`model` / `migration` / `API schema` / `route parameter` / `search hit` / `URL` / `frontend routing` / `cache key` / `analytics` / `logs`。重点字段：`public_id` / `internal_id` / `release_id` / `assembly_id`。

## 5.2 external/internal isolation

扫描范围：`HTTP body` / `HTTP headers` / `error responses` / `redirect Location` / `URL` / `SSR payload` / `HTML` / `JS` / `JSON` / `source maps` / OpenAPI examples / `logs` / analytics payload / `cache key+value` / generated artifacts。

## 5.3 fail-closed 不自动等于缺陷

若某导入能力当前 `feature disabled` + `adapter returns UnsupportedImportError`，先判断：**这是未实现功能，还是为保护数据一致性主动关闭？** 若是主动保护，则"fail-closed"本身不是缺陷；**真正缺陷是缺少安全启用它所需的数据协议/写入协议。**

---

# 6. PostgreSQL 搜索：按查询类型路由

当前计划不能把所有输入统一视为 trigram substring search。官方 `pg_trgm` 支持 `LIKE`/`ILIKE` 索引搜索，但效率取决于可提取 trigram 数量；无可提取 trigram 的 pattern 可能退化为全索引扫描。因此首先建立 Query Class：

| Query Class | 示例 | 优先候选 |
|---|---|---|
| **Exact ID** | accession / public_id 精确值 | B-tree equality |
| **Prefix** | `Glyma.01%` | B-tree/pattern ops 或 trigram，实测决定 |
| **Short** | 1–2 chars | 限制、提示补全或专门策略 |
| **Substring** | `%kinase%` | trigram |
| **Natural text** | 多词描述 | FTS / trigram 混合候选 |
| **Fuzzy typo** | 拼写误差 | trigram similarity |

## 6.1 Search Benchmark Matrix

至少含：`exact identifier` / `prefix` / `1-char` / `2-char` / `3-char` / `middle substring` / `common term` / `rare term` / `literal %` / `literal _` / `mixed case` / `multi-word` / `not found`。记录：query class / pattern / rows / selectivity / plan / estimated vs actual rows / buffers / execution time / result count。

## 6.2 索引验收

**禁止**把 `index scan = 成功` / `seq scan = 失败` 作为判据。高选择率/小表场景 Seq Scan 可能更合理。真正验收：planner estimation 合理、latency 达标、IO 可接受、写/存储无回归。

## 6.3 1–2 字符输入需要产品策略

对 short query 先决定：允许搜索？/ 最小长度？/ exact-only？/ prefix-only？/ autocomplete？**不要为了支持 1 字符 substring 强迫数据库走昂贵路径。**

---

# 7. 全局搜索 DB RTT

先 profile：`DB execution` / `network RTT` / `pool wait` / `serialization` / `ranking` / `JSON encoding` / `total endpoint latency`。只有 DB round trip 明显占比时才优化。候选：`A. UNION ALL` / `B. multiple queries + independent sessions` / `C. search projection/document` / `D. FTS + trigram`。

## 7.1 Cursor 契约补强

keyset cursor 必须有：deterministic sort / unique tie-breaker / cursor schema+version / release+assembly+site context / filter fingerprint。否则查询合并后可能产生重复页、漏项、跨 context cursor 复用。

---

# 8. `total_count` 与兼容性

先确认：OpenAPI 当前类型 / 前端是否依赖 number / generated client 类型 / 第三方 consumer。合法目标：`total_count: integer`（真总数）/ `total_count: null`（明确隐藏）/ `page_count: integer`（当前页）。禁止继续复用错误语义。但 `number → null` 可能是客户端 breaking change，因此需要：compatibility assessment / API version strategy / generated client update / frontend migration / contract test。

---

# 9. ClickHouse 导入幂等：控制面 + 数据面

## 9.1 先确认真实引擎与版本

```sql
SELECT version();
SHOW CREATE TABLE variant_facts;
```

若存在 staging，再 `SHOW CREATE TABLE <actual_staging_table>`——**不要保留不可直接执行的 `<staging>` 占位命令作为正式验收命令。** 确认：engine / replication / partition key / ORDER BY / materialized views / async insert / dedup settings / cluster topology。

## 9.2 Import Fingerprint

原版 `source_sha256 + release_id + assembly_id + importer_version` 还不够。建议：

```text
import_fingerprint =
  source_sha256 + release_id + assembly_id + importer_version
  + schema_version + normalization_version + semantic importer config hash
```

原则：**任何会改变输出事实的配置，都必须进入 fingerprint。** 文件名、上传时间等非语义字段通常不进入。

## 9.3 PostgreSQL manifest 作为控制面候选

控制面记录：`import_id` / `fingerprint` / `source_sha256` / `release_id` / `assembly_id` / `schema_version` / `importer_version` / `config_hash` / `status` / `expected_rows` / `written_rows` / `started_at` / `completed_at` / `failure_code`。状态机：`CREATED → PARSING → WRITING → VERIFYING → PUBLISHED ↘ FAILED`。必须定义：哪个状态对 portal 可见 / 谁负责恢复 / FAILED 是否可 retry / 旧 FAILED 如何清理。

## 9.4 ClickHouse dedup 不能作为唯一长期保证

MergeTree 系列支持 insert-level/block-level dedup 与 token，但导入协议仍不应只依赖服务器 dedup history（dedup window 有生命周期；MV/async insert 依版本配置而异；ReplacingMergeTree 后台合并是 eventual）。推荐：

```text
application manifest + deterministic batch_id + CH dedup token（辅助）
+ publish visibility rule + final row-count/checksum verification
```

而不是只靠 `insert_deduplication_token`。

## 9.5 ReplacingMergeTree 额外约束

若实际使用 ReplacingMergeTree：background merge 不代表即时唯一；普通 SELECT 可能暂时看到重复版本；若依赖 `FINAL`/`argMax`，必须纳入性能基线；ORDER BY key 必须与逻辑唯一键设计一致。

## 9.6 P2-3 硬约束：staging + base/MV 一致性 finalize

当前 `variant_facts` 公共读路径直接按 `release_key/assembly_key` 查询最终表，并不会自动查询 PostgreSQL `import_manifests`。因此：

- **禁止**实现“`WRITING` 时直接写最终 `variant_facts`，验证完成后才把 manifest 标为 `PUBLISHED`”的方案；这会让半写数据提前进入读路径。
- P2-3 第一版必须使用**不可被 portal 正常查询命中的 staging 数据面**；完成 row-count/checksum/schema/context 验证后才能 finalize。
- 若 `variant_facts` 存在增量 Materialized View / SummingMergeTree / AggregatingMergeTree 下游，**base table 与所有相关 MV target 必须作为一个一致性单元处理**。仅移动/替换 base partition 不足以证明 summary 正确。
- ClickHouse 增量 MV 按 source table 的新 INSERT block 触发；partition move/replace 不应被假设会重新触发原 MV。因此候选方案优先为：**base staging + 对应 MV staging/显式 summary rebuild + 验证 + coordinated finalize**。
- finalize 前必须枚举实际依赖：`system.tables` / `system.dependencies` / `SHOW CREATE TABLE`，不得按旧文档猜测 MV 数量和 target。
- 若无法证明 base + summary 的一致切换，则 P2-3 保持 fail-closed，**不得以“最终表数据看起来正确”作为 Gate-2 通过条件**。

## 9.7 VCF v1 发布边界：仅 draft release 可写

P2-3 第一版只允许向 **draft release** 导入/重建 VCF 数据：

- worker 在开始写数据前必须锁定并验证 release 状态；
- 非 draft release 一律 fail-closed；
- 不在本轮同时实现“已公开 release 的在线热替换/无停机数据切换”；
- `manifest=PUBLISHED` 表示该 logical import 已完成数据面 finalize，**不等于 release 已对公共门户发布**；release publication 仍由既有 release gate 控制。

这样把 import visibility 与 release visibility 分成两层，避免把 ClickHouse 的局部切换误当成完整发布事务。

## 9.8 Worker/API 边界：共享协议下沉，数据库所有权不混淆

当前 worker 明确采用窄 SQLAlchemy Core table definitions，避免依赖 API ORM。P2-3 不得为了复用 `import_manifest_service.py` 而让 worker 直接 import `apps/api`。

硬约束：

- **禁止** `apps/worker -> apps/api/app/*` 运行时依赖；
- fingerprint canonicalization、状态枚举、允许迁移等**纯协议**优先下沉到现有共享包（如 `packages/jobs-py`）；
- PostgreSQL manifest 的 ORM / Alembic migration 仍由 API 侧拥有；
- worker 只声明执行所需的窄 Core schema，并通过 PostgreSQL 持久化状态；
- API/worker 对状态机与 fingerprint 的一致性必须由 contract test 锁定，不能复制两套逐渐漂移的规则。

目标边界：

```text
packages/jobs-py     = import protocol / pure contract
apps/api             = schema + migration + control-plane owner
apps/worker          = parser / writer / finalize executor
PostgreSQL manifest  = durable control-plane source of truth
ClickHouse           = staged/finalized data plane
```

---

# 10. Import Retry / Crash Fixture：必须定义"期望结果"

不能只写"fixture 全绿"。

| Case | 期望 |
|---|---|
| same file + same release + same assembly + same semantic config | 不产生第二份逻辑事实 |
| same content + different filename | 与上条相同 |
| same file + different release | 创建独立 release 数据，不应误去重 |
| same file + different assembly | 独立数据或明确拒绝，按契约 |
| parser/config version changed | 由 fingerprint 决定是否允许重新导入 |
| crash before first batch | 可安全 retry |
| crash mid-write | portal 不可见 partial dataset；retry 后只有一份逻辑事实 |
| crash after data write before publish | recovery 能识别并完成/回滚逻辑发布 |
| ClickHouse timeout after ambiguous ACK | retry 不产生逻辑重复 |
| invalid record | fail-closed 或明确 partial policy |
| checksum mismatch | 不 publish |
| duplicate batch | 幂等 |
| row count mismatch | 不 publish |

---

# 11. `module_data_rows`：ADR 已决，执行 promotion 而不是继续争论角色

ADR-0004 已 Accepted：`module_data_rows` 是 **landing/staging**，不是门户 canonical read source；必须按 `module_key` 显式 promotion 到 `genes` 等 canonical 表。

## 11.1 P2-4 第一版范围

第一版只实现**有明确 schema 契约和 canonical target 的 module_key**。建议先完成一条 `genes` 链路：

```text
module TSV
  → strict validation
  → module_data_rows staging
  → promotion validation
  → genes canonical table
  → /genes public read path
```

未知/未映射的 `module_key` 必须 fail-closed；**禁止**设计“任意 JSON 自动映射任意数据库表”的通用 promotion engine。

## 11.2 Promotion contract 必须先写清

每个 `module_key` 至少声明：

- canonical target；
- natural/business key；
- release binding；
- assembly binding；
- chromosome/外键 resolution；
- insert/update/replace 语义；
- provenance / import identity；
- retry / partial failure 语义；
- staging retention 与 cleanup；
- schema evolution owner。

尤其 **assembly/chromosome 不允许猜测或从名称模糊推断**。缺少确定绑定时必须拒绝 promotion。

## 11.3 Promotion 原子性

promotion 必须满足：

- canonical write 与 promotion 状态可恢复；
- retry 不制造第二份 canonical logical fact；
- 失败时不能留下“部分 canonical 已可见但 staging 状态仍未完成”的不可判定状态；
- cleanup 只能发生在 canonical verification 完成之后；
- portal 始终继续读 canonical 表，不得为了省事临时改成直接读 `module_data_rows`。

---

# 12. Analytics：先定义耐久性等级

"Python bounded queue + batching"只有在事件允许有限丢失时才合适。先把事件分类：

| 等级 | 例子 | 允许丢失 | 推荐 |
|---|---|---|---|
| **A0 Best effort** | Web vitals | 是 | 内存队列 / async insert |
| **A1 Operational** | 搜索性能事件 | 少量可接受 | bounded queue + retry |
| **A2 Business critical** | 计费/审计/强业务指标 | 否 | durable queue / outbox |

> 如果 SoyMutDB analytics 只是产品使用分析，不要为了"零丢失"过度工程。

## 12.1 ClickHouse batching 指标

记录：`events/s` / `insert requests/s` / `rows/insert` / `bytes/insert` / `parts/s` / `active parts` / `merge queue` / CPU / memory / network / failure rate / queue depth / flush latency。若当前 ClickHouse 版本/部署支持且合适，可把 async inserts 纳入候选，而不是默认只在 Python 自己造批处理器。

---

# 13. 安全审计第二轮补强

## 13.1 控制存在 ≠ 控制正确

重新验证：password hashing params / JWT algorithm+issuer+audience+expiry / RBAC enforcement location / refresh+session revocation / CSRF origin+proxy assumptions / rate-limit key / rate-limit failure policy / CSP actual response / HSTS environment scope / sanitization call sites / secret handling。

## 13.2 fail-closed rate limit 需评估可用性

Redis 故障时 fail-closed：安全性更强，但可能把 Redis 故障扩大成 API 全站拒绝。按 endpoint threat model 定义：auth-sensitive endpoint → fail-closed 可能合理；public read endpoint → 是否需 degraded mode 需决策。**不得把"fail-closed"自动标记成成熟设计。**

## 13.3 Analytics 输入的数据最小化

除注入/高基数外，再检查：`search_query` 是否真的需要原文 / IP+user-agent+referrer retention / `session_id` 可否长期关联 / 日志与 analytics 是否重复保存敏感输入 / TTL+retention。

---

# 14. 性能基线：不是一个阶段只测一次

改成：**每个 domain 在第一次修改前必须有 baseline snapshot。**

- **Search**（改动前）：p50/p95/p99、query classes、EXPLAIN、DB RTT、pool wait。
- **Analytics**（batching 前）：events/s、insert calls/s、parts/s、merge pressure。
- **CI**（DAG 改动前）：median/p90/p95、queue time、job critical path、cache hit。
- **Import**（若当前路径不可执行）：不存在有效 before baseline → 明确记录"baseline starts only after correctness path is enabled"，**不要制造假对照。**

---

# 15. SLO：由需求定义，由基线验证

删除"SLO 由真实基线推导"，改为：

```text
SLO      = 用户/业务需求 + 预期峰值 + 成本约束 + 可靠性要求
baseline = 当前能力
benchmark = 验证新实现能否满足 SLO
```

如果当前没有业务 SLO：先定义 Service Target（Search p95 target / p99 guardrail / Import completion target / Max RSS / Peak concurrent users / Analytics max acceptable loss / CI developer feedback target），**需负责人确认，不能由 benchmark 自己生成。**

---

# 16. CI 优化

允许：dependency caching / build artifact reuse / DAG parallelization / matrix partition / change-aware execution / main+nightly expensive tests。但 change-aware execution 必须：有依赖映射 / 共享基础文件变化触发全量相关测试 / main 必跑完整关键门 / 定期 full suite。**禁止 path filter 造成"看起来快但漏测"。**

---

# 17. Rust：本轮 No-Go 范围，不使用"永久排除"

主路线保持：`correctness → data path → query/write shape → batching → capacity → optional runtime optimization`。

## 17.1 Rust PoC 前置（全部满足）

1. import path 已正确可执行；2. 目标 workload 有业务 SLO；3. Python baseline 存在；4. profile 证明 Python-owned CPU 是主要瓶颈；5. 当前 C/HTSlib/I/O 时间占比已拆清；6. CI 可构建 wheel；7. deployment target 可安装；8. 架构目标（amd64/arm64）明确；9. crate/native dependency 审计通过。

## 17.2 PoC 契约：100% 契约级一致性

比较：logical records / normalized fields / release+assembly binding / error category / contractually required error location / checksum+fingerprint / publish behavior。**不要求**内部对象结构相同、异常文本逐字相同、实现步骤相同。

## 17.3 本轮 No-Go

本轮不立项：`service/router rewrite` / `ORM rewrite` / `Celery/release-state-machine rewrite` / `Rust sidecar` / `microservice decomposition`。未来若要重开：新 workload evidence + 新 profile + 新 ADR + 新 cost model，**而不是"永久禁止"。**

---

# 18. 新路线图

```text
Phase 0  Fact Discovery
   ↓
Gate A   Contract / Architecture Decisions
   ↓
Phase 1  P0 Correctness & Isolation
   ↓
Phase 2  Import Protocol & Canonical Data Path
   ↓
Phase 3  Domain Baselines
   ↓
Phase 4  Targeted Optimization
   ↓
Phase 5  Capacity + Failure Validation
   ↓
Phase R  Optional Rust PoC
   ↓
Phase 6  Staging / Production Observation
```

## Gate A 必须完成的决策

至少：`ADR-DATA-01 module_data_rows role` / `ADR-DATA-02 import visibility+idempotency contract` / `ADR-API-01 total_count compatibility semantics` / `ADR-OPS-01 supported deployment architectures`。若已有正式契约，则引用现有 ADR，不重复造文档。

---

# 19. Phase Exit Criteria

- **Phase 0**：每个候选问题有 State + Evidence + locator + reproduction + owner + next action。
- **Phase 1**：P0 `S3/E2` merge-ready；negative tests green；no skip/xfail。准备发布时 `S4/E3`。
- **Phase 2**：证明 no partial visibility / retry idempotent / ambiguous ACK safe / fingerprint correct / canonical reader sees only finalized+published import；ClickHouse base 与全部增量 MV/summary target 一致；VCF v1 仅写 draft release；worker 不依赖 API package。
- **Phase 3**：每个即将优化的 domain 有可重复 baseline。
- **Phase 4**：每项优化有 before/after / same workload / same dataset / same environment class / confidence+repeat count / no correctness regression。
- **Phase 5**：至少 expected load / peak load / cold+warm / dependency failure / pool saturation / recovery。倍率如 `2x peak` 只能在容量目标明确后选，不写死。
- **Phase R**：结果只允许 `ADOPT` / `REJECT` / `DEFER(reason + explicit reopen condition)`；DEFER 不能写"继续观察"。
- **Phase 6**：达到 `E4` / `S5` 才真正关闭高风险项。

---

# 20. PR 强制模板（第二轮）

```markdown
## Requirement / Contract
## State before
- Lifecycle:
- Evidence:
## Scope
## Out of scope
## Reproduction / Baseline
## Root cause
## Decision / ADR
## Change
## Tests
## Contract compatibility
## Performance evidence
## Security / privacy impact
## Data migration / backfill impact
## Failure / recovery behavior
## Rollback or forward-fix
## Observability
## State after
- Lifecycle:
- Evidence:
## Remaining uncertainty
```

---

# 21. 第一批任务（重新排序）

```text
T0-1  Lock HEAD / branch / versions / topology
T0-2  Re-read current constraint docs
T0-3  Relocate D1–D8 by symbols, not historical paths
T0-4  Build issue register with State + Evidence
T0-5  Inspect PostgreSQL version/extensions/index definitions
T0-6  Inspect ClickHouse version + SHOW CREATE TABLE variant_facts
T0-7  Trace public_id/internal_id end-to-end
T0-8  Trace module_data_rows writers + readers + lifecycle
T0-9  Capture pre-change search/analytics/CI baselines where executable
T0-10 Build search query-class fixture
T0-11 Build import retry/crash/ambiguous-ACK fixture
T0-12 Build external/internal negative leakage suite
T0-13 Decide Gate A ADRs
```

已展开为可执行子计划：**`docs/superpowers/plans/2026-09-20-phase-0-fact-baseline-plan.md`**（W0）。
> 该文件内容本身在 Phase 0 执行、连库核验前，对其中每条结论仍应按 Evidence/State 重新定级，不得因"已写成文件"就当事实。

---

# 22. 第二轮审计后的优先级

| Priority | 内容 |
|---|---|
| **P0** | 身份/站点/release/assembly 契约违规 |
| **P0** | partial publish、重复事实、错误 context 数据 |
| **P0** | external/internal 数据泄漏 |
| **P1** | API 契约语义错误 |
| **P1** | 搜索/DB 执行路径 |
| **P1** | ClickHouse ingestion/parts 压力 |
| **P1** | analytics 成本与背压 |
| **P1** | observability / capacity evidence |
| **P2** | CI feedback time |
| **Optional** | Rust PoC |
| **Current-program No-Go** | 全面 Rust rewrite / 无证据微服务拆分 |

---

# 23. 最终 Definition of Done

本轮计划完成必须满足：

- 当前代码事实均有 E1+，不再引用 E0 当结论；
- P0 merge 至少 S3/E2；P0 release 至少 S4/E3；
- external/internal negative suite 全绿；
- import crash/retry/ambiguous ACK 全绿；
- no partial visibility；
- ClickHouse finalize 覆盖 base + 相关 MV/summary 一致性，禁止只替换 base partition 后宣称完成；
- VCF v1 仅允许 draft release 写入，已发布 release 热替换不在本轮范围；
- worker 不得新增对 API package 的运行时依赖；共享 import protocol 通过共享包/contract tests 保持一致；
- import fingerprint 覆盖全部语义变换输入；
- PostgreSQL 优化按 query class 验证；
- short query 有明确产品策略；
- ClickHouse dedup 不作为唯一长期 exactly-once 保证；
- analytics durability 等级已确定；
- SLO 来自业务/容量目标，而不是由当前慢速基线反推；
- 每个优化都有可重放 before/after；
- 没有用 skip/xfail 伪装通过；
- Rust 仅在 profile + SLO + deployment gate 全满足后评估；
- Rust 比较使用 contract-level equivalence；
- 当前 No-Go 项未来只能通过新证据 + 新 ADR 重开；
- staging/production 观察达到 E4/S5 后才关闭高风险项。

---

## 附录 A · 第二轮重点复核命令

```bash
# 代码与版本
git rev-parse HEAD; git branch --show-current; git status --short; git log -1 --oneline

# 重新按符号定位（不依赖旧路径）
git grep -n "module_data_rows"; git grep -n "UnsupportedImportError"
git grep -n "total_count";       git grep -n "gin_trgm_ops"
git grep -n "variant_facts";     git grep -n "record_event"
git grep -n "public_id";         git grep -n "internal_id"
```

PostgreSQL：

```sql
SELECT version();
SELECT extname, extversion FROM pg_extension WHERE extname IN ('pg_trgm','pg_stat_statements');
SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes WHERE indexdef ILIKE '%trgm%';
```

ClickHouse：

```sql
SELECT version();
SHOW CREATE TABLE variant_facts;
```

若定位到真实 staging 表名后，再执行其 `SHOW CREATE TABLE`，不要使用 `<staging>` 占位符直接运行。

---

## 附录 B · 外部技术复核结论

**PostgreSQL：** 当前官方文档明确 `pg_trgm` 的 GiST/GIN operator class 可用于 `LIKE`/`ILIKE`；pattern 能提取的 trigram 越多，索引通常越有效；无可提取 trigram 的 pattern 可能退化为 full-index scan。因此本计划不再把 `ILIKE` 或 `ESCAPE` 本身视为索引失效根因。

**ClickHouse：** MergeTree 家族支持 insert deduplication / dedup token；`ReplacingMergeTree` 的 replacement 依赖后台 merge，查询时可能仍存在多个版本；需要即时逻辑去重时可能依赖 `FINAL` 或其他 query pattern；ingestion 正确性不应只依赖一个有限生命周期的数据库 dedup 机制。因此 SoyMutDB 导入协议应优先采用 `application-level manifest + deterministic identity + database dedup assistance + explicit publish visibility + recovery verification`，而不是把数据库内部去重机制当作完整业务事务。

---

## 附录 C · 技能选择说明

| 技能 | 用途 | 落到本文 |
|---|---|---|
| `dev-expert` | 证据纪律、根因、威胁建模、生产就绪、反过度工程、Plan-Gate | 全篇；§1 双轨状态；§2 门禁分离；§13 威胁模型；§17 Go/No-Go |
| `systematic-debugging` | 先复现后修、失败测试转回归 | §3.4 Exit 的 reproduction；§10 fixture 期望结果 |
| `receiving-code-review` | 结论须可核验，不空泛贴标签 | §13.1 控制存在≠控制正确；§20 PR 模板 State before/after |

---

## 审计结语

第二轮后，这份计划坚持三个核心原则：

> **证据强度不等于修复状态。**
> **性能基线不等于业务 SLO。**
> **数据库提供的去重能力不等于完整的业务 exactly-once 协议。**

这样可以显著降低后续 agent 执行时"看到一个合理方案就直接实施"的概率，减少无证据重构、性能误优化和数据一致性事故。

---


---


# 24. 第四轮：UI/UX、研究工作流与功能深化

> **定位：** W-UI 是 Phase 2 的并行工作流，不取代数据正确性主线。可以先做信息架构、只读查询体验、组件契约和 E2E；任何依赖尚未通过 Gate-2 的写入/发布能力必须显示真实 capability 状态，禁止 UI 先行伪装“可用”。

## 24.1 官方设计与组件依据

本轮以以下官方资料为设计约束，而不是只参考截图：

- Ant Design 首页：<https://ant.design/index-cn>
- 设计原则：<https://ant.design/docs/spec/introduce-cn>
- React 使用：<https://ant.design/docs/react/introduce-cn>
- 组件总览：<https://ant.design/components/overview-cn/>
- 资源/生态：<https://ant.design/docs/resources-cn>
- Ant Design CLI：<https://ant.design/docs/react/cli-cn>
- Ant Design Pro v6 发布说明：<https://github.com/ant-design/ant-design-pro/issues/11734>

Ant Design 的“自然、确定性、意义感、成长性”落到 SoyMutDB 的具体要求：

1. **自然**：科研对象使用用户熟悉的 gene / mutant / variant / phenotype / genomic region 语言，不发明产品内部术语。
2. **确定性**：release、assembly、筛选条件、数据来源、加载/错误/空状态始终明确；禁止静默回退到 demo 数据。
3. **意义感**：每个页面围绕科研任务，而不是围绕数据库表；操作后即时反馈，并明确“下一步能做什么”。
4. **成长性**：复用 AntD token/component + SoyMutDB domain components；新增物种/数据类型时扩展 registry，不复制整套页面。

## 24.2 技术栈结论：不做无收益框架迁移

当前仓库已经具备 Ant Design Pro v6 强调的大部分现代基线：

- React 19.2；
- Ant Design 6.6.1；
- Tailwind CSS 4；
- TanStack Query；
- TanStack Router；
- Vite + route code splitting；
- Web 已启用 `defaultPreload: "intent"`；
- 全局 ConfigProvider、light/dark、i18n、reduced-motion 已存在。

因此本轮：

- **不迁移到 Umi Max，仅因为 Pro v6 使用 Umi；**
- **不全量引入 ProComponents，仅因为它存在；**
- **不为了构建工具宣传切换 utoopack/Turbopack；**
- **不重做现有 Router / Query / SSG 架构。**

任何此类迁移必须有独立 ADR + bundle/build/runtime benchmark + 回滚方案。

## 24.3 Ant Design 6 设计系统深化

### UI1-1 · CLI 驱动的版本准确审计

针对仓库固定的 AntD `6.6.1`，把官方 CLI 作为开发/审计辅助：

```bash
npx antd --version 6.6.1 doctor
npx antd --version 6.6.1 usage ./apps/web/src
npx antd --version 6.6.1 usage ./apps/admin/src
npx antd --version 6.6.1 lint ./apps/web/src
npx antd --version 6.6.1 lint ./apps/admin/src
```

若实际 CLI 参数与当前版本文档不一致，以 `npx antd --help` 为准，**禁止把示例命令本身当验收事实**。

用途：发现 deprecated API、直接导入、语义/组件误用；先报告，再按风险分批修，不把自动迁移当无审查写入器。

### UI1-2 · 评估 `cssVar` 模式，而不是盲目开启

当前 Web/Admin theme 已有动态主色、暗色和 motion contract，但 ConfigProvider 尚未把 `cssVar` 作为正式契约。

评估项：

- light/dark/custom Admin primary color；
- SSG → client handoff 是否闪烁；
- CSP / static artifact；
- 首屏 CSS 与运行时 style 数量；
- theme switch re-render；
- visual regression；
- bundle/runtime 指标。

只有全部通过才启用。AntD 6 `zeroRuntime` **本轮默认 No-Go**：动态主题、SSG/CSP 与构建静态抽取的收益需单独证明。

### UI1-3 · 表单风格按场景，而不是全站一刀切

Pro v6 使用 global filled variant 只作为参考。SoyMutDB：

- 公共检索：`outlined` / compact，强调参数可读性；
- Admin 数据录入/导入 wizard：可局部评估 `filled`，降低复杂表单视觉噪声；
- danger / warning / readonly 状态必须通过语义色 + 文本/图标共同表达，不能只靠颜色。

## 24.4 同类数据库得到的产品信息架构

### SoyBase 借鉴

SoyBase Fast Neutron Mutant 资源的有效模式是**多科研入口**，而不是单一“全局搜索”：按 mutant/sample、trait/phenotype、gene、locus/region、image、sequence/BLAST 等进入；trait 还支持条件组合和范围筛选。

SoyMutDB 应收敛为五条一级研究任务：

```text
Gene → Mutants → Variants → Genome context
Phenotype → Mutants → Gene/Variant evidence
Region → Variants → Mutants/Genes → JBrowse
Mutant → Phenotype + Variants + Genes + Provenance
Sequence → BLAST → Gene → Mutant/Variant
```

### MaizeGDB 借鉴

MaizeGDB 的 variation/mutant 信息强调 phenotype、stock/source、allele/variation 属性、gene/region 关联。SoyMutDB 不照搬视觉，而补齐：

- 可获取性/材料状态（若数据源真实提供）；
- provenance / source / publication；
- phenotype 与 genomic evidence 的双向跳转；
- mutation/variant 的上下文而非孤立 ID。

**硬约束：** 没有真实字段/来源时 UI 不创建“种子库存”“图片”“谱系”等虚构数据，只能先定义可选 schema/empty state。

## 24.5 公共站信息架构：从页面集合升级为研究工作流

### UI2-1 · 首页搜索升级为多实体 Omnibox

保留现有简洁 Hero，不增加大面积装饰动画。增强搜索框：

- AutoComplete 分组：Genes / Mutants / Variants / Phenotypes / Tools；
- exact ID 优先，再 prefix，再 general search；
- 每项显示 entity type + primary ID + 一条必要上下文；
- Enter 进入统一结果页，方向键/键盘可完整使用；
- 最近搜索仅本地、可清除；默认不存原始敏感查询到 analytics；
- 搜索 URL 可复制/分享。

首页一级入口保持“突变体 / 基因 / 变异”，增加清晰的“按表型浏览”入口；BLAST/JBrowse/Primer 属于工具，不与数据实体混为一层。

### UI2-2 · 统一搜索结果

统一 `/search` 不做一个无限大表，而采用 entity-grouped result：

- 顶部显示解析后的 query；
- tabs/segments：All / Genes / Mutants / Variants / Phenotypes；
- 每组显示真实命中数语义；无 true-total 时明确显示“本页/更多可用”，不伪造总数；
- URL 保存 entity/filter/sort/context；
- Empty state 说明“为什么为空”并给出恢复操作：清筛选、换 assembly、尝试 ID/prefix、转 BLAST。

## 24.6 Mutant Explorer：本轮公共 UI 的最高价值页

当前 `/mutants` 只有 mutagen 文本过滤 + 100 条列表，功能明显低于同类数据库。

### UI3-1 · 服务端筛选模型

逐项评估 API/schema 后支持：

- keyword / public_id / line name；
- cultivar；
- mutagen；
- generation；
- phenotype category；
- phenotype term / ontology term（数据存在才启用）；
- numeric phenotype range + unit；
- linked gene；
- linked variant / consequence；
- chromosome/region；
- image availability（有真实 image asset 才启用）；
- material/seed availability（有真实 inventory contract 才启用）。

必须服务端 pagination/filter/sort；**禁止把“拉 100 条到浏览器再过滤”扩展成正式方案**。

### UI3-2 · 双视图

- Desktop 默认 Table：适合比较；
- “Cards / Gallery”只在存在图像或丰富 phenotype summary 时启用；
- Mobile 优先 compact List/Card，不把 8–12 列表格硬塞进 390px；
- 筛选区 desktop 可用 sidebar / collapsible panel，mobile 用 Drawer；
- active filters 用可关闭 Tag，并提供 Reset all。

### UI3-3 · Mutant Detail

将当前“Descriptions + phenotype table + variants link”扩成任务化详情：

1. Overview：public_id、名称、species/cultivar、mutagen、generation、summary；
2. Phenotypes：trait/category/value/unit/method/source；
3. Variants：该 line 的变异摘要和高影响位点；
4. Affected genes：variant/deletion 与 gene 的证据链；
5. Genome context：JBrowse 深链/嵌入；
6. Provenance：source dataset、release、assembly、publication；
7. Downloads：当前 mutant 关联数据的 release-aware export。

可选 Image / Material availability 只有数据契约存在时出现。

页面标题必须同时显示**人类可读名称 + canonical public_id**，避免复制/引用时丢失身份。

## 24.7 Variant Explorer：从过滤表升级为可解释的变异研究台

当前 filters 只有 chromosome/type/impact/mutant_line，下一步按 API 支持扩展：

- region start/end；
- gene ID/symbol；
- consequence；
- allele frequency min/max；
- quality min；
- read depth min；
- filter status；
- mutant line；
- release + assembly context（全站统一）。

表格：

- Variant ID、Chr:Pos、Ref/Alt、Type、Impact、Consequence、Gene、AF、Quality；
- column visibility 允许用户控制；
- 保留关键 identity 列，不允许全部隐藏；
- cursor paging 继续用 `placeholderData` 防闪；
- sticky/header/横向滚动只在实际列宽需要时启用；
- 大数据依然使用 server-side filter/sort/paging；virtualization 只能优化已加载行，不代替后端分页。

新增 Variant Detail route 或 URL-addressable Drawer：

- canonical ID；
- Ref/Alt + position；
- consequence/impact；
- HGVS；
- AF / depth / quality / filter；
- linked mutant line；
- linked gene；
- “Open in JBrowse”；
- source release/assembly/provenance。

## 24.8 Phenotype Explorer：补齐同类数据库最重要的入口

新增 `/phenotypes` 前先确认真实 phenotype schema。

目标功能：

- category tree / ontology（若存在）；
- keyword；
- numeric range；
- unit；
- mutant count；
- phenotype → mutant list；
- image browse（有真实图像资产时）；
- 可把多个 trait criteria 组合成 AND/OR 查询时，必须先有明确 API contract，不能前端自行拼全量数据。

第一版可以只做 category + keyword + range，避免过度工程。

## 24.9 Gene / Mutant / Variant 三向联动

Gene Detail 在现有 Overview / Expression / Homologs 基础上增加：

- associated mutants；
- variant summary by impact/type；
- “View all variants for this gene”；
- “Open genomic interval in JBrowse”。

所有交叉链接保留 `release/assembly`，禁止跳转后悄悄回默认版本。

## 24.10 JBrowse 2 集成深化

不重做 genome browser；把 JBrowse 2 作为专业 genomic context。

- VariantTrack 按 consequence / impact / AF 提供可解释 colorBy；
- tooltip/detail 与 SoyMutDB gene/mutant/variant IDs 建双向链接；
- 若未来有 multi-sample genotype 数据，评估 sample genotype table / matrix；
- sample metadata（cultivar/phenotype）只有真实元数据时才用于分组/着色；
- 检查索引格式与最大 chromosome；只有实际需要时由 TBI 切 CSI；
- Web 侧深链必须显式携带 assembly + region，不能仅传 gene string 猜坐标。

## 24.11 可视化规范

ECharts / Cytoscape 统一遵循：

- chart 有文字 title/summary；
- ECharts 启用 ARIA 能力并评估 decal，不能只靠红绿区分；
- tooltip 中保留单位与样本量；
- zero-data 显示 Empty，不绘制“0 值看似有结果”的图；
- error 与 no-data 分开；
- 图下提供表格/下载或可访问替代；
- 高密度点图默认 progressive/采样策略需 benchmark，不能为了动画牺牲可读性。

## 24.12 Admin：把“一个大导入 Modal”升级为可恢复工作流

当前 imports 已有 capability、template、draft、preview、local/S3、task table，是良好基础；下一步不重写，而分层重构。

### UI5-1 · Import Wizard

使用 AntD `Steps` 表达真实协议：

```text
1 Source
→ 2 Bind context (dataset/release/assembly/module)
→ 3 Validate & Preview
→ 4 Ingest
→ 5 Verify
→ 6 Publish/Complete
```

状态必须来自后端 manifest/import task，不允许前端自创“完成”。

- local file 评估 `Upload.Dragger`，替代自制视觉壳；
- S3 URI 保持 Advanced；
- release/assembly 从可选实体选择，不让用户手输内部 ID，除非明确 Advanced 模式；
- validation issues 提供 row/field/category、可下载 diagnostics；
- preview 固定只读并标注截断行数；
- capability disabled 时展示原因 + 前置条件，不提供可点但必失败的主按钮。

### UI5-2 · Manifest 状态可视化

统一映射：

`CREATED → PARSING → WRITING → VERIFYING → PUBLISHED / FAILED`

每个状态显示：

- 当前动作；
- processed / expected；
- elapsed；
- last update；
- failure code；
- Safe retry 是否允许；
- 数据当前是否 portal-visible。

**禁止用“100% progress”代替 published/verified 语义。**

### UI5-3 · 失败与恢复

- 复杂操作失败使用 AntD `Result` + diagnostics link；
- retry 仅当后端声明安全；
- ambiguous ACK 场景 UI 显示“状态确认中”，不要立即建议重复提交；
- drafts 明确 server-backed，并显示 release/module/context；
- 发布前提供 summary/diff/provenance/checksum review。

### UI5-4 · Admin 帮助降噪

当前全局 `AdminUsageGuide` 信息量过大。评估改成：

- 首次进入可选 Tour；
- Header Help / Drawer 按当前路由提供 context help；
- 高风险动作附近保留短说明；
- 长篇 workflow 不默认占据每页首屏。

## 24.13 Loading / Empty / Error / Success 状态契约

AntD 组件按语义统一：

| 状态 | 首选 |
|---|---|
| 首次加载且布局可预测 | Skeleton |
| 翻页/筛选保持旧数据 | Query placeholderData + subtle fetching indicator |
| 无数据 | Empty + 原因 + recovery action |
| 局部可恢复错误 | Alert |
| 整页/复杂动作结果 | Result |
| 首次功能引导 | Tour |
| 多步骤操作 | Steps |

禁止：

- loading 直接清空整页；
- error 冒充 empty；
- disabled capability 冒充 error；
- Empty 只有“暂无数据”没有下一步。

## 24.14 Responsive 与可访问性

- 390px / 768–1024 / 1440px 三类 viewport 作为固定验收；
- 保留现有 skip-link、focus-visible、reduced-motion；
- click/touch target 不小于既有 design-system contract；
- icon-only button 必须有 accessible name；
- Table 在移动端应降维展示，不以横向滚动作为唯一方案；
- 颜色不是状态唯一编码；
- keyboard 能完成 search → filter → open detail → back；
- JBrowse iframe/嵌入必须有可理解 title 与外部打开替代。

## 24.15 性能策略：保持已有优势，按证据优化

仓库 Web 已有 `defaultPreload: "intent"`，所以本轮不是“新增路由预取”，而是核验：

- 高频链路（search → gene/mutant/variant detail）是否同时预取必要 query；
- preload 是否错误带入大 chart/JBrowse chunk；
- hover prefetch 的网络成本；
- `staleTime` 与 release-aware queryKey；
- 返回列表时是否保留 filter/scroll/data。

仅在 profile 证明渲染瓶颈时使用 virtualization / transition/deferred；不要提前把所有表格虚拟化。

## 24.16 W-UI 执行顺序

```text
UI0  inventory + task-flow baseline + AntD CLI audit
 ↓
UI1  design-system contract (cssVar evaluation, state patterns)
 ↓
UI2  public IA + omnibox + shareable search state
 ↓
UI3  Mutant / Variant / Phenotype explorers
 ↓
UI4  Gene cross-links + JBrowse + visualization accessibility
 ↓
UI5  Admin import wizard + manifest/recovery UX
 ↓
UI6  responsive/a11y/performance pass
 ↓
UI7  E2E task acceptance + staging observation
```

可与 P2 并行：

- UI0/UI1/UI2 的只读设计与测试；
- UI3 中已有 API 能力的 Mutant/Gene 页面；
- UI6 的无业务语义改动。

必须等待对应数据 Gate：

- VCF durable import UI 的“启用” → P2-3/P2-5/P2-6；
- canonical module promotion 可见性 → P2-4；
- phenotype/image/material inventory → 对应真实 schema/data；
- multi-sample JBrowse matrix → 真实 genotype dataset。

## 24.17 用户任务级 E2E，而不是页面截图级“看起来不错”

至少固定 7 条主任务：

1. Gene ID → gene detail → associated mutant → variants → JBrowse；
2. Phenotype → mutant list → mutant detail → genomic evidence；
3. Region → variants → variant detail → JBrowse；
4. Mutant public_id → phenotype + affected genes + export；
5. Sequence → BLAST → gene → mutant/variant；
6. Admin local file → bind context → validate → preview → submit → verify；
7. Admin failed import → diagnostics → safe retry / blocked retry。

每条验收：

- 关键 context 不丢失；
- URL 可复制并恢复核心筛选；
- loading/error/empty 明确；
- keyboard 可完成核心路径；
- 390 / 1024 / 1440 至少一次；
- 不出现 demo fallback 假装真实数据；
- disabled capability 不能进入“看似成功”的下一步。

## 24.18 UI/UX Definition of Done

- 研究入口围绕 gene/mutant/variant/phenotype/region/sequence，而不是内部表名；
- Mutant Explorer 不再只有 mutagen 单筛选 + 固定 100 条；
- Variant Explorer 有 URL-addressable detail 与 genomic context；
- Phenotype 至少有真实 schema 驱动的 browse/search 入口；
- Gene/Mutant/Variant 三向跳转保留 release + assembly；
- JBrowse 深链可复现；
- Admin import 是可恢复步骤流，不是“大 Modal + 一次提交”；
- capability gating 与真实后端一致；
- Skeleton/Empty/Alert/Result/Steps 语义统一；
- chart 有 accessibility contract；
- mobile 不以桌面大表硬缩放作为主要体验；
- `cssVar` 是否启用有 benchmark/visual evidence，不靠版本潮流决定；
- ProComponents/Umi/utoopack 不因“官方模板在用”而进入仓库；
- UI7 主任务 E2E 全绿后，才把本轮 UI 高风险项标 S4/E3。

---

## 附录 D · 第四轮 UI/UX 外部参考摘要

### Ant Design / Pro

- Ant Design 官方原则用于约束语义、反馈、复用与信息层级。
- Ant Design Pro v6 的 `cssVar`、React Query、route prefetch、Skeleton 等作为**模式参考**；本仓库已具备 React 19 / AntD 6 / Tailwind 4 / Query / intent preload，因此不复制其框架栈。
- 官方 CLI 用于版本准确的 API/usage/lint 复核。

### 同类数据库

- **SoyBase Fast Neutron Mutants**：借鉴其 sample/trait/gene/locus/image/BLAST 多入口、trait 条件筛选和 phenotype-first discovery。
- **MaizeGDB**：借鉴其 variation ↔ phenotype ↔ stock/source ↔ gene/region 的证据联动。
- 只借鉴科研任务模型与信息架构；SoyMutDB 的字段、可用性、图像、材料状态必须来自自身真实数据契约。

## 附 · 执行状态真源与下一步路线图（2026-09-21）

> **本章是当前唯一的执行状态真源。**
> 上游章节保留审计原则与长期路线图；若上游描述与本章当前状态冲突，以本章、Accepted ADR、当前 `main` 代码和可重复测试证据为准。

### A. 当前仓库基线

- **目标分支：** `main`
- **基线提交：** `29b416af58d42754aa9c4cfdaa413d0c58f22ba0` — `docs(plan): harden Phase 2 staging and finalize constraints`
- **PR：** 当前未检索到 open/closed PR；不得把“无 PR”解释成“无开发历史”。
- **开发分支：**
  - `codex/fix-compose-preview-data-layer`：ahead 0 / behind 7，当前无独立待合并提交；
  - `feature/upgrade-antd-mcp-mcp`：ahead 0 / behind 185，视为陈旧分支，不作为新开发基线；
  - `gh-pages` / `pages`：与 `main` 无共同祖先，按发布分支隔离，不参与 Phase 2 开发。
- **新工作必须从当前 `main` 创建分支**；禁止从上述陈旧开发分支续写 Phase 2。

### B. 已完成（含证据）

- **环境**：mamba `postgres16` (PG 16.15) + `node24` (24.19.0) + `apps/api/.venv`。
- **Phase 0**：D1–D8 实测分级；D8 mutant public identity 已核实合规；PG/CH DDL 事实已解析。
- **Gate A**：
  - ADR-0004：`module_data_rows` = staging + explicit promotion；
  - ADR-0005：PG manifest + semantic fingerprint + explicit publish visibility；
  - ADR-0006：`total_count` 语义拆分；
  - ADR-0007：deployment architecture。
- **Phase 1**：
  - P1-2：禁用导入类型 API 422 capability closure，9 tests；
  - P1-3：identity/assembly matrix，69 tests；
  - P1-1：node gate 与 isolation checker 已过，完整 artifact/full-stack 证据仍待补。
- **Phase 2 P2-1/P2-2**：
  - migration `0037` + `ImportManifest`；
  - semantic fingerprint；
  - `start_or_resume` 幂等；
  - guarded FSM；
  - `FAILED → CREATED` retry；
  - manifest 层仅 `PUBLISHED` 可见规则；
  - 共 16 tests 绿。

关键提交：`5b103aa 346c772 3f080cb d7b8c9d 64c5a1b cd63a24 25348e16`。

### C. 新发现的 P2-3 correctness gap

当前 `ClickHouseService` 的门户查询直接读取 `variant_facts`，按 release/assembly 等字段过滤，**并不会因为 PostgreSQL manifest 尚未 PUBLISHED 自动屏蔽已经写入最终表的数据**。

因此原“manifest + 直接写 final table + 最后标 PUBLISHED”的实现顺序不足以证明 no-partial-visibility。

同时，`variant_facts` 的增量 Materialized View / summary 若存在，partition move/replace 不会被假设自动重放原 source INSERT 触发逻辑。**P2-3 必须把 base 与相关 MV target/summary 作为一个数据一致性单元。**

这两条均为 **P0 数据正确性硬约束**，高于性能优化和功能重开。

### D. Phase 2 执行顺序

```text
P2-3A  import protocol seam / worker boundary
   ↓
P2-3B  enumerate CH base + MV dependencies; staging/finalize design
   ↓
P2-3C  VCF writer → staging only
   ↓
P2-3D  row-count/checksum/context/schema verification
   ↓
P2-3E  coordinated base + summary finalize
   ├─────────────────────┐
   ↓                     ↓
P2-5 failure fixtures   P2-4A promotion contract
                         ↓
                       P2-4B genes first promotion
   └──────────┬──────────┘
              ↓
           Gate-2
              ↓
        P2-6 capability reopen
              ↓
       P1 full-stack E2E
              ↓
           Phase 3
```

### E. P2-3A · 共享 import protocol + worker seam

**目标：** 连接已经完成的 PG manifest 与 worker 执行路径，但不破坏 worker/API 分层。

**必须做：**

1. 把 fingerprint canonicalization、状态枚举/转换规则等纯协议抽到现有共享 package；优先复用 `packages/jobs-py`。
2. API ORM/Alembic 继续拥有 `import_manifests` schema。
3. worker `tables.py` 增加执行需要的窄 manifest Core definition。
4. worker 通过 PG 更新 manifest，不 import `apps/api/app/*`。
5. 加 contract tests，证明 API 与 worker 使用同一 fingerprint/status 语义。

**禁止：**

- worker 直接 import `app.services.import_manifest_service`；
- 复制第二套 fingerprint 实现；
- 为了“代码复用”把 API ORM 带进 worker image。

**Exit：** worker/API dependency boundary 不退化；同一语义输入在 API/worker 得到完全相同 fingerprint 与状态规则。

### F. P2-3B · ClickHouse staging/finalize 设计

先对真实实例/DDL 枚举：

```sql
SELECT version();
SHOW CREATE TABLE variant_facts;
-- 再枚举与 variant_facts 相关的 materialized views / target tables / partition keys
```

设计必须回答：

- staging base table 的 schema/partition/order；
- 相关 MV 是否需要 staging clone 或显式 summary rebuild；
- finalize 的最小一致性单元；
- retry 时如何定位并清理某一 `import_id` 的 staging 数据；
- release/chromosome partition 冲突策略；
- ambiguous ACK 后如何判定“写成功但客户端没收到响应”；
- finalize 中途失败如何恢复；
- finalize 前后各自允许 portal 看见什么。

**硬约束：** 未获得真实 CH 证据前，不把某个具体 `REPLACE PARTITION` 命令写成唯一既定实现。

### G. P2-3C/D/E · VCF durable writer

VCF v1：

1. 校验 release 存在且状态为 **draft**；
2. 计算 semantic fingerprint，`start_or_resume`；
3. `CREATED → PARSING`；
4. parse/normalize，稳定 logical identity；
5. `PARSING → WRITING`；
6. **仅写 staging**，batch identity deterministic；
7. `WRITING → VERIFYING`；
8. 校验 expected/written rows、checksum、release、assembly、schema；
9. coordinated finalize：base + 相关 summary/MV target；
10. finalize 后再次核对 canonical counts/checksum；
11. 仅全部成功后 `VERIFYING → PUBLISHED`；
12. 任一失败进入 `FAILED`，portal 不得看到 partial dataset。

**不在 v1 范围：** 已发布 release 的在线热替换、跨 release 原子交换、多集群复制切换。

### H. P2-4A/B · canonical promotion

先写显式 mapping contract，再编码。

第一条只做 `genes`（若当前 module schema 名称不同，以实际 registry 为准）：

```text
module_data_rows
  → validate mapping/context
  → resolve assembly + chromosome
  → idempotent canonical upsert/replace
  → verify
  → mark promotion complete
  → cleanup/retention
  → /genes read proof
```

必须先定义：

`module_key → target → business key → assembly binding → chromosome resolution → retry → provenance → retention`。

未知 module_key 继续 fail-closed。

### I. P2-5 · 故障夹具

以下 case 必须逐条有断言，不接受“整体测试绿”代替：

| Case | 必须证明 |
|---|---|
| same content + same semantic context | 不产生第二份 logical facts |
| same content + different filename | 仍视为同 logical import |
| different release | 独立数据 |
| different assembly | 独立或明确拒绝 |
| parser/schema/config version changed | fingerprint 按契约变化 |
| crash before first batch | 可 retry |
| crash mid-write | final/public read 不可见 partial |
| crash after staging write before finalize | recovery 可继续或清理重来 |
| crash during finalize | base/summary 不得留下不可判定分裂状态 |
| ambiguous ClickHouse ACK | retry 无逻辑重复 |
| duplicate batch | 幂等 |
| checksum mismatch | 不 publish |
| row-count mismatch | 不 publish |
| invalid record | fail-closed 或按明确 partial policy |
| retry from FAILED | 同 manifest logical identity 下安全恢复 |

### J. P2-6 · 能力重开门

只有 P2-1~P2-5 全部满足 Gate-2 后才允许重开。

第一批最多只考虑 **VCF**：

- VCF writer + fixture + E2E 都有证据 → 可单独评审是否把 VCF flag 置 true；
- FASTA/GFF3/BLAST/seed/expression/homolog 等仍按各自 writer/protocol 完成度保持 false；
- **禁止“一次性把七个 flag 全开”**。

### K. P1 full-stack 补证据

与 Phase 2 可并行准备环境，但不得冒充已完成：

- running API；
- seeded release；
- unpublished sentinel；
- external/internal negative E2E；
- E2E-01/02；
- ID-05 artifact evidence；
- UI-02。

### L. 后续阶段门禁

**Phase 3** 仅在生产量级 seed 可用后开始：search p50/p95/p99 + EXPLAIN；analytics ingest/parts；CI critical path。

**Phase 4** 只能优化已有 baseline 的 domain：trigram、exact-ID `upper()`、3 RTT、COUNT、analytics batching、`total_count` compatibility。

**Phase R** 继续保持 Optional/No-Go：没有 SLO + profile 证明 Python-owned CPU 瓶颈，不启动 Rust PoC。

### M. 当前下一步

**数据主线第一优先级：P2-3A。**

完成共享 import protocol 与 worker manifest seam 后，再进入 P2-3B 的真实 ClickHouse staging/MV 设计。与此同时可独立起草 P2-4A mapping contract，但 **P2-4B canonical writer 不应抢在 contract review 前实现**。

### N. W-UI 并行工作流

UI/UX 不阻塞 P2-3A，但必须服从 capability/data gate：

1. **立即可做：** UI0 AntD CLI/组件/路由审计、UI1 design-system contract、UI2 信息架构/搜索状态、现有 Mutant/Gene 只读页面改造。
2. **条件可做：** Variant detail/JBrowse 联动仅使用当前已发布数据能力；缺失字段保持 unavailable/empty，不造 mock production facts。
3. **需等待：** VCF import enable、canonical promotion、phenotype/image/material 高级筛选、multi-sample genotype UI 等，分别等待 P2/真实 schema。
4. UI PR 不得绕过 P2 capability flags，不得通过前端隐藏错误把未实现后端伪装成完成。

---

## 第四轮执行结语

当前项目的下一阶段不是“把禁用的导入函数解开”，而是把 **control plane、staging data plane、finalize、canonical promotion、failure recovery** 组成一条可证明正确的发布协议。

本轮数据正确性四条最高优先级硬约束继续不变，同时增加一条 UI 硬约束：

> **WRITING 数据不得直接进入 portal 正常读取的最终数据面。**
>
> **ClickHouse base 与增量 MV/summary 必须作为一致性单元验证和 finalize。**
>
> **VCF v1 只写 draft release，不在本轮做已发布数据热替换。**
>
> **worker 不依赖 API package；共享的是协议，不是 ORM/服务实现。**
>
> **UI 不得提前承诺后端尚未通过 Gate 的能力；所有“可用”状态必须来自真实 capability/data contract。**
