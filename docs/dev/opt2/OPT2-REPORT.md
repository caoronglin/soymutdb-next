# OPT2 第二轮优化执行报告（2026-09-26）

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

- **清单**：`docs/dev/opt2/OPT2-CHECKLIST.md`（8 项 → 5 个子代理）。
- **执行方式**：协调者 + 5 个并行子代理（`nwafu/DeepSeek-V4.1-Flash`），各自独占文件集，冻结跨代理契约后再落码；协调者逐条独立复跑，不采信子代理自述。
- **输入**：`docs/dev/ablation/2026-09-26/OPTIMIZATION-REPORT.md` §4/§6 的未验证项 + `docs/dev/vue-parity/README.md` §5 的残留。
- **前提**：HEAD `053666680`，工作树含前两轮未提交改动；本轮**未提交**。

## 1. 执行总表

| ID | 内容 | 负责 | 状态 | 关键证据（协调者复跑） |
| --- | --- | --- | --- | --- |
| OPT2-01 | 联邦搜索 `format=html` 走**真实 HTTP 层**（httpx ASGITransport + 真实 PostgreSQL） | A | ✅ | 4 tests；断言 200 / `text/html; charset=utf-8` / 非 JSON / 负例内部 id 不在 body |
| OPT2-02 | release 作用域"best-effort"证实或修复 | A | ✅ **证实并修复** | 改前红：`assert [] == ['OPT2RA']`、两个未发布 release 共用 1 个 html key；改后 3 个 release（101/102/None）⇒ 3 个不同键 |
| OPT2-03 | 本轮触及文件的 ruff | A | ✅ | `ruff check app/api/v1/search.py` → `All checks passed!` |
| OPT2-04 | internal 站 E2E 走真实输入 | B | ✅ | 真实 `pressSequentially`；`grep "search?q="` = 0；Playwright internal **3 passed** |
| OPT2-05 | verifier 单条命令 build+verify | B | ✅ | `bash scripts/verify-site-variant-artifacts.sh` → **EXIT=0**；`PREBUILT=1` 分支未破 |
| OPT2-06 | 消融草稿 → 常规回归套件 | C | ✅ | `src/ablation/` → `src/regression/`（5 文件 15 tests 用例数不变），旧目录已删 |
| OPT2-07 | 门户注册 Service Worker | D | ✅ | preview:4173 实拍 `getRegistrations()=1`、state `activated`、离线 reload 仍渲染 |
| OPT2-08 | 研究者门禁（React `ResearcherGate` 对等） | E | ✅ | gate 三态 + 10 角色逐项 + 4 视图 denied/allowed；`/analyses` SSG 未破 |

## 2. 协调者在本轮**新发现并修复**的问题（不在原清单里）

### 2.1 P0：Antdv Next `Input` 的 `v-model` 是**空绑定**（真实功能缺陷）

- **症状**：全局搜索页 `/search` 的搜索框、`/mutants` 的诱变剂筛选框，**打字不进入组件状态**；提交/应用后 URL 与请求都不带关键词。这正是用户说的「功能很多用不了」。
- **证据**：`antdv-next@1.5.4` 的 `Input` 只声明 `value` + `update:value`（`dist/input/Input.d.ts:31,77`），整个类型面 **`grep -c modelValue` = 0**。裸 `v-model` 编译成 `model-value` + `update:modelValue`，组件两者都不认：输入框看起来能打字（浏览器自己保留文本），绑定 ref 始终为空。
- **修复**：`SearchView.vue:312`、`MutantsListView.vue:85` → `v-model:value`。
- **浏览器实测**：`/search` 输入 `Glyma.01G000100` + 提交 → `URL=/search?q=Glyma.01G000100&limit=20`；`/mutants` 输入 `EMS` + 应用 → `/mutants?mutagen=EMS`（修复前两者都不动）。
- **连带修复（更重要）**：**7 个测试文件的 `Input` stub 声明的正是 `modelValue`**（`apps/web/src/test/mount-portal-view.ts` + 6 个 test），也就是说**测试一直在对着一个不存在的契约验证**，所以这个 bug 能穿过 165 个绿灯测试出厂。已把 7 个 stub 改为真实契约（`value`/`update:value`）；改后全量 46 files / 201 tests 仍全绿，且 `Mutants.test.ts` 的那条「编辑诱变剂写入 URL」现在真正走了生产路径。
- **防复发**：新增 `apps/web/src/regression/antdv-input-binding.test.ts`（静态扫描全部 `.vue`，禁止对门面 `Input` 使用裸 `v-model`，并钉住两处已修字段）。

### 2.2 CI 门禁修复：`check:contract` 之前是**红的**

- `pnpm --filter @soymutdb/api-client check:contract` 是 CI 门禁（`scripts/verify-frontend-artifacts.sh:111`、`ci.yml:107`、`baseline-validation.yml:253`），但它**在本轮之前就已失败**：`generated/openapi.d.ts` 停留在 09-25，落后 576 行（含前几轮的 `/admin/settings/site-brand` 等新路由），OPT2-A 又新增了一个可选 query 参数。
- **修复**：`pnpm --filter @soymutdb/api-client generate:api-client` 重新导出 OpenAPI 并重生成客户端类型 → 再次 `check:contract` **EXIT=0**（`OK: client schema in sync with backend OpenAPI.`，可见性报告 `status: PASS`）。随后 `api-client` 26 files / 139 tests 全绿。
- 备份：`.validation/opt2/contract-backup/`（回滚点）。

### 2.3 站点隔离加固：Service Worker 命名空间未随变体分离

- **依据**：DB-CORE-5 明确要求两个变体的 **service-worker 命名空间与缓存保持分离**。原模板 `RUNTIME_CACHE = "soymutdb-runtime"` **不带变体**，而运行时缓存装的正是**导航 HTML**——内网站的页面含私有记录。两个变体一旦落在同一 origin，外部访问者会命中内网页面；`activate` 的清理前缀 `startsWith("soymutdb-static-v")` 还会互删对方的 precache。
- **现状**：今天靠"两个变体各自独立 origin"这一层隐含前提兜住，不是文档要求的显式隔离。
- **修复**：`public/sw.js` 新增构建期注入 `__SW_NAMESPACE__`；运行时缓存名与清理前缀都改为按变体；`scripts/gen-sw.js` 注入 `SITE_VARIANT` 并把占位符纳入守卫。
- **证据**：`dist/external/sw.js` → `SW_NAMESPACE = "external"`；`dist/internal/sw.js` → `"internal"`；两件制品占位符计数 0；verifier EXIT=0。
- **防复发**：新增 `apps/web/src/regression/service-worker-namespace.test.ts`（4 tests：注入存在、缓存名必须带变体、清理前缀按变体、`/api` 守卫必须是路径段判定而非 `includes("/api/")`）。

### 2.4 顺带修正的两处**假警报**（撤回，避免后续做无用功）

| 原判 | 结论 | 证据 |
| --- | --- | --- |
| `dist/` 直接发布缺 `404.html` 会深链 404 | **撤回**：nginx 用 `try_files $uri $uri/ /index.html`；Cloudflare Pages 用内置 SPA 兜底，而该兜底**恰好要求顶层没有 404.html**（`_redirects` 删 catch-all 是 oracle R7 的有意决定） | `infra/docker/web-nginx.conf:84`、`admin-nginx.conf:72`、`apps/web/public/_redirects` |
| `/search/suggest` 无消费者是迁移缺口 | **撤回**：React 基线同样零消费者（`git grep -in suggest <sha> -- apps/web/src` = 0），属既有未接线 API | git grep 基线 |

## 3. 协调者复跑验收矩阵

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| API 联邦/契约（A） | `pytest tests/test_opt2_*.py tests/test_opt_federated_cache_{key,callsites}.py tests/test_search_{federation,contract}.py` | **42 passed** |
| API 消融回归 | `pytest tests/test_ablation_*.py tests/test_opt_*.py tests/test_opt2_*.py` | 见 §3.1 |
| ruff（触及文件） | `ruff check app/api/v1/search.py` | **All checks passed!** |
| 客户端契约 | `pnpm --filter @soymutdb/api-client check:contract` | **EXIT=0，schema in sync** |
| api-client | `pnpm --filter @soymutdb/api-client test` | **26 files / 139 tests** |
| 门户单测 | `pnpm --filter @soymutdb/web test` | **46 files / 201 tests** |
| 门户类型/lint | `typecheck` / `lint` | **0 / 0** |
| 可见文案 | `python3 scripts/check_visible_i18n.py` | **OK** |
| 双站制品 | `bash scripts/verify-site-variant-artifacts.sh`（无 PREBUILT） | **EXIT=0**（BUILD→SCAN→VERIFY） |
| internal E2E | `playwright test -c playwright-internal.config.ts --workers=1` | **3 passed / 0 skipped** |
| 管理端 | `pnpm --filter @soymutdb/admin test` / `typecheck` | 见 §3.1 |
| SW 命名空间 | `dist/{external,internal}/sw.js` | `external` / `internal`，占位符 0 |

### 3.1 收尾复跑（同一轮，全部 exit 0）

| 包 | 命令 | 结果 |
| --- | --- | --- |
| api-client | `pnpm --filter @soymutdb/api-client test` | **26 files / 139 tests passed** |
| web | `pnpm --filter @soymutdb/web test` | **46 files / 201 tests passed** |
| admin | `pnpm --filter @soymutdb/admin test` / `typecheck` | **22 files / 98 tests passed** / **0 错误** |
| charts / ui-vue / i18n-core | 各包 `test` | **4 / 5 / 7 passed** |
| API 消融+优化回归 | `pytest tests/test_ablation_*.py tests/test_opt_*.py tests/test_opt2_*.py` | **61 passed** |
| internal E2E（制品就位时） | `playwright test -c playwright-internal.config.ts --workers=1` | **3 passed / 0 skipped**（复跑 2 次一致） |

> 说明：internal E2E 在两次"合并脚本"里报过 3 failed，其中一次已定位为 **`pnpm --filter @soymutdb/web build` 的 `emptyOutDir` 清空了 `dist/{external,internal}`**（webServer 报 `ENOENT: apps/web/dist/internal/index.html`）；制品就位后连续两次复跑均 3 passed。已列入 §4.7 的操作顺序约束。

## 4. 未验证项与剩余风险（不得隐藏）

1. **真实 Redis 仍不可达**：本机无 `redis-server`/`valkey-server` 二进制；联邦搜索与缓存用例仍走进程内假实现。OPT2-01 只把"真实 HTTP 层"补齐，没有补"真实 Redis"。
2. **真实外部 provider 未打**：`format=html` 测试用确定性命中替身，adapter 内部未运行（外网检索在本沙箱不可依赖）。
3. **SW 未验证**：gh-pages 子路径部署下的 scope 推导、跨版本轮换（需连续两次真实部署）、Firefox/Safari。
4. **研究者门禁**：真实研究者 JWT 会话未验（用路由拦截 + 10 角色单测替代）；**匿名深链 `/analyses` 最终落在 `/login` 而非门禁空态**（`getCurrentUser` 401 → 既有 `onAuthLogout` 硬跳，React 基线同样如此）；空态实际只对"已认证的非研究者"可见。若要匿名也停在空态，需产品决策改 `main.ts` 或让该查询不走 refresh。
5. **`isResearcher` 有意偏离 React**：React 用 `{researcher, administrator}`，比服务端授权表更严，会误拒 curator/data_manager 等本可提交分析任务的角色；Vue 版按 `apps/api/app/core/security.py:141-160` 的服务端口径实现（除 viewer 外都授予 researcher）。前端门禁只是 UX，服务端 `require_role` 才是边界。
6. **repo-wide ruff 债务 404 条**（UP045×143 / E501×89 / UP037×59…）**不在本轮**：ruff 不在任何 CI 门禁（`verify-backend-tests.sh`/`ci-job-steps.sh` 无 ruff，`.cnb.yml` 0 命中），285 条自动修复属无关大重构。
7. **两个"整版 E2E 变红"的假警报（已于 OPT3 定位，见 §7 勘误）**：
   - `pnpm --filter @soymutdb/web build` 的 vite `emptyOutDir` 会清空 `dist/{external,internal}` → internal E2E 报 `ENOENT: apps/web/dist/internal/index.html`。制品顺序必须是：先普通 build，**最后**跑双站 verifier。
   - **更主要的成因**：脚本重定向了 `XDG_CACHE_HOME`（pnpm 沙箱 helper）而 Playwright 依此查找浏览器 → `browserType.launch: Executable doesn't exist at <XDG_CACHE_HOME>/ms-playwright/...`，一个环境问题会让整套 3 条用例同时红。修法：`export PLAYWRIGHT_BROWSERS_PATH="${HOME}/.cache/ms-playwright"`（已写入 `e2e/README.md` 的 Sandbox 说明与 `.validation/opt3/verify.sh`）。
8. **既有失败**：`apps/api/tests/a0/test_rl_catalog_baseline.py` 收集失败（`No module named 'tools'`），与本轮无关。
9. **未验证的 E2E 面**：internal 站的真实 `INTERNAL_BASE_URL` 部署；`OFFLINE=false` 分支。
10. **对本报告 §3.1 注解的勘误**：那条「两次合并脚本各报 3 failed」的批注只对其中一次（`emptyOutDir`）成立；复现后确认主导原因是上面的浏览器路径问题，产品侧的 internal E2E 在制品就位时**连续多次 3 passed**。

## 5. 回滚点

| 范围 | 回滚 |
| --- | --- |
| 本轮全部 | `git checkout -- <file>`（未提交） |
| 客户端契约重生成 | `.validation/opt2/contract-backup/{openapi.json,error-codes.json,openapi.d.ts}` |
| SW 模板 | `git checkout -- apps/web/public/sw.js apps/web/scripts/gen-sw.js` |

## 6. 建议下一步

1. **尽快提交**：三轮（消融 / 优化 / OPT2）改动都还在工作树，`SearchView.vue`、`scripts/*`、`e2e/*` 有被并发会话覆盖的记录。
2. 把「测试 stub 必须与真实组件契约一致」写进 review 清单；本轮 7 个 stub 说谎导致 P0 漏网，值得扩到 admin 与其它门面组件。
3. 真 Redis / 真实外部 provider 的验证放到有依赖的环境；本沙箱标注为环境阻塞。
4. ruff 债务要么纳入门禁并分批清理，要么从 Makefile 的 `lint` 目标里去掉指向不存在的 `apps/api/src` 的陈旧命令——现状是"看起来有 lint，实际没跑"。
