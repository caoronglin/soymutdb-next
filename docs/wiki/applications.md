# 应用与功能状态

本页记录公共站与管理端的路由与实现状态。**「已实现」= 代码在、有测试/构建证据；
「计划中」= 尚未恢复或尚未实现**，不以空页面充数。

## 公共站 `apps/web`（35 条路由）

路由定义：`apps/web/src/router/routes.ts`。

| 分组 | 路由 | 状态 |
| --- | --- | --- |
| 首页 | `/`（标识符搜索 + 实体入口 + 工具 + 组装 + 真实新闻） | 已实现 |
| 搜索 | `/search`、`/search/genes`、`/search/location`、`/search/gbrowse`、`/search/primer`、`/search/blast`、`/search/tools` | 已实现 |
| 实体 | `/genes`、`/genes/:geneId`、`/variants`、`/mutants`、`/mutants/:publicId` | 已实现 |
| 工具 | `/tools`、`/tools/seqfetch`、`/tools/exppattern`、`/tools/enrichment`、`/blast`、`/browser`、`/analyses*`、`/sra`、`/compare`、`/analytics` | 已实现 |
| 内容 | `/news`、`/news/:slug`、`/about`、`/publications`、`/downloads`、`/guide`、`/help` | 已实现 |
| 账户 | `/login`（独立布局 + 子路径回跳校验） | 已实现 |

公开边界要点：

- 搜索结果无合法 URL 时渲染不可点击行（`search-result-disabled`），不伪造 `#` 链接。
- 搜索/表格显示 assembly 与 release 上下文；assembly 选择使用稳定 `id`，v4/v5 标签带版本。
- 品牌快照运行时更新页眉、文档标题与 favicon；读取失败保留构建期默认。
  **构建期把品牌写入静态 HTML/manifest：计划中。**

## 管理端 `apps/admin`（14 条路由）

路由定义：`apps/admin/src/router/index.ts`。

| 路由 | 功能 | 状态 |
| --- | --- | --- |
| `/login` | 独立登录卡片，根路径/子路径回跳 | 已实现 |
| `/` | Dashboard（真实指标；React 版扩展指标） | 已实现（关键指标） |
| `/releases` | 发布版本与来源 | 已实现 |
| `/imports` | 导入列表与创建 | 已实现；导入详情/进度增强: 计划中 |
| `/table-templates` | 可配置表格列模板 | 已实现 |
| `/publications` | 文献管理 | 已实现 |
| `/news` | 新闻双语编辑；预览/回收站 | 部分（列表/编辑已实现，预览/回收站计划中） |
| `/media` | 媒体库（归档而非硬删） | 已实现 |
| `/audit` | 审计日志筛选 | 已实现 |
| `/features` | 能力开关 | 已实现 |
| `/instances` | 实例登记、连接探活、门户跳转、设为当前目标；全部页面显示目标实例/发布/服务器 | 已实现（本地可写，远端只读） |
| `/settings` | 版本化设置编辑器 + 设置历史 | 已实现（历史回滚 UI 计划中） |
| `/settings/brand` | 外网/内网双语品牌与图标 | 已实现 |

React 基线（`2004c25c6`）的旧深链采用两种明确处理（`apps/admin/src/router/index.ts`）：

- **重定向到已恢复的等价入口**：
  `/settings/site → /settings/brand`；`/settings/security → /settings?section=security`；
  `/news/new → /news?new=1`；`/news/trash → /news?status=archived`；`/news/:id → /news?edit=<id>`。
  `SettingsView` 支持 `?section=`，`NewsAdminView` 支持 `?status=`/`?edit=`/`?new=`。
- **尚未恢复的工作流**：`/page-builder*`、`/content*`、`/resource-catalog`、`/widgets*`、
  `/layout`、`/widget-preview`、`/widget-health`、`/analytics-settings`、`/imports/new`、
  `/imports/:taskId`、`/settings/{legacy,appearance,integrations,localization,advanced}`
  落到 `LegacyUnavailableView`：写明请求路径、标记「计划中」、不读写任何数据，并提供已恢复入口。
  禁止用空页面或无说明 404 代替（`legacy-routes.test.ts` 锁定该策略）。

## 语言

- 字典：`packages/i18n-core/src/locales/{en,zh}/common.json`，两语言 key 集合必须一致。
- 占位符统一使用 i18next 语法 `{{var}}`；`i18n-core` 测试会拒绝单花括号写法。
- 可见文案预算：`scripts/check_visible_i18n.py` + `scripts/visible-i18n-baseline.json`，
  计数只降不升；未翻译页面在 baseline 中显式列出。当前基线为 **6 串 / 1 文件**
  （`TableTemplatesView` 的物种与 scope 数据值），其余可见文案均来自字典。
- 扫描器按 token 判定：科学名/缩写/含数字标识可白名单，句子与标签必须走字典。
