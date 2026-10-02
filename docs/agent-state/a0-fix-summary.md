# A0 Gate 契约漂移修复总结（t9）

> **已归档（2026-10-01）**：智能体执行日志与提示词草稿（治理要求工作区不存放日志）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §7 变更记录；执行结论见 docs/dev/project-status.md。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

> 由 `qa-verify` 产出。目标：把 `apps/api/tests/a0/` 的 38 个失败收敛到 0，
> 并判断正确的修复方向。本报告给出真实根因、已确认的修复映射，以及一处
> **必须由 A0 计划 owner / captain 决策的实现级缺陷**。

---

## 0. 结论（诚实裁定）

38 个失败不是「改几个断言字符串」能收敛的，而是两类问题叠加：

1. **测试夹具落后一个契约大版本**（可修，但工作量大）：`tools/a0/*` 是实现
   的 **v2 semantic-gate 契约**（`a0.gate.v2` / `a0.reviewer-attestation.v2` /
   `a0.trusted-assertion.v2` / `a0.semantic-gate.v1` / `a0.action-recipe.v1`），
   而 `apps/api/tests/a0/test_rl_gate_evidence.py` 和
   `test_rl_reviewer_attestation.py` 的 fixture 仍在构造 **v1** manifest/assertion
   形状（缺 `recipe_id`、`semantic_gate_contract_version`、`action_recipe_version`、
   `ci_identity`、`review_tool_source_sha256`、`gate_tool_source_sha256`、33 phase
   结构、v2 event/action binding、v2 trusted-assertion 大字段集等）。这导致 gate
   在进入业务语义校验前就 `BLOCKED`，并发出 `missing-top-level:*` /
   `semantic-gate-contract-version` / `action-recipe-version` / `recipe-id` 等顶层
   契约码，业务层 finding 码（`nonzero-exit` / `list-invalid` …）永远没机会出现。

2. **一处实现级缺陷：canonical snapshot ↔ sidecar 的互认证摘要形成数学上不可
   满足的循环**，导致任何「合法 manifest」都无法到达 `PASS`（详见 §3）。

因此「38 → 0」若要成立，必须同时：A) 重写测试 fixture 到 v2 形状（正确对齐），
B) 修复/裁定 §3 的互认证摘要循环 —— 后者是对 fail-closed gate 语义的改动，
应当由 A0 计划 owner 决策，QA 不应单方面放宽安全契约。

---

## 1. 与本次 Phase 2/3/4 的关系

`git status --short tools/a0/ apps/api/tests/a0/` 为空，两个目录自 baseline
提交 `4d970bfba`（2026-08-07）起零改动；实现与测试在同一次 initial baseline
提交里就「自带不一致」（实现 v2、测试 v1）。**与本次 Phase 2/3/4 完全无关。**

---

## 2. finding-code 词汇表：测试期望 → 实现实际（已核对）

以下映射来自逐行比对 `tools/a0/rl_emit_gate_evidence.py` +
`tools/a0/rl_reviewer_attestation.py` 与测试断言。实现是较新且 plan §11 B1–B11
一致的权威契约，测试码需向实现收敛（**不反向放宽 gate**）。

| 测试期望码 | 实现实际码 | 说明 |
|---|---|---|
| `nonzero-exit` | `nonzero-exit` ✅ | 一致（`exit_code != 0`），但需先满足顶层字段 |
| `missing-source-digest` | `missing-source-digest` ✅ | `rl_validate_action_graph` 中 `not rl_is_sha256(...)` |
| `missing-artifact` | `artifact-missing-or-unsafe` | 改名 |
| `unsafe-path` | `artifact-raw-list` / `artifact-raw-archive` | 词表重构 |
| `sensitive-input` | `sensitive-input`（经 `rl_is_opaque_ref`/markers） | 需核对 argv 敏感词检测 |
| `alembic-attestation` | `alembic-attestation` ✅ | `action_type` 含 alembic 且 `attestation_kind != actual_engine` |
| `list-invalid` | `archive-list-safety-failure`（list_summary 语义） | 词表重构 |
| `restore-empty-failure` | `empty-proof-failure` / `restore-semantic-failure` | 词表重构 |
| `semantic-failure` | `semantic-projection-failure` | 词表重构 |
| `cleanup-failure` | `restricted-archive-failure`（cleanup_status） | 词表重构 |
| `artifact-ref-invalid` | `artifact-ref-invalid` ✅ | 一致 |
| `section-artifact-owner` | `section-owner` | 改名 |
| `section-artifact-reviewer` | `section-reviewer` | 改名 |
| `artifact-digest` | `artifact-digest` ✅ | 一致 |
| `artifact-schema` | `artifact-schema` ✅ | 一致 |
| `action-unknown` | `recipe-action-type` | 改名 |
| `not-applicable-for-database-action` | `not-applicable-for-database-action` ✅ | 一致 |
| `event-unresolved` | `event-reuse-or-unresolved` | 改名 |
| `event-mismatch` | `event-binding-mismatch` / `event-action-mismatch` | 拆分 |
| `timestamp-order` | `timestamp-order` ✅（action 级）/ `event-time` | 部分拆分 |
| `section-time-order` | （无对应；section 无独立时间排序） | 需重写用例 |
| `snapshot-parent-binding` | `canonical-sidecar-binding` | 改名 |
| `snapshot-self-digest` | `snapshot-self-digest` ✅ | 一致 |
| `event-duplicate-or-invalid` | `event-duplicate` / `event-invalid` | 拆分 |
| `artifact-payload-contract` | `artifact-payload-contract` ✅ | 一致 |
| `attestation-assertion-ref` | `attestation-assertion-mismatch` | 改名 |
| `artifact-missing-or-unsafe` | `artifact-missing-or-unsafe` ✅ | 一致 |
| `artifact-raw-archive` | `artifact-raw-archive` ✅ | 一致 |
| `trusted-assertion-expired` | `trusted-assertion-expired` ✅ | 一致 |
| `attestation-path-binding` | `attestation-path-binding` ✅ | 一致 |
| `self-hash-scope` | `self-hash-scope` ✅ | 一致 |
| `trusted-boundary` | `trusted-boundary` ✅ | 一致 |
| `trusted-boundary-unverified` | `trusted-boundary-unverified` ✅ | 一致 |
| `semantic-gate-contract-version` | `semantic-gate-contract-version` ✅ | 一致 |

---

## 3. 实现级缺陷：canonical-snapshot ↔ sidecar 互认证摘要循环（阻塞 PASS）

**现象**：`rl_validate_canonical_sidecars`（`rl_reviewer_attestation.py`）要求

- snapshot payload 必须含 `sidecar_sha256`，且其值 == sidecar 的 index `sha256`
  （= sidecar 文件字节的 SHA-256，经 `rl_compute_bundle_digest` 对原始字节校验）；
- sidecar payload 必须含 `child_sha256`，且其值 == snapshot 的 index `sha256`
  （= snapshot 文件字节的 SHA-256）。

snapshot 文件字节包含 `sidecar_sha256`=S，sidecar 文件字节包含 `child_sha256`=C，
而 C=sha(snapshot 字节)、S=sha(sidecar 字节)。于是 C 依赖 S、S 依赖 C，构成
`C = A(B(C))` 的哈希不动点。

**证明**：脚本对迭代 `S_{n+1} = sha(sidecar(child_sha256 = sha(snapshot(sidecar_sha256=S_n))))`
跑了 10000 轮，`S` 持续漂移、无收敛 → 不存在不动点（除非找到 SHA-256 前像，
计算上不可行）。

**后果**：任何 producer 都无法让 `canonical-sidecar-digest` 不触发，因而 gate
永远 `BLOCKED`，`PASS` 不可达。`test_rl_gate_emits_a0_only_result_even_when_status_passes`
这一「happy path」因此注定失败，且**不是测试写错，是实现契约不满足**。

**建议修复方案（需 owner 决策，二选一）**：
- (a) snapshot 只以 `sidecar_ref` + `sidecar_sha256` 单向引用 sidecar，sidecar 以
  `child_ref` + `child_sha256` 单向引用 snapshot，但**其中一处 sha 不参与对方文件字节**
  —— 即让 `sidecar_sha256` 存「sidecar 内容（不含 child_sha256 字段）的摘要」，
  或把 `child_sha256` 从 sidecar payload 移到 sidecar 的 index entry（不进文件字节）。
- (b) 用「sidecar 的内部 `child_sha256` 由 snapshot 的 index sha 决定，但 snapshot
  payload 的 `sidecar_sha256` 由 sidecar 的『除 child_sha256 外的稳定前缀』决定」，
  明确文档化单向摘要方向。

无论哪种，都改变了 fail-closed gate 的摘要语义，必须由 A0 计划 owner 审签，
QA 不宜自行放宽。

---

## 4. 其余 4 个文件的根因（可修，方向明确）

| 文件 | 失败数 | 根因 | 修复方向 |
|---|---|---|---|
| `test_rl_catalog_baseline.py` | 1 | `rl_expected_system_baseline` 期望 `"BLOCKED"`，实现返回 `"EXPECTED"`（`rl_catalog_baseline.py:545/683` 语义分歧） | 对齐实现语义（确认哪个是 canonical 后改测试或实现注释） |
| `test_rl_schema_reconciliation.py` | 2 | reason-code canonical 保留 vs 期望剔除 + 敏感字面量 `raw-schema-name` wipe 规则分歧 | 对齐实现 canonicalization 规则 |
| `test_rl_contract_reconciliation.py` | 1 | 测试夹具 route `/search` 与工具 required-relation `/api/v1/search` 前缀不一致 | 夹具补 `/api/v1` 前缀 |
| `test_rl_reviewer_attestation.py` | 4 | 同上 digest 规范化 + `trusted-assertion.v1` vs `.v2` 大字段集 + 同名异常 | 重写 fake verifier 到 v2 字段集 |

---

## 5. 现状与建议

- **已确认可修**：38 中约 34 个是「测试 fixture/断言落后 v2」的确定性漂移，方向
  已经全部厘清（§2/§4），修复 = 重写 fixture 到 v2 + 对齐 finding 码，不触碰 gate 语义。
- **已证明阻塞**：`…_emits_a0_only_result_even_when_status_passes`（1 个）+ 任何依赖
  PASS 的路径，被 §3 的实现级摘要循环阻断，**单改测试无法达成**。
- **建议**：captain 立一个 A0 实现级决策（§3 至少选定 (a)/(b) 之一），再由熟悉
  A0 计划的成员执行实现修复 + 测试对齐；QA 复核最终 38→0 并回归 `pytest apps/api/tests/a0 -q`。
  本次 t9 未自行放宽 fail-closed 安全语义，也未对 `tools/a0/*` 做未审签改动。

## 6. 复现命令

```bash
cd apps/api
PYTHONPATH=<repo-root> .venv/bin/python -m pytest tests/a0 -q   # 38 failed / 326 passed
```
