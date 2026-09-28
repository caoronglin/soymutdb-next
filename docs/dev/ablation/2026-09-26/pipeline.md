# W5 流水线消融实验报告（VCF 身份 / 选定样本基因型 / finalize 汇总清理 / 跨装配分区 / staging DDL）

- 仓库：`/mnt/data02/T25ronglin/code/web`
- HEAD：`8e78116fdbcda533a9399f36680cacedcc08dac2`（`git rev-parse HEAD` 已核对）
- 日期：2026-09-26
- 实验目录：`.validation/ablation/pipeline/`
- 判定口径：
  - **GUARD-ACTIVE**：消融后行为发生翻转，该因子是真守卫。
  - **GUARD-INERT**：消融后行为不变，可能是死代码或冗余。
  - **GAP**：对照（真实实现）本身已失败。

## 目标与范围

对 W5 工作流的五个高风险因子做**真实代码**消融：每个场景先跑真实生产函数/流程作为对照，再只中和**一个**因子作为消融臂。生产源码不做永久修改，全部通过 `.validation/ablation/pipeline/harness_<n>.py` 导入真实函数并用 `monkeypatch`/重建单一函数完成。

范围：

1. `compute_variant_id` 是否把 `assembly` 纳入哈希（ASM-01）。
2. `_pick_mutant_line` 返回的选中样本下标是否真正用于读取基因型（对照 `gt_types[0]`）。
3. `variant_finalize._purge_release_summaries` 是否防止汇总重复累加。
4. `_carry_untouched_partitions` 的 `assembly_key NOT IN` 是否防止跨装配同染色体误删。
5. staging DDL（`variant_facts_staging`）在 production DDL 与升级脚本中的闭包。

不在范围：真实 DB 服务器、MinIO、真实 cyvcf2 二进制 VCF（用等价属性对象复刻行构建逻辑）、PostgreSQL 集成（无 PG 服务）。

## 环境与命令

- Python：`apps/worker/.venv/bin/python`（3.14.6，含 pytest、`import chdb`）。
- 无需 DB 服务器；场景 3/4 使用 chdb 嵌入式引擎 + `apps/worker/tests/fixtures/variant_facts_schema.sql`。
- pytest 统一加 `-p no:cacheprovider`。
- harness 运行前缀统一为 `cd apps/worker && PYTHONPATH=src:. .venv/bin/python ../../.validation/ablation/pipeline/harness_<n>.py`。

## 逐场景结果表

| 场景 | 对照 | 消融 | 判定 | 证据 |
| --- | --- | --- | --- | --- |
| S1 装配进入 variant_id | v4 != v5（不碰撞） | 去掉 `{assembly}` 后 v4 == v5 碰撞 | **GUARD-ACTIVE** | `harness_1.py` exit 0；`ingest.py:343` |
| S2 选中样本基因型 | 从 `gt_types[mutant_sample_idx]` 读，报告 heterozygous | 改读 `gt_types[0]` 得 homozygous_ref / unknown | **GUARD-ACTIVE** | `harness_2.py` exit 0；`ingest.py:609,621` |
| S3 finalize 汇总清理 | 重发布后 facts=2/summary=2 | 跳过 purge 后 facts=2/summary=4 | **GUARD-ACTIVE** | `harness_3.py` exit 0；`variant_finalize.py:252` |
| S4 跨装配分区清理 | v4_rows=1 v5_rows=1 | `NOT IN`→`IN` 后 v4_rows=0 v5_rows=2 | **GUARD-ACTIVE** | `harness_4.py` exit 0；`variant_finalize.py:241` |
| S5 staging DDL 闭包 | 12 passed / 1 skipped, exit 0 | 不适用（命令证据） | **对照通过（DDL 已闭包）** | `init.sql:145`、`upgrade_variant_facts_schema.sql:85` |

**判定计数：GUARD-ACTIVE 4，GUARD-INERT 0，GAP 0，闭包对照通过 1。**

---

## S1：`compute_variant_id` 是否把 `assembly` 纳入身份（ASM-01）

**决定行**：`apps/worker/src/soymutdb_worker/tasks/ingest.py:343`

```python
key = f"{release_id}|{assembly}|{chromosome}|{position}|{ref}|{alt}"
```

同一 release 下仅 `assembly` 不同的两个变异：

- 对照（真实 `compute_variant_id`）：`v4 != v5`，`collide=False`。
- 消融（同一 sha256 + `int.from_bytes`，键去掉 `assembly`）：`v4 == v5`，`collide=True`。

命令：`cd apps/worker && PYTHONPATH=src .venv/bin/python ../../.validation/ablation/pipeline/harness_1.py` → exit 0。

```
CONTROL  v4=10588736968576557241 v5=1018530362187511727 collide=False
ABLATION v4=17459332979158985104 v5=17459332979158985104 collide=True
VERDICT GUARD-ACTIVE
```

**结论：GUARD-ACTIVE。** `assembly` 确实参与身份哈希；去掉即发生 v4/v5 身份碰撞（跨装配同名位点静默合并）。性质上已闭包，但见“未验证项”：`compute_variant_id` 自身无独立单测，只有本消融与下游 DDL 测试间接覆盖。

---

## S2：基因型是否读取“被选中样本”的列

**决定行**：`apps/worker/src/soymutdb_worker/tasks/ingest.py:609`（`_pick_mutant_line(...)` 返回 `mutant_sample_idx`）与 `:621`（`zygosity = determine_zygosity(int(gt_types[mutant_sample_idx]))`）。

对照复刻 `_iter_vcf_base_rows` 的行构建，读取 `gt_types[mutant_sample_idx]`；消融只把读取下标换成 `0`。

| 用例 | 对照 | 消融 | 翻转 |
| --- | --- | --- | --- |
| A：`samples=[control, mutant-a]`，`gt=[0,1]` | `zygosity=heterozygous`，`mutant_line='mutant-a'` | `zygosity=homozygous_ref` | 是 |
| B：反序 `samples=[mutant-a, control]`，`gt=[1,0]` | `zygosity=heterozygous` | `zygosity=heterozygous` | 否（此配置下消融臂巧合相同） |
| C：多 ALT `alts=[G,T]`，`gt=[0,1]` | 两行均 `heterozygous` | 两行均 `homozygous_ref` | 是 |
| D：缺失 GT `gt=[3,1]` | `zygosity=heterozygous` | `zygosity=unknown` | 是 |

命令：`... harness_2.py` → exit 0；关键输出：

```
CASE-A control_zygosity = heterozygous | ablation = homozygous_ref
CASE-D control_zygosity = heterozygous | ablation = unknown
VERDICT GUARD-ACTIVE
```

对照在四种用例下均正确报告**被选中样本**（`mutant-a`）的基因型与正确 `mutant_line`，即使第 0 列是 control/缺失。**结论：GUARD-ACTIVE。** 用例 B 说明优势排序使消融臂在该反序配置下恰好读到同一列，属配置性巧合而非守卫失效；判定以 A/C/D 为准。

---

## S3：`_purge_release_summaries` 是否防止汇总重复累加

**决定行**：`apps/worker/src/soymutdb_worker/tasks/variant_finalize.py:252`（对 8 张 release 作用域汇总表 `ALTER TABLE ... DELETE ... SETTINGS mutations_sync = 1`）。

两臂均：stage 2 条 facts → finalize → 再次 stage 同样 2 条 → 再 finalize（模拟重试/二次导入）。消融只把 `_purge_release_summaries` 打成 no-op。

命令：`cd apps/worker && PYTHONPATH=src:. .venv/bin/python ../../.validation/ablation/pipeline/harness_3.py` → exit 0。

```
CONTROL  after_finalize_1=(2, 2) after_finalize_2=(2, 2)
ABLATION after_finalize_1=(2, 2) after_finalize_2=(2, 4)
VERDICT GUARD-ACTIVE
```

格式为 `(facts, gene_impact_summary FINAL cnt)`。消融后二次 finalize 使汇总翻倍到 4（事实仍为 2，因为分区 drop 后从 staging 重建），即 `SummingMergeTree` 上出现不一致汇总。**结论：GUARD-ACTIVE。**

---

## S4：跨装配同染色体的分区清理

**决定行**：`apps/worker/src/soymutdb_worker/tasks/variant_finalize.py:241`（`where += " AND assembly_key NOT IN (...)"`，由 `:225` 的 `imported_assemblies` 驱动）。物理分区为 `(release_key, chromosome)`，v4/v5 同染色体共分区，drop 会同时删除两者。

构造：base 预置 v4(id10,Chr01) + v5(id20,Chr01)；stage v5(id21,Chr01) 后 finalize。消融只把 carry 的 `NOT IN` 翻成 `IN`（不搬运“本次未导入装配”的行）。

命令：`cd apps/worker && PYTHONPATH=src:. .venv/bin/python ../../.validation/ablation/pipeline/harness_4.py` → exit 0。

```
CONTROL  v4_rows=1 v5_rows=1
ABLATION v4_rows=0 v5_rows=2
VERDICT GUARD-ACTIVE
```

对照：导入 v5 后 v4 行存活（1 行），v5 仅剩新行（1 行）。消融：v4 行被同一分区 drop 连带删除（`v4_rows=0`，跨装配误删），v5 还残留旧 id20（`v5_rows=2`）。**结论：GUARD-ACTIVE。**

---

## S5：staging DDL 闭包（E1 证据）

命令：

```
cd apps/worker && .venv/bin/python -m pytest tests/test_clickhouse_production_ddl.py tests/test_legacy_clickhouse_migration.py tests/test_vcf_import.py -q -p no:cacheprovider
```

退出码 0，**真实结果：12 passed, 1 skipped**（唯一 skip 为 `test_vcf_import.py:132` 的 PostgreSQL 集成，需 `SOYMUTDB_RUN_POSTGRES_INTEGRATION=1`）。

DDL 闭包事实：

- `infra/clickhouse/init.sql:145` `CREATE TABLE IF NOT EXISTS variant_facts_staging`（生产 DDL 已含 staging）。
- `infra/clickhouse/upgrade_variant_facts_schema.sql:85` 同样 `CREATE TABLE IF NOT EXISTS variant_facts_staging`（升级路径已含）。
- `tests/test_clickhouse_production_ddl.py:82 test_production_init_ddl_declares_the_staging_table` 直接在 chdb 上加载**生产 init.sql** 并断言 staging 表存在、含 `variant_id/release_key/assembly_key/import_id/batch_id` 列，且 `:92` 起跑通 stage→verify→finalize。
- `tests/test_legacy_clickhouse_migration.py` 用真实 `upgrade_variant_facts_schema.sql` 跑迁移并验证幂等重跑。

**结论：staging DDL 在 HEAD 已闭包**（init + upgrade 双路径），并有真实嵌入引擎测试守护。

## GAP 与 INERT 发现

- **无 GAP**：五个场景的对照臂全部按预期工作（S1–S4 harness exit 0 且对照值正确；S5 全绿）。
- **无真正的 GUARD-INERT**：仅 S2 用例 B（反序且 mutant 恰在 0 列）在消融下数值不变，是配置巧合，非死代码。
- 一个结构性观察（非本消融因子，未单独判定）：`variant_finalize.py:241` 的 `NOT IN` 若翻成 `IN`，除跨装配误删外还会让被替换装配的旧行残留（S4 消融臂 `v5_rows=2`），说明“排除被替换装配”与“搬运其他装配”是同一个 `NOT IN` 的两面。

## 未验证项

- 未用真实 cyvcf2 二进制 VCF 驱动，S2 用了属性等价的 `FakeVariant` 复刻 `_iter_vcf_base_rows` 行构建；未验证 cyvcf2 的 `gt_types` 具体 dtype。
- 未连真实 ClickHouse/PostgreSQL 服务；S3/S4 在 chdb 上运行（与既有 acceptance 测试同一模式）。
- S3 只验证了一轮重试循环，未验证多次/并发重试。
- S4 只覆盖单 release、单共享染色体、v4/v5 两装配；未覆盖多染色体混合。
- `compute_variant_id` 无独立单测，仅由本消融与下游测试间接覆盖。
- S5 的 1 个 skip（PG 集成）未在本环境执行。

## 原始证据附录

### A1 S1 运行

```
$ cd apps/worker && PYTHONPATH=src .venv/bin/python ../../.validation/ablation/pipeline/harness_1.py
CONTROL  v4=10588736968576557241 v5=1018530362187511727 collide=False
ABLATION v4=17459332979158985104 v5=17459332979158985104 collide=True
VERDICT GUARD-ACTIVE
EXIT=0
```

### A2 S2 运行

```
$ cd apps/worker && PYTHONPATH=src .venv/bin/python ../../.validation/ablation/pipeline/harness_2.py
--- A samples=[control, mutant-a] gt=[0,1] ---
CONTROL  alt=G   type=SNP  mutant_line='mutant-a' ml_sid=2368075201 zygosity=heterozygous
ABLATION alt=G   type=SNP  mutant_line='mutant-a' ml_sid=2368075201 zygosity=homozygous_ref
--- B samples=[mutant-a, control] gt=[1,0] ---
CONTROL  alt=G   type=SNP  mutant_line='mutant-a' ml_sid=2368075201 zygosity=heterozygous
ABLATION alt=G   type=SNP  mutant_line='mutant-a' ml_sid=2368075201 zygosity=heterozygous
--- C multi-ALT alts=[G,T] samples=[control, mutant-a] ---
CONTROL  alt=G   type=SNP  mutant_line='mutant-a' ml_sid=2368075201 zygosity=heterozygous
CONTROL  alt=T   type=SNP  mutant_line='mutant-a' ml_sid=2368075201 zygosity=heterozygous
ABLATION alt=G   type=SNP  mutant_line='mutant-a' ml_sid=2368075201 zygosity=homozygous_ref
ABLATION alt=T   type=SNP  mutant_line='mutant-a' ml_sid=2368075201 zygosity=homozygous_ref
--- D missing-GT col0 gt=[3,1] samples=[control, mutant-a] ---
CONTROL  alt=T   type=SNP  mutant_line='mutant-a' ml_sid=2368075201 zygosity=heterozygous
ABLATION alt=T   type=SNP  mutant_line='mutant-a' ml_sid=2368075201 zygosity=unknown

CASE-A control_zygosity = heterozygous | ablation = homozygous_ref
CASE-D control_zygosity = heterozygous | ablation = unknown
VERDICT GUARD-ACTIVE
EXIT=0
```

### A3 S3 运行

```
$ cd apps/worker && PYTHONPATH=src:. .venv/bin/python ../../.validation/ablation/pipeline/harness_3.py
CONTROL  after_finalize_1=(2, 2) after_finalize_2=(2, 2)
ABLATION after_finalize_1=(2, 2) after_finalize_2=(2, 4)
VERDICT GUARD-ACTIVE
EXIT=0
```

### A4 S4 运行

```
$ cd apps/worker && PYTHONPATH=src:. .venv/bin/python ../../.validation/ablation/pipeline/harness_4.py
CONTROL  v4_rows=1 v5_rows=1
ABLATION v4_rows=0 v5_rows=2
VERDICT GUARD-ACTIVE
EXIT=0
```

### A5 S5 pytest

```
$ cd apps/worker && .venv/bin/python -m pytest tests/test_clickhouse_production_ddl.py tests/test_legacy_clickhouse_migration.py tests/test_vcf_import.py -q -p no:cacheprovider
......s......                                                            [100%]
12 passed, 1 skipped in 1.26s
EXIT=0
# -rs: SKIPPED [1] tests/test_vcf_import.py:132: set SOYMUTDB_RUN_POSTGRES_INTEGRATION=1 to run PostgreSQL integration
```

### A6 关键源码行核验

```
ingest.py:343            key = f"{release_id}|{assembly}|{chromosome}|{position}|{ref}|{alt}"
ingest.py:209            def _pick_mutant_line(
ingest.py:609            mutant_line_name, ml_sid, mutant_sample_idx = _pick_mutant_line(
ingest.py:621            zygosity = determine_zygosity(int(gt_types[mutant_sample_idx]))
variant_finalize.py:198  def _carry_untouched_partitions(
variant_finalize.py:241  where += f" AND assembly_key NOT IN ({placeholders})"
variant_finalize.py:252  def _purge_release_summaries(
init.sql:145             CREATE TABLE IF NOT EXISTS variant_facts_staging (
upgrade_variant_facts_schema.sql:85  CREATE TABLE IF NOT EXISTS variant_facts_staging (
```

### A7 harness 文件

- `.validation/ablation/pipeline/harness_1.py` — S1 装配哈希消融
- `.validation/ablation/pipeline/harness_2.py` — S2 选中样本基因型消融
- `.validation/ablation/pipeline/harness_3.py` — S3 汇总 purge 消融
- `.validation/ablation/pipeline/harness_4.py` — S4 跨装配 carry 消融
