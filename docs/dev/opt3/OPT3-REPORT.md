# OPT3 第三轮：React 对等收口（2026-09-26/27）

- **方式**：协调者 + 2 个并行子代理（`nwafu/DeepSeek-V4.1-Flash`），协调者逐条独立复跑。
- **目标**：把审计里仍开的 React 对等缺口（通知中心、路由动效）补齐，并厘清最后两项（CMS 内容）的真实阻塞。
- **前提**：HEAD `053666680` + 三轮未提交改动；本轮新增改动同样**未提交**。

## 1. 本轮交付

| ID | 内容 | 状态 | 协调者复跑证据 |
| --- | --- | --- | --- |
| OPT3-N | 门户**通知中心**（React `notification-bell.tsx` 对等） | ✅ | Playwright **21/21** 断言通过；`web` 50 files / 251 tests |
| OPT3-M | 门户**路由动效运行时**（`motion-policy` + `route-motion*` 对等） | ✅ | `MOTION_BROWSER_OK`；reduced 下 `data-anim=off`、VT=0、reveal=0、导航可用 |
| OPT3-E2E | internal E2E 「3 failed」根因定位与修法 | ✅ | 根因 `XDG_CACHE_HOME` 重定向导致 Playwright 找不到浏览器；修后 `3 passed` |
| OPT3-ROUTE | `/antd-pilot` 定性 | ✅ 有意退役 | React 侧无任何导航入口引用、基线无对应 spec；属迁移试点页 |

### 1.1 通知中心（OPT3-N）

- **新增**：`packages/api-client/src/notifications.ts`（`listNotifications` / `fetchUnreadCount` / `markNotificationsRead`）、`apps/web/src/lib/notifications.ts`（`useNotifications`）、`apps/web/src/components/PortalNotificationBell.vue`；`PortalHeader.vue` 右侧图标区接线（语言切换之前）。
- **对等项**：仅登录可见 · 未读徽标 · 30s 轮询 · 20 条未读优先 · 类型图标（inline SVG）· 相对时间 · 链接跳转（先标记已读）· 全部已读 · `aria-expanded`/`role=menu`/Escape/外部点击/焦点回归。
- **适配**：门户门面没有 AntD 的 `Badge/Popover/List`，按 `AdminNotificationBell.vue` 的 token 风格手写浮层；列表查询同样以"已登录"为前置（React 允许匿名打开浮层时发请求，Vue 收紧）。
- **边界**：匿名 → 组件不渲染、两个查询 `enabled:false`、无轮询无请求（浏览器实测）。
- **i18n**：复用既有 `notifications.*` 命名空间；协调者补 `notifications.titleWithCount`（zh 消息通知（{{count}} 条未读）/ en Notifications ({{count}} unread)）。全量 zh/en 各 **1656** key、完全对等、引用零缺失。

### 1.2 路由动效（OPT3-M）

- **新增**：`apps/web/src/lib/motion.ts`（纯策略 + 令牌读取 + 模块级单一状态源 + `useMotion` + `installRouteMotion`）、`apps/web/src/components/motion/RevealOnMount.vue`；`main.ts` 接线、`PortalLayout.vue` keyed 包装。
- **令牌不双写**：时长/缓动/stagger 全部从 `style.css` 既有 `--anim-*` 读出；`<html data-anim="standard|minimal|off">` 复用既有 CSS 规则。
- **降级**：`prefers-reduced-motion: reduce` 或偏好 `off` → 完全不动画；`startViewTransition` 缺失/reduced/同路径/页面隐藏 → 直接跳过；全程 `try/catch`，动效失败不阻断导航。
- **子代理的技术发现（有价值）**：`<Transition>` 放在 `PortalLayout` 内是**惰性**的——PortalLayout 每个路由整体重建，旧实例同步卸载（`leave` 类永不出现）、新实例无 `appear`；rAF 采样 700ms 内 `.route-fade-*` 出现次数恒为 0。因此改用 keyed `RevealOnMount`，VT 可用时用 `:disabled` 让位给根交叉淡入。
- **SSG 安全**：预渲染 HTML 中**没有**内联 `opacity:0`（`grep -c 'style="[^"]*opacity' dist/index.html` = 0），无 JS 时内容可见。

### 1.3 internal E2E 「3 failed」根因（OPT3-E2E）

前两轮合并脚本里出现过 3 次「internal E2E 整版变红」，本轮复现并定位：

```
Error: browserType.launch: Executable doesn't exist at
  <XDG_CACHE_HOME>/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-linux64/chrome-headless-shell
```

- **根因**：验证脚本为 pnpm 重定向了 `XDG_CACHE_HOME=.validation/pnpm/cache`，而 Playwright 按同一环境变量查找浏览器 → 指向空目录 → **3 条用例同时 launch 失败**。产品侧无问题。
- **修法**：`export PLAYWRIGHT_BROWSERS_PATH="${HOME}/.cache/ms-playwright"`。已写入 `e2e/README.md`（新增 "Sandbox / CI note" 小节）与 `.validation/opt3/verify.sh`。
- **附带**：另一条独立成因（vite `emptyOutDir` 清空 `dist/{external,internal}`）仍然成立，顺序约束不变：**先普通 build，最后跑双站 verifier**。`docs/dev/opt2/OPT2-REPORT.md` §4.7 已勘误。

## 2. 协调者复跑验收矩阵（全部 exit 0）

| 门禁 | 结果 |
| --- | --- |
| `pnpm --filter @soymutdb/api-client test` | **27 files / 146 tests** |
| `pnpm --filter @soymutdb/api-client check:contract` | **schema in sync** |
| `pnpm --filter @soymutdb/web test` | **50 files / 251 tests** |
| `web typecheck` / `lint` | **0 / 0** |
| `python3 scripts/check_visible_i18n.py` | **OK** |
| `python3 scripts/test_motion_policy.py` | **OK**（未引入 gsap/lenis） |
| `pnpm --filter @soymutdb/web build` | **exit 0**（27 documents） |
| 预渲染可访问性 | `dist/index.html` 含 `<title>`/description；内联 `opacity` 计数 **0** |
| `pnpm --filter @soymutdb/admin test` / `typecheck` | **22 files / 98 tests** / **0 错误** |
| charts / ui-vue / i18n-core | **4 / 5 / 7 tests** |
| 路由外壳审计（33 路由） | **missingShell = 0** |
| 通知中心浏览器断言 | **21/21 PASS** |
| 动效浏览器断言 | **MOTION_BROWSER_OK**（4 场景，pageerror 0） |
| 双站制品 `verify-site-variant-artifacts.sh`（无 PREBUILT） | **EXIT=0** |
| internal E2E（设 `PLAYWRIGHT_BROWSERS_PATH`） | **3 passed / 0 skipped** |
| `dist/{external,internal}/sw.js` 变体命名空间 | `external` / `internal` |

## 3. 仍未完成：最后一项实质缺口是 **CMS 内容**（GAP-03/04），且已定位真实阻塞

React 允许运营在管理端编辑站点的**文案与整页结构**，前台读取：

- `GET /api/v1/site/content?variant=external|internal` —— **84 个注册 `content.*` 键**（hero / tool / nav / 各页 title+subtitle / help FAQ / common UI / blast / guide / downloads）。
- `GET /api/v1/page-definitions/{route}` —— 首页整页由 PageDefinition 组件树驱动（React `page-builder/loader.ts` + `renderer.tsx`）。

**协调者实测到的阻塞（决定设计，不能猜）**：

```bash
$ curl -s "http://127.0.0.1:8010/api/v1/site/content?variant=external" | python3 -c "import json,sys;d=json.load(sys.stdin);print(len(d))"
131
$ # 抽样
{"hero.title":"Explore the Unknown Territories of Multi-Species Mutation",
 "tool.gene.label":"Gene ID Search", ...}
```

- 接口对**每一个注册键都返回值**，且是**英文注册默认值**（不是"仅返回被改过的行"）。
- 因此**"服务端值直接胜出"的接法会把中文门户的 Hero/工具卡文案整体变成英文**——React 的 `useSiteContent` 契约注释里正是这么写的（"let the content value win"），这是 React 侧既有的双语隐患，Vue 端不应照抄。
- 两条可行设计（需拍板，二选一）：
  1. **接口加 `only_overrides=true`（推荐）**：`GET /site/content` 增加可选参数（或返回 `{values, overridden}`），只回被运营改过的键。前端即可安全地"有覆盖用覆盖、否则用当前语言的 i18n"，无需在前端镜像 84 条默认值。属**加法式**契约变更，需重生成 `generated/openapi.d.ts`（流程已跑通：`pnpm --filter @soymutdb/api-client generate:api-client`，门禁 `check:contract` 现为绿）。
  2. **前端镜像注册默认值**：在 `lib/site-content.ts` 内置一份 84 键默认值表，与返回值比对以判定"是否被覆盖"。无后端改动，但默认值双写、有漂移风险（需要一条与 `settings_registry.py` 对齐的守卫测试）。
- **PageDefinition（GAP-03）另需产品决策**：Vue 门户的结构现在是代码定义（导航/分区/组件由 `views/*.vue` 决定），是否要恢复"运营可在后台任意增删页面区块"的整页渲染器？若答案是否，则 GAP-03 应像 `/antd-pilot`、管理端 page-builder/widgets 一样**明确记为有意退役**（对齐 ADR-0009），而不是继续挂在"缺失"清单里。

## 4. 其余未完成/未验证（沿用前几轮，未变）

1. 真 Redis / 真外网 provider（本机无 `redis-server`）；ClickHouse 未起 → `/api/v1/variants` 503 属设计上的 fail-closed。
2. SW：gh-pages 子路径 scope、跨版本轮换、Firefox/Safari 未验。
3. 研究者门禁：真实研究者 JWT 会话未验；匿名深链 `/analyses` 落 `/login`（与 React 一致）。
4. 详情页成功态真机渲染、live 部署态（CSS/CSP/SW/子路径）未验。
5. 管理端后端聚合端点（`/releases/current`、dashboard storage_growth、审计聚合/导出、导入上传/校验、媒体上传、插件运行时）—— 前端无法闭合，页面已显式降级。
6. `views/**` 未接入 `RevealOnMount`（本轮刻意）；接入建议见 `opt3-m-route-motion.md`。
7. repo-wide ruff 404 条不在任何 CI 门禁内，属既有债务。
8. 三轮改动仍全部未提交。

## 5. 回滚点

| 范围 | 回滚 |
| --- | --- |
| 本轮全部 | `git checkout -- <file>` / 删除新增文件（未提交） |
| 客户端契约（OPT2 重生成） | `.validation/opt2/contract-backup/` |
| SW 模板 + 构建脚本 | `git checkout -- apps/web/public/sw.js apps/web/scripts/gen-sw.js` |
