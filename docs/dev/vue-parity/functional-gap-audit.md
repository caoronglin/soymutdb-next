# Vue 功能缺口审计（2026-09-26）

> **已归档（2026-10-01）**：Vue / React 迁移期文档（Vue 已退役，React 为唯一生产路径）。继任：docs/dev/project-status.md。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

> 快照：`HEAD = 053666680ad0a456c8dfff8c2b0fab54a42a0de8`（main），**工作树有未提交改动/未跟踪文件**，
> 审计时刻 `2026-09-26 23:07 CST`。工作树中另有代理在并发修改 `apps/web/src/views/HomeView.vue`、
> `apps/web/src/components/visuals/*`、`apps/web/src/views/VariantsView.vue`、`apps/admin/src/**`（见 `git status`）。
> 文中凡标注「工作树」的结论都只对 23:07 这一刻成立，重跑前请先看 `git status`。
>
> 基线（只读，未 checkout）：门户 `d3904c2105f34e5d74f3ae3a163d6b25f075bf64`、
> 管理端 `2004c25c61d850f15335dcc8329d0649930c35a4`；已构建 React 产物 `.deploy/react-site/`。
> 唯一写入文件：本报告。

## 0. 结论摘要（P0 4 条 / P1 7 条 / P2 5 条）

**P0（用户直接感知、且全部是前端未接线；均不需要后端或契约改动）**

1. **GAP-01 明暗主题开关完全缺失**：React header 有 `toggleTheme`；Vue 无按钮、`createThemeConfig({dark:false})` 写死、`style.css` 的 `[data-theme="dark"]` 无人写入。
2. **GAP-02 全局命令面板 / Cmd+K 缺失**：React `__root` 挂载 `CommandPalette`（Cmd+K/Ctrl+K + 快捷跳转）；Vue 无组件、无快捷键、header 无可点击入口。
3. **GAP-03 首页 CMS（PageDefinition）驱动未接线**：`packages/api-client/src/page-definitions.ts` 在 `apps/web`/`apps/admin` 零消费者；`HomeView.vue` 全静态；API `/api/v1/page-definitions/*` 仍在。
4. **GAP-04 后台可编辑站点内容（`getSiteContent`）零消费者**：React 有 `site-content.tsx` 并在 header + 12 个路由消费；Vue 完全没有，后端 `/site/content` 依然存在。

**P1**

5. GAP-05 门户未做会话恢复、未注册登出重定向（`restoreSession`/`onAuthLogout` 无调用）。
6. GAP-06 `dist/sw.js` 已构建但**没有任何前端注册代码**（service worker 永不激活）。
7. GAP-07 通知中心：API `/notifications*` 齐全，Vue 无组件也无 api-client 封装。
8. GAP-08 `/analyses` 缺研究者门禁（React `ResearcherGate` 包住整页）。
9. GAP-09 无全局/路由错误边界（`onErrorCaptured` 0 处），渲染异常白屏。
10. GAP-10 搜索框无联想（`/search/suggest` 无消费者）。
11. GAP-11 `apps/web/dist` 无 `404.html` 且 `_redirects` 删掉了 SPA catch-all（发布脚本会补 404，但直接发 dist 会深链 404）。

**P2**

12. GAP-12 `/antd-pilot` 路由缺失（唯一缺失的门户路由）。
13. GAP-13 `search-worker-client`（相对 `.deploy/react-site` 产物；相对给的源码基线本就已删除）。
14. GAP-14 `nav.mySeeds` / `nav.myBlast` 是死文案键（基线同样未接线）。
15. GAP-15 减少动效控制 + `startViewTransition` 运行时缺失（CSS 在，JS 无）。
16. GAP-16 `pnpm --filter @soymutdb/web typecheck` 当前红（2 文件 6 错）。

> 需要区分：**管理端**（`apps/admin`）在 23:07 的工作树里已经补上了主题切换（`apps/admin/src/lib/theme.ts`）、
> 命令面板（`apps/admin/src/components/AdminCommandPalette.vue`）和通知铃铛（`AdminNotificationBell.vue`），
> 但**门户 `apps/web` 三者都还没有**。管理端 page-builder/widgets 的「未恢复」是 ADR-0009 的有意决定，不算坏。

---

## 1. 运行时连通性实测

### 1.1 原始输出

审计开始时（父代理把 API 起起来之前）：

```
$ curl -s -o /dev/null -w '%{http_code}\n' --max-time 4 http://127.0.0.1:8010/api/v1/health
000
$ curl -s -o /dev/null -w '%{http_code}\n' --max-time 4 http://127.0.0.1:8000/
200
$ curl -s --max-time 4 http://127.0.0.1:8000/ | head -c 200
<!doctype html>... <meta name="description" content="D509引物设计平台 — a profession...
$ curl -s -o /dev/null -w '%{http_code}\n' --max-time 4 http://127.0.0.1:5173/
200
$ curl -s -o /dev/null -w '%{http_code}\n' --max-time 5 http://127.0.0.1:5173/api/v1/health
500
```

开始监听端口（`ss -ltn`）显示 `8000`(0.0.0.0)、`5173/5174/5175`(0.0.0.0) 在听，**没有 8010**。
`5173/5174/5175` 的 `<title>` 分别是 `SoyMutDB` / `SoyMutDB admin` / `SoyMutDB Genome Browser`，
即本仓库的三个 dev server。

API 起来之后（父代理作业，uvicorn 127.0.0.1:8010）：

```
$ for p in /health /api/v1/health /api/v1/health/live /api/v1/health/ready \
           /api/v1/genes/assemblies /api/v1/news/featured "/api/v1/genes?page=1&page_size=1" /api/v1/variants; do
    printf '%-45s ' "$p"; curl -s -o /dev/null -w '%{http_code}\n' --max-time 6 "http://127.0.0.1:8010$p"; done
/health                                       200
/api/v1/health                                404
/api/v1/health/live                           200
/api/v1/health/ready                          503
/api/v1/genes/assemblies                      200
/api/v1/news/featured                         200
/api/v1/genes?page=1&page_size=1              200
/api/v1/variants                              503

$ for p in /api/v1/genes/assemblies /api/v1/news/featured; do
    printf '%-45s ' "$p"; curl -s -o /dev/null -w '%{http_code}\n' --max-time 6 "http://127.0.0.1:5173$p"; done
/api/v1/genes/assemblies                      200
/api/v1/news/featured                         200
```

### 1.2 判定

- **端口 8000 不是本仓库 API**，是另一个项目（HTML 自称 `D509引物设计平台`）。本仓库 dev API 端口是 **8010**
  （`Makefile:123`、`apps/web/vite.config.ts:80`、`.env.example` 的 `VITE_API_BASE_URL=http://localhost:8010/api/v1`）。
- `/api/v1/health` **本身就是 404**（任务里的探测路径），真实存活探针是 `GET /health`（`apps/api/app/main.py:331`）
  与 `GET /api/v1/health/live`、`/api/v1/health/ready`（`apps/api/app/api/v1/health.py:25,31`）。
  `ready` 返回 503 是设计语义（有必选依赖不可用），本机因 ClickHouse 未起。
- `/api/v1/variants` 503 = ClickHouse 未起（预期降级，非 500）。
- 开发期 `5173` 的 `/api` 代理指向 `http://localhost:8010`（`apps/web/vite.config.ts:109-111`）。
  API 未起时代理返回 **500**（不是超时），首页/列表页因此进入错误态。
- **「API 未启动会不会永远 loading？」——不会。** `HomeView.vue:83-84` 显式暴露 `isAssembliesPending/isError`，
  `:212-218` / `:252-261` 分别渲染 loading / error + Retry；`createQueryClient()` 的 `retry` 只对 5xx/网络错误重试 2 次
  （`apps/web/src/lib/query-client.test.ts:33-40`）后进入 `isError`，配合 5s/30s 超时（`packages/api-client/src/client.ts:47-51`）
  大约数秒内落到错误态。真正「看起来永远 loading」的情况是 ClickHouse 端点 503 被无限轮询叠加时，但同样会终结。

### 1.3 仓库正常的本地起 API 方式（可复制）

```bash
export PNPM_HOME=/mnt/data02/T25ronglin/code/web/.validation/pnpm/home
export XDG_STATE_HOME=/mnt/data02/T25ronglin/code/web/.validation/pnpm/state
export XDG_CACHE_HOME=/mnt/data02/T25ronglin/code/web/.validation/pnpm/cache
export XDG_CONFIG_HOME=/mnt/data02/T25ronglin/code/web/.validation/pnpm/config

# 方式 A（文档口径，最省事）：
make dev            # .env + 安装依赖           (Makefile:52-64)
make db-up          # postgres/clickhouse/redis/minio  (Makefile:77-79)
make migrate        # alembic upgrade head      (Makefile:86-88)
make init-clickhouse# 灌 ClickHouse schema       (Makefile:90-92)
make run-api        # uvicorn app.main:app --reload --host 0.0.0.0 --port 8010  (Makefile:122-123)

# 方式 B（无 Docker，本机隔离 PG 已在 127.0.0.1:55432；父代理本次用的就是这条）：
cd apps/api && SOYMUTDB_ENV=dev \
  SOYMUTDB_DATABASE_URL="postgresql+asyncpg://soymutdb:soymutdb_dev_password@127.0.0.1:55432/soymutdb_validation" \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
# 前置：cd apps/api && alembic upgrade head；PG16 数据目录 .validation/postgres16
```

同时起门户：`pnpm --filter @soymutdb/web dev`（5173，`apps/web/package.json:8`）。

---

## 2. 路由对等矩阵

枚举命令：

```bash
git ls-tree -r --name-only d3904c2105f34e5d74f3ae3a163d6b25f075bf64 -- apps/web/src/routeTree.gen.ts   # React
grep -oE 'path: "[^"]+"' apps/web/src/router/routes.ts                                                  # Vue
```

门户路由总数：React 36（`routeTree.gen.ts` 去重）vs Vue 35（`apps/web/src/router/routes.ts`，`grep -c` = 35）。
**差异只有 1 条。**

| React 路由 | Vue 路由 | 状态 | 证据 |
| --- | --- | --- | --- |
| `/` `/about` `/analytics` `/blast` `/browser` `/compare` `/downloads` `/guide` `/help` `/login` `/publications` `/search` `/seed-request` `/sra` | 同名 | implemented | `apps/web/src/router/routes.ts` 逐条存在；组件绑定 `apps/web/src/router/index.ts:46-81,88-102` |
| `/genes` `/genes/$geneId` `/mutants` `/variants` `/news` | 同名 | implemented | 同上（列表页 + 详情页均为 Vue view） |
| `/mutants/$id` | `/mutants/:publicId` | renamed(param) | URL 形状相同，仅占位符改名；`routes.ts` `mutant` 项 |
| `/news/$slug` | `/news/:slug` | implemented | 占位符名一致 |
| `/search/genes` `/search/location` `/search/gbrowse` `/search/primer` `/search/blast` `/search/tools` `/tools` `/tools/seqfetch` `/tools/exppattern` `/tools/enrichment` `/analyses` `/analyses/fastp` `/analyses/scanpy` `/analyses/$jobId` | 同名 | implemented | 同上 |
| `/antd-pilot` | **无** | **missing** | React `apps/web/src/routes/_antd-pilot.tsx`；Vue `routes.ts` 无对应项，`/antd-pilot` 落到 `/:pathMatch(.*)*` → `NotFoundView`（`router/index.ts:103-107`） |

动态路由无独立 HTML（`meta.prerender` 不含 `:`），由 SPA 承担；静态路由 81 个 `index.html`（见 §8/§4.3），
**无 redirect 类型**（React 也没有）。Vue 另有「cond-route」：`/browser`、`/search/gbrowse` 在 core-only 部署下
替换为 `FeatureUnavailableView`（`apps/web/src/router/feature-gating.ts:12-16`，`router/index.ts:95-97`），属于可用性降级而非缺失。

管理端（`apps/admin`）路由对等（React `apps/admin/src/routes/**` vs `apps/admin/src/router/index.ts:32-106`）：

| React | Vue | 状态 |
| --- | --- | --- |
| `/` `/login` `/media` `/publications` `/audit` `/features` `/analytics-settings` `/imports` `/imports/new` `/imports/$taskId` | 同名 | implemented |
| `/news` `/news/new` `/news/trash` `/news/$id` | `/news` + query redirect | redirect（`index.ts:78-80`） |
| `/content` `/content/...` | `/content` `/content/pages` `/content/legacy` | implemented + redirect（`index.ts:39-46`） |
| `/table-views` | `/table-templates` | renamed |
| `/settings/{site,security,appearance,integrations,localization,advanced}` | `/settings?section=...` redirect + `/settings/brand` | redirect |
| `/page-builder` `/page-builder/$pageId` `/widgets` `/widgets/$name` `/widget-preview` `/widget-health` `/layout` `/resource-catalog` | `LegacyUnavailableView` | unavailable（ADR-0009 有意退役，见 `index.ts:96-104` 注释） |
| — | `/releases` `/instances` | Vue 新增 |

---

## 3. 功能缺口明细（按优先级）

### GAP-01 [P0] 明暗主题开关完全缺失

- **现象**：全站只有浅色；`style.css` 里写好的暗色 token 永远不生效。
- **根因（前端未接线）**：
  - `apps/web/src/components/PortalHeader.vue:238-265` 右侧簇只有语言切换 + 汉堡，无主题按钮。
  - `apps/web/src/components/PortalLayout.vue:16` `createThemeConfig({ dark: false })` 硬编码；
    其它 5 个视图同样写死（`DownloadsView.vue:57`、`EnrichmentView.vue:210`、`ExpPatternView.vue:153`、`FeatureUnavailableView.vue:17`、`GeneView.vue:107`、`ConfigurableTable.vue:120`）。
  - `apps/web/src/style.css:58` `[data-theme="dark"], .dark {` 存在，但全仓库没有 `documentElement.setAttribute("data-theme", ...)`（grep 唯一命中 `main.ts:31` 的 `dataset.appReady`）。
  - 无 `apps/web/src/lib/theme.ts`（`ls apps/web/src/lib | grep theme` 为空）。
  - React 对照：`site-header.tsx:125,362-364`（`toggleTheme` 按钮）+ `lib/theme-provider.tsx:20-55`（localStorage + `prefers-color-scheme` + `setAttribute("data-theme")`）。
- **影响**：所有页面；用户投诉「Vue 很多用不了」里最直观的一条。
- **最小修复面**：新增 `apps/web/src/lib/theme.ts`（照抄 `apps/admin/src/lib/theme.ts` 的工作树实现，补 localStorage + matchMedia），
  `PortalLayout.vue:16` 与各视图改为响应式 `createThemeConfig({ dark: theme.value === 'dark' })`，`PortalHeader.vue` 加按钮。纯前端。
- **验收**：点按钮后 `<html data-theme="dark">`、刷新保持、`style.css` 暗色分支命中；新增 `PortalHeader.test.ts` 断言。

### GAP-02 [P0] 全局命令面板 / Cmd+K 缺失

- **现象**：header 的搜索是个纯表单（回车跳 `/search`）；没有 Cmd+K 弹层、没有快捷跳转列表。
- **根因（前端未接线）**：`apps/web/src/components/` 下无 `CommandPalette*`；`PortalHeader.vue` 无 `openPalette`；
  全仓库无 `Cmd+K`/`keydown` 全局监听（grep `command-palette|commandPalette` 在 `apps/web/src` 为 0 命中，
  只命中 `style.css:746` 的 kbd 样式）。
  React 对照：`routes/__root.tsx:11,65` 挂载 `CommandPalette`，组件在 `components/command-palette.tsx:70-85` 注册 Cmd/Ctrl+K。
- **影响**：键盘流用户；`AdminCommandPalette.vue` 的工作树实现可直接移植。
- **最小修复面**：新增 `apps/web/src/components/CommandPalette.vue`（照抄工作树 `apps/admin/src/components/AdminCommandPalette.vue` 去掉 gene 搜索），
  在 `App.vue` 或 `PortalLayout.vue` 挂载。纯前端。
- **验收**：Cmd+K 打开、↑↓ 选择、Enter 跳转、Esc 关闭。

### GAP-03 [P0] 首页 CMS（PageDefinition）驱动未接线

- **现象**：首页 hero / 资源卡片 / 任务入口全部是 `HomeView.vue` 里的硬编码 `const`；后台发布的内容不生效。
- **根因（前端未接线 + 管理端能力退役）**：
  - `packages/api-client/src/page-definitions.ts` 存在且 `index.ts:66` 导出，但 `grep -rn "page-definitions|PageDefinition" apps` 只命中 `packages/api-client` 自身与 `apps/web/scripts/finalize-csp.ts`（字符串）。
  - `HomeView.vue:32-72` 是 `DATABASE_ENTRIES/TASK_ENTRIES/RESOURCE_ENTRIES/HERO_SLIDES` 常量；无 `usePageDefinition`。
  - `apps/web/src/page-builder/` 目录在 Vue 里不存在（整目录缺失）。
  - API 仍在：`apps/api/app/api/v1/router.py:94` 挂载 `page_definitions.router`（前缀 `/page-definitions`，见 `page_definitions.py:33`）。
  - React 对照：`routes/index.tsx`（`usePageDefinition("/")` + `findResourceCards` + `resource_cards` renderer）、`page-builder/renderer.tsx`、`routes/__tests__/home-page-definition-binding.test.tsx`。
  - 管理端也断了：`apps/admin/src/router/index.ts:103-104` 把 `/page-builder*` 指向 `LegacyUnavailableView`。
- **影响**：编辑者改了首页但看不到；React 的「CMS 驱动首页」能力整体丢失。
- **最小修复面**：门户新增 `usePageDefinition`（直接复用 `packages/api-client/src/page-definitions.ts`）+ 一个最小 `resource_cards` 渲染器接进 `HomeView.vue`；
  管理端是否恢复 page-builder 决定「能不能编辑」，但「能显示已发布定义」只需门户改动。**不需要后端改动**。
- **验收**：`GET /api/v1/page-definitions/` 返回定义时首页渲染发布卡片；无定义时落回当前静态常量。

### GAP-04 [P0] 站点可编辑内容（`getSiteContent`）零消费者

- **现象**：后台改的 hero 文案、导航标签、各页标题一律不生效。
- **根因（前端未接线）**：`packages/api-client/src/site.ts:109` 有 `getSiteContent()`，但 `grep -rn "getSiteContent" apps` 无命中；
  Vue 没有 `site-content` provider。React 对照：`lib/site-content.tsx`（provider + 内置默认表），消费方
  `site-header.tsx`、`components/home/antd-home.tsx`、`routes/{blast,downloads,guide,help}.tsx`、
  `routes/{genes/index,search/genes,search/location,variants/index}.tsx`。
- **影响**：与 GAP-03 叠加，等于首页/导航的 CMS 面全塌。
- **最小修复面**：新增 `apps/web/src/lib/site-content.ts`（`useQuery` 包 `getSiteContent(site.siteVariant)` + `get(key, fallback)`），
  `PortalHeader.vue` 的 `labelKey` 与 `HomeView.vue` 的 hero 改走 `get()`。纯前端。
- **验收**：后台改 `hero.title` 后前台刷新即变；API 失败时回退 `t()` 文案。

### GAP-05 [P1] 门户未做会话恢复 / 登出重定向

- **现象**：刷新后内存 token 丢失；会话中途失效不会跳登录页。
- **根因（前端未接线）**：`apps/web/src/main.ts:1-32` 没有 `restoreSession()` / `onAuthLogout()`；
  全仓库引用者只有 `apps/admin/src/lib/auth.ts:13,69`（管理端有）。
  React 对照：`apps/web/src/main.tsx:41-42,62,66`（`void restoreSession()` + 401 后 `window.location = /login`）。
  另 `clearLegacyTokens()` 门户也没调（React `main.tsx` 有）。
- **缓解事实（重要，避免误判）**：`packages/api-client/src/search.ts:2` 用的是 `http`，而 `http.get` 走 `authRequest`
  （`auth.ts:241-249,175-207`），**401 会先 `refreshAccessToken()` 再用 HttpOnly cookie 重放**。
  因此内网站双身份搜索在刷新后第一次请求会 401→自动 refresh→成功，并非不可用（见 GAP-13 的 `/search/internal` 授权）。
- **影响**：首屏多一次 refresh 往返；refresh 失败时门户不跳 `/login`（用户停在原页）；遗留 localStorage token 不清。
- **最小修复面**：`apps/web/src/main.ts` 加 3 行（`clearLegacyTokens()` / `void restoreSession()` / `onAuthLogout(...)`）。纯前端。
- **验收**：登录→刷新→`/search/internal` 不出现 401 重放；手动删 cookie 后触发登出跳 `/login`。

### GAP-06 [P1] service worker 已构建但从不注册

- **现象**：预缓存/离线能力丢失。
- **根因（前端未接线）**：`apps/web/dist/sw.js` 存在（7106 B，构建产物），`public/sw.js` + `scripts/gen-sw.js` 都在，
  但 `grep -rn "navigator.serviceWorker|serviceWorker.register" apps packages`（排除 dist）**0 命中**。
  React 对照：`apps/web/src/main.tsx:230-240`（`import.meta.env.PROD && VITE_SW_ENABLED !== "false"` 时注册）。
- **影响**：重复访问无预缓存；离线可用性回退。
- **最小修复面**：`apps/web/src/main.ts` 追加 React 那段 `load` 回调注册。纯前端。
- **验收**：`VITE_SW_ENABLED` 未禁用时 Application→Service Workers 有 active registration。

### GAP-07 [P1] 通知中心无客户端与 UI

- **现象**：没有铃铛、没有未读角标、没有通知列表。
- **根因（前端未接线）**：API 齐全（`apps/api/app/api/v1/notifications.py:33,53,63`，`router.py:92` 已挂载），
  但 `packages/api-client` 无 notifications 封装（grep 0 命中），`apps/web/src` 无铃铛组件。
  React 对照要注意：**基线里 `components/notifications/notification-bell.tsx` 本身也是孤儿**——
  `git grep "NotificationBell"` 在基线只有它自己，`routes/__root.tsx` 并未挂载；`use-current-user.ts` 也只被它和 `researcher-gate.tsx` 引用。
  所以这是「基线组件存在但从未挂载」的功能，Vue 连组件都没有。
- **影响**：BLAST/分析任务完成的后台通知不可见（worker 侧仍会写通知）。
- **最小修复面**：api-client 加 3 个函数（可照抄 React 组件的 `secureHttp` 调用），门户加铃铛组件并挂进 `PortalHeader.vue`。
  工作树的 `apps/admin/src/components/AdminNotificationBell.vue` 可作模板。纯前端。
- **验收**：有未读时角标显示，点开可读、可全部已读。

### GAP-08 [P1] `/analyses` 缺研究者门禁

- **现象**：匿名或 viewer 进入 `/analyses` 直接看到表单，提交时才失败。
- **根因（前端未接线）**：React `routes/analyses/index.tsx:17,144,207` 用 `<ResearcherGate>` 包住整页；
  Vue `apps/web/src/views/AnalysesView.vue` grep `researcher|Gate|auth` 无命中，且门户没有任何 `/auth/me` 查询
  （grep `current-user|auth/me|isResearcher` 只命中 `LoginView.vue:43` 的 cache 清理）。
- **影响**：权限反馈延迟到提交；与 DB-CORE「授权由 API 强制、UI 只是提示」一致，但可用性差。
- **最小修复面**：门户加 `useCurrentUser`（`/auth/me`，401 视作匿名）+ 轻量 Gate 组件包住 `AnalysesView` 与 `ScalarAnalyses*`。纯前端。
- **验收**：匿名访问显示「需 researcher」空态，不渲染表单。

### GAP-09 [P1] 无全局/路由错误边界

- **现象**：任一视图渲染抛错 → 整棵 Vue 树卸载白屏。
- **根因（前端未接线）**：`grep -rn "onErrorCaptured|ErrorBoundary" apps/web/src` 0 命中。
  React 对照：`routes/__root.tsx:42,55,66` 包 `ErrorBoundary`，另有 `components/error-boundary.tsx`。
- **影响**：偶发数据形状错误会整站白屏而不是局部降级。
- **最小修复面**：加 `apps/web/src/components/AppErrorBoundary.vue`（`onErrorCaptured`）包住 `RouterView`。纯前端。
- **验收**：注入一个抛错视图后 header/footer 仍在，出现重试入口。

### GAP-10 [P1] 搜索框无联想

- **现象**：输入无下拉建议。
- **根因（前端未接线）**：`packages/api-client/src/search.ts:132` `getSearchSuggestions`（`/search/suggest`）在门户 0 消费者。
  注：React 基线同样没消费（`git grep getSearchSuggestions` 只命中 api-client 自身），故是「两版都没有」而非回归；但 API 已就绪。
- **影响**：首页/header 搜索体验弱。
- **最小修复面**：header 搜索框加防抖 + `getSearchSuggestions` 下拉。纯前端。
- **验收**：输入 2 字符出现 ≥1 条建议，点击跳结果。

### GAP-11 [P1] `dist` 无 `404.html`，`_redirects` 删掉 SPA catch-all

- **现象**：把 `apps/web/dist` 直接挂到不做 SPA fallback 的静态主机（GitHub Pages 不读 `_redirects`）时，深链 404；
  React 产物要么有 `/* /index.html 200` catch-all，要么有 `404.html`。
- **根因（产物/部署配置差异）**：
  - `find apps/web/dist -name '404.html'` → 空；`.deploy/react-site/404.html` 存在。
  - `apps/web/dist/_redirects` 明文说明已删除 `/* /index.html 200`（注释："Cloudflare Pages applies redirects BEFORE static-file matching…"）。
  - 发布脚本会补：`scripts/build-pages-artifact.sh:85` `cp index.html 404.html`（只作用于 `pages-dist/`，不是 `apps/web/dist`）。
- **影响**：直接发 dist 的场景（本地静态预览、非 Pages 主机）深链 404；预渲染的 81 个静态 `index.html` 只覆盖非动态路由。
- **最小修复面**：构建收尾（`apps/web/scripts/`）把 `index.html` 复制为 `dist/404.html`；或在 `_redirects` 里对动态前缀做 fallback。
- **验收**：`curl -sI http://<host>/genes/AT1G01010` 在无 SSG 文件的路径上返回 200。

### GAP-12 [P2] `/antd-pilot` 路由缺失

- **根因**：Vue `routes.ts` 无该路由（React `routes/_antd-pilot.tsx`）。
- **影响**：截图基线/验收 spec 若仍指向 `/antd-pilot` 会 404；对用户无感。
- **最小修复面**：`routes.ts` + `index.ts` 加一个 view（或改为并到某个调试页）。

### GAP-13 [P2] `search-worker-client` 缺失（相对已部署 React 产物）

- **证据**：`.deploy/react-site/assets/search-worker-client-COsun0ly.js` 存在，`index-DjMMqkPA.js` 引用它 1 次；
  源文件 blob 在 `cab115493`（"feat: complete data publishing and search upgrade"）存在，
  **在任务给的基线 `d3904c2` 已不在树里**（`git ls-tree d3904c2 -- .../search-worker-client.ts` 空）。
- **根因**：`apps/web/src/workers/search.worker.ts` + `lib/search-worker-client.ts` 未迁移到 Vue；
  当前 `grep -rn search-worker apps packages` 0 命中。
- **影响**：大结果集的客户端过滤/排序回到主线程。
- **最小修复面**：移植两个文件并在 DataTable/Search 结果里按需 dynamic import。

### GAP-14 [P2] `nav.mySeeds` / `nav.myBlast` 是死键

- **证据**：`packages/i18n-core/src/locales/en/common.json:21-22` 有键；
  `git grep "nav\.my" d3904c2 -- apps packages` **0 命中**（当前同样 0）。React 的 `NAV_GROUPS` 与 Vue 的 `NAV_GROUPS` 都没引用。
- **判定**：「我的种子/我的 BLAST」两版都没有真正的入口，只有文案；且 api-client 无对应 aggregate 端点。
- **影响**：期望「我的 X」的用户找不到入口。
- **最小修复面**：确认后端是否有 per-user 聚合接口；有则在 `PortalHeader.vue` NAV_GROUPS 加入口，无则先标注不可用。

### GAP-15 [P2] 减少动效控制与 View Transition 运行时缺失

- **证据**：`apps/web/src/style.css:323-347` 定义了 `::view-transition-*`，但全仓库无 `document.startViewTransition`
  与无 motion policy 运行时；React 有 `lib/motion-policy.ts`、`lib/animation-context.tsx`、`components/animation-control.tsx`、
  `components/route-motion-runtime.tsx`、`lib/view-transitions.ts`。
- **影响**：页面切换无过渡；「动画强度」偏好不可调。
- **最小修复面**：移植 `motion-policy` + `route-motion-runtime`（Portal 内 `router.afterEach` 调 `startViewTransition`）。

### GAP-16 [P2] 前端 typecheck 当前红

- **复现**：`cd apps/web && pnpm typecheck`（`vue-tsc --noEmit`）→ 6 errors：
  `src/ablation/p1-04-variants-cursor-key.test.ts:32` TS6133 + `:58,59,70,71` TS2352（readonly tuple → `unknown[]`）；
  `src/views/GenesListView.vue:252` TS6133（`row` 未使用）。
- **影响**：`pnpm typecheck` 门禁失败；`pnpm test` 当前 35/35 通过（23:06:58 实测），但 `typecheck` 不过。
- **最小修复面**：两个文件的小改（去掉未用变量、`as unknown as unknown[]` 或改断言）。

---

## 4. 不属于前端缺口、但会表现为「功能用不了」的环境问题

1. **`localhost:8010` 原本没服务**（审计起始 `curl` = 000）。`vite.config.ts:109-111` 把 `/api` 代理到它，
   于是 5173 下 `/api/v1/health` = 500，首页 assemblies/news、所有列表页进入错误态。
   这是「功能用不了」的第一大环境根因，**不是 Vue 代码缺口**。
2. **端口 8000 是另一个项目**（primer-web，HTML `D509引物设计平台`），别对着 8000 测本仓库 API。
3. **ClickHouse 未起**：`/health/ready` 503、`/api/v1/variants` 503（设计上的 fail-closed，不是 500）。
   `make init-clickhouse`（`Makefile:90-92`）或 `make db-up` 才补得上。
4. **迁移漂移实例**：另一个库 `soymutdb_performance`（25 万基因）停在 alembic `0027`，缺 `releases.assembly_id` 列，
   直连它全量 500；`make migrate`（`Makefile:86-88`）后（0040→0042）才可用。文档指引见 `docs/dev/mamba-validation-environment.md:80-120`。
5. **工作树并发修改**：23:0x 有代理在写 `apps/web/src/views/HomeView.vue`、`components/visuals/*`、
   `VariantsView.vue/.test.ts`、`apps/admin/src/**`。期间观察到 `HomeView.test.ts` 因 `FluidGradient.vue` 的
   `withDefaults(defineProps(), { colors: () => [...DEFAULT_FLUID_COLORS] })` 报 SFC 编译错误（23:04），
   23:05 已修（改从 `./fluid-palettes` 导入）；`VariantsView.test.ts` 的 ui-vue mock 一度缺 `Button`（23:05）后补齐（23:06）。
   **结论会随工作树变动，报告以 23:07 为准。**
6. **`apps/web/dist` 是 22:04 的产物**，早于 23:05 的 HomeView 改动 → 直接拿 dist 验证会看到旧代码。

---

## 5. 建议的执行顺序（可直接当排期）

**第 1 批（P0，全部纯前端、可并行，半天量级）**

1. GAP-01 主题切换（先抽 `lib/theme.ts`，因为 GAP-02/03 的组件也要用它）。
2. GAP-02 命令面板（复用管理端工作树实现）。
3. GAP-03 首页 PageDefinition + GAP-04 `getSiteContent`（同一个 `query-options` 文件里加两个 factory）。

**第 2 批（P1，纯前端）**

4. GAP-05 main.ts 会话恢复/登出（3 行，风险最低，先做）。
5. GAP-09 错误边界 → GAP-06 SW 注册 → GAP-08 研究者门禁。
6. GAP-07 通知（需在 api-client 加 3 个薄封装，仍无后端改动）。
7. GAP-10 搜索联想；GAP-11 404.html（改构建脚本，注意别覆盖 `_redirects` 语义）。

**第 3 批（P2 / 门禁）**

8. GAP-16 typecheck 修绿（阻塞其它 PR）。
9. GAP-15 motion/view-transition → GAP-13 search worker → GAP-12 `/antd-pilot`。
10. GAP-14 先与后端确认 per-user aggregate 是否存在，再决定加入口还是标 unavailable。

**回归护栏建议**

- 每条 P0 补一个 view 级测试（主题 `data-theme`、Cmd+K 打开、page-definition 渲染、`getSiteContent` 覆盖）。
- 跑 `pnpm --filter @soymutdb/web test && pnpm --filter @soymutdb/web typecheck`；
  后端起来后跑 `e2e` 的内部站 spec（`e2e/playwright-internal.config.ts`）覆盖 GAP-05 的真实登录链路。

---

## 附：关键证据命令汇总

```bash
# 基线枚举（不切分支）
git ls-tree -r --name-only d3904c2105f34e5d74f3ae3a163d6b25f075bf64 -- apps/web/src | sort
git show d3904c2105f34e5d74f3ae3a163d6b25f075bf64:apps/web/src/components/site-header.tsx | grep -n 'toggleTheme\|nav.theme'
git show d3904c2105f34e5d74f3ae3a163d6b25f075bf64:apps/web/src/routes/__root.tsx | grep -n 'CommandPalette\|ErrorBoundary'
git show d3904c2105f34e5d74f3ae3a163d6b25f075bf64:apps/web/src/main.tsx | grep -n 'restoreSession\|onAuthLogout\|serviceWorker'

# 缺口断言
grep -rn 'page-definitions\|PageDefinition' apps --include=*.ts --include=*.vue
grep -rn 'getSiteContent' apps packages --include=*.ts --include=*.vue
grep -rn 'onErrorCaptured\|ErrorBoundary' apps/web/src
grep -rn 'navigator.serviceWorker' apps packages --include=*.ts --include=*.vue
grep -rn 'command-palette\|commandPalette' apps/web/src
grep -rn 'nav\.my' apps packages

# 对等/产物/门禁
grep -cE '^    path: "' apps/web/src/router/routes.ts
find apps/web/dist -name '404.html'; ls .deploy/react-site/404.html
cd apps/web && pnpm test && pnpm typecheck
```
