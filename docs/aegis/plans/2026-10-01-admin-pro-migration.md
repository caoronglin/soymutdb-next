# 管理后台 Pro v6 迁移执行计划（对齐官方 sub-page 实例）

- 整理日期：2026-10-01
- 设计来源（已批准）：[`docs/superpowers/specs/2026-10-01-admin-pro-migration-design.md`](../../superpowers/specs/2026-10-01-admin-pro-migration-design.md)
- 官方实例：[`ant-design-pro` `src/pages/table-list`](https://github.com/ant-design/ant-design-pro/blob/master/src/pages/table-list/index.tsx)（预览 `/admin/sub-page`）
- 计划性质：把已批准设计拆成可执行切片；不新增或放宽设计约束

## 1. 本计划解决什么问题

`docs/aegis/plans/2026-09-27-react-pro-v6-replatform.md` 的 W2/W3 停在「11 个页面用裸 antd `Table`」这一旧口径上。
2026-10-01 实跑核对后的真实缺口是三件事，且都**不是**「门面没导出 Pro 组件」：

1. 6 个页面仍是裸 antd `Table`，没有走 ProTable 外壳（4 个已在共享适配器 `components/data-table.tsx` 上）；
2. `ProDescriptions` 全仓 0 处，`ProCard` 全仓 0 处，详情与列表页混排；
3. `ProLayout.menuItemRender` 用 `<a href>`，每次导航整页刷新，且 `__root.tsx` 的 `PAGE_TITLES` 与 `PageContainer` 页头口径重复。

外加两条与「内容管理」直接相关的待办：导航可达性守卫随 Vue 退役删除后无人接管；可见文案守卫当前为红（39 个文件）。

## 2. 已核实现状（2026-10-01 实跑）

| 维度 | 实测 | 证据 |
| --- | --- | --- |
| admin 单测 | 6 files / 41 tests（本轮由 3/19 增加） | `pnpm --filter @soymutdb/admin test` |
| admin typecheck | exit 0 | `pnpm --filter @soymutdb/admin typecheck` |
| antd CLI lint | web 152 文件 / admin 112 文件无问题 | `antd lint apps/{web,admin}/src` |
| antd CLI usage | 对本仓报「No antd imports found」（不解析 `@/lib/antd` 门面） | `antd usage apps/admin/src` |
| antd CLI doctor | 报 `antd is not installed in node_modules`（antd 只存在于 workspace 包，不在根） | `antd doctor` |
| `Table.pagination` 类型 | `object \| false`，**无 cursor/keyset** | `antd info Table` |
| 可见文案守卫 | exit 1，39 个文件 | `node scripts/check_visible_i18n_react.mjs` |
| 导航可达性 | 6 条裸 `Table` 页 + 10 条未入导航路由（其中 7 条为 ADR-0009 有意退役、6 条为 settings 子路由） | 本轮 `regression/nav-reachability.test.ts` |
| 消融测试 | API 侧 16 个文件 **149 passed / 0 failed** | `pytest tests/test_ablation_*.py` |

## 3. 切片

### A1 · 页头与导航归一（设计 §3.1）

- `__root.tsx`：删 `PAGE_TITLES`；`menuItemRender` 改 `<Link to={item.path}>`（TanStack Router），保留 `headerRender={false}`。
- 每个功能页包 `PageContainer`，把 `title`/`subTitle`/`breadcrumb`/`extra` 从页面自身搬进去。
- 门禁：`nav-reachability.test.ts` 保持绿；admin typecheck + 41 tests；浏览器实测点击侧栏不再整页刷新（`performance.getEntriesByType('navigation')` 只出现一次）。

### A2 · 列表页 ProTable 外壳（设计 §3.2）

按此顺序逐页，单页一个切片，每页配一条消融：

1. `content/static-page-migration-report.tsx`（只读报告，最小切片）
2. `preview-test-data.tsx`（只写 `available` 一个字段，最容易在迁移中被 ProTable 默认编辑行为放宽）
3. `table-views.tsx`
4. `instances.tsx`
5. `releases.tsx`（附 `rowSelection` + `FooterToolbar` 批量下线）
6. `audit.tsx` 从 `DataTable` 迁到独立 `ProTable` + 导出动作

- **不得**把 cursor/keyset 列表改成页码分页；antd `pagination` 只支持 `object | false`，keyset 列表必须 `pagination={false}` + 自带控件。
- `content/pages-tab`、`news/index`、`imports`、`audit` 已在 `DataTable` 适配器上，适配器本身保持窄契约，等 W3 收口后再决定是否解散。

### A3 · 详情与表单（设计 §3.3）

- `ProDescriptions` + `Drawer`：`imports/$taskId`、`instances`、`releases`、`content/version-history-dialog`。
- `ModalForm`：`content/page-form-dialog.tsx`、`news-form.tsx`、`external-article-import-modal.tsx`。
- 页内长表单保持 `ProForm`：`news/new`、`news/$id`、`settings/*`。
- 提交锁 + 失败反馈 + 成功后 `invalidateQueries` 三件套齐全才算完成。

### A4 · 内容管理收口（设计 §3.4）

- `/content/pages`：状态机列上色、发布/回滚二次确认并写审计、版本历史抽屉。
- `/news` 系列：双语同屏校验、回收站恢复/彻底删除的影响条目数提示。
- `/media`：MIME/大小前置校验、引用计数、删除被引用资源时阻断并说明原因。
- 写目标可见：`InstanceContext` 在写路径上可见（不只是页眉），非 dev 环境 `preview-test-data` 继续 404。

### A5 · 可见文案守卫转绿（交付门禁前置）

- `check_visible_i18n_react.mjs` 当前 exit 1（39 文件）。逐文件把硬编码文案搬进 `zh`/`en` 或在
  `scripts/visible-i18n-allowlist.json` 登记规范 token；每修一文件跑一次守卫，禁止为过门禁而整体加白名单。

### A6 · 性能对照（设计 §3.5）

- 长列表加 `content-visibility`；分页/筛选切换包 `startTransition`；重组件保持动态导入；
  `staleTime` 按数据域分档而非全站单一值。
- 不声称已验证：LCP/CLS 需要真实部署态测量（`docs/3.9升级优化文档.md` §11.13）。

## 4. 门禁

| # | 门禁 | 本地可跑 |
| --- | --- | --- |
| 1 | `pnpm --filter @soymutdb/admin lint typecheck test` | 是 |
| 2 | `node scripts/check_visible_i18n_react.mjs` exit 0 | 是（A5 前为红） |
| 3 | `python3 -m pytest scripts -q`（含 CI/交付契约 275） | 是 |
| 4 | `node scripts/check-react-entry-graph.mjs`、`node scripts/check-vue-retirement.mjs` | 是 |
| 5 | `antd lint apps/admin/src` 无问题 | 是 |
| 6 | admin 单测里的消融项能因删除守卫而转红 | 是 |
| 7 | `pnpm --filter @soymutdb/web test`（内容管理改动不得影响公共站） | 是 |
| 8 | 双站制品隔离与 external 泄漏负例 | 是（`verify-site-variant-artifacts.sh`） |
| 9 | 截图视觉验收、Admin save→公共渲染 E2E、响应式运行时 | **否**，需可写隔离环境 |

## 5. 顺序与暂停条件

顺序：**A1 → A2（逐页）→ A3 → A4**，**A5 可与 A1–A4 并行**（它只改文案，不改结构）。

暂停并报告的条件：迁移需要改动后端契约才能推进；`antd`/`ProComponents` 出现许可证或漏洞告警；
`check-react-entry-graph.mjs` 不再 PASS；任何切片为了套用 ProTable 默认行为而被迫改分页语义或公开身份字段。

## 6. 本轮已完成的准备（不属于上述切片的代码改动）

| 项 | 文件 | 目的 |
| --- | --- | --- |
| 内容管理 URL 状态功能测试 | `apps/admin/src/routes/content/content-management.test.ts` | 锁住「URL 为真源」：分页/状态/分类解析、序列化、缓存键隔离 |
| 导航可达性消融 | `apps/admin/src/regression/nav-reachability.test.ts` | 恢复 Vue 退役后丢失的守卫；含合成消融证明守卫可失效 |
| 门面导出完整性消融 | `apps/admin/src/regression/antd-facade-exports.test.ts` | 补 `@ant-design/cli usage` 解析不到门面层的盲区 |