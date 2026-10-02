# Route B —— 虚拟数据本地验证证据（VIRTUAL ITERATION ONLY）

> **已归档（2026-10-01）**：一次性的基础模式验收战役记录（操作手册仍在 ops/）。继任：`docs/ops/README.md` 及其下的现行运维手册；部署事实见 `docs/dev/project-status.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../../ARCHIVE.md)。

> 本目录为 **非生产虚拟数据** 驱动的 Route B seed loader 验证证据（t18）。**仅验证解析/校验/plan/emit**，
> **未执行任何写库**（未调用 `--write`/`--apply`）。产物由 `scripts/seed_release_data.py` 生成，
> 使用 `SOYMUTDB_EVIDENCE_DIR=docs/ops/evidence/route-b`（受 Git 跟踪）。

## 命令与结果（可复现）

数据源：`scripts/fixtures/route-b-virtual/`（VIRTUAL TEST DATA，无 Demo 标记）；
`--release-id 9001`（虚拟非生产 id）、`--assembly VirtualSoy1.0`。

| 命令 | 结果 | 产物 |
| --- | --- | --- |
| `... --check` | exit 0：`chromosomes=2 genes=2 transcripts=1 exons=2 aliases=3 variants=3 mutants=2` | `check.log` |
| `... --plan` | exit 0：plan 计数同上；写 manifest | `plan.log` + `seed-manifest.json` |
| `... --emit-sql DIR` | exit 0：生成可回放 `variant_facts.sql`（canonical、`release_key='9001'`、确定性 variant_id、gene_id/gene_symbol+consequence/impact 自 ANN 提取） | `emit.log` + `variant_facts.sql` |

说明：`variant_facts.sql` 为纯演示行级映射（CH 侧无自增 FK），PG 侧（assemblies/chromosomes/genes/…）
含自增 FK，`--emit-sql` 不生成（需 apply 时解析 id）。本目录产物在 `--write` 未授权前不得用于生产。

## 红线核对

- ✅ 未执行 `--write`/`--apply`（无任何写库路径命中）。
- ✅ 无 Demo 标记（`SMDB-*`/`Wm82.a4.v1`/`referenceGenome`/`Williams82`）。
- ✅ 全程使用虚拟数据，非真实生产数据。
