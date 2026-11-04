# Rust 内核限值 ↔ `/tools/sequence/capabilities` 对账

## 现状问题

`GET /api/v1/tools/sequence/capabilities` 对外广告一组输入限值：inline 序列
1 MiB、pattern 256 nt、`max_hits` / `max_regions` 1000、k 1–32、已实现的遗传
密码表 `[1]`、以及 `0-based-half-open` / `1-based-inclusive` 两个坐标系标签。
客户端按这些值决定「什么输入是合法的」。

这组值同时存在于两处，且**没有第三处把它们绑在一起**：

| 权威侧 | 副本侧 |
| --- | --- |
| `packages/bio-core/src/{sequence,intervals,translation,bindings}.rs` 里的 `pub const` 与 `capabilities()` 字面量 | `apps/api/app/schemas/sequence_tools.py` 里的 `MAX_*` 常量与 `SequenceCapabilitiesResponse` 默认值 |

`apps/api/app/services/sequence_tools_service.py::capabilities()` 只填
`available` / `engine` / `engine_version` / `reason`，其余字段取 Pydantic
默认值 —— 也就是**照抄 Python 侧的常量**，运行时从不读内核的
`capabilities()`。于是任一侧单独改动都会出现「广告限值与实际强制限值不同」：
客户端按广告值发请求，内核按自己的常量拒绝，或反过来广告得比内核更严。

这类漂移 `check-contract.sh` 看不见：它比的是 `app.main:app` 导出与
`openapi.json` 快照，而两侧**都是 Python 侧常量**，快照与导出永远自洽。
`test_openapi_snapshot_contract.py` 也只管快照字节；`apps/api` 的用例断言的是
端点行为，不是「行为所依据的常量等于内核常量」。这正是 #96/#107 那几轮反复
踩到的形状：**两边一起错的时候，一致性检查会替它背书**。

## 方案依据

- 判据只读**已提交的源码字节**：不需要 wheel、不需要 Rust 工具链、不需要
  FastAPI import、不需要 PostgreSQL。因此能挂在 `scripts/verify-bio-core.sh`
  里、排在昂贵的 `maturin build` **之前**，缺工具链时照样能拦住契约漂移。
- Rust 是权威侧，Python 是副本侧。守卫对四个数值上限、`k_range`、
  `genetic_codes`、两个坐标系标签逐项比对，**字段缺失或形状被改写必须报错，
  不能当成「没差异」**。
- 守卫自带 `--self-test`：14 个单向变异（每个字段的 Rust 侧 / Python 侧各一）
  逐个注入，确认每一个都被点名。判据要自证「自己会响」，否则又是一条
  「文件在仓库里、但没人跑过」的守卫。
- `scripts/test_bio_core_capability_parity.py` 是承重回归：把 `check()` 换成
  恒绿后，单向漂移用例必须转红；`scripts/test_bio_core_capability_parity_wiring.py`
  单独钉接线，避开 `test_ci_job_contracts.py` 这个多 PR 共享热点。
- 两层都进 `verify-bio-core.sh`：`--self-test` + 现树检查在构建前，回归套件在
  隔离 venv 建好之后（那一层才有 pytest）。

## 放弃方案

- **运行时让 `capabilities()` 去 import 内核再取 `capabilities()`**：wheel 缺失
  时该端点仍须可用（它要报 `available: false` / `reason`），不能把广告面绑在
  引擎在场与否上。且失败关闭的 503 语义要求 `require()` 只在计算端点抛错。
- **把 Python 侧常量删掉、改成从 Rust 生成**：跨语言代码生成会引入新构建步骤
  与产物，超出这一刀的边界；且 `SequenceCapabilitiesResponse` 是 Pydantic
  契约，需要静态默认值才能进 OpenAPI 快照。
- **把判据塞进 `check-contract.sh` 或扩 OpenAPI 快照**：那是导出/快照自洽层，
  正好是本节开头指出的盲区所在；`openapi.json` / `openapi.d.ts` 又是 20+ 个
  open PR 的共享热点，不新增第二处双写。
- **改 `test_ci_job_contracts.py` / `smoke.sh`**：两者都有多个并行 PR 在改，
  接线断言单独成文件即可，不制造 add/add 冲突。

## 改动点

- 新增 `scripts/check_bio_core_capability_parity.py`：读 5 份源码字节、逐项
  比对；`--self-test` 14 例；现树检查 exit 0/1，漂移逐行报出字段名与两侧值。
- 新增 `scripts/test_bio_core_capability_parity.py`：18 条（含 14 个参数化单向
  漂移、缺字段、恒绿弱化检出、自测通过）。
- 新增 `scripts/test_bio_core_capability_parity_wiring.py`：4 条钉住接线位置、
  `--self-test`、回归套件在门禁里真跑、以及「摘掉接线必须被检出」的负控。
- `scripts/verify-bio-core.sh`：构建前两层 + 构建后一层，共三处调用。
- 本文件：记录判据与放弃方案。

## 预期

- main 现状：守卫 PASS、23 条回归全绿、`verify-bio-core.sh` 其余步骤不变。
- 把 `MAX_INLINE_SEQUENCE` 的 Rust 侧改成 `1_048_577` 或 Python 侧改成
  `1_048_577`（只动一侧）：守卫报
  `max_inline_sequence: Rust enforces ... but the API advertises ...`，exit 1。
- 把 `k_range` / `genetic_codes` / 坐标系标签任一侧改掉：同样逐项点名。
- 删掉 `--self-test` 调用、删掉回归套件调用、把 `check()` 改成恒绿：各自被
  对应接线断言 / 承重回归判红。
- 不改变任何端点行为、不触碰 `openapi.json` / `openapi.d.ts`、不新增运行时依赖。
