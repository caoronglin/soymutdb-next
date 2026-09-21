# Phase 1 · P0 正确性与隔离

> **父计划：** `plan.md`（第二轮审计版 §14/§19）+ Gate A（`docs/ops/gate-a-decision-brief-2026-09-20.md`，已签批）
> **前置：** Phase 0 完成（`docs/ops/phase-0-fact-baseline-2026-09-20.md`）；Gate A 四项 ADR 已 Accepted（`docs/adr/0004`–`0007`）。
> **Wave：** W1 ｜ **退出判据：** §3
> **范围说明：** D8（突变体公开身份）已在 Phase 0 核实为**合规**并解除，**不在本阶段**。本阶段只处理仍存的 P0：站点隔离、fail-closed 能力收口、身份契约回归锁定。

---

## 0. 为什么 Phase 1 现在很小

Phase 0 用实测把原"8 项缺陷"收敛：唯一真正的 P0 候选 D8 被证合规；其余为 P1 性能/契约项，挂到 Phase 3/4 或 Gate A。因此 Phase 1 只保留三条**正确性/隔离**主线：

1. **P0-3 external/internal 泄漏**——负向套件覆盖全部载体，杜绝内部数据外泄。
2. **D5 能力收口**——7 类 fail-closed 导入在 API 返回 422 + Admin UI 隐藏，杜绝用户触发"排队后失败"任务。
3. **身份/上下文/assembly 契约回归锁定**——ID/CTX/ASM 矩阵全绿、无 skip/xfail，锁住 D8 合规结论。

---

## 1. 任务清单

### P1-1 · external/internal 泄漏负向套件（P0-3）

**Files:** 扩展现存 `scripts/check_site_artifact_isolation.py`、`scripts/test_site_artifact_isolation.py`；新增 API 级负向测试 `apps/api/tests/test_external_leakage_negative.py`
**依赖：** Node 切到 **24.19.0**（`check-toolchain-pins.py` 要求；环境默认 26.8.1 会被拒）；web 可构建
**Steps:**
1. 负向断言覆盖 §5.2 全部载体：`HTTP body` / `HTTP headers` / `error responses` / `redirect Location` / `URL` / `SSR payload` / `HTML` / `JS` / `JSON` / `source maps` / OpenAPI examples / `logs` / analytics payload / `cache key+value` / generated artifacts。
2. 用带唯一哨兵值的**未发布**突变体 + 一个已知 `internal_id`：断言 external 侧对这些**零命中**，且匿名按 internal_id 查询返回统一 not-found（**不确认存在性**，ID-02）。
3. 构建 external/internal 双制品后跑隔离检查；**不得 skip/xfail** 任何隔离场景；当前未覆盖载体登记为缺口，不冒充通过。
4. 无构建产物时标 `SKIPPED（缺 dist）`，不计通过（`scripts/smoke.sh` 语义）。

**Verify:**
```bash
# 需 node 24.19.0
python3 -m unittest scripts.test_site_artifact_isolation -v
pnpm --filter @soymutdb/web build:sites
python3 scripts/check_site_artifact_isolation.py \
  --external-root apps/web/dist/external --internal-root apps/web/dist/internal \
  --sentinel "$UNRELEASED_SENTINEL"
cd apps/api && .venv/bin/python -m pytest tests/test_external_leakage_negative.py -q
```
**Accept:** 全部载体有断言；`internal_id`/哨兵/internal origin 在 external 零命中（有证据）；无 skip/xfail；未覆盖载体登记为缺口。

---

### P1-2 · fail-closed 导入能力收口（D5）

**Files:** `apps/api/app/core/features.py`（已有开关）、导入相关 router/service（`apps/api/app/api/v1/*import*`、`services/import_*`）、`apps/admin`（导入 UI）、新增 `apps/api/tests/test_import_capability_closure.py`
**依赖：** 无数据库依赖（纯门禁验证）
**Steps:**
1. 对 7 类默认关闭的导入（fasta/gff3/vcf/blast_db/seed_data/expression_csv/homolog_csv）：
   - **API 侧**：开关关闭时，提交该类导入返回 **422**（明确"能力未启用"），**不**入队、不产生 worker fail-closed 任务。
   - **Admin UI 侧**：开关关闭时，对应入口**隐藏或禁用**，不让用户提交。
2. 核对 `features.py:51-70` 的开关同时门控 API 与 UI（不能只藏 UI）。
3. 新增测试：每个关闭类型 → API 422；每个关闭类型 → UI 不渲染提交入口（前端单测或组件断言）。
4. **不重开任何开关**（重开前置是 ADR-0005 的幂等协议，属 Phase 2）。

**Verify:**
```bash
cd apps/api && .venv/bin/python -m pytest tests/test_import_capability_closure.py -q
```
**Accept:** 7 类关闭类型 API 均 422 且无入队；Admin UI 均隐藏/禁用；有回归测试；无开关被擅开。

---

### P1-3 · 身份/上下文/assembly 契约回归锁定

**Files:** `apps/api/tests/`（`test_mutants.py`、`test_public_id_service.py`、`test_search_contract.py`、`test_search_database_integration.py`、`test_genes.py`、`test_gene_service.py` 及跨版本/crosswalk 相关测试）
**依赖：** mamba PostgreSQL（已就绪，`SOYMUTDB_TEST_DATABASE_URL`）
**Steps:**
1. 跑 `database-core-contract.md` §7 矩阵，确认存在且全绿、**无 skip/xfail**：
   `ID-01~05`、`CTX-01~03`、`ASM-01~05`。
2. 对每个矩阵项记录：测试文件、站点/权限、查询、预期。缺口（无对应测试的项）登记为**阻断项**，不降级门禁。
3. 重点复核（承接 Phase 0 D8 结论）：external 按 `public_id` 命中且响应无 `internal_id`（ID-01）；external 按 `internal_id` 不确认存在性（ID-02）；internal 授权按任一 ID 定位同一实体（ID-04）。
4. crosswalk（迁移 0034 已建）确认 ASM-04/05：v4 exact + 明示 v5 关联；相似但未映射基因**不**生成跨版本关系。

**Verify:**
```bash
cd apps/api
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_testfixtures' \
  .venv/bin/python -m pytest tests/test_mutants.py tests/test_public_id_service.py \
  tests/test_search_contract.py tests/test_search_database_integration.py tests/test_genes.py -q
```
**Accept:** 矩阵项全部有对应测试且通过；pass/fail 计数入 PR；无 skip/xfail；缺口显式登记。

---

## 2. 阶段退出判据（Gate-1）

```bash
# P0 merge-ready: S3/E2
cd apps/api && .venv/bin/python -m pytest tests/test_external_leakage_negative.py \
  tests/test_import_capability_closure.py tests/test_mutants.py tests/test_public_id_service.py \
  tests/test_search_contract.py tests/test_search_database_integration.py tests/test_genes.py -q
python3 -m unittest scripts.test_site_artifact_isolation -v
# 无 skip/xfail（隐私/隔离/身份场景）
```

**DoD 勾选项：**
- [ ] P1-1 泄漏负向套件覆盖全部载体，`internal_id`/哨兵 external 零命中
- [ ] P1-2 七类 fail-closed 导入 API 422 + UI 隐藏，有回归测试
- [ ] P1-3 ID/CTX/ASM 矩阵全绿、无 skip/xfail、缺口登记
- [ ] 每个 P0 达 **S3/E2**（merge-ready）；准备发布另行达 **S4/E3**
- [ ] PR 附命令 + pass/fail 计数 + 泄漏扫描结果 + 未验证项

**未验证项披露：** 若 node 未切 24.19.0 或无 web 构建产物，P1-1 的制品扫描部分标 `SKIPPED（原因）` 并阻断"external 零命中"结论，**不得冒充通过**。

---

## 3. 风险与回滚

| 风险 | 缓解 |
|---|---|
| node 版本不符导致 web 构建/门禁失败 | 先切 24.19.0（`.nvmrc`）；未切则 P1-1 制品部分 SKIPPED |
| 泄漏载体遗漏 | 按 §5.2 清单逐项断言；缺口登记不降级 |
| 误重开导入开关 | P1-2 明确"不重开"，重开属 Phase 2（ADR-0005） |
| 用 skip/xfail 伪装矩阵通过 | 退出判据显式查 skip/xfail；P0 禁绕过 |

**本阶段改动集中在门禁/收口/测试**，回滚 = 还原对应 PR；无数据迁移、无不可逆操作。

---

## 4. 交付后下一步

Phase 1 退出（P0 S3/E2）后进入 **Phase 2（导入协议与 canonical 数据链路）**，按 ADR-0004（module_data_rows promotion）+ ADR-0005（幂等/可见性）实现写入器闭环，并在 ClickHouse 可用后补 T0-6 引擎确认。性能项（D1/D2/D4/D7）归 Phase 3 基线 → Phase 4 优化；`total_count`（ADR-0006）随 Phase 4 搜索改造落地。

---

## 修订（Review 2026-09-20，强化 P1-2 / P1-3）

> 回应 Phase 0/Gate A review 的 F1/F5/F6。不改变本阶段三大主线，只收紧判据。

### P1-3 加强（F5 + F1 残余）——逐矩阵项覆盖，禁止"有测试文件=全覆盖"

1. **逐项列表**：对 `database-core-contract.md` §7 的每个矩阵 ID 建覆盖表：
   `ID-01..05`、`CTX-01..03`、`ASM-01..05`、`UI-01/02`、`E2E-01/02`。
   每行：矩阵 ID → 对应测试文件:用例 → 站点/权限 → 预期 → 状态(有/缺)。
2. **重点核查可能缺口**（Phase 0 未逐一证实，极可能缺专门测试）：
   - `CTX-01/02/03`：跨 site variant / release / assembly 的**缓存隔离**——需专门集成测试证明缓存不串上下文。
   - `ID-03`：internal 未授权查询返回 401/403 且无数据。
   - `UI-01`：突变体列表/详情**只显示 public_id、不显示内部 id**（前端断言）。
3. **缺口即阻断**：任一 P0 矩阵项无对应测试 → 登记为阻断项并补测试，**不得降级门禁**。
4. **F1 残余收尾**：重新生成 TanStack 路由树，消除 `routeTree.gen.ts` 里的过期 `$ln`（实际路由为 `$id.tsx`，传值是 public_id）；确认无 `$ln` 残留。

### P1-2 加强（F6）——先测现状再补

1. **先验证**：对 7 类关闭类型，实测当前 API 行为——是**直接 422**，还是**入队后 worker fail-closed**？Phase 0 只证实了 worker adapter 会 raise，未证实 API 侧现状。
2. 若已 422 → 只补回归测试锁定；若入队后失败 → 改为 API 层 422 + Admin UI 隐藏/禁用，杜绝"排队后失败"任务。
3. 每一步记录实测证据（Status Code + Body）。
