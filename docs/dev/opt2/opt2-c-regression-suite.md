# OPT2-06 小结：消融 harness 提升为常规回归套件

- 任务来源：`docs/dev/opt2/OPT2-CHECKLIST.md` OPT2-06（源自 `docs/dev/ablation/2026-09-26/OPTIMIZATION-REPORT.md` §6.3）。
- 日期：2026-09-26。负责人：agent C。
- 改动范围：仅 `apps/web/src/ablation/**` → `apps/web/src/regression/**`，以及本文件。**未改任何应用源码 / 断言 / 依赖。**

## 1. 结论

5 个文件全部判定为**长期不变量**（不是一次性实验草稿），整体迁移到 `apps/web/src/regression/`，
并按语义重命名、补写文件头（守护的不变量 + 消融依据 + 变红含义）。
`apps/web/src/ablation/` 目录已删除。迁移只改文件头注释，文件正文逐字节保留（`cp` 后仅 `edit` 头部），
因此没有放宽/删除任何断言，也没有 `it.skip`。

## 2. 旧路径 → 新路径映射

| 旧路径 | 新路径 | 改名理由 |
| --- | --- | --- |
| `src/ablation/p1-04-variants-cursor-key.test.ts` | `src/regression/variants-cursor-query-key.test.ts` | 内容即「variants 列表 query key 必须携带 cursor」，去掉工单号、点明 query key |
| `src/ablation/opt06-search-result-fields.test.ts` | `src/regression/search-result-fields.test.ts` | 内容即 SearchResult 可选字段的防御性渲染 |
| `src/ablation/ui01-public-id.test.ts` | `src/regression/public-id-boundary.test.ts` | 内容即外部站只暴露 public_id 的公开边界 |
| `src/ablation/ui02-internal-ids.test.ts` | `src/regression/internal-identity.test.ts` | 内容即 internal 站 public_id/internal_id 的区分与复制 |
| `src/ablation/search-context.test.ts` | `src/regression/search-context-scope.test.ts` | 内容即结果行的 assembly/release/source 作用域上下文 |

相对 import 未变：`../views/*.vue` 在 `src/regression/` 下与 `src/ablation/` 下解析结果相同。

## 3. 每个文件头写明的「守护的不变量 + 依据」

| 新文件 | 守护的不变量 | 消融依据 |
| --- | --- | --- |
| `variants-cursor-query-key.test.ts` | 首页与游标页必须占两个不同缓存条目且各读各的数据 | `frontend.md` §3「P1-04 variants 游标键」（GUARD-ACTIVE）+ §6.C |
| `search-result-fields.test.ts` | `match_type`/`cross_version` 保持可选；新载荷渲染、旧载荷照旧 | `opt-c-internal-ui.md` §2/§3 RED；`OPTIMIZATION-CHECKLIST.md` OPT-06 |
| `public-id-boundary.test.ts` | 外部 mutants 列表/详情只渲染并只用 `public_id` | `frontend.md` §3「UI-01 列表/详情」（GUARD-ACTIVE）+ §6.B |
| `internal-identity.test.ts` | internal 站区分并复制两种 id；external 站不泄漏 internal 身份 | `frontend.md` §3「UI-02」+ §4 GAP-UI02；`README.md` §3 G2；`opt-c-internal-ui.md` §2/§3 |
| `search-context-scope.test.ts` | 每行都必须带 assembly/release/source，缺 label 时回退 assembly_id | `frontend.md` §3「SRCH-CTX 结果上下文」（GUARD-ACTIVE）+ §6.D |

每个头部还写明「变红意味着什么」，例如公开边界红 = 公开页面泄漏了持久键。

## 4. 无「不宜长期保留」文件

5 个文件断言的均为生产不变量（查询键、公开身份、internal 身份、可选字段契约、assembly 作用域），
且都经单因素消融被证实为 GUARD-ACTIVE 或 GAP 锚点，故全部迁移，无需保留/删除任何一个。

## 5. 配置

- `apps/web/vitest.config.ts`：`include: ["src/**/*.test.ts"]` → `src/regression/**` 自动被发现，未改。
- `apps/web/tsconfig.json`：`include: ["src"]` → 已覆盖，未改。
- `knip.json`：不含 ablation 字样，无需改。
- `apps/web/src/ablation/` 已 `rm -rf`，目录不存在。

## 6. 验证证据（均实跑）

- 改前基线：`pnpm --filter @soymutdb/web test 2>&1 | tail -6` → `Test Files 37 passed (37)` / `Tests 165 passed (165)`，exit 0。
- 改后：同一命令 → `Test Files 38 passed (38)` / `Tests 173 passed (173)`，0 failed，exit 0。
  - 增量 `+1 file / +8 tests` 来自并发 agent 新建的 `apps/web/src/lib/current-user.test.ts`（单独跑确认 1 file / 8 tests），
    与本次迁移无关；既有 37 个文件一个不少。
- 迁移文件自身：`vitest run src/regression` → `Test Files 5 passed (5)` / `Tests 15 passed (15)`，
  与旧 `src/ablation` 5 文件的用例数（3+2+3+4+3=15）完全一致。
- `pnpm --filter @soymutdb/web typecheck` → exit 0。
- `pnpm --filter @soymutdb/web lint` → exit 0。
- 残留检索（`apps packages scripts e2e .github .cnb.yml`，排除 node_modules/dist）：
  命中仅 5 处，全部是新文件头里对 `docs/dev/ablation/2026-09-26/...` 的**引用文字**，
  已无任何指向旧 `apps/web/src/ablation/` 的活引用。

## 7. 未完成 / 未验证 / 阻塞

- 未完成：无。
- 未验证：`docs/dev/ablation/**`、`docs/dev/vue-parity/**`、`docs/dev/opt2/OPT2-CHECKLIST.md` 内仍写旧路径
  `src/ablation/...`。按所有权约定不改这些文档，属历史报告，保留原样。
- 阻塞：无。
