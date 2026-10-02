# W2 消融实验报告：assembly 与跨版本（ASM-01～ASM-05）

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../../ARCHIVE.md)。

- 日期：2026-09-26
- 工作树 HEAD：`8e78116fdbcda533a9399f36680cacedcc08dac2`（git rev-parse 实测）
- 执行者：子代理 B（W2）
- 判定口径：`GUARD-ACTIVE`（消融单一因素后行为翻转，对照通过）／`GUARD-INERT`（消融后不变）／`GAP`（对照即失败）
- 证据分级：E1 = 真实运行；E2 = 源码追踪（附精确行号）。

---

## 1. 目标与范围

对 `docs/dev/database-core-contract.md` §3 契约矩阵中 W2 的 assembly 身份与跨版本不变量，逐场景做「对照 → 单因素消融 → 比对」：

- **ASM-01/02**：v4 与 v5 同 accession 共存且按 assembly 标注；assembly 作用域查询不得泄漏到另一命名空间。
- **ASM-03**：未限定 assembly 的歧义 accession 必须在**全量匹配集**上判定；`limit=1` 不得报告 `ambiguous=False`。
- **ASM-04**：v4 exact 命中且存在 `gene_crosswalks` 行时，必须浮出显式跨版本链接／`match_type=cross-version`。验证 2026-09-26 审计中的已知 GAP 是否仍在。
- **ASM-05**：相似但未建 crosswalk 的基因不得因字符串相似被当作跨版本亲属。
- **附**：别名匹配保持 assembly 作用域（anchor `::test_gene_search_marks_exact_and_alias_matches`）。

所有消融均用 pytest `monkeypatch` 完成，**未持久修改任何生产源码**。

### 锚点（均已先读源码再运行）

| 锚点测试 | 源码 |
| --- | --- |
| `apps/api/tests/test_search_database_integration.py::test_v4_v5_same_accession_coexist_and_are_labelled` | `apps/api/app/services/search_service.py` |
| `...::test_unscoped_ambiguity_is_judged_over_full_match_set` | `search_service.py:532-545,798-824` |
| `...::test_crosswalk_data_is_explicit_and_linked` | `apps/api/app/models/genomic.py:264-308` |
| `...::test_similar_genes_without_crosswalk_stay_unrelated` | `search_service.py` `_gene_match_conditions` |
| `...::test_gene_search_marks_exact_and_alias_matches` | `search_service.py:306-317,746-757` |

关键源码事实（E2）：
- `search_service.py:288-321` `_gene_match_conditions` 在 `assembly_id is not None` 时追加 `Gene.assembly_id == assembly_id`（第 319-320 行）——assembly 作用域隔离点。
- `search_service.py:532-545` 注释明确「ambiguity 属于整个 release 作用域匹配集，而非被截断的页」，并在 `assembly_id is None` 时调用 `_gene_assembly_distribution`；`search_service.py:798-824` 用不带 limit 的聚合查询实现。
- `search_service.py:28` 只 import `Assembly, Gene, GeneAlias`——**未 import `GeneCrosswalk`**。
- `apps/api/app/schemas/search.py:29` 定义了 `MatchType.CROSS_VERSION = "cross-version"`，但 `grep -rn "CROSS_VERSION" apps/api/app` 只命中该定义本身。

---

## 2. 环境与命令

```
Node v24.19.0；apps/api/.venv/bin/python 3.14.6
PostgreSQL 16 @ 127.0.0.1:55432 (user soymutdb, trust)；二进制 $PWD/.mamba-root/envs/postgres16/bin
```

每个 pytest 运行前重建独立库：

```bash
cd /mnt/data02/T25ronglin/code/web
PG_BIN=$PWD/.mamba-root/envs/postgres16/bin
$PG_BIN/dropdb -p 55432 -h 127.0.0.1 -U soymutdb --if-exists abl_assembly
$PG_BIN/createdb -p 55432 -h 127.0.0.1 -U soymutdb abl_assembly
```

对照命令（exit 0，`5 passed, 7 deselected, 1 warning in 1.31s`）：

```bash
cd apps/api && SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_assembly' \
  .venv/bin/python -m pytest tests/test_search_database_integration.py -q -p no:cacheprovider \
  -k "coexist_and_are_labelled or judged_over_full_match_set or crosswalk_data_is_explicit_and_linked or stay_unrelated or marks_exact_and_alias_matches"
```

消融脚本（新增，未改生产码）：`apps/api/tests/test_ablation_assembly_scope_and_crossversion.py`

```bash
# 对照+消融对比，exit 0，5 passed
.venv/bin/python -m pytest tests/test_ablation_assembly_scope_and_crossversion.py -q -p no:cacheprovider -s -k "not must_be_exposed"
# ASM-04 因素移除消融，exit 0，1 passed
.venv/bin/python -m pytest tests/test_ablation_assembly_scope_and_crossversion.py -q -p no:cacheprovider -s -k "dropping_crosswalk"
# ASM-04 期望契约，exit 1，1 failed（GAP）
.venv/bin/python -m pytest tests/test_ablation_assembly_scope_and_crossversion.py -q -p no:cacheprovider -s -k "must_be_exposed"
```

---

## 3. 逐场景结果表

| 场景 | 对照（因素在场） | 消融（只中和一个因素） | 判定 | 证据（命令 + 退出码 + 关键输出行） |
| --- | --- | --- | --- | --- |
| **ASM-01/02** v4/v5 同 accession 按 assembly 隔离 | scoped v4 → `hits=1 assemblies=[1]`；对照 anchor `5 passed` EXIT=0 | monkeypatch `_gene_match_conditions` 丢弃 assembly 谓词 | **GUARD-ACTIVE** | `pytest .../test_ablation_...py -k "not must_be_exposed"` EXIT=0；`[ASM-01 CONTROL] scoped v4 hits=1 assemblies=[1]` → `[ASM-01 ABLATED] scoped v4 hits=2 assemblies=[1, 2]`（anchor 断言 `len==1`，故 anchor 会翻红） |
| **ASM-03** 歧义在全量匹配集判定 | `limit=1` → `len=1 ambiguous=True by_assembly={'3':1,'4':1}` | monkeypatch 中和全量聚合 `_gene_assembly_distribution` → 回落到截断页分支 | **GUARD-ACTIVE** | 同上 EXIT=0；`[ASM-03 CONTROL] len=1 ambiguous=True` → `[ASM-03 ABLATED] len=1 ambiguous=False by_assembly={}` |
| **ASM-04** crosswalk 必须显式浮出 | v4 exact 命中；`results=1`，`match_type=exact`，`cross-version anywhere=False`；DB 中 `crosswalk_rows=1` | 移除因素：删除该 crosswalk 行后重跑 | **GAP**（期望链接缺失；因素对 search 完全无影响） | `-k "must_be_exposed"` **EXIT=1**：`assert 'Glyma.05G000100' in {'Glyma.01G000100'}`；`-k "dropping_crosswalk"` EXIT=0：`with=[('Glyma.01G000100','exact',1,'/genes/...')] without=[...相同...]` |
| **ASM-05** 相似未映射基因不得变跨版本 | `match_types=[text, text] ambiguous=True`；anchor `stay_unrelated` 通过 EXIT=0 | 探针式消融：去掉「必须有 provenance」的要求，把跨 assembly 的文本命中提升为 `cross-version` | **GUARD-ACTIVE** | 同上 EXIT=0；`[ASM-05 CONTROL] match_types=[text, text]` → `[ASM-05 ABLATED] match_types=[cross-version, cross-version]` |
| **别名作用域** 别名匹配保持 assembly 作用域 | scoped v4 → `hits=['GmFT2b'] match_types=[alias]` | 同 ASM-01，丢弃 assembly 谓词 | **GUARD-ACTIVE** | 同上 EXIT=0；`[ALIAS CONTROL] hits=['GmFT2b']` → `[ALIAS ABLATED] hits=['GmFT2b','GmFT2c']` |

对照基线（E1，EXIT=0，`5 passed`）见 §6 `baseline_anchors.log`。

---

## 4. GAP 与 INERT 发现

### GAP-1（ASM-04，确认审计结论在 HEAD 仍成立）：`GeneCrosswalk` 从未被 search 读取

**判定依据（E1，命令 exit 1）**：

```
$ .venv/bin/python -m pytest tests/test_ablation_assembly_scope_and_crossversion.py -q -p no:cacheprovider -s -k "must_be_exposed"
[ASM-04 ROWS] crosswalk_rows=1 target=2
[ASM-04 DESIRED] ids={'Glyma.01G000100'} match_types={<MatchType.EXACT: 'exact'>}
E   assert 'Glyma.05G000100' in {'Glyma.01G000100'}
FAILED ...::test_asm04_crosswalk_must_be_exposed_as_cross_version
== 1 failed, 5 deselected ==  EXIT=1
```

**决定该结论的源码路径**：
- 决定文件：`apps/api/app/services/search_service.py`
  - 第 28 行 `from ..models.genomic import Assembly, Gene, GeneAlias`——**无 `GeneCrosswalk`**；
  - `_search_genes`（664-796 行）只 `join Assembly`，`match_type` 仅由 `rank_expr`（exact/alias/text，696-757 行）派生，无 crosswalk join；
  - `schemas/search.py:29` 的 `MatchType.CROSS_VERSION` 已定义却**无任何生产者**（`grep -rn "CROSS_VERSION" apps/api/app` 仅命中定义行）。
- `grep -rn "GeneCrosswalk" apps/api/app` 仅命中 `models/genomic.py`；生产侧唯一提到 crosswalk 的是 `table_views_service.py:15`（docstring，非查询）。

**因素移除消融（EXIT=0）**证明该因素对 search 端到端「零影响」：

```
[ASM-04 ABLATION] with=[('Glyma.01G000100','exact',1,'/genes/Glyma.01G000100?assembly=1')]
                  without=[('Glyma.01G000100','exact',1,'/genes/Glyma.01G000100?assembly=1')]
1 passed  EXIT=0
```

即：有 crosswalk 行与没有该行，搜索结果逐字段相同。ASM-04 在当前 HEAD 是**真实 GAP**，而非「测试曾经通过」。

### INERT 发现

- 本次 W2 无 `GUARD-INERT`。全部 5 个可控场景的消融都产生了可观测翻转。
- 补充观察（非判定项）：ASM-04 的 anchor 测试 `test_crosswalk_data_is_explicit_and_linked` 只断言 `gene_crosswalks` 表的行级约束与唯一性，**完全绕过 search service**，因此它「通过」并不能证明搜索端消费了 crosswalk——这是 GAP 长期未被测试捕获的直接原因。

### 未被本轮捕获但值得记录

- `MatchType.CROSS_VERSION` 是「已声明、未接线」的枚举值：若未来接线，需同时补 OpenAPI/client 契约与前端展示，本轮未验证。

---

## 5. 未验证项

1. **HTTP 路由层**：全部实验在 `SearchService` 服务层；`/api/v1/search` 路由序列化后 `cross-version` 的 JSON 呈现未跑。
2. **release 不同源的 v4/v5**：仅覆盖「同一 active release 下两个 assembly」（与 anchor 一致）；跨 release 的 unscoped 行为未验证。
3. **crosswalk 关系型别**：只用了 `one_to_one`；`one_to_many` / `many_to_one` / `release_id` 字段对搜索的影响未验证。
4. **反向方向**：`source→target` 已验证；`target→source` 检索（用 v5 accession 找 v4）未验证。
5. **导入管线写入**：worker/导入端是否实际产生 `gene_crosswalks` 行，本轮未跑。
6. **别名跨 assembly 同名但不同 accession 的排序**：只验证了隔离翻转，未覆盖 `limit` 截断下的排序稳定性。
7. **`limit>1` 时 ASM-04 目标是否出现**：在默认 `limit=20` 下 v5 target（不同 accession）也完全缺席，已由 probe 覆盖；更大 limit 未单独跑。

---

## 6. 原始证据附录

日志目录：`.validation/ablation/assembly/`

| 文件 | 内容 | 退出码 |
| --- | --- | --- |
| `baseline_anchors.log` | 5 条 anchor 对照，`5 passed, 7 deselected, 1 warning in 1.31s` | 0 |
| `ablations.log` | ASM-01/02、ASM-03、ASM-04 probe、ASM-05、别名 的对照/消融双行输出，`5 passed, 1 deselected` | 0 |
| `asm04_gap.log` | ASM-04 期望契约失败，`1 failed` | 1 |
| `asm04_ablation.log` | 移除 crosswalk 行输出不变，`1 passed` | 0 |
| `static_evidence.log` | HEAD、`CROSS_VERSION`/`GeneCrosswalk` grep、生产码 git diff | 0 |

生产码未修改证据（`git diff --stat` 仅含先前已存在的 `packages/genome-view-model` 等改动，与本轮无关；`git status --short` 中新增仅 `apps/api/tests/test_ablation_assembly_scope_and_crossversion.py`、`docs/dev/ablation/`）：

```
$ git diff --stat
 apps/jbrowse/package.json | 1 -
 packages/genome-data/package.json | 1 -
 packages/genome-view-model/src/index.ts | 21 +++------------------
 packages/genome-view-model/src/viewport.ts | 2 +-
 packages/genome-view/package.json | 1 -
 pnpm-lock.yaml | 4 ++--
```

关键复现命令汇总（均可重跑）：

```bash
# 对照（EXIT 0, 5 passed）
cd apps/api && SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_assembly' \
  .venv/bin/python -m pytest tests/test_search_database_integration.py -q -p no:cacheprovider \
  -k "coexist_and_are_labelled or judged_over_full_match_set or crosswalk_data_is_explicit_and_linked or stay_unrelated or marks_exact_and_alias_matches"

# 消融对比（EXIT 0, 5 passed）
.venv/bin/python -m pytest tests/test_ablation_assembly_scope_and_crossversion.py -q -p no:cacheprovider -s -k "not must_be_exposed"

# ASM-04 GAP（EXIT 1, 1 failed）
.venv/bin/python -m pytest tests/test_ablation_assembly_scope_and_crossversion.py -q -p no:cacheprovider -s -k "must_be_exposed"
```

---

## 7. 结论

- ASM-01/02、ASM-03、ASM-05、别名作用域：**GUARD-ACTIVE**，保护性因素均在当前 HEAD 真实生效。
- **ASM-04：`GAP`**。`gene_crosswalks` 表有数据、约束与 provenance，但 `apps/api/app/services/search_service.py` 从不读取它，`MatchType.CROSS_VERSION` 无生产者；删除/新增 crosswalk 行对搜索结果零影响。修复点是 `_search_genes` 增加 crosswalk join 并在命中时输出 `match_type=cross-version` + 链接。
