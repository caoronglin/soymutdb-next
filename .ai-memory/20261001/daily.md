# 2026-10-01 工作日志

## [20:0x] 定稿: 「真实情况」核对 —— 6 处契约漂移，全部修复并复跑

- **背景**: 用户要求提交仓库并「整理记录项目真实情况」。此前工作树里有 436 项未提交改动（Vue 完全退役 + React 重写 + API 新端点），
  多份状态文档与代码已经不一致（`docs/dev/project-status.md` 还写着「三端均为 Vue 3」）。
- **做法**: 不采信任何文档的自述，全部实跑复核；每一处「文档说 A、代码是 B」都以代码 + 命令输出为准。
- **修掉的 6 处真实漂移**（详见 `docs/dev/project-status.md` 表格）:
  1. `apps/api/tests/test_expression.py` —— `/expression/*` 已按 release fail-closed 返回 503，测试仍断言旧的 200 空列表 → 6 failed。
     注入 `get_release_context`；另 3 处旧断言改为当前公开契约（`/libraries/{public_id}`、内部主键不再是 locator、cursor 为不透明签名串）→ **19 passed**。
  2. `apps/api/tests/test_gwas_api.py` —— 路由新增 `response: Response`，测试漏传 → 1 failed → **18 passed**。
  3. `apps/api/tests/conftest.py` —— 本地复用的测试库在会话被强杀后残留角色行，后续每个会话 setup 都报 `roles_name_key`；
     读起来像代码缺陷，其实是被污染的环境。角色种子改 `on_conflict_do_nothing`。
  4. `apps/api/tests/test_ablation_sra_no_fabrication.py` —— 3 个消融用例漏挂 `offline` fixture，实际去访问 NCBI；
     **网络通的时候守卫失败、断网的时候守卫通过**，即一个「只在断网时才生效」的消融不是消融。补 fixture → **11 passed**。
  5. `packages/query-keys` —— 联邦搜索已永久下线、`federated` 已从缓存键移除，测试仍断言该维度。
  6. `packages/charts` —— 图表回退分支没把 description 暴露给辅助技术，测试却断言回退态根本不渲染的 `role="img"`。
- **验证**: web 20 files/99 tests · admin 6 files/41 tests · api-client 27/150 · jbrowse 40 · genome-view 43 · genome-data 121 ·
  genome-view-model 23 · shared 49 · charts 5 · query-keys 11 · i18n-core 10 · `pytest scripts -q` 275 passed/1 skipped ·
  API 消融 16 files **149 passed / 0 failed** · admin lint + typecheck exit 0。
- **未验证 / 阻碍（必须说清楚）**: API 全量 pytest 在本机约 47% 处被 OOM kill（EXIT=137），**没有可信的全量数字**；
  `apps/worker` 本机 `multiprocessing` spawn 失败，未取得数字；本机无 Docker，testcontainers 用例 SKIPPED/ERROR。

## [20:3x] 管理后台: 按官方 Pro sub-page 实例写迁移设计 + 计划

- **官方实例核对**: 拉取 `ant-design-pro` `src/pages/table-list/index.tsx`（线上预览 `/admin/sub-page`）源码逐行读。
  目标模板 = `PageContainer` + `ProTable`(`actionRef`/`request`) + `ProColumns`(`valueType`/`valueEnum`/`hideInForm`) +
  `rowSelection` + `FooterToolbar` + `ProDescriptions`(`Drawer`) + `ModalForm` + `useMutation`/`invalidateQueries` + `message.useMessage`。
- **antd CLI 三个有用的结论**（`@ant-design/cli@6.6.5`，需 `HOME` 可写）:
  - `antd lint apps/{web,admin}/src` → 152 / 112 文件**无问题**。
  - `antd usage` 对本仓报「No antd imports found」—— **它不解析 `@/lib/antd` 门面层**，这是真实盲区，必须由仓内静态守卫补。
  - `antd doctor` 报 `antd is not installed in node_modules` —— antd 只存在于 workspace 包，不在根，属工具误判，不是依赖缺失。
  - `antd info Table` → `pagination: object | false`，**没有 cursor/keyset**。这条直接决定迁移约束：
    凡 keyset 分页的列表必须 `pagination={false}` + 自带控件，**不得**为了套用 ProTable 默认分页而退回 offset 分页。
- **产出**:
  - `docs/superpowers/specs/2026-10-01-admin-pro-migration-design.md`（设计，含现状实测表与 4 条硬约束）
  - `docs/aegis/plans/2026-10-01-admin-pro-migration.md`（A1–A6 切片 + 门禁 + 暂停条件）
  - 登记进 `docs/aegis/INDEX.md`
- **纠正旧计划的口径**（重要）: `2026-09-27-react-pro-v6-replatform.md` 与 `docs/3.9升级优化文档.md` 都说
  「11 个页面用裸 antd `Table`、ProTable 直用 0 处」。实跑 grep 的真实情况是：**4 个页面已在 ProTable 适配器上
  （`components/data-table.tsx` 内有 `ProTable` + `ProColumns`），6 个仍是裸 `Table`**。
  即「ProTable 0 处」这个数字是错的，缺口比记录的少一半但性质更清楚（适配器已存在，缺的是把剩余 6 页接上去 + 详情）。

## [20:5x] 功能测试与消融测试（管理端）

- **内容管理功能测试** `apps/admin/src/routes/content/content-management.test.ts`（12 例）:
  锁「URL 为真源」——`page` 非正安全整数一律回落 1、未知 `status` 回落 `all`、`category` 去空白、
  序列化只写偏离默认的维度、序列化↔解析往返不丢不增、列表/详情缓存键互不串。
  顺带抓到一个真实 API 语义差异：`contentKeys.pageVersions` 返回普通数组（没有 `.startsWith`），
  写断言时按数组处理，不改实现。
- **导航可达性消融** `apps/admin/src/regression/nav-reachability.test.ts`（5 例）:
  Vue 退役时删掉的 `nav-reachability.test.ts` 按官方实例的导航纪律恢复。首次运行**真的报出 10 条未入侧栏的路由**，
  逐条判定后分类：`/page-builder`、`/widgets`、`/widget-preview`、`/widget-health`、`/layout` 属 ADR-0009 有意退役；
  `/settings/{advanced,appearance,integrations,localization,security}` 是 `/settings` 的标签页（祖先可达）；
  `/imports/new`、`/news/new`、`/news/trash` 等是列表页的子入口。判定规则因此从「逐条列举」改成
  「侧栏里有 + 详情参数路由豁免 + 有可达祖先豁免 + 有意退役白名单」，并加合成消融：抽掉 `/media` 必须转红。
- **门面导出完整性消融** `apps/admin/src/regression/antd-facade-exports.test.ts`（5 例）:
  静态扫描 `src/**` 对 `@/lib/antd` 的具名导入，与门面导出集合求差；断言 admin 无绕过门面的 `antd`/`pro-components` 直引；
  断言迁移前提组件（`PageContainer`/`ProTable`/`ProDescriptions`/`ProCard`/`ModalForm`/`StatisticCard`）确实导出了；
  合成消融：删掉使用最广的那个符号，所有使用方都必须被报出。
  依据是真实历史故障：一个 mock 声明 `modelValue` 而 antd v6 只有 `value`，把「全局搜索框打字没反应」的 P0 放过了；
  另一个 mock 缺 `Flex` 导出，红了整整一轮才被发现。
- **API 消融**: 16 个文件 **149 passed / 0 failed**（含修好的 SRA 3 例）。
- **admin 单测**: 3 files / 19 tests → **6 files / 41 tests**。

## 仍未完成 / 归属

- 可见文案守卫 `check_visible_i18n_react.mjs` **exit 1，39 个文件**（迁移计划 A5）。
- 6 个页面迁 ProTable、详情改 `ProDescriptions`、`menuItemRender` 改 `<Link>`（迁移计划 A1–A3）。
- API 全量数字缺失：需要分片跑法并写进 `scripts/verify-backend-tests.sh`。
- `Makefile:197` lint 目标指向不存在的 `apps/api/src`；`AGENTS.md` 的 pnpm pin 写成 11.21.0（实际 12.5.1）。
- Vue 退役后仍缺契约覆盖：admin 会话（`lib/auth-context.tsx`）、web 动效可访问性（`lib/motion-*.ts`）。
## [21:3x] 修: check-vue-retirement 守卫把「重建为 React 的 genome-view」误判为退役

- **症状**: 提交前最终复核发现 `node scripts/check-vue-retirement.mjs` → FAIL(5)，首条即
  `apps/web/package.json: dependencies.@soymutdb/genome-view`。
- **真因**: 守卫的 denylist 硬编码了 `packages/ui-vue` 与 `packages/genome-view` 两个包名。那是 14:35「Vue 完全退役」
  那一刻的事实；随后 00:41 按设计把 `genome-view` **重建为 React 渲染器**（纯函数 `renderGenomeViewSvg` +
  React 组件 + 43 个测试），`apps/web` 也确实在用它。
  也就是说：守卫按**包名**判定，而现实按**框架**判定。9-29 的日志写「check-vue-retirement PASS」时是真的，
  但 genome-view 重建之后没人再跑它，所以红线一直挂到今天。
- **修法**: 从 denylist 与「退役包残留」清单里移除 `genome-view`，**保留** `.vue` 文件扫描与
  `@soymutdb/**` / `vue` / `@vue/*` import 扫描 —— 这些扫描本来就走 `packages` 目录，因此重建后的包若重新引入
  Vue 组件或 Vue import 仍会被拦。注释里写清楚为什么这个包名被特意排除。
- **消融验证**: 在临时副本里放一个 `apps/web/src/VueProbe.vue` → 守卫 exit 1 并精确报出该文件；
  正式目录跑 → PASS exit 0；`pytest scripts -q` 275 passed/1 skipped 不受影响。

## [21:5x] 同一类缺陷的第二处: check-react-entry-graph 同样按包名判 Vue

- `node scripts/check-react-entry-graph.mjs` → **FAIL**（web），报 3 处 `imports @soymutdb/genome-view`
  （`routes/genome-view.tsx`、`lib/locus-structure.ts`、`components/gene-genome-view.tsx`）。
- 与前一条**同源**：`scripts/react-entry-graph.mjs` 的 `FORBIDDEN_VUE_PACKAGES` 里也硬编码了
  `@soymutdb/genome-view`。包重建为 React 之后，两个守卫同时变红，而 9-29 的收尾日志记录的是「双双 PASS」——
  那是重建之前的事实，重建之后没人再跑。
- **修法**: 从 `FORBIDDEN_VUE_PACKAGES` 移除该包名，保留 `.vue` 文件规则（它照旧覆盖 `packages/**`，
  因此包内若重新出现 Vue 组件仍会被拦）。
- **消融验证**: 临时副本里把一个 `VueProbe.vue` 接进 `umi-entry.tsx` 的 import 闭包 → 守卫 exit 1 并精确指出
  `apps/web/src/components/probe-importer.ts imports ./VueProbe.vue`；正式目录 → 三端 PASS / exit 0；
  `pytest scripts/test_platform_delivery_contracts.py scripts/test_ci_job_contracts.py -q` 97 passed。
- **教训（写给下一个人）**: 守卫的判据必须落在**属性**上（是否 .vue、是否 import vue），
  不能落在**名字**上；一旦某个包被重建，名字型判据会静默变成红灯，而没人再跑它时就是长期红线。
