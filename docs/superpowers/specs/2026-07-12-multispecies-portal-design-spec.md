# 多物种静态科研门户：功能与体验设计说明

**文档用途：** 供其他智能体或工程团队执行；本文定义目标架构、产品能力、交互规则、分阶段交付和质量门，不提供实现代码。

**产品目标：** 将 SoyMutDB Next 从大豆专属门户演进为可扩展至多物种的科研数据平台。管理员可完整管理公开内容与模块展示，公开用户获得快速、可引用、可理解的静态数据发现体验。

**非目标：** 不构建通用低代码系统；不允许管理员编辑生产文件、任意模板或脚本；不在没有指标证明前拆分微服务；不让技术情报自动升级依赖或发布生产内容。

**全局工程约定：** 新增自有业务函数、变量、模块、类型、组件、服务、脚本与测试夹具统一以 `rl_` 开头。不得修改框架约定、第三方 API、环境变量、数据库既有列、配置键、路由协议或已有公共接口来强加此前缀。所有新增业务规则、发布/版本转换、权限判断、数据清理边界和非直观性能处理必须添加简洁中文注释，说明“为什么”而非复述语法。

---

## 1. 已有基础与设计约束

| 范围 | 已有基础 | 本设计要求 |
|---|---|---|
| 公开端 | `apps/web`，React/Vite SSG | 保持静态优先，公开页面不直连数据库 |
| 管理端 | `apps/admin`，React/Tauri | 保持 localhost/内网边界；成为唯一业务控制面 |
| API | `apps/api`，FastAPI/SQLAlchemy | 继续承载内容、数据、发布和管理 API，不在公开页面请求期拼装页面 |
| 搜索 | `apps/web/src/workers/search.worker.ts` | 将 Worker 扩展为版本化静态索引的查询层 |
| 内容版本 | `Release`、`StaticPage`、`ContentVersion` | `Release` 仅作为待迁移的数据发布基础；页面内容版本作为 `PublicationManifest` 输入，门户快照另建 `publication_release_id` |
| 组件与布局 | Widget / PageLayout 设计 | 升级为有范围、状态和 Schema 约束的模块配置 |

## 2. 推荐总体架构

```text
管理控制面（受限访问）
  用户/权限  内容/导航/模块  物种/组装/数据发布  技术情报审核
                                     │
                                     ▼
版本化发布层
  校验 → 私有预览 → 审核 → publication_release_id 快照 → 静态构建/搜索索引 → 原子发布
                                     │
                                     ▼
公开静态门户（CDN / Nginx）
  HTML + CSS/JS + 版本化公开数据包 + JS/Web Worker 分片搜索
```

### 2.1 端到端衔接与打包链路

```text
已审核配置 + 固定数据输入
→ dataset release 验证
→ publication manifest 冻结
→ Web SSG / 搜索索引 / Admin / API / Worker / Rust 独立构建
→ SBOM、内容哈希、测试和 OCR 证据
→ 不可变制品仓库
→ 预览环境验收
→ 原子切换 publication_release_id
→ 监控与可验证回滚
```

每个交接点都必须有输入契约、输出契约、责任边界和失败行为：数据层只产出已验证的 `dataset_release_id`；发布层只接收已审核内容和数据快照；构建层只读取冻结的 manifest；CDN 只服务已签名/校验的不可变制品；运行时模块不得绕过上述版本链路。

### 2.2 可复现打包机制

- **版本锁定：** Node/pnpm、Python/uv、Rust/Cargo、容器基础镜像和 OCR 版本均锁定到仓库定义的稳定版本；升级先由技术情报流程输出 ADR、兼容性矩阵、试点结果和回滚方案，不能仅因版本最新就升级。
- **构建矩阵：** `apps/web` 生成 SSG、压缩静态资源与 `SearchManifest`；`apps/admin` 生成 Web/Tauri 管理端制品；`apps/api`、`apps/worker` 生成带锁定依赖的 Python 制品；`apps/core-rs` 生成 Rust 二进制。每个制品必须标注 Git commit、`publication_release_id`（无公开快照的服务标记 `not-applicable`）、输入 lockfile 哈希、构建工具版本和 SHA-256。
- **制品清单：** 每次打包生成 `artifacts/manifest.json`，记录制品路径、大小、SHA-256、SBOM 路径、来源提交、构建时间和依赖版本。发布器只能消费验证通过的清单，禁止直接发布工作区目录。
- **分层发布：** API/Worker/Rust 先部署到预览并通过健康检查；Web/Admin 静态制品在相同 manifest 上完成验收；只有所有依赖制品和数据版本兼容才允许发布指针切换。
- **回滚：** 保留与每个 `publication_release_id` 匹配的制品清单、静态资源、索引和兼容服务版本；回滚以清单为单位，不允许混搭不同构建产物。

### 2.3 必须遵守的边界

1. 管理端写入草稿、配置和发布命令；它不得直接覆写公开静态产物或生产数据库数据。
2. 一个 `publication_release_id` 同时绑定页面、导航、站点地图、下载清单、实体静态页和搜索索引；发布和回滚按完整快照切换。
3. 管理员配置仅能引用注册模块及其 JSON Schema；禁止任意 JavaScript、模板表达式、内联 CSS 和未净化 HTML。
4. 公开端无 JavaScript、Worker 或外部搜索时，仍应可阅读、导航并理解功能降级状态。
5. 默认保持模块化单体 + 后台任务；只有以索引体积、构建时长或 SLO 证明瓶颈后，才讨论独立搜索或更多服务。

## 3. 核心领域模型

```text
Species (stable UUID, immutable public slug, optional NCBI Taxonomy ID)
  └─ Assembly
      └─ DatasetRelease
          ├─ Gene / Transcript
          ├─ Variant / MutantLine / Phenotype
          ├─ Expression / Annotation
          └─ Evidence / Provenance

PublicationManifest (publication_release_id)
  ├─ SiteConfig / NavigationPolicy
  ├─ Page[] / ModuleInstance[]
  ├─ ModuleAvailability[]
  ├─ SearchManifest
  └─ audit / provenance references
```

### 3.1 标识、作用域与链接契约

- `dataset_release_id` 是科研数据快照标识：一个数据发布属于一个 `assembly_id`；它是 Gene、Variant、Line、Annotation、下载数据项和搜索文档的必填外键。
- `publication_release_id` 是公开门户快照标识：它冻结页面配置、导航、模块配置、被引用的数据发布集、静态产物清单和搜索清单。它不能复用现有 `Release.id`，也不能替代 `dataset_release_id`。
- 合法作用域只有四类：`global`（站点、Guide、Help、全局 Publication）、`species`（物种介绍）、`assembly`（浏览器与组装元数据）、`dataset`（科研对象与数据下载）。全局/物种内容不得伪造 assembly 或 dataset 外键。
- `Species` 使用不可变内部 UUID 和不可变 public slug；学名、俗名和别名可修改。`Assembly` 使用内部 UUID、稳定 accession 和状态；同一物种在任一时刻只能有一个默认公开组装。废弃组装保留可引用记录，不允许被静默复用。
- 公开 canonical URL 的固定格式为 `/species/:speciesSlug/assemblies/:assemblyAccession/releases/:datasetReleaseVersion/<entity>/:entitySlug`。旧短路由仅 302 至默认公开上下文；若旧链接无法唯一解析，返回解释性 410 页面，不猜测目标。
- `speciesSlug`、`assemblyAccession`、`datasetReleaseVersion` 和 `entityPublicId` 使用小写 ASCII、连字符分词的不可变公开标识；原始外部 ID 保存在别名表。路径参数必须经 UTF-8 百分号编码后解码并按规范化标识匹配；拒绝包含 `/`、控制字符或规范化后冲突的输入。`datasetReleaseVersion` 在同一 assembly 内永久唯一且不可修改，`entityPublicId` 至少在 `dataset_release_id + entity_type` 内唯一。
- 每个科研对象、坐标、缓存键、搜索分片和下载项都使用三层数据作用域；全局页面、指南、帮助与全局文献只使用其合法作用域。
- 外部 ID 只能作为有命名空间的别名，例如 `ncbi:`、`ensembl:`、`uniprot:`；不得以名称相同推断跨物种等价关系。
- 跨物种比较必须呈现同源关系、证据来源和版本条件。
- 物种特有字段进入适配器或扩展属性，不污染通用模型。

### 3.2 发布快照契约

每份 `PublicationManifest` 至少包含：`publication_release_id`、`manifest_schema_version`、构建输入内容版本列表、被引用的 `dataset_release_id` 列表、页面/导航/模块配置哈希、搜索索引文件 URL 与 SHA-256、下载文件 URL 与 SHA-256、构建工具版本、创建时间、不可变产物根路径和前一个公开快照引用。构建从一个事务性输入快照读取；构建期间的新草稿不得进入该快照。失败产物写入隔离前缀，只有 manifest 完整性验证通过后才能原子更新公开指针。

保留至少最近 12 个已发布快照和其引用产物；数据库 schema 至少支持当前及前两个公开快照读取。任何破坏性 migration 必须先通过兼容发布、备份恢复和回滚演练。构建中应规范化时间戳和压缩元数据，确保相同快照具有可复现内容哈希。

## 4. 管理员控制面设计

### 4.1 权限与治理

“管理员全权限”定义为完整业务控制权，不是绕过安全流程的数据库/服务器权限。

| 角色 | 主要权限 |
|---|---|
| Platform Owner | 管理管理员、全局策略、密钥引用和发布策略 |
| Data Steward | 维护物种、组装、数据集、导入校验和发布候选 |
| Content Editor | 编辑内容、导航、SEO、模块配置和多语言文案 |
| Reviewer | 审核内容、数据和技术情报 |
| Publisher | 生产发布和回滚 |
| Auditor | 只读查看审计、发布和质量证据 |

现有账号与权限实现必须先盘点后迁移：采用**能力权限**而非角色层级继承；一个用户可拥有多项能力，`Auditor` 只拥有只读能力且绝不因查看审计记录得到写权限。先映射现有角色到新能力集合，再在预览环境验证现有管理员不会失权或意外提权。

高风险操作（权限提升、批量删除、生产发布、回滚）必须重新认证，并产生追加式审计记录。默认规则是提交者不能审核自己的变更，Reviewer 不能发布自己审核的高风险变更。单管理员部署是受控例外：必须记录 `single_operator_exception`、执行第二次凭据确认、等待 15 分钟冷静期，并向预配置告警接收人发送通知。

审计记录只追加，不在应用层提供编辑或常规删除接口；审计事件应写入独立保留存储并包含前一事件哈希、事件哈希、操作者、时间、动作、作用域、前后摘要和脱敏后的敏感字段。高风险操作在同一业务事务中写入带幂等键的 audit outbox；投递器按顺序分区构造哈希链。投递失败时，发布状态不得切换，并由补偿任务重试或回滚业务操作，避免“操作成功但无审计”。保留期至少 365 天；清理只能由保留作业在到期后运行，并记录清理证明，不得沿用现有 180 天删除逻辑。

### 4.2 管理端信息架构

```text
Overview
  Dashboard / Pending Reviews / Recent Releases
Catalogue
  Species / Assemblies / Dataset Releases
Data Operations
  Imports / Variants / Lines / Tracks / Downloads
Public Experience
  Navigation & Modules / Page Layouts / Content / Search Indexes / Preview
Quality & Publishing
  Accessibility / Build Status / Publish Queue / Rollback / Health
Governance
  Users & Roles / Audit Logs / System Settings / Technology Radar
```

### 4.3 页面与模块配置

管理员可管理页面路由、SEO、多语言文案、模块顺序和模块范围；不能编辑页面执行逻辑。

```text
Page
  route / locale / SEO / publication state / ordered module instances

ModuleInstance
  registered type / validated config / sort order / scope / fallback copy

ModuleAvailability
  scope: global | species | assembly | dataset release | language
  state: Draft | Preview | Published | Hidden | Deprecated
  rule: time window | data dependency
```

**关闭模块时的产品行为：** 管理端显示受影响的导航项、首页入口、站点地图、搜索筛选、静态路由和深链；必须先生成预览，发布成功后才替换当前公开版本。未发布或没有数据时，公开端提供说明与替代入口，不能留空白或死链。

**解析规则：** 作用域优先级为 `dataset > assembly > species > global`；同一优先级只允许一条已发布规则，否则发布校验失败。`Hidden` 从导航、站点地图和新列表移除，但已发布科研详情页保持 200 并显示“当前不在导航中”；`Deprecated` 保持 200、`noindex` 和替代链接；不存在、未发布或从未公开的对象返回 404。时间窗口仅在构建快照创建时按 UTC 计算；禁止基于登录用户、Cookie、IP 或任何请求期受众属性改变已发布科研内容。

**动态模块边界：** 默认将现有 dynamic/external Widget 迁移为构建期内容。科研数据模块如保留运行时读取，必须在请求、响应、Redis 缓存键和 HTML 元数据中显式携带 `publication_release_id` 与 manifest 引用的 `dataset_release_id`；版本不可用时显示降级状态，严禁回退至“最新数据”。只有不影响科研内容、导航、可见性或引用的实时运行状态模块可读取实时数据，并必须位于明确的白名单中。

### 4.4 发布流程

```text
编辑草稿
→ Schema 校验
→ 影响分析
→ 私有预览构建
→ 审核
→ 生成 PublicationManifest / publication_release_id
→ 生成页面、数据包和索引
→ 完整性/安全/体验检查
→ 发布确认
→ CDN/Nginx 原子切换
→ 监控、审计
```

回滚必须切换到历史完整发布快照，禁止只回滚 HTML 或索引中的某一部分。回滚前检查历史下载文件、索引和 API 兼容性仍在保留窗口内；更新 CDN 当前指针后按路径版本化资源、短 TTL HTML 和缓存清除策略验证恢复。管理端草稿不随公开回滚倒退，但必须显示当前公开快照与当前编辑草稿的差异。

## 5. 公开门户功能与 UX 设计

### 5.1 路由与全局科研上下文

推荐公开路由：

```text
/species
/species/:speciesSlug
/species/:speciesSlug/assemblies/:assemblyAccession/releases/:datasetReleaseVersion/genes
/species/:speciesSlug/assemblies/:assemblyAccession/releases/:datasetReleaseVersion/genes/:geneId
/species/:speciesSlug/assemblies/:assemblyAccession/releases/:datasetReleaseVersion/variants
/species/:speciesSlug/assemblies/:assemblyAccession/releases/:datasetReleaseVersion/variants/:variantId
/species/:speciesSlug/assemblies/:assemblyAccession/releases/:datasetReleaseVersion/lines
/species/:speciesSlug/assemblies/:assemblyAccession/releases/:datasetReleaseVersion/browser
/species/:speciesSlug/assemblies/:assemblyAccession/releases/:datasetReleaseVersion/downloads
/search?scope=all|species&species=:speciesSlug&assembly=:assemblyAccession&release=:datasetReleaseVersion&q=...
```

保留旧短路由作为兼容入口，但只在能唯一解析默认公开物种、组装和数据发布时 302 到 canonical URL；所有详情、下载、浏览器和分享链接使用 canonical URL。首次进入无物种上下文的首页或 `/search` 不自动下载任何科研索引，只显示物种选择和可搜索的物种目录；URL 参数优先于已保存偏好，用户明确选择“全部物种”后才按需加载其他分片。

### 5.2 公共端组件边界

| 组件 | 责任 |
|---|---|
| `PublicAppShell` | 页头、页脚、跳至正文、页面标题与全局布局 |
| `SpeciesContextBar` | 当前物种、组装、发布版本及切换入口；移动端折叠 |
| `SpeciesSwitcher` | 按俗名、学名和别名查找物种；展示数据可用性 |
| `ModuleAvailabilityGuard` | 统一处理未发布、无数据、维护中和下线模块 |
| `ScientificBreadcrumbs` | 显示物种 → 组装 → 模块 → 对象的科学上下文 |
| `SpeciesBadge` / `AssemblyTag` / `ReleaseTag` | 始终用文本、徽章和颜色共同表达范围和状态 |
| `SearchScopeControl` | 选择当前物种或全部物种，并提示索引状态 |
| `ComparisonBasket` | 保存待比较/导出的对象，并显示跨物种限制 |

上述为产品术语；代码中的新增组件、文件、hooks、服务和变量分别命名为 `rl_public_app_shell`、`rl_species_context_bar`、`rl_species_switcher`、`rl_module_availability_guard`、`rl_scientific_breadcrumbs`、`rl_search_scope_control`、`rl_comparison_basket` 等 `rl_` 标识，不修改已有导出或第三方组件名。

### 5.3 页面体验

**首页：** 平台定位、全局搜索、支持物种、数据覆盖、核心探索入口、近期发布、引用与可信度。首页不再把大豆作为不可切换的默认主体。

**物种主页：** 学名/俗名、组装、发布版本、来源与引用、数据统计、可用模块和推荐查询。模块未发布时展示明确说明。

**数据浏览：** 统一筛选语言：基础范围（物种、组装、发布、来源）+ 对象筛选（坐标、影响、表型、材料、实验条件）。桌面端支持固定筛选器、列选择和导出；移动端使用筛选抽屉与关键字段卡片。

**详情页：** 必须明确对象身份、物种、组装、数据版本、来源、引用和可用分析入口；任何比较链接都提示是否跨物种或跨组装。

### 5.4 视觉语言

- 科学、可信、信息密度适中，避免营销式卡片堆叠。
- 展示型标题用于页面层级；等宽字体用于基因 ID、坐标和变异位点。
- 物种识别使用“小型徽章 + 学名 + 组装标签”；颜色仅辅助，状态同时有文字与图标。
- 动效仅用于页面进入、上下文切换和加载反馈；严格遵守 `prefers-reduced-motion`。
- 图表必须提供文本摘要和数据下载；不以 Canvas 或颜色作为唯一信息载体。

### 5.5 无障碍与响应式

| 环境 | 设计要求 |
|---|---|
| 键盘/屏幕阅读器 | 物种/组装切换、筛选抽屉、比较篮和搜索命令面板可完整操作；搜索更新使用非打断式 `aria-live` |
| 桌面 | 常驻上下文栏、固定筛选器、宽表支持列固定与横向滚动 |
| 平板 | 上下文栏压缩；筛选器折叠；表格保持可横向查看 |
| 手机 | 物种上下文优先可达；筛选为抽屉；数据表变为包含关键字段的卡片；不依赖 hover |

## 6. 静态 JavaScript 搜索

```text
DatasetRelease → Search Document Builder → species/type/language 分片
→ SearchManifest（schema、release、hash、size、records）→ CDN
→ 浏览器按需加载 → Web Worker → 静态详情页
```

### 6.1 搜索规则

- 优先覆盖 Gene、Variant、MutantLine、Download、Publication、Guide 和 Help。
- 默认仅加载当前物种与语言分片；用户选择全物种范围后再惰性下载其他索引。
- 排序优先级：精确 ID → ID 前缀 → 别名/同义词 → 标题 → 描述。
- `SearchManifest` 固定包含 `schema_version`、`publication_release_id`、数据作用域、语言、分片 URL、SHA-256、压缩后与未压缩字节数、最大内存估算、记录数和生成时间。文档 schema 固定为 `id`、`type`、`scope`、`title`、`aliases[]`、`species`、`assembly`、`dataset_release`、`summary`、`canonical_url`、`source`：`global` 的三层范围字段必须为 `null`，`species` 只允许 `species` 非空，`assembly` 要求 `species` 与 `assembly`，`dataset` 三者均必填。发布校验拒绝所有不符合 scope 的文档；未知 schema 或 hash 不匹配时丢弃分片并显示可重试错误。
- 查询规范化采用 Unicode NFKC、Unicode case folding、空白折叠和已发布别名表；结果以 `type + canonical_url` 去重，默认最多显示 100 条，稳定并列排序使用 canonical URL。
- 搜索文档仅包含公开展示和跳转字段；发布前对字段白名单、敏感信息和版本一致性进行检查。
- 每个结果展示对象类型、物种、组装、数据发布、来源、匹配原因和稳定链接。
- Worker 不可用时，仅当已加载分片压缩后不超过 2 MB、未压缩后不超过 8 MB、记录数不超过 10,000 且最大内存估算不超过 24 MB 才允许主线程降级。降级查询必须分批处理、每批让出主线程、支持取消，且总预算为 150 ms；超过任一阈值时显示索引不可用状态并链接到预生成的物种、实体类型和首字母目录。无 JS 时这些目录、站点地图、前 100 条分页浏览页和下载页面必须可用。
- 每个索引最多缓存当前公开快照和前一个快照；切换发布后，客户端检测 `publication_release_id` 不一致即删除旧缓存。分片使用 brotli 优先、gzip 回退；仅支持当前两代 Chromium、Firefox、Safari 及其移动版。

### 6.2 外部来源搜索

NCBI、UniProt、Ensembl 等实时检索必须与本地静态结果分组显示。浏览器不得直接访问第三方：外部查询仅经过 FastAPI 搜索适配器，适配器执行允许来源校验、速率限制、缓存、超时、HTML 净化和 circuit breaker；请求日志不得存储完整检索词与可识别用户信息。API 不可用或来源降级时，公开端只显示本地静态结果及“外部来源暂不可用”状态。每个外部结果展示来源名称、服务状态、更新时间和离开本站提示；不得与“本平台已发布数据”混排。

## 7. 技术栈情报与升级决策

```text
可信来源清单 → 定时采集 → 原始证据隔离
→ 解析/去重/分类 → 候选技术 → 人工审核 → 技术雷达 → 升级建议
```

- 来源优先级：官方文档/发布说明/仓库、标准组织、同行评议论文；知乎等社区内容仅用于发现线索。
- 每条候选必须记录 URL、发布时间、采集时间、内容哈希、适用范围、收益、迁移成本、风险、置信度和审核意见。
- 外部内容视为不可信输入：遵守 robots、许可和频率限制；净化 HTML；防范提示注入；不得自动改依赖、配置、部署或公开内容。
- 任何升级提案必须显式声明使用的仓库 `skills/`、技术来源、替代方案、风险、回滚策略、验收标准和仓库清理动作。当前仓库未发现知乎命名 skill；若缺失，执行者必须如实说明，而不是伪造调用记录。

## 8. 执行阶段与交付物

### Phase 0 — 基线与治理

**交付物：** 大豆专属硬编码清单、页面/数据/搜索盘点、术语表、权限矩阵、威胁模型、性能与可访问性基线、第二物种候选评估。

**通过条件：** 所有关键数据来源、许可、责任人与现有管理员操作可追溯；冻结新增大豆专属耦合。

### Phase 1 — 数据标识、权限与审计基础

**交付物：** `Species`、`Assembly`、`DatasetRelease` 的最小契约、稳定标识规则、旧 `Release` 映射与只读兼容层；能力权限迁移、现有账号差异报告、服务端 allow/deny 测试、重新认证与单管理员例外流程；事务型 audit outbox、独立审计存储、哈希链和保留策略。

**通过条件：** staging 环境完成迁移和备份恢复；Auditor 无任何写能力，现有账号无意外失权/提权；高风险业务事务先写入同一事务的不可变 outbox，审计投递失败会阻止发布状态切换或触发补偿；大豆双读关键查询差异低于 0.1%，其余差异逐条归因。未达到这些条件不得生成首个 `PublicationManifest`。

### Phase 2 — 发布快照、打包与回滚

**交付物：** `PublicationManifest`、`publication_release_id` 规则、冻结输入/原子指针/预览/回滚方案、`artifacts/manifest.json` 制品清单、SBOM、版本化构建矩阵和发布审计验证矩阵。

**通过条件：** 同一冻结输入可复现内容哈希；页面、数据包和索引版本自动一致性验证；只有已验证制品清单能进入预览；回滚演练成功，且未混搭制品、索引或数据快照。

### Phase 3 — 管理内容与模块控制

**交付物：** 模块注册表、配置 Schema、范围化可见性、管理端 Public Experience 工作区、影响预览与审核发布流程。

**通过条件：** 管理员可不写代码完成内容、导航和模块配置；未审核修改无法公开；禁用模块不产生孤立导航、死链或不一致搜索筛选。

### Phase 4 — 多物种公开体验、静态搜索与第二物种发布

**交付物：** 物种上下文路由、公共组件、物种主页模板、分片搜索索引规范、搜索范围与外部来源交互设计、移动/无障碍验收用例；至少一个许可清晰的第二物种的导入、科研质量校验、DatasetRelease、静态页、索引、下载、引用和正式发布。

**通过条件：** 对 8 名具有基本生物信息学经验的测试者，至少 7 人能在两分钟内从指定物种主页或搜索入口找到给定基因/变异，并正确说出其组装与数据版本；在 Moto G Power（Chrome、Fast 4G）上，当前物种 2 MB 压缩索引首次查询的 INP 小于 200 ms，Long Task 不超过 50 ms；至少 7 人能区分本地与外部结果。大豆与第二物种必须复用同一领域模型、页面、搜索、打包和发布流水线，且不存在复制实现。

### Phase 5 — 技术情报与持续演进

**交付物：** 来源目录、采集与审核流程、内部技术雷达、升级建议模板、清理清单。

**通过条件：** 技术选择可追溯至证据和人工决策；采集失败不影响公开服务；不发生自动升级或自动发布。

## 9. 强制质量门

所有 Phase 必须串行推进；下一 Phase 的前置输入是上一 Phase 的交付物、通过条件证据、已归档的 ADR 与风险记录。任一通过条件失败即停止推进，先修复或获得书面风险接受；不得以临时硬编码跨越依赖。

执行者按本次变更边界选择确定性检查，而不是对每个文档或局部 UI 改动盲跑全栈：

```bash
# Web / SSG：pnpm --filter @soymutdb/web lint && pnpm --filter @soymutdb/web typecheck && pnpm --filter @soymutdb/web test && pnpm build:web
# Admin：pnpm --filter @soymutdb/admin lint && pnpm --filter @soymutdb/admin typecheck && pnpm build:admin
# API：cd apps/api && pytest -v && ruff check . && mypy .
# Worker：cd apps/worker && pytest -v && ruff check . && mypy .
# 迁移：仅在 disposable/staging 数据库运行，先断言 APP_ENV=staging、数据库主机不为生产域名且备份已完成；执行 Alembic upgrade → downgrade → upgrade、备份恢复和双读差异检查。禁止裸运行 make migrate；生产迁移仅能由单独受审发布流程触发。
# Infra：make build-docker；必要时 make db-up、make test-e2e
# 所有代码边界：pnpm review（仓库内部确定性审查，不是官方 OCR）
```

管理端的权限、审核、重新认证、冷静期和发布确认实现前，必须先添加并运行 Admin 测试脚本；测试必须覆盖能力驱动的路由/控件可见性、API 的逐能力 allow/deny、提交者/审核者/发布者隔离、单管理员例外和异常路径，不能以 UI 隐藏代替服务端拒绝。

涉及公开端的发布验收必须以待验收的 `publication_release_id` 启动本次静态构建产物：构建 → 固定端口静态服务 → 健康检查页面 manifest 与待验收快照一致 → `npx playwright test --config=tests/e2e/playwright.config.ts` → 关闭服务。测试覆盖键盘导航、页面可访问性、移动视口、禁用 JS、Worker 失败、离线索引和模块显隐一致性；禁止复用未知的 `localhost:8080` 服务。性能门使用 Phase 4 中定义的设备、网络、INP 与 Long Task 阈值；数据迁移门使用 Phase 1 的差异阈值。

必须安装并固定官方 Alibaba Open Code Review `v1.7.7`；若升级该工具，必须先通过独立 ADR 更新版本和审查基线。本地可使用 `pnpm dlx @alibaba-group/open-code-review@1.7.7`，CI 使用同一固定版本。设置 `OCR_NO_UPDATE=1` 以禁止工具自动更新，并先通过环境变量 `OCR_LLM_URL`、`OCR_LLM_TOKEN`、`OCR_LLM_MODEL`（必要时 `OCR_USE_ANTHROPIC`）配置 Provider；凭据仅由密钥管理提供：

```bash
mkdir -p artifacts/ocr
export OCR_NO_UPDATE=1
pnpm dlx @alibaba-group/open-code-review@1.7.7 version
pnpm dlx @alibaba-group/open-code-review@1.7.7 llm test
BASE_SHA="$(git merge-base origin/main HEAD)"
HEAD_SHA="$(git rev-parse HEAD)"
pnpm dlx @alibaba-group/open-code-review@1.7.7 review --from "$BASE_SHA" --to "$HEAD_SHA" --format json --audience agent > artifacts/ocr/review.json.tmp && mv artifacts/ocr/review.json.tmp artifacts/ocr/review.json
```

OCR 的先决条件是 Git 仓库、`origin/main` 可用且完整历史已获取；CI checkout 使用 `fetch-depth: 0`。对未提交本地变更，使用固定版本的 `pnpm dlx @alibaba-group/open-code-review@1.7.7 review --format json > artifacts/ocr/worktree-review.json.tmp && mv artifacts/ocr/worktree-review.json.tmp artifacts/ocr/worktree-review.json` 审查工作区。OCR 命令失败、JSON 无法解析和“未发现问题”必须分别记录，不能混为通过。

下列变更除 diff review 外，必须执行相应范围的扫描；扫描输出保存为 `artifacts/ocr/<boundary>-scan.json`，默认不提交：

```bash
pnpm dlx @alibaba-group/open-code-review@1.7.7 scan --path apps/api --format json > artifacts/ocr/api-scan.json.tmp && mv artifacts/ocr/api-scan.json.tmp artifacts/ocr/api-scan.json
pnpm dlx @alibaba-group/open-code-review@1.7.7 scan --path apps/web --format json > artifacts/ocr/web-scan.json.tmp && mv artifacts/ocr/web-scan.json.tmp artifacts/ocr/web-scan.json
pnpm dlx @alibaba-group/open-code-review@1.7.7 scan --path apps/admin --format json > artifacts/ocr/admin-scan.json.tmp && mv artifacts/ocr/admin-scan.json.tmp artifacts/ocr/admin-scan.json
pnpm dlx @alibaba-group/open-code-review@1.7.7 scan --path infra --format json > artifacts/ocr/infra-scan.json.tmp && mv artifacts/ocr/infra-scan.json.tmp artifacts/ocr/infra-scan.json
```

阻断级和本次变更引入的高风险问题必须关闭；既有基线问题和误报需附带定位证据、责任人、期限或正式驳回记录，禁止为清零进行无关重构。OCR 是补充审查，不能替代构建、测试、性能、安全、可访问性和科研数据人工审核。带 OCR 凭据的 CI 仅审查 diff，不执行不可信 PR 代码；发布 PR 评论时必须使用重试、幂等键和无法映射行号时的普通评论降级。

## 10. 交给执行智能体的统一提示词

```text
你正在执行 SoyMutDB Next 的“多物种静态科研门户”升级。先阅读：
1. docs/superpowers/specs/2026-07-12-multispecies-portal-design-spec.md
2. docs/superpowers/plans/2026-07-11-multispecies-static-portal-roadmap.md
3. README.md、docs/design/architecture.md，以及目标目录中的局部 AGENTS.md。

本任务只执行指定 Phase 的范围，禁止扩展为无关重构或提前拆分微服务。Phase 必须串行：只有提供上一 Phase 的验收证据后才可进入下一 Phase。维护公开静态端、管理控制面和发布层的隔离：公开页面不直连数据库；管理员可通过受审 API/后台任务管理发布候选，但不得直接连接或覆写生产数据库；页面、导航、索引与数据包必须使用相同 publication_release_id。

开始前：明确本阶段的用户路径、数据契约、风险、回滚方式；只从仓库根目录 `skills/` 选择技能，先读取 `skills/<skill-name>/SKILL.md`，并在交付摘要中逐条列出实际使用的 skill 名称和路径。不得使用、创建、复制或提交仓库 `skills/` 外的 skill，也绝不修改或提交默认忽略的 `skills/` 内容。若需要知乎技术栈检索而 `skills/` 中不存在对应 skill，明确记录缺口，使用官方资料替代，不得声称已调用。

实现时：遵守受约束模块配置，禁止任意脚本/模板/未净化 HTML；遵守 `dataset_release_id`（科研数据快照）与 `publication_release_id`（门户快照）的分离；所有科研实体、URL、缓存和索引都要使用合法的 global/species/assembly/dataset 作用域；完成无 JS、Worker 失效、无数据、未发布和移动端降级。所有新增自有函数、变量、模块、类型、组件、服务、脚本及测试夹具以 `rl_` 开头；第三方 API、框架约定、配置键与已有公共接口保持原名。为新增业务规则、权限判断、版本转换、清理边界和非直观性能代码写简洁中文“为什么”注释。

验证：按第 9 节的变更边界运行 Web、Admin、API、Worker、迁移或 Infra 检查，并运行 `pnpm review`。完成制品清单、SBOM、哈希和预览发布验证。使用固定版本 `pnpm dlx @alibaba-group/open-code-review@1.7.7`，设置 `OCR_NO_UPDATE=1`；在完整 Git 历史下先生成 `BASE_SHA="$(git merge-base origin/main HEAD)"` 与 `HEAD_SHA="$(git rev-parse HEAD)"`，再运行 OCR review。若涉及 API、Web、Admin 或 Infra 边界，额外运行相应 OCR scan。关闭本次引入的所有阻断/高风险问题；为历史问题或误报保留证据、责任人与期限。

交付：提交变更摘要、验证证据、publication release 影响、回滚步骤、未决风险，以及清理确认。清理时仅删除本任务生成且经过清单确认的产物；不得默认运行 `pnpm clean`（删除根 node_modules）或 `make clean-all`（删除 pnpm-lock.yaml）。不得提交 `.env`、密钥、构建缓存、临时报告或默认忽略的 `skills/` 内容。
```
