# OPT2-08 — Vue 研究者门禁（ResearcherGate）小结

> 负责人：E。基线 HEAD `053666680`。React 只读基线 `d3904c2105f34e5d74f3ae3a163d6b25f075bf64`。
> 性质：补齐 React→Vue 迁移的明确对等缺口。**门禁只做 UX；真正的授权边界是服务端
> `require_role(RESEARCHER)`**（`apps/api/app/api/v1/analyses.py`），前端判定永远不等于鉴权。

## 1. 改动文件清单

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| `packages/api-client/src/auth.ts` | 改 | 新增 `CurrentUser` 类型（取自 `generated/openapi.d.ts` 的 `UserResponse`）与 `getCurrentUser(): Promise<CurrentUser>`，走既有 `http.get("/auth/me")`（Bearer + refresh-on-401） |
| `packages/api-client/src/index.ts` | 改 | 追加导出 `getCurrentUser` / `type CurrentUser`（包 `exports` 只暴露 `.`，必须在 barrel 导出） |
| `packages/api-client/src/auth.test.ts` | 改 | `getCurrentUser` 成功解析 + 匿名 401 分支（含"只 refresh 一次"断言） |
| `apps/web/src/lib/current-user.ts` | 新建 | `useCurrentUser()` vue-query 封装；`isResearcher(user)` 纯函数 |
| `apps/web/src/lib/current-user.test.ts` | 新建 | 服务端 10 角色逐项 + `null`/legacy 行 + superuser + 组合式匿名降级 |
| `apps/web/src/components/ResearcherGate.vue` | 新建 | 三态默认插槽门禁；`data-testid` = `researcher-gate-loading` / `researcher-gate-denied` |
| `apps/web/src/components/ResearcherGate.test.ts` | 新建 | 三态 + 登录 redirect 查询参数 + 返回首页 |
| `apps/web/src/views/AnalysesView.vue` | 改 | 页面主体包 `<ResearcherGate>` |
| `apps/web/src/views/AnalysesFastpView.vue` | 改 | 同上 |
| `apps/web/src/views/AnalysesScanpyView.vue` | 改 | 同上 |
| `apps/web/src/views/AnalysesJobView.vue` | 改 | 同上；**并修复 `/:jobId` 未接线**（详见 §5） |
| `apps/web/src/views/AnalysesView.test.ts` | 新建 | denied 挡内容 / allowed 保留自身 `analyses-*` 分支 |
| `apps/web/src/views/AnalysesFastpView.test.ts` | 新建 | 同上（`fastp-*`） |
| `apps/web/src/views/AnalysesScanpyView.test.ts` | 新建 | 同上（`scanpy-*`） |
| `apps/web/src/views/AnalysesJobView.test.ts` | 新建 | 同上（`analysis-job-*`）+ 断言 fetch 使用路由 `jobId` |

未改：`packages/i18n-core/**`、`PortalLayout.vue`、`PortalHeader.vue`、`style.css`、`router/index.ts`、其它 views、`apps/api/**`、`e2e/**`。

## 2. 与 React `researcher-gate.tsx` 逐项对照

| 维度 | React 基线 | Vue 实现 | 一致性 |
| --- | --- | --- | --- |
| loading | `<Spin tip="Checking access…">` | `<StateBlock variant="loading" title="Checking access…">`（仓库空态组件） | 等价；testid `researcher-gate-loading` |
| denied | `<Empty>` + Safety 图标 + 标题 + 说明 | `<StateBlock variant="empty" icon="beaker">` + 标题 + 说明 | 等价；testid `researcher-gate-denied` |
| denied 按钮 | AntD `Button`：Sign in（primary）+ Back to home | `@soymutdb/ui-vue` `Button`：登录（primary）+ 返回首页 | 等价 |
| allowed | `return <>{children}</>` | `<slot />` | 等价 |
| 包住范围 | 4 个 routes 的**页面主体**（含页头/表单/表格），`container` 外壳在外 | 4 个 view 的内层 `div` 内包住页面主体；`PortalLayout`（导航）在门外 | 等价：只挡内容，不挡导航 |
| 视图自身 loading/error | 在 gate 内渲染 | 在 slot 内渲染，未被吞掉（测试断言 `analyses-empty` / `analysis-job-detail`） | 等价 |

### 有意的分歧（已按协调者判据）

1. **`isResearcher` 口径按服务端真相放宽。** React 用 `RESEARCHER_ROLES = {researcher, administrator}`，
   会误拒 `curator`/`data_manager`/`track_manager`/`blast_manager`/`seed_manager`/`content_editor`/`auditor`
   —— 这些角色在 `apps/api/app/core/security.py:141-160` 的 `_ROLE_GRANTS` 里**都授予 researcher**（`administrator` 授予全部，
   只有 `viewer` 不授予）。Vue 改为：`is_superuser` → true；否则 `role_name != null && role_name !== "viewer"`。
   前端误放行由服务端兜底，误拒才是真实缺陷。
2. **登录按钮带 `redirect`。** React 是 `navigate({to:"/login"})`；Vue 用
   `router.push({ path: "/login", query: { redirect: route.fullPath } })`，配合既有 `LoginView`
   的 `safeRedirect` 在登录后回到原页。

## 3. i18n key 清单（当前靠 `defaultValue` 兜底，i18n-core 由协调者补）

`t()` 调用均带 `defaultValue`，因此**即使 catalog 暂无条目也能正确渲染英文**；中文本轮通过
`defaultValue` 给出建议值，待协调者写入 `packages/i18n-core/src/locales/{en,zh}/common.json` 的
`analyses.gate.*` 后自动生效（并覆盖英文默认）。

| key | zh（建议） | en（建议） |
| --- | --- | --- |
| `analyses.gate.checking` | 正在校验权限… | Checking access… |
| `analyses.gate.title` | 需要研究权限 | Research access required |
| `analyses.gate.description` | 分析模块运行 fastp / scanpy 流程，仅对研究者及以上账户开放。请使用研究者账户登录后提交分析任务。 | The Analyze module runs fastp / scanpy pipelines and is available to researcher accounts and above. Sign in with a researcher account to submit analysis jobs. |
| `analyses.gate.signIn` | 登录 | Sign in |
| `analyses.gate.backHome` | 返回首页 | Back to home |

> `defaultValue` 目前全部是英文（与 React 基线文案逐字一致）；zh 建议值需协调者落库。
> 未硬编码任何可见文本；`python3 scripts/check_visible_i18n.py` 通过。

## 4. 验证证据（全部实跑）

### 4.1 单测

```bash
pnpm --filter @soymutdb/api-client test          # EXIT=0；Test Files 26 passed，Tests 139 passed
pnpm --filter @soymutdb/web test                 # EXIT=0；Test Files 44 passed，Tests 194 passed
pnpm --filter @soymutdb/web exec vitest run \
  src/components/ResearcherGate.test.ts src/lib/current-user.test.ts \
  src/views/AnalysesView.test.ts src/views/AnalysesFastpView.test.ts \
  src/views/AnalysesScanpyView.test.ts src/views/AnalysesJobView.test.ts
# EXIT=0；6 files / 20 tests passed
```

新增覆盖点：gate 三态、登录 redirect=`/analyses`、返回首页、4 视图 denied/allowed、
服务端 10 角色逐项、匿名 401→null 不抛错、`getCurrentUser` 的成功与 401。

### 4.2 静态门禁

```bash
pnpm --filter @soymutdb/web typecheck    # EXIT=0，无输出（vue-tsc 0 错误）
pnpm --filter @soymutdb/web lint         # EXIT=0
pnpm --filter @soymutdb/api-client typecheck  # EXIT=0
pnpm --filter @soymutdb/api-client lint       # EXIT=0（4 条既有 warning）
python3 scripts/check_visible_i18n.py    # EXIT=0 (visible i18n OK)
```

### 4.3 SSG 预渲染未被破坏

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000 VITE_JBROWSE_BASE_URL=http://127.0.0.1:5175 \
  pnpm --filter @soymutdb/web build     # EXIT=0
```

`vite build` + `generate-static-routes.ts` 均通过，`[static-routes] /analyses -> analyses/index.html`
照常产出（27 个文档）。门禁只在客户端查询（`useQuery`，setup 顶层无 await），不阻塞预渲染。

### 4.4 活体（Playwright，dev server `127.0.0.1:5173`，拦截 `/api/v1/auth/me` 模拟会话）

真实后端在 8000 上 `/api/v1/auth/me` 返回 401，故用路由拦截构造角色，base 仍是真实 dev server。

| 场景 | 结果 |
| --- | --- |
| 匿名（不被拦截，真实 401） | `GET /auth/me` 401 → 一次 `/auth/refresh` 401 → 既有全局 `onAuthLogout` 跳 `/login`。**不显示分析表单**。这是与 React `main.tsx` 完全一致的既有行为 |
| `role_name=viewer` 访问 `/analyses`、`/analyses/fastp`、`/analyses/scanpy`、`/analyses/j1` | 4 条全部 `researcher-gate-denied=true`，无提交表单/表格 |
| `role_name=viewer` 点「登录」 | 跳转实测为 `/login?redirect=/analyses` |
| `role_name=researcher` 访问 `/analyses`、`/analyses/j1` | 门禁放行；`analyses-open-fastp` / `analysis-job-detail` 正常渲染 |
| `is_superuser=true, role_name=null` | 门禁放行 |
| `role_name=researcher` + `/analyses/j1` | 无 `Missing required prop: "jobId"` 警告（见 §5） |

结论：匿名深链会被既有全局 logout 处理器弹到 `/login`（与 React 同）；**已认证的非研究者**看到门禁空态，
研究者看到内容。两者都不再"看到表单、提交后 401"。

## 5. 附带修复：`/analyses/:jobId` 的 jobId 从未接线

`AnalysesJobView.vue` 原用 `defineProps<{ jobId: string }>()`，但 `router/index.ts` 的
`PORTAL_ROUTES` 映射**没有 `props: true`**，导致运行时 Vue 警告 `Missing required prop: "jobId"`、
`getAnalysis(undefined)`。改为与同目录 `GeneView`/`MutantDetailView` 一致地读
`useRoute().params.jobId`（`computed`）。测试断言 `getAnalysis` 以 `"j1"` 调用。未改 `router/index.ts`。

## 6. 未完成 / 未验证 / 阻塞

- **未验证：真实研究者后端会话下的 allowed 分支。** 8000 端口的 API 未提供可用登录会话，
  故 allowed 分支用 Playwright 路由拦截验证（`/auth/me` 200 + 角色），非真实 JWT。
- **未验证：匿名分支"门禁空态"是瞬态。** 因 `onAuthLogout` 硬跳 `/login`，匿名用户最终落在登录页
  而非空态卡（React 同样如此）。若产品希望匿名也停在空态，需要产品决策（不在本轮）。
- **未做：`packages/i18n-core` 落 key。** 协调者独占；本组件依赖 `defaultValue` 兜底。
- **阻塞：无。**
