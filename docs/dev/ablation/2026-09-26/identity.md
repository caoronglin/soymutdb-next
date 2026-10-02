# W1 消融报告：身份与公开边界（ID-01～ID-04 + 未发布负例）

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../../ARCHIVE.md)。

- 工作流：W1「身份与公开边界」
- 执行者：消融子代理 A
- 基线：`git HEAD 8e78116fd`（`docs/dev/ablation/2026-09-26/PLAN.md` §2）
- 日期：2026-09-26
- 方法：真实代码路径对照 → 只中和一个保护因素（monkeypatch 优先）→ 比对判定
- 判定口径：`GUARD-ACTIVE` / `GUARD-INERT` / `GAP`（见 `PLAN.md` §1）；证据分级 E1（真实运行）

## 1. 目标与范围

验证 `docs/dev/database-core-contract.md` 中「身份分离 / 公开边界」类不变量在当前 HEAD 上是否**真的由代码守卫**，
而不是仅仅「历史上测试通过」。覆盖：

| 场景 | 不变量 | 锚点测试 |
| --- | --- | --- |
| ID-01 | 外部匿名响应只携带 `public_id`，不带持久键；外部搜索按 `public_id` 命中 | `test_mutants.py::test_public_responses_carry_public_id_only`、`test_search_database_integration.py::test_external_mutant_search_uses_public_id_only`、`test_search_contract.py::test_external_search_does_not_expose_mutant_persistence_ids` |
| ID-02 | 已存在的内部整型 id 不是公开定位符；与未知 id 同一 404 包络（无存在性预言机） | `test_mutants.py::test_internal_persistence_key_is_not_a_public_locator` |
| ID-03 | 内部端点必须服务端授权；401/403 无数据；成功响应 `Cache-Control: private, no-store` | `test_search_contract.py::test_internal_search_sets_private_no_store_header`、`test_search_internal_http.py`（3 条） |
| ID-04 | 内部授权后可用 `public_id` 与 `internal_id` 命中同一实体，并回报 `matched_field` | `test_search_database_integration.py::test_internal_search_returns_both_identities_and_matched_field` |
| NEG-* | 草稿/未发布/缺 `public_id`/无活动 release 一律 fail-closed；未发布记录内部可见外部不可见 | `test_mutants.py` 4 条负例、`test_search_database_integration.py::test_unpublished_mutant_is_visible_internally_only` |

**不在本报告范围**：双站制品/`dist/external` 泄漏（W6）、Redis 缓存键与站点隔离（W3）、assembly/跨版本（W2）、
前端查询键（W4）；这些在对照命令中会一并变绿，但不作为本工作流判定。

## 2. 环境与命令

- Node `v24.19.0`；API 解释器 `apps/api/.venv/bin/python` = Python `3.14.6`。
- PostgreSQL 16 常驻 `127.0.0.1:55432`（user `soymutdb`，trust）。
- 本工作流专用库：`abl_identity`（每轮 pytest 前 drop/create）。
- 新建（未提交）临时测试：`apps/api/tests/test_ablation_identity_public_boundary.py`（13 条用例，全部自带「对照断言 + 消融断言」）。
- **未对任何生产源码做持久修改**；`git diff --stat` 仅显示其他工作流的既有改动（见 §6）。

公共前置：

```bash
cd /mnt/data02/T25ronglin/code/web
PG_BIN=$PWD/.mamba-root/envs/postgres16/bin
$PG_BIN/dropdb -p 55432 -h 127.0.0.1 -U soymutdb --if-exists abl_identity
$PG_BIN/createdb -p 55432 -h 127.0.0.1 -U soymutdb abl_identity
```

对照（14 条锚点，exit 0）：

```bash
cd apps/api && SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_identity' \
  .venv/bin/python -m pytest tests/test_mutants.py::test_public_responses_carry_public_id_only \
  tests/test_mutants.py::test_internal_persistence_key_is_not_a_public_locator \
  tests/test_search_contract.py::test_internal_search_sets_private_no_store_header \
  tests/test_search_contract.py::test_external_search_does_not_expose_mutant_persistence_ids \
  tests/test_search_internal_http.py::test_internal_search_success_carries_private_no_store \
  tests/test_search_internal_http.py::test_internal_search_anonymous_error_is_private_no_store \
  tests/test_search_internal_http.py::test_internal_search_privileged_error_is_private_no_store \
  tests/test_search_database_integration.py::test_external_mutant_search_uses_public_id_only \
  tests/test_search_database_integration.py::test_internal_search_returns_both_identities_and_matched_field \
  tests/test_search_database_integration.py::test_unpublished_mutant_is_visible_internally_only \
  tests/test_mutants.py::test_non_public_mutant_line_is_not_disclosed \
  tests/test_mutants.py::test_public_routes_exclude_draft_and_unreleased_records \
  tests/test_mutants.py::test_public_mutant_routes_fail_closed_without_active_release \
  tests/test_mutants.py::test_missing_public_id_records_fail_closed \
  -v -p no:cacheprovider
```

关键输出：`======================== 14 passed, 1 warning in 2.79s =========================`（完整 39 条锚点另跑为 `39 passed`）。

消融（13 条，exit 0）：

```bash
cd apps/api && SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_identity' \
  .venv/bin/python -m pytest tests/test_ablation_identity_public_boundary.py -v -s -p no:cacheprovider
```

关键输出：`======================== 13 passed, 1 warning in 3.43s =========================`

> 说明：每条消融用例在同一个测试内先跑真实路径（对照）并断言其原始观察，再 monkeypatch 单一因素后重新测量并断言**翻转/不变**。
> 用例通过 = 翻转已被证明；若某个「守卫」实际不起作用，用例会因「未翻转」而失败。

## 3. 逐场景结果表

图例：`ABLATION-RESULT` 行为测试内打印的机器可读证据（原始日志 `.validation/ablation/identity/ablations.log`）。
判定列全部依据「消融后观察是否翻转」。

| 场景 | 对照（命令 + 退出码 + 关键输出） | 消融（单一因素 + 命令 + 退出码 + 关键输出） | 判定 | 证据文件/行 |
| --- | --- | --- | --- | --- |
| ID-01a 公开 HTTP 投影隐藏持久键 | 锚点 `test_public_responses_carry_public_id_only` PASSED，exit 0；`ABLATION-RESULT ID-01.control {"has_internal_id": false, "item": ["cultivar","mutagen","name","public_id","variant_count"], "status": 200}` | 因素：把 `ml.id` 作为 `internal_id` 加入公开投影（`_to_response` 复制 + 原样 `JSONResponse` 绕过 response_model）；`test_abl_id01_public_http_projection_hides_internal_key` 通过，exit 0；`ABLATION-RESULT ID-01.ablation_expose_persistence_key {"has_internal_id": true, "item": [...,"internal_id",...], "leaked_id": true}` | **GUARD-ACTIVE** | `ablations.log`；`test_mutants.py:110-131` |
| ID-01b 外部搜索不以持久键为身份 | 锚点 `test_external_mutant_search_uses_public_id_only` PASSED，exit 0；`ABLATION-RESULT ID-01s.control {"ids": ["SMPUB00001"]}` | 因素：外部命中 `hit.id` 重新绑定为持久键（`_search_mutant_lines` 包装）；`test_abl_id01_search_projection_hides_internal_key` 通过，exit 0；`ABLATION-RESULT ID-01s.ablation_expose_persistence_key {"ids": ["2"], "leaked": true}` | **GUARD-ACTIVE** | `ablations.log`；`test_search_database_integration.py:352-355` |
| ID-02 内部整型 id 非公开定位符 | 锚点 `test_internal_persistence_key_is_not_a_public_locator` PASSED，exit 0；`ABLATION-RESULT ID-02.control {"code": "not_found", "public_id_of_row": "SMHIDDEN01", "status": 404}` | 因素：`GET /mutants/{path}` 增加 `MutantLine.id == <digit>` 回退分支；`test_abl_id02_internal_key_is_not_a_public_locator` 通过，exit 0；`ABLATION-RESULT ID-02.ablation_internal_key_becomes_locator {"public_id": "SMHIDDEN01", "status": 200}`（且 `999999` 仍 404） | **GUARD-ACTIVE** | `ablations.log`；`mutants.py:65-88` |
| ID-03a 内部端点角色门 | 锚点 `test_search_internal_http.py` 3 条 PASSED，exit 0；`ABLATION-RESULT ID-03.control {"anonymous": 401, "viewer": 403, "researcher": 200, "header": "private, no-store"}` | 因素：`app.api.v1.deps.has_role` 恒真（丢弃角色比较）；`test_abl_id03_internal_role_gate_is_load_bearing` 通过，exit 0；`ABLATION-RESULT ID-03.ablation_drop_role_gate {"data": 1, "viewer": 200}` | **GUARD-ACTIVE** | `ablations.log`；`deps.py:77-95`、`search.py:235-243` |
| ID-03b 内部响应 `private, no-store` | 锚点 `test_internal_search_sets_private_no_store_header` + `test_internal_search_success_carries_private_no_store` PASSED，exit 0；`ABLATION-RESULT ID-03c.control {"header": "private, no-store"}` | 因素：`MutableHeaders.__setitem__` 对 `cache-control` 变为 no-op（等价删除该赋值）；`test_abl_id03_cache_control_is_load_bearing` 通过，exit 0；`ABLATION-RESULT ID-03c.ablation_drop_cache_control {"header": null}` | **GUARD-ACTIVE** | `ablations.log`；`search.py:270` |
| ID-04a `matched_field` 注解 | 锚点 `test_internal_search_returns_both_identities_and_matched_field` PASSED，exit 0；`ABLATION-RESULT ID-04.control {"by_public_field": "public_id", "by_internal_field": "internal_id", "by_internal_public_id": "SMPUB00002", "by_internal_type": "exact"}` | 因素：把 `internal_id` 命中降级为 `matched_field="name"`（等价删除该注解分支）；`test_abl_id04_matched_field_annotation_is_load_bearing` 通过，exit 0；`ABLATION-RESULT ID-04.ablation_drop_matched_field {"by_internal_field": "name", "row_found": "SMPUB00002"}` | **GUARD-ACTIVE** | `ablations.log`；`search_service.py:1027-1037` |
| ID-04b 内部 id SQL 分支 | `ABLATION-RESULT ID-04b.control {"matched_field": "internal_id", "mutants": ["SMPUB00003"]}` | 因素：剔除 `matched_field=="internal_id"` 的行（等价删除 `MutantLine.id == internal_id_value` 分支）；`test_abl_id04_internal_id_sql_branch_is_load_bearing` 通过，exit 0；`ABLATION-RESULT ID-04b.ablation_drop_internal_id_sql_branch {"mutants": []}` | **GUARD-ACTIVE** | `ablations.log`；`search_service.py:1013-1014` |
| NEG-01 禁运记录不泄漏 | 锚点 `test_non_public_mutant_line_is_not_disclosed` PASSED，exit 0；`ABLATION-RESULT NEG-EMB.control {"embargoed_detail": 404, "names": ["public-line"]}` | 因素：从 `_visible_public_conditions` 去掉 `is_public IS true`；`test_abl_neg_embargoed_row_leaks_when_is_public_predicate_dropped` 通过，exit 0；`ABLATION-RESULT NEG-EMB.ablation_drop_is_public {"embargoed_detail": 200, "names": ["embargoed-line","public-line"]}` | **GUARD-ACTIVE** | `ablations.log`；`mutants.py:25-36` |
| NEG-02 草稿/非激活 release 不泄漏 | 锚点 `test_public_routes_exclude_draft_and_unreleased_records` PASSED，exit 0；`ABLATION-RESULT NEG-REL.control {"names": ["visible"]}` | 因素：去掉 `release_id == active` 谓词；`test_abl_neg_draft_and_unreleased_leak_when_release_predicate_dropped` 通过，exit 0；`ABLATION-RESULT NEG-REL.ablation_drop_release_scope {"names": ["draft","inactive","null-release","visible"]}` | **GUARD-ACTIVE** | `ablations.log`；`mutants.py:25-36` |
| NEG-03 缺 `public_id` 不泄漏 | 锚点 `test_missing_public_id_records_fail_closed` PASSED，exit 0；`ABLATION-RESULT NEG-PID.control {"body": []}` | 因素：去掉 `public_id IS NOT NULL` 谓词；`test_abl_neg_missing_public_id_leaks_when_predicate_dropped` 通过，exit 0；`ABLATION-RESULT NEG-PID.ablation_drop_public_id_predicate {"names": ["no-public-id"], "public_id": ""}` | **GUARD-ACTIVE** | `ablations.log`；`mutants.py:25-36` |
| NEG-04 无活动 release 时 fail-closed | 锚点 `test_public_mutant_routes_fail_closed_without_active_release` PASSED，exit 0；`ABLATION-RESULT NEG-NORELEASE.control {"status": 503}` | 因素：`app.dependency_overrides[get_release_context]` 返回固定上下文（不再抛 503）；`test_abl_neg_no_active_release_fails_closed` 通过，exit 0；`ABLATION-RESULT NEG-NORELEASE.ablation_drop_fail_closed {"body": [], "status": 200}` | **GUARD-ACTIVE** | `ablations.log`；`release_context.py:93-96` |
| NEG-05 未发布记录搜索不到 | `ABLATION-RESULT NEG-SEARCH.control {"ids": []}`（对齐 `test_external_mutant_search_uses_public_id_only` 的 unpublished 断言） | 因素：外部搜索条件去掉 `is_public IS true`；`test_abl_neg_unpublished_leaks_into_external_search_when_is_public_dropped` 通过，exit 0；`ABLATION-RESULT NEG-SEARCH.ablation_drop_is_public {"ids": ["SMSECRET01"]}` | **GUARD-ACTIVE** | `ablations.log`；`search_service.py:845-852` |
| INERT-01 外部搜索 `public_id IS NOT NULL` | `ABLATION-RESULT INERT-PID.control {"ids": ["SMLAB00009"]}` | 因素：外部搜索条件去掉 `public_id IS NOT NULL`；`test_inert_external_search_public_id_not_null_predicate_is_redundant` 通过，exit 0；`ABLATION-RESULT INERT-PID.ablation_drop_public_id_not_null {"ids": ["SMLAB00009"]}`（含 NULL `public_id` 行仍不出现） | **GUARD-INERT**（冗余，非缺陷） | `ablations.log`；`search_service.py:849` |

合计：**GUARD-ACTIVE 12，GUARD-INERT 1，GAP 0**。

## 4. GAP 与 INERT 发现

### 4.1 GAP

- 本工作流 14 条对照锚点全部通过，**无 GAP**。真实运行命令与退出码见 §2 与 `.validation/ablation/identity/baseline_scenario_anchors.log`。

### 4.2 INERT-01（唯一发现，属防御性冗余）

- 位置：`apps/api/app/services/search_service.py:849`，外部搜索条件里的 `MutantLine.public_id.is_not(None)`。
- 依据：SQL 三值逻辑下 `NULL ILIKE <pattern>` 为 `NULL`（不匹配），因此该谓词对结果集**不可观测**。消融后
  `INERT-PID.ablation_drop_public_id_not_null` 与对照完全一致（`["SMLAB00009"]`），且 NULL `public_id` 行仍未出现。
- 处置建议：不是死代码，可作为「显式意图」保留；若追求最简 SQL 可删除，但需保留路由层 `_visible_public_conditions`
  中的同名谓词（见 4.3）。

### 4.3 观察：同名谓词在两处，语义不同

- `_visible_public_conditions`（`mutants.py:25-36`）中的 `public_id IS NOT NULL` 对**列表路由**是载荷性的
  （NEG-03 消融后缺 `public_id` 的行会进入列表），但对**详情路由**是冗余的（详情另有 `upper(public_id) = …` 等值条件）。
- 因此不能因为「外部搜索里冗余」就整体删除该谓词。

### 4.4 观察：搜索 DTO 的 `'"internal_id"' not in dump` 属结构性断言

- `SearchResultItem`（`app/schemas/search.py:69-91`）根本没有 `internal_id` 字段，所以
  `test_external_mutant_search_uses_public_id_only` 中「dump 不含 `"internal_id"`」在服务层无论怎么改都成立，
  真正承担该断言的是**响应 DTO 的形状**，而非某个运行时判断。
- 该断言并非 dead：一旦有人给 `SearchResultItem` 加 `internal_id`，断言立即翻转。故记为观察项，不单列 INERT。

## 5. 未验证项

1. **ID-02 的「无存在性预言机」只验证了状态码/包络**（已存在内部 id 与未知 id 同为 404 `not_found`），
   未测量两者**时序差异**（是否存在基于响应耗时的侧信道）。→ 未验证。
2. **搜索 DTO 层无法用 monkeypatch 直接注入 `internal_id`**：因 `SearchResultItem` 无该字段，服务层又无法
   从 `SearchHit` 透传，故 ID-01b 采用「把 `hit.id` 重新绑定为持久键」这一等价观察。若要做严格的
   「给 DTO 加字段」消融，需要一次生产编辑（本工作流选择不改源码）。→ 记录为方法边界，非缺陷。
3. **`is_deleted IS false` 谓词**未单独消融（NEG 系列覆盖了 `is_public`/`release_id`/`public_id`/fail-closed）。
4. **站点制品层泄漏**（`dist/external` 是否含内部 id、HTML 片段）不在本工作流；归 W6。
5. **`private, no-store` 在错误路径（401/403）的赋值**来自 `core/exceptions.py:183/205`，本次只消融了成功路径
   `search.py:270`；错误路径未消融。
6. **Redis 真实缓存路径**：本地运行日志显示 `cache_read_failed_fallback_to_db`（无 Redis），故内部搜索
   「绕过共享缓存」的验证归 W3，本报告不重复判定。

## 6. 原始证据附录

### 6.1 工作区状态（证明未持久修改生产源码）

```text
$ git rev-parse HEAD
8e78116fdbcda533a9399f36680cacedcc08dac2

$ git status --short
 M apps/jbrowse/package.json
 M packages/genome-data/package.json
 M packages/genome-view-model/src/index.ts
 M packages/genome-view-model/src/viewport.ts
 M packages/genome-view/package.json
 M pnpm-lock.yaml
?? apps/api/tests/test_ablation_assembly_scope_and_crossversion.py
?? apps/api/tests/test_ablation_cache_site.py
?? apps/api/tests/test_ablation_identity_public_boundary.py
?? apps/web/src/ablation/
?? docs/dev/ablation/
?? packages/genome-view-model/src/errors.ts

$ git diff --stat
 apps/jbrowse/package.json                  |  1 -
 packages/genome-data/package.json          |  1 -
 packages/genome-view-model/src/index.ts    | 21 +++------------------
 packages/genome-view-model/src/viewport.ts |  2 +-
 packages/genome-view/package.json          |  1 -
 pnpm-lock.yaml                             | 16 ++--------------
 6 files changed, 6 insertions(+), 36 deletions(-)
```

`apps/api/app/**` 无任何 diff：本工作流**全部消融走 monkeypatch + 新增 scratch 测试**。
（对照日志另有 `39 passed` 全锚点跑与 `52 passed`「scratch+锚点」合并跑，均 exit 0。）

### 6.2 原始日志文件

| 文件 | 内容 | 结果 |
| --- | --- | --- |
| `.validation/ablation/identity/baseline_scenario_anchors.log` | 14 条场景锚点对照，`-v` | exit 0，14 passed |
| `.validation/ablation/identity/baseline_anchors.log` | 4 个锚点文件全量对照，`-v` | exit 0，39 passed |
| `.validation/ablation/identity/ablations.log` | 13 条 scratch 消融，`-v -s`，含全部 `ABLATION-RESULT` | exit 0，13 passed |
| `.validation/ablation/identity/workspace_state.log` | HEAD / status / diff / 版本 | — |

### 6.3 全部 `ABLATION-RESULT` 原始行

```text
ABLATION-RESULT ID-01.control {"has_internal_id": false, "item": ["cultivar","mutagen","name","public_id","variant_count"], "status": 200}
ABLATION-RESULT ID-01.ablation_expose_persistence_key {"has_internal_id": true, "item": ["internal_id","name","public_id","variant_count"], "leaked_id": true, "status": 200}
ABLATION-RESULT ID-01s.control {"has_internal_id": false, "ids": ["SMPUB00001"]}
ABLATION-RESULT ID-01s.ablation_expose_persistence_key {"ids": ["2"], "leaked": true}
ABLATION-RESULT ID-02.control {"code": "not_found", "public_id_of_row": "SMHIDDEN01", "status": 404}
ABLATION-RESULT ID-02.ablation_internal_key_becomes_locator {"public_id": "SMHIDDEN01", "status": 200}
ABLATION-RESULT ID-03.control {"anonymous": 401, "header": "private, no-store", "researcher": 200, "viewer": 403}
ABLATION-RESULT ID-03.ablation_drop_role_gate {"data": 1, "viewer": 200}
ABLATION-RESULT ID-03c.control {"header": "private, no-store"}
ABLATION-RESULT ID-03c.ablation_drop_cache_control {"header": null}
ABLATION-RESULT ID-04.control {"by_internal_field": "internal_id", "by_internal_public_id": "SMPUB00002", "by_internal_type": "exact", "by_public_field": "public_id"}
ABLATION-RESULT ID-04.ablation_drop_matched_field {"by_internal_field": "name", "row_found": "SMPUB00002"}
ABLATION-RESULT ID-04b.control {"matched_field": "internal_id", "mutants": ["SMPUB00003"]}
ABLATION-RESULT ID-04b.ablation_drop_internal_id_sql_branch {"mutants": []}
ABLATION-RESULT NEG-EMB.control {"embargoed_detail": 404, "names": ["public-line"]}
ABLATION-RESULT NEG-EMB.ablation_drop_is_public {"embargoed_detail": 200, "names": ["embargoed-line","public-line"]}
ABLATION-RESULT NEG-REL.control {"names": ["visible"]}
ABLATION-RESULT NEG-REL.ablation_drop_release_scope {"names": ["draft","inactive","null-release","visible"]}
ABLATION-RESULT NEG-PID.control {"body": []}
ABLATION-RESULT NEG-PID.ablation_drop_public_id_predicate {"names": ["no-public-id"], "public_id": ""}
ABLATION-RESULT NEG-NORELEASE.control {"status": 503}
ABLATION-RESULT NEG-NORELEASE.ablation_drop_fail_closed {"body": [], "status": 200}
ABLATION-RESULT NEG-SEARCH.control {"ids": []}
ABLATION-RESULT NEG-SEARCH.ablation_drop_is_public {"ids": ["SMSECRET01"]}
ABLATION-RESULT INERT-PID.control {"ids": ["SMLAB00009"]}
ABLATION-RESULT INERT-PID.ablation_drop_public_id_not_null {"ids": ["SMLAB00009"]}
```

### 6.4 消融点与生产源码对照

| 场景 | 生产源码位置 | 被中和的单因素 |
| --- | --- | --- |
| ID-01a | `app/api/v1/mutants.py:126-133`（`_to_response`）/ `schemas/variant.py:149-161` | 公开 DTO 不含持久键 |
| ID-01b | `app/services/search_service.py:845-909` | 外部命中以 `public_id` 为身份 |
| ID-02 | `app/api/v1/mutants.py:65-88` | 仅按 `public_id` 定位 |
| ID-03a | `app/api/v1/deps.py:77-95` + `search.py:243` | `require_role(RESEARCHER)` 角色比较 |
| ID-03b | `app/api/v1/search.py:270` | `response.headers["Cache-Control"] = "private, no-store"` |
| ID-04a | `app/services/search_service.py:1027-1037` | `matched_field` 注解分支 |
| ID-04b | `app/services/search_service.py:1013-1014` | `MutantLine.id == internal_id_value` SQL 分支 |
| NEG-01 | `app/api/v1/mutants.py:25-36` | `is_public IS true` |
| NEG-02 | 同上 | `release_id == active_release` |
| NEG-03 | 同上 | `public_id IS NOT NULL` |
| NEG-04 | `app/services/release_context.py:93-96` | 无活动 release 抛 `ServiceUnavailableError` |
| NEG-05 | `app/services/search_service.py:847` | 外部搜索 `is_public IS true` |
| INERT-01 | `app/services/search_service.py:849` | 外部搜索 `public_id IS NOT NULL`（与 ILIKE 冗余） |

### 6.5 临时测试文件

`apps/api/tests/test_ablation_identity_public_boundary.py`（13 用例，未提交）。
因 FastAPI `0.137.1` 的 `_IncludedRouter` 懒构建 `_EffectiveRouteContext`，其中 `_replace_endpoint` 通过
`monkeypatch` 改写共享 `APIRoute.endpoint` 后调用 `_invalidate_effective_contexts(app)` 强制重建路由视图；
该机制本身已由「scratch+锚点合并跑 `52 passed`」证明无跨文件污染。
