# BLAST 引擎切 DIAMOND + 富集统计核心 Rust 化

> 2026-10-05。两条**相互独立**的工作流，写在同一文档是因为它们同源于一次
> 性能排查，但没有任何依赖关系，可各自排期。Track A 先做——它修的是一个
> 已存在的缺陷，不是优化。

## Goal

- **Track A**：让 `blastp`/`blastx` 真正跑在 DIAMOND 上（当前默认配置下它们
  硬失败），并接通 `.dmnd` 索引获取路径。
- **Track B**：把 `enrichment_service` 的统计核心从手写 Python 迁到 Rust，
  前提是先补上它现在缺失的数值对拍与基线。

两条都不改变对外 API 契约。

## Architecture

Track A 已有全部代码，缺的是配置与资产：

```
resolve_engine()      已实现按 program 能力分流
  blastp/blastx   → diamond
  blastn/tblastn/tblastx → blast      ← DIAMOND 无等价物，非重复 owner
build_diamond_command() 已实现，12 个 outfmt 列显式写出
parse_diamond_tabular()  已实现
DIAMOND_BIN 存在性检查   已实现，但 auto 模式下是 raise 而非回退  ← 缺陷
```

Track B 的候选是 `apps/api/app/services/enrichment_service.py` 的五个纯数值
函数：`_log_pmf`、`_logsumexp`、`hypergeom_sf`、`benjamini_hochberg`、
`gsea_term_stat`。选它的理由是它在公开 API 热路径上
（`POST /api/v1/tools/enrichment`）、纯计算无 I/O、手写无成熟 C 库兜底、
且已有 1164 行测试网。**不放进 Track A**：一是无关，二是它需要的判据还没建。

## Tech Stack

| Track | 现有 | 目标 |
| --- | --- | --- |
| A | `ncbi-blast+`（`infra/docker/Dockerfile.worker:73`）、Python `subprocess` 编排 | 加 `diamond-aligner`，编排层不动 |
| B | Python 3.14 手写实现，`numpy`/`scipy` 已在 `apps/api` | Rust crate + 进程边界（见下） |

**Track B 的边界选型：先走进程边界，不走 PyO3/FFI。** 理由：本机 cgroup 受限，
`argon2-cffi` 的 `Threading failure`（`_argon2_cffi_bindings` 每次 hash 起工作
线程、Python 层无开关）已经演示过 Rust 扩展在本机的线程问题；且 Python 3.14
的 ABI 每次升级都要重编 wheel。FFI 留作性能判据证明有收益之后的第二选项。

## Baseline/Authority Refs

- `docs/ops/multi-genome-blast.md` — `SOYMUTDB_BLAST_DATABASE_PATHS` 的配置格式与索引来源
- `apps/worker/tests/test_blast_task.py` — 744 行 / 35 用例，含 DIAMOND argv 专项
- `apps/api/tests/test_enrichment.py` — 1164 行
- `docs/aegis/baseline/2026-10-02-w0-rebaseline.md` §8-L — W6「未取得任何性能结论」，本计划沿用其报告口径（median/min/max/spread/样本数，不接受单次计时）
- `AGENTS.md` — 消融协议、`do not commit generated dist/cache`、双站边界

## Compatibility Boundary

- `blastn`/`tblastn`/`tblastx` **保留 BLAST+**。这是能力边界而非历史包袱：
  DIAMOND 无 tblastn，`blast.py:78-81` 的 `DIAMOND_PROGRAMS = {blastp, blastx}`
  与其注释已记录该事实。**不退休 BLAST**。
- 显式 `BLAST_ENGINE=diamond` 且 program 不受支持时**继续 raise**（`:254-259`）。
  该行为是对的：显式指定却静默换工具，运维会以为自己测了 DIAMOND。
- 索引格式是**新增**而非替换：`.dmnd` 与 `.nin/.ndb` 并存，按引擎各取所需。
- Track B 若落地，`enrichment_service` 的公开签名与返回结构不变。

## TDD Route

- mode: `off`
- decision: `skipped`
- authority: 项目配置为 off，且用户未要求严格 TDD
- test posture: 每个 Task 附消融（变异 → 红 → 恢复 → 绿），沿用本仓库既有做法
- verification: 回归靠现有测试网 + 新增断言；性能靠 W6 口径的对比报告

## Tasks

### Task A1 — `auto` 在 DIAMOND 缺失时回退 — **✅ 已完成 2026-10-05**

**根因（比原判断更具体）**：`2debd36aa`（`feat(api,worker): gene structure
import, locus view, footer content, DIAMOND`）只改了 `blast.py` 与
`test_blast_task.py` 两个文件——**未碰任何 Dockerfile / compose / cnb / 文档**。
功能上了，基础设施从未跟上。默认 `BLAST_ENGINE=auto` 对 `blastp` 一律返回
`diamond`，而 `run_blast_command` 在二进制缺失时是 `raise` 不是回退，于是默认
配置下所有 `blastp`/`blastx` 任务硬失败。

**修法与原计划不同，且这个差别是必需的**：存在性检查必须落在
`resolve_engine` 内部，**不能**只改 `run_blast_command`。`blast.py:790-791` 的
注释写明 "One decision drives the binary, the parser and the raw file's
extension together"——同一个 `resolve_engine` 调用还决定输出文件名
（`results.txt` / `results.json`）与解析器。若只在执行层回退，会出现
「跑的是 BLAST、却按 tabular 去解析一个叫 `results.json` 的文件」，正是那段
注释警告的失败模式。

**实施**：`auto` 遇 `blastp`/`blastx` 且 `DIAMOND_BIN` 缺失 → 回落 `blast` 并
`logger.warning`（消息给出两条可操作路径：装 `diamond-aligner`，或设
`SOYMUTDB_DIAMOND_BIN`）。显式 `diamond` 在二进制缺失时仍 `RuntimeError`。

**验证**：
- 新增 4 例（回落 / 存在时仍优先 / 显式不降级 / 核酸程序不受影响），
  消融「去掉存在性检查」→ 1 failed，恢复 → 43 passed
- 端到端：本机无 DIAMOND 时 `resolve_engine("blastp")` 由 `diamond`（→ 抛错）
  变为 `blast`
- 修了两个**既有**测试：`test_auto_engine_routes_each_program_to_the_one_that_implements_it`
  与 `test_auto_is_the_default_engine` 原先依赖宿主机是否装了 DIAMOND，现显式
  固定可用性，使它们只测「能力分流」，可用性交给新增用例——未削弱断言
- worker 全量 494 passed / 24 skipped；ruff clean

### Task A2 — `.dmnd` 索引获取路径

**文件**：`apps/worker/src/soymutdb_worker/tasks/blast.py:355-372`（`resolve_database`）

**现状**：缓存探测只认 `.ndb`/`.nin`：
```python
if (db_path.with_suffix(".ndb")).exists() or (db_path.with_suffix(".nin")).exists():
    return db_path
```
命中失败即从 S3 `blast-dbs/{db_name}` 下载，而那里存的是 BLAST 索引。
**结论：`.dmnd` 在当前代码里没有任何获取路径**——这是切 DIAMOND 的真正阻塞点。

**最小变更**：探测增加 `.dmnd`；下载前缀按引擎分流（DIAMOND 用独立前缀，
避免把 `.dmnd` 混进 BLAST 索引目录）。**不得**用「下载后按扩展名猜」的隐式回退。

**兼容性**：`blastn` 等走 BLAST 的任务路径完全不变。

**证明**：单测覆盖三种态（本地已有 `.dmnd` / 需下载 / 本地有 `.nin` 但引擎是 DIAMOND 时应拒绝而非误用）。

### Task A3 — 基础设施装 DIAMOND

**文件**：`infra/docker/Dockerfile.worker:73` 附近、`deploy/conda/README.md:55,233`

**最小变更**：在 worker 镜像与 conda 说明里加 `diamond-aligner`。`Dockerfile.migrate-clickhouse:10` 已把「analyses 全栈」列为刻意排除项，确认 DIAMOND 不受该注释影响。

**兼容性**：纯新增包。

**证明**：`docker compose build worker` 后 `command -v diamond`；本机验证 `DIAMOND_BIN.exists()` 为真。

### Task A4 — 参数白名单：`--quiet` 与 `--id`

**文件**：`apps/worker/src/soymutdb_worker/tasks/blast.py`（`DIAMOND_PARAM_FLAGS`、`DIAMOND_ALLOWED_PARAMS`）

**现状**：用户给的目标命令里有 `--quiet` 与 `--id 30`，二者都不在白名单，
会被 `validate_diamond_parameters` 拒绝并抛 `Disallowed DIAMOND parameter`。

**必须先定的语义问题**：`--id 30` 是序列一致性下限。对 DIAMOND `blastp`
默认（非 sensitive）模式，`--id` 的语义与 BLAST 不同；植物基因组重复序列多，
设 30% 可能把大量真实同源过滤掉。**在 A4 动工前需确认这 30% 是业务真实需求
还是从 BLAST 命令里带过来的习惯写法**——这一步不要跳过，也不要在计划里替用户假设。

`--quiet` 无语义风险（只抑制进度输出），可直接加。

**兼容性**：新增可选参数，默认不启用，不改变既有 argv。

**证明**：每个新参数一条「构造出的 argv 含该标志」用例 + 一条「未传时不含」用例；
消融：从 `DIAMOND_PARAM_FLAGS` 移除 → 构造用例转红。

### Task A5 — 建库与真机验证

**文件**：`docs/ops/multi-genome-blast.md` 增补 DIAMOND 建库小节

**内容**（用户提供的命令，经核对可用于 DIAMOND）：
```bash
diamond makedb -p 4 --in TAroport11_pep_20220914-longest.fa --db TAroport11_pep_20220914-longest.dmnd
diamond makedb -p 4 --in Xnip-v7-pep-longest.fa              --db Xnip-v7-pep-longest.dmnd
diamond blastp --out G126--blast-tair11.txt \
  --query G126-cat-merge-utr_prot_logst.fa \
  --db TAraport11_pep_20220914-longest.dmnd \
  -e 1e-10 --outfmt 6 --max-target-seqs 1 --id 30 --threads 4
```

**三处必须修正后再执行**：
1. 该命令注释写「tblastn比对」，但命令是 `blastp`（`--query ..._prot_...` 蛋白
   + `--db ..._pep_...` 蛋白库）。DIAMOND **没有 tblastn**。按命令本身是
   蛋白对蛋白，DIAMOND 是对的；注释需改，否则后人会按注释去迁核酸查询。
2. `--outfmt 6` 必须补 `DIAMOND_OUTFMT6_COLUMNS` 的 12 个列名。只写 `6` 会
   输出 DIAMOND 默认列序，解析器按位置取列就会静默错位。
3. `--id 30` 见 Task A4，前置未确认前不要执行。

**验证判据**：同一查询分别跑 DIAMOND 与 BLAST，比对 top hit 集合与
`bitscore`/`pident`。**不要求逐位相同**（两者打分算法不同），要求
top-1 一致且 top-`--max-target-seqs` 召回不显著劣化；偏差需记录而非掩盖。

### Task B1 — 补 scipy 数值对拍（**迁移前置，不可跳过**）

**文件**：`apps/api/tests/test_enrichment.py`

**现状**：第 70 行 docstring 声明 "Edge cases mirroring scipy"，但全仓 grep
`scipy` 只命中这行注释，**没有任何 `import scipy` 的实际对拍**。手写的
`hypergeom_sf` 与 `scipy.stats.hypergeom.sf` 的一致性从未被验证过。

**最小变更**：新增对拍用例，覆盖 N/K/n/k 的边界组合（k 低于最小重叠 → 1.0；
高于最大 → 0.0；N=K；n=0）与常规值的双侧一致性。

**为什么这是前置**：迁移要求 Rust 输出与**当前 Python 实现**逐位等价，而
"当前实现"本身未被验证过。没有这一步，迁移后数值变化无法归因。

### Task B2 — 取性能基线

**判据**：报告强制打印 median / min / max / spread / 样本数（沿用 W6 口径）。
在真实负载（基因集规模取自 `gene_annotations` 实际分布）下测
`hypergeom_sf` 与 `benjamini_hochberg` 的耗时占比。

**若基线显示占比不显著，则 Track B 终止**并写进文档——记录「测了、不值得迁」
比默默不做更有价值。

### Task B3 — Rust crate 与双跑对拍

**边界**：进程边界（独立 crate + 简单 IPC），不引入 PyO3。理由见 Tech Stack。

**等价判据**：Rust 实现与 Python 实现对同一输入**逐位相同**（f64 精确相等，
允许显式声明的 ULP 容差并写进测试名）。不等价即停，不进入 Task B4。

### Task B4 — 切流与回退

保留 Python 实现作为可回退路径一个版本；切流后跑一次全量 `test_enrichment.py`
与 W6 口径的性能对比；**下一个版本删除 Python 实现**（这是 retirement track，
删除需另行确认）。

## Verification

| Task | 判据 |
| --- | --- |
| A1 | 新增回退用例 + 消融转红；`test_blast_task.py` 全绿 |
| A2 | 三态覆盖；消融（去掉 `.dmnd` 探测）转红 |
| A3 | 镜像内 `diamond --version` 成功 |
| A4 | 每参数正反用例；A4 前置语义问题已确认 |
| A5 | top-1 一致 + 召回偏差已记录 |
| B1 | 对拍用例通过；无 scipy 时明确 skip 而非静默通过 |
| B2 | 报告含五项统计量；不显著则终止 Track B |
| B3 | 逐位等价；不等价即停 |
| B4 | 全量回归 + 性能对比不劣化 |

## Risks

1. **A1 修完不等于 DIAMOND 生效**。回退后默认仍跑 BLAST，只有 A2（索引）+
   A3（装包）+ A4 完成且 A5 验证后，DIAMOND 才真正承接流量。四者缺一都会
   静默停在 BLAST，必须在 A5 显式确认 `resolve_engine` 的结果。
2. **`.dmnd` 索引体积与构建时间**未实测。`diamond makedb -p 4` 用 4 线程，
   大基因组库的构建时间需在 A5 前用一个小库先试。
3. **`--id 30` 可能改变生物学结论**。见 A4。这是业务决策不是技术决策。
4. **Track B 可能以「不值得迁」结束**。B2 就是为此设的止损点。
5. 本机无 BLAST 也无 DIAMOND 二进制，A3/A5 无法在本机验证，需在具备镜像的
   环境执行——**不得把「本机跑不了」记作「已验证」**。

## Retirement

- **不退休 BLAST+**。`blastn`/`tblastn`/`tblastx` 仍需要它，能力边界有据。
- **不退休 Python 富集实现**直到 B4 完成并另行确认删除。
- 本计划不产生新的重复 owner：`blastp` 的 owner 是 DIAMOND，`blastn` 的 owner
  是 BLAST，`resolve_engine` 只是路由器。
