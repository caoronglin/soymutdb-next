# SoyMutDB Next 多物种门户产品与架构设计

> **已归档（2026-10-01）**：2026-08 设计波次与旧基线快照。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md；门户布局以 `docs/superpowers/specs/2026-08-14-public-web-layout-alignment-design.md` 为准。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

**状态：** 迭代设计基线  
**目标：** 将 SoyMutDB Next 从大豆专属突变数据门户升级为可治理、可发布、可回滚的多物种科研数据平台。核心运行链路固定为“管理控制台 → 静态资源生成中心 → 内部搜索 API / 外部搜索 API”。  
**依据：** `README.md`、`docs/design/architecture.md`、现有 Web/Admin/API/Worker/Rust 结构及已存在的内容、发布、组件和搜索设计。

---

## 1. 产品定位与成功标准

### 1.1 产品定位

SoyMutDB Next 是面向科研人员的数据发现、分析、比较、下载和引用门户。公开站点以静态发布和浏览器端搜索为主，管理端作为受限控制面，负责内容、数据、物种、页面模块和发布治理。

搜索采用两套完全隔离的 API：**内部搜索 API**只查询静态资源生成中心发布的本地科研数据索引；**外部搜索 API**只访问受控外部来源。它们不混用数据源、缓存、版本语义、可用性判断或结果可信度。

平台不再将“大豆”视为系统级默认实体；大豆成为首个物种适配器。后续物种必须复用同一数据模型、页面模板、搜索、发布和运维路径。

### 1.2 北极星

让研究者在可复现的物种、组装和数据发布上下文中，快速找到、理解、比较、下载并正确引用科研数据；让管理员无需改代码即可安全控制公开内容与数据发布。

### 1.3 12–18 个月目标指标

| 维度 | 指标 |
|---|---|
| 多物种 | 至少 2 个物种通过同一数据、页面、搜索和发布链路正式发布 |
| 数据发现 | 具备基本生物信息学经验的用户中，≥ 85% 在 2 分钟内找到指定基因或变异并识别其组装和数据版本 |
| 发布可靠性 | 页面、导航、下载和索引的发布快照一致性校验 100% 通过；可在既定恢复目标内完整回滚 |
| 搜索体验 | 当前物种索引在中端移动设备上不产生超过 50 ms 的主线程长任务；本地与外部结果误认率低于 10% |
| 管理效率 | 管理员可在不写代码的情况下完成物种内容、导航和模块配置，并通过预览确认影响范围 |
| 质量 | 核心公开流程键盘可用、关键状态不依赖颜色、关键页面满足 WCAG AA 目标 |

### 1.4 明确不做

- 不建设允许管理员编辑任意 HTML、JavaScript、模板表达式或 CSS 的低代码系统。
- 不让管理员直接连接生产数据库、编辑生产静态文件或绕过审核/审计。
- 不为每个物种复制页面、路由或业务服务。
- 不因“最新”而升级技术栈；升级必须有兼容性、收益、试点和回滚证据。
- 不在缺少规模或 SLO 证据时提前拆分微服务。

---

## 2. 用户、角色与核心旅程

### 2.1 用户角色

| 角色 | 核心目标 | 关键权限 |
|---|---|---|
| 访客研究者 | 发现可用物种与数据覆盖 | 浏览公开静态内容 |
| 研究者 | 查询、比较、导出、引用结果 | 公开搜索、下载和分析入口 |
| 数据管理员 | 导入、校验和管理物种数据发布 | 数据候选和质量流程 |
| 内容管理员 | 编辑页面、导航、SEO 和模块内容 | 内容及模块草稿 |
| 审核者 | 核验内容、数据和技术情报 | 审核、退回、记录意见 |
| 发布者 | 将已审核快照部署或回滚 | 生产发布及回滚 |
| 平台负责人 | 管理权限、策略和紧急治理 | 管理策略、权限与密钥引用 |
| 审计者 | 追踪操作和发布证据 | 严格只读审计访问 |

权限采用**能力集合**而不是角色层级继承。`Auditor` 永远是只读能力，不因角色层级自动继承写权限。高风险操作要求重新认证；默认提交者不得审核自己的高风险变更，审核者不得发布自己审核的高风险变更。

### 2.2 核心研究者旅程

#### 旅程 A：从物种目录进入

1. 用户访问首页或 `/species`，看到物种目录、可用组装、最新数据发布和模块覆盖。
2. 选择物种后进入物种主页；页面显示学名、俗名、组装、数据发布、来源、引用和模块状态。
3. 用户进入 Genes、Variants、Lines、Browser 或 Downloads。
4. 若目标模块未发布，显示“未发布/无数据/维护中”原因、可用替代入口和预期动作，而不是空表或死链。

#### 旅程 B：已知对象直接搜索

1. 用户通过顶部搜索、首页搜索或命令面板输入基因 ID、变异坐标、材料 ID 或关键词。
2. 搜索首先返回当前物种的已发布静态索引；用户可明确切换为“全部物种”。
3. 结果按对象类型分组，且每项显示物种、组装、数据版本、来源、匹配原因和稳定链接。
4. NCBI、UniProt、Ensembl 等结果显示在独立“外部来源”区，不能与本地数据混排。

#### 旅程 C：筛选、比较、导出与引用

1. 用户在数据浏览页按照物种、组装、发布、坐标、影响、表型、材料和实验条件筛选。
2. 把对象加入比较篮或导出篮；跨物种、跨组装时必须显示限制和同源/映射证据。
3. 下载包与引用信息固定绑定数据发布版本、来源、许可和生成时间。

### 2.3 核心管理员旅程

#### 旅程 D：新增物种和数据发布

1. 数据管理员创建物种档案、组装和数据发布候选。
2. 系统校验字段映射、坐标规则、来源、许可、行数、错误和引用信息。
3. 管理员启用目标模块并配置物种主页内容。
4. 生成搜索索引和静态预览，审核后形成发布快照。

#### 旅程 E：隐藏或调整模块

1. 内容管理员选择模块及范围：全局、物种、组装、数据发布或语言。
2. 管理端展示影响：导航、首页卡片、站点地图、搜索筛选、路由与深链。
3. 用户查看桌面及移动端预览，提交审核。
4. 发布成功后，公开站点以新快照整体切换；失败则继续服务旧快照。

#### 旅程 F：回滚发布

1. 发布者在发布中心选择历史 `publication_release_id`。
2. 系统验证该快照引用的下载、索引和兼容服务仍在保留窗口内。
3. 重新认证并记录审计事件后，原子切换当前公开指针。
4. 健康检查确认 HTML、索引和数据包均来自目标快照。

---

## 3. 信息架构与 UI/UX

### 3.1 公开端信息架构

```text
Discover
  /species
  /species/:speciesSlug
Explore
  /species/:speciesSlug/assemblies/:assemblyAccession/releases/:datasetReleaseVersion/genes
  /species/:speciesSlug/assemblies/:assemblyAccession/releases/:datasetReleaseVersion/variants
  /species/:speciesSlug/assemblies/:assemblyAccession/releases/:datasetReleaseVersion/lines
Analyze
  .../browser
  .../compare
Search
  /search?scope=species|all&species=...&assembly=...&release=...&q=...
Resources
  .../downloads
  /publications
  /guide
  /help
```

短路由（如旧的 `/genes`、`/variants`）仅在能够唯一解析默认公开物种、组装和数据发布时 302 到 canonical URL；否则显示说明性迁移页面，不猜测目标。

### 3.2 全局科研上下文

每个科研数据页在主导航下方提供 `rl_species_context_bar`：

```text
Glycine max（Soybean）  |  Wm82 v4.0  |  Dataset 2026.07
[切换物种] [切换组装] [查看来源与引用]
```

- 桌面端常驻；移动端压缩为可展开按钮。
- 切换时提示会被清除的筛选、目标物种中不可用的模块及目标数据版本。
- 详情、下载、浏览器、比较和共享链接均含完整上下文。

### 3.3 页面组件与体验规则

| 产品组件 | 行为 |
|---|---|
| `rl_species_switcher` | 支持俗名、学名、别名搜索；展示可用模块和发布状态 |
| `rl_module_availability_guard` | 统一处理无数据、未发布、维护、隐藏和下线状态 |
| `rl_scientific_breadcrumbs` | 显示物种 → 组装 → 模块 → 对象路径 |
| `rl_search_scope_control` | 明确当前物种/全部物种、索引版本和外部结果范围 |
| `rl_comparison_basket` | 保存比较/导出项，显示跨物种与跨组装限制 |
| `rl_release_impact_preview` | 在管理端展示模块配置变更影响的页面和入口 |

### 3.4 响应式与无障碍

- **桌面：** 常驻科研上下文、固定筛选器、宽表支持列固定与横向滚动。
- **平板：** 上下文压缩为一行，筛选器折叠为抽屉，表格保留可横向查看能力。
- **手机：** 上下文优先可见；筛选使用抽屉；表格改为关键字段卡片；关键操作不依赖 hover。
- 物种/组装切换器、筛选抽屉、比较篮与命令面板支持完整键盘操作和焦点管理。
- 搜索结果和索引加载使用非打断式 `aria-live`；图表提供文字摘要和数据下载；状态采用文字、图标和颜色三重表达。
- 所有动效遵循 `prefers-reduced-motion`；动效只用于进入、切换和加载反馈，不影响科学数据阅读。

---

## 4. 功能设计

### 4.1 物种、组装与数据发布

核心关系：

```text
Species
  └─ Assembly
      └─ DatasetRelease
          ├─ Gene / Transcript
          ├─ Variant / MutantLine / Phenotype
          ├─ Expression / Annotation
          └─ Evidence / Provenance
```

关键规则：

- `Species` 同时拥有不可变内部 UUID 与不可变 public slug；学名、俗名和别名可更新。
- `Assembly` 使用稳定 accession；同一物种同一时刻最多一个默认公开组装。
- `dataset_release_id` 是科研数据快照，必须用于科研对象、坐标、下载项、缓存键和搜索文档。
- 外部 ID 存为命名空间别名；不得根据同名基因、染色体或坐标自动推断跨物种等价关系。
- 第二物种必须经过真实导入、质量校验、索引、下载、引用和正式发布，不接受仅展示 UI 壳层。

### 4.2 内容、导航与模块配置

管理员通过受约束的结构化配置控制公开体验：

```text
Page
  route / locale / SEO / publication state / ModuleInstance[]

ModuleInstance
  registered type / validated config / sort order / scope / fallback copy

ModuleAvailability
  scope: global | species | assembly | dataset | language
  state: Draft | Preview | Published | Hidden | Deprecated
  rule: time window | data dependency
```

规则：

- 范围优先级：`dataset > assembly > species > global`；同一优先级存在多个发布规则时，发布校验失败。
- `Hidden` 从导航、站点地图和新列表移除，但已发布科研详情保持 200 并显示当前不可导航状态。
- `Deprecated` 保持 200、`noindex` 和替代链接；未发布/不存在的对象返回 404。
- 时间窗口仅在构建快照时按 UTC 计算；禁止按登录身份、Cookie、IP 或其他请求期受众属性改变已发布科研内容。
- 禁止管理员输入任意脚本、模板表达式、内联 CSS 或未经净化的 HTML。

### 4.3 发布、预览与回滚

`publication_release_id` 是公开门户快照，与 `dataset_release_id` 严格分离。

```text
草稿编辑
→ Schema 校验
→ 影响分析
→ 私有预览
→ 审核
→ PublicationManifest 冻结
→ 生成页面、索引、下载清单和制品
→ 完整性/安全/体验检查
→ 原子切换
→ 监控与审计
```

`PublicationManifest` 至少包含：

| 字段 | 用途 |
|---|---|
| `publication_release_id` | 门户快照标识 |
| `manifest_schema_version` | 清单兼容性 |
| `content_versions` | 固定的内容版本输入 |
| `dataset_release_ids` | 被公开引用的数据发布集合 |
| `config_hashes` | 页面、导航和模块配置完整性 |
| `search_assets` / `download_assets` | URL、SHA-256、大小和版本 |
| `build_metadata` | Git commit、lockfile 哈希、构建工具版本、时间 |
| `artifact_root` | 不可变制品根路径 |
| `previous_release_id` | 回滚引用 |

构建只读取事务性冻结输入；构建期间的新草稿不进入当前快照。失败制品进入隔离前缀，只有清单及哈希验证通过后才更新公开指针。至少保留最近 12 个发布快照和制品。

### 4.4 静态搜索与外部搜索

搜索不是单一服务，而是由静态资源生成中心供给的**内部搜索 API**与独立的**外部搜索 API**组成。公开前端以两个明确分区消费结果，不得在 API、缓存或 UI 结果列表中合并它们。

#### 4.4.1 内部搜索 API：查询已发布静态资源

```text
DatasetRelease
→ Search Document Builder
→ species/type/language 分片
→ SearchManifest
→ Immutable static artifacts
→ Internal Search API
→ canonical 静态详情页 / 下载 / 引用
```

内部搜索 API 只读取已发布 `PublicationManifest` 引用的 SearchManifest 与不可变索引/分区数据。它不能查询草稿、候选数据、生产数据库的未发布记录或任何外部来源。每一个结果都必须可追溯到 `publication_release_id` 与 `dataset_release_id`。

`SearchManifest` 应包含 schema 版本、`publication_release_id`、作用域、语言、URL、SHA-256、压缩/未压缩大小、内存估算、记录数和生成时间。

搜索文档字段：

```json
{
  "id": "gene-glyma-01g000100",
  "type": "gene",
  "scope": "dataset",
  "title": "Glyma.01G000100",
  "aliases": ["..."],
  "species": "glycine-max",
  "assembly": "wm82-v4",
  "dataset_release": "2026-07",
  "summary": "...",
  "canonical_url": "/species/...",
  "source": "local"
}
```

- `global` 文档的三层数据范围字段为 `null`；`species` 仅物种必填；`assembly` 要求物种和组装；`dataset` 三者必填。
- 查询进行 Unicode NFKC、case folding、空白折叠和别名规范化；按 `type + canonical_url` 去重；稳定排序为精确 ID、前缀、别名、标题、描述。
- 内部 API 请求必须包含 `q`、`scope`、`species`、`assembly`、`dataset_release`、`types`、`filters`、`cursor`、`limit` 与可选 `publication_release_id`。未指定快照时仅查询当前 active publication；指定历史快照时只在保留期内提供只读结果。
- 内部结果使用稳定 cursor 分页，返回 `result_id`、`type`、`canonical_url`、物种/组装/数据发布、命中解释、索引版本和 `publication_release_id`。排序固定为精确 ID、前缀、别名、标题、描述；不得因外部来源响应改变内部排序。
- Internal Search API 的缓存键必须包括 query 规范化结果、完整过滤条件、locale、`publication_release_id` 和 schema 版本。发布切换后，新快照使用新缓存命名空间；旧快照缓存只在保留期内只读服务。
- 小型公开索引可由浏览器 Worker 作为可选离线增强，但它必须使用内部 API 同一 query/result 契约；Worker 失败时回退内部 API，而不是回退主线程全量过滤。离线模式只查询已缓存且明确标记版本的分片。

#### 4.4.2 外部搜索 API：受控外部科研查询

外部搜索 API 与内部搜索 API 是独立系统。它通过 FastAPI adapter 查询 NCBI、UniProt、Ensembl、EMBL-EBI 等外部来源，但不读取内部静态索引，也不将外部结果写入内部 SearchManifest 或公开发布快照。

```text
用户外部查询
→ External Search API
→ source-specific adapter
→ allowlist / rate limit / timeout / circuit breaker
→ short-lived external cache
→ 标准化外部结果或来源降级状态
```

规则：

- 浏览器不得直连第三方。外部 API 执行来源 allowlist、限流、超时、重试、缓存、HTML 净化和 circuit breaker。
- 外部缓存与内部缓存物理/逻辑隔离，缓存键包括来源、规范化 query、请求参数、adapter 版本和响应 schema 版本；不包含 `publication_release_id`。
- 外部结果返回 `source_name`、`source_url`、`source_record_id`、`retrieved_at`、`adapter_version`、可用性状态和明确的 `result_origin: external`；不得伪装为本地 dataset 或本地 canonical URL。
- 外部 API 不保存完整科研查询与可关联用户身份的长期关联；按隐私策略保留最小化聚合指标。
- 任何来源失败只影响该来源分区。外部 API 故障不得影响内部搜索 API、公开静态页面、下载或发布。

#### 4.4.3 前端搜索呈现与错误策略

```text
搜索结果页
├─ 已发布本地数据（Internal Search API）
│  ├─ 当前物种/全部物种范围、publication release、索引更新时间
│  └─ 可进入详情、比较、导出和引用
└─ 外部科研来源（External Search API）
   ├─ 按 NCBI / UniProt / Ensembl 等来源分组
   ├─ 标识实时查询、来源时间和离开本站提示
   └─ 只可打开来源页或显式“导入为候选数据”流程，不能直接加入本地发布数据
```

- 内部 API 无结果时，前端展示实际生效的本地范围、筛选和可执行的扩大范围建议；不把外部结果当作本地补充结果。
- 外部 API 或单一来源失败时，保留内部结果并显示“外部来源暂不可用”；不能把整个搜索页显示为空或失败。
- 用户点击“加入比较/导出”只作用于内部已发布结果。外部结果只能保存外部书签或进入受审核的候选导入流程。

### 4.5 审计与数据治理

- 权限提升、删除、发布和回滚要求重新认证。
- 高风险操作在业务事务内写入具备幂等键的 audit outbox；独立投递器写入保留存储并构造哈希链。
- 审计投递失败时不得切换发布状态，必须重试或补偿，避免“操作成功但无审计”。
- 审计至少保留 365 天；不可由管理员普通编辑或删除；保留作业的清理行为本身也要记录证明。
- 所有科研数据记录来源、许可、版本、导入时间、转换规则和引用方式。

---

## 5. 架构与实现边界

### 5.1 控制面、发布面、公开面

```text
管理控制台（Admin / Tauri）
  全局权限、物种/数据、内容/模块、审核、发布、审计、技术雷达
                               │ 已审核的配置与数据候选
                               ▼
静态资源生成中心
  FastAPI 编排 + Celery Worker + Web SSG + Search Builder
  冻结 Manifest、生成 HTML/JSON/索引/下载包、校验、打包、签名、回滚制品
                               │ Immutable artifacts + active publication pointer
             ┌─────────────────┴─────────────────┐
             ▼                                   ▼
内部搜索 API                              Nginx / CDN 公开资源
  查询已发布本地索引                         HTML、JSON、下载包、站点地图
  固定 publication/dataset 快照                       │
             │                                      ▼
             └─────────────── 公开前端 ────────────┐
                                                    │ 外部查询（独立路径）
                                                    ▼
                                             外部搜索 API
                                             source adapters → NCBI/UniProt/Ensembl
                                             短期缓存、限流、熔断；不读取内部索引
```

### 5.2 现有模块处理策略

| 现有资产 | 决策 |
|---|---|
| `apps/web` React/Vite/SSG | 保留并泛化路由、上下文和静态构建输入 |
| `apps/admin` React/Tauri | 保留；重组为任务工作区，补全发布治理与权限测试 |
| FastAPI | 保留；分为发布编排、内部搜索 API、外部搜索 API 三个明确边界 |
| Celery/Redis | 保留；导入、校验、构建、预热、审计投递和索引任务；内部/外部搜索缓存命名空间隔离 |
| Rust/Axum | 暂缓扩展；仅在性能基线证明需要时承担热路径 |
| Widget/PageLayout | 泛化为注册模块、范围化可见性和 manifest 输入 |
| Dynamic Widget | 默认迁移为构建期；科研运行时组件必须绑定发布/数据快照 |
| 大豆硬编码导航、染色体与文案 | 迁移为物种配置；验证后删除旧分支 |

### 5.3 代码约定

- 新增自有函数、变量、模块、类型、组件、服务、脚本和测试夹具以 `rl_` 开头。
- 不修改第三方 API、框架约定、环境变量、既有列、配置键、已有公共接口或导出以强加此前缀。
- 新增业务规则、权限判断、发布版本转换、清理边界与非直观性能处理必须有简洁中文“为什么”注释。

---

## 6. 技术栈与打包策略

### 6.1 技术决策

| 领域 | 决策 | 原因 |
|---|---|---|
| React/Vite/TanStack Router | 保留，按稳定版本升级 | 已与 SSG、现有路由和共享组件匹配 |
| Web Worker | 保留并用于分片静态搜索 | 避免大索引阻塞主线程 |
| FastAPI/SQLAlchemy/Alembic | 保留 | 满足 API、管理、迁移和异步数据边界 |
| PostgreSQL/Redis/ClickHouse | 保留 | 分别承载业务事实、缓存锁和分析，避免功能重叠 |
| Celery | 保留 | 适合导入、索引、构建、审计投递等后台任务 |
| Rust/Axum | 暂缓扩展 | 仅在测量到 Python 热点后引入，避免双实现成本 |
| Open Code Review | 引入固定版本门禁 | 用于补充语义代码审查，不替代测试 |
| SBOM/制品哈希 | 引入 | 提供供应链、回滚和发布可追溯性 |
| 独立搜索服务 | 暂缓 | 仅在索引大小、构建频率或查询指标证明浏览器静态搜索不够时引入 |

### 6.2 打包矩阵

| 制品 | 输入 | 输出 | 必须附带 |
|---|---|---|---|
| Web SSG | 发布 manifest、静态内容、数据快照、前端 lockfile | HTML、JS/CSS、压缩资源、静态实体页 | 哈希、构建版本、页面/索引一致性 |
| Internal Search | 已发布数据分区、别名表、公开字段白名单 | SearchManifest、不可变分片索引 | schema、hash、大小、记录数、publication/dataset 版本 |
| External Search | 来源 allowlist、adapter 配置、短期缓存策略 | 不生成发布制品；仅运行时标准化结果 | 来源、adapter/schema 版本、检索时间、可用性状态 |
| Admin Web/Tauri | 管理端源代码、lockfile | Web bundle / 原生包 | commit、依赖版本、SBOM |
| API/Worker | Python lockfile、迁移版本 | 容器/部署制品 | Python 版本、SBOM、健康检查 |
| Rust | Cargo.lock、源码 | 内部二进制 | Cargo 版本、hash、基准链接 |
| 发布清单 | 上述全部已验证制品 | `artifacts/manifest.json` | 制品路径、大小、SHA-256、SBOM、commit、发布时间 |

发布器只能消费已验证制品清单，不能直接发布工作区目录。任何构建失败均不能覆盖当前公开版本。

---

## 7. 分阶段迭代路线

### Phase 0：审计与 ADR

**目标：** 盘点现有功能、路由、硬编码、数据模型、权限、动态组件、构建链和死代码候选。

**交付：** 基线报告、技术债清单、数据/内容来源清单、风险矩阵、ADR 初稿、不可修改边界。

**验收：** 已有当前失败与新增失败的区分；已确定第二物种选择标准；没有在此阶段重构业务逻辑。

### Phase 1：领域标识、权限与审计

**目标：** 建立多物种数据内核、兼容迁移、能力权限和可靠审计。

**交付：** `Species/Assembly/DatasetRelease`、旧 ID/URL 映射、allow/deny 测试、再认证、审核隔离、audit outbox、审计保留方案。

**验收：** staging 完成升级/降级和备份恢复；大豆双读差异低于既定阈值；Auditor 无写能力。

### Phase 2：发布快照、制品和回滚

**目标：** 建立 `PublicationManifest`、可复现构建、SBOM、制品清单、预览和原子回滚。

**交付：** 快照模型、构建矩阵、`artifacts/manifest.json`、预览环境、回滚运行手册。

**验收：** 同一冻结输入得到一致内容哈希；预览只消费已验证制品；回滚恢复完整快照。

### Phase 3：管理员控制面

**目标：** 让管理员安全管理物种、数据、内容、导航、模块、审核和发布。

**交付：** 重组后的管理信息架构、模块 Schema、范围化可见性、影响预览、审核/发布界面及测试。

**验收：** 未审核变更不可公开；关闭模块不会留导航孤岛、死链或搜索不一致。

### Phase 4：多物种公开 UI/UX

**目标：** 让物种、组装和发布版本成为所有公开旅程的可见上下文。

**交付：** 多物种路由、物种目录/主页、通用数据浏览、响应式组件、无障碍用例、兼容路由策略。

**验收：** 移动端能完成筛选、详情与下载；无数据/下线/跨组装状态有明确下一步。

### Phase 5：双搜索 API

**目标：** 提供完全隔离的内部搜索 API 与外部搜索 API，前端明确区分已发布本地数据和外部实时结果。

**交付：** Internal Search API、SearchManifest、索引构建器、共享查询/结果契约、历史快照查询策略；External Search API、source adapter、短期缓存、熔断与来源状态；前端双分区与离线/低网络策略。

**验收：** 内部 API 只返回已发布本地快照结果，外部 API 不读取或写入内部索引；结果、缓存、错误和可用性完全隔离；Worker 故障回退内部 API 不造成主线程冻结；内部索引无敏感字段。

### Phase 6：第二物种正式发布

**目标：** 用真实第二物种验证复用架构。

**交付：** 第二物种数据导入、质量验证、组装、发布、索引、下载、引用和静态页面。

**验收：** 两个物种复用同一模型、页面、搜索、构建和发布链路，无复制实现。

### Phase 7：技术情报、性能与可靠性

**目标：** 建立证据驱动的技术升级和性能优化机制。

**交付：** 技术雷达、升级 ADR、性能基线/优化对比、监控、告警、健康检查和事故手册。

**验收：** 每项技术升级有官方证据、试点和回滚；性能优化有前后指标。

### Phase 8：清理、全量回归与运营交接

**目标：** 清除确认无用内容，完成全量验证和运维交接。

**交付：** 删除清单、引用分析、回归报告、发布/回滚演练、管理员指南、架构和运行文档。

**验收：** 无未解释高风险问题；任何删除项均有验证与回滚依据；后续团队可以独立维护。

---

## 8. 质量门与运营

### 8.1 检查分层

- Web：lint、typecheck、Vitest、SSG build、Playwright、无 JS、Worker 故障和移动端检查。
- Admin：lint、typecheck、构建、能力权限 UI 与 API 集成测试。
- API/Worker：pytest、Ruff、mypy、迁移测试、数据质量和外部 adapter 契约测试。
- Infra：容器构建、Nginx/CSP、健康检查、预览发布和回滚演练。
- 数据：来源/许可、坐标范围、别名、版本、统计和双读差异校验。

### 8.2 Open Code Review

使用固定的官方 `@alibaba-group/open-code-review` 版本。每个重大阶段的 diff 必须运行 `review`；数据、API、Web、Admin、Infra 边界变更额外运行对应 `scan`。OCR 输出 JSON 作为审查证据，但不能替代确定性测试、安全检查、可访问性检查和科研数据审核。

OCR 凭据仅来自密钥管理；CI 使用完整 Git 历史，禁止在带凭据环境执行不可信 PR 代码。阻断级及本次引入的高风险问题必须关闭；历史问题和误报要有证据、责任人及期限。

### 8.3 性能和可靠性预算

| 项目 | 初始预算 |
|---|---|
| 静态页 TTFB | 维持 README 的低延迟目标 |
| 缓存组件 | P95 < 50ms |
| 内部 API | P95 < 200ms |
| Web Vitals | 所有核心指标 Good |
| 当前物种搜索索引 | 压缩 ≤2MB、未压缩 ≤8MB、≤10,000 文档、预计内存 ≤24MB |
| 主线程降级搜索 | 总预算 ≤150ms，必须分批且可取消 |
| 发布 | 新快照只在完整制品验证后原子切换 |
| 回滚 | 恢复完整 HTML、索引、下载和兼容服务版本 |

---

## 9. 清理策略

清理是产品迭代的一部分，但必须保守执行：

1. 建立候选清单：死代码、过期组件、重复配置、废弃依赖、临时报告、旧索引、无引用构建脚本。
2. 对每项执行引用搜索、运行时路径检查、测试和发布影响分析。
3. 先迁移或弃用，再删除；保留兼容期和回滚说明。
4. 禁止默认运行会删除依赖或锁文件的全局清理命令。
5. 不删除 lockfile、密钥、有效制品、当前发布快照或其他任务产物。

---

## 10. 实施约束

实施智能体需要显式从仓库根目录 `skills/` 选择并声明实际使用的 skills。重点任务通常需要：

| 任务 | 仓库内 skill |
|---|---|
| 产品拆解 | `skills/feature-planning/SKILL.md` |
| Vite / 打包 | `skills/vite/SKILL.md`、`skills/pnpm/SKILL.md`、`skills/turborepo/SKILL.md` |
| 前端体验 | `skills/frontend-design/SKILL.md`、`skills/react-best-practices/SKILL.md` |
| 测试 | `skills/test-driven-development/SKILL.md`、`skills/playwright-skill/SKILL.md`、`skills/webapp-testing/SKILL.md` |
| 后端与数据 | `skills/fullstack-dev/SKILL.md`、`skills/sql-expert/SKILL.md` |
| UI/无障碍评审 | `skills/web-design-guidelines/SKILL.md` |
| 重构和清理 | `skills/code-refactor/SKILL.md` |
| 验证 | `skills/code-reviewer/SKILL.md`、`skills/verification-before-completion/SKILL.md` |

当前仓库未发现知乎命名 skill。技术栈调研需优先采纳官方文档、官方 Release、官方仓库、标准组织和同行评议资料，并在交付中如实记录该 skill 缺口。

---

## 11. 最终交付物

每个阶段结束必须交付：

1. 功能与架构变更说明；
2. 用户旅程和 UI/UX 变化；
3. 数据/接口/配置契约变化；
4. 使用的 skills 与路径；
5. 测试、构建、OCR、性能和安全证据；
6. 制品清单、发布影响和回滚步骤；
7. 清理项目及引用分析；
8. 已知风险、责任人、截止时间与下一阶段输入。

没有验证证据时，不得声明某阶段完成。

---

## 12. 深化优化方案：从内容门户升级为科研数据平台

现有方案已覆盖内容、页面模块和静态发布，但科研数据能力仍需优先深化。下列优化按依赖顺序执行；P0 未完成前，不应大规模扩展管理 UI、逐实体静态页或跨物种比较。

### 12.1 P0：版本化数据导入契约与隔离区

建立统一的 `rl_species_adapter` 边界，而不是让每个物种直接写入发布表：

```text
SourceFile
→ RawAsset（不可变原始文件 + checksum）
→ NormalizedRecord（统一字段/单位/坐标）
→ ValidatedRecord（规则、词表、去重验证）
→ CandidateDatasetRelease（待审核发布候选）
→ DatasetRelease（已批准科研数据快照）
```

**统一契约要求：**

| 内容 | 规则 |
|---|---|
| 必填元数据 | source URL、许可、来源版本、导入者、导入时间、转换规则版本、原始文件 SHA-256 |
| 坐标 | 明确 `assembly_id`、contig namespace、坐标系统、单位与边界规则 |
| 空值 | 区分 unknown、not-applicable、withheld；禁止用空字符串表达不同含义 |
| 去重 | 使用来源命名空间 ID + assembly + 坐标/对象身份；冲突进入人工复核 |
| 可重跑 | `source_hash + adapter_version + mapping_version` 为幂等导入键；同输入重跑产生一致输出哈希 |
| 隔离 | 不合格记录只进入 quarantine，不能污染候选或已发布数据 |

`rl_species_adapter` 只负责字段识别、本体/命名空间映射、坐标与单位规范化和质量报告；不得直接发布、定义页面逻辑、绕过搜索构建器或生成物种专属 URL。

#### 数据平面 ADR（首次实现前阻断）

不能假定全部版本化变异和导出事实都存入 PostgreSQL。先以真实大豆和第二物种样本完成基准，再冻结以下分层：

| 数据类别 | 默认存储 | 不可变与查询规则 |
|---|---|---|
| 物种、组装、发布状态、权限、审计、对象目录 | PostgreSQL | 强事务事实；保存分区引用、行数、哈希和状态，不保存海量原始变异正文 |
| 原始输入、隔离记录、规范化快照、质量明细、下载包 | 对象存储 | 内容寻址、版本化保留；RawAsset 不可修改 |
| 大规模 Gene/Variant/Line 规范化数据 | Parquet 分区对象 | 按 `species/assembly/dataset_release/entity_type/contig` 分区；不可变快照 |
| 导出和批量查询 | 分区 Parquet 查询引擎或受控 Worker | 从已验证分区读取；任务输出引用输入分区和 hash |
| 缓存与锁 | Redis | 可丢失，不是科研事实或发布事实来源 |
| 产品分析 | ClickHouse | 仅最小化聚合事件，不保存原始科研数据源 |

`PublicationManifest` 必须引用数据分区路径、分区 hash、schema 版本和保留期。PostgreSQL 事务负责候选发布元数据与分区引用的原子提交；对象存储写入先完成并校验，再允许候选状态切换。

**新增管理员体验：** 导入采用五步向导：目标上下文 → 文件检测 → 字段/坐标映射 → 来源/许可/引用 → 质量报告与提交。失败任务必须提供错误代码、记录样例、推荐修复、保留配置后的重试与安全取消。

**验收：** 相同输入可安全重跑；每次候选发布有输入/输出行数平衡表、拒收清单和规则版本；第二物种不新增专用业务表或独立导入链路。

### 12.2 P0：稳定科研对象身份与跨版本生命周期

当前 `dataset_release_id` 表示记录快照，但不能代替科研对象身份。应增加三层模型：

```text
StableScientificObject
  跨数据发布稳定的逻辑对象和 public ID

DatasetRecordVersion
  某 DatasetRelease 内对象的版本化事实、来源与校验状态

PublicationProjection
  某 PublicationManifest 内公开的页面、搜索、下载和引用投影
```

生命周期状态：`added`、`unchanged`、`changed`、`withdrawn`、`merged`、`split`。撤回对象保留可解释 tombstone 页面，显示撤回原因、最后有效版本、替代对象（如有）和引用提示，不能无声 404。

第一期禁止通用自动合并。每类实体拥有独立身份策略：

| 实体 | 第一期稳定身份 | 禁止自动合并条件 |
|---|---|---|
| Gene | 来源提供的稳定 namespace ID + assembly；无稳定来源 ID 时为 `unresolved` | 同名、同坐标或相似别名不能自动合并 |
| Transcript | 来源稳定 transcript ID + 父 Gene 来源关系 | 仅相同 exon 结构不能自动合并 |
| Variant | 来源 variant ID；若无则来源、assembly、规范化坐标、REF/ALT 的复合自然键 | 不同来源的同位置/等位基因须人工确认 |
| MutantLine | 来源材料 accession + 来源 namespace | 相同展示名称不能自动合并 |
| Phenotype | 版本化观测记录，含本体、方法、单位和实验条件 | 数值相同不表示同一观测 |

`merged`、`split`、`withdrawn` 只能由数据管理员基于来源证据创建显式关系；关系记录必须含判定人、原因、来源和生效 release。无法确定时保持 `unresolved`，不生成 StableScientificObject 关系。

**验收：** 旧稳定链接在新发布后仍能解析；系统能生成相邻 release 的 change set；同 ID 冲突、合并和拆分均要求人工复核与审计。

### 12.3 P0：受控词表、分类学与证据模型

为多物种筛选、比较和可重复引用建立受控语义层：

- 物种：NCBI Taxonomy ID、学名、别名及分类学版本；
- 功能影响：Sequence Ontology ID 与版本；
- 表型/性状：受控本体 ID、方法、单位、实验条件；
- 基因/蛋白：命名空间、外部 ID、同义词来源；
- 证据：来源类型、方法、置信度、版本、许可和审核状态。

自由文本可作为补充说明，但不得成为筛选、比较或生物学等价判断的主键。未知映射必须显式标记，不能伪装为标准术语。

### 12.4 P0：静态制品规模模型与混合呈现策略

不得默认逐变异生成静态 HTML。Phase 0 需使用真实大豆和第二物种样本建立页面基数模型：实体数、页面数、文件数、制品大小、构建时长、CDN 失效成本和回滚成本。

| 实体规模/用途 | 呈现策略 |
|---|---|
| 物种、组装、发布、帮助、下载、热门基因 | 预生成静态页面 |
| 普通基因/材料 | 静态壳 + 不可变版本化 JSON 数据文件，按需加载 |
| 海量变异 | 染色体/坐标分区数据、预生成浏览目录和搜索索引；不逐变异建 HTML |
| 机器下载 | 不可变压缩包、字段字典、校验和、manifest 和引用文件 |

SSG、浏览器 Worker 与未来只读搜索服务必须共享查询/结果契约；当索引体积、内存、首查延迟或构建频率超出预算时，切换到服务端实现而不改写前端语义。

每个 canonical 详情 URL 的最低 HTML 内容必须包含对象标题、物种、组装、数据发布、摘要、出处、引用、无数据/撤回状态和增强数据加载失败说明；JSON 只增强大表、轨道和附加字段。HTML 与 JSON 必须由同一 manifest 原子发布并保留至该快照过期；JSON hash 失败、缺失或禁用 JavaScript 时，详情页仍保持可读、可引用、可回滚。

### 12.5 P0：收敛构建期与运行时组件链路

对现有 `/widget/{name}`、运行时 HTML fragment、动态搜索与 Rust widget 渲染写 ADR，明确：

1. 科研内容默认构建期静态化，公开页面不依赖运行时 HTML 拼装；
2. 类型化组件接收 JSON 数据契约，禁止将 HTML fragment 作为科研内容主协议；
3. 公开科研事实只能从 manifest 固定的不可变 JSON、静态数据文件或 publication-pinned 只读 API 获取；运行时服务不得决定科研内容、导航、可见性或引用；
4. 实时组件只允许展示不影响科研事实、导航、引用或模块可见性的运行状态，并进入白名单；
5. 每个保留的 runtime widget 有负责人、业务理由、退场期限和错误降级策略。

### 12.6 P0：发布状态机与端到端可观测性

发布不是线性脚本，应为可恢复状态机：

```text
DatasetReleaseApproval:
draft → validating → candidate → awaiting_data_approval → approved | rejected

PublicationBuild:
draft → input_frozen → building → verifying → awaiting_publication_approval
→ approved_for_deployment | failed | cancelled

Deployment:
pending → publishing → active | failed | cancelled
rollback_requested → deploying_previous_snapshot → active
```

审批总是绑定不可变输入 hash：数据审批绑定 CandidateDatasetRelease hash，发布审批绑定已验证 manifest hash；任一输入变化即使审批失效。每步记录输入哈希、输出哈希、attempt、lease、heartbeat、幂等键、补偿动作和操作者。公开指针切换采用数据库并发控制或 fencing token，确保两个发布不能同时切换同一环境。回滚创建新的 Deployment attempt，将历史快照重新设为 active，不修改原快照的历史状态。

从 Phase 1 开始统一传播：`request_id`、`import_job_id`、`dataset_release_id`、`publication_release_id`、`build_id`。通过 OpenTelemetry/OTLP 接入浏览器、FastAPI、Celery、PostgreSQL、Redis 和外部 HTTP；标签不包含完整搜索词、用户 ID、Cookie 或高基数查询参数。

**必须告警：** 数据新鲜度超期、索引分片缺失/哈希失败、制品验证失败、发布步骤超时、CDN 快照不一致、Worker 查询加载失败、回滚失败。

---

## 13. 研究者功能优化

### 13.1 数据出处与引用成为一级功能

在详情、搜索、比较、下载与导出完成页提供统一 `rl_provenance_citation_panel`：

| 信息 | 内容 |
|---|---|
| 快照 | dataset release、publication release、assembly accession |
| 证据 | 原始来源、论文/实验、转换规则版本 |
| 权利 | 实际适用许可与再分发限制 |
| 完整性 | SHA-256、大小、生成时间、字段字典 |
| 引用 | DOI/稳定 URL、文本引用、BibTeX、RIS |

比较报告与导出包自动生成引用清单，合并所涉及的发布、来源和许可证；跨版本比较必须显式显示“不是同一数据快照”。

### 13.2 研究集合、批量输入与异步导出

将单纯表格筛选扩展为可复现研究集合：

- 支持粘贴或上传最多 1,000 个基因 ID、坐标或材料 ID；返回命中、未命中与歧义项；
- 筛选条件写入 canonical URL，可保存为命名查询和只读分享链接；
- `rl_comparison_basket` 同时作为导出篮，显示对象数量、跨版本限制和不可用项；
- 异步导出页显示筛选表达式、预估记录数、字段、格式、版本、许可和进度；
- 导出结果附原始查询、数据版本、引用、字段字典、校验和和重试入口。

超大导出应推荐按染色体分区、调用机器接口或生成压缩包，避免长时间阻塞浏览器请求。

### 13.3 跨物种比较的窄范围承诺

第一期只承诺**基因正交关系查找与并列展示**，不承诺 liftover、任意变异、表型和表达的跨物种等价比较。

比较关系必须包含 ortholog group、方法、来源、版本、置信度和审核状态。比较结果分为：

- 上下文一致：同物种、同组装、同数据发布；是否可比较仍由对象类型、方法、单位、实验条件和证据规则决定；
- 版本差异：同物种/组装、不同数据发布，展示 change set，不暗示测量结果可比；
- 正交并列：跨物种且具有正交关系证据，仅并列展示，禁止暗示表型或变异等价；
- 不可比较：缺少所需证据时明确阻止比较操作。

不同组装 liftover 是独立 ADR 和后续阶段能力，需要明确 chain 来源、方向、坐标语义、验证数据集和失败规则后才可规划。

### 13.4 FAIR 与机器可访问能力

每个公开发布提供：版本化 metadata API 或静态 JSON、公开 manifest、批量下载清单、字段字典、LICENSE inventory、CITATION、checksums；评估 JSON-LD/Bioschemas 与 DOI/DataCite 对接。机器响应必须带 assembly、dataset release 和 schema version，优先 REST/静态 JSON，不引入 GraphQL。DOI 是可选字段；没有 DOI 时使用稳定 URL 和版本化引用，不得显示占位 DOI。组合导出生成逐来源许可清单和兼容性结果；许可不兼容时阻断组合导出，而不是自动“合并许可证”。

### 13.5 隐私友好的分析

分析事件采用最小化字典和聚合阈值；完整搜索词默认不长期保存，不将可关联身份和科研查询长期组合存储。分析系统失败不得影响公开门户。管理端只展示达到最小聚合量的查询趋势。

---

## 14. 管理端与体验优化

### 14.1 管理端重组

将当前按技术实体划分的侧栏重组为任务工作区：

```text
工作台
  待我处理 / 失败任务 / 待审核 / 当前发布健康
数据发布
  物种与组装 / 数据候选 / 导入与质量报告 / 搜索与下载制品
站点内容
  页面与导航 / 模块配置 / 多语言内容 / 预览与影响分析
发布中心
  审核队列 / 发布快照 / 健康检查 / 回滚
治理
  成员与能力权限 / 审计 / 许可与保留策略 / 技术雷达
```

菜单应显示任务计数，如“3 imports failed”“2 changes awaiting review”“1 preview expired”，而不是让管理员逐页寻找异常。

### 14.2 发布前研究者视角质量门

发布页面不再仅显示基因/变异数量，而显示完整发布摘要：数据质量、许可/引用、索引预算、下载校验和、导航/路由影响、桌面/移动验收、审核记录和可用回滚目标。阻断项未通过时，不显示生产发布动作。

### 14.3 统一空状态和错误恢复

`rl_module_availability_guard` 对以下状态给出原因和下一步：

| 状态 | 用户提示 | 下一步 |
|---|---|---|
| 无数据 | 当前发布没有该类记录 | 切换发布、查看下载、请求数据 |
| 未发布 | 存在候选但未对外公开 | 显示公开状态，不泄露数据 |
| 维护 | 模块/外部来源临时不可用 | 访问静态目录、状态页、稍后重试 |
| 隐藏 | 不在当前导航中 | 合规深链提示或替代模块 |
| 弃用 | 原因、替代资源、迁移期限 | 前往替代页面 |
| 零命中 | 当前有效范围与筛选条件 | 清除条件、扩大范围、查看示例 |
| 网络失败 | 失败的具体层级 | 重试、查看缓存、使用替代入口 |

生产 `ErrorBoundary` 不向普通用户暴露原始异常信息；展示错误参考编号、重试、返回安全页、状态页和合规诊断入口。

---

## 15. 最新稳定技术栈与供应链优化

技术升级使用“先试点、后阻断”的策略：先生成证据和制品，再在稳定后作为发布门禁。

| 范围 | 建议 | 升级前验证 |
|---|---|---|
| React | 如仍低于 React 19，迁移至 19.2 稳定线 | 依赖兼容、createRoot、类型、测试工具；不同时引入 Server Components |
| Vite | 新环境优先 Vite 8；生态未兼容时先 Vite 7 | Node 20.19+/22.12+、ESM、插件、Vitest、SSG 脚本和容器 |
| FastAPI | 迁移 Pydantic v2 后升级至当前稳定线 | OpenAPI、请求校验、序列化、错误响应、Content-Type 回归 |
| PostgreSQL | 新部署评估 18；保守生产升级先 17 | 扩展、ORM、备份恢复、pg_upgrade/逻辑复制和统计重建 |
| Redis | 旧 Redis 6/7 规划至 8 | 模块、ACL、Lua、集群、持久化和客户端兼容 |
| 客户端搜索 | 小/中型分片评估 MiniSearch；大规模保留服务端升级契约 | 真实数据、中文/别名、内存、排序和 Worker 基准 |
| 可观测性 | OpenTelemetry + OTLP | 采样、PII 脱敏、低基数属性和成本预算 |
| 供应链 | SPDX SBOM + SLSA provenance + Sigstore/Cosign | 构建器身份、digest、签名验证和多架构镜像 |
| OCR | 固定官方版本、关闭自动更新 | Git、规则、Provider、JSON schema、代码出境和成本 |

上述版本为 Phase 7 候选而非主路径承诺。Phase 0–2 仅升级已阻断支持、安全维护或当前实现的组件；禁止把 React、Vite、PostgreSQL、Redis 等大版本升级与数据模型、发布状态机或迁移改动放入同一发布批次。每次升级需要独立 ADR、兼容矩阵、隔离试点、构建/数据演练和独立回滚。

建议使用官方文档、Release 和仓库作为升级依据。仓库没有知乎 skill 时，不得将社区内容作为唯一技术决策依据。

---

## 16. 路线图调整

在原 Phase 0–8 上作如下调整：

1. **Phase 0** 增加真实数据规模、制品规模、本体覆盖和许可覆盖基线；
2. **Phase 1** 同时完成导入契约、稳定 ID、受控词表、权限和审计，而不仅是容器实体；从第二物种真实小样本开始 walking skeleton；
3. **Phase 2** 同时完成发布状态机和最小可观测性，不能等到性能阶段；
4. **Phase 3–5** 在稳定数据/发布契约上实现管理员、公开 UX 和搜索；
5. **Phase 6** 完成第二物种全量发布；跨物种比较作为受限的基因正交关系能力单独验收；
6. **首次生产快照前**完成最小灾备：PostgreSQL、对象存储、审计和制品按存储类型定义 RPO/RTO、自动备份、隔离恢复、manifest/hash 验证和恢复演练；
7. **Phase 7–8** 再扩大跨区域灾备、FAIR 能力、技术升级和清理范围。

最先必须形成的 ADR：

1. 科研对象稳定身份与跨版本生命周期；
2. 导入契约、quarantine 和数据质量门；
3. 静态实体页面基数及混合制品策略；
4. 构建期与运行时 widget/search 链路收敛；
5. Worker 到服务端搜索的容量触发器和共享查询契约；
6. 发布状态机、并发控制与可观测性语义；
7. 数据、制品和审计的灾备 RPO/RTO。
