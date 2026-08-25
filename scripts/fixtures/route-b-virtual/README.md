# Route B —— 非生产虚拟 fixture（VIRTUAL TEST DATA）

> **声明**：此目录为 **虚拟/测试数据（NON-PRODUCTION）**，**不是** 真实生产数据，也 **不含任何**
> SoyMutDB Demo 占位（无 `SMDB-*`、无 `Wm82.a4.v1`、无 `referenceGenome`、无 `Williams82` 等）。
> 用于在本机验证 Route B seed loader（`scripts/seed_release_data.py`）的解析/校验/plan/emit，
> **严禁** 用于生产注入。由 data-platform(t18) 生成。

## 文件

| 文件 | 内容 | 说明 |
| --- | --- | --- |
| `genome.fa` | 2 条虚拟序列 `TestChr01`(6000bp)/`TestChr02`(4000bp) | 非真实参考基因组 |
| `assembly.meta` | `name=VirtualSoy1.0`、`species=Glycine max` | 虚拟组装元数据；name 非生产、不含演示符号 |
| `annotations.gff3` | 2 个 gene（`VitGene.01G000100`、`VitGene.02G000200`）+ mRNA + 2 exon | 虚拟基因模型 |
| `variants.vcf` | 3 条变异（含 `ANN` SnpEff 注释：missense/synonymous/stop_gained） | 虚拟变异，含受控 consequence/impact |
| `mutants.tsv` | 2 个虚拟品系 `VitM1`/`VitM2` | 虚拟突变品系元数据 |

## 生成方式（可复现）

由 t18 用确定性逻辑（固定的序列/坐标/注释）生成，非随机。粒度刻意足够小以便肉眼核对。
重新生成/校验：
```bash
# 校验（parse + validate + counts）
SOYMUTDB_EVIDENCE_DIR=docs/ops/evidence/route-b \
  bash scripts/seed-release-data.sh --source-dir scripts/fixtures/route-b-virtual \
  --release-id 9001 --assembly VirtualSoy1.0 --check
# plan（写 seed-manifest.json）与 emit-sql（写 variant_facts.sql）
SOYMUTDB_EVIDENCE_DIR=docs/ops/evidence/route-b \
  bash scripts/seed-release-data.sh --source-dir scripts/fixtures/route-b-virtual \
  --release-id 9001 --assembly VirtualSoy1.0 --plan
SOYMUTDB_EVIDENCE_DIR=docs/ops/evidence/route-b \
  bash scripts/seed-release-data.sh --source-dir scripts/fixtures/route-b-virtual \
  --release-id 9001 --assembly VirtualSoy1.0 --emit-sql docs/ops/evidence/route-b
```

## 断言

- 不含 Demo 标记：`grep -rnE 'SMDB-|Wm82\.a4\.v1|referenceGenome|Williams82' .` 应为空。
- 预期 `--check` 计数：`chromosomes=2 genes=2 transcripts=1 exons=2 aliases=3 variants=3 mutants=2`。
- 预期 `--emit-sql` 生成可回放 `variant_facts.sql`（canonical 字段、确定性 `variant_id`、`release_key='9001'`）。
- **绝不 `--write`/`--apply` 写库**。
