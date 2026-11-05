# 内核错误码逐码金标准（value-level golden）

## 补的是哪一类漂移

`packages/bio-core/src/errors.rs` 同时拥有机器码集合与每个码的一句话。
这条链上其余每一个消费方都从它派生期望：

- `apps/api/app/services/bio_core_bridge.py` 的 `KERNEL_ERROR_MESSAGES`（#134）
- `apps/api/tests/test_sequence_tools_error_codes.py` 的 `kernel_codes()` / `TRIGGERS`（#134）
- `scripts/check_bio_core_error_codes.py` 的 `parse_errors_rs()`（#134）
- `scripts/check_kernel_error_messages.py` 的 `CODE_RE`（#148）
- `packages/bio-core/python_tests/test_wheel_contract.py` 里 2 个码的 3 条字面量断言

**派生出来的期望无法冻结值**。PR #134 的复核里可复现的最小反例：把
`errors.rs` + bridge 两处 `EMPTY_SEQUENCE` 一起改名，再把回归文件掏空成一行
`# derived from errors.rs`，`check_bio_core_error_codes.py` 输出
`bio-core error code contract passed (10 codes bound)`、rc=0。守卫的全部检测能力
寄生在 `KERNEL_ERROR_MESSAGES` 那张字面量表上，而那张表本身就是被测对象。

判据一句话：**把 `errors.rs` 里任意一个码改名，若 `errors.rs` 之外没有任何一处
`git grep` 命中会因与它不一致而失败，则码值未被冻结。** 改动前这个测试对 10 个码
里的 8 个失败——没有命中点可失败。

## 这一刀做什么

新增 `packages/bio-core/errors.golden.json`：一份**手写**、不从 `errors.rs`
生成、位于 Rust 源码下游的逐码锁文件，记录对外契约——客户端可能收到的
`error.details.code` 值及其含义。

`scripts/check_kernel_error_golden.py` 只读两份已提交字节（无 wheel、无 Rust
工具链、无 FastAPI、无 PG、无 pytest、CPython 3.11 即可）：

1. `errors.rs` 的 `code()` 映射与 `#[error(...)]` 句子解析为 `{code: sentence}`；
2. 锁文件按 JSON 读，拒绝重复键、空对象、非 `UPPER_SNAKE` 键、非字符串值；
3. 双向集合比对 + 逐码句子比对，缺一侧绝不读成「没差异」。

因此**任何单侧改名都会红**：`errors.rs` 改了而锁文件没改 → 红；锁文件改了而
`errors.rs` 没改 → 红；两处一起改（连同所有共派生消费方）→ 仍需人工编辑锁文件
才能落地，即一次显式、可评审的契约变更。这正是「内部一致性」与「对外契约」的分界：
#134 保证的是 *码集与 errors.rs 一致*，本刀保证的是 *码值稳定*。

刻意不重复别人的职责：本刀不检查 bridge 映射、不检查 FFI `raise()` 站点、
不检查 API 响应形状。#134 / #148 各守各的，互不替代。

## 接线（零共享脚本改动）

回归 `packages/bio-core/python_tests/test_kernel_error_golden.py` 用 stdlib
`unittest` 写成（pytest 同样收集 `TestCase`），落在一个**已按目录收集**的路径：

- `scripts/verify-bio-core.sh`: `pytest "${CRATE_DIR}/python_tests" -q`
- `scripts/verify-backend-tests.sh`: `pytest packages/bio-core/python_tests -q`

两条 CI 阶段都按目录收，不需要往 `scripts/smoke.sh` 的 `tests=()` 数组里插条目——
那个数组当前被 14 条在飞 PR 同时编辑，是已知冲突热点。这也避开「登记了但没被
收集」的时态陷阱：文件在目录里就会被两条 runner 真跑，不是只挂在某个名册上。

守卫自身可直接跑（pre-commit / 开发机 / CI 构建前均可）：

```
python3 scripts/check_kernel_error_golden.py --self-test   # 16 例（15 变异 + 1 正向对照）
python3 scripts/check_kernel_error_golden.py              # 现树：10 codes frozen
python3 -m unittest discover -s packages/bio-core/python_tests -p 'test_kernel_error_golden.py' -v
```

## 变更流程

新增或重命名一个内核码，必须**同一笔提交**里同时改：

1. `packages/bio-core/src/errors.rs`（Rust 真源）
2. `packages/bio-core/errors.golden.json`（人工同步，显式评审）
3. 所有共派生消费方（bridge 表、API 回归的 `TRIGGERS`、守卫解析结果）

只改 1+3 会让本守卫报 `needs a reviewed entry` / `no longer raises`。这是刻意的：
码值是对外契约，不该在一次顺手改名里静默漂移。

## 边界

锁文件只冻结 `details.code` 的**值域**，不冻结 HTTP 状态、不冻结 `details` 的其余
字段、不冻结客户端 TS 联合类型。若将来要把它发布成 `packages/api-client` 的
`details.code` 联合类型，那是另一个 phase：本刀提供的是可被那种生成器消费的
独立锚点，不是生成器本身。

## 本轮 CI 的真实状态（不是判据转红）

`verify` 流水线（`cnb-i7r-1k6ksbjmm`）在 `Prepare` 阶段就结束了，**七个**验证
stage 全部 `skipped`（0ms），没有任何门禁运行：

```
Pipeline prepare error: Root Group's events CPU core-hours are insufficient
for pre-freezing (Freezing time: 10.00 min, equivalent to 2.67 core-hours).
Contact the root group administrator to extend.
```

这不是「某条判据转红」，也不是「绿灯」：Prepare 在拉起任何容器之前就终止了构建，
`Frontend verification` / `Rust bio-core` / `API + Worker verification` /
`Contract suites` / `Dependency governance` / `Database A/B harness` /
`Compiler prerequisites` 七条全都没跑。

### 根因：根组织云原生构建 CPU 配额耗尽（仓库外）

CNB 官方 [定价](https://docs.cnb.cool/zh/pricing.md) 口径：云原生构建-CPU 免费额度
**160 核时/月**、月底清零；构建启动后按 `节点规格 × 预冻结时长` 预留额度，
**可用额度不足即立即终止任务**。本流水线 `runner.cpus: 16`，预冻结 10 min，
`16 × 10 / 60 = 2.67 核时`——与报错逐字吻合。这是根组织的「events」额度池，
不是本 PR 引入的：本 PR 只新增 4 个文件，未改 `.cnb.yml` 或任何共享脚本。

用 `cnb build start-build` 在同一时间窗做了最小探针（config 内联、不落仓库），
逐档核实 `cpus` 与预冻结核时的线性关系：

| `runner.cpus` | 预冻结核时 | Prepare 结果 |
| --- | --- | --- |
| 16 | 2.67 | error（配额不足） |
| 8  | 1.33 | error（配额不足） |
| 4  | 0.67 | error（配额不足） |
| 2  | 0.33 | error（配额不足） |
| 1  | 0.17 | success（仅此档还能挤进剩余余额） |

所以**调低 `runner.cpus` 不是修法**：它只是把「额度不足」的门槛往下挪，且当前
剩余余额连 2 核都预冻结不了；把全量 `verify` 从 16 核降到 1 核既跑不动 pnpm
turbo 全链，也是对既有容量规划的倒退。同一时间窗内 #160、#163、#164 等无关 PR
的 `verify`（含 #160 自己改成 8 核的分支）以**完全相同**的 Prepare 报错结束，
与改动无关。`Contact the root group administrator to extend` 的字面含义就是：
需要根组织管理员在「组织 → 设置 → 用量管理」绑定预算、提升上限后重跑。

### 配额恢复前能拿到的证据（都不是 CI 代签）

1. **本机只读项全绿**：守卫 plain `10 codes frozen`、`--self-test` 16/16、回归
   6 例 OK、`test_ci_job_contracts.py` 92 OK、`check_bio_core_wheel.py --static`
   OK、`test_site_artifact_isolation` 11 OK、`check-toolchain-pins.py` OK、
   `py_compile` / `json.tool` / `git diff --check` 全清。
2. **平台侧部分验证**（`cnb-b5q-1k6ktcj14`，`api_trigger` 一次性探针，1 核 +
   `python:3.15` 镜像，配置内联不落仓库）：在 CI 的 **Python 3.15.2** 上实跑
   本 PR 四个新文件，守卫 plain、`--self-test` 16/16、回归 6 例、`py_compile`、
   `json.tool` 全部 `PASS`。这只覆盖新增字节，不覆盖 wheel / Rust / API / PG /
   前端全链，**不能读成 `verify` 终态**。
3. 自动重跑不可用：本分支没有 `api_trigger` 正式配置（`CONFIG_EVENT_EMPTY`），
   上面那条是临时内联探针，不构成可重复入口。

**结论**：代码本身没有可修的 CI 红灯；七个验证 stage 从未运行。CI 终态一律以
平台为准，配额恢复后直接重跑 `verify` 并回填，本节届时删除。
