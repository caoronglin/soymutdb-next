# React + Ant Design Pro v6 全线迁移执行计划

- 整理日期：2026-09-29
- 设计来源（已批准）：[`docs/superpowers/specs/2026-09-27-react-pro-v6-replatform-design.md`](../../superpowers/specs/2026-09-27-react-pro-v6-replatform-design.md)
- 计划性质：把已批准设计转成可执行分解；不新增或放宽设计约束

## 1. 这份计划解决什么问题

设计在 2026-09-27 已获用户确认，但 `docs/aegis/plans/` 下没有对应的执行计划，实施进度散落在 `docs/dev/react-migration-progress-2026-09-27.md`、`.ai-memory/handoff.md`、`docs/dev/ablation/2026-09-26/` 等多份文档里，无法一眼看出「做到哪、还剩什么」。本文件把现状核实、剩余任务、执行顺序与门禁收口到一处。

## 2. 已核实现状（2026-09-29，均为代码证据）

| 维度 | 现状 | 证据 |
| --- | --- | --- |
| 运行栈 | 三个应用均已是 React 19 + Umi Max 4 + antd 6 + ProComponents v3 | `apps/{web,admin,jbrowse}/package.json` |
| Vue 生产路径 | 已切断：React 入口不触达任何 `.vue` | `node scripts/check-react-entry-graph.mjs` → web 95 / admin 21 / jbrowse 9 模块全 PASS |
| Vue 死代码 | 仍有 **106** 个 `.vue`：web 56、admin 34、jbrowse 5、`packages/genome-view` 11 | `find apps packages -name '*.vue'` |
| admin 布局 | ProLayout 已接线 | `apps/admin/src/routes/__root.tsx` |
| admin 组件门面 | 已导出 `PageContainer`、`ProCard`、`ProDescriptions`、`ProForm`、`ProFormSelect`、`ProFormText`、`ProTable`、`ProColumns`（71 行） | `apps/admin/src/lib/antd.ts`（2026-09-29 复核） |
| Pro 业务组件落地 | ProTable **0** 个页面、ProDescriptions **0**、ProCard **0**；PageContainer 4–6 文件、ProForm 3 文件 | 逐项 grep |
| 待迁列表页 | **11** 个页面仍用裸 antd `Table` | 见 §3 W2 |
| web / jbrowse | 未引入 Pro 组件（符合设计：公共站/JBrowse 只共用 token，不套 ProLayout） | ProLayout/ProTable/PageContainer 均为 0 |
| 共享 UI 包 | `packages/ui-react` 仅 `design-tokens.ts` + `index.tsx` | `ls packages/ui-react/src` |
| 门禁脚本 | 均已就位 | `verify-site-variant-artifacts.sh`、`verify-frontend-artifacts.sh`、`check-react-entry-graph.mjs`、`check_page_registry.py` |

**结论**：技术栈迁移已完成，但 **Pro v6 的业务组件体系基本没有落地**——列表用裸 Table、详情没有 ProDescriptions、页面缺 PageContainer 统一页头。这就是本计划的主体工作。

## 3. 剩余工作分解

### W1 · Admin Pro 门面补齐（前置，解锁后续全部）

- 门面已存在于 `apps/admin/src/lib/antd.ts`，**不需要从零扩建**：2026-09-29 复核确认它已导出 `PageContainer`、`ProCard`、`ProDescriptions`、`ProForm`、`ProFormSelect`、`ProFormText`、`ProTable`、`ProColumns`。
- 本步只补确实缺失的导出：`ProFormDigit`、`ProFormTextArea`、`ProList`，以及 `ProTable` 的 `ActionType` 类型；不得为已存在的组件再造包装层（设计 D3 `:43`）。
- 统一 `PageContainer` 页头契约（title / subTitle / breadcrumb / extra 操作区），并保证既有 `data-testid` 不被移除。
- 门禁：`apps/admin` typecheck + lint 通过；现有 22 files / 98 tests 保持通过。
- **早期版本的本计划曾把此处写成"门面极薄、仅 2 处 export，需扩为 Pro 门面"，该判断有误**——"2"是 export 语句条数而非导出符号数。W2/W3 不存在"门面未导出"阻塞，仅剩个别符号需补。

### W2 · 列表页迁 ProTable（11 个页面）

- `audit.tsx`、`content/news-publication-tab.tsx`、`content/pages-tab.tsx`、`content/version-history-dialog.tsx`、`imports/import-validation-report.tsx`、`imports.tsx`、`instances.tsx`、`news/index.tsx`、`news/trash.tsx`、`releases.tsx`、`table-views.tsx`
- 每个页面：`request` 接既有 query function、保留筛选/分页/排序语义、`rowKey` 沿用既有业务主键、`options={{ reload, density, setting }}` 按需开启。
- **硬约束**：不得改变 API 契约与 release/assembly 作用域；分页必须继续走既有 cursor/keyset 语义，不得为了 ProTable 默认分页而退回 offset 分页。
- 单页一个切片，改完即跑该页相关 vitest。

### W3 · 表单与详情

- 表单页改 `ProForm` + 校验 + 提交锁 + 成功/失败反馈：`news/new.tsx`、`news/$id.tsx`、`settings/*`。
- 详情页引入 `ProDescriptions`：`releases.tsx`、`imports/*`、`instances.tsx`。
- 保持 `panel`/`form` 双语 key 完整；新文案必须同时进 `zh`/`en`。

### W4 · 消融与验收（设计 R8 + 交付门禁）

> 原 W4「Vue 退役（设计 R7）」已按用户 2026-09-29 的决定从本计划移除：不再为 Vue 相关清点与退役安排计划项。仓内仍有 106 个 `.vue`（web 56、admin 34、jbrowse 5、`packages/genome-view` 11）及 `packages/ui-vue`、`packages/genome-view` 目录，它们是无消费者的遗留文件，不阻塞本计划任何一项。

- 按设计表 E0–E6 逐组记录命令、退出码、结果与 GUARD 判定；`SKIPPED` 不计通过。
- 响应式与无障碍：375 / 768 / 1024 / 1440 px 无横向溢出、触控目标 ≥ 44 px、键盘焦点可见、`prefers-reduced-motion` 被尊重。

## 4. 门禁（引用设计第「验收与交付门禁」节，标注本地可跑性）

| # | 门禁 | 本地可跑 |
| --- | --- | --- |
| 1 | 冻结安装 + Umi Max 最小静态导出试验 | 部分：本机 `pnpm` 解析到 v11.24.0 且报 `unable to open database file`，需用 corepack 转发 shim |
| 2 | 三应用 lint/typecheck/unit/build + `--frozen-lockfile` | 是 |
| 3 | React 路由与行为矩阵无未解释差异 | 是 |
| 4 | 双站制品隔离、external 泄漏负例、CSP/SW/base | 是（`verify-site-variant-artifacts.sh`） |
| 5 | public/internal ID × external/internal × v4/v5 矩阵非 skip 证据 | 部分：15 个测试依赖 testcontainers，本机无 Docker |
| 6 | JBrowse bridge / 深链 / 轨道渲染真实浏览器断言 | 需部署栈 |
| 7 | 视口/键盘/对比度/表单状态 + 双语门禁 | 是（`check_visible_i18n_react.mjs`，**当前 exit 1**） |
| 8 | 消融报告逐组记录 | 是 |
| 9 | 验证逻辑落在仓库脚本、`.cnb.yml` 单一事实来源 | 是 |

## 5. 已知阻碍（承接当前环境，非规模问题）

- **构建链**：`apps/web/scripts/csp.ts` 只认 `NODE_ENV=development` 放行 http origin，而 `apps/web/config/config.ts` 还认 `SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED`；两者不一致使 http 预览地址无法走完 `build-sites.ts`，目前只能分步跑 `max build` → `finalize-csp` → `gen-sw`。
- **包管理器**：PATH 中的 `pnpm` 指向坏 shim，构建脚本内部的裸 `pnpm` 调用需要 corepack 转发。
- **Docker 缺失**：`docker` 不在本机，15 个 testcontainers 守卫必然 SKIPPED（不等于 PASS）。
- **i18n 守卫当前为红**：`node scripts/check_visible_i18n_react.mjs` → exit 1，命中 `routes/analyses/$jobId.tsx`、`analyses/fastp.tsx`、`analyses/scanpy.tsx`、`news/$slug.tsx`、`components/site-header.tsx`。
- **`Makefile:197` 的 lint 目标已失效**：`cd apps/api && ruff check src/`，而 `apps/api/src` 不存在（代码在 `apps/api/app`），等于看起来有 lint 实际没跑。

## 6. 执行顺序与暂停条件

顺序：**W1 → W2（逐页）→ W3 → W4（消融与验收，可并行于 W2/W3 的单页验证）**。

暂停并报告的条件（承接设计「已知风险与暂停条件」）：Umi Max 静态导出与双站/CSP/SW 不兼容、Pro v6 依赖出现许可证或漏洞问题、`check-react-entry-graph.mjs` 不再 PASS、或需要改动后端契约才能推进。
