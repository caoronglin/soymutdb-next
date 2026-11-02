# 应用与功能状态

本页记录公共站与管理端的路由与实现状态。**「已实现」= 代码在、有测试/构建证据；
「计划中」= 尚未实现**，不以空页面充数。

## 公共站 `apps/web`（React 19 + Umi Max 4）

路由定义：`apps/web/src/router/routes.ts`（TanStack Router 文件路由 +
`apps/web/src/routes/**`），`external` / `internal` 两种构建变体共用同一份代码。

| 分组 | 路由 | 状态 |
| --- | --- | --- |
| 首页 | `/`（标识符搜索 + 实体入口 + 工具 + 组装 + 新闻） | 已实现 |
| 搜索 | `/search`、`/search/genes`、`/search/location`、`/search/gbrowse`、`/search/primer`、`/search/blast`、`/search/tools` | 已实现 |
| 实体 | `/genes`、`/genes/:geneId`、`/variants`、`/mutants`、`/mutants/:publicId` | 已实现 |
| 工具 | `/tools`、`/tools/seqfetch`、`/tools/exppattern`、`/tools/enrichment`、`/blast`、`/browser`、`/genome-view`、`/analyses*`、`/sra`、`/compare`、`/analytics` | 已实现 |
| 内容 | `/news`、`/news/:slug`、`/about`、`/publications`、`/downloads`、`/guide`、`/help`、`/seed-request` | 已实现 |
| 账户 | `/login`（独立布局 + 子路径回跳校验） | 已实现 |

公开边界要点：

- 搜索结果无合法 URL 时渲染不可点击行（`search-result-disabled`），不伪造 `#` 链接。
- 搜索/表格显示 assembly 与 release 上下文；assembly 选择使用稳定 `id`，v4/v5 标签带版本。
- 品牌快照运行时更新页眉、文档标题与 favicon；读取失败保留构建期默认。
  **构建期把品牌写入静态 HTML/manifest：计划中。**
- 内容文案经 `useSiteContent().get("<key>", t(...))` 读取，服务端只返回被覆盖的键；
  未覆盖时回落到 i18n 字典（内容键契约由 `scripts/check_content_key_contract.py` 守护）。

## 管理端 `apps/admin`（React 19 + Umi Max 4）

路由定义：`apps/admin/src/routes/**`（TanStack Router 文件路由）。历史深链按
ADR-0009 与 `LegacyUnavailable*` 策略处理：能重定向的重定向（如
`/news/new → /news?new=1`），已退役的显式渲染 `legacy-unavailable` 页面并给出恢复入口，
禁止空页面或静默 404。

| 分组 | 路由 | 状态 |
| --- | --- | --- |
| 登录/首页 | `/login`、`/`（Dashboard 真实指标） | 已实现 |
| 发布 | `/releases`（含发布行编辑） | 已实现 |
| 导入 | `/imports`、`/imports/new`、`/imports/:taskId` | 已实现（含 Import Studio 草稿/映射/校验/提交） |
| 内容 | `/content`（静态页面、版本历史、旧内容迁移报告） | 已实现 |
| 新闻 | `/news`、`/news/new`、`/news/:id`、`/news/trash` | 已实现（双语文案、状态筛选） |
| 表格 | `/table-views`（可配置列模板与保存视图） | 已实现 |
| 内容库 | `/publications`、`/media` | 已实现（媒体归档而非硬删） |
| 审计/能力 | `/audit`、`/features` | 已实现 |
| 实例 | `/instances`（登记、探活、门户跳转、设为当前目标） | 已实现（本地可写，远端只读） |
| 设置 | `/settings`（版本化设置与历史）、`/settings/{brand,appearance,advanced,integrations,localization,security}` | 已实现 |
| 其他 | `/analytics-settings`、`/usage-guide`、`/preview-test-data` | 已实现 |

## 前端技术栈（2026-10-18 核对）

三个前端均为 **React 19 + Umi Max 4 + Ant Design 6**（`apps/*/package.json`），
Vue 已完全退役（仓库内 0 个 `.vue` 文件）：

- 构建/开发：Umi Max（webpack 生产构建，`max build` / `max dev`）；工作区根
  `pnpm build` 走 turbo，公网站点用 `pnpm build:web` 产出 `dist/external` 与
  `dist/internal` 两棵独立制品。
- 路由/数据：TanStack Router + TanStack Query（`packages/query-keys` 持有缓存键契约）。
- 样式/图表：Tailwind CSS 4 + `packages/ui-react` 设计系统门面；图表在
  `packages/charts`（`@ant-design/plots` + 自管 G2 运行时）。
- 桌面壳：`apps/jbrowse` 复用 `@soymutdb/genome-view` / `@soymutdb/genome-data`
  与 `@jbrowse/react-linear-genome-view`。
- 测试工具链：Vitest（`packages/*/vitest.config.ts`、`apps/*/vitest.config.ts`）+
  Playwright（`e2e/`）；Vite 仅作为测试/开发工具依赖，不参与生产构建。

## 语言

- 字典：`packages/i18n-core/src/locales/{en,zh}/common.json`，两语言 key 集合必须一致。
- 占位符统一使用 i18next 语法 `{{var}}`；`i18n-core` 测试会拒绝单花括号写法。
- 可见文案预算：`node scripts/check_visible_i18n_react.mjs`（React 源码扫描，基线在
  `scripts/visible-i18n-baseline.json`，计数只降不升）；遗留 Vue 扫描器只覆盖 `.vue`
  文件（当前 0 个）并共享同一基线文件，新增可见文案必须走字典。
- 扫描器按 token 判定：科学名/缩写/含数字标识可白名单，句子与标签必须走字典。
