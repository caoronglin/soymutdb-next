# Route B 首版数据源：QA 选型 / 许可核对 / 验收映射清单

> **状态**：本文由 QA（qa-acceptance）为**加速 captain 首版真实数据源拍板**而作，是 `G10` 放行前置 ①
> 「权威数据源与版本/许可」的**验收侧核对清单**。与 `docs/ops/route-b-seed-data-design.md`（t12，实现）、
> `docs/ops/first-release-data-plan.md`（t3，数据面标准）、`docs/ops/production-readiness.md`（t1，G10 标准）一致。
> admin 注意：本文**不虚构具体来源的外部事实**（URL/基因数/许可原文等须由 data-platform 对源记录核实），
> 只给出**作选型比较时必满足的 QA 验收映射**与**拍板所需的最小信息**。
>
> **QA 红线**：`G10` 只接受**真实、权威、可溯源、无 Demo 占位**的数据；来源、版本、许可、checksum、provenance
> 缺一不可。选型必须以「能否满足 D1/C1/C5/P1/P2」为准，而非仅看「有无数据」。

---

## 0. captain 需拍板的四项（最小集）

| # | 需拍板 | 说明 | 影响 Gate |
|---|---|---|---|
| A | **选定来源** | Phytozome / NCBI / Ensembl Plants / SoyBase 之一（或指定其它权威来源） | G10 前置① |
| B | **assembly 版本** | 具体版本标识（如 `Wm82.a2.v1`、`GCF_004193775.1`）+ 与仓库符号 `Wm82v4.0` 的映射 | D1 / C1 |
| C | **许可** | 是否允许公开再分发 / 商用；引用 DOI / 出处 | P2 / 合规 |
| D | **是否含 VCF+ANN** | 若合并变异缺失 `ANN`（导致 consequence/impact 为空），需确认是否用 SnpEff 注释（谁来做） | C5 |

> **命名对齐（重要）**：仓库内部 assembly key 为 `Wm82v4.0`（`settings_registry`/`VITE_DEFAULT_ASSEMBLY`/`config.py`
> `default`）；公开版本名如 `Wm82.a2.v1`（Phytozome）或 `GCF_004193775.1`（NCBI）可能不同。`loader --assembly`
> 可覆盖（无需改码），但**必须统一**、绝不可混用多个符号——否则 `variant_facts.assembly_key` 会出现多值（违 C1）
> 或 `D1` 身份不一致。建议：内部统一 `Wm82v4.0`，源映射到该 key，并在 provenance 记录**源 assembly 名**。

---

## 1. 选型比较：候选来源 vs QA 验收门

> 下表所列来源名沿用 data-platform 提出的候选集；具体字段（assembly 名、是否有 GFF3/VCF、是否含 ANN、
> 基因/变异规模、许可原文）**须由 data-platform 对源记录核实后回填**。QA 给出的是
> **每一项对验收门的要求**。

| 候选来源 | assembly 版本（待核实） | FASTA | GFF3 | VCF(含 ANN) | 许可（待核实，是否可再分发/商用） | 引用 DOI（待核实） | 备注 |
|---|---|---|---|---|---|---|---|
| Phytozome | e.g. `Wm82.a2.v1` | 是 | 是 | 视批次（视是否提供变异/ANN） | 需确认（Phytozome 使用条款） | 需确认 | 常见大豆参考；注意命名 `Wm82.a2.v1` vs `Wm82v4.0` |
| NCBI (RefSeq) | e.g. `GCF_004193775.1` | 是 | 是 | 是（dbSNP/ClinVar 类） | 公共领域/开放 | 需确认 | 命名不同 `GCF_...`，需映射；VCF 需确认 ANN/效应注释 |
| Ensembl Plants | `Glycine_max` 版本 | 是 | 是 | 视版本 | 需确认 | 需确认 | 注释丰富；assembly 版本需与 `Wm82v4.0` 对齐 |
| SoyBase | 视提供 | 是 | 是 | 视提供 | 需确认 | 需确认 | 大豆专项；需确认稳定性与 assembly 版本 |

> **QA 提示**：不要只看「有数据」；要核 **assembly 是否等于仓库默认 `Wm82v4.0`（或可安全映射且不混用）**、
> **GFF3 是否含 gene/transcript/exon/alias**、**VCF 是否含 ANN（C5 需要 consequence/impact）**、
> **许可是否可公开再分发**。

---

## 2. 每个候选必须满足的验收门（选型判据）

| 验收门 | 来源须提供 | QA 如何验证（真实证据） |
|---|---|---|
| D1 身份 | `assembly` 可唯一映射到 `Wm82v4.0`；`species=Glycine max`；`version` 可追溯 | `releases.version=0.1.0`、`assemblies.is_default`；`validate-release-data.sh` D1 |
| C1 单一 assembly | 数据集只含一个 assembly（无混入其它符号） | `SELECT DISTINCT assembly_key FROM variant_facts WHERE release_key=…` == `['Wm82v4.0']` |
| C3 基因引用一致 | `variant_facts.gene_id`（来自 ANN GeneID / info GENE）须在 `genes.id` 中存在；孤儿（有 `gene_surrogate_id` 但无对应 `genes.id`）== 0 | `SELECT count(DISTINCT v.gene_id) FROM variant_facts v WHERE v.release_key='<RID>' AND v.gene_id NOT IN (SELECT id FROM genes)` == 0 |
| C5 受控枚举 | `variant_type` ∈ {SNP,INS,DEL,MNV,SV}；`impact` ∈ {HIGH,MODERATE,LOW,MODIFIER}（需 VCF ANN 或 SnpEff 注释） | `variant_facts` 枚举计数==0 非法值；非枚举计数==0 |
| P1 checksum | 逐文件 `sha256` 可与 `seed-manifest.json` 命中 | `sha256sum` 比对 manifest |
| P2 provenance | `source`/`tool`/`tool_version`/`checksum_sha256` 非空 | `SELECT count(*) FROM provenance WHERE source='' OR tool='' OR checksum_sha256=''`==0 |
| 无 Demo | 数据不含 `SMDB-*`/`Wm82.a4.v1`/`referenceGenome`/`Williams82` | `grep` 扫描 + `check-production-artifact.sh` |

> **真实数据核对项（C3 相关，落地时复核，非当前阻塞）——GeneName/GeneID 分离**：
> - `gene_symbol` 来自 ANN `GeneName`（parts[3]，人类可读符号）；`gene_id` 来自 ANN `GeneID`（parts[4]，稳定 ID）。
>   真实 Wm82 数据通常**自然分离**（GeneName≠GeneID）；虚拟 fixture 因 GeneName=GeneID 是刻意为之。
> - 观测/核对命令：`SELECT count(*) FROM variant_facts WHERE release_key='<RID>' AND gene_symbol='' AND gene_id<>''`
>   作为「缺 GeneName」观测项；并与源 ANN 抽样比对 GeneName/GeneID。
> - 若源 ANN 字段顺序/命名与 SnpEff 标准不同，data-platform 按数据调整解析（`_vcf_info`/`_parse_vcf_info` 兜底），
>   QA 从原始 info 复核。

---

## 3. Toolchain 要求（选型时确认）

| 项 | 要求 | 若无，影响 |
|---|---|---|
| FASTA (`genome.fa[.gz]` + `.fai`) | 染色体名唯一、每条 `length>0`、`is_default` 唯一 | 影响 `assemblies`/`chromosomes` |
| GFF3 (`annotations.gff3[.gz]`) | 含 `gene`/`mRNA`/`exon` 特征 + ID/Parent 一致 | 影响 `genes`/`transcripts`/`exons`/`gene_aliases`；C4 坐标边界 |
| VCF (`variants.vcf[.gz]`) | `CHROM/POS/REF/ALT` 合法；**若需 C5 的 consequence/impact，须有 `ANN`** | 无 ANN → 需 SnpEff 注释步骤（归属需拍板） |
| `assembly.meta` | name/version/species/fasta_url/fai_url/description | 影响 `assemblies` 元数据 |

---

## 4. 增量路径（建议）

**先基因、后变异**：
1. 先仅带 FASTA + GFF3 + mutants（若需），跑 `--check`/`--emit-sql` 出 `seed-manifest.json`，QA 先核 D1/D2/P1/P2（基因/assembly）——最短路径先让 G10 的「基因/assembly 面」落地。
2. 变异 VCF（含 ANN）到位后再启 `--write` 写 `variant_facts`，QA 核 C1/C5 后放行。

> 这样即便变异注释（ANN/SnpEff）仍在排队，也可先推进基因面数据，避免整链阻塞在变异注释上。

---

## 5. 获取 / 校验命令骨架（数据源一敲定即可跑）

> 骨架；真实 URL/checksum 以源记录为准。规范文件名 + 记录 sha256。

```bash
# 1) 建数据源目录
mkdir -p docs/ops/evidence/route-b/source
cd docs/ops/evidence/route-b/source

# 2) 下载（示例；替换为真实 URL）
# FASTA
wget -O genome.fa.gz "<FASTA_URL>"; gzip -t genome.fa.gz
# GFF3
wget -O annotations.gff3.gz "<GFF3_URL>"; gzip -t annotations.gff3.gz
# VCF（含 ANN 优先）
wget -O variants.vcf.gz "<VCF_URL>"; gzip -t variants.vcf.gz
# mutants.tsv（可选；样本名 ↔ mutant_line 映射）
wget -O mutants.tsv "<MUTANTS_URL>"

# 3) 记录 sha256（P1）
sha256sum genome.fa.gz annotations.gff3.gz variants.vcf.gz mutants.tsv > source.sha256

# 4) 写 assembly.meta（把公开 assembly 名映射到内部 Wm82v4.0）
cat > assembly.meta <<'JSON'
{"name":"Wm82v4.0","version":"<公开版本如 Wm82.a2.v1 / GCF_004193775.1>","species":"Glycine max","fasta_url":"<...>","fai_url":"<...>","description":"<来源+许可+引用>"}
JSON

# 5) QA 先出实现层校验（解析/校验/无 Demo/计数 + manifest + SQL 回放）
SOYMUTDB_EVIDENCE_DIR=docs/ops/evidence/route-b \
  python3 scripts/seed_release_data.py --check \
  --source-dir scripts/fixtures/route-b-virtual --release-id <RID> --manifest-out docs/ops/evidence/route-b/seed-manifest.json
# 注：将 --source-dir 指向上面的真实 source 目录；--release-id 为真实 draft release id。
# check/plan/emit 不写库：SOYMUTDB_SEED_ENABLED 未设 → --write exit 4（guard 生效）。

# 6) 真实写入（数据源/迁移确认 + 授权后）
SOYMUTDB_SEED_ENABLED=1 SOYMUTDB_EVIDENCE_DIR=docs/ops/evidence/route-b \
  python3 scripts/seed_release_data.py --write \
  --source-dir docs/ops/evidence/route-b/source --release-id <RID>
```

---

## 6. QA 复核真实证据后如何放行 G10 / 解 G12

一旦 captain 拍板（A/B/C/D）+ data-platform 在 staging 产出真实证据：
1. 我据 §2 逐项核 D1/C1/**C3**/C5/P1/P2 + **GeneName/GeneID 分离**（`validate-release-data.sh` + `variant_facts` 查询输出 `validate-release-<rid>.log`）。其中 C3 用上述 `gene_id NOT IN (SELECT id FROM genes)`==0；GeneName/GeneID 用 `gene_symbol='' AND gene_id<>''` 观测项 + 源 ANN 抽样比对。
2. `seed-manifest.json` 逐文件 sha256 命中、`provenance` 完整、无 Demo。
3. 全部通过 → G10 转 ✅；`--write` 已注入真实数据 → 跑 `validate-release-data.sh` 过 G12。
4. 任一失败 → G10/G12 维持 No-Go 并记录整改。

---

## 7. 待办 / 依赖

- **captain**：拍板 A（来源）+ B（版本/命名映射）+ C（许可）+ D（VCF ANN / SnpEff 归属）。
- **data-platform**：对源记录核实候选来源的 assembly 版本/规模/ANN/许可/DOI；敲定后跑 `--check`/`--emit-sql`。
- **qa-acceptance**：本清单维护 + 按 §2 复核真实证据。
