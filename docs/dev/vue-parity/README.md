# Vue ↔ React 视觉与功能对等修复（2026-09-26）

> **已归档（2026-10-01）**：Vue / React 迁移期文档（Vue 已退役，React 为唯一生产路径）。继任：docs/dev/project-status.md。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

> 触发：用户反馈「现在的 Vue UI 和 React 还是不一样、很多功能用不了、样式和布局没有同步」。
> 验收参照：线上 React 站 <https://caoronglin.github.io/soymutdb-next/>（2026-08-08 构建，截图 `.validation/vue-parity/react-live-home.png`）
> ＋ React 源码基线 门户 `d3904c2105f34e5d74f3ae3a163d6b25f075bf64` / 管理端 `2004c25c61d850f15335dcc8329d0649930c35a4`
> （一律用 `git show <sha>:<path>` 只读读取，未切分支）。
> 功能缺口全量审计：`docs/dev/vue-parity/functional-gap-audit.md`（P0×4 / P1×7 / P2×5）。

## 1. 根因（实测，非推测）

| # | 现象 | 根因 | 证据 |
| --- | --- | --- | --- |
| R1 | 首页/列表页全部 500，功能像"用不了" | dev `/api` 代理指向未启动的 `localhost:8010`；端口 8000 是另一个项目（primer-web） | `apps/web/vite.config.ts:80,109-111`；`curl 8010` = 000 |
| R2 | API 挂了页面长时间停在「加载中…」而不是错误态 | Vue 用 `new QueryClient()`（TanStack 默认：staleTime 0 / refetchOnWindowFocus / retry 3）；React 基线是 5min/30min/仅重试 5xx 两次 | `d3904c21:apps/web/src/lib/query-client.ts` |
| R3 | 首页失去深绿流体渐变 Hero、工具卡图标、新闻+轮播分层 | React 用 AntD 组件 + WebGL2 `FluidGradient`；Vue 首页改成裸 div + Tailwind 工具类 | `d3904c21:apps/web/src/components/{home/antd-home.tsx,fluids/fluid-gradient.tsx}` |
| R4 | 11 条路由**完全没有页眉/导航/页脚**，内容挤在 `max-w-3xl p-8` | React 把 shell 放在根路由 `__root.tsx`；Vue 改成每个 view 自己包 `PortalLayout`，14 个视图漏包 | `.validation/vue-parity/route-shell-audit.json` |
| R5 | `/help` 标题显示原始 key `help.title`；管理端 shell 显示 `admin.shell.*` | 字典缺 20+ 个被引用的 key（React 侧靠 `defaultValue` 兜底） | key 集合比对脚本 |
| R6 | 所有 antd 主按钮渲染成近黑色 | `packages/ui-vue` 把 `colorPrimary` 设为 `oklch(...)`，而 AntD 用 tinycolor 派生色阶、无法解析 oklch（React 基线注释明确记录过这个坑） | `d3904c21:apps/web/src/lib/antd-theme.ts` |
| R7 | 任一 view 抛错整站白屏 | 无 `onErrorCaptured` 边界；且 router 全量静态 import，一个文件编译失败即全站白屏 | 实测 `SearchView.vue` 编译失败 → `#app` 为空 |
| R8 | `/analytics` 整页崩溃（白屏，加边界后显示错误态） | `trendAreaChart` 把 ISO 日期字符串绑到 `scaleLinear`；React 基线用的是 ECharts **category** 轴 | `packages/charts/src/definitions.ts:78`；实测 `TypeError: A quantitative scale factory requires numeric values` |

## 2. 本轮修复（按文件）

**门户视觉（R3）**
- 新增 `apps/web/src/components/visuals/FluidGradient.vue`：WebGL2 fragment shader（fbm + domain warping、5 色、grain/vignette）忠实移植；WebGL2 不可用回退 `linear-gradient`；`prefers-reduced-motion` 只渲染一帧；卸载时释放 RAF/GL/observer。
- 新增 `visuals/fluid-palettes.ts`、`visuals/IconGlyph.vue`（内联 SVG，零新依赖）。
- 重写 `apps/web/src/views/HomeView.vue`：流体渐变 Hero（eyebrow/大标题/白色药丸搜索框/CTA）→ 数据库入口 → 最新动态‖流体轮播 → 搜索工具 5 卡 → 资源导览 3 卡 → 页脚。`data-testid` 与 i18n key 全部保留。
- `PortalHeader.vue`/`PortalFooter.vue` 对齐 React 页眉页脚（品牌、分组导航、搜索、语言、主题、GitHub、页脚链接/版本）。

**布局外壳（R4）**
- 11 个缺失 shell 的视图补 `PortalLayout`，并删除重复的 `ConfigProvider`；`ConfigurableTable` 去掉纯透传的 provider 包裹。实测 `missingShell` 由 11 条降到 0（`/login`、404 为有意豁免）。

**查询策略（R2）**
- 新增 `apps/web/src/lib/query-client.ts` + 回归测试，恢复 React 的 staleTime/gcTime/不重试 4xx。

**设计令牌（R6）**
- `packages/ui-vue/src/index.ts`：`colorPrimary` 改用 hex 种子 `#2f6f4f`（tinycolor 可解析），用户可见高频 token 用 components 级 oklch 覆盖（Button/Tag/Menu），并补 `fontFamily`/heading 字号映射；`facade.test.ts` 增加「禁止 oklch 作种子」回归断言。

**i18n（R5）**
- 补齐 web + admin 引用的全部缺失 key（`help.*`、`seedRequest.purpose`、`admin.shell.*`、`admin.dashboard.*`、`admin.publications.*`、`commandPalette.*`、`home.*` 等），zh/en 各 **1650** key、完全对等；`scripts/check_visible_i18n.py` 补充「键盘加速键」「标识符字段名」白名单并保持自检通过。

**健壮性与会话（R7 + 审计 P0/P1）**
- 新增 `components/AppErrorBoundary.vue`（`onErrorCaptured` + 重试重挂子树）并包住 `RouterView`；新增回归测试。
- `main.ts` 补 `clearLegacyTokens()`、`restoreSession()`、`onAuthLogout()`（子路径安全的登录回跳）。
- 新增 `components/PortalCommandPalette.vue`（⌘K/Ctrl+K 命令面板，11 tests）并挂载到 `PortalLayout`；页眉原来的 ⌘K 聚焦处理器移除，避免与面板争抢快捷键。
- 新增 `lib/theme.ts`：主题是文档级状态，页眉切换、`PortalLayout` 的 AntD `ConfigProvider` 同源；实测 `data-theme`/`.dark`/body 背景与 localStorage 持久化全部生效。

**图表崩溃（R8）**
- `packages/charts/src/definitions.ts`：`trendAreaChart` 的 x 轴由 `scaleLinear` 改为 band scale（并显式给出 domain，band scale 无法从连续 mark 推断），对齐 React 的 ECharts `xAxis.type = "category"`；补「日期轴不得绑定数值 scale」回归断言。
- `packages/charts/src/ChartFigure.vue`：给 `<Chart>` 加 `onErrorCaptured`，图表运行时抛错时降级为 `chart-unavailable` 提示 + **精确数值表**（该表本就是这个组件的可访问替代），不再让整条路由崩掉；补回归测试（4 tests）。

**管理端（审计：管理端同样退化）**
- `apps/admin`：新增分组侧栏、页头、指标卡、三类内联 SVG 图表、⌘K 面板、通知铃铛、主题切换、分页与状态组件；20 个视图重写；44 条路由全部可达（新增 `nav-reachability.test.ts`）。未恢复的能力以 `LegacyUnavailableView` 显式标记，不造假数据。

## 3. 验证证据

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 门户类型 | `pnpm --filter @soymutdb/web typecheck` | **exit 0，零错误** |
| 门户 lint | `pnpm --filter @soymutdb/web lint` | **exit 0** |
| 门户测试 | `pnpm --filter @soymutdb/web test` | **37 files / 165 tests passed** |
| 管理端类型 | `pnpm --filter @soymutdb/admin typecheck` | **exit 0** |
| 管理端测试 | `pnpm --filter @soymutdb/admin test` | **22 files / 98 tests passed** |
| 管理端 lint | `pnpm --filter @soymutdb/admin lint` | **exit 0** |
| 可见文案 | `python3 scripts/check_visible_i18n.py` | **OK（5 tracked strings / 1 file）** |
| 构建 | `pnpm --filter @soymutdb/{web,admin} build` | **exit 0** |
| 图表包 | `pnpm --filter @soymutdb/charts test` | **4 tests passed** |
| 路由外壳 | `.validation/vue-parity/audit-routes.mjs` | 33 条路由 **missingShell 0**（仅 `/login` 与 404 无 chrome；`/blast` 未登录时正确重定向到 `/login`） |
| 首页浏览器 | Playwright @ 127.0.0.1:5173 | `canvas=4`（与线上 React 一致）、`h1=探索多物种突变的未知疆域`、31 个链接（线上 React 同为 31）、`scrollWidth==clientWidth==1440`、无 pageerror |
| `/analytics` | Playwright | h1=`可视化分析`、shell 在位、4 图空态 + 1 图降级为精确数值表、0 pageerror（修复前整页崩溃） |
| 主题 | Playwright 点击 `[data-testid=theme-toggle]` | `data-theme=dark`、`.dark`、body 背景切到暗色 token、localStorage 持久化 |
| 命令面板 | Playwright `Control+k` | `role=dialog` 打开、6 条快捷项为中文、Escape 关闭 |

截图：`.validation/vue-parity/{react-live-home,before-home,progress-home,dark-home,palette-open,after-final-*}.png`。
原始日志：`.validation/vue-parity/{final-gates.log,final-tests.log,api.log,route-shell-audit.json}`。

## 4. 本地把数据跑起来（否则会看到错误态）

```bash
# PostgreSQL 16 已在 127.0.0.1:55432（数据目录 .validation/postgres16，trust 认证）
cd apps/api && SOYMUTDB_ENV=dev \
  SOYMUTDB_DATABASE_URL="postgresql+asyncpg://soymutdb:soymutdb_dev_password@127.0.0.1:55432/soymutdb_performance" \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
# 门户 dev server 在 5173，/api 代理到 8010
```

- `soymutdb_performance` 已迁到 alembic head `0042`，含 25 万基因；需存在 published release 且 `active_release.release_id` / `assemblies.release_id` 指向它，`list_genes` 的 join 才成立。
- ClickHouse 未起时 `/api/v1/variants` 返回 503 属**设计上的 fail-closed**，不是 500。
- 端口 `8000` 是另一个项目，不要对着它测本仓库 API。

## 5. 仍未完成（来自审计，按优先级）

**已完成（OPT4，第四轮）**：CMS 内容能力落地 —— 接口加法式 `only_overrides`、客户端 `getSiteContent(variant,{onlyOverrides})`、门户 `useSiteContent()` + HomeView(`hero.*`/`tool.*`) + PortalHeader(`nav.*`) 共 35 键接线；**GAP-03 收口**（PageDefinition `resource_cards` 移植，真实种子数据端到端 + 404 回退内置带）；并修掉一处 P0 匿名跳转回归（`/auth/me` 探针未做会话门控 → 匿名被硬跳 `/login`）。详见 `docs/dev/opt4/OPT4-REPORT.md`。

**已完成（OPT3，第三轮）**：门户通知中心（`PortalNotificationBell.vue`，浏览器 21/21 断言）、路由动效运行时（`lib/motion.ts` + `RevealOnMount.vue`）—— 见 `docs/dev/opt3/OPT3-REPORT.md`。

**已完成（前两轮）**：首页/页眉/页脚视觉恢复（WebGL 流体 Hero）、33 条路由外壳覆盖、i18n 收口、AntD 主色、暗色主题、⌘K 命令面板、错误边界、会话恢复、service worker 注册（含变体命名空间）、`/analyses` 研究者门禁、全局搜索框与诱变剂筛选框的 `v-model` 空绑定、客户端契约重同步。

**已完成（OPT5，第五轮）内容键接线收口**：React 真正消费过的注册 `content.*` 键已全部接线（含 help FAQ 的 `faq{i}`↔`q{i}` 下标映射、`hero.image`），并补齐 4 个缺失 i18n 键。覆盖率可复跑（`.validation/opt5/content-coverage.py`）：**131 注册 / 105 已接 / 25 个 React 从未引用（非缺口） / 1 个已解释差异**。本文件早前写的"剩余 96 个键"是错误数字（提取正则漏了 47 个 camelCase 键），已在 `OPT5-REPORT.md` §2.1 记录。

**最后一条 frontend parity 差异（已于 goal round 4 闭合）**：Blast 命中表曾缺 React 的「基因跳转」与「JBrowse」两列。现已加法式补齐——`blast.hitGeneId` 接到新增「基因ID」列（`compactGeneId(hit.subject_id,18)` → `/search/genes?q=…&run=true`），并新增「JBrowse 2」列（`subject_id:start..end` + 由 job 数据库反查的 assembly）；Vue 原有的 score / alignment 列保留且标注正确。浏览器实测通过，内容覆盖率 **ACTION=0**。仍缺 React 的 assembly 列与输入序列 ID 列（不涉及 content 键，属可选增强）。详见 `OPT5-REPORT.md` §4/§8。

> 事实更正：GAP-03 不是"首页整页由 PageDefinition 驱动"。核对 React 源码后确认，首页只从定义里取 **`resource_cards` 一个节点**（`routes/index.tsx` 的 `findResourceCards(definition.root)`），其余区块都是静态代码；`RenderNode` 对其余 20 余种节点在首页场景从未被使用。因此无需"恢复整页渲染器"的产品决策。

**P2（仍未认领）**：`nav.mySeeds`/`nav.myBlast` 为死键（React 基线同样未接线，非缺口）。
**管理端后端缺口**（前端无法闭合，已在页面显式降级）：`/releases/current`、`/admin/dashboard-series.storage_growth` 数据源、审计聚合/导出、导入上传与校验报告、媒体上传/筛选、插件运行时。
**验证缺口**：`/news/:slug` 正文、`/genes/:id` 与 `/mutants/:id` 的**成功态**真机渲染（当前 fixture 数据下是 404/error 态，仅单测覆盖）；BigWig/BigBed 离线 fixture；live 部署态（CSS/CSP/SW/子路径）。

### 5.0 有意**不恢复**的一条：`/antd-pilot`

React 的 `/antd-pilot` 是 **AntD 5 迁移试点页**（文件头自述「试点页 — G1 截图基线对象」，4 个 demo 场景供截图对比），**不是产品功能**：
- 在 React 基线里**没有任何导航/页眉入口引用它**（`git grep -n "antd-pilot" <sha> -- apps/web/src/components apps/web/src/routes/__root.tsx` = 0 命中），用户不可达；
- 基线 `e2e/` 下也没有对应 spec。

AntD 迁移既已完成、Vue 版又不再使用 AntD 作为页面骨架（改走 Tailwind + 门面原语），恢复这个页面没有产品价值。因此门户路由数 React 36 / Vue 35 的差额**按有意退役处理**，不计入对等缺口（对齐 ADR-0009 对管理端 page-builder/widgets 的同类处理）。

### 5.1 经复核**撤回**的两条（避免后续做无用功）

| 原判 | 复核结论 | 证据 |
| --- | --- | --- |
| `dist/` 直接发布缺 `404.html`，深链会 404 | **假警报，撤回**。两条目标托管路径都已覆盖：nginx 用 `try_files $uri $uri/ /index.html`（`infra/docker/web-nginx.conf:84`、`admin-nginx.conf:72`）；Cloudflare Pages 走**内置 SPA 兜底**，而该兜底**恰好要求顶层没有 `404.html`**——`_redirects` 里删掉 `/* /index.html 200` 是 oracle R7 的有意决定（`apps/web/public/_redirects` 注释），`build-pages-artifact.sh:85` 只给 pages 制品补 404.html | `infra/docker/*-nginx.conf`、`apps/web/public/_redirects` |
| `/search/suggest` 无消费者（审计 GAP-10） | **不是迁移缺口，撤回**。React 基线同样零消费者：`git grep -in suggest d3904c21 -- apps/web/src` = 0 命中 | `git grep -in suggest` 基线 |
