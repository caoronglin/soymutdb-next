# SoyMutDB 消融 GAP 优化执行报告（2026-09-26）

- **输入**：`docs/dev/ablation/2026-09-26/README.md` 的 6 个 GAP + 5 个 INERT + 1 条弱断言 → 落为 `OPTIMIZATION-CHECKLIST.md` 的 11 项。
- **执行方式**：总控 + 5 个并行子代理（模型 `nwafu/DeepSeek-V4.1-Flash`），各自独占文件集，冻结跨代理契约后再落码。
- **协作前提**：期间存在**并发外部会话**，HEAD 从 `8e78116fd` 一路推进到 `053666680`，并把本次部分改动一并提交（`f5a144f6a` 缓存 scope、`362e7a30b` 双身份渲染、`2836aa4de` E2E 骨架）。本报告按**当前工作树**为准确认结果。
- **未提交**：本轮剩余改动仍在工作树（清单见 §5）。

## 1. 执行总表

| ID | 内容 | 负责 | 状态 | 关键证据 |
| --- | --- | --- | --- | --- |
| OPT-01 | 搜索消费 `gene_crosswalks`，浮出显式跨版本关联 | A | ✅ 关闭 G1 | 红：`assert 'Glyma.05G000100' in {'Glyma.01G000100'}` exit 1 → 绿：`links=[('Glyma.05G000100','cross-version')]` |
| OPT-02 | `site_variant` 纵深防御字段固化 | A | ✅ | `test_opt_crossversion_links.py` 钉住 cache params 含 `site_variant` |
| OPT-03 | 联邦搜索缓存键纳入生物 scope | B | ✅ 关闭 G3 | 键从 `(query, sources)` 扩为 `site_variant/release/assembly/filters`；全 None 时**字节等同旧键** |
| OPT-04 | 外部搜索冗余 `public_id IS NOT NULL` 固化 | B | ✅ | 注释 + `test_opt_federated_cache_redundant_predicate.py`（2 tests） |
| OPT-05 | internal 搜索 client + 内站双 id UI（含复制） | C | ✅ 关闭 G2 | `internalSearch()`（search.ts:156）+ `copy-public-id`/`copy-internal-id` 控件 |
| OPT-06 | `SearchResult` 补 `match_type`/`cross_version`，收紧弱断言 | C | ✅ | `opt06-search-result-fields.test.ts`；`ui02` 重写为值敏感（换绑必红） |
| OPT-07 | 双站扫描要求 `external/*.html` | D | ✅ 关闭 I3 | 删除 `external/index.html` → `FAIL: ... missing a top-level HTML entry` exit 1 |
| OPT-08 | verifier 多哨兵（含 `internal.soymutdb.invalid`） | D | ✅ 关闭 I5 | `DEFAULT_SENTINELS` 常量 + `--print-default-sentinels`；注入 internal origin → exit 1 |
| OPT-09 | 空目录名中的哨兵也检查 | D | ✅ 关闭 I4 | `sentinel #N found in directory path: <rel>`，文件命中时不重复 |
| OPT-10 | 详情页 E2E + 解除 JBrowse 深链 skip | E | ✅ 关闭 G4/G5 | 新增 entity-detail 3 passed；public skip 2 → 1 |
| OPT-11 | internal 站 E2E：登录 → internal_id 检索 → 详情 | E | ✅ 关闭 G6 | `playwright-internal.config.ts` 3 passed / 0 skipped（旧：8 failed / 1 passed） |

**11/11 完成，6 个 GAP 全部关闭。**

## 2. 协调者独立复核（复跑，非采信子代理）

| 复核项 | 命令 | 结果 |
| --- | --- | --- |
| A（OPT-01/02） | `pytest tests/test_ablation_assembly_scope_and_crossversion.py tests/test_opt_crossversion_links.py tests/test_search_database_integration.py tests/test_search_contract.py tests/test_mutants.py` | **47 passed**，exit 0 |
| B（OPT-03/04） | `pytest tests/test_opt_federated_cache_{key,callsites,redundant_predicate}.py tests/test_search_contract.py tests/test_cache.py tests/test_search.py` | **64 passed**，exit 0 |
| C（OPT-05/06） | `apps/web vitest run src/views/SearchView.test.ts src/views/Mutants.test.ts src/ablation` | **7 files / 29 passed**，exit 0 |
| D（OPT-07/08/09） | `python3 -m unittest scripts.test_site_artifact_isolation -v`（6 → 11 tests）+ 扫描真实 `dist` | **11 tests OK**；`OK: external artifact contains no supplied protected values` exit 0 |
| E（OPT-10/11） | `playwright test -c playwright-{public,internal,entity-detail}.config.ts` | **30 passed / 1 skipped**、**3 passed**、**3 passed**，均 exit 0 |
| 消融回归复核 | `pytest tests/test_ablation_*.py tests/test_opt_*.py` | **43 passed**（改前 ASM-04 与联邦缓存 GAP 两项为红） |
| 广域 API 回归 | 16 个搜索/缓存/基因测试文件 | **155 passed**，exit 0 |
| 制品重建 + 守卫 | `pnpm --filter @soymutdb/web build:sites` → 扫描 → `verify-site-variant-artifacts.sh` | **BUILD_EXIT=0 / SCAN_EXIT=0 / VERIFY_EXIT=0** |
| 重建后 E2E 复跑 | internal + public 两套 | **3 passed** / **30 passed / 1 skipped**，exit 0（重建后 `dist/internal` 已含 `search/internal`，internal 用例走真实内站端点） |

## 3. 冻结契约落地确认

- **跨版本链接**（A 产出，C 消费）：`CrossVersionLink` + `SearchResultItem.cross_version: list[...] = []`；双向查询、`release_id` 非空时按 release 过滤、NULL 视为通用；**不新增结果行**（`total_count` 不变），exact 命中保持 `match_type=exact`，`MatchType.CROSS_VERSION` 首次有了生产者；无 provenance 的相似基因不进列表（ASM-05 无回归，有专项负例测试）。
- **内站双身份**（C）：`internalSearch(query, opts?)` → `GET /api/v1/search/internal`；内站渲染双 id 与两个复制控件；外站行为零变化（有回归断言）。

## 4. 未验证项与剩余风险（不得隐藏）

1. **无真实 Redis / 无真实 HTTP 层**：联邦缓存用例使用内存假实现；`format=html` 分支是直接调用端点 + patch 依赖，未走真实 HTTP。
2. **release 线程为 best-effort**：没有已发布 release 时缓存键降级为 `None`，故「不同 release ⇒ 不同键」只在存在 release 时成立。
3. **剪贴板**只在 jsdom 下验证（spy + 回退路径），未在真实浏览器/非安全上下文核实系统剪贴板写入；401→refresh→logout 未打活体后端。
4. **E2E 为离线 mock**：entity-detail 仅断言 iframe `src` 契约（离线无 JBrowse shell，真实 shell 由 `playwright-jbrowse.config.ts` 覆盖）；internal 检索经 URL 深链 `?q=` 触发（antdv `Input` 的 `v-model` 在制品上 fill 不更新组件状态）。
5. **verifier 完整路径**：`build:sites` 与 verifier 在同一次作业内串行执行，但 verifier 以 `SOYMUTDB_SITE_VARIANTS_PREBUILT=1` 消费既有产物；未在单条命令内跑无标记版本。
6. **ruff**：`apps/api/app/api/v1/search.py` 存在 2 条**既有**问题（`I001 :15`、`E501 :34`），非本次引入。
7. **并发覆盖风险**：`packages/api-client/src/search.ts` 等文件已被并发会话提交（`362e7a30b`）；`apps/web/src/views/SearchView.vue` 与全部 e2e 改动仍未提交，若并发会话再次编辑可能覆盖 —— 建议尽快定稿提交。
8. `apps/web/src/ablation/p1-04-variants-cursor-key.test.ts` 的 `vue-tsc` 只读元组报错为既有问题，与本次改动无关。

## 5. 当前未提交改动（回滚点）

```
M apps/api/app/api/v1/search.py
M apps/api/app/search/cache.py
M apps/api/app/services/search_service.py
M apps/api/tests/test_search_federation.py
M apps/api/tests/test_search_scope_provenance.py
M apps/web/src/views/SearchView.vue
M e2e/playwright-entity-detail.config.ts
M e2e/playwright-internal.config.ts
M e2e/static-server.mjs
M e2e/tests/{entity-detail,genes,internal-site}.spec.ts
M e2e/tests/helpers.ts
M scripts/check_site_artifact_isolation.py
M scripts/test_site_artifact_isolation.py
M scripts/verify-site-variant-artifacts.sh
?? apps/api/tests/test_{ablation_*,opt_*}.py
?? apps/web/src/ablation/
?? docs/dev/ablation/
```

- 单文件回滚：`git checkout -- <file>`。
- 注意：`packages/api-client/src/search.ts`（含 `internalSearch`）**已被并发会话提交**，回滚需 revert 该提交，不能只 checkout。

## 6. 建议下一步

1. 由本会话或并发会话**尽快提交**上述工作树改动，避免同文件竞态覆盖。
2. 补齐 §4.1/4.3 的真实依赖验证（真 Redis、活体后端、真实浏览器剪贴板）。
3. 把 `apps/web/src/ablation/*` 从消融草稿提升为常规回归套件（或迁入 `apps/web/src/__tests__`），使 GAP 不回归有长期锚点。
4. 修 `apps/api/app/api/v1/search.py` 的既有 ruff 问题，恢复 `ruff check` 全绿。
