# SoyMutDB 首版真实数据范围与 Release 验收标准

> **状态**：本文是 `data-platform`(t3) 针对 **首版生产 Release（P0）** 冻结「真实数据范围」与
> 「Release 数据面验收标准」的权威文档，与 [`production-readiness.md`](production-readiness.md) 的
> G0 / G10 / G11 / G12 对齐。本文**只冻结范围与验收标准，不虚构已经上线的能力**；凡是标注
> `🎯 目标/待验证` 的能力都需要本轮（build-release / frontend-platform / data-platform / ops-security）
> 先完成、再由 QA 验收后才放行。数据面判定以**源代码与已运行查询的事实**为准。

> **一致性说明（重要）**：本文在撰写时以 `main`（`460b1529f`）的**实际代码**逐条核验数据面写入与查询
> 链路，发现 `production-readiness.md` §2.1 对「基因数据来自 module TSV」的表述与当前实现存在出入
> （详见 §5）。本文如实记录，不掩盖缺口；`qa-acceptance` 在冻结 Go/No-Go 前应以此为准。

---

## 1. 目的与边界

- 划清 **首版生产 Release（0.1.0）真实数据范围**：哪些数据类必须有真实数据、哪些**明确不承诺**。
- 定义 **Release 数据面验收标准（G0/G10/G12）**，给出可执行的可核查查询命令与通过判定。
- 明确 **数据导入写入器收口（G11）**：哪些导入类型首版真实写入闭环、哪些被禁用/隐藏，避免「用户
  能操作但得到失败/占位结果」。
- 界定 **staging 数据面**与**生产数据面**的差异，避免用 Demo 数据冒充 Release。

**范围外**：本文不定义前端隐藏规则的具体 CSS/组件（归 `frontend-platform` t5/t6）、不定义生产环境变量
与 secret（归 `ops-security` t2）、不定义工具链/镜像（归 `build-release` t4）。本文只输出数据面的事实、
范围冻结与验收标准。

---

## 2. 首版 Release 标识冻结（对齐 G0）

> 与 `Release` 模型对齐：`version` 唯一 `String(32)`，`name` `String(256)`，`assembly` `String(128)`。

| 字段 | 首版值（建议，**冻结**） | 说明 |
| --- | --- | --- |
| `version` | `0.1.0` | 语义版本，唯一；首版从 0.1.0 起，后续递增 |
| `name` | `SoyMutDB 0.1.0 — Glycine max (Williams 82) Wm82v4.0` | 人类可读，含物种 + 品系 + assembly |
| `assembly` | `Wm82v4.0` | **单一** assembly；`settings_registry.py` `data.defaultAssembly` 默认即 `Wm82v4.0` |
| `species` | `Glycine max` | 大豆，单物种 |
| `default_blast_db` | `williams82_cds` | `config.py` `blast_default_db` |
| `default_assembly` | `Wm82v4.0` | `VITE_DEFAULT_ASSEMBLY`（前端） |

**名称归一强制项（G12 一致性校验必须通过）**：

- 生产数据面**禁止出现** `Wm82.a4.v1` 这一符号。`apps/web/scripts/fallback-data.ts` 的示例条目
  （`SMDB-00001` …，`referenceGenome: "Wm82.a4.v1"`）属于 **Demo 占位**，只允许出现在 `demo` 构建，
  **不得进入生产制品/生产数据面**。生产统一为 `Wm82v4.0`。
- 生产查询必须绑定 `release_id`/`X-SoyMutDB-Release`，动态请求不得静默切换到其它 release
  （`release_context.py` 默认解析 `ActiveRelease` 单向活动指针）。

---

## 3. 数据面拓扑（当前事实）

数据面横跨 PostgreSQL（权威业务/维度）与 ClickHouse（变体事实），经 `release_context` 统一按
`release_id → release_key`（即 `str(release_id)`）固定查询范围：

```
FastAPI (apps/api)
 ├─ /genes, /genes/{id}  ──► PostgreSQL「genes」(ORM)  + assemblies/chromosomes
 ├─ /variants, /search, stats,
 │    popgen, /blast      ──► ClickHouse「variant_facts」
 │                                  （release_key = str(release_id), assembly_key = assembly）
 ├─ /downloads, /data/*    ──► MinIO「genomic-data」(导出静态文件 + Range)
 └─ /page-definitions/{r}, /content/snapshot ──► PostgreSQL「page_definitions / content」

Celery worker (apps/worker)
 └─ import adapters / tasks ──► PostgreSQL「module_data_rows」、ClickHouse「variant_facts」
```

关键的 `variant_facts` 查询字段（`clickhouse_service.py` 实际使用 + `upgrade_variant_facts_schema.sql`）：
`variant_id, release_key, assembly_key, chromosome, position, ref_allele, alt_allele, variant_type,
variant_subtype, length, gene_id, gene_symbol, gene_surrogate_id, mutant_line_surrogate_id,
mutant_line_name, consequence, consequence_id, impact, rs_id, quality_score, filter_status,
read_depth, allele_frequency, hgvs_c, hgvs_p, zygosity`。

---

## 4. 首版真实数据范围冻结（对齐 G10）

> 原则：**首版只承诺「单物种 + 单一 assembly」的可信最小数据集**；任何超出范围的能力**不作为放行前提**，
> 且不得用占位数据冒充真实数据。

### 4.1 P0 最小数据集（首版必须为真实数据）

| 数据类 | 覆盖内容 | 存于 | 读取端点 | 首版数据要求 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 基因/注释/别名 | `genes` + `transcripts` + `exons` + `gene_aliases`（含染色体、起止、strand、biotype） | PostgreSQL | `/genes`、`/genes/{id}` | 真实大豆参考基因集；行级 schema 校验 + checksum | 🎯 待验证 |
| 变异 | `variant_facts`（坐标、ref/alt、type、gene、consequence/impact、zygosity 等） | ClickHouse | `/variants`、`/search`、popgen、stats | 单一 `assembly_key=Wm82v4.0`；坐标范围合法；统计与明细一致 | 🎯 待验证 |
| 统计/分布 | 染色体/assembly 统计（总 count、type 分布、density bins、dashboard） | ClickHouse（派生） | `/stats`、density/dashboard | 由上述变异/基因派生，与明细一致 | 🎯 待验证 |
| 下载 | Release 导出的静态文件（基因/变异/注释，含 `manifest.json` + 逐文件 SHA-256） | MinIO `genomic-data` | `/downloads`、`/data/*` | 文件存在且 checksum 命中；`Range` 支持 | 🎯 待验证 |
| JBrowse 轨道 | 该 assembly 的 bundle + 轨道文件（基因/变异对应轨道，含 `.fai`） | MinIO / 静态 | `/browser` | 浏览器可加载 `Wm82v4.0` 轨道；**不得** fallback 到 `Wm82.a4.v1` | 🎯 待验证 |

**P0 数据范围 = 上述 5 类。** 每类都必须满足 §5 的一致性约束与 §7 的查询验证。

### 4.2 明确不承诺（首版范围外）

> 这些能力**存在代码骨架/占位**，但**首版不保证真实可用**。在 Admin/前端必须隐藏或标注「即将开放」。

| 类别 | 说明 | 首版处理 |
| --- | --- | --- |
| 多物种 | 非大豆物种门户 | 首版仅大豆单物种；其他物种隐藏 |
| 多 assembly | 多基因组比对/轨道堆叠 | 首版仅 `Wm82v4.0` 单一 assembly；多 assembly 视图隐藏 |
| FASTA/GFF3/VCF 导入 | 真实写入**未闭环**（见 §5） | 在 Admin 创导入按能力隐藏；不作为首版数据承诺 |
| BLAST DB 导入 | 自定义 BLAST DB 写入未闭环 | 隐藏；首版仅使用默认 `williams82_cds` 查询 |
| Expression / Homolog / Seed 导入 | 对应写入未闭环 | 隐藏；不作为首版数据承诺 |
| GWAS | `gwas` bucket | 可保留 bucket，但**不承诺可查询** |
| 分析流水线 | fastp/scanpy 等 analyses | 可运行 worker，不承诺首版出公开结果 |
| 多语言 / MCP / 通知 | — | 已有实现，不作为 P0 数据硬门禁 |

---

## 5. 数据导入写入器收口（对齐 G11）—— 现状与缺口

### 5.1 写入器现状（以 `apps/worker/src/soymutdb_worker/tasks/` 为准）

`data_adapters.py` 的 `_ADAPTERS` 注册表（`get_adapter(kind)` 返回后由 `ingest.run_import_adapter`
调用 `.run()`）：

| `ImportType` | 注册的 adapter | `.run()` 实际行为 | 是否持久化到数据面 |
| --- | --- | --- | --- |
| `module_tsv` | `ModuleTsvAdapter` | 流式校验 + 分块 `INSERT` 到 `module_data_rows` | ✅ **是**（写入 `module_data_rows`） |
| `fasta` | `FastaAdapter` | `raise UnsupportedImportError` | ❌ 否 |
| `gff3` | `Gff3Adapter` | `raise UnsupportedImportError` | ❌ 否 |
| `vcf` | `VcfAdapter` | `raise UnsupportedImportError` | ❌ 否 |
| `blast_db` | `BlastDbAdapter` | `raise UnsupportedImportError` | ❌ 否 |
| `seed_data` | `UnsupportedCsvAdapter("seed_data")` | `raise UnsupportedImportError` | ❌ 否 |
| `expression_csv` | `UnsupportedCsvAdapter("expression_csv")` | `raise UnsupportedImportError` | ❌ 否 |
| `homolog_csv` | `UnsupportedCsvAdapter("homolog_csv")` | `raise UnsupportedImportError` | ❌ 否 |

`ingest.py` 中的独立任务同样**未持久化**：

- `import_vcf(...)`：正文头部直接 `raise UnsupportedImportError(...)`（**fail-closed**，防止 `variant_facts`
  的 `MergeTree` 在重试时产生重复事实）。
- `import_gff3(...)`：只统计 gene/transcript/exon 数量并返回 `{genes, transcripts, exons}`，**不写库**。
- `import_mutant_lines(...)`：只计数并不写 `mutant_lines`。

### 5.2 关键缺口：导入产物与门户读取表不一致

> **源代码事实（重点，需 QA 关注）**：

- 门户 `/genes`、`/genes/{id}`（`gene_service.py`）读取的是 **PostgreSQL `genes` 表**（ORM 模型
  `models/genomic.py: Gene`）。
- 唯一的持久化导入写入器 `module_tsv` 写入的是 **`module_data_rows`**（`models/module_data.py`），
  且 `module_data_rows` **当前没有任何 API/worker 消费者**（仓库内 grep 无读取点，属于 **write-only** 暂存表）。
- 因此，**在现有导入链路下，门户 `/genes` 所读的 `genes` 表没有真实写入器**；`variant_facts` 同样
  **没有**真实写入器（`import_vcf` fail-closed）。

**结论**：`production-readiness.md` §2.1 把「基因检索」数据来源写成「module TSV（genes module）」是
**不准确的**——module TSV 当前并不回填 `genes` 表。首版若要通过 import 管线获得真实基因/变异数据，
必须先完成下列收口之一（**数据平台前置**）。

### 5.3 收口路径（数据平台建议，供 captain 排期）

首版真实数据注入可选两条路线，**推荐 B 为主**：

- **路线 A（补齐核心写入器）**：为 GFF3/FASTA/VCF 实现真正的幂等持久化写入器 + 原子 finalize：
  - GFF3 → 写 `genes`/`transcripts`/`exons`/`gene_aliases`（`import_gff3` 当前仅计数，需改为写库）。
  - FASTA → 写 `assemblies`/`chromosomes`（含 `fai`）。
  - VCF → 写 ClickHouse `variant_facts`（需先具备 durable checksum/import identity + staging/finalize，
    消除 `MergeTree` 重试重复；`variant_facts` 需按 `upgrade_variant_facts_schema.sql` 的 canonical schema 迁移）。
  - 成本高、涉及 ClickHouse 迁移与幂等协议，**不建议在首轮硬门禁前强制完成**。
- **路线 B（受控真实数据种子：推荐首版）**：用**可复现的受控脚本/迁移**直接把**权威真实数据**写入核心表
  （`assemblies`/`chromosomes`/`genes`/`variant_facts`），并绑定到 `release_id`。
  **设计与 CLI 契约见 [`route-b-seed-data-design.md`](route-b-seed-data-design.md)（t12）；
  骨架脚本 [`seed-release-data.sh`](../../scripts/seed-release-data.sh)（t12，默认 fail-closed：仅 plan /
  `--check`，`--apply` 需 `SOYMUTDB_SEED_ENABLED=1` 且 loader 已实现，**绝不注入示例数据**）**。该脚本：
  - 只接受**公开权威来源 + 固定版本**；记录 `Provenance`（source / tool / tool_version / checksum_sha256）。
  - 幂等（可重跑不产生重复）；带 `manifest.json`（逐文件 SHA-256）。
  - **不经过**浏览器直传/多格式导入（那些仍由 module_tsv 承担），从而绕开「导入写入器未闭环」的阻塞。
  - 与 `import_vcf` 的 fail-closed 不同，这是**显式、可审计的数据装载**路径，需在 Admin「Data Imports」
    之外单独说明，避免与「导入」混淆。

> 无论 A/B，`variant_facts` 查询侧依赖 canonical schema（`upgrade_variant_facts_schema.sql`）。
> 首版若缺失该迁移，`SELECT` 字段名会与 `clickhouse_service.py` 不一致而查询失败。

### 5.4 前端/API 能力收口（G11 必须通过）

现状（`apps/api/app/api/v1/admin_imports.py` + `apps/admin/src/routes/imports.tsx`）：

- `schemas/data_publishing.py` 的 `ImportType` **允许全部 8 种** `vcf/gff3/fasta/blast_db/seed_data/
  expression_csv/homolog_csv/module_tsv`。
- `admin_imports.create_import` 仅对 `module_tsv` 做 feature-flag / 格式 / 校验强制；其余类型**直接接受**
  并 dispatch，最终 worker `fail-closed`——用户会得到**失败任务**而非清晰的能力提示。
- `imports.tsx` 的 `ALL_IMPORT_TYPES` 当前**列出全部 8 种**；`capabilities` 只提供
  `imports.module_tsv / imports.module_xlsx / imports.local_upload` 三个开关。

**收口要求**：

1. **新增 per-type 能力开关**：为上述未实现类型注册 feature key（如 `imports.fasta` / `imports.gff3` /
   `imports.vcf` / `imports.blast_db` / `imports.seed_data` / `imports.expression_csv` /
   `imports.homolog_csv`），默认 `false`，并加入 `GET /api/v1/capabilities` 的 `features`（public 可见）。
2. **API 侧拒绝**：`create_import` 对未实现类型在能力关闭时返回 `422`（而非 dispatch 后 fail-closed）；
   已存在的任务在 worker 层维持 fail-closed（不静默成功）。
3. **Admin UI 隐藏**：`imports.tsx` 仅展示 `features[imports.*] === true` 的类型；首版仅
   `module_tsv` 可操作，其余隐藏或标注「即将开放」。
4. **不产生占位结果**：任何未开放类型不得让用户操作后出现成功/占位响应。

---

## 6. Release 数据面验收标准（对齐 G0/G10/G12）

> 数据面「ready」必须同时满足：数据集全部 `READY` + source objects 完整（`sha256` 且 `etag`）。
> 以下为数据面**附加**验收标准，作为 `release_service.mark_release_ready` 之外的数据级门禁。

### 6.1 数据结构与范围（G0/G10）

| # | 标准 | 判定 | 证据 |
| --- | --- | --- | --- |
| D1 | `release.version` 唯一；`releases.assembly` 为单值 `Wm82v4.0`；`assemblies.species=Glycine max`、`assemblies.is_default` 指向 `Wm82v4.0` | `SELECT version, assembly FROM releases WHERE status='published'` 唯一且为 `0.1.0`/`Wm82v4.0`；`SELECT name, species FROM assemblies WHERE is_default` 为 `Wm82v4.0`/`Glycine max` | 查询输出 |
| D2 | 数据面不含 `Wm82.a4.v1` 等 Demo 符号（assembly 归一为 `Wm82v4.0`） | 全库/制品 grep `Wm82.a4.v1` 零命中 | grep 输出 |
| D3 | 数据集全部 `READY`，且 source object 有 `sha256`+`etag` | `release_service.validate_release` 通过 | API 日志 / 查询 |
| D4 | `manifest.json` 含 `version` + `provenance`，`readiness` 四项 `jbrowse/blast/downloads/api` 全 `true` | `release_service.mark_release_ready` 通过 | API 日志 |

### 6.2 跨数据集一致性（G12）

| # | 标准 | 判定 | 证据 |
| --- | --- | --- | --- |
| C1 | `variant_facts` 的 `assembly_key` 全部为 `Wm82v4.0`（无多 assembly 混入） | `SELECT DISTINCT assembly_key FROM variant_facts` == `['Wm82v4.0']` | 查询输出 |
| C2 | `variant_facts` 按 `release_key` 隔离；无效 `release_id` 查询返回空/404 | 用非活动 `release_id` 查询 `count()`==0 或 API 404 | 查询输出 |
| C3 | `genes.gene_id` 与 `variant_facts.gene_id` 引用一致（变异命中的 gene 在基因表存在） | join 统计孤儿 gene_id == 0 | 查询输出 |
| C4 | 染色体坐标边界合法：`variant_facts.position ≤ chromosome.length`；`genes.start/end` 在染色体范围内 | 越界计数 == 0 | 查询输出 |
| C5 | 变异 type/impact/consequence 使用受控枚举（SNP/INS/DEL/MNV/SV；HIGH/MODERATE/LOW/MODIFIER） | 非枚举值计数 == 0 | 查询输出 |
| C6 | JBrowse 轨道 `.fai`/bundle 对应 `Wm82v4.0`，且不 fallback 到 `Wm82.a4.v1` | `/browser` 加载该 assembly；无 404 | E2E + 数据面查询 |

### 6.3 下发与可追溯（G12）

| # | 标准 | 判定 | 证据 |
| --- | --- | --- | --- |
| P1 | 每个下载/导出对象在 `manifest.json` 有 SHA-256，且实际文件 checksum 命中 | `sha256sum` 比对 manifest | 校验输出 |
| P2 | `Provenance` 记录 source / tool / tool_version / checksum_sha256 | `SELECT * FROM provenance` 有关键字段且非空 | 查询输出 |
| P3 | 关键步骤带时间戳（UTC），证据可复现（附命令/脚本路径） | 归档 `acceptance/data-query/` | 目录清单 |

---

## 7. 数据面查询验证脚本（G12 证据，可执行示例）

> **可运行脚本**：`scripts/validate-release-data.sh`（t7 交付，已做逻辑冒烟测试）。使用方式：
> `RELEASE_ID=<N> bash scripts/validate-release-data.sh`（可加 `--pg` / `--ch` / `--api` /
> `--dry-run`），连接变量见脚本头（`SOYMUTDB_PG_DSN`/`SOYMUTDB_CLICKHOUSE_*`/`SOYMUTDB_API_BASE`/
> `RELEASE_ID`/`ASSEMBLY` 等）。下方为脚本所执行的**命令模板**；真实值以运行环境为准。归档到
> `artifacts/acceptance/data-query/`。

### 7.1 PostgreSQL（基因/assembly 维度，`psql`）

```bash
# 1) release 身份
psql "$SOYMUTDB_DATABASE_URL" -Atc \
  "SELECT version, assembly FROM releases WHERE status='published' ORDER BY id DESC LIMIT 1;"

# 2) 基因规模与染色体覆盖
psql "$SOYMUTDB_DATABASE_URL" -Atc \
  "SELECT count(*) AS genes, count(DISTINCT chromosome_id) AS chromosomes FROM genes;"

# 3) 基因明细抽样（必须为真实记录，非 SMDB-*）
psql "$SOYMUTDB_DATABASE_URL" -Atc \
  "SELECT g.id, g.biotype, g.start, g.end, g.strand, c.name AS chr
   FROM genes g JOIN chromosomes c ON c.id = g.chromosome_id
   WHERE g.assembly_id = (SELECT id FROM assemblies WHERE name='Wm82v4.0') LIMIT 5;"

# 4) 无明显 Demo 占位符号
psql "$SOYMUTDB_DATABASE_URL" -Atc \
  "SELECT count(*) FROM genes WHERE id LIKE 'SMDB-%' OR name LIKE '%SMDB-%';"   # 期望 0

# 5) provenance 完整性
psql "$SOYMUTDB_DATABASE_URL" -Atc \
  "SELECT count(*) FROM provenance WHERE source='' OR tool='' OR checksum_sha256='';"  # 期望 0
```

### 7.2 ClickHouse（变异事实，`clickhouse-client`）

```bash
# 1) 锁定 release_key（= release_id 字符串）后统计
clickhouse-client --database soymutdb --query \
  "SELECT count() AS total FROM variant_facts WHERE release_key='<RID>' AND assembly_key='Wm82v4.0';"

# 2) 单 assembly 去重：确认没有混入其它 assembly
clickhouse-client --database soymutdb --query \
  "SELECT DISTINCT assembly_key FROM variant_facts WHERE release_key='<RID>';"   # 期望仅 Wm82v4.0

# 3) 变异类型分布（受控枚举）
clickhouse-client --database soymutdb --query \
  "SELECT variant_type, count() AS cnt FROM variant_facts
   WHERE release_key='<RID>' AND assembly_key='Wm82v4.0' GROUP BY variant_type ORDER BY cnt DESC;"

# 4) 区域查询（region query 必须命中）
clickhouse-client --database soymutdb --query \
  "SELECT variant_id, chromosome, position, ref_allele, alt_allele, gene_id, consequence
   FROM variant_facts
   WHERE release_key='<RID>' AND assembly_key='Wm82v4.0' AND chromosome='Chr01'
     AND position BETWEEN <P0> AND <P1> LIMIT 10;"

# 5) 坐标边界：不得存在 position>染色体长度（示例 Chr01 长度已知）
clickhouse-client --database soymutdb --query \
  "SELECT count() FROM variant_facts
   WHERE release_key='<RID>' AND assembly_key='Wm82v4.0' AND chromosome='Chr01' AND position > <CHR01_LEN>;"  # 期望 0

# 6) dashboard/统计一致性：明细 count 与聚合一致
clickhouse-client --database soymutdb --query \
  "SELECT count() FROM variant_facts WHERE release_key='<RID>' AND assembly_key='Wm82v4.0';"
```

### 7.3 API（门户实际查询，`curl`）

```bash
# 1) capability：未实现导入类型必须不可用
curl -s "$API_BASE/api/v1/capabilities" | jq '.features["imports.vcf"]'   # 期望 false / 不存在

# 2) 基因检索返回真实记录（非 SMDB-*）
curl -s "$API_BASE/api/v1/genes?assembly=Wm82v4.0" | jq '.items[] | {id, biotype, chromosome}'

# 3) 变异统计
curl -s "$API_BASE/api/v1/stats" -H "X-SoyMutDB-Release: <RID>" | jq .

# 4) 无效 release 查询应 404
curl -s -o /dev/null -w '%{http_code}\n' "$API_BASE/api/v1/genes?release_id=999999"   # 期望 404

# 5) 下载对象 checksum
curl -s "$API_BASE/api/v1/data/<path>" | sha256sum
```

---

## 8. 首版放行的数据面判定汇总

| Gate | 约束 | data-platform 交付 | 状态 |
| --- | --- | --- | --- |
| G0 | Release 命名 + 数据范围冻结 | 本文 §2/§4 | 🎯 待验证 |
| G10 | 真实数据范围冻结（单物种单 assembly 最小集） | 本文 §4 | 🎯 待验证 |
| G11 | 导入写入器收口 + 未实现类型不可操作 | 本文 §5 + 能力开关/UI 验收 | 🎯 待验证 |
| G12 | 查询验证满足标准 | 本文 §6/§7 命令与输出 | 🎯 待验证 |

**No-Go 触发（数据面）**：

- 数据面出现 `Wm82.a4.v1` / `SMDB-*` 占位（未归一）。
- 门户 `/genes`、`/variants` 在活动 release 下返回空/示例/占位。
- `variant_facts` 混入多 assembly 或 `release_key` 未隔离。
- 未实现导入类型在 Admin 仍可触发真实写入或得到「成功」占位响应（无 422/隐藏）。
- `variant_facts` 未按 canonical schema 迁移导致查询字段不匹配。
- `manifest.json` 缺失 `version`/`provenance`/`readiness`，或下载对象 checksum 不命中。

---

## 9. 证据归档与依赖

- **本文档**：`docs/ops/first-release-data-plan.md`（t3 主交付）。
- **路线 B 设计与 CLI 契约**：`docs/ops/route-b-seed-data-design.md`（t12）。
- **路线 B 骨架脚本**：`scripts/seed-release-data.sh`（t12；默认 fail-closed，`--check`/`--dry-run` 只预检+plan，`--apply` 需 `SOYMUTDB_SEED_ENABLED=1` 且 loader 已实现；绝不注入示例数据）。
- **可运行验证脚本**：`scripts/validate-release-data.sh`（t7 交付；对 PG/CH/API 跑 G11/G12 检查并输出 PASS/FAIL）。
- **查询验证输出**：`artifacts/acceptance/data-query/`（用上述脚本跑出的原始输出，t7 提供；路线 B 的 `seed-manifest.json`、`seed-<release_id>.log` 亦归档至此）。
- **依赖队友**：
  - `build-release`(t4)：无直接数据依赖；提供数据面相关镜像/工具链。
  - `frontend-platform`(t5/t6)：`VITE_DEPLOYMENT_MODE=production` 禁止占位数据、隐藏未实现导入类型、
    `default_assembly`/`VITE_DEFAULT_ASSEMBLY` 归一为 `Wm82v4.0`。
  - `ops-security`(t2)：生产 `env.production.example` + CORS/JWT/MCP 边界（数据面只读不涉 secret）。
  - `qa-acceptance`(t1)：以本文为准冻结 G0/G10/G11/G12 判定。

---

## 10. 当前事实核验清单（撰写时，`main`=`460b1529f`）

- ✅ `config.py`：`APP_ENV ∈ {dev,staging,prod}`；`blast_default_db="williams82_cds"`；
  `prod` 对 CORS/JWT/示例值 fail-fast（`_DEFAULT_PRODUCTION_VALUES` 亦在补 `clickhouse_password` 等默认）。
- ✅ `settings_registry.py`：`data.defaultAssembly` 默认 `Wm82v4.0`。
- ✅ `data_adapters.py._ADAPTERS`：仅 `module_tsv` 持久化写入 `module_data_rows`；其余 7 类 `fail-closed`。
- ✅ `ingest.py`：`import_vcf` fail-closed；`import_gff3`/`import_mutant_lines` 仅计数不写库。
- ✅ `gene_service.py` 读 `genes` 表；`data_adapters`/`module_data_rows` 无读取消费者（write-only）。
- ✅ `admin_imports.py` 允许全部 8 种类型；仅 `module_tsv` 有 feature-flag 强制。
  **t8 更新**：`create_import` 现对每种类型先 `_require_import_type_enabled`，未实现类型（默认关闭）返回 422。
- ✅ `apps/admin/src/routes/imports.tsx` 列出全部 8 种类型。
  **t8 更新**：Admin「Data Imports」现仅渲染 capability 为 `enabled` 的类型（默认仅 `module_tsv`），
  未实现类型已隐藏并阻止提交。
- ✅ `feature-flags` 注册：`imports.module_tsv / imports.module_xlsx / imports.local_upload`
  （无其余类型开关）。**t8 更新**：新增
  `imports.fasta/gff3/vcf/blast_db/seed_data/expression_csv/homolog_csv`（默认 `off`，public 可见，
  见 `core/features.py` 的 `IMPORT_TYPE_FEATURES`）。
- **t7 更新**：新增可运行验证脚本 `scripts/validate-release-data.sh`（见 §7）。
- ✅ `clickhouse_service.py` 读 `variant_facts`，按 `release_key`+`assembly_key`+`chromosome` 过滤。
- 🔄 `apps/web/src/lib/deployment.ts` 的 `DeploymentMode` 已被 `frontend-platform`(t5) 扩展为
  `standard|demo|minimal|production`（新增 `isProductionDeploymentMode`），并新增
  `scripts/release-manifest.ts`；`docs/ops/production-security-checklist.md` 由 `ops-security`(t2) 添加。
  **数据面判定以 t5 最终合入为准**，本表记录并行工作现状。
- ⚠️ `variant_facts` 需按 `infra/clickhouse/upgrade_variant_facts_schema.sql` 的 canonical schema
  迁移，否则查询字段名与 `clickhouse_service.py` 不一致。

> 上表若有出入，以代码库实际状态为准，并在本文更新日期栏记录修订。
