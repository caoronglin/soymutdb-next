# React + Ant Design Pro v6 全线迁移与 UI 重构设计

**状态**：设计已获用户确认，实施中；完整消融门禁未通过/受阻，用户明确授权继续
**日期**：2026-09-27

## Proposal

- **Intent**：终止 SoyMutDB 前端 Vue 技术线，以迁移前 React 版本为基线，用 Ant Design Pro v6 统一重建三个前端，并在保留数据库产品契约的前提下优化整站 UI。
- **受益用户**：公共站研究者、SoyMutDB 管理员、通过 JBrowse 查看基因组数据的用户。
- **Scope**：`apps/web`、`apps/admin`、`apps/jbrowse`；Vue 组件层、组件/图表/基因组视图包、依赖与交付构建；迁移前 React 的活跃页面/行为以及当前 Vue 功能矩阵中仍使用的新增能力；UI/响应式/无障碍改进；用户要求的消融实验。
- **Out of scope**：不重做后端权威数据模型或 API 业务语义；不更改数据库权限、发布、assembly 或缓存契约；不整体清除/回滚当前未提交改动；已有 ADR 明确退役的旧能力默认仍退役。
- **Approach**：复用迁移前 React 基线，采用 `@umijs/max` 4（Umi Max）、React 19、antd 6、`@ant-design/pro-components` v3，建立共享 React 组件门面，按应用分批重建并最终一次性关闭 Vue 生产路径。

## 已核实基线与约束

- 公共站 React 基线：`d3904c210`；管理端 React 基线：`2004c25c6`；JBrowse React 壳的 Vue 切换前版本：`ffc4e7e1c`。
- 当前工作区已有 **156 个已修改文件、72 个未跟踪文件**。开始实现前必须保存清单并按前端/后端/交付/测试/文档分类；非前端改动保留。不得以 `git reset`、全仓 checkout 或删除未知文件的方式恢复基线。
- 当前产品契约要求数据库优先体验、明确 `public_id`/`internal_id`、assembly/release/provenance、external/internal 双站隔离。UI 迁移不得弱化这些约束。
- Umi Max 静态导出、双站构建、子路径、CSP、Service Worker 的适配尚未在本仓验证，列为前置技术门禁。
- 工具链以 `.nvmrc`、`.cnb.yml` 和 `scripts/test_ci_job_contracts.py` 的交付合同为准。已观察到 Agent 指引与根 `package.json` 对 pnpm 版本存在漂移，Gate 0 先记录并按正式仓库合同核实，禁止静默改 pin。

## Architecture Decisions

### Decision 1：采用完整 Ant Design Pro v6 栈

- **选择**：React 19 + Umi Max 4 + antd 6 + ProComponents v3；使用官方 Ant Design CLI 做组件 API、废弃 API 和项目配置检查。
- **理由**：用户明确选择完整 Pro v6，而非只引入组件库。Pro v6 发布说明确认其基于 React 19、antd 6、Umi Max 4 和 ProComponents v3。
- **替代方案**：在现有 Vite 上仅换 React/antd/ProComponents。该方案改动小，但不符合用户选定的完整 Pro v6 框架。
- **代价**：路由、构建、测试和静态导出配置均需迁移；Pro v6 的脚手架默认配置不能未经核验直接覆盖本仓 CI、子路径和双站策略。
- **撤销条件**：若 Umi Max 静态导出无法通过外部/内部制品隔离、子路径/CSP/SW 验收，暂停其余应用迁移并向用户报告，不自动退回 Vite。

### Decision 2：保留 Monorepo、后端契约与静态交付边界

- pnpm/Turbo、CNB 主流水线、GitHub 镜像规则、OpenAPI/client、API、PostgreSQL/ClickHouse/对象存储职责不因 UI 框架变化而重做。
- 公共站继续分别构建 external 与 internal 制品；任何 internal 数据不得进入 external HTML、JS、JSON、manifest、source map 或 Service Worker。
- Umi Max `exportStatic` 作为静态导出候选，在 Gate 0/1 做最小验证。输出目录与现有发布流程的映射必须实测后再确定。

### Decision 3：共享组件包与领域包分层

- `packages/ui-vue` 改为 React 共享 UI 门面（目标名 `packages/ui-react`，实施前检查 workspace/import 命名冲突）。负责共享主题/ConfigProvider、通用布局与有明确复用价值的控件。
- `packages/charts` 改为 React 图表门面，集中图表实现与依赖；具体图表依赖需经许可证、维护状态、漏洞和包体积审查。
- `packages/genome-view` 改为 React 视图层；`packages/genome-data` 与 `packages/genome-view-model` 保持框架无关并复用，JBrowse 轨道继续使用领域专用 SVG/Canvas，不强行用普通后台表格组件替代。
- 应用层通过这些共享包复用新增 UI 行为；不为每个 antd 控件再造无业务价值的包装层。

### Decision 4：功能基线与退役边界

- 逐项映射历史 React 路由和当前功能矩阵。迁移前 React 的活跃功能与 Vue 阶段新增且当前仍使用的能力均需在 React 中实现并覆盖测试。
- 保留 stable URL、深链、redirect 和双站路由策略。ADR 明确退役的 Page Builder/Widgets 等能力默认保持退役，不因为恢复历史 React 文件而复活。
- 后端/API 当前未提交改动不作全局回滚；需要前端消费的新字段继续走 OpenAPI/client 契约。

## UI 设计方向

### 信息架构

- **公共站**：研究者任务优先。首页突出标识符搜索、实体入口和真实数据库结果；列表强调筛选、分页和可追溯字段；详情明确 public ID、assembly、release、来源和关联入口。避免把研究数据库重做成营销落地页。
- **管理端**：使用 ProLayout 等符合管理任务的布局；列表、编辑、导入/发布/审计流程按真实 API 状态组织，表单有校验、提交锁、错误/成功反馈。
- **JBrowse**：Ant Design 用于应用外壳、搜索/筛选/设置等常规控件；基因组轨道、坐标和深链使用 React 领域组件。

### 组件与视觉规范

- 以 antd 6 Design Tokens 和 ProComponents v3 为共同基准，建立共享主题和语义 token；默认沿用项目科学数据库的清晰、中性、可读方向，避免模板化渐变与装饰。保留既有可用的主题能力，主题差异通过 token 管理。
- 参考用户授权使用的图表 Sketch 套件、Pro 通用业务模板 Sketch 套件与 Ant Design Landing 模板资源；只借鉴信息层级、组件和布局，不把 Sketch 二进制放进应用运行时或生产制品，也不逐页照搬旧模板。
- Ant Design CLI 的 `doctor`、`lint`、组件 API/示例查询通过仓库脚本使用；CNB/GitHub workflow 不新增内联构建逻辑。
- 响应式验收视口：375、768、1024、1440 px；无横向溢出，关键触控目标至少 44 px，键盘焦点可见，表单和异步组件具备 loading/empty/error/success/disabled 状态，尊重 `prefers-reduced-motion`。中英文现有本地化需保持完整。

## Requirements 与 Scenarios

### R1：统一 React/Pro v6 运行栈

三个应用 SHALL 使用 React + Umi Max，并通过共享锁文件安装兼容的 React、antd、ProComponents 与 Umi Max 版本。

**Scenario：所有应用按锁文件构建**
- GIVEN 干净安装环境和已审阅的 pnpm-lock.yaml
- WHEN 执行冻结安装、类型检查和各应用构建
- THEN web、admin、JBrowse 均完成 React/Umi 构建
- AND 不加载 Vue runtime 或 Vue 插件

### R2：静态站点与双站安全边界

公共站 SHALL 可静态导出 external/internal 两套分离制品，且保留既有部署 base、路由深链、CSP 与 SW 行为。

**Scenario：external 制品不含 internal 哨兵**
- GIVEN 合成 internal-only 数据和唯一泄漏哨兵
- WHEN 分别构建两个 site variant 并扫描完整制品目录
- THEN internal 功能仅在授权 internal 路径可见
- AND external 制品、URL 与客户端可见日志中无 internal ID、未发布记录或哨兵

### R3：数据库核心身份、assembly 与 release 语义

React UI SHALL 保留 `public_id` 与 `internal_id` 的受众边界，并让搜索结果/详情/深链携带适用的 assembly、release 和来源信息。

**Scenario：匿名外部用户输入 internal ID**
- GIVEN internal ID 对应真实记录
- WHEN 未认证用户在 external 搜索并打开可见页面
- THEN UI/API 不泄露记录存在性
- AND URL、响应、客户端日志和 external 制品无 internal ID

**Scenario：v4/v5 歧义检索**
- GIVEN 两个 assembly 对同一查询均有命中
- WHEN 用户未选择 assembly
- THEN 界面逐 assembly 标注结果或要求 disambiguation，不静默合并
- AND 选择后的详情/JBrowse 深链保留对应 assembly 与 release

### R4：历史及现有活跃功能延续

迁移 SHALL 提供路由/行为矩阵；每个活跃功能有 React 页面或明确 redirect/unavailable 状态，不得出现无说明空白路由。

**Scenario：访问旧深链**
- GIVEN 用户持有 React 基线或当前 Vue 活跃路由的稳定 URL
- WHEN 直接打开或刷新该 URL
- THEN React 应用呈现对应页面，或执行已定义的兼容 redirect/unavailable 响应
- AND 登录、筛选、分页和 assembly 上下文符合原契约

### R5：共享组件一致性与 UI 可用性

三个应用 SHALL 使用 React 共享 UI 与统一设计 token；新增功能 SHALL 复用经过验证的 antd/ProComponents 包，而非复制独立 Vue 实现。

**Scenario：跨应用一致交互**
- GIVEN 使用同类表单、列表或通知组件的页面
- WHEN 用户以键盘/触屏操作并触发 loading、empty、error、success 状态
- THEN 控件主题、焦点、错误语义和交互反馈保持一致
- AND 在 375/768/1024/1440 px 无截断或横向滚动

### R6：JBrowse bridge 与数据视图

React JBrowse SHALL 保持已有 postMessage 白名单、origin/version 校验、ready 握手、深链和 assembly/locus 语义。

**Scenario：从基因详情打开 JBrowse**
- GIVEN 带 assembly 与 release 上下文的基因详情
- WHEN 用户打开浏览器深链并加载对应轨道
- THEN 目标 locus、轨道和坐标空间正确
- AND iframe 消息契约拒绝未授权 origin、伪造来源和未知消息类型

### R7：Vue 退役

最终交付 SHALL 从生产源码、workspace manifest、构建配置、测试运行时和依赖锁文件移除 Vue 组件与 Vue runtime/plugin；历史迁移文档可保留为审计记录。

**Scenario：全仓框架残留检查**
- GIVEN 三个应用和所有共享 UI 包完成迁移
- WHEN 执行源码、manifest、配置、锁文件和构建产物扫描
- THEN 不存在被应用加载的 `.vue` 文件、Vue runtime、Vue plugin、Vue Router/Pinia/Vue Query 依赖
- AND 历史文档中的 Vue 说明明确标为历史，不被误认为生产实现

### R8：可重复的消融实验

消融 SHALL 使用合成数据/独立测试构建，不得将删减安全约束的产物部署或发布。

**Scenario：单因子消融验证守卫有效性**
- GIVEN 固定 React 基线、Pro v6 处理组、相同数据与浏览器视口
- WHEN 分别运行完整处理组及按组移除的测试变体（共享 UI facade、身份/搜索、assembly/release、JBrowse bridge）
- THEN 每个实验记录命令、退出码、测试/路线结果、产物体积或性能观测及判定
- AND 移除安全/assembly 守卫时对应负例应翻转为失败；恢复守卫后重新通过
- AND `GUARD-ACTIVE`、`GUARD-INERT`、`GAP` 三态与已有消融报告保持一致定义；无真实观测的数据不得宣称提升

## 消融实验设计

| 组别 | 对照/消融变量 | 必须记录的证据 |
| --- | --- | --- |
| E0 基线 | 历史 React 页面/路由及同一合成数据 | route map、关键任务、截图、console、可用的产物/性能基线 |
| E1 Pro v6 壳层 | React 基线 vs Umi Max/Pro Layout 壳层 | 启动/静态导出、路由、首屏交互、资源路径、console |
| E2 共享 UI 包 | 完整 `ui-react` facade vs 隔离测试中的单组 bypass | 组件契约、页面任务、样式一致性、增量产物大小；不以代码行数推断质量 |
| E3 生物搜索 | 完整 search/filter/pagination/assembly/release vs 每次去掉一个因子 | 对应结果/缓存隔离/歧义测试应失败或结果不同，记录 exact assertion |
| E4 身份边界 | external/internal 授权和 ID 投影逐因子消融 | 未授权负例、响应/URL/log/artifact 哨兵扫描；所有消融只在合成、隔离环境运行 |
| E5 JBrowse | 完整 bridge/deep-link/track renderer vs 单因素移除 | bridge contract、assembly/locus/deep-link E2E 和实际轨道渲染结果 |
| E6 最终 UI 回归 | 完整 React Pro v6 处理组 | 路由矩阵、Playwright、无障碍/响应式截图、external/internal artifact gate |

同一任务路径、测试数据、视口和浏览器应在对照组与处理组保持一致。性能结果记录设备/浏览器/运行次数与分布；先建立基线，不预设未经测量的收益阈值。消融失败不计为产品测试通过；报告区分真实运行与静态推断。

## 验收与交付门禁

1. 冻结安装、工具链 pin 契约、Umi Max 最小静态导出试验通过；否则停在技术门禁并报告具体不兼容点。
2. web、admin、JBrowse 各自 lint/typecheck/unit/build 通过；`pnpm install --frozen-lockfile` 通过。
3. React 路由与行为矩阵无未解释差异；旧深链和当前活跃 Vue 功能均有 React 路径或正式退休记录。
4. `scripts/verify-site-variant-artifacts.sh`、external 泄漏负例、CSP/SW/base 路径和双站静态发布验证通过。
5. 数据库核心契约的 public/internal ID × external/internal × v4/v5 矩阵在对应 API/client/UI/E2E 层有非 skip 的验证证据。
6. JBrowse bridge、实体详情到 JBrowse 深链和轨道渲染有真实浏览器断言。
7. 视口/键盘/对比度/表单状态检查完成；双语覆盖门禁通过。
8. 消融报告逐组记录命令、退出码、结果、限制、GUARD 判定与失败清单；不以 “SKIPPED” 算通过。
9. 最终扫描确认生产前端和锁文件中 Vue 依赖/组件为 0；历史文档可保留。
10. 所有前端验证逻辑落在仓库脚本中；`.cnb.yml` 仍为交付单一事实来源，GitHub workflow 仅调用共同脚本。

## 已知风险与暂停条件

- Umi Max 的 `exportStatic` 与当前 external/internal 子目录产物、CSP 重写、SW 命名空间及发布脚本兼容性未验证，需先做小型 PoC。
- 当前未提交改动范围很大，可能存在并行会话写入；每个 Wave 前后重新核对 `git status` 和目标文件 diff，仅操作已确认归属的文件。
- 三个应用、共享包和交付链同时迁移，最终交付不能保留半 Vue/半 React 的生产路径；中间 Wave 属不可发布迁移态。
- Pro v6 及组件依赖需锁定经过许可证/漏洞/维护度检查的兼容版本；不得用 `latest`。
- UI 性能目标以实测基线和现有 bundle 门禁为准；没有基线时先测量，不声称“更快”。

## 参考资料

- Ant Design Pro v6 发布说明 / Issue #11734: https://github.com/ant-design/ant-design-pro/issues/11734
- Ant Design CLI: https://ant.design/docs/react/cli-cn
- Ant Design React 介绍: https://ant.design/docs/react/introduce-cn
- Ant Design 组件总览: https://ant.design/components/overview-cn/
- Ant Design 设计规范: https://ant.design/docs/spec/introduce-cn
- Ant Design 资源: https://ant.design/docs/resources-cn
- 图表 Sketch 套件（用户授权参考）: https://gw.alipayobjects.com/os/bmw-prod/704968a5-2641-484e-9f65-c2735b2c0287.sketch
- Pro 通用模板 Sketch 套件（用户授权参考）: https://gw.alipayobjects.com/os/bmw-prod/22208f9d-f8c5-4d7c-b87a-fec290e96527.sketch
- Ant Design Landing 模板下载: https://landing.ant.design/docs/download-cn
- 项目生物数据库契约: `docs/dev/database-core-contract.md`
- 当前 Vue 功能对照矩阵: `docs/dev/vue-migration-feature-gaps.md`
- 项目消融方法与报告基线: `docs/dev/ablation/2026-09-26/README.md`
