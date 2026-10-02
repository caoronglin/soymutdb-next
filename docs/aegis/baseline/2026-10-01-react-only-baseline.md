# SoyMutDB 基线 — 2026-10-01（React-only 收口后）

- 日期：`2026-10-01`
- 状态：**current**（取代 `2026-09-28-initial-baseline.md`，后者保留为历史快照）
- 治理依据：`docs/aegis/BASELINE-GOVERNANCE.md` §1 双基线角色、§5 基线检查协议、§6 七维架构复审
- 本快照的性质：**证据 + 现行判据**。它不自行授权行为；单项契约仍以对应 spec/plan 为准。
- 本版与 2026-09-28 版的差异集中在四件事：Vue 退役完成、`genome-view` 以 React 重建、
  联邦搜索永久下线、管理后台 Pro 业务组件体系仍未落地。

## 0. 怎么用这份基线（3 步）

1. 改动前读 §1 产品/需求基线与 §2 架构/运行时边界基线；
2. 把手上的工作逐条对照 §1.4 的需求项与 §2 的所有权/契约表；
3. 用 §5 的报告格式给结论（`aligned` / `Design Defect` / `Implementation Drift` / `missing-authority` /
   `needs-clarification`，并标 `scope: requirements | architecture | both`），改完再用 §6 的七维过一遍。

§3 是命令与今日实测值，用来判断「这条需求现在是否真的成立」；§4 是尚未确认、**不许自行拍板**的项。

## 1. 产品 / 需求基线

### 1.1 确认的需求来源

| 来源 | 覆盖范围 |
| --- | --- |
| `AGENTS.md` | 仓库级产品与交付约束（身份、assembly、双站、缓存、发布、流水线） |
| `docs/dev/database-core-contract.md` | 生物信息学核心契约与测试矩阵（规范性） |
| `docs/superpowers/specs/2026-08-14-public-web-layout-alignment-design.md` | 门户信息架构、搜索工具页、结果列顺序（2026-09-29 修订） |
| `docs/superpowers/specs/2026-09-27-react-pro-v6-replatform-design.md` | 前端统一到 React 19 + Umi Max + antd 6 + ProComponents v3 |
| `docs/superpowers/specs/2026-09-28-admin-editable-footer-search-font-design.md` | 页脚可编辑、搜索控件、字体与性能门禁 |
| `docs/superpowers/specs/2026-10-01-admin-pro-migration-design.md` | 管理后台对齐官方 `ant-design-pro` sub-page 实例 |
| `.ai-memory/project_memory.md` | 已落库的实现记录与决策（含「生产保留 PostgreSQL」） |
| 用户指令（2026-09-29） | 「去除 Vue 技术路线」「做好基因 ID 与物理位置两项查询」 |

### 1.2 目标状态（用户可见）

1. **SoyMutDB 是数据库产品**：进入任何页面都能看到标识符搜索、可筛选分页的结果集、实体详情页、稳定链接，
   以及 assembly / release / provenance 上下文。营销或编辑性内容可以支撑这些流程，但不得取代它们。
2. **公共门户**：首页模块顺序固定为 Gene ID / Physical Location / JBrowse 2 / BLAST / Primer Design（前两项为主入口）；
   五个工具页各自独立渲染标题、表单与结果表，不继承门户 hero 与全局搜索框。
3. **管理后台**：功能页统一到 `PageContainer` + `ProTable`/`ProDescriptions`/`ModalForm` 外壳；
   内容管理（页面、新闻、文献、媒体、预览测试数据）具备可审计的写入闭环。
4. **交付可判定**：双站制品隔离、CSP/Service Worker/base、发布原子性与回滚在真实环境可复跑，而不是「脚本已写」。

### 1.3 用户与场景

| 角色 | 场景 | 基线要求 |
| --- | --- | --- |
| 研究者 | 按基因登录号或物理区间查找基因/变异，并跳到区间视图 | 检索必须带 assembly 作用域；坐标非法要显式拒绝，不能静默取默认版本 |
| 运营 | 编辑门户页面、新闻、文献、媒体与页脚 | 每次写入要知道写到了哪个实例、哪个站点变体；双语同屏校验；删除被引用资源要阻断并说明原因 |
| 数据管理员 | 导入数据集、发布 release、回滚 | 状态机由服务端校验；未全 ready 不发布；发布是单一权威指针切换 |
| 内部审核员 | 用内部标识符检索、查看未发布记录 | 必须由 API 服务端授权；匿名查询不得泄露存在性 |

### 1.4 需求项与验收判据

> 每条都给出可执行判据。「今天成立吗」一列是 2026-10-01 实跑结论。

| # | 需求 | 验收判据（可执行） | 今天成立吗 |
| --- | --- | --- | --- |
| R-01 | 突变体有稳定 `public_id` 与私有 `internal_id`，不得互相推导 | `pytest tests/test_ablation_identity_public_boundary.py`；外部 URL 只认 public_id | ✅（消融 149 passed） |
| R-02 | 匿名以内部标识符查询不得泄露存在性 | 内部检索匿名 401 / 低权 403，响应 `private, no-store` | ✅ |
| R-03 | v4/v5 是独立命名空间，跨版本等价只能来自带 provenance 的 crosswalk | 无 assembly 查询按 assembly 分组或判歧义；`similar genes without crosswalk` 保持无关 | ✅ |
| R-04 | 深链 assembly 不可判定时不回退默认版本 | `apps/web/src/lib/search-assembly.test.ts`、`routes/search/tool-pages.test.tsx` | ✅ |
| R-05 | 坐标必须是安全整数 | 同上，`NaN`/非整数直接拒绝 | ✅ |
| R-06 | external/internal 是显式构建与部署边界 | `scripts/check-site-variant-artifacts` 系列 + external 泄漏负例 | ✅ |
| R-07 | 结果视图以查询参数为唯一真源 | admin `routes/content/content-management.test.ts` | ✅（本轮新增） |
| R-08 | 管理后台每条路由都能从侧栏到达 | `apps/admin/src/regression/nav-reachability.test.ts` | ✅（本轮新增；Vue 退役时曾丢失） |
| R-09 | antd 门面必须导出被使用的符号 | `apps/admin/src/regression/antd-facade-exports.test.ts` | ✅（本轮新增，补 CLI 盲区） |
| R-10 | 三端为 React，Vue 残留为 0 | `check-vue-retirement.mjs` + `check-react-entry-graph.mjs` | ✅（两守卫今日修正后才真绿） |
| R-11 | 管理后台 Pro 业务组件体系落地 | ProTable 覆盖全部列表页；`ProDescriptions` 用于详情 | ❌ 6 页仍裸 `Table`，`ProDescriptions` 0 处 |
| R-12 | 可见文案不得硬编码 | `node scripts/check_visible_i18n_react.mjs` exit 0 | ❌ exit 1，39 个文件 |
| R-13 | 页脚可编辑、链接目的地服务端校验 | footer API + Admin 编辑器 + 公共渲染 | ❌ Task 1 部分完成，编辑器未做 |
| R-14 | 交付门禁在真实环境可判定 | 双站制品、CSP/SW/base、发布回滚实跑 | ❌ 本机无 Docker/Kind，SKIPPED ≠ PASS |
| R-15 | 公开/内部 × public/internal 标识 × v4/v5 矩阵有**非 skip** 证据 | 15 个 testcontainers 用例需 Docker | ⚠️ 本机 SKIPPED/ERROR |

### 1.5 非目标

- 不重做后端权威数据模型或 API 业务语义；不改数据库权限、发布、assembly、缓存契约。
- 不引入第二个权威存储（不用 SQLite 走完整开发路径）。
- 不上传可执行 JS / 任意模板 / 未净化 HTML；不做多目标同时发布。
- 不重新实现 `/widgets`、`/page-builder`、`/layout`（ADR-0009 有意退役）。
- 不为套用组件默认行为而改分页语义或公开身份字段。

### 1.6 工作流约束

- `.cnb.yml` 是交付单一事实来源；GitHub workflow 只镜像，job body 只调 `scripts/`。
- Node/pnpm/Python/uv 的 pin 必须一致，不得静默修改。
- 公开边界改动必须有负向泄漏测试（响应体、URL、客户端可见日志、`dist/external`）。
- 隐私/身份/assembly 隔离场景不得以 skip/xfail 过门禁；`SKIPPED` 必须写原因且不计入通过。
- 文档与代码冲突时**先修文档或先修代码，不得让文档单方面描述未发生的事**（本基线多次因文档滞后而重写）。

## 2. 架构 / 运行时边界基线

### 2.1 规范所有者与契约

| 关注点 | 规范所有者 | 契约载体 | 依赖方向 |
| --- | --- | --- | --- |
| 身份、release、assembly、权限、工作流状态、审计 | PostgreSQL | `docs/dev/database-core-contract.md` + Alembic 迁移 | 应用 → PG（权威） |
| 变异等批量事实 | ClickHouse（可重建分析投影） | `infra/clickhouse/*.sql` + schema 契约测试 | 只能由投影读取，不签发公开身份 |
| 对象 | MinIO（默认私有） | 预签名会话 | 大文件不经 API 内存 |
| 缓存 / 队列 | Redis（可丢弃） | 缓存键必须含 site variant / release / assembly / query / filters | — |
| 门户页面与内容呈现 | `apps/web/src/routes/**` | 门户 IA 与搜索工具页 spec | → api-client / 共享包 |
| 管理后台功能页 | `apps/admin/src/routes/**` | `2026-10-01-admin-pro-migration-design.md` | → api-client / `@/lib/antd` 门面 |
| 共享文案资源 | `packages/i18n-core` | zh/en 对等 | 被两端消费，不反向 |
| 图表 / 基因组渲染 | `packages/charts`、`packages/genome-view`（React 渲染器） | 纯函数 `renderGenomeViewSvg()` | 数据层不依赖框架 |
| JBrowse 集成 | `apps/jbrowse` + iframe 桥 | postMessage 白名单、origin/version 校验、ready 握手 | 单向向下 |
| 验证门禁 | `scripts/**` + `e2e/tests` | `smoke.sh` 各 profile | 不引入运行时依赖 |

### 2.2 架构不可协商项

1. 三端共用 React/antd/ProComponents 与共享锁文件；共享包分层为 `ui-react` 门面 / `charts` 图表门面 / 领域包保持框架无关。
2. 不为每个 antd 控件再造包装层；组件一律经 `@/lib/antd` 门面导入（`regression/antd-facade-exports.test.ts` 强制）。
3. external/internal 制品、origin、CORS、SW 命名空间、hashed assets 不得复用；`noindex` 不是访问控制。
4. 静态页内嵌 release ID，水合请求携带它，避免静默查询到别的数据集。
5. 凭据只在服务端环境或 secret manager；页面定义与 TSV 不能提供。
6. 守卫的判据必须落在**属性**上（如「是否 `.vue`」「是否 import `vue`」），不能落在**包名**上——
   包被重建后名字型判据会静默变红而无人察觉（2026-10-01 两个守卫的真实教训）。

### 2.3 兼容性边界

保持不变：既有路由与查询参数、API 契约与响应形状、鉴权门禁、站点变体边界、搜索行为、keyset 分页语义、
canonical 生物学取值与 provenance。允许的变更：**加法式**契约扩展（新字段、新可选参数），
且必须同步重生成 OpenAPI 客户端并跑 `check:contract`。

### 2.4 运行时就绪边界（runtime-ready）

| 面 | 状态 | 依据 |
| --- | --- | --- |
| 三端 typecheck + 单测 | ✅ | 本日实跑 |
| 交付/平台契约 | ✅ 275 passed / 1 skipped | `pytest scripts -q` |
| 消融（API） | ✅ 149 passed | `tests/test_ablation_*.py` |
| 双站制品隔离 | ⛔ 本机无 Docker/Kind，未在真实流水线实跑 | SKIPPED |
| 发布 / 回滚 | ⛔ 未实跑 | 需要真实环境 |
| 响应式与视觉验收 | ⛔ 需可写隔离预览环境 | 见 `docs/3.9升级优化文档.md` §11.13 |

### 2.5 退役状态

| 对象 | 状态 | 判据 |
| --- | --- | --- |
| Vue 运行时与全部 `.vue` | ✅ 已退役 | `check-vue-retirement.mjs` PASS |
| `packages/ui-vue` | ✅ 已退役 | 包不存在 |
| 联邦搜索（API `app/search/` + 前端开关 + `federated` 缓存维度） | ✅ 已永久下线 | 端点与类型消失 |
| `packages/genome-view`（Vue 版） | ✅ 已退役；同名包已重建为 React 渲染器 | 43 tests + `check-vue-retirement` PASS |
| Page Builder / Widgets / Layout（ADR-0009） | ⛸ 有意退役，路由指向明确「未恢复」页 | 导航可达性测试登记为有意退役 |

## 3. 今日实测值（判断需求是否真的成立）

```
export GOMAXPROCS=1 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=1   # 本机 cgroup 受限，缺这三个会线程耗尽
apps/web          20 files / 99 tests · typecheck exit 0
apps/admin         6 files / 41 tests · typecheck exit 0 · lint exit 0
apps/jbrowse      40 pass · typecheck exit 0
packages          api-client 27/150 · genome-view 5/43 · genome-data 14/121 · genome-view-model 2/23
                  shared 4/49 · charts 1/5 · query-keys 1/11 · i18n-core 1/10
pytest scripts -q 275 passed / 1 skipped
API 消融           16 files / 149 passed / 0 failed
API 全量            ⛔ 本机 OOM kill（EXIT=137 @ ~47%），无可信全量数字
check-visible-i18n  ⛔ exit 1（39 个文件）
antd CLI            lint web 152 / admin 112 文件无问题；usage 因门面层报「No antd imports found」
                    doctor 误报 antd 未安装（antd 只在 workspace 包）；info Table → pagination: object | false
```

## 4. 尚未确认（**不许自行拍板**）

产品/业务口径：`public_id` 正式格式与历史保留策略 · internal 检索角色名单与审计保留期 ·
无 assembly 查询的 UX（多版本分组 or 先要求选版本）· v4↔v5 映射展示规则与真实数据来源 ·
生产对象存储选择与第二物种最小数据集 · RPO/RTO 与容量上限 · 主导航口径 ·
Gene ID 单行 vs 批量 · Physical Location 单框 vs 四控件 · 页脚导航初始 bounds ·
字体性能门禁不达标时是否调整策略 · `analyses` 队列补 worker 还是下线 ·
`_headers` 转 gh-pages 语义还是删除。

## 5. 基线检查报告（2026-10-01，治理 §5 格式）

| 判定 | scope | 内容 | 归属 |
| --- | --- | --- | --- |
| Implementation Drift | both | 旧计划/整合文档记录「11 页裸 antd `Table`、ProTable 直用 0 处」，实跑为 4 页已在 ProTable 适配器上、6 页仍裸 | 已在本轮更正（计划与整合文档） |
| Implementation Drift | architecture | 两个 Vue 守卫按包名判定，与「`genome-view` 已重建为 React」冲突，自重建起长期为红 | 已修（`check-vue-retirement.mjs`、`react-entry-graph.mjs`） |
| Implementation Drift | architecture | API mock 测试未跟上 release fail-closed：`test_expression` 6 failed、`test_gwas_api` 1 failed | 已修（并按公开契约改断言） |
| Design Defect | architecture | `test_ablation_sra_no_fabrication` 漏挂 `offline` fixture → 实际联网，「只在断网时才生效的消融」 | 已修 |
| missing-authority | requirements | 页脚可编辑（Task 2–5）与 Pro 组件体系落地缺 Task 级完成自述，文档状态落后于代码 | 待补（本文件已给出 R-11/R-13 判据） |
| needs-clarification | requirements | §4 全部产品口径；其中 3 项直接决定 R-11/R-13 的验收写法 | 待用户拍板 |
| Aligned | both | R-01…R-10 全部成立并有可执行判据；交付契约 275、消融 149、三端 typecheck 与单测全绿 | — |

## 6. 七维架构复审（2026-10-01）

1. **所有权完整性**：每个关注点有且仅一个规范所有者（§2.1）；`@/lib/antd` 门面的存在消除了「组件从哪来」的二义。
2. **模块边界**：共享层不含框架耦合；`genome-data`/`genome-view-model` 不依赖 React/Vue。
3. **契约变更**：本轮 API 变更为加法式（`region-structure`、footer content、0045 迁移）；联邦删除为**减法**，
   已同步客户端与 OpenAPI，属已批准的退役。
4. **级联膨胀**：无新增级联依赖；`genome-view` 的 React 重建复用了纯函数渲染器，静态与交互共用一份实现。
5. **依赖方向**：应用 → 共享包 → 数据层，单向；`genome-data` 不依赖任何框架。
6. **退役完整性**：Vue 与联邦搜索退役干净；`genome-view` 的 Vue 版已删、同名 React 版是重建而非残留。
7. **熵流**：净复杂度下降 —— 删除 106 个 `.vue` 与 `packages/ui-vue`；新增复杂度集中在 3 个小守卫文件与 2 份文档。

## 7. 变更记录

| 日期 | 变更 | 触发 |
| --- | --- | --- |
| 2026-09-28 | 建立初版双基线快照 | Aegis 工作区初始化 |
| 2026-10-01 | 本版取代初版：改为 React-only 收口后的现状；新增 §1.4 可执行判据、§2.4 运行时就绪边界、§3 实测值、§5 检查报告、§6 七维复审 | 用户指令「提交基线，整理成可用文档」；本日 8 处真实缺陷修复后的实测状态 |