# SoyMutDB × 曹帅课题组：视觉素材、架构与执行验收设计

> 状态：**设计提案 / 待审批（PLAN ONLY）** · 日期：2026-10-09  
> 基线：`main@d262c8faa34abca3b5e2076f7abc4ddb92051729`  
> **当前 PR 仅新增/调整文档，不生成或提交生产素材，不改应用代码、Windows 脚本、CI、依赖或数据库。** 未来实施必须另起 PR、经过人工确认与验收。  
> 协同执行提示词：[`docs/agents/caoslab-visual-agent-prompt.md`](../agents/caoslab-visual-agent-prompt.md)

## 1. 调研事实、界限及目标

### 1.1 已核实的外部信息

来源均为曹帅课题组公开页面，**不等于已取得图片复制权或课题组官方品牌授权**：

- [课题组主页](https://www.x-mol.com/groups/Caoslab)：曹帅课题组，PI 为西北农林科技大学曹帅教授。
- [研究方向](https://www.x-mol.com/groups/Caoslab/research)：旱区作物驯化育种的遗传/表观遗传基础；野生种质资源优异等位基因与元件挖掘、种质创新及从头驯化；复杂基因组中的 DNA/RNA 甲基化调控；遗传学、多组学、生物信息学、基因编辑等方法。
- [公开成果目录](https://www.x-mol.com/groups/Caoslab/publications)：覆盖莴苣泛基因组、作物驯化的跨代表观遗传机制、DNA 甲基化、玉米/水稻等方向。每项对外展示的文献、作者、年份与 DOI 必须以论文原始页面再次核对。
- [Ant Design 视觉规范](https://ant.design/docs/spec/visual-cn/)：准确、有效、清晰的可视化；[图标规范](https://ant.design/docs/spec/icon-cn/)：准确、简单、一致；[布局](https://ant.design/docs/spec/layout/)：统一网格与自适应；[可视化页面](https://ant.design/docs/spec/visualization-page/)：概览优先、再过滤、再细节；[ProLayout 官方文档](https://procomponents.ant.design/components/layout/)；[Ant Design Charts 示例](https://ant-design-charts.antgroup.com/en/components/plots/overview)。

**重要分界**：SoyMutDB 是生物信息数据库，不是 X-MOL 课题组网站的镜像。平台的突变体、基因、变异、坐标、版本、数据量等仅以平台已发布的数据和 API 为准；课题组的跨物种研究成果只可作为经过审核的研究背景/成果展示，不能装成大豆突变体的数据证据。不得擅称“课题组官方唯一网站”“官方标识”“已验证科研结论”。

### 1.2 审计快照：架构与代码质量（证据等级）

依据当前 `main` 实际文件及已通过/失败的工作流，而非推测：

| 维度 | 已有证据 | 审计判定 |
|---|---|---|
| 公共站 | `apps/web` React/Umi；基因/区间搜索；JBrowse；external/internal 分离；已合并 PR #5 的 PR E2E 为 31 passed / 1 skipped | 核心路径可构建并通过**离线模拟**浏览器测试；真实线上部署需单独验证 |
| 后台 | `apps/admin/src/App.tsx` TanStack Router + 鉴权；`routes/__root.tsx` ProLayout；`packages/ui-react` + Ant Design 6 / ProComponents；现有登录态页面只有有凭据部署环境才能测试 | 组件架构有基础；**不能仅凭登录页 smoke 宣称后台业务/布局全可用** |
| 数据层 | FastAPI / PostgreSQL（权威）/ ClickHouse（分析投影）/ Redis（缓存队列）/ MinIO（文件）/ Worker | 约束明晰；真实发布、权限、来源、组装版本仍须独立验收 |
| CI/CD | `.cnb.yml` 权威，GitHub Actions 镜像；主 CI + baseline + PR Playwright | PR 浏览器及基线通过；合并前 `dependency-governance` 因 Knip + `braces` High **失败**，不能视作全绿 |
| 管理端验收缺口 | `e2e/tests/admin-console.spec.ts` 使用旧 `admin-sidebar` test id，但现行 `ProLayout` 不挂载旧侧栏；`admin-production-login.spec.ts` 仅覆盖登录页 | 后台**已确认测试断言漂移**；需修复断言并在具备受控凭据的隔离环境执行 |
| Windows 部署 | `deploy/windows/install.ps1` 仅安装 `apps/api`，独立共享 Python 本地包需标准安装器；升级链重复执行服务安装 | 当前脚本易失败，且仅部署 API，**不是完整网站一键生产部署** |
| 老设计文档 | `docs/design/architecture.md` 仍介绍 Widgets/Page Builder，`docs/adr/0009-retire-page-builder-and-widgets.md` 已决定退役 | 旧文档属历史，不能作为当前实现规范 |
| 死代码 | `apps/admin/src/components/admin-sidebar.tsx` 仍含旧侧栏 UI；`react-app.tsx` 实际导入 `index.css`，另存 `style.css` | 是待复核清理候选；未执行完整引用/构建/页面差异检查前不得直接删除 |

**综合判断**：架构方向与数据真实性边界合理；公共站的离线主流程可用性证据较强，后台登录后完整操作、生产态数据、Windows 部署和依赖安全尚没有“全部可用”的证据。任何百分比“完成度”在未取得全量验收矩阵前都是臆测，不予评分。

## 2. 推荐系统架构：最少概念、清晰边界

```text
X-MOL/论文/课题组许可素材 ──> 素材审核台账 ──> [经审批的静态科研插画/SVG]
                                                     │
公共站 apps/web ──> packages/ui-react (AntD tokens/components)
      │                    │
      ├── gene / mutant / variant / phenotype / JBrowse
      └── 只读共享 @soymutdb/api-client ──────┐
                                              ▼
后台 apps/admin ──> ProLayout + PageContainer ──> FastAPI
   (需认证/RBAC/审计，素材只作为内容)             │
                                      PostgreSQL [权威/发布/权限]
                                      ClickHouse [按版本分析投影]
                                      Redis [可丢弃缓存/队列]
                                      MinIO [原始文件/制品]
                                      Worker [导入分析后台任务]
```

- **唯一来源**：作物基因组与生物数据由 API/已发布 release 提供，论文元数据由 DOI/出版方核对，素材文件由明示台账与审核许可提供。禁止图像生成器输出可当成实验结果的数据。
- **唯一设计系统**：`packages/ui-react` 及应用既有 AntD facade / token 为准；不另建 CSS/UI 框架、不新增第二套图标平台。业务页面继续 React + Umi + TanStack Router，不能照旧设计稿重启 Widgets / Page Builder。
- **双站隔离**：external 的图像、Alt、metadata、JSON、构建包及缓存不可包含 internal、未发布记录或内部 ID。
- **后台职责**：管理发布、审计、导入、设置与内容；素材上传/编辑权限由已有服务端 RBAC 检查，绝不从前端绕过。
- **静态资产与数据图表分离**：学术概念示意图为静态原创 SVG/WebP；发布统计/变异密度/表型频数等必须由实际 API 数据生成，可编辑、带单位及来源，不用 AI 合成曲线或假数据。

## 3. 视觉方向与页面分配

**风格**：简约、学术可信、以数据库任务为中心。植株/染色体/基因组/甲基化 motif 做辅助点缀，不用花哨的生物科技蓝光、满屏渐变、伪三维 DNA 模型。优先浅底、暗色兼容、最多 1 个主色 + 1 个科研强调色；不得绕过已有可调主题色功能。

信息架构：

| 页面 | 主任务 | 素材角色 |
|---|---|---|
| 首页 | 输入基因、突变体编号或进入数据库检索 | 轻量 crop/mutation 示意 hero + 4 个快捷入口小图标；搜索框必须比科研装饰醒目 |
| 基因详情 | gene / assembly / release / locus / mutation sites | 真实标注的坐标示意，必要时 JBrowse；不得硬编码假基因 |
| 突变体详情 | 公共 ID、等位变异、表型、证据 | 功能分区图标；不借图形遮住“未发布/不可用”状态 |
| 搜索/筛选结果 | 多条件查询、分页、排序与证据 | 清晰表格、标签和真实分布图（可选），不要大面积插画 |
| 数据可视化 | 科研探索：对比/分布/关系/趋势 | Ant Design Charts 根据**问题与数据类型**选图；标题、单位、图例、Release/Assembly 均可见 |
| 关于/课题组背景（若获授权） | 交代研究背景与贡献 | 可用原创驯化/表观遗传示意；人物与 Logo 需许可；链接回 X-MOL |
| Admin 控制台 | 导入、发布、管理、审计 | 遵循 ProLayout / PageContainer，使用现有 AntD 语义图标；不放营销 hero 干扰操作 |

### 3.1 拟定素材清单（现在**未生成**）

| ID / 建议文件名 | 类型 / 场景 | 来源与内容约束 | 优先级 |
|---|---|---|---|
| A01 `crop-genomics-hero` | 16:9 首页科研背景，可分别导出桌面与手机裁剪 WebP/AVIF | 豆株形态 × 染色体抽象叠加，**原创示意**，无捏造统计/论文成果 | P1 |
| A02 `domestication-journey` | SVG/PNG 研究背景简图 | 野生资源 → 优异等位/遗传与表观遗传解析 → 种质创新；流程仅为概念，不宣称实验已证实 | P1 |
| A03 `methylation-regulation` | SVG DNA/RNA 甲基化概念图 | 机制需文献复核；标注“概念示意”，不画错误甲基化位点 | P1 |
| A04 `pangenome-diversity` | SVG 泛基因组概念图 | 莴苣等跨物种成果作为“课题组背景”；SoyMutDB 页面不能标注为大豆数据 | P2 |
| A05 `genome-browser-context` | SVG 辅助说明 | gene/exon/variant 与 assembly/release 的层级；与 JBrowse 真界面明确区分 | P1 |
| I01–I06 `gene`, `variant`, `mutant`, `phenotype`, `search`, `download` | 6 枚一致的 24px SVG 图标 | 优先复用 @ant-design/icons，只有缺少准确语义时做原创 | P1 |
| I07–I09 `domestication`, `epigenetics`, `germplasm` | 3 枚研究主题 icon | 植物元素少量、统一线重与留白；无需额外图标库 | P2 |
| C01 `mutation-spectrum` | 可交互真实统计图 | 需要释放版数据、assembly、计数定义；没有数据则不发布 | P1 |
| C02 `chromosome-distribution` | 按染色体的真实分布图 | 要写明组装版本、染色体长度/坐标尺度及计数口径 | P1 |
| C03 `phenotype-distribution` | 真实表型类别统计 | 需要表型 ontology/缺失率说明；不得将缺失值当 0 | P2 |
| P01 `research-highlights` | 论文卡片视觉封面/缩略图 | 优先原创构图；版权受限的出版社封面只放原站链接，不复制重制 | P2 |

总计候选 **4 幅科研插画 + 9 枚图标 + 3 个数据图表 + 1 组论文卡片**；不代表必须全部制作。首批建议 A01–A03、I01–I06；图表只有拿到可信数据源后才能安排。

### 3.2 资源规范与台账

- 输出路径建议：`apps/web/public/visuals/caoslab/`；**只在实际实现 PR 才创建**。可编辑源文件另置 `docs/design/assets/sources/`（SVG/绘图源，禁止提交第三方未经授权原始照片）。
- 命名：全小写英文 kebab-case，后缀表明 dark/light/尺寸（如 `crop-genomics-hero-desktop.webp`）；图标 SVG 有 `viewBox`、无内联脚本、外链、`foreignObject`；默认装饰图 `aria-hidden`，信息图附中文/英文文字等价描述。
- 源稿（SVG 或可重生成程序）、发布文件（SVG/WebP/AVIF）、许可（自制/明确授权/公共许可及适用条件）、生成工具版本、制作人、出处 URL/DOI、审核人、哈希 SHA256、使用页面、目标 release/assembly（如适用）必须记录在资产清单。
- 暂定单文件预算：英雄图桌面 WebP/AVIF ≤ 350 KiB，其他插画 ≤ 180 KiB，24px 简笔图标 SVG ≤ 5 KiB；超预算需有质量/清晰度和加载证据。禁止为体积牺牲文字可读性。
- UI 对比度遵循 WCAG 2.2 AA（普通文本 ≥ 4.5:1；非文本交互要素 ≥ 3:1）；深色模式、200% 缩放、键盘导航、`prefers-reduced-motion`、390/768/1440px 检查均是必需项。
- **科研图表不按上述静态图压缩交付**：应保留 CSV/JSON 来源、处理代码、坐标轴、颜色语义、单位、样本量、缺失/筛选口径、数据版本与链接，确认图表可复现。
- 禁止把 X-MOL 照片、人物肖像、学校/期刊 Logo、论文原图、商标或出版社封面直接下载到仓库；需版权/肖像/商标权核实与书面授权。AI 生成图片必须显式标记为示意，不能冒充显微照片、实验测量或课题组真实场景。

## 4. 当前遗留任务裁决（不是功能完成清单）

| 任务 | 继续？ | 优先级 / 退出条件 |
|---|---|---|
| 依赖治理：Knip 及 `braces` GHSA | **必须** | P0。分类每个 entrypoint/unused 候选、证实可删；GHSA 无已发布修复时保持阻断，评估可替换上游链或经过审批的隔离发布策略，禁止伪造绿灯 |
| Admin 响应式与业务 | **必须** | P0。ProLayout 真实 DOM + 登录后 Dashboard/Imports/Settings/News/Content，390/768/1440 桌面及手机、键盘/暗色，真实鉴权环境通过；没有凭据记 NOT VERIFIED |
| Admin 的 Playwright smoke 进 CI | **必须** | P0。先做无需密钥的生产登录制品测试，认证功能另需受控部署与测试账号；失败保留截图/trace |
| Windows 部署 UX | **必须但范围限定** | P0/P1。明确“单机 API-only”还是“完整栈”；使用共享本地 Python 包安装器、幂等服务管理、备份/迁移/回滚、health；不能宣称仅 Windows 脚本实现 CH/Redis/MinIO/worker |
| 死代码/旧文件治理 | **继续、不可批量删** | P1。逐文件列出引用、运行时入口、静态资源和 Git 历史；安全删除须能构建 + 测试 + 产物差异说明 |
| 静态原创视觉资产 | **做有用的** | P1。先小批高质量示意与图标，必须证明检索效率没有退化；按本文件 A/I 标识逐件验收 |
| 数据图表 | **有数据才做** | P1/P2。Release/Assembly/data provenance，真实数据可复现；没有来源则保持占位设计而不是生成假数 |
| 论文/成员/课题组资讯 | **需 PI 内容审批** | P2。每项逐一验证出处、版权与本人授权，避免导入 X-MOL 全站抓取内容 |
| PR #2–#4 experimental Rust / OmicVerse 等 | **维持 No-Go / 暂缓** | P2。性能/科学正确性、资源成本、依赖平台资格通过后单独决策；不得因素材改造顺带开放生产 |
| 退役 Widgets / Page Builder | **保持退役** | 不重启。旧文档需标注 historical，数据库表及 API 的物理移除必须另起迁移评审 |
| “全平台重写”“新增多套 UI 框架”“重做所有旧设计文档” | **不做** | 拒绝过度设计；必须有明确缺陷证据与效益才重新提案 |

## 5. 实施次序及可审计验收（仅供未来执行）

- **M0 事实基线**：记录 exact Git SHA、路由/API 与环境矩阵、已有真实 CI，筛选错误/无法验证/已证实三态。验收：带证据链接，不跨不同 SHA 拼凑 PASS；无凭据后台为 NOT VERIFIED。
- **M1 视觉源与版权**：课题组与出版方审核文字/图像使用权限，批准首批素材、主体与元数据。验收：逐项台账齐全，无未经许可第三方资产。
- **M2 原创视觉资产**：最多先交 1 个首页图 + 3 个研究示意 + 6 个 icon 的候选源稿；按用途审查，排除不适用图。验收：与 AntD token/光暗/移动端协调、尺寸、对比度、SVG 安全、可访问性、原创授权达标。
- **M3 真实统计图**：只有 API 已发布真实数据可用才制作 C01–C03；需交查询、样本数、转换代码与数据校验。验收：图表与 API 复算相等，空值/未发布/不同 assembly 不被混合。
- **M4 Admin + Windows + 清理（独立代码 PR）**：先测再修，变更范围按模块隔离。验收：认证权限负测、移动端可用、PowerShell `-DryRun` 与隔离 Windows/PG 实测、无数据损毁、删除文件可追溯。
- **M5 CI/CD（独立 PR）**：GitHub 与 CNB 复用已检入测试脚本，PR 构建产物 smoke；在线 deploy smoke 检查真实发布站点。验收：失败不降级、每个 skipped 说明前提、保留 trace/报告/版本、无密钥暴露。
- **M6 发布审查**：审批人检查 diff、许可、实际数据、测试和回滚，基于同一 HEAD 合并。验收：全部 P0 为 Pass；High/Critical 没有虚假的“已修复”；部署另设门禁。

**必要负向测试**：失效登录/未授权后台拒绝；external 不输出 internal ID/未发布记录；换 assembly/release 不复用旧数据；空结果与 503 不混淆；无数据的图表绝不展示虚构数字；移动端不遮蔽检索操作；无后台凭据时不能以 skip 记“测试通过”；Windows 缺少 `DATABASE_URL`、服务包装器、备份目录权限或 PG 可用性时必须明确失败。

**CI 验收规则**：输出每一步命令、版本、输入、退出码、通过/失败/跳过数量、报告位置；构建/测试/扫描失败直接阻断目标发布；冒烟测试和消融测试分别覆盖“关键功能存在”和“去掉关键约束必定失败”，不得替换为假 fixture 绿灯。

## 6. 未来每个视觉资产的审批清单

```yaml
id: A01
status: planned                # planned | licensed | produced | reviewed | published
purpose: public-home-hero
species: Glycine max           # 不是实验数据；若有其他作物须显式区分
kind: conceptual-illustration  # never empirical-data-figure
source_urls:
  - https://www.x-mol.com/groups/Caoslab/research
license: "original-work / permission-pending"
attribution: "awaiting-review"
source_sha256: null
published_release: null
assembly: null
alt_zh: "待审"
alt_en: "Pending review"
author: null
reviewer: null
artifact_path: null
tests: []
```

文档链接作为未来执行入口：[`docs/agents/caoslab-visual-agent-prompt.md`](../agents/caoslab-visual-agent-prompt.md)。**先做设计评审，再生产文件；当前没有获批可对外发布的课题组授权素材。**
