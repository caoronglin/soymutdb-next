# SoyMutDB Rust 生物计算内核（`packages/bio-core`）

> 状态：0.1.2 已实现 P1–P3（内核 / REST 契约 / 区间与格式），P4 为全量门禁。
> 依据：`SoyMutDB_Rust_Core_Development_Spec_2026-11-05.md`（设计提案，非既成事实）。
> 本文只描述仓库里**实际存在**的代码；未实现项在末尾单列，不写成已完成。

## 1. 决策与真实编译结论

规格里的 crate 版本是候选值，未经编译验证。实机探针修正了两处：

| 项 | 规格候选 | 实测结论 |
| --- | --- | --- |
| Rust 工具链 | 未 pin | **1.99.1**（`rust-toolchain.toml`）。`bio-seq 0.15.2` 依赖的 `bio-seq-derive 4.12.2` 用了 unstable `uint_bit_width`，1.90/1.95 均编译失败 |
| noodles | 0.118.0 | 同版本，但要求 rustc ≥1.91 |
| PyO3 | 0.30.1 | 同版本，但 `Python::with_gil` 已移除，改用 `#[pymodule] fn(&Bound<PyModule>)` |
| 反向互补 | Rust-Bio `alphabets::dna::revcomp` | 该函数**不处理小写与 IUPAC**；唯一公开实现在 `sequence::reverse_complement`，Rust-Bio 只作纯 ACGT 的独立 oracle |

四库版本均按 `=` 精确锁定并提交 `Cargo.lock`：`bio 4.2.2` / `noodles 0.118.0` / `rust-lapper 1.3.0` / `bio-seq 0.15.2` / `pyo3 0.30.1` / `maturin 1.16.0`。wheel 目标 **CPython 3.15**（`cp315-cp315-manylinux_2_34_x86_64`）。

## 2. 单一职责（不维护两套语义）

| 科学动作 | 唯一 owner |
| --- | --- |
| 精确 / 近似匹配、双序列比对、ORF、统计 | Rust-Bio |
| IUPAC + 大小写反向互补 | 本 crate `sequence.rs` |
| 定长 k-mer、标准遗传密码表翻译 | bio-seq |
| 0-based 半开区间重叠 | rust-lapper |
| FASTA / FASTQ / BED 有界校验 | noodles |
| 认证、ReleaseContext、SQL、对象存储、任务 | Python API / Celery（Rust 不碰） |

Rust 只接收已校验的 bytes / 整数元组，不拿 DB 凭据、不自行决定可见性、不打开路径或 URL。

## 3. 坐标与科学约束

- 内部区间 `[start0, end0)` 0-based 半开；对外 `[start1, end1]` 1-based inclusive。换算只在 `coordinates.rs`，其他模块不得自行 ±1。
- 相邻区间不重叠；`count` 按记录（重复注释分别计），`covered_bp` 按并集。
- `N` / IUPAC 默认**文字精确**，不暗当通配符；k-mer 对含模糊碱基的窗口 `skip`（返回 `skipped_windows`）或 `reject`。
- 只实现 NCBI 标准遗传密码表（table 1，64 密码子全表有金标准）。其他 `genetic_code_id` 显式 `UNKNOWN_GENETIC_CODE`，**不静默回退**。
- ORF 返回「候选」而非已证实基因；比对 `identity` 分母是比对列数并写进文档。
- `bio 4.2.2` 的 `Alignment::cigar()` 对 Local/Global 直接 panic，因此 CIGAR 由 `operations` 自行推导，三模式统一。

## 4. 分层与端点

```
FastAPI /api/v1/tools/sequence/*   →  Pydantic 限额  →  sequence_tools_service
                                                        ↓ anyio.to_thread
                                              bio_core_bridge.require()
                                                        ↓
                                       soymutdb_bio_core (PyO3 wheel)
/api/v1/tools/intervals/overlap    →  interval_overlap_service
                                        ↓ 先按已发布 ReleaseContext 解析 assembly/chromosome
                                        ↓ 只查该 (assembly, release, chr) 的 genes
                                        ↓ 1-based → 0-based 半开
                                              rust-lapper
```

新增端点（全部不改动既有 `/tools/seqfetch`）：

| HTTP | 路径 |
| --- | --- |
| GET | `/api/v1/tools/sequence/capabilities` |
| POST | `/reverse-complement` `/match` `/align` `/stats` `/orfs` `/translate` `/kmers` `/inspect` |
| POST | `/api/v1/tools/intervals/overlap` |

**失败关闭**：wheel 缺失或 `SOYMUTDB_BIO_ENGINE=python`（无等价实现）时，所有计算端点返回结构化 `503 service_unavailable`，绝不返回空成功；`capabilities` 始终可用并明说 `available/reason`。

**边界**：`/match` 的 `target` 目前只有 `kind: inline`；不接受任意路径 / S3 key / URL / region，不伪造染色体坐标与 JBrowse 链接。全基因组相似性搜索仍由 NCBI BLAST+ / DIAMOND 负责。

## 5. CI / 门禁（复用单一执行来源）

- `scripts/ci-job-steps.sh` 的 `bio-core` job → `scripts/verify-bio-core.sh`：
  `cargo fmt --check` → `clippy -D warnings` → `cargo test`（unit + golden + adversarial）→ `maturin build --locked` → **安装该 wheel** → import smoke → 真实科学断言 → `pytest python_tests`。
- `.cnb.yml`（PR/push/manual）、`.cnb/pipelines/verify.yml`、`.github/workflows/ci.yml` 三方各只写一行 `run bio-core` 委托，无平行 `rust.yml`。
- `scripts/verify-backend-tests.sh` 在 API pytest 之前把**同一个 wheel** 装进 API venv，并跑 wheel 契约 pytest，保证后端套件跑的是发布制品而非源码 import。
- `scripts/smoke.sh`：`--profile contracts` 跑 `check_bio_core_wheel.py --static`；`--profile runtime` 跑 `--runtime`（import + 真实算法）。缺 wheel 一律 FAIL，不 SKIP 冒充 PASS。
- `scripts/test_ci_job_contracts.py` 断言 job inventory、两家 provider 委托、wheel 产物与 smoke 集成。

## 6. 未实现（不吹）

- wheel 尚未装进 `infra/docker/Dockerfile.api` / `.worker` 运行时镜像；当前由 CI 的 venv 安装路径覆盖测试，镜像侧需独立 PR 加 Rust builder stage + SHA-256 校验。
- 未做多架构 wheel、fuzz / benchmark、`/tools/sequence/batch` 异步作业、CDS phase 组装、GFF3 Parent 关联、VCF/BCF/BAM/CRAM、非标准遗传密码表。
- 区间索引按请求从已发布 genes 构建（受 bounding span 限制），尚无跨 release/assembly 的缓存与失效策略。
- 前端 `/tools/sequence` 页面由 @npc/CodeBuddy(deepseek-v4.1-flash) 接入；本文只覆盖后端与内核。
