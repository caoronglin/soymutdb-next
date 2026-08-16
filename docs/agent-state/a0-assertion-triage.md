# A0 断言漂移 Triage（38 failures）

> 由 `qa-verify`（task t7）产出。判断 A0 release-lifecycle 工具链的 38 个
> 失败是否与本次 Phase 2/3/4 改动相关。

- **Triage:** 2026-08-16 16:24 +0800
- **范围:** `apps/api/tests/a0/`（10 个测试文件）+ `tools/a0/*.py`（被测试实现）
- **复现:** `PYTHONPATH=<repo-root> pytest tests/a0 -q` → **确定性 38 failed / 326 passed**（两次运行一致，无 Docker、无网络、无 DB 依赖，纯内存契约断言）。

---

## 1. 结论（TL;DR）

**38 个失败与本次 Phase 2/3/4 改动完全无关，是 A0 工具链自身在初始基线提交
（`4d970bfba`）就已内嵌的「测试期望 ↔ 工具实现」契约漂移。**

判定依据（三条独立证据）：

1. **无文件被本次改动触碰**：`git status --short tools/a0/ apps/api/tests/a0/`
   为空 —— 整个 A0 目录在工作树中零修改；两者最后一次提交都是 baseline
   `4d970bfba`（2026-08-07），早于本 run 的 `91f4f8f97` 及所有 Phase 2/3/4 diff。
2. **失败发生在内存契约断言**，不依赖 Docker/Postgres/网络 —— 此前基线报告把
   38 个 a0 失败与 77 个 Docker 错误区分开来，本 triage 进一步确认这 38 个是
   纯粹的工具语义断言失败。
3. **根因是 finding-code / 字段语义 / digest 三者的词汇表漂移**，见 §2 分类。

> 是否为「回归」：不是。是否为「发布闸门」：是 —— A0 定义里 gate `BLOCKED`
> 会阻断后续 A1（生产迁移/写入）授权，因此这 38 个失败虽与本次改动无关，但
> 在正式 release 前必须被 a0 工具链 owner 修复（见 §4 建议），不能当作噪声忽略。

---

## 2. 失败分类与根因

| 文件 | 失败数 | 根因类别 |
|---|---|---|
| `test_rl_gate_evidence.py` | 30 | **finding-code 词汇表漂移**（主因） |
| `test_rl_reviewer_attestation.py` | 4 | digest/语义漂移 |
| `test_rl_schema_reconciliation.py` | 2 | 字段/序列化漂移 |
| `test_rl_catalog_baseline.py` | 1 | 状态枚举漂移（`EXPECTED` vs `BLOCKED`） |
| `test_rl_contract_reconciliation.py` | 1 | 测试夹具路径前缀漂移 |

### 2.1 `test_rl_gate_evidence.py`（30 → 最大簇）

**最典型的根因**：assertion 期望某个 finding code 出现在
`rl_result["findings"]` 里，但实际 `findings` 现在已经是被一组不同的
「顶层契约违规」code 占据（`semantic-gate-contract-version`,
`action-recipe-version`, `recipe-id`, `missing-top-level:*`…），而测试所期望的
业务层 code（`nonzero-exit` / `missing-source-digest` / `list-invalid` /
`restore-empty-failure` / `semantic-failure` / `cleanup-failure` /
`missing-artifact` / `unsafe-path` / `alembic-attestation` /
`artifact-ref-invalid` / `attestation-assertion-ref` / `artifact-schema` /
`action-unknown` / `not-applicable-for-database-action` / `event-unresolved` /
`event-mismatch` / `timestamp-order` / `section-time-order` /
`snapshot-parent-binding` / `artifact-payload-contract` …）**从未被当前实现发出**。

对照 `tools/a0/rl_emit_gate_evidence.py` 实际会 `rl_finding(...)` 的 code 集合：
`artifact-root`, `attestation-*`（12 个）, `reviewer-identity`, `review-root`,
`self-hash-scope`, `trusted-boundary`, `trusted-boundary-unverified`,
`semantic-gate-contract-version`, `gate-contract-error`, `gate-result-write`,
`root-binding` … —— 与测试期望的 vocabulary **几乎零交集**。

即：**这是两代不同的 gate finding-code 契约**。测试写的是更早一版「数据库
action 语义码」，实现已演进成「attestation / trusted-boundary / top-level
contract」语义码。断言字符串两侧都是既有代码，未随本次改动变化。

### 2.2 `test_rl_reviewer_attestation.py`（4）

- `test_rl_manifest_digest_scope_excludes_derived_fields`: hash 断言
  `76b56d… == 3ff49b…` 不相等 —— manifest digest 的规范化范围（哪些字段算
  derived、被排除）在实现与测试期望间不一致。
- `test_rl_reviewer_attestation_passes_only_with_fake_external_assertion`:
  `'BLOCKED' == 'PASS'` —— 实现收紧后对 fake external assertion 的门槛产生
  了不同的 blocking 判定。
- `test_rl_reviewer_attestation_blocks_assertion_manifest_digest_mismatch`:
  期望 finding `trusted-assertion-digest-mismatch`，但该 code 不在当前实现的
  vocabulary 里（同类 §2.1）。
- `test_rl_reviewer_attestation_rejects_self_hash_scope`:
  `DID NOT RAISE ValueError` —— 预期拒绝路径在实现里未触发同名异常。

### 2.3 `test_rl_schema_reconciliation.py`（2）

- `test_nonrelation_relkind_…`: 期望 `unknown_relkind` 这类 reason code
  **被当作 applicable 而不是 canonical 保留**；实现把它作为 canonical
  reason code 保留下来 → `assert 'unknown_relkind' not in reason_codes` 失败。
- `test_invalid_reason_category_kind_and_digest_are_canonicalized_without_echo`:
  序列化里仍含 `raw-schema-name` / `"BLOCKED"` 等测试认为应被 wipe 的原始
  敏感字面量 → 序列化规范化规则漂移。

### 2.4 `test_rl_catalog_baseline.py`（1）

`rl_expected_system_baseline` 期望 `"BLOCKED"`，实现返回 `"EXPECTED"` ——
对「无 context 时每个 object 的 expected baseline」判定，实现与测试对
`EXPECTED`/`BLOCKED` 的语义定义不一致。

### 2.5 `test_rl_contract_reconciliation.py`（1）

测试夹具写入 `apps/api/app/api/v1/search.py`（`@router.get("")`, prefix
`/search` → route `/search`），但 `rl_reconcile_contracts` 的 required relation
是 `("search", "GET", "/api/v1/search")`。夹具路径少了 `/api/v1` 前缀，导致
route 被判 `missing`，`assert any(route.status == "observed"…)` 失败。
（夹具没跟上工具的 required-relation 常量。）

---

## 3. 与本次改动的关系判定

- Phase 2（admin page builder）/ Phase 3（static publication）/ Phase 4（web
  UI）改动均**未触及** `tools/a0/*` 或 `apps/api/tests/a0/*`。
- 所有 38 个失败在本次 run 的起点（baseline `91f4f8f97`）就已存在，且就我所
  记录的 Phase-1 基线（`execution-baseline.md` §5.1）中已列为「38 failure =
  a0 RL gate evidence 断言漂移」。
- 失败是**确定性**的（两次运行逐字节一致），非 flaky，非 Docker/环境导致。

→ **结论：与本次改动无关；属 A0 工具链在 baseline 内嵌的 test↔impl 契约漂移。**

---

## 4. 建议（非本次 range，需 a0 owner 单独处理）

1. **统一 finding-code 契约**：以 `tools/a0/rl_emit_gate_evidence.py` 当前实现
   为准，更新 `test_rl_gate_evidence.py` 的 30 个断言码；或反方向补充实现来
   发出测试所期望的业务层 code。二选一后跑 `pytest tests/a0 -q` 到绿。
   推荐前者（实现是较新语义），但需 a0 计划 owner 确认哪一版是 canonical。
2. **digest/字段规范化**：对齐 `rl_reviewer_attestation` 与
   `rl_schema_reconciliation` 的 derived-field 排除规则和敏感字面量 wipe 规则。
3. **状态枚举语义**：对 `EXPECTED`/`BLOCKED` 在 catalog baseline 与 reviewer
   attestation 中的语义做注释与对齐。
4. **夹具路径**：`test_rl_contract_reconciliation.py` 夹具补 `/api/v1` 前缀，
   或在 tool 的 required-relation 常量里明确 api/v1 前缀约定。
5. 修完后建议跑 `pytest tests/a0 -q -p no:cacheprovider` 并比对 38→0。

> 注意：A0 gate 语义是 fail-closed（`BLOCKED`），因此这些失败会阻断后续 A1
> 生产迁移授权。建议 captain 将「A0 工具链契约修复」立为独立 follow-up
> task，指派给熟悉 A0 计划（`docs/superpowers/plans/2026-07-19-a0-factual-reconciliation-implementation-plan.md`）
> 的成员，不并入本次 Phase 2/3/4 交付验收。

---

## 5. 复现命令

```bash
cd apps/api
PYTHONPATH=<repo-root> .venv/bin/python -m pytest tests/a0 -q   # 38 failed / 326 passed
```
