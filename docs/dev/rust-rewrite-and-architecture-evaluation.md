# 架构优化与 Rust 重写评估方案

> 类型：架构评估 + 方案设计（Design Proposal），**不是实施授权**
> 日期：2026-09-11
> 发起：Issue #2「架构优化探索」
> 代码基线：`cc8792a`（`main`）
> 上游约束：`AGENTS.md`、`docs/dev/database-core-contract.md`、`docs/dev/pi-agent-hard-constraints.md` H01–H12、
> `docs/design/full-stack-upgrade-2026-08.md`（"No microservice decomposition without measured need"）

---

## §0 一句话结论

**当前 SoyMutDB 的瓶颈不是语言，而是"IO/算法路径没做对"：**

1. 公共搜索仍是**低效的 `ILIKE '%q%'` 三连查**（迁移 0024/0027 已建 **9 个**单列 trigram 索引，但 `ESCAPE` 与多列 `OR` 使索引难以被利用）；
2. 导入链路是**"伪流式"**——整文件进内存、内存 `set` 去重；
3. **CI 才是当前最贵的"性能问题"**：8 个 job 串成 `dependency-governance → docker-build(×2 arch) → kubernetes-kind` 关键路径，
   任何 PR 都要等全链路。

**Rust 重写的结论是分层的、有条件的，且其中一条在复核中被推翻：**

| 候选 | 结论 | 依据 |
| --- | --- | --- |
| 全量重写 API/worker | ❌ **明确否决** | 与已批准架构决策冲突；41 service / 48 router / 35 迁移 / 36k 行 Python 测试重写成本不可回收 |
| **全量重写计算内核**（旧 `core-rs` 类型） | ❌ **否决（结构理由）** | 本项目 99% 的 CPU 已在 C/Fortran 里：`cyvcf2`(HTSlib)、`pysam`、`numpy/OpenBLAS`、`scipy`、`polars`(本身即 Rust)、外部 `blastn`/`fastp` 二进制。重写它们只是"换壳"，不产生新算力 |
| ~~单点：`noodles` 流式 VCF 摄取内核~~ | ⚠️ **原推荐已被复核推翻**（详见 §3.4） | 经典导入链路（含 VCF）**当前整体 fail-closed**，路径根本不执行 → **无可测收益**。真正的阻塞是"写入器 + 幂等协议未实现"，属架构问题而非语言问题 |
| **Rust sidecar 进程** | ❌ 排除中间态 | 双运行时/双镜像/双供应链，成本高于收益；若确需 Rust，用 **PyO3 + maturin 原生扩展** |
| `pingora` 类 Rust 网关替代 nginx | ⚠️ **先 ADR，暂不动** | 边际收益需真实 QPS 压测证据；**nginx `proxy_cache` 尚未启用**，先做那个 |

**因此本次评估的净结论是：当前不存在值得立项的 Rust 重写点。**

最先该做的三件事（与语言无关）：

1. **搜索执行计划收口** —— 9 个 trigram 索引已建，但需 `EXPLAIN` 实测是否真被使用；
2. **导入写入器闭环** —— staging/幂等/finalize，这是解锁一切真实数据的前提；
3. **CI 关键路径压缩** —— 当前最贵的"性能问题"，优化后全团队受益。

Rust 应排在这三项**全部完成之后**，并须重新评估当时是否有真实基准支持。

---

## §1 现状事实基线（本次实测，2026-09-11）

### 1.1 代码规模

| 区域 | 规模 | 备注 |
| --- | --- | --- |
| `apps/api/app` | 40,896 行 / 48 router + 41 service + 25 model | 模块化单体 |
| `apps/worker/src` | 9,832 行 | Celery 多队列 |
| `apps/api/tests` + `apps/worker/tests` | 29,641 + 6,673 行 | **测试是重写时最大的沉没成本** |
| `apps/web` / `apps/admin` / `apps/jbrowse` | 25,962 / 19,826 / 1,622 行 | React 19 + Vite 6 |
| `packages/*` | 24,760 行 | `api-client` / `shared` / `i18n` / `jobs-py` / `motion` |
| Alembic 迁移 | 35 个版本 | PostgreSQL 权威 schema |
| E2E | 13 个 Playwright spec | |

Python 总代码约为 TS 的 1.7 倍；**若把测试计入，重写 Python 侧的体量约为 77k 行**。

### 1.2 已具备的工程底座（**不要重造**）

`docs/dev/platform-optimization-plan.md` §1.1 已盘点十项后端成熟实践：统一异常体系、service 层无环、
keyset 分页、插件签名 fail-closed、OpenAPI→client 契约链路、`core/features.py` 特性开关、审计日志、
Redis Lua 限流（fail-closed）。本次复核确认这些结论成立，**任何"引入统一错误处理/重建分层"的提案在这里都是倒退**。

### 1.3 真正的问题清单（按证据分级）

| # | 问题 | 证据（文件:行） | 严重度 |
| --- | --- | --- | --- |
| **P-1** | 公共搜索 3 次串行 `ILIKE '%q%'`，trigram 索引覆盖不全且被 `escape="\\"` 绕过 | `services/search_service.py:249-251/363/417-420/581-583`；`migrations/versions/0024/0027` | 高 |
| **P-2** | `list_genes` 在 page 模式走 `COUNT(*) subquery` | `services/gene_service.py:121-124` | 中 |
| ~~P-3~~ | ~~`resolve_release_context` 每请求一次 DB 查询~~ | **已消除**：`release_context.py:73` 已有 `@cached('release-context', ttl=60)` | 已修 |
| **P-4** | 导入"伪流式"：worker 整文件读入内存；`DelimitedTextReader` 用 `io.StringIO(text)`；`seen_keys: set` 无界增长；XLSX ZIP 整体读入 | `docs/research/2026-08-17-...audit.md` §2.2 | 高 |
| ~~P-5~~ | ~~每请求一次 `SELECT` 取 active release~~ | **已消除**：同 P-3，60s 缓存已就位 | 已修 |
| **P-6** | ClickHouse 埋点**每事件一行 INSERT** | `performance-optimization-plan.md` §1 | 中 |
| **P-7** | CI 关键路径过长：`docker-build` 串行依赖 `frontend`/`api-tests`/`dependency-governance`/`clickhouse-migration`/`mcp-e2e` 五个 job，且 amd64/arm64 双跑 4 个镜像并各自 Trivy + SBOM；`kubernetes-kind`（装 kind 集群）再串在其后 | `.github/workflows/ci.yml:362-367`、`:636` | **高（当前最痛）** |
| **P-8** | `pydantic v2` 模型逐行构造是导入热路径的主要 CPU 开销 | `worker/tasks/ingest.py` | 中（待基准） |

> 说明（避免把假设当结论）：P-1 的 `escape="\\"` **可能**使 PostgreSQL 无法利用 `gin_trgm_ops`
> （转义后的 pattern 与索引项不匹配），但这是**待实测假设，本文档不声称已确认**。
> 唯一可信的判据是 `EXPLAIN (ANALYZE, BUFFERS)` 是否显示 index scan —— 属 Phase R0 第一项。

---

## §2 架构优化的三个方向（不涉及语言重写）

### 2.1 方向一：搜索执行路径收口（预期收益最大/成本最低）

**目标契约（不改 API 形状）**：`GET /api/v1/search` 的 p95 从"秒级"降到 **< 150 ms**（沿用 v2.0 目标）。

**动作**

1. **实测优先**：对 `search_service` 三条查询分别跑 `EXPLAIN (ANALYZE, BUFFERS)`，产出基线报告
   （复用已有 `Makefile` 的 `explain-query` 与 `slow-query-report`，及迁移 `0025_pg_stat_statements`）。
2. **建 expression index**：把 `ILIKE` 从 `escape("\")` 改回可利用索引的形式，并补充 `lower()` 表达式索引：
   ```sql
   CREATE INDEX CONCURRENTLY ix_genes_search_trgm
     ON genes USING gin (lower(accession || ' ' || coalesce(name,'') || ' ' || coalesce(description,'')) gin_trgm_ops);
   ```
   `escape` 仅在 pattern 含 `%`/`_` 时才需要；应改为**只在用户输入真的包含通配符时转义**，其余走索引路径。
3. **统一候选集**：三条查询（gene/mutant/publication）合并为一次 `UNION ALL` + 统一打分，
   避免 3 次串行往返；每类 `LIMIT` 已存在，改造成本可控。
4. **`total_count` 语义**：`services/search_service.py:167` 返回 `total_count=len(hits)`（**页内计数**）
   且 `schemas/search.py:98/135` 默认 `0`（非 `null`），而契约规定 `total_count=null` 表示"隐藏总数"。
   建议：显式返回 `null`，或新增 `page_count` 字段并保持 `total_count` 语义纯净。
   **属契约澄清，需前端同步 + OpenAPI 重新生成**，不可只改后端。
5. **release 上下文缓存 —— 已完成，无需再做**：`release_context.py:73` 的 `@cached('release-context', ttl=60)`
   已实现（含 `cache_decorator.py` 的 key 参数校验）。**仅需补验证**：发布/回滚后 60s 内
   读到旧 release 的窗口是否可接受；若不可接受，在 `release_service` 内加显式失效。

**验收**：`ID/CTX/ASM` 矩阵测试全绿（不得 skip）；`EXPLAIN` 输出显示走 index scan；p95 基准 ≤150 ms。

### 2.2 方向二：导入写入器闭环（**最高优先级的前置项**）

> ⚠️ **重要更正**：本节初稿把导入问题描述为"伪流式性能问题"。
> 复核后确认**真正的阻塞是"没有写入器"**：经典科研导入链路整体 fail-closed
> （`worker/tasks/data_adapters.py:125,135,148,158,171`），`import_vcf` 第一行即抛错（`ingest.py:446-450`）。
> 性能优化在这一路径上**没有任何意义，因为它根本不执行**。详见 §3.4。

**现状（代码事实）**

| 导入类型 | 状态 |
| --- | --- |
| `module_tsv` | ✅ 唯一真正持久化；流式校验 + 分块 UPSERT 到 `module_data_rows` |
| fasta / gff3 / vcf / blast_db / seed_data / expression_csv / homolog_csv | ❌ `UnsupportedImportError`，特性开关默认 `false` |
| `module_data_rows` | ⚠️ **write-only：全仓库无读取者**（`docs/ops/first-release-data-plan.md` §5.2） |

**真实待办（按依赖顺序）**

1. **解除 fail-closed**：设计 staging 表 + 唯一约束 + 单事务 finalize，使重试幂等
   （`MergeTree` 无去重，这是 `import_vcf` 被禁的根因）。
2. **canonical schema 对齐**：`infra/clickhouse/upgrade_variant_facts_schema.sql`
   与 `clickhouse_service.py` 的 `SELECT` 字段必须一致。
3. **消费端闭环**：`module_data_rows` 要么补读取者（回填 `genes` 等门户读取表），要么删表。
   **门户 `/genes` 读的是 `genes` 表，而导入只写 `module_data_rows`——两者当前不连通。**
4. **能力收口**：7 个未实现类型补 API 侧 422 + Admin UI 隐藏（开关已在 `features.py:43-70`）。

**流式化（次要项，待写入器就位后再做）**：整文件 `bytes` → 内存解码 → 内存 `set` 去重 → XLSX ZIP 全量读入。

**目标形态**

```text
S3 GetObject stream / 本地 file handle
   → 增量哈希（服务端算 SHA-256，前端不再 arrayBuffer 全读）
   → 流式 reader（文本: TextIOWrapper+csv / XLSX: 临时文件+openpyxl read_only / VCF: bgzf 流）
   → staging 表唯一约束去重（替代内存 set）
   → COPY / 批量 INSERT
   → 单事务 finalize + outbox
```

**分步**：先做上述 1–4（架构与幂等协议，**纯 Python 可完成**），
再做流式化（S3 流接口、staging 唯一约束、XLSX 落临时文件）。
Rust 的介入点仅在最后一步，且须先满足 §3.4.1 的三条先决条件。

### 2.3 方向三：CI 关键路径压缩（当前投入产出比最高）

**问题**：`docker-build` 的 `needs` 含 `dependency-governance` 与 `clickhouse-migration`，且 amd64/arm64 各建 4 个镜像
再做 Trivy + SBOM；`kubernetes-kind` 又串在 `docker-build` 之后，并额外安装 kind 集群。

**动作**

1. `dependency-governance` / `clickhouse-migration` **移出** `docker-build` 的 `needs`（它们与镜像构建无数据依赖）。
2. PR 上只跑 **`linux/amd64`**；`arm64` 与 `kubernetes-kind` 仅在 `main` 或 `workflow_dispatch` 跑。
3. 镜像**分层缓存**（`docker/build-push-action` + `type=gha`），Python 依赖层单独缓存。
4. `mcp-e2e` 目前未进入 `docker-build.needs`，需确认它是否真的在跑（`:1102`）——避免"声明依赖但无实际门禁"。

**验收**：以 `cnb pulls get-ci-timing` / GitHub Actions 的 job 时长为准，PR 关键路径目标 **≤ 15 min**。

---

## §3 Rust 重写评估

### 3.1 否决"全量重写"的结构性理由（不是偏好）

1. **已批准的架构决策明确禁止**：`docs/design/full-stack-upgrade-2026-08.md` 非目标条款：
   "No microservice decomposition without measured need"；`apps/core-rs` 的最终处置是
   "benchmark-gated with a unique role **or removed**"，仓库实际选择了**移除**（`docs/dev/architecture-and-deployment.md` §清理范围）。
2. **`docs/aegis/.../10-intent.md` 写明 Non-goals：No Tauri/Rust/Go integration into this monorepo.**
   任何 Rust 引入都需要**先修订这条约束并形成独立 ADR**，不能由单次任务默认放开。
3. **算力已在 C/Fortran 中**：`cyvcf2`(HTSlib) / `pysam` / `numpy`(OpenBLAS) / `scipy` / `polars`(本身即 Rust) /
   外部 `blastn`、`fastp` 二进制。把 Python 外壳换成 Rust 外壳，**不会把这些算法加速**。
4. **测试沉没成本**：36k 行 Python 测试 + 35 个迁移 + OpenAPI 契约 + `jobs-py` 作业契约需全部重建。
5. **运维面翻倍**：镜像数从 4 增至 5+，Trivy/SBOM/签名/双架构流水线都要再走一遍（§1 已证明这是当前瓶颈）。

### 3.2 本次实测：Rust 依赖图的真实代价（不是估算）

在受控环境中对候选技术栈做了 `cargo generate-lockfile` / `cargo add` 实测（`rustc 1.98.1`）：

| 技术栈组合 | 传递依赖数 | 结论 |
| --- | --- | --- |
| `axum + tokio + sqlx + serde` | **162** | 最小可用服务 |
| 上表 + 常用生产件（`tower-http`/`redis`/`clickhouse`/`aws-sdk-s3`/`jsonwebtoken`/`argon2`/`utoipa`） | **367** | **约 2.3×** |
| 上表 + `noodles-vcf`/`noodles-fasta`/`noodles-bgzf` | **387** | 只 +20，**生物解析器本身极轻** |
| 上表 + `rust-htslib` | **417** | +50，且引入 C 工具链与静态链接 |
| 上表 + `bio`（rust-bio） | **461** | +94 |

**这条数据直接给出了排序**：
- **服务层重写**要背上 **367 个可传递依赖** 的供应链与审计面（Trivy/SBOM/license），
  而它**不带来算法收益** → 是"重写成本全付、收益拿不到"的组合。
- **摄取内核重写**只需 `noodles-*`，**仅 20 个额外依赖**，且直接解决 P-4 → **投入产出比完全不同**。

### 3.3 环境前提（必须先验证，否则不能立项）

- 本工作区当前**没有 C 工具链**（`cc` / `gcc` 均不存在），Rust 编译在链接阶段即失败；
  本次实测只能用桩链接器验证**依赖解析与编译单元数量**，无法产出二进制或基准数字。
  → **任何 Rust 立项前，必须先确认 CI runner 与生产 runner 是否具备 `cc` + `mold`/`lld`**。
- amd64/arm64 双架构：`rust-htslib` 需交叉编译或原生 C 工具链，成本显著高于纯 Rust 栈。

### 3.4 关键反证：原定"推荐重写点"在复核中被推翻

本节记录一次**结论反转**，因为它是全文最有价值的部分。

**初判**：把「流式 VCF/变异摄取内核」作为唯一推荐的 Rust 重写点——依据是 `docs/research/2026-08-17-...audit.md`
§2.2 描述的"伪流式：整文件进内存、内存 set 去重"。

**复核推翻**（以代码为准，2026-09-11）：

| 事实 | 证据 |
| --- | --- |
| 整个经典科研导入链路（fasta/gff3/**vcf**/blast_db/seed_data/expression_csv/homolog_csv）是 **fail-closed** 的 | `worker/tasks/data_adapters.py:64,125,135,148,158,171`；`ingest.py:448` |
| `import_vcf` 在函数体**第一行**就 `raise UnsupportedImportError`，因为在 `MergeTree` + 无 durable checksum/import identity 下，重试会产生**重复事实** | `ingest.py:446-450` |
| 7 个特性开关默认 `false`，注释明确写着"writer not yet closed" | `api/app/core/features.py:43-70` |
| 唯一真正持久化的导入 `module_tsv` 写的是 `module_data_rows`，而该表**没有任何读取者**（write-only） | `docs/ops/first-release-data-plan.md` §5.2 |
| 首版权威结论是**路线 B：受控真实数据种子**，而非修导入管线 | 同上 §5.3 |

**因此，正确的排序是：阻塞点不是"解析器太慢"，而是"写入器与幂等/去重协议尚未存在"。**

把解析器换成 Rust **既不能解除 fail-closed，也不能带来任何可测收益**（因为该路径当前根本不执行）。
更糟的是：VCF 写入的**真正难点**是 staging/finalize 幂等协议与 ClickHouse schema 迁移（`upgrade_variant_facts_schema.sql`），
这两件事**都不是语言问题**。

> 这正是 `docs/dev/optimization-master-plan.md` §1「教训」所警告的情形：**把未经验证的结论当作已记录事实**。
> 本次评估因此把 Rust 的结论从"推荐"下调为"**在有界场景下有条件可行，但当前不是优先级**"。

### 3.4.1 Rust 在导入链路上的正确介入位置（修订后）

若未来要引入 Rust，**前置条件不是"性能达标"，而是"该路径已重新启用"**：

```text
先决条件（缺一不可）：
  1. staging 表 + 唯一约束 + 单事务 finalize 已实现（解锁 fail-closed）
  2. ClickHouse variant_facts canonical schema 迁移已就位
  3. 该路径已在真实 2M 行数据上跑通，有 Python 版基准数字

满足后，Rust 的可介入点（按收益排序）：
  a. BGZF 块级并行解压（noodles-bgzf）——纯解压即 CPU 密集，收益最实在
  b. VCF 记录解析与批次列式组装（避免逐行 Python 对象）
  c. 增量 SHA-256 校验（替代前端 arrayBuffer 全读）
```

**绑定形式**：`PyO3 + maturin` 编译为 Python 原生扩展，`apps/worker` 内 `import` 即用。
**不采用** Rust sidecar 进程（双运行时/双镜像/双网络边界，成本高于收益）。

**仍然有效的实测论据**（§3.2）：`noodles-*` 只增加 **20 个**传递依赖，是 Rust 生态里唯一"低成本可选项"。
但请注意：**依赖成本低 ≠ 有收益**。收益取决于上述三条先决条件是否成立。

### 3.5 备选（只做 ADR，不排期）

| 候选 | 前置证据 |
| --- | --- |
| `pingora` 类 Rust 网关替代 nginx | 需真实 QPS 压测证明 nginx 是瓶颈；**当前 nginx `proxy_cache` 尚未启用**，先做那个 |
| 静态制品签名/摘要校验（`manifest.json` SHA-256 链） | 当前由 Node/Python 脚本完成且已通过 CI；收益仅为速度，优先级低 |
| WASM 前端加速（JBrowse 大文件解析） | 需浏览器侧实测；`apps/jbrowse` 仅 1,622 行，规模未到 |

---

## §4 分阶段路线图与验收

### Phase R0 — 证据与前置（无代码风险，**先做**）

| 项 | 产出 |
| --- | --- |
| `EXPLAIN (ANALYZE, BUFFERS)` 基线 | 3 条搜索查询 + `list_genes` 的执行计划与耗时 |
| 导入基准 | 现有 Python 路径在 2M 行下的吞吐/峰值 RSS（`SOYMUTDB_RUN_2M_IMPORT_PERF=1`） |
| 工具链确认 | CI/生产 runner 是否有 `cc` + `lld`/`mold`；amd64/arm64 是否都可原生编译 |
| CI 时长基线 | 每个 job 的 P50 时长（`cnb pulls get-ci-timing`） |

**门禁**：以上四项产出的数字是所有后续决策的输入；**没有数字就没有立项**。

### Phase R1 — 不写 Rust 的架构优化（1–2 个迭代）

搜索收口（§2.1）→ 导入 Python 侧流式化（§2.2 前半）→ CI 关键路径压缩（§2.3）。

**验收**：p95 ≤150 ms；导入峰值 RSS 与文件大小解耦；PR 关键路径 ≤15 min。

### Phase R2 — 导入写入器闭环（**Rust 的真正先决条件**）

**这是本次评估识别出的最大阻塞点**，且与语言无关：

1. 设计 `variant_facts` 的 **staging 表 + 唯一约束 + 单事务 finalize**，
   使重试不再产生重复事实（解除 `import_vcf` 的 fail-closed）。
2. 落 canonical schema 迁移（`infra/clickhouse/upgrade_variant_facts_schema.sql`），
   保证 `clickhouse_service.py` 的 `SELECT` 字段一致。
3. 明确 `module_data_rows`（当前 **write-only，无读取者**）的归宿：
   要么补读取者，要么删表——**不能长期留一张只写不读的暂存表**。
4. 为 7 个未实现类型提供 **API 侧 422 + UI 隐藏**（能力开关已存在，`features.py:43-70`），
   避免用户操作后得到 fail-closed 的失败任务。

**验收**：`imports.vcf` 等开关可安全置 `true`；重试幂等测试通过；无重复事实。

### Phase R3 — Rust 摄取内核 PoC（**仅在 R2 完成后**才可立项）

**立项前置（三条全满足）**：
1. R2 完成，导入路径已重新启用；
2. 有 Python 版的真实 2M 行基准（吞吐/峰值 RSS）；
3. R0 的工具链确认通过（`cc` + `lld`/`mold`，amd64 至少；arm64 视交付目标）。

**做法**（若立项）：
1. 新建 `apps/ingest-rs`（**独立 `Cargo.toml`，不进 pnpm workspace**），maturin 构建 Python 扩展。
2. 实现增量 SHA-256、BGZF 块级并行解压、列式批次组装。
3. 与 Python 实现**并行跑同一 fixture**，比对记录数、字段、错误行号（**fail-closed，不得静默跳过**）。
4. **Go/No-Go 门槛（建议）**：吞吐 ≥ **2×** 且峰值内存 ≥ **3× 下降**。
   **未达标即终止，保留 Python 实现**——不设"长期双跑"。

**约束**：不修改 `apps/api`；不改 OpenAPI；不改 `release_id`/`assembly_id` 语义；
不接触 `public_id`/`internal_id`/站点边界；新依赖必须过 license + Trivy 门禁。

### Phase R4 — 永久排除项

**API / routers / services / ORM / Celery / release 状态机永久排除在重写范围外。**
R0–R3 完成后若仍无 Rust 立项，本方案即告结束——**这是可接受且大概率正确的结果**。

---

## §5 风险与反模式清单

| 风险 | 缓解 |
| --- | --- |
| **"因为有 Rust 所以用它"**（本次实际发生） | 以 R0 基准 + R3 Go/No-Go 门槛硬性约束；**没有数字就没有立项** |
| **把过期文档当现状**（本次实际发生） | 所有结论必须给 `文件:行号`；无法给出即标注"待核实"（沿用 `optimization-master-plan.md` §1 教训） |
| 优化一条**不执行**的路径 | 动手前先确认 feature flag 与 fail-closed 状态，再谈性能 |
| 预先把 `escape` 改动当成"已修复" | 必须附 `EXPLAIN` 前后对照；索引未命中不算完成 |
| 双实现长期共存 | R3 必须给**明确终止条件**，不设"可选长期双跑" |
| 供应链膨胀 | 新增 crate 逐个过 `dependency-governance` + Trivy + license 审计 |
| 双架构构建失败 | R0 先验证 arm64 原生工具链；否则 Rust 内核仅 amd64 |
| 违反 H01–H12 | Rust 内核**不接触** `public_id`/`internal_id`/站点边界，只做解析与批处理 |

**反模式（明确禁止）**

- ❌ 用 Rust 重写 service/router/ORM
- ❌ 引入 Rust sidecar 进程（双运行时/双镜像/双网络边界）
- ❌ 在 `Cargo` 里重新实现已有 C 库能做的事（HTSlib/BLAS/htslib 绑定优于重写）
- ❌ 以"性能"名义跳过 `ID-01~05` / `CTX-01~03` / `ASM-01~05` 门禁

---

## §6 需业务/负责人拍板的事项（不得自行决策）

1. `apps/core-rs` 的排除条款（`10-intent.md` Non-goals）**是否修订**？若不修订，Rust 讨论仅限"扩展模块"而非"服务重写"。
2. **导入写入器闭环（§2.2 / Phase R2）是否排期？** 这是解锁真实数据的前提，**优先级高于任何语言选择**。
3. `module_data_rows`（write-only）的归宿：补读取者回填 `genes`，还是废弃该表？
4. VCF 导入的幂等/去重协议是否被接受为 staging + 单事务 finalize 模式？
5. 导入吞吐的**真实目标**（行/秒、最大文件体积、可接受峰值内存）。
6. arm64 是否为目标交付架构（仅在 Phase R3 立项时才有意义）。
7. 搜索 `total_count` 的契约语义（真实总数 vs 页内计数 vs `null`）。

---

## 附录 A：本次评估的方法与限制

- **方法**：仓库静态审计 + 文档交叉核对 + 受控环境依赖解析实测。
- **本次复核推翻的两处初判**（均已在上文标注，保留以警示后续读者）：
  1. `resolve_release_context` 无缓存 → 实际 `release_context.py:73` 已有 60s `@cached`；
  2. VCF 摄取是"待优化的性能热点" → 实际该路径**整体 fail-closed**，`import_vcf` 首行抛错。
- **推断 vs 事实**：本文档区分 `EXPLAIN` 未跑的**假设**（P-1 的索引失效）与代码可核验的**事实**
  （fail-closed、`cached` 已存在、`module_data_rows` 无读取者）。
- **限制**：
  - 工作区无 C 工具链，**未能编译二进制**，故 **无运行时基准数字**；依赖计数为 `Cargo.lock` 实测，可信。
  - 未连接生产 PostgreSQL/ClickHouse，**执行计划为待实测项**（Phase R0）；P-3/P-5 两条初判在复核时
  被代码推翻（缓存已实现），已在表中标注为已修 —— 这正是本文档要求「引用必须给行号」的原因。
  - 未联网核验 crate 的 CVE/维护活跃度（详见 §4 R0 门禁）。
- **声明**：本文档所有"当前状态"结论均给出文件/行号或实测命令；无法给出证据的条目一律标注"待核实"。
