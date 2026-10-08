# DIAMOND / Biopython / pyDEG / Rust：审计报告与实施计划

状态：已进入实现；统计截断修复完成。**2026-10-06：比对链路收敛为 DIAMOND
`blastp` 单一引擎**（NCBI BLAST 的代码、镜像与 conda 依赖均已移除），详见 A 段。
Rust 和 pyDEG 的生产切流尚未完成，且两者都还卡在各自的前置条件上。

本文件是此项工作的唯一计划与审计入口，取代此前版本中未获证据支持的判断。既有数据库、对象存储和队列权威关系保持不变；本轮没有迁移或删除业务数据，没有提交或推送代码。

## 审计发现与处理

| 等级 | 已核实问题 | 本轮处理 |
| --- | --- | --- |
| P1 | API 默认发送 BLAST 的 `dust` / 布尔 `soft_masking`，DIAMOND 校验拒收；API 的 `matrix` 又不在 BLAST 白名单中。旧队列任务与新 API 默认须分别处理。 | **已随引擎收敛消解**：这些是 NCBI 专属选项，本部署不再有 BLAST 引擎。`word_size` / `dust` / `soft_masking` 现由 API schema 显式拒绝，不静默忽略。 |
| P1 | 即使选到 BLAST，遮罩键名也不能原样下发。NCBI BLAST 2.16.0 实测：`blastp` / `tblastn` / `tblastx` 只有 `-seg`，`-dust` 会打印 USAGE 并失败；只有 `blastn` 有 `-dust`。蛋白任务一旦带上显式 `dust`，此前会在执行期炸掉。 | 翻译层随 BLAST 引擎一并删除。DIAMOND 遮罩用 `--masking` / `--soft-masking`，由其自身参数校验负责；API 不再接受 BLAST 遮罩字段。 |
| P1 | 线程数没有单一 owner：参数字典可覆盖任务预算，0 / 负数 / 极大值可通过校验，BLAST 分支还会生成重复的 `-num_threads`。 | 线程预算收敛到任务层 owner，参数只能调低、不能抬高；正整数且受部署 `BLAST_MAX_THREADS`（默认 4）约束；只下发一次 `--threads`。 |
| P1 | Worker DIAMOND 白名单生成不存在的 `--word-size`；上层 `word_size` 曾被静默忽略。 | 删除无效翻译。`word_size` 改为显式拒绝，不再静默忽略。 |
| P1 | 默认执行 DIAMOND 2.1.14，在 4 GiB 虚拟内存上限下连 180 aa 查询也在临时存储初始化时失败。 | 真实子进程复现；单独缩小 block-size、文件缓冲和分配器 arena 均未解决。匹配版本源码显示 HitBuffer 存在每 bin 1 GiB 预留路径；`--bin 1` 单变量验证成功。本轮固定一个查询 bin，保留原资源上限。大型生产负载仍需独立测量。 |
| P1 | 手写超几何右尾最多累积 100000 项，截断会丢掉主要质量，绝非总能忽略。`(N,K,n,k)=(2000000,1000000,1000000,1)` 返回 `0.0`，SciPy 返回 `1.0`。 | 移除固定截断；按均值选择直接右尾或左尾补集，在实际求和起点初始化对数 PMF，输出限定在 `[0,1]`。以 SciPy 与穷举小支持集回归；不替换为本机更慢的 SciPy 单项调用。 |
| P1 | 格式错误的 `BLAST_DATABASE_PATHS` 原先悄悄降级为空映射，意外取消数据库白名单。 | 配置必须为非空名称到非空路径字符串的 JSON 对象；无效配置使启动失败。只有显式 `{}` 进入 legacy 模式。 |
| P2 | legacy 缓存只识别核酸单文件，漏掉蛋白三件套和 `.dmnd`；下载未校验所选索引，宽前缀可能混入相邻库；直接写最终文件可留下半成品。 | 只认精确的 `blast-dbs/<name>.dmnd`；宽前缀中的 `makeblastdb` 产物不被接受；临时文件原子替换，下载后校验非空。索引内容本身仍由真实加载器判定。 |
| P2 | 单独安装 DIAMOND 会使只有 BLAST 蛋白索引的老部署失败；后期另行选引擎还可能造成输出和解析器错配。 | **已消解**：不再存在第二个引擎，也就没有引擎与索引错配的可能。老部署需按 `docs/ops/multi-genome-blast.md` 重建 `.dmnd`。 |
| P2 | `.exists()` 把目录和不可执行文件视为已安装；Docker 无 DIAMOND，默认路径又与 apt 安装位置不一致。 | 检查普通文件与执行权限，经 PATH 发现 apt/Conda 实际目录；Docker 加 `diamond-aligner`，Conda 配置只保留 `diamond`。镜像实际构建验证尚待 Docker 运行环境。 |
| P2 | DIAMOND 12 列输出没有查询总长，持久化一直为零。 | 2026-10-06 曾用 Biopython `SeqIO` 恢复长度；2026-10-08 改为 API/worker 共用蛋白 FASTA 契约并明确定义计数单位。多记录总长为各记录之和；记录级结果模型扩展另行验收。 |
| P3 | 本地预览 CLI 的环境默认与显式路径修复缺少回归。 | 增加缺失/空值、默认、覆盖、每次建 parser 重新读环境的测试。 |

关键代码与回归：

- [Worker 比对实现](../../../apps/worker/src/soymutdb_worker/tasks/blast.py)、[API 提交参数](../../../apps/api/app/services/blast_service.py)、[跨引擎与真机回归](../../../apps/worker/tests/test_diamond_integration.py)。
- [富集统计核](../../../apps/api/app/services/enrichment_service.py)、[独立数值 oracle](../../../apps/api/tests/test_enrichment_oracles.py)、[可重跑基准](../../../scripts/benchmark_enrichment_core.py)。
- [预览配置回归](../../../apps/api/tests/test_local_preview_cli.py)、[部署操作说明](../../ops/multi-genome-blast.md)。

### 旧报告纠偏

- 配置映射原本就能直达 `.dmnd`；缺陷是 legacy 缓存、参数、安装与路由不闭合，并非整个 Worker 完全没有 `.dmnd` 路径。
- DIAMOND 2.1.14 的默认 12 列与现有解析器相同。显式列名用于固定契约，不代表已复现默认列错位；`max-target-seqs` 默认是 25，并非全部命中。
- 实测子命令收敛后仅保留 `blastp`。核酸/翻译比对（`blastn` / `blastx` / `tblastn` / `tblastx`）在本部署不可提交。
- `--id 30` 是比对输出的身份比例过滤，与 API 目前标为客户端使用的 `percent_identity` 不同；本轮没有偷偷修改其 OpenAPI 语义。
- API 的 `dust` / `soft_masking` / `word_size` 字段已随引擎收敛退役；显式传入被拒绝，不改名也不透传。
- 既有手算和 `math.comb` 测试已覆盖部分统计；新增的是独立 SciPy oracle，旧稿“从未数值验证”的表述过度。截断问题现已另行真实复现。
- 不再引用未经本项目测量的 100–1000 倍提速，也不由文件行数认定热点。
- `2debd36aa` 的实际统计是 62 个文件变化；其缺少 DIAMOND 部署接入，不等于整个提交只改了两个文件。
- Argon2 库的实现语言、Python ABI 更新是否重建 wheel 均取决于具体实现和打包策略，不作为本项目迁移依据。

## A：比对链路验收

A1–A4 本轮实现：参数、索引、命令、解析、落库形成一致契约，Docker/Conda 声明接入；A5 真机验证记录在文末，镜像级验证另有前置条件。

**2026-10-06 收敛：比对链路只剩 DIAMOND `blastp`。** 原先的 `auto` 引擎选择、
按程序路由、NCBI BLAST 执行分支与回滚开关已全部删除。下表取代原路由表：

| 条件 | 行为 |
| --- | --- |
| `blastp`；`.dmnd` 就绪；DIAMOND 可执行 | DIAMOND / 12 列 tabular |
| `blastn` / `blastx` / `tblastn` / `tblastx` | 不支持的程序错误 |
| BLAST 专属参数 `word_size` / `dust` / `soft_masking` | 参数错误（拒绝，不静默忽略） |
| DIAMOND 缺失、不可执行或指向目录 | 二进制错误；**不换引擎** |
| 索引缺失、为空或不是 `.dmnd`（含 `makeblastdb` 产物） | `DatabaseIndexUnavailable` |
| 数据下载或 `BLAST_DATABASE_PATHS` 配置异常 | 错误；不伪装成功 |

提交面只有 `BlastSubmitProgram`（单值 `blastp`）；响应面保留五值
`BlastProgram`，因为历史 `blast_jobs` 行必须仍能反序列化。这是读取侧兼容，
不是第二套提交词表。PostgreSQL 的 `blast_program_enum` 未改动。

科学验收独立于软件烟测：在真实大豆/拟南芥数据上统计召回、identity、coverage、
命中排名和资源使用。`--max-target-seqs 1` 不证明唯一同源或正交关系。

回滚：收敛前部署若仍需 NCBI BLAST，需回退代码提交并恢复 BLAST 蛋白索引；
本部署已无 `SOYMUTDB_BLAST_ENGINE` 开关。

## B：统计核心与 Rust 门禁

数值契约：`hypergeom_sf(N,K,n,k) = P(X >= k)`，SciPy oracle 是 `hypergeom.sf(k-1,N,K,n)`；BH 保持输入顺序、正确处理 ties/0/1。无实际需求证明时不另增统计权威实现。

当前 oracle：小支持集穷举绝对误差 `1e-12`；大背景测试相对误差 `5e-8`、绝对误差 `1e-14`；深右尾（56000/2000000 量级）另用 `rel=1e-8, abs=0` 并要求结果为正，防止"塌成 0 但绝对误差看不出来"。这些是当前回归上限，不是已认可的未来 Rust 精度退化额度；科学显著性阈值附近还需结论级测试。

基准环境：Python 3.14.6 / SciPy 1.18.1，单线程 BLAS；固定随机种子，预热一次，11 次测量。700 组大豆规模的**合成** term 统计；baseline 为 `7ec14b41f`。时间单位秒：

| 实现 | 中位数 | 最小 | 最大 | 跨度 | 样本数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 修复前 Python | 0.063953 | 0.063743 | 0.064429 | 0.000686 | 11 |
| 修复后 Python | 0.055484 | 0.055370 | 0.058609 | 0.003239 | 11 |
| SciPy 单项 | 0.112597 | 0.112046 | 0.117233 | 0.005187 | 11 |
| SciPy 批量 | 0.073393 | 0.073299 | 0.073561 | 0.000263 | 11 |
| BH 10000 项 | 0.003158 | 0.003123 | 0.003246 | 0.000124 | 11 |
| 合成 ORA 流水线 | 0.080728 | 0.080310 | 0.081211 | 0.000901 | 11 |

合成流水线含 56000 个背景基因、700 个 term、500 个输入基因，排除 SQL 读取。cProfile 含插桩成本，不等于上述墙钟：总计 0.311 秒，超几何核累计 0.245 秒，BH 未进入前 12 热点。该数据说明统计核在此合成负载有占比，不证明线上瓶颈。

较早基准阶段查询旧测试库时 `to_regclass('public.gene_annotations')` 为 `NULL`；
这只是当时状态。最终全新库迁移后该表存在、行数为 0；当前缺的是可用真实注释
负载，不再以“表不存在”作为 Rust 前置缺口。两次都没有真实富集请求性能结论。

Rust 分阶段要求：

1. 获取 assembly/release/ontology 明确的真实注释负载，保存不含敏感信息的 `[N,K,n,k]` cases 与 checksum；记录 SQL/映射构建/数值核/序列化分别耗时、p50/p95、RSS 和并发压测。
2. 对 Python 优化、SciPy 批量、Rust 批量候选使用同一输入与线程预算；统计显著性、极小尾概率、ties、异常值、排序须一致。BH 仅在真实占比值得时迁移。
3. 用测量选择 PyO3/maturin 或独立进程；比较边界拷贝、启动/IPC、取消、崩溃隔离、部署 wheel/ABI 支持。不提前宣布某一种方案胜出。
4. 候选整体 API 路径 p95 至少改善 20%，数值不退化、RSS 不恶化、并发取消可复现后，才实施逐步切流和显式回滚；20% 是本计划目标，尚非已取得结果。
5. 真正切流时保留一处统计 owner，Python 参考实现仅作为测试 oracle，不把双路径永久在线化。

### B1：Python 核心优化（已实现，2026-10-06）

原算法每步调用多个 `log`，并为整个尾部保存 Python float 列表。保留一处
`enrichment_service.hypergeom_sf` 统计 owner，改为从靠近均值的一端向外做 PMF
比例递推，以起点 PMF 缩放、`math.fsum` 补偿求和，再在 log 空间恢复概率；
左尾补集使用 `expm1`。仍遍历完整支持集，不设固定截断；BH、背景定义、
assembly/release 过滤及响应契约均未更改。删除仅供旧求和路径使用的 `_logsumexp`。

同机 Python 3.14.6 / SciPy 1.18.1，单线程、一次预热、11 次测量，700 组合成 cases：

| 负载 | 本次优化前中位数 | 本次优化后中位数 | 耗时降低 |
| --- | ---: | ---: | ---: |
| 超几何核 700 cases | 58.952 ms | 27.535 ms | 53.29%（约 2.14 倍） |
| 合成 ORA（不含 SQL） | 79.786 ms | 50.189 ms | 37.10% |

证据为仓库根目录下 `.validation/enrichment-before-streaming.json` 与
`.validation/enrichment-after-streaming.json`；上方旧表是此前测量，不能与本表混算。
20 万项支持集的单次 `tracemalloc` 峰值为 800 bytes；回归要求低于 256 KB，
该值只表示 Python 跟踪分配，不表示整个 API RSS。增加均值两侧、正支持集下界、
深右尾、显著性/BH 判定和空间回归；SciPy 为独立 oracle。剩余误差来源包含
`lgamma` 大数差分，未声称任意规模下精确或已达到生产 p95 目标。

### B2：Rust 候选与生产迁移（待执行）

只有取得真实 scoped 注释负载后才进入候选开发。先比较当前优化后的 Python，
不能以优化前的慢实现作为唯一对手。Rust 工具链安装、候选构建和切流是三个
不同验收状态；主服务 Python pin 保持 3.14。任务细分见 D 节。

## C：Biopython 与 omicverse.bulk.pyDEG

### C1 Biopython：已开始实际接入

Worker 已声明 Biopython，原稿遗漏了实施项。2026-10-06 在查询长度恢复和烟测 fixture 中实际使用过 `Bio.SeqIO` / `Bio.Seq`；2026-10-08 查询提交与执行改用下述共享标准库契约，Biopython 留在烟测 fixture 中。C1 的输入 checksum provenance 尚未交付，不将依赖声明或局部接入当作 C1 完整验收。

本部署后续序列适配范围仅为 `blastp` 的蛋白 FASTA：多记录、重复 ID、空记录、
换行、模糊氨基酸和末尾 `*` 的处理须显式记录并回归。A/C/G/T 也都是合法氨基酸，
不得仅因组成像核酸而判无效；不重开 `blastx`、翻译表或反向链执行路径。
新增 provenance 需带原始 assembly/release/输入 checksum，保持旧任务可读。
成熟的 Biopython 操作不为“全 Rust”目标重写；适配代码归现有 worker 所有，
只有出现多个调用方和重复实现时才抽出共用模块。

**2026-10-08 修正 C1 的归属判断**：本段原写“适配代码归现有 worker 所有”，但
蛋白 FASTA 规则现在有 API 与 worker 两个调用方，按同段自己的条件（“出现多个调用方
和重复实现时才抽出共用模块”）必须共用，否则就是 M0-1 刚退役的那种重复 owner。唯一
owner 定为 [共享契约包](../../../packages/jobs-py/src/soymutdb_jobs/protein_fasta.py)
的 `parse_protein_fasta`：仅标准库、无 ORM、无 Biopython，API 与 Celery worker 都调用
它。这里是有界设计例外：仅提交结构/字符规则收敛到共享标准库解析器，不为 Rust 重写
Biopython 的其他成熟操作。初稿仍保留 API/service 的旧字符校验，实际不能据此宣称两侧
一致；推送前复核后才将 blastp helper 委托共享契约，并拒绝 Unicode 大写折叠为氨基酸。
`Bio.SeqIO` 从生产查询长度计算处退役，仍是 worker 依赖并在 DIAMOND 烟测 fixture 中使用。
共享包自己的测试此前不在根门禁内，已补入
`scripts/verify-backend-tests.sh`，否则这个新 owner 会是没有证据的地盘。

### C2 pyDEG：明确独立交付，尚未切流

用户给的是 omicverse API，不是同名独立包，也不是要求用 Scanpy 偷换。已读取官方 [pyDEG 参考](https://omicverse.readthedocs.io/zh-cn/latest/api/reference/omicverse.bulk.pyDEG.html)：`omicverse.bulk.pyDEG(raw_data)` 接受 genes × samples 的原始 count DataFrame，提供 normalization / deg_analysis 等方法；本轮尚无实际 omicverse 环境烟测。

待实施闭环：

1. 在隔离分析环境中验证 omicverse 具体版本与 Python 3.14、NumPy/SciPy/AnnData 的依赖和 import 能力；若上游版本约束不兼容，显式记录独立 worker 环境，不更改主项目 Python pin，也不默默替换分析库。
2. 新建内部 `pyDEG` adapter，严格检查非负原始 counts、gene 行/sample 列方向、重复 ID、metadata 对齐、分组重复和 contrast。TPM/FPKM/log 表达不得冒充原始 count 数据。
3. 使用 omicverse 的公开接口，固定统计 method 和 contrast 方向；统一输出 gene_id（assembly-scoped）、log2FC、pvalue、padj 及原始库字段映射。
4. 纳入现有 Celery job contract、取消/重试/幂等、MinIO 原始输入和产物、PostgreSQL job 状态；记录库版本、参数、随机种子、输入 checksum、assembly/release、方法与引用。
5. 用 toy counts 与公开数据验证对照方向、重复样本、零 count、小样本、稳定排序、错误恢复、后续富集衔接，并比较已知参考输出。

此项保留在计划中；本轮不宣称差异表达功能上线。

## D：剩余迁移任务的执行计划

### 目标、架构与兼容边界

依据用户“优化核心算法、做好迁移任务计划”的要求，先交付 B1 的 Python 优化，
再按证据推进 Biopython、Rust 候选与 omicverse pyDEG。生产迁移尚未执行。
参考 `docs/dev/database-core-contract.md` 和本计划；保留用户并行修改的 W0 baseline。
起始工作树为 `main` / `7ec14b41f`，已有未提交改动，继续使用原工作区，不提交或推送。

数据权威不变：PostgreSQL 管 job/权限/release，MinIO 管输入与产物，Redis 为
可丢弃队列，ClickHouse 不新增统计或差异表达权威状态。API 继续拥有富集统计
入口；worker 的 `AnalysisJobStore` 拥有作业状态转换。无第二套永久在线统计 owner。

TDD Route：`off / skipped`，未要求严格 test-first；每个任务均有回归与实证验收。
执行方式为单 owner 顺序实施。数值优化是现有函数内局部修改，未扩展服务职责；
迁移是跨层任务，分别交付环境、契约、计算、作业、界面和切流，避免一次改完。

### 执行任务与前置关系

| 任务 | 当前状态 / 依赖 | 代码或配置 owner | 产物与退出条件 |
| --- | --- | --- | --- |
| M0 环境与负载盘点 | 环境/工具已验证；真实负载仍缺 | [profiler](../../../scripts/profile_enrichment_workload.py) | 既往 fixture 测量不证明生产 p95；导入 owner 缺失判断已撤回，≥20% 原门槛保留；新报告明确 database replay 与 synthetic |
| M0-1 既有导入链路加固 | 2026-10-08 收敛切片；根门禁证据见下 | [API 服务](../../../apps/api/app/services/gene_annotation_import_service.py)、[CLI](../../../scripts/import_annotations.py) | 重复 worker owner 已按确认退役；仅 draft、不可变/幂等、dry-run、解析字节摘要与实际行数核对；真实上游文件仍缺 |
| M1 蛋白 FASTA 边界 | 提交结构/字符边界已实现；推送前修正后的 fresh 证据见下；C1 完整资格仍未满足 | [共享契约](../../../packages/jobs-py/src/soymutdb_jobs/protein_fasta.py)、API `schemas/blast.py`、worker `tasks/blast.py` | API/service/worker 共用规则，拒绝空记录、重复 ID、Unicode 非残基；`query_len` 为明确的项目计数，不是引擎 qlen；输入 checksum 与记录级结果身份尚未闭合 |
| M2 Rust 批量候选 | 待执行，依赖 M0 真实负载 | API 统计 owner、benchmark；crate 位置在选择边界后确定 | 同一批量输入对拍；比较 PyO3 与进程成本，记录取消/故障/RSS；先验收候选，不接线上请求 |
| M3 omicverse 环境资格 | 待执行，可独立于 M2 | `deploy/conda/`；新增 pyDEG 环境配置为拟新增文件 | 固定经 resolver 验证的 omicverse 版本及锁文件；真实 import + toy counts 全流程；主项目 Python pin 不降级 |
| M4 pyDEG 计算 adapter | 待执行，依赖 M3 | 拟新增 worker `tasks/analyses/pydeg.py` | genes×samples 原始 counts、metadata/contrast 校验；公开 API 真调用；统一结果、失败和 provenance，不用 Scanpy 代替 |
| M5 作业/持久化契约 | 待执行，依赖 M4 输出契约 | `packages/jobs-py/src/soymutdb_jobs/{contract,schemas}.py`，API model/schema/service，worker store | task/queue/payload/analysis type 同步；真实 PostgreSQL migration 与旧 job 读取；outbox 原子投递、重送幂等、取消/重试验收 |
| M6 API/client/界面闭环 | 待执行，依赖 M5 | OpenAPI、`packages/api-client`、现有 `/analyses` | 参数、上传、状态、取消、结果下载；assembly/release/对照方向可见；研究者权限与跨用户负向测试，双站制品和 E2E |
| M7 受控生产切流 | 待执行，依赖所有相关门禁 | 现有 CI 与部署脚本 | 独立镜像实跑、科学参考数据、性能/取消/崩溃证据齐全后开启；回滚演练通过；不把环境 smoke 当上线 |

M2 与 M3/M4 可独立准备，但 M5 前必须固定 pyDEG 输入、输出和运行环境；M7 中
Rust 和 pyDEG 分别切流，避免同时改变两个统计责任边界。

### Rust 验收与退役

1. M0 数据记录 assembly/release/ontology/source checksum；分离 SQL、映射、核、
   序列化耗时。固定请求集和并发，至少报告单请求与并发请求的 p50/p95/RSS。
2. M2 批量输入为整数 `[N,K,n,k]`，输出保持顺序；上下尾、可表示的深尾、边界、
   BH ties/0/1/异常值和阈值判定须与独立 oracle 一致，沿用 B 节精度要求。
3. 无证据不迁 BH，也不重写 SeqIO。PyO3 的 GIL/线程释放、wheel/ABI，进程的
   IPC/拷贝/退出码和取消均计入端到端成本，不只比较纯核时间。
4. 保留原验收门槛：同一真实负载、相同完整请求路径与并发下，p95 改善 ≥20%，
   数值 oracle、取消/故障、RSS 与部署资格同时通过后才考虑切流。
   M0 的少量 fixture 分阶段重放中，核中位数占约 7.6%～8.5%，SQL 占约 63%～69%；
   这只是“先检查 SQL/映射收益”的方向性线索。阶段中位数之比不等于完整路径 p95
   的可优化比例，更不能证明生产门槛“数学上不可能”。撤回上一轮据此降低门槛的判断。
   真实负载缺失时不得用 fixture 达成 M2 验收；若真实负载收益不足，可以不迁 Rust，
   但不得把纯核提速改称完整路径收益。
5. 切流通过部署版本选择一处 owner；失败回滚上一份可启动制品，既有结果不重算。
   原 Python 算法留在测试参考侧，旧生产分支退役；不新增静默双引擎 fallback。

### pyDEG 输入、契约变更与隔离

- M3 若 omicverse 与 Python 3.14 的约束冲突，先记录 resolver/import 证据，再
  形成专用 worker 环境决策；隔离 Python 版本属于待确认设计，主环境保持原 pin。
  规划专用 `analyses_pydeg` 队列，名字为拟定值，写入 jobs-py 契约后才成为权威；
  避免无 omicverse 的通用 analyses worker 消费该任务。
- M4 只收非负、有限、整数原始 counts。重复 gene/sample ID、转置矩阵、负值、
  小数/TPM/FPKM/log 数据、metadata 缺失或额外样本、单组/不足重复、无效 contrast
  均在边界验证。不得隐式合并、转置或以零补齐；零 count 基因的过滤规则记录在报告。
- 明确 contrast 为 treated 相对 control，log2FC 正值表示 treated 更高；方法名和
  多重检验修正规则由真实公开 API 验证后固定，不能仅填一个占位方法完成验收。
- 结果字段为 assembly-scoped gene_id、log2FC、pvalue、padj；库输出中的 NA、
  零 count、过滤原因保留可追溯含义，不伪装为 0/显著。列映射、稳定排序、版本、
  随机种子、输入/metadata checksum、方法/引用、assembly/release 写入产物 manifest。
- 已核实持久化 `analysis_type_enum` 只有 `fastp` / `scanpy`；M5 增加 `pydeg` 是
  PostgreSQL schema 变更，不是只扩 Python Literal。新增 Alembic migration
  （文件名依实际下一 revision 确定），同时更新 model、API schema、共享 payload
  和 task/queue 注册。老 fastp/scanpy job 的读取与执行必须保留。
- 升级顺序：schema → 支持新值的所有读端 → 专用 worker → 开启提交；滚动部署
  期间先保持 pyDEG 提交关闭。回滚先关提交、排空或显式取消新任务，保留能够读取
  pyDEG 历史 job 的读端；不得直接把含新行的库交给只认识旧 enum 的二进制。
- enum downgrade 需在真实 PostgreSQL 上覆盖无新行/存在新行两种情况：存在
  pyDEG job 时停止降级，不删业务行；无新行时才验证恢复原 enum 与依赖列。
  未形成历史读取方案前，M7 禁止宣称可无损回滚。

### 作业与科学验收

M5 复用现有 `analysis_jobs` + outbox + `AnalysisJobStore`，不新建作业权威库。
输入沿用 `tasks/analyses/input_keys.py` 的 user/upload-session、HEAD size/checksum
及下载完整性校验。输出只落当前 job 的对象前缀；结果上传并确认后才置成功。
同一事件重送、worker 崩溃、存储失败、取消中途和超时均有状态机与清理回归；
永远不将半成品当可下载最终结果。错误消息按既有规则清洗。

M4/M6 的科学用例：固定 toy counts 与可再获取的公开参考数据，验证方向、样本
对齐、重复、零 count、小样本、NA、稳定排序和 padj；记录参考版本/方法/容差及
显著基因集差异，不要求跨库 bitwise 恒等。差异表达结果接富集前显式选背景和
ontology，保持 assembly/release，避免把筛选后的显著基因集冒充总体。

各任务验收为其聚焦 pytest/真实依赖 smoke，再运行
`bash scripts/verify-backend-tests.sh`（使用全新测试库）；共享契约变更另外运行
API-client 契约/typecheck，M6 运行双站 build、权限矩阵与 Playwright。
部署任务复用 `scripts/build-release-image.sh` 与 `scripts/smoke.sh --profile images`，
缺 Docker 时记未执行。基准不承担数值/权限门禁；全部完成与生产启用分开记录。

## M0：环境与真实负载盘点（2026-10-07 已执行）

工具：`scripts/profile_enrichment_workload.py`。四条路径均已实跑，不是设计草案。

### M0.1 环境清单（`.validation/m0-environment.json`）

Python 3.14.6 CPython；fastapi 0.137.1、pydantic 2.13.4、sqlalchemy 2.0.52、
asyncpg 0.31.0、numpy 2.5.2、scipy 1.18.1、biopython 1.88；Node 24.19.0、
pnpm 12.5.1、uv 0.11.33；本机 PostgreSQL 16.15。Linux 7.0.0-34、256 CPU。

**环境缺口**（与数据缺口分开记录）：PATH 上无 `rustc` / `cargo` / `docker`；
DIAMOND 2.1.14 只存在于隔离验证目录 `.validation/diamond-runtime/usr/bin/diamond`，
未全局安装，也不在 PATH。API venv 未安装 omicverse。这些是 M2/M3/M7 的真实前置，
不是本轮可绕过项。

### M0.2 真实负载：数据缺口，已按缺口结案

穷举扫描本机 32 个数据库（`.validation/m0-realgap-emptytable-probe.json`）：
`gene_annotation_sets` / `gene_annotations` 仅在走过 Alembic 的库中存在，且
**全部为 0 行**。`--real` 默认路径按设计失败关闭，输出
`workload_kind: "unavailable"`，报告探测对象、逐项计数与 `next_prerequisite`，
不生成任何 case、计时或 RSS 结论。另有一次探测（未迁移库）如实区分
“表不存在”与“表存在但无行”两种缺口。

**2026-10-08 复核纠正**：上一轮仅检索 worker，却错误推广为“仓库没有注释写入实现”。
实际已有 [API 导入服务](../../../apps/api/app/services/gene_annotation_import_service.py)、
[CLI](../../../apps/api/scripts/import_gene_annotations.py) 与
[回归测试](../../../apps/api/tests/test_gene_annotation_import.py)。其既有规则为 draft-only、
不可变快照。数据表在当时探测中为空，不证明写入器不存在。M0-1 改为既有链路加固与
重复 owner 退役；真实上游注释文件缺口和 M2 真实负载前置仍保留。

### M0.3 工具验证：真实 SQL 分支已实跑

为验证 `--real` 分支不是未执行代码，在一次性库 `soymutdb_m0_harness_20261006`
中填充 **fixture** 快照（8000 基因 / 55943 注释行 / 700 term，
source_name=`M0 fixture snapshot`，source_sha256 与 row_count 自洽）。
结果 `.validation/m0-harness-fixture-profile.json`：`workload_kind: "real"`，
scope 携带 assembly_id/release_id/ontology/source_sha256，
`cases_sha256` 冻结了 662 个 `[N,K,n,k]` 整数与输入基因校验和，
报告记录 7994 背景基因、返回 20 个 term；当时并没有比较分阶段结果与生产入口的
显式断言，故撤回“结果一致”的验证声明。2026-10-08 已加入 calculation 字段逐项比较、
漂移失败关闭，以及无注释输入不计入 `n` 的回放回归；新报告标为 `database_replay`，
不再把数据库中的合成数据自动称作真实负载。历史 JSON 保留原样，不重标为新证据。
该 fixture **不是真实大豆注释数据**，只证明剖析工具在真实 PostgreSQL 上可执行；
任何 p95/RSS 结论仍须由 M0-1 导入真实快照后重测。

合成自检（`.validation/m0-harness-selfcheck.json`）只用于验证工具自身，
`workload_kind: "synthetic"`，报告中带显式声明，不作为负载证据。

### M0.4 关键实测：数值核不是当前瓶颈

`.validation/m0-harness-fixture-profile.json` 的分阶段中位数（3 次，单线程；
首轮 5 次的对应数字一并列出，两轮同向）：

| 阶段 | 中位数 | 占端到端 | 首轮占比 |
| --- | ---: | ---: | ---: |
| `sql_annotations` | 125.174 ms | 69.0% | 约 63% |
| `mapping` | 19.995 ms | 11.0% | 约 10% |
| `numeric_core` | 15.446 ms | 8.5% | 约 7.6% |
| `provenance_source` | 13.804 ms | 7.6% | 约 10% |
| `resolve_assembly` | 2.481 ms | 1.4% | 约 1% |
| `serialization` | 0.046 ms | <0.1% | <0.1% |
| 端到端 | 181.527 ms | 100% | 194.99 ms |

并发 4 时每请求 p50 577.44 ms、p95 578.76 ms（首轮 596.28 / 597.66 ms），
说明在当前单线程预算下并发请求高度串行；峰值 RSS 207.4 MB、增长 47.8 MB
（首轮 218.54 / 52.35 MB）。

限定结论：这两次 fixture 仪表化重放中 SQL 的中位数占比较大，值得优先分析；
不是完整生产请求的 p95 优化上限。保留原 Rust ≥20% 完整路径 p95 门槛；M2 可准备候选，
但真实负载缺失时不得通过验收或上线。若真实负载收益不足，允许不迁 Rust。

## M0-1：既有注释链路加固与重复 owner 退役（2026-10-08）

### 上一轮结论纠正

2026-10-07 曾将新增 worker 写入器标为完成；2026-10-08 复核证明该实现重复已有 API
owner，并违反 draft-only 与快照不可变规则。其“重复导入幂等”实际是删旧建新；
“保留已发布快照”测试使用 draft；“按 ID 精确清理”实际仍是 `id >= 900000` 范围删除。
校验文件与两个解析 pass 分别打开路径，也不足以保证摘要对应解析字节。
上述完成声明撤回，历史测试绿色不是这些契约的证据。

旧 [根门禁日志](../../../.validation/backend-gate-m0-1-final.log) 及合成 CLI 数据保留原样；
旧 top p 的准确记录是 `2.801e-103`，不是先前写下的 `2.801e-03`。这不能单凭读到 20 个
term 就作为科学正确性结论，也不证明上游真实性或生产发布资格。
2026-10-08 对旧合成快照做只读复查：映射插入顺序前 500 基因的 top case 为
`[4000,128,500,128]`、p=`3.514469221613267e-123`；固定种子随机 500 基因的 top
p≈`0.002937`、q≈`0.998947`。两种回放共 1360 个 term 与 SciPy SF 对拍，严格
`rel_tol=1e-9, abs_tol=0`，最大相对误差 `1.25e-11`；冻结输入、case 与全部比较见
[独立 oracle 证据](../../../.validation/historical-fixture-ora-oracle-strict-20261008.json)。
这支持“取映射前若干基因产生选择偏倚”的解释，但旧请求未留存，未精确复原历史
`2.801e-103`；不把新回放等同历史根因，不据此调整统计算法。

### 已批准的最小收敛设计

- 用户明确选择“收敛到既有导入器”，允许退役上一轮新增重复 worker 实现与两份测试，
  根 CLI 改为复用 API 入口；**未授权、也未执行业务数据库删除**。
- 唯一 owner 继续是 [API 服务](../../../apps/api/app/services/gene_annotation_import_service.py)。
  对 release 加行锁，仅接受 draft；相同摘要与来源元数据重入保留 ID，不同快照要求新 release。
- [API CLI](../../../apps/api/scripts/import_gene_annotations.py) 增加 `--dry-run`；复用同一
  文件描述符的初始摘要与解析字节复核，提交前拒绝输入变更。直接服务调用的摘要责任仍在调用方。
- [根入口](../../../scripts/import_annotations.py) 仅转交 API CLI；使用 API venv、位置 TSV
  参数、`--sha256`。旧替换/skip/batch/importer-version 参数退役，不建立兼容写入分支。
- 服务初次导入及幂等重入均检查实际存储行数；savepoint 与 CLI 外层事务保障失败回滚。
- 重复内部源码退役前存入 [本地归档](../../../.validation/retired-duplicate-annotation-import.tar.gz)，
  归档不在运行/收集路径；没有迁移、Celery、公共 API 字段或用户 W0 baseline 变更。

### 起始状态、边界与验证

本轮 TaskStartSnapshot：workspace `/mnt/data02/T25ronglin/code/web`、`main`、
HEAD `7ec14b41fdd9f2555eebeccfb192dcc3c18e67c8`；与 upstream 0/0，无 staged 项或进行中的
merge/rebase/cherry-pick；既有大量 dirty/untracked 与 3 个额外 worktree 均保留。
TDD mode `off` / route `skipped`，采用修改后真实回归；不提交或推送。

Change Necessity：文档更正不足以阻止重复写入入口覆盖快照，必须移除该职责。复杂度通过
删除约千行重复实现/测试、保留 19 行转交入口控制；不新增统计 owner 或 fallback。
ArchitectureReviewRequired：已复核 canonical owner 与持久化边界并取得收敛授权；若发现
外部消费者、真实数据变更或需要降低验收门槛，停止并重新确认。

聚焦回归 **60 passed / exit 0**，包含既有解析/导入、CLI dry-run 与非 draft/已发布快照
拒绝、不可替换、字节变更、计数不一致、其他 assembly 的基因、跨 release 绑定、后续
批次失败回滚，以及 profiler calculation parity / 故意漂移失败关闭、未注释输入 `n`
语义和 SciPy oracle。日志：[切片结果](../../../.validation/annotation-canonical-targeted-final.log)。
相关 Ruff 在 `RAYON_NUM_THREADS=1` 下 exit 0；默认多线程在 4 GiB 地址空间上 abort 的
尝试不计通过。完整根门禁 `bash scripts/verify-backend-tests.sh` **exit 0**：API
**1975 passed**（62.69 s），worker **562 passed / 1 skipped**（20.17 s），包含架构
guard、真实 PostgreSQL、分析依赖 import 和强制真实 DIAMOND smoke。
日志：[根门禁](../../../.validation/backend-gate-canonical-annotations-final.log)。

使用全新库 `soymutdb_canonical_gate_20261008_a`；`SOYMUTDB_TEST_DATABASE_URL` 与
`SOYMUTDB_DATABASE_URL` 指向该库，`SOYMUTDB_RUN_POSTGRES_INTEGRATION=1`；
`SOYMUTDB_TEST_DIAMOND_BIN=$PWD/.validation/diamond-runtime/usr/bin/diamond`、
`SOYMUTDB_REQUIRE_DIAMOND_SMOKE=1`。资源为 8 GiB 地址空间、420 秒 timeout，
GOMAXPROCS/RAYON/UV/BLAS/OMP 线程均为 1。API 的 31 个新回归计入根门禁；worker
较上一轮少 34 项是已退役重复 owner 的测试，而不是把仍有效的业务测试隐藏或跳过。
唯一跳过项为需 `SOYMUTDB_RUN_2M_IMPORT_PERF=1` 的 2M-row 性能层；单独 `-k 2000000 -rs`
复核：[跳过原因](../../../.validation/backend-canonical-optional-skip.log)。相关补丁空白检查
exit 0，退役模块 `find_spec` 返回 None、两份测试不再存在、worker 源码无遗留引用，
运维/计划 Markdown 文件链接可解析。曾有一次工具启动失败，重试后完成检查，不计初次失败为通过。
只完成本次收敛切片，不表示 M0–M7 迁移或生产环境验证完成；置信度 B（真实上游、真实
并发导入/发布竞态、历史请求精确复原与镜像级验证仍未覆盖）。下一步按 M1 检查蛋白 FASTA
边界；真实注释取得后重新测生产完整路径 p95。

### 真实数据与后续任务

真实上游 GO/KEGG 文件仍未取得。规范化、核实来源后，先按
[运维说明](../../ops/data-import-and-release.md) 对 draft dry-run，再导入；需要变更已存在
快照时创建新 release。剖析输出 `database_replay` 仅证明所选数据库作用域可重放，不自动
证明是真实上游或真实用户请求。M1/M3 可继续准备，M2 真实负载验收、M4–M7 与生产上线
仍未完成。

## M1：蛋白 FASTA 边界（2026-10-08）

### 实测发现的三个缺陷

先用真实 DIAMOND 2.1.14 逐一测量，而不是照抄计划里的假设。`plain` 对照组正常，
排除了探针自身的问题（首轮探针曾因 4 GiB `ulimit -v` 传导给子进程而让**所有**输入
都报内存分配失败，改为 worker 自己的命令构造后重测）：

| 输入 | rc | hits | 旧 `query_len` | 结论 |
| --- | --- | --- | --- | --- |
| 普通序列 | 0 | 1 | 36 | 对照正常 |
| **空记录** | **1** | 0 | 36 | DIAMOND 报 `Error: Missing fields in input line`，且只在作业已进入 running 后暴露；API 旧校验只检查第一个 header，因此放行 |
| **重复 ID** | 0 | **2** | 72 | 两份都被搜索，返回两行用户无法区分的命中；`query_len` 翻倍 |
| **末尾 `*`** | 0 | 1 | **37** | `len(record.seq)` 把终止符当残基计数，对 36 残基蛋白报 37 |
| 小写 / CRLF / 换行 | 0 | 1 | 36 | 本身可搜索，但两侧各自解析会漂移 |

### 收敛设计与边界

- 唯一 owner 是 [共享契约 `parse_protein_fasta`](../../../packages/jobs-py/src/soymutdb_jobs/protein_fasta.py)：
  仅标准库，无 ORM/Biopython/引擎调用，API/schema/service 与 worker 委托该结构/字符
  规则；提交长度限制另行保留。此前“两侧不可能不同答案”的声明失实：API/helper 仍有旧
  字符校验，tab/NBSP 等实测不同，且 Unicode 大写可改写输入。推送前修正后只允许 ASCII
  空格/tab 与 CR/LF 格式化，非 ASCII 残基在转大写前拒绝。理由修正见 C1。
- API 在提交时返回 422，并**携带稳定 code**（`protein_fasta_record_empty`、
  `protein_fasta_duplicate_id`、`protein_fasta_invalid_residue` 等）；code 也写进异常
  消息，因为 API 只回传消息、worker 只落库消息，仅作属性存在的 reason 会在两条路径上
  丢失。校验改为 `mode="before"`，否则空串会先被 `min_length` 拦下并给出
  “至少 10 个字符”这种误导原因。
- worker 在写文件与生成引擎之前拒绝，因此不再出现“已排队、已启动、才报
  Missing fields”的失败；失败原因进入作业 `error_message`。
- `query_len` 定义为每记录规范化序列位置数减去一个末尾 `*` 后求和；内部 `*`、gap
  仍占位置。这是项目计数，不是严格的生物学残基数，也不是 DIAMOND `qlen` 或 alignment
  length。`*` 保留在实际引擎输入；复核真实 DIAMOND 的 666 aa 对照、加 `*`、加 `**`
  时 `qlen` 分别为 666/667/668，alignment length 都为 666。撤回“搜索成功已证明长度
  等于实际搜索残基数”的解释。仅含单个 `*` 的记录拒绝，补正此前误写为 `>*` 的 fixture。
- 模糊残基 `B`/`Z`/`X` 与 `A`/`C`/`G`/`T` 合法；`U`/`O`/`J` 沿用仓库既有结论排除在
  字符表之外，既有 `test_blast_validation.py` 的 `U` 用例即为此。
- **旧结果可读**：读取路径不重跑校验、不重算 `query_len`。较早新增测试仅构造 schema，
  不证明服务读取链；推送前补调用真实 `BlastService.get_job/get_result` 的 15 项 fake-session
  回归，覆盖 5 个历史程序 × 末尾 stop/重复 ID/空记录，并保留存储长度。这是服务层证据，
  不冒充 PostgreSQL/HTTP 历史读回的完整资格。
- 无迁移、无公共 API 字段变更、无 OpenAPI/客户端再生成需求（`query_sequence` 仍是同一
  字符串字段，收窄的是取值集合），无部署变更。

### 证据

- 共享契约 [87 passed](../../../.validation/backend-gate-m1-protein-fasta-final.log)
  （新增门禁步骤）、API **2027 passed**（57.28 s）、worker **584 passed / 1 skipped**
 （20.30 s），架构守卫、worker 包标记、分析依赖 1.12.4 均通过，**exit 0**。唯一跳过项
  仍是需 `SOYMUTDB_RUN_2M_IMPORT_PERF=1` 的 2M-row 性能层。
- 较早新增回归：共享蛋白 parser **30 项**（87 是共享包全树总数，非全部新增）、[API 52 项](../../../apps/api/tests/test_blast_protein_fasta_contract.py)
  （含 API↔共享契约同进同拒的对照表）、[worker 22 项](../../../apps/worker/tests/test_blast_protein_fasta.py)
  与 [真实 DIAMOND 用例](../../../apps/worker/tests/test_diamond_integration.py)。
  真实二进制用例在 `SOYMUTDB_REQUIRE_DIAMOND_SMOKE=1` 下无跳过，并反向固定了
  “空记录确实会让真实引擎报 `Missing fields in input line`”，即本切片拒绝理由的直接来源。
- 既有 `test_blast_validation.py` 两条断言从 `Invalid characters` 改为 code 匹配：
  被拒行为未变，改的是文案来源。FakeSession 增加了记录落库值的字段，使失败原因与
  `query_len` 可断言。
- 较早相关 Ruff 与架构守卫 exit 0；上方为较早记录，不冒充推送前最终复验。

### 推送前复验（2026-10-08）

用户确认将全部当前源码/文档一起提交，排除本地环境、缓存和证据。cnb HTTPS 认证缺失后，
用户明确改选 `origin/main`；GitHub 认证可用，远端为本地 HEAD 的祖先，采用普通快进，
不强推、不删除业务数据。起点 `main@7ec14b41f`，W0 baseline 既有 25 行追加保持不改义。

- 新鲜完整后端根命令 `bash scripts/verify-backend-tests.sh`：**95 shared / 2057 API /
  585 worker + 1 skipped，exit 0**；共享蛋白 parser 现在为 38 项、API 契约文件为 67 项。
  全新库 `soymutdb_prepush_final_20261008_194816`，真实 PostgreSQL 与强制 DIAMOND 冒烟；
  8 GiB 上限、300 秒外层超时、单线程。日志
  `.validation/backend-gate-prepush-current-green-20261008.log`。
- 新鲜完整前端根命令 `bash scripts/verify-frontend-artifacts.sh`：**exit 0**，包含双站点
  构建、CSP/favicon/可见 i18n/包体预算、11 个测试任务、lint 12 个任务、typecheck 13 个
  任务、架构守卫及 OpenAPI/client contract。Web 205、admin 62、api-client 153 测试通过，
  其他共享包与 JBrowse 任务也通过；Turbo 可复用本轮同源码证据，不把缓存说成全部强制重跑。
  Node **24.19.0**、pnpm **12.5.1**；本地 affinity 为 2 CPU，忽略目录内 preload 仅让
  旧 `os.cpus()` worker 池遵守 affinity，未关闭压缩或跳过门禁。9 月旧根制品整体保留到
  `.validation/web-dist-with-legacy-20261008_193553` 后从空目录重建当前双树。日志
  `.validation/frontend-gate-prepush-final-green-20261008.log`。
- 双站点实际制品复用扫描：`SOYMUTDB_SITE_VARIANTS_PREBUILT=1 bash
  scripts/verify-site-variant-artifacts.sh`；internal noindex/无公开内容快照、external 无内部
  sentinel，exit 0。不是线上浏览器或部署验收。
- CI/job、worker image 与 Dockerfile 契约 **76 passed**；MCP 独立测试环境 **66 passed**，
  覆盖真实 FastMCP HTTP bearer 认证；不是 Docker/nginx 容器烟测。日志
  `.validation/prepush-delivery-contracts.log`、`.validation/prepush-mcp-final.log`。
- 推送前门禁暴露的既有维修：favicon checker 误拒绝 Umi 的 `shortcut icon` 且成功分支
  解包旧 tuple；改为 HTML rel token parser 并补正负及 CLI 成功自测。JBrowse 配置已声明
  favicon 却缺源码资产，补同款已有品牌 SVG；删除 SVG renderer 未使用常量；MCP 测试
  重新绑定 canonical job/transport 脚本，保留 `/mcp`、308、bearer 断言，不将业务逻辑放回
  workflow。这些是提交前阻断维修，不是新功能、模型/迁移或权限边界改动。
- 独立只读复核未发现上述有界修正的新重要/阻断问题。复杂度：blastp 旧字符 owner 收敛到
  共享 parser，favicon regex 替换为 HTML parser，不加回退链；历史非蛋白校验保留仅供既有
  读值兼容，新增执行仍只允许 blastp。置信度 B：C1 全资格及部署/E2E 仍有下方缺口；既有
  OpenAPI route debt allowlist 未在此切片消除。

### 未覆盖

C1 的**原始输入/规范化搜索输入 checksum provenance 尚未实现**：已有 checksum 是输出
TSV 摘要，虽 payload 已带 assembly/release，仍不证明原始输入字节来源。多记录 TSV/parser
有 query ID，但持久化/API hit 仍无记录级 query identity，属既存待验收缺口。较早“M1 完整
闭环”的声明撤回；当前只交付结构/字符边界与有界服务回归，不因此扩张迁移或切流。
并发/重投递下双写与取消竞态未覆盖；可选 2M-row 性能层未跑；真实用户 FASTA 文件集
未取得，边界矩阵来自显式构造用例；M2–M7 未开始。

## 验证记录与交付边界

### 2026-10-06 严重缺陷追加修复

在用户要求解决严重 BUG 后，继续沿上述内存事件和同源搜索链路排查，修复三项：

| 缺陷 | 已证实的原因 | 修复与覆盖 |
| --- | --- | --- |
| 缓存 JSON 编码内存失控 | `_json_default` 用 `hasattr(model_dump/isoformat)` 接受动态代理；未配置 MagicMock 的 `model_dump()` 每次制造新 mock，JSON default 转换持续展开 | 根据对象真实类型处理 BaseModel / datetime/date/time，保留其序列化格式与其他类型的既有字符串 fallback；不再执行动态代理的伪序列化协议 |
| 同源搜索忽略 assembly | `assembly_id` 进入 cursor filters，却未进入 search SQL；同一 release 的 v4/v5 混入结果和总数 | `Assembly.id == assembly_id` 进入共用 conditions，覆盖 count、offset、keyset；真实 PostgreSQL + HTTP 阴性测试排除另一 assembly 与 draft 数据 |
| 搜索首屏无后续 cursor | offset 分支固定 `has_more=False` / `next_cursor=None`，客户端拿不到首次 keyset continuation | offset 和 cursor 都查询 page_size+1，共享续页计算；保留页码与 total 语义，覆盖两页衔接、末页及跨 assembly cursor 422 |

内存对照证据为 `.validation/cache-encoding-growth.json`：提取 `7ec14b41f` 的真实
旧 `_json_default` 与当前实现，同一模拟 release identity、各自独立子进程、
1 GiB RLIMIT_AS、12 秒外层超时。旧版 1.315 秒触发 MemoryError，峰值 RSS
1,022,232 KiB；修复版完成编码，峰值 RSS 121,048 KiB。该结果证明编码路径缺陷，
不是 Redis 重试；PID 1518449 已退出，未取得当时的完整内存 dump，不把此对照
冒充对原 PID 的现场剖析。homolog fixture 的显式 release override 仍保留，
它与编码器修复分别保护测试查询顺序和实际缓存边界。

新增 `apps/api/tests/test_homolog_assembly_scope.py` 的 5 项 PostgreSQL/HTTP 回归：
修复前均失败；加入组装条件后 3 项通过，另 2 项揭示首屏游标缺陷；修复续页后
全部通过。缓存回归覆盖无 spec / BaseModel spec / datetime spec 动态 mock、真实
Pydantic/日期/时间/UUID，以及 `get_or_set` 入口；编码回归先检查 default 返回类型，
避免误恢复旧代码时测试本身无限扩张。

最终相关切片 **55 passed**；完整根门禁 **exit 0**：API **1944 passed**（57.13 s），
worker **562 passed / 1 skipped**（20.10 s，仍为可选 2M-row 性能层），包含实际
PostgreSQL 集成和 DIAMOND 冒烟。使用新建测试库 `soymutdb_critical_recheck_20261006`，
沿用 8 GiB / 240 秒根门禁约束；日志 `.validation/backend-gate-critical-fixes-final.log`。
相关 Ruff 和按现有 CRLF 行尾的 diff 空白检查通过。未修改 API 字段词表、模型/DDL、
部署或前端；未提交/推送；未触碰用户 W0 baseline。源码/回归已验证，不代表部署启动
或全项目不存在其他缺陷。

复杂度：缓存仍只有现有 encoder owner，替换两处鸭子类型判断；同源路由共用
conditions 与续页计算，删除重复续页分支，不新增 fallback、状态或统计 owner。
原页码模式因既有客户端仍消费 page/total 保留，切换并验收客户端后再单独退役。

### 2026-10-06 核心优化阶段门禁（较早记录）

- 完整根命令 `bash scripts/verify-backend-tests.sh` 最终 **exit 0**，不是若干切片相加。
  API 全树 **1934 passed**（56.46 s）；worker **562 passed / 1 skipped**（20.30 s）。
  唯一跳过项为需显式开启的 2M-row 导入性能层；独立 `-k 2000000 -rs` 复核原因。
  架构 guard、自测、worker package-marker、真实分析依赖 import 均通过。
  日志：仓库根目录 `.validation/backend-gate-final-streaming.log`。
- PostgreSQL 16 使用全新独立测试库 `soymutdb_gate_streaming_final_20261006`；
  `SOYMUTDB_RUN_POSTGRES_INTEGRATION=1`。真实 DIAMOND 冒烟设置
  `SOYMUTDB_TEST_DIAMOND_BIN=$PWD/.validation/diamond-runtime/usr/bin/diamond` 与
  `SOYMUTDB_REQUIRE_DIAMOND_SMOKE=1`，缺二进制即失败。
- 资源约束：`ulimit -v 8388608`（8 GiB 虚拟内存上限），外层
  `timeout --kill-after=10s 240`；GOMAXPROCS/RAYON/UV/BLAS/OMP 线程均为 1。
  shell 直接重定向日志并保留真实退出码，未使用会掩盖失败的 `pytest | tail`。
- 富集主测试与 oracle 共 68 项，包含均值两侧的 400 次对拍、20 万项支持集
  常量空间、深尾与 0.05/BH 判定回归。相关 Ruff 通过；补丁空白检查按既有
  CRLF 行尾规则通过。不宣称全仓 Ruff 无历史问题。
- 旧复用库首跑 worker 失败：查询证明 `assemblies` 缺失而 `alembic_version`
  留有 `0045`；API fixture teardown drop metadata，worker Alembic 因标记而不重建。
  全新隔离库复跑通过。没有清空旧库或 stamp/reset 其迁移版本；测试 fixture
  原有契约已明确要求每次使用全新库。
- 之前报告的 PID 1518449 / 约 200 GB 内存事件：补齐 homolog release-context
  fixture 后整文件和根门禁完成；分配链未独立追踪，先前“缓存重试循环”归因
  缺少证据，撤回。当前资源受限验证不等于已定位那次内存增长的完整根因。
- 环境复核：当前 PATH 未找到 `rustc` / `cargo` / `docker`；API 验证 venv
  未找到 omicverse module。真实注释负载、Rust候选、pyDEG环境、镜像启动仍未交付。
  本轮完成范围是 Python 优化、后端门禁与 M0–M7 迁移计划，不是生产迁移启用。

### 2026-10-06 收敛后较早实测

- Worker 全量：**539 通过 / 24 跳过**，含真实 DIAMOND 2.1.14 的 `blastp` 冒烟
  （`SOYMUTDB_REQUIRE_DIAMOND_SMOKE=1`，二进制缺失即失败）。API BLAST 相关
  切片 **71 通过**。
- 前端：web `lint` 0 errors、`typecheck` 通过、`205 passed`；`api-client`
  `153 passed`；站点构建 rc=0。CLI 扫描 14 个路由后复扫，13 个页面各恰好
  一个 H1、零个无可访问名控件。
- 真实二进制版本：DIAMOND `2.1.14.168`，apt 包解压到隔离验证目录，未全局安装。
  NCBI BLAST `2.16.0` 仅用于收敛前的实测，收敛后不再参与任何测试。
- **既有基线缺口已闭合**：`apps/api/tests/test_gene_service.py` 原 8 项失败，
  根因是测试替身不完整（`_Result` 缺 `all()`）与转录本 ID 断言沿用旧契约。
  服务的 `_public_transcript_id` 是刻意的隐私修复（不再把 BIGSERIAL 主键
  `tx.id` 暴露给匿名调用方），故修的是替身与断言，不是服务。现 18 通过，
  新增两条：未命名转录本不得回落为主键；`variant_count` 走自己的查询。
- **`/guide` 无法验证**：内容 API 返回 502，指南正文未加载，标题层级不可判定。
  这不计为通过，也不计为缺陷。
- **`/analyses` 仅验证门禁页**：分析页本体在鉴权之后，其 H1 改动对登录用户
  生效，浏览器无法实证。

### 仍未取得结论（不冒充交付）

- **Docker 镜像级验证**：当前 PATH 未找到 Docker CLI，`Dockerfile.worker` 与
  `environment-worker.yml` 的声明变更**不等于镜像启动通过**，daemon 未作新的独立探测。
- **Rust 统计核**：PATH 中无 Rust 工具链，且计划要求先取得 assembly/release/
  ontology 明确的真实注释负载并测得 p95 改善 ≥20%。全新迁移测试库已有
  `gene_annotations` 表，但 `COUNT(*) = 0`；真实负载前置条件尚未满足。
- **pyDEG**：omicverse 环境尚未建立，接入未开始。
- 保留用户同时修改的 W0 baseline，未回退或覆盖；源码变更没有业务数据破坏面。

重跑命令（从仓库根目录）：

```bash
SOYMUTDB_TEST_DIAMOND_BIN=<diamond 路径> SOYMUTDB_REQUIRE_DIAMOND_SMOKE=1 \
  apps/api/.venv/bin/python -m pytest apps/worker/tests/test_blast_task.py \
  apps/worker/tests/test_diamond_integration.py -q
apps/api/.venv/bin/python -m pytest apps/api/tests/test_enrichment.py \
  apps/api/tests/test_enrichment_oracles.py apps/api/tests/test_blast_backend_parameters.py \
  apps/api/tests/test_local_preview_cli.py -q
PYTHONPATH=apps/api OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  apps/api/.venv/bin/python scripts/benchmark_enrichment_core.py --samples 11
SOYMUTDB_TEST_DATABASE_URL=<测试库 URL> bash scripts/verify-backend-tests.sh
```

真实 DIAMOND 冒烟默认跳过，只有显式给出 `SOYMUTDB_TEST_DIAMOND_BIN` 时才执行；
`SOYMUTDB_REQUIRE_DIAMOND_SMOKE=1` 会在二进制缺失时直接失败，使"跳过"无法冒充
"通过"。
