# SoyMutDB Route B —— 受控真实数据种子脚本设计与实现准备

> **状态**：本文是 `data-platform`(t12) 为 **首版生产 Release（0.1.0）真实数据注入** 出的
> **设计与实现准备**文档，定义路线 B（受控真实数据种子）的目标、数据模型映射、CLI 契约、
> 幂等/安全协议与脚本骨架。**适用范围**：解决 `first-release-data-plan.md` §5 指出的
> 「门户读取表（`genes`/`variant_facts`）无真实写入器」这一 G10 前置缺口。
>
> **红线**：本路线**绝不注入示例/演示数据**。脚本对任何输入做真实性校验，若源数据缺失、格式不符、
> 或命中 Demo 标记（`SMDB-*`、`Wm82.a4.v1`、`fallback-data.ts`/legacy fixture 特征），**必须 fail-closed**。
> 本文不声称已实现可跑通的真实写入器——只给设计、CLI 契约与可部署的骨架。

---

## 1. 目标与非目标

### 1.1 目标

- 用**可复现、受控、幂等**的方式，把**权威真实数据**（参考基因组 FASTA、基因注释 GFF3、变异 VCF、
  突变品系元数据）直接写入门户读取的数据面：
  - PostgreSQL：`assemblies`、`chromosomes`、`genes`、`transcripts`、`exons`、`gene_aliases`、
    `mutant_lines`；并登记 `data_sets` + `provenance` + `release_data_sets`（release-scoped）。
  - ClickHouse：`variant_facts`（canonical schema，`release_key`+`assembly_key` 隔离）。
- 全程记录 **Provenance**（source / tool / tool_version / checksum_sha256）与逐文件 **manifest
   / SHA-256**，供 G12 查询验证与审计。
- 与现有 **Release 状态机**协同：只在 **draft** release 上写入；写入后把对应 DataSet 置 `ready`，
  再 `validate` → `mark_ready`（其中 jbrowse/blast/downloads 的 readiness 由外部构建提供，种子工具只填
  自己拥有的数据面证据）。

### 1.2 非目标（明确不做）

- **不作为**浏览器多格式导入（`module_tsv`）的替代（它写 `module_data_rows`，write-only，不供门户）。
- **不实现**路线 A 的七类导入 durable 写入器（FASTA/GFF3/VCF 等 adapter 的持久化）。
- **不使用/不生成**任何示例 ID、占位 gene、`SMDB-*` 或 `Wm82.a4.v1` 符号。
- **不替代**JBrowse bundle / BLAST DB / 下载导出等派生对象的生产（那些由 build-release/frontend-platform
  与独立构建产出）。

---

## 2. 数据模型映射（源文件 → 目标表）

> 列名以 `apps/api/app/models/*` 与 `infra/clickhouse/upgrade_variant_facts_schema.sql`（canonical）为权威。

### 2.1 FASTA → `assemblies` + `chromosomes`

| 目标表 | 关键列 | 来源 |
| --- | --- | --- |
| `assemblies` | `name`(唯一, e.g. `Wm82v4.0`) · `species`(`Glycine max`) · `version` · `description` · `fasta_url` · `fai_url` · `is_default` · `release_id` | FASTA header/文件名 + 元数据文件 |
| `chromosomes` | `assembly_id` · `name` · `length` · `order` | FASTA 每条序列长度（或 `.fai` 的列 2） |

- 输入：`*.fa[.gz]`（+ 可选 `*.fa.fai`）、`assembly.meta`（name/version/species/url 等）。
- 校验：序列名唯一、`length>0`、`is_default` 只允许一个、name 归一为 `Wm82v4.0`（**拒绝** `Wm82.a4.v1`）。

### 2.2 GFF3 → `genes` + `transcripts` + `exons` + `gene_aliases`

| 目标表 | 关键列 | 来源（GFF3 feature） |
| --- | --- | --- |
| `genes` | `id`(e.g. `Glyma.01G000100`) · `assembly_id` · `chromosome_id` · `name` · `biotype` · `start` · `end` · `strand` · `description` · `attributes`(JSONB) | `##gff-version 3`; `gene` 行 + `ID`/`Name`/`biotype`/`Dbxref` |
| `transcripts` | `id` · `gene_id` · `name` · `biotype`(`mRNA`) · `start` · `end` · `strand` · `is_canonical` | `mRNA`/`transcript` 行, `Parent=gene_id` |
| `exons` | `transcript_id` · `start` · `end` · `order` | `exon` 行, `Parent=transcript_id` |
| `gene_aliases` | `gene_id` · `alias` · `source` | `gene` 的 `Name`/`Alias`/`Dbxref` 属性 |

- 校验：ID 引用一致（transcript→gene、exon→transcript 存在）；坐标在 `chromosomes.length` 内；
  `start<=end`；strand ∈ {+,-}；biotype 默认 `protein_coding`/`mRNA`。
- **不落库**：GFF3 若无 gene/transcript/exon 特征则 fail-closed。

### 2.3 VCF → ClickHouse `variant_facts`（canonical schema）

| 目标列（canonical） | 来源 |
| --- | --- |
| `variant_id` | `compute_variant_id(release_id, file_key, chrom, pos, ref, alt)`（确定性，见 §4） |
| `release_key` | `str(release_id)`（必须与 `release_context.release_key` 一致） |
| `assembly_key` | `Wm82v4.0`（单一 assembly；**拒绝** `Wm82.a4.v1`） |
| `chromosome` / `position` / `ref_allele` / `alt_allele` | VCF CHROM/POS/REF/ALT |
| `variant_type` / `variant_subtype` / `length` | `determine_variant_type(ref,alt)`（SNP/INS/DEL/MNV/SV） |
| `gene_id` / `gene_symbol` / `gene_surrogate_id` | `gene_id`（邻近基因，可选）；`gene_surrogate_id=_surrogate_id(gene_id)` |
| `mutant_line_surrogate_id` / `mutant_line_name` | 样本 → `_surrogate_id(sample)`；首个非参样本名 |
| `consequence` / `consequence_id` / `impact` | SnpEff ANN 最严重项（`CONSEQUENCE_RANK`/`IMPACT_RANK`） |
| `quality_score` / `filter_status` / `read_depth` / `allele_frequency` | QUAL/FILTER/DP/AF |
| `rs_id` / `hgvs_c` / `hgvs_p` / `zygosity` | ID/VCF INFO `ANN` 解析/GT |

- 校验：POS ∈ (0, chr_len]；`ref_allele`/`alt_allele` 非空、非 `<*>`；`variant_type` ∈ 受控枚举；
  `release_key`/`assembly_key` 稳定。
- **幂等**：按 `(release_key, assembly_key, chromosome, position, gene_surrogate_id,
  mutant_line_surrogate_id, variant_id)` 去重（写入前对同一 `release_key` 旧批次做 staging/替换协议，
  见 §4），避免 `MergeTree` 重试重复。

### 2.4 突变品系元数据 TSV → `mutant_lines`（可选，用于 variant 的品系引用）

| 目标表 | 关键列 | 来源（TSV 表头） |
| --- | --- | --- |
| `mutant_lines` | `name` · `species` · `cultivar` · `mutagen` · `mutagen_dose` · `generation` · `description` · `is_public` · `release_id` | `name,species,cultivar,mutagen,mutagen_dose,generation,description` |

> 注意：`mutant_lines.name` 唯一；`is_public=true` 才进入公开数据面。

---

## 3. 输入契约与真实性校验（无示例数据）

### 3.1 必需输入

| 文件 | 建议命名 | 必需 | 备注 |
| --- | --- | --- | --- |
| 参考基因组 | `genome.fa[.gz]`（+ `genome.fa.fai`） | 是 | 组装/染色体的权威来源 |
| 组装元数据 | `assembly.meta`（JSON） | 是 | name/version/species/fasta_url/fai_url/description |
| 基因注释 | `annotations.gff3[.gz]` | 是 | genes/transcripts/exons/aliases |
| 变异 | `variants.vcf[.gz]` | 是* | 首版若仅基因无变异可缺，但 G10 要求变异最小集（见 §6） |
| 突变品系 | `mutants.tsv` | 否 | 可选 |

### 3.2 真实性校验（每个文件必做）

1. **存在性**：文件存在且非空。
2. **候选校验**：FASTA/GFF3/VCF 格式（magic/header）合法；`*.gz` 用 gzip 完整性。
3. **checksum**：逐文件 `sha256`，记录到 manifest。
4. **Demo 拒绝（fail-closed）**：任何输入/解析结果命中以下任一即整体中止：
   - `SMDB-00001` 等 `SMDB-*` 占位 gene/mutant；
   - `Wm82.a4.v1` / `referenceGenome` Demo 符号；
   - legacy fixture（`infra/clickhouse/fixture_legacy.sql` 的 `'Wm82'`/`'Williams82'` 等占位样例标记）。
5. **规模 sanity**：基因数/变异数大于 0；染色体长度合理（>0）。
6. **assembly 归一**：`name==Wm82v4.0`，否则报错（除非显式 `--assembly` 覆盖且非 Demo）。

---

## 4. 幂等与安全协议（Route B 关键）

| 议题 | 决策 |
| --- | --- |
| Release 状态 | 只允许在 `draft` release 上写入；非 draft 直接拒绝（对齐 `create_release` + `module_tsv` 的 draft-only 约束）。 |
| 作用域 | 所有写入以 `release_id`(PG) / `release_key=str(release_id)`(CH) 收口；禁止跨 release 污染。 |
| 幂等 | 同一 `release_id` 重跑：先删除该 release 下旧的 `genes/transcripts/exons/gene_aliases/mutant_lines/variant_facts`（release-scoped），再按批次插入；以**稳定主键**（gene id / variant sort key）去重。CH 用 staging + 替换协议（`variant_facts_new`→`RENAME`，如 `upgrade_variant_facts_schema.sql`）避免 `MergeTree` 重试重复。 |
| 事务性 | PG 用单事务写入 + `DataFrame`/分批 `INSERT`；任一步失败整体回滚，不留半成品。CH 写入在 PG finalize 之前，失败则回滚 PG 指针。 |
| Provenance | 每个 DataSet 至少一行 `provenance`：`data_set_id`/`object_key`/`checksum_sha256`/`source`/`tool`/`tool_version`。 |
| Manifest | 逐文件 `sha256` + release/assembly/tool/版本 → `seed-manifest.json`。 |
| 派生对象 | 种子工具只负责核心数据面；JBrowse/bundle、BLAST DB、下载导出由各自流水线，本工具只登记 readiness 证据占位（其余为 false，交由外部填充后 `mark_ready`）。 |
| 确定性序号 | gene_surrogate_id / mutant_line_surrogate_id 用 `_surrogate_id(key)=int.from_bytes(sha256(key)[:4],'big')&0xFFFFFFFF`；variant_id 用 `compute_variant_id(release,file_key,chrom,pos,ref,alt)`（与 worker 一致，保证可复现）。 |

---

## 5. 编排（脚本流程）

```
preflight(输入/格式/checksum/Demo拒绝)
  └─ create_or_get_draft_release (version/name/assembly)   [需 `--release-id` 或 `--create-release`]
  └─ seed_assembly            → assemblies + chromosomes（写 Provenance: fasta）
  └─ seed_genes_from_gff3     → genes + transcripts + exons + gene_aliases（写 Provenance: gff3）
  └─ (可选) seed_mutant_lines → mutant_lines（写 Provenance: mutants.tsv）
  └─ seed_variants_from_vcf   → ClickHouse variant_facts（写 Provenance: vcf）
  └─ bind_datasets            → data_sets(type=seeded_*) + release_data_sets + provenance
  └─ mark_dataset_ready       → DataSet.status=ready（全套 ready 后可 validate/ready）
  └─ emit manifest            → seed-manifest.json + 汇总（供 G12 归档 artifacts/acceptance/data-query/）
```

- 顺序：先 PG 基因（发布前变异校验需要 gene_id 引用），后 CH 变异（C3/C4 校验）。
- `--dry-run` 只预检 + 打印 plan/命令，**不动库**。
- `--check` 只做输入校验与 checksum，不写库（用于发布前预检，QA 可用来验证源数据真实性）。

---

## 6. 校验门（对应 G12 / first-release-data-plan §6）

| # | 检查 | 判定 |
| --- | --- | --- |
| D1 | release 身份/assembly 单一 | `releases.version=0.1.0`，`assembly=Wm82v4.0`，`assemblies.is_default` species=`Glycine max` |
| D2 | 无 Demo 符号 | 全库 grep `Wm82.a4.v1`/`SMDB-*` 零命中 |
| C1 | CH assembly 唯一 | `SELECT DISTINCT assembly_key FROM variant_facts WHERE release_key=...` == `['Wm82v4.0']` |
| C2 | release 隔离 | 非活动 release 记录 0 |
| C3 | 变异命中的 gene 存在 | 孤儿 `gene_surrogate_id`（无对应 `genes.id`）== 0 |
| C4 | 坐标边界 | `genes.start/end`、`variant_facts.position` 不越界 |
| C5 | 受控枚举 | variant_type ∈ {SNP,INS,DEL,MNV,SV}；impact ∈ {HIGH,MODERATE,LOW,MODIFIER} |
| P1 | checksum | 逐对象/文件 SHA-256 命中 manifest |
| P2 | provenance 完整 | `source`/`tool`/`checksum_sha256` 非空 |

> 种子工具在写入后（或 `--check` 时）输出上述校验结果；QA 用 `scripts/validate-release-data.sh`
> （t7）确认。

---

## 7. CLI 契约

```
seed-release-data.sh [options]

Options:
  --source-dir <DIR>         真实数据源目录（必需）
  --release-id <N>           已存在 draft release id（与 --create-release 二选一）
  --create-release          以 --version/--name/--assembly 新建 draft release
  --version <V>              release.version（默认 0.1.0）
  --name <S>                 release.name（默认 SoyMutDB 0.1.0 — ...）
  --assembly <A>             默认 Wm82v4.0（禁止 Demo 值）
  --species <S>              默认 Glycine max
  --tool <T>                 注入工具名（写 provenance）
  --tool-version <V>         provenance 工具版本
  --batch-size <N>           默认 50_000（CH）/ 10_000（PG 分批）
  --dry-run[=1]              只预检 + 打印 plan，不动库
  --check[=1]                只做输入/格式/checksum/真实性校验，不写库
  --apply[=1]                实际写入（需 SOYMUTDB_SEED_ENABLED=1，见 §8 安全）
  --manifest-out <PATH>      seed-manifest.json 输出路径
  --log-out <PATH>           运行日志（供 G12 归档）
  -h|--help                  帮助
```

**环境变量**：`SOYMUTDB_PG_DSN`（或 `SOYMUTDB_DATABASE_URL`）、`SOYMUTDB_CLICKHOUSE_HOST/PORT/
USER/PASSWORD/DATABASE`、`SOYMUTDB_SEED_ENABLED`（=1 才允许 `--apply` 真正写库）。

**退出码**：`0` 成功；`2` 输入/真实性校验失败（fail-closed）；`3` 目标 release 非 draft/不存在；
`4` 写入失败（事务回滚）；`5` 非法参数。

---

## 8. 脚本（CLI 契约 + 真实 loader）

- **CLI 契约入口**：`scripts/seed-release-data.sh`（bash，参数解析 + 预检 + Demo 拒绝 + 委托）。
- **真实 loader**：`scripts/seed_release_data.py`（python，通用解析+写入）。当前已实现：
  - `parse_fasta` → `chromosomes`；`load_assembly_meta` → `assemblies`；
  - `parse_gff3` → `genes`/`transcripts`/`exons`/`gene_aliases`（含引用一致校验）；
  - `parse_vcf` → `variant_facts`（canonical 字段，确定性 `variant_id`/`gene_surrogate_id`/
    `mutant_line_surrogate_id`，从 `ANN` 取最严重 consequence/impact，并从 ANN 提取
    `gene_id`/`gene_symbol`，受控枚举）；
  - `parse_mutants` → `mutant_lines`；
  - `--check` 只解析+校验+计数；`--plan` 解析+写 `seed-manifest.json`；`--emit-sql` 生成可回放的
    CH `variant_facts` INSERT SQL；`--write` 为 PG(asyncpg)+CH(clickhouse_connect) 适配器（见 §11）。
- **默认 fail-closed**：shell 与 python 都对源数据做真实性校验（存在/格式/Demo 标记 `SMDB-*`/
  `Wm82.a4.v1`/legacy 拒绝/assembly 归一）；`--apply`（--write）需 `SOYMUTDB_SEED_ENABLED=1` 且
  loader 写库适配器已启用，否则不动库、绝不注入示例数据。
- 真实写入的 SQL/表/列以 §2 与 `apps/api/app/models/*`、`infra/clickhouse/upgrade_variant_facts_schema.sql`
  为准。

---

## 9. 回滚与恢复

- **回滚**：`release_id` 级（删除该 release 下 `genes/transcripts/exons/gene_aliases/mutant_lines` +
  CH `variant_facts` 按 `release_key` 删除），不触碰其它 release；配合 `release_service.rollback_release`
  切回上一 active release。
- **备份**：写库前建议按 `deploy/scripts/backup.sh` 先备份 PG/CH/S3（release 写入属于数据变更）。
- **恢复演练**：`verify-restore.sh` 后重跑 `seed` 或 `validate-release-data.sh` 确认数据面。

---

## 10. 证据归档（G12）

| 产物 | 路径 |
| --- | --- |
| 运行日志 | `artifacts/acceptance/data-query/seed-<release_id>.log` |
| 校验输出 | `scripts/validate-release-data.sh` 输出 → `artifacts/acceptance/data-query/validate-release-<release_id>.log` |
| 清单 | `artifacts/acceptance/data-query/seed-manifest.json` |
| Provenance 查询 | `SELECT * FROM provenance WHERE data_set_id IN (...)` |

> **重要（QA 提示）**：`artifacts/` 在 `.gitignore` 中且跨轮次可能被重置。请用
> `SOYMUTDB_EVIDENCE_DIR=<持久目录>`（如 `docs/ops/evidence/`，随交付提交）覆盖默认
> `artifacts/acceptance/data-query/`，或用 `--manifest-out`/`--emit-sql <DIR>`/`--log-out` 显式指定；
> 关键证据建议同时留一份在 `docs/ops/` 或随交付归档（`seed-<release_id>.log` +
> `seed-manifest.json` + `provenance` 查询），避免环境重置丢失。

---

## 11. 待办（实现前需冻结）

1. **数据源与版本**：确认 `Wm82v4.0` 的权威 FASTA/GFF3/VCF 来源、版本、许可（如 Phytozome/NCBI/合作方）。
2. **mutant_line 与变异样本映射**：VCF 样本名 ↔ `mutant_lines.name` 的对应表。
3. **CH canonical 迁移已执行**：`infra/clickhouse/upgrade_variant_facts_schema.sql`（否则查询字段不匹配）。
4. **是否启用 route B**：`--write`/`--apply` 需要明确授权与后台备份；建议先在 staging 跑种子 + validate。
5. **loader 写库适配器**：`scripts/seed_release_data.py` 的解析/`--check`/`--plan`/`--emit-sql` 已实现；
   仅 `--write`（PG `asyncpg` + CH `clickhouse_connect` 插入、写 `data_sets`/`provenance`/`release_data_sets`、
   置 `ready`）待数据源/版本冻结并授权后启用（当前 fail-closed）。
