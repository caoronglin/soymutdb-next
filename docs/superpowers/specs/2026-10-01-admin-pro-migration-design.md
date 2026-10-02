# 管理后台 Pro v6 迁移设计（对齐 Ant Design Pro 官方 sub-page 实例）

- 日期：2026-10-01
- 状态：**已批准方向，等待逐页实施**；本文只定义目标形态与硬约束，不在本轮改写页面代码
- 依据实例：[ant-design-pro `src/pages/table-list`](https://preview.pro.ant.design/admin/sub-page/)（线上预览 `/admin/sub-page`）与其
  [`index.tsx`](https://github.com/ant-design/ant-design-pro/blob/master/src/pages/table-list/index.tsx)
- 上游契约：`docs/3.9升级优化文档.md` §3（不可违反的基线契约）、§5（Pro v6 落地现状）
- 相关计划：`docs/aegis/plans/2026-09-27-react-pro-v6-replatform.md`（W2/W3）、`docs/aegis/plans/2026-10-01-admin-pro-migration.md`
- 既有裁定的修正口径：本文以 `docs/3.9升级优化文档.md` §5 的「口径修正」为准 —— 组件门面**已经**导出 Pro 组件，
  W2/W3 不存在「门面未导出」阻塞；`ProTable` 也**已经**通过共享适配器 `apps/admin/src/components/data-table.tsx` 落地。
  真正的缺口是「11 个页面仍用裸 antd `Table`」和「详情页没有 ProDescriptions」这两类。

## 1. 官方实例的实际形态（2026-10-01 读取源码核对）

`ant-design-pro` 的 `table-list`（预览路由 `/admin/sub-page`）是一个**嵌套子页面**，其结构是本设计的目标模板：

| 要素 | 官方写法 | 作用 |
| --- | --- | --- |
| `PageContainer` | 页面最外层容器，自带面包屑与页头 | 页头口径唯一来源 |
| `ProTable` + `actionRef` | `actionRef.current?.reload()` / `reloadAndRest()` | 增删改后刷新，不必各自维护分页状态 |
| `request={async (params, sort, filter) => ...}` | 数据与查询参数收敛在 `request` | 表格只描述列，页面不再手写 fetch 分支 |
| `ProColumns` | `title` / `dataIndex` / `sorter` / `valueType` / `valueEnum` / `hideInForm` / `render` | 列即筛选表单：ProTable 自带搜索区 |
| `rowSelection` + `FooterToolbar` | 批量选择后底部工具条汇总与批量操作 | 批量审批/删除 |
| `ProDescriptions` + `Drawer` | 详情抽屉 | 详情不再与列表页混排 |
| `ModalForm`（`CreateForm`/`UpdateForm`） | 新建/编辑弹窗表单 | 表单与详情分离 |
| `useMutation` + `invalidateQueries` | 变更后按 queryKey 失效缓存 | 不手写 `refetch` 瀑布 |
| `message.useMessage()` + `contextHolder` | 反馈绑定到实例，避免静态 API 警告 | 与 antd 6 一致 |

## 2. 本仓现状（2026-10-01 实跑核对，不引用旧结论）

| 维度 | 现状 | 证据 |
| --- | --- | --- |
| 布局 | `ProLayout` 已接线，`headerRender={false}` + 自研 `AdminHeader` | `apps/admin/src/routes/__root.tsx` |
| 导航 | `menuItemRender` 用 `<a href>`，**每次点击整页刷新**，且与 `AdminSidebar` 并存两套导航 | `__root.tsx:70-77` |
| 组件门面 | 导出 60+ 符号，含 `PageContainer`/`ProTable`/`ProDescriptions`/`ProCard`/`ModalForm`/`StatisticCard` | `apps/admin/src/lib/antd.ts` |
| Pro 落地 | `PageContainer` 15 处、`ProForm` 4 处、`ProTable` **3 处（均在 `data-table.tsx` 适配器内）**、`ProDescriptions` **0**、`ProCard` **0** | 逐项 grep |
| 列表页 | 4 个页面已在 ProTable 适配器上（`imports`、`audit`、`content/pages`、`content/news-publication`、`content/version-history`）；**6 个仍是裸 antd `Table`** | `routes/{releases,instances,table-views,preview-test-data}.tsx`、`content/static-page-migration-report.tsx` |
| 详情 | 无 `ProDescriptions`；`imports/:taskId`、`instances`、`releases` 详情与列表同页堆叠 | 同上 |
| 批量操作 | 无 `rowSelection` / `FooterToolbar` | 全仓 0 处 |
| 内容管理 | `content.tsx` + `content/pages-tab.tsx`(453 行) + `news/index.tsx`(341) + `media.tsx`(378) + `publications.tsx`(357)；URL 状态由 `content/search.ts` 解析，**已是 URL 真源** | 实读源码 |
| 双语 | 组件级 `t(key,{defaultValue})` + `check_visible_i18n_react.mjs` 守卫（**当前 exit 1，39 个文件**） | 实跑 |
| 组件层面 | `antd lint apps/web/src` 152 文件、`apps/admin/src` 112 文件**无问题**；但 `antd usage` 对本仓报「No antd imports found」——**门面层它不解析**，故新增 `apps/admin/src/regression/antd-facade-exports.test.ts` 代替 | 实跑 `@ant-design/cli@6.6.5` |
| 导航可达性 | 旧 Vue 树的 `nav-reachability.test.ts` 随 Vue 退役删除，本轮按官方实例恢复为 `apps/admin/src/regression/nav-reachability.test.ts`（含合成消融） | 本轮新增 |

## 3. 目标形态

### 3.1 页头与导航归一

- 每个功能页以 `PageContainer` 为唯一页头容器：`title` / `subTitle` / `breadcrumb` / `extra`；删除 `__root.tsx` 里按 pathname 猜标题的 `PAGE_TITLES` 表。
- 导航只保留 `NAV_SECTIONS` 一处来源，`ProLayout.route` 由它派生；`menuItemRender` 改用 TanStack Router 的 `<Link to={item.path}>`，消除整页刷新。
- 保留 `headerRender={false}`：本仓页眉承载实例上下文与登出，属产品决策，不在本次迁移范围。

### 3.2 列表页：以 `ProTable` + `actionRef` 为统一外壳

对 §2 列出的 6 个裸 `Table` 页面逐页迁移，单页一个切片：

- `columns` 用 `ProColumns`；筛选条件用 `valueType`/`valueEnum` 声明，让 ProTable 生成搜索区，而不是页面自绘筛选表单。
- 数据获取收敛到 `request`，返回 `{ data, total, success }`。
- 变更操作走 `useMutation` + `invalidateQueries`；刷新用 `actionRef.current?.reload()`。
- 批量动作（`releases` 的下线、`audit` 的导出、`instances` 的登记）按官方实例加 `rowSelection` + `FooterToolbar`。

**硬约束（不可让步）**

1. 不改任何 API 契约：不新增/改名/重排字段，不改端点，不改鉴权。
2. **分页语义不变**：antd `Table.pagination` 的类型是 `object | false`，ProTable 的 `pagination` 同样只支持页码。本仓凡是 keyset/cursor 的列表必须
   `pagination={false}` + 自带「上一页/下一页」控件，不得为了套用 ProTable 默认分页而退回 offset 分页。
   （依据：`antd info Table` 实跑输出 `pagination  object | false`；本仓既有契约见 `AGENTS.md`「filterable and paginated result sets」与
   `docs/3.9升级优化文档.md` §3 缓存键条款。）
3. `rowKey` 沿用既有业务主键；**不得**为了省事用数组下标，也不得把内部 `id` 当公开身份暴露到文案或链接上（公开契约见 §3.4）。
4. 新增文案必须同时进 `zh`/`en`，且不引入硬编码可见字符串（`check_visible_i18n_react.mjs` 必须转绿）。

### 3.3 详情与表单

- 详情：`ProDescriptions` + `Drawer`（`imports/:taskId`、`instances`、`releases`、内容版本历史）。
- 表单：`ModalForm`（新建/编辑弹窗，如 `content/page-form-dialog.tsx`、`news-form.tsx`、`external-article-import-modal.tsx`）与页内 `ProForm`（长表单，如 `/news/new`、`/news/$id`、`settings/*`）**按官方实例区分使用**，不互相替换。
- 提交锁、失败反馈、成功后按 queryKey 失效缓存，三件套缺一不可。

### 3.4 内容管理（本轮的重点面）

内容管理是数据库产品里唯一让运营改数据的入口，迁移必须让「改了什么」可见：

| 页面 | 迁移目标 | 内容管理要点 |
| --- | --- | --- |
| `/content/pages` | `ProTable`（已有适配器）+ 版本历史 `ProDescriptions` 抽屉 | 状态机（draft/published/archived）用 `valueEnum` 上色；发布/回滚动作走确认弹窗并写审计 |
| `/content/legacy` 迁移报告 | 保留表格，补「可安全迁移/需人工」两列语义 | 只读页面不得出现可编辑控件 |
| `/news`、`/news/new`、`/news/$id`、`/news/trash` | 列表 `ProTable` + `ModalForm`/`ProForm` | 双语标题/摘要同屏校验；回收站为软删列表，恢复/彻底删除二次确认并显示影响条目数 |
| `/publications` | `ProTable` + 详情抽屉 | `is_featured` 等业务标记在列表可见 |
| `/media` | `ProTable` + 上传抽屉 | 上传前校验 MIME/大小；引用计数可见，删除被引用资源时必须阻断并说明原因 |
| `/preview-test-data` | `ProTable` + 开关列 | 只写 `available` 一个字段的契约不得被 `ProTable` 的默认编辑行为放宽 |

**内容管理不可让步的行为约束**：任何写操作都要能回答「写到哪个实例、哪个站点变体、哪个 release」。
`InstanceContext`（`lib/instance-context-react.tsx`）必须在写路径上可见，而不是只在页眉显示一次；
`preview-test-data` 这类 dev-only 端点在非 dev 环境必须继续 404（`test_local_test_preview.py` 锁定）。

### 3.5 性能（对照 Vercel React 规则）

本仓是 Umi Max SPA + SSG，不是 Next.js，Vercel 规则里 server-* 一节不适用；适用的部分：

- **渲染级**：`rendering-conditional-render`（用三元而非 `&&`）、`rendering-hoist-jsx`、`rendering-content-visibility`（长列表表格）。
- **重渲染级**：`rerender-derived-state-no-effect`（派生状态在渲染期算，不用 effect 同步）、`rerender-memo`（只 memo 真正贵的列渲染）、
  `rerender-transitions`（分页/筛选切换用 `startTransition`，输入框保持可打字）。
- **包体级**：`bundle-dynamic-imports` —— 编辑器、图表、上传等重组件一律动态导入（沿用现有 `lazy()` 模式）。
- **数据获取级**：`client-swr-dedup` 已被 TanStack Query 覆盖；关键是 `staleTime`/`retry` 按数据域设定，不要全站一个值。

## 4. 消融与验证

- 每个迁移切片配一条消融：删掉新加的守卫（批量选择计数、确认弹窗、写目标提示、URL 状态守卫）必须让测试转红。
- 内容管理已有守卫：URL 真源（本轮 `content-management.test.ts`）、导航可达性、门面导出完整性（本轮两个 `regression/` 文件）。
- 合并门禁：`pnpm --filter @soymutdb/admin lint typecheck test` + `python3 -m pytest scripts -q` + `node scripts/check_visible_i18n_react.mjs`（必须 exit 0）+ 双站制品隔离。

## 5. 本轮不做（明确边界）

- 不改后端契约；不引入第二个权威存储；不为迁移顺带重构 import/release 域。
- 不把 `/widgets`、`/page-builder`、`/layout` 重新做出来（ADR-0009 有意退役，本文只在导航可达性测试里登记它们属于有意退役）。
- 不把 `AdminHeader` 换成 ProLayout 默认头（承载实例上下文，属产品决策）。
- 不宣称已验证：截图视觉验收、Admin save→公共渲染 E2E、响应式运行时检查都需要可写隔离环境（见 `docs/3.9升级优化文档.md` §11.13）。