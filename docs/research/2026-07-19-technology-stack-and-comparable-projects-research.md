# 技术栈与同类项目研究（2026-07-19）

## 1. 执行结论

本次研究不改变已接受的总体架构，而是为其补充证据、边界和验收条件。推荐继续采用以下技术基线：

```text
受限管理控制面
  → FastAPI 模块化单体
  → PostgreSQL 权威治理与发布账本
  → Worker/TypeScript 构建的版本化静态资源
  → 不可变对象存储制品 + manifest/ready marker + fencing/CAS
  → 静态优先公共门户
       ├─ Internal Search API：只读已发布本地资源
       └─ External Search API：只访问隔离的外部来源适配器
```

执行决策如下：

1. **保留 FastAPI 模块化单体**作为控制面和领域 API。按 catalog/species/assembly/dataset、ontology、import、content、publication、approval、audit 等边界组织模块；router 只处理协议和授权，service 负责短事务，repository 负责查询访问。
2. **PostgreSQL 是权威源**，保存物种、组装、科学对象、数据集快照、本体来源与 release、映射、断言、治理、审批、manifest、public pointer ledger、audit/outbox 等事务事实。Redis 只用于缓存、锁、限流、进度提示和受控去重，不能成为科学事实、发布真相或永久审计源。
3. **静态优先继续成立**。原始本体、导入文件、规范化文档分片、下载包、页面和搜索索引作为不可变 artifact 存放于 MinIO/S3/POSIX 兼容对象存储；PostgreSQL 保存注册、digest、来源、许可、生命周期和发布引用。
4. **两套搜索系统必须物理和语义隔离**。第一阶段 Internal Search 使用已发布、有界、版本化静态分片；MiniSearch 可作为现有 TypeScript Web Worker 的实现细节。External Search 使用独立 endpoint、适配器、缓存、限流、超时和 provenance，不能访问内部 ORM 或覆盖本地事实。
5. **发布采用可恢复 saga**：Prepare DB transaction → External pointer CAS → Finalize DB transaction；CAS 后的 smoke 失败必须创建新的 fenced compensation attempt 或进入 `unknown`，不能声称旧指针从未改变。
6. **不捆绑版本升级或新基础设施**。当前版本和兼容性差异先进入 A0 reconciliation；任何升级、替换搜索引擎或拆分服务都必须有独立 ADR、兼容测试、收益测量和回滚证据。

这是一份研究与决策记录，不是产品实施授权，也不表示已有代码变更已经完成。

## 2. 证据质量规则

### 2.1 证据等级

| 等级 | 证据来源 | 可支持的结论 | 使用规则 |
|---|---|---|---|
| A | 官方标准、官方文档、官方项目仓库、官方 schema/release 资料 | 协议语义、数据模型、项目真实能力、许可与发布方式 | 可直接进入架构决策；仍须结合本项目约束验证 |
| B | 多个成熟项目的公开实现和可复现仓库模式 | 可借鉴的边界、适配器、manifest、stable ID、release/archive 模式 | 只能选择性借鉴，不等于可直接复制 runtime |
| C | 高质量社区技术观察（含知乎）且与 A/B 证据一致 | 工程痛点、实施顺序、性能和运维经验 | 只能作为补充和待验证假设，不能单独改变架构 |
| D | 低票、营销、教程拼接、无法核验作者/代码或与项目数据不符的内容 | 不足以支持架构或安全结论 | 不采纳 |

### 2.2 Zhihu 证据声明

知乎证据是**非权威的社区经验**，不等同于标准、官方文档或项目事实。此次可复用的高质量观察仅限于与官方/仓库证据相互印证的工程边界：

- 元数据/治理放 PostgreSQL，大文件或 Parquet 放不可变对象存储，Redis 只做瞬态协调与缓存；这与本项目的 PostgreSQL authority、artifact reference 和 Redis non-authority 约束一致。
- 生产发布应绑定完整的版本化资源包，包括来源、权限/许可、生成资源、校验、diff、审批、审计和回滚，而不是只有一个任务状态；这与 PublicationManifest 和三条追加历史一致。
- 静态站点的搜索可在构建期生成索引并放入 Web Worker，按范围分片加载；这只支持“CPU 工作移出主线程”和“有界加载”，不证明某个引擎或任意数据规模安全。
- 大数据前端需要分页、分片、懒加载、虚拟化、Worker 生命周期管理和服务端 fallback；这些只补充 UX/性能验收项，不足以自动引入 IndexedDB、WASM、Worker pool 或新搜索服务。

知乎检索/思考结果中存在低质量、推广性或疑似生成内容；未采用这些内容。`zhida-thinking-1p5` 曾返回 HTTP 554 空响应，因此没有把其推理结论当作证据。知乎观察必须回到官方文档、仓库和 B-pre-ADR 基准中验证。

## 3. 当前项目技术栈与就绪度

下表只记录当前仓库可观察到的基线和研究结论，不提出未经验证的版本升级处方。

| 领域 | 当前仓库基线 | 对接受架构的适配 | 就绪度 | 缺口/闸门 |
|---|---|---|---|---|
| 公共门户 | React 19.2、Vite 6、TypeScript、TanStack、Tailwind；`apps/web/scripts/ssg-build.ts` 生成静态页面 | 适合静态优先和确定性资源构建 | 部分就绪 | 两个生成器尚无共同 generation/manifest/hash/atomic boundary；需 C 阶段闭合 |
| Admin | React/Vite、TanStack Table/Router、共享 UI；可选 Tauri 桌面壳 | 可承载受限控制面和科研仪器式高密度工作区 | 部分就绪 | 现有 UI 覆盖宽但后端契约不完整；A1 先建立 capability、typed command、审批和 403 行为 |
| API | FastAPI 0.137.1、SQLAlchemy async、Pydantic、Alembic；`apps/api/app` 按 API/service/model 组织 | 应保留为模块化单体，适合短事务和领域边界 | 部分就绪 | 需完成 schema/ORM/OpenAPI/client/worker reconciliation；router 与 service 的边界需落地 |
| PostgreSQL | Compose 使用 PostgreSQL 18.4；JSONB、UUID、`pgcrypto`、`uuid-ossp` 已存在 | 适合治理元数据、映射、审批、manifest、audit/outbox | 部分就绪 | 测试容器为 PostgreSQL 16，Alembic 与 ORM 对 `releases` 有漂移；A0 必须以实际 schema 为事实并完成迁移 rehearsal |
| ClickHouse | Compose 使用 ClickHouse 24.8；变异事实/分析已有分离方向 | 可继续承载大体量变异事实和分析，不与 PostgreSQL authority 冲突 | 部分就绪 | 需验证 dataset/object version 与 ClickHouse facts 的 scope/发布绑定，不在首阶段搬迁所有事实 |
| Redis | Compose 使用 Redis 7.4；Celery broker、缓存、锁和限流均有使用 | 可作为 non-authority 协调层 | 部分就绪 | 必须分命名空间、TTL、token lock、lease/fencing；不能依靠 Redis lock 或 keyspace notification 保证发布正确性 |
| Worker | Celery worker/beat，多队列；静态页面任务存在注册名不一致缺陷 | 可承载 build、validate、relay、reconcile 等异步任务 | 未就绪 | BackgroundTasks 不作为队列；业务写入、audit outbox、task outbox 同事务，relay 提交 Celery；先修正并测试注册契约 |
| Artifact store | Compose 已有 MinIO，S3 接口和 immutable bucket 方向；`user-tracks` 开启 versioning | 适合 raw source、静态制品、manifest 和下载包 | 部分就绪 | 需验证 Object Lock/versioning、Range/CORS、ready marker、CAS provider capability 和 orphan reconcile |
| 搜索 | API 当前把内部/外部搜索混在一条路由；service 查询 live PostgreSQL；前端 Worker 只是数组过滤排序 | 可演进为两个隔离系统；MiniSearch 仅是 bounded Worker provider 候选 | 未就绪 | D 阶段实现独立 contracts、manifest-backed provider、rank tiers、签名 cursor、API fallback 和敏感字段扫描 |
| JBrowse 2 | 独立 `apps/jbrowse`，使用 `@jbrowse/core` 和 React linear genome view | 适合作为 genome-browser visualization subsystem | 部分就绪 | 需 release-specific immutable config、track/index artifact registration、Range/CORS 验证；不得作为 provenance store |
| Rust hotpath | README 记录 Axum 本地内部服务，仓库有 Rust workspace | 可保留为 benchmark-gated hotpath | 未作为控制面基线 | 不因存在 Rust 就拆分 FastAPI；只有真实 SLO/基准证明后才形成独立 ADR |
| 迁移与测试 | Alembic 存在；API 测试夹具使用 `Base.metadata.create_all()`；Testcontainers 为 PostgreSQL 16 | 有基础工具但尚不足以证明迁移安全 | 未就绪 | A0 必须覆盖 upgrade/downgrade（可逆部分）/upgrade、备份恢复、空库重建、双物种 walking skeleton |
| 命名与注释 | 设计要求新增第一方函数/变量/类型/组件/服务/夹具使用 `rl_` | 可作为后续实现约束 | 设计就绪 | 实施时为非显然业务规则、授权、版本转换、迁移安全和性能决策增加简短中文 why-comments |

### 3.1 当前 readiness 的总体判断

项目具备实现该架构所需的主要运行时组件，但**尚未具备直接进入产品实现或生产迁移的证据**。尤其是：

- 当前配置同时出现 README 的 Python `>=3.10` 描述与 API `pyproject.toml` 的 Python `>=3.14` 声明，必须在 A0 记录事实并验证支持矩阵，不能在本研究中自行指定升级或降级。
- Compose 与测试容器的 PostgreSQL 版本不同，且 ORM/Alembic 可能漂移；不能把 `create_all()` 结果当作迁移验收。
- 当前 SSG、per-Gene 静态任务、搜索路由和 Worker 注册尚未形成同一 publication identity。
- 管理端页面范围不能证明后端能力存在；所有高风险动作都必须以 OpenAPI/client contract、permission matrix、状态机、幂等和 E2E 证据为准。

## 4. 可比项目矩阵

| 项目 | 官方/仓库证据 | 可借鉴模式 | 不应复制的部分 | 对 SoyMutDB 的结论 |
|---|---|---|---|---|
| LegumeInfo / SoyBase | [LegumeInfo](https://legumeinfo.org)、[data portal](https://data.legumeinfo.org)、[datastore specifications](https://github.com/legumeinfo/datastore-specifications)、[graphql-server](https://github.com/legumeinfo/graphql-server) | 静态公共门户与交互式组件/API 分离；collection metadata sidecar、manifest、change history | 文件约定不能替代本项目需要的 PostgreSQL 审批、不可变 manifest、审计证明 | 最近的产品形态参考；采用 portal/data collection 边界，扩展为受治理发布系统 |
| Gramene / Ensembl Plants | [Gramene](https://gramene.org)、[Ensembl Plants](https://plants.ensembl.org)、[Core schema](https://plants.ensembl.org/info/docs/api/core/core_schema.html)、[plant scripts](https://github.com/Ensembl/plant-scripts) | assembly-first、多物种 stable identifier、来源/provenance、assembly/annotation/variation 分离发布 | 不复制其完整数据库/API/Solr estate 或运营规模 | 用于校准 `Species → Assembly → DatasetRelease`、稳定身份和来源语义 |
| Alliance of Genome Resources | [Alliance](https://www.alliancegenome.org)、[curation schema](https://github.com/alliance-genome/agr_curation_schema)、[open data](https://github.com/alliance-genome/agr_open_data) | current + archived releases、member provenance、对象存储分发、schema-as-code、CI 生成和 source-specific tracking | LinkML/JSON Schema 不是首阶段必须增加的依赖；不直接引入其全套联盟运行时 | 强化 release/archive、schema 校验和来源成员追踪；未来 schema ADR 再评估 |
| JBrowse 2 | [JBrowse 2](https://jbrowse.org/jb2/)、[components repo](https://github.com/GMOD/jbrowse-components)、[config guide](https://jbrowse.org/jb2/docs/config_guide/) | assembly/track config、索引远程文件、adapter/plugin、deep links、浏览器渲染 | 不作为 provenance、publication 或权限系统；不让 config 绕过 manifest/artifact registration | 保留为独立可嵌入浏览器；config 和 track URL 必须绑定 immutable publication |
| InterMine | [InterMine](https://intermine.org)、[repo](https://github.com/intermine/intermine)、[web services](https://intermine.org/documentation/web-services/) | source adapter、key-based identifier merge、integration/postprocessing、template/batch query | Java/PostgreSQL/Solr 全套 runtime 与静态优先、FastAPI modular monolith 冲突，首阶段运维范围过大 | 只借鉴适配器、键合并和批量查询思想；不引入 InterMine 主架构 |
| OLS 4 / BioPortal | [OLS 4](https://www.ebi.ac.uk/ols4/)、[OLS repo](https://github.com/EBISPOT/ols4)、[BioPortal](https://bioportal.bioontology.org)、[BioPortal UI](https://github.com/ncbo/bioportal_web_ui) | CURIE/IRI normalization、source/release catalogue、controlled ingestion、synonym/definition/hierarchy、provenance | Neo4j/Solr/Rails 是参考实现，不是本项目必需组件；不把全文/图数据库作为事实源 | 直接支持 ontology registry、release snapshot、生命周期和 provenance 设计 |
| WormBase（次级） | [WormBase](https://wormbase.org/) | 成熟的物种门户、长期 release/archive 和对象追踪经验 | 不把其规模、专用数据管线和运营组织假定为本项目当前容量 | 仅作长期发布治理和多物种运营的补充观察，不改变首阶段技术栈 |

跨项目共同结论是：`portal software`、publication、dataset、assembly、annotation、ontology source/release、pipeline/schema 和 file digest 必须保持独立身份。搜索索引不是事实权威，JBrowse config 不是治理边界，也不应在没有规模/SLO 证据时增加 graph/search cluster。

## 5. 推荐技术基线与明确不推荐

### 5.1 推荐基线

- **控制面**：现有 FastAPI 模块化单体；显式 capability 授权；service 短事务；repository 查询；新增第一方业务代码遵守 `rl_` 前缀。
- **权威数据**：PostgreSQL 保存可审计治理事实和不可变引用；ClickHouse 继续承载适合其数据平面的变异事实/分析，但必须被 dataset/object version 和 publication evidence 约束。
- **大对象与发布**：S3-compatible object store 保存原始文件、规范化资源、静态页面、搜索分片、下载包；所有 artifact 注册后以 SHA-256、大小、类型、许可和来源绑定；manifest 最后写入，发布只切换已验证的 immutable set。
- **异步执行**：Celery worker 继续作为执行层；业务事实、audit outbox、task-dispatch outbox 同 PostgreSQL 事务提交，commit 后 relay 投递任务；每个 worker 以业务幂等键执行，不假设 exactly-once。
- **内部搜索**：TypeScript Worker 中的 MiniSearch 作为首选候选，必须包装自有 manifest/schema/config-hash/checksum/version；只加载显式有界的公开 index shards，并可回退到 Internal Search API 或无 JS 静态目录。
- **外部搜索**：独立 FastAPI endpoint/adapter contract，source-specific cache、rate limit、timeout/circuit breaker 和 provenance；外部结果不能覆盖或自动写入本地 ontology facts。
- **基因组浏览**：JBrowse 2 只负责 visualization；assembly、track、index sidecar、Range/CORS 和 release-specific config 由 publication manifest/artifact registry 管理。
- **前端体验**：保留 React/Vite/Tailwind、TanStack、共享 `packages/ui` 和现有可访问性基础；按 Scientific Field Manual / Research Instrument 方向演进，静态优先、context bar、来源/许可/版本/digest 可见。

### 5.2 明确不推荐

- 不引入 Elasticsearch、OpenSearch、第二搜索数据库或永久 Node search service 作为首阶段内部搜索。
- 不因为浏览器构建使用 Node/TypeScript 就新增 Node 控制面服务。
- 不因社区建议微服务化就拆分当前 FastAPI 模块化单体。
- 不把 Redis 用作科学事实、publication pointer 的唯一权威、永久审计或可靠消息总线；不使用 keyspace notification 充当发布机制。
- 不把 JBrowse 2、MiniSearch 或任何搜索索引当作 provenance、授权或发布真相。
- 不在 PostgreSQL 中无界存放原始 genomic/ontology payload，也不把大文件任意塞进 JSONB；先保留 immutable artifact reference。
- 不首阶段导入全部 OBO、启用完整 OWL reasoning、宽泛重构 TO/PATO/ENVO 或无数据依据地纳入 PO。当前 ontology slice 为 NCBI Taxonomy + GO + SO + RO + ECO；PO 仅在真实植物结构/发育数据需要且另有 scope decision 时加入。
- 不提出 Node、Vite、FastAPI、PostgreSQL 或 Redis 的版本升级处方。研究记录当前仓库事实；版本变更必须独立 ADR 和回滚验证。

## 6. 研究发现到已接受架构的映射

| 研究发现 | 接受的架构映射 | 可验证的实施含义 |
|---|---|---|
| SoyBase/LegumeInfo 的静态门户、collection metadata 和 manifest 经验 | 保留静态-first；将页面、下载、索引和 ontology facets 组合成 PublicationManifest | 构建输入冻结；manifest 记录 digest、来源、许可、config、search/download assets；旧制品不原地覆盖 |
| Gramene/Ensembl Plants 的 assembly-first 与 stable ID | `Species → AssemblyScope → DatasetRelease → ScientificObject`；Gene/Transcript 身份包含 namespace、assembly，Transcript 还绑定 parent Gene | A0/A1 建立 scope-aware uniqueness、legacy adapter 和 unresolved mapping；第二物种 walking skeleton 在 B-pre-ADR 完成 |
| Alliance 的 current/archive release、provenance 和 schema-as-code | dataset、publication、ontology release set、pipeline/schema、artifact 分离；当前指针与历史快照分离 | approval/build/deployment 各自追加历史；schema validation 可先作为 contract，是否引入 LinkML/JSON Schema另走 ADR |
| JBrowse 2 的 immutable track/config 与远程 indexed files | JBrowse 作为 bounded visualization subsystem，受 publication manifest 和 artifact registry 约束 | 每个 release 生成不可变 config/track URL；验证 Range/CORS、index sidecar、deep link 与 digest 一致 |
| InterMine 的 source adapter、key merge、postprocessing | ontology/data import 采用 provider adapter、显式 namespace、keyed mapping 和 diagnostics | 不静默合并跨 species/assembly identity；冲突进入 unresolved/resolution event；不引入 InterMine runtime |
| OLS/BioPortal 的 ontology catalogue 与 release/provenance | PostgreSQL ontology source/release/term/synonym/relation/assertion registry + immutable raw artifacts | release set 包含依赖 closure、Taxonomy/ECO mapping、parser/validator、license evidence 和 digest；obsolete 保留历史，不覆盖原事实 |
| 官方 OSS/文档对 FastAPI、Celery、Redis 和 object-store 的边界观察 | 模块化单体、短事务、commit 后任务 relay、Redis non-authority、artifact + CAS/fencing | 业务/审计/任务 outbox 同事务；worker 业务幂等；Prepare → CAS → Finalize；CAS 后失败补偿或 unknown |
| MiniSearch 官方能力与社区静态 Worker 观察 | bounded Internal Search provider；引擎序列化不作为长期公共协议 | B-pre-ADR 固定 shard/doc/timeout/limit/memory ceilings；manifest 校验失败回退 API/目录；Worker 不承担授权 |
| 知乎的高质量补充观察 | 只用于强化 release bundle、Worker 生命周期、分片/fallback 和 orphan reconcile 的验收意识 | 不能单独选引擎、扩大容量、引入 IndexedDB/WASM、改变权威边界或推翻官方证据 |

## 7. 风险与验证闸门

| 风险 | 影响 | 必须通过的闸门 |
|---|---|---|
| Alembic、ORM、实际 schema 和前端契约漂移 | 迁移破坏、404、错误发布状态 | **A0**：实际 schema/revision/OpenAPI/client/worker reconciliation；disposable PostgreSQL upgrade→可逆 downgrade→upgrade；备份恢复和空库重建 |
| 科学对象 identity 跨 namespace/species/assembly 合并 | 不可复现、错误注释和错误比较 | **A0/B-pre-ADR**：大豆+第二物种 walking skeleton；scope-aware uniqueness、unresolved queue、legacy mapping evidence |
| ontology closure、许可或 evidence mapping 不完整 | 错误公开事实或合规风险 | **B**：release set closure、TaxID/ECO mapping、license inventory、dangling reference/obsolete/unsupported qualifier diagnostics；未解决项阻断 public approval |
| SSG、索引、页面和下载来自不同快照 | 用户看到混合版本 | **C**：统一 publication identity/generation；immutable artifact、manifest-last、ready marker、hash/size/type 校验和 recoverable saga |
| CAS 成功后 smoke 失败或跨存储状态未知 | 短暂错误版本或错误回滚 | **C**：记录 verifying；失败建立 fenced compensation attempt；无法证明时进入 unknown、冻结后续 promotion 并人工 resolution |
| 浏览器索引过大或 Worker 失效 | 主线程卡顿、搜索不可用、泄露字段 | **B-pre-ADR/D**：测量压缩/解压大小、内存、load、P50/P95、shard/doc caps；字段 allowlist、敏感扫描、API fallback、静态目录 fallback |
| External Search 侵入内部事实或故障级联 | 本地结果不可信、外部超时拖垮门户 | **D**：独立 route/import/cache/limit/error/provenance contract；provider timeout/circuit breaker；外部失败不影响内部结果 |
| Redis lock 被误当作一致性机制 | 重复发布或错误 active pointer | **A1/C**：DB fencing 和 pointer CAS 为事实；Redis 只去重/协调；测试 token release、lease expiry、retry 和 split-brain 场景 |
| 审批、审计和任务投递不一致 | 高风险行为无法追责或重复执行 | **A1**：三条 append-only histories、audit/task outbox 同事务、hash-chain/retention policy、幂等/并发/失败审计测试 |
| Admin UI 宣称不存在的后端能力 | 操作员误以为已治理 | **A1/E**：OpenAPI/client contract、permission matrix、state machine、跨角色 E2E；无契约入口移除或禁用 |
| 过早引入新搜索/图数据库/微服务 | 运维复杂度、迁移风险、架构分裂 | **F**：只有规模、内存、SLO、授权或数据模型证据触发独立 ADR；无证据则维持当前基线 |

## 8. 精确下一步

以下动作是研究后的执行顺序，不是已完成事项，也不授权跳过用户设计确认或 Oracle 复核：

1. **完成 A0 reconciliation 包**：记录实际 Alembic head、已部署 schema、ORM metadata、OpenAPI 路由、API client 调用、Admin affordance、Worker task 注册和旧 `Release` 证据分类；明确 Python/Node/数据库运行时支持事实，不自行升级。
2. **在 disposable PostgreSQL 环境执行迁移演练**：空库建库、`upgrade`、仅可逆部分 `downgrade`、再次 `upgrade`、备份恢复；把 PostgreSQL 16 测试容器与 Compose PostgreSQL 18.4 的差异写入兼容性记录。
3. **冻结 A1 控制面契约**：定义 `rl_` capability matrix、typed command、approval binding、请求/幂等键、requester/approver separation、三条 append-only histories、`rl_audit_outbox` 与 `rl_task_dispatch_outbox` 的事务边界。
4. **修复并验证任务契约**：核对 Admin static-build dispatch 名称与 Worker 注册名，增加 contract test；确保任务投递失败不会制造业务成功事实，worker retry 使用业务幂等键。
5. **完成 B-pre-ADR 双物种 walking skeleton**：选择大豆和一个第二物种，使用受控最小数据跑通 Taxonomy、Assembly scope、scientific object、dataset object version、manifest、原始 artifact、页面、Internal Search、下载和引用；记录真实规模、对象存储能力、RPO/RTO 和 provider 语义。
6. **根据 B-pre-ADR 固定 Internal Search 初始边界**：最大 shard 数、文档数、单次 `limit`、timeout、Worker 内存上限、压缩/解压大小和 P50/P95；若超过边界，先采用 API/静态目录 fallback，不立即换引擎。
7. **实现 B ontology closure 设计验证**：注册 NCBI Taxonomy、GO、SO、RO、ECO 的 source/release；验证 raw artifact digest、closure、ECO mapping、license evidence、obsolete/do-not-annotate、asserted-only 和 unresolved diagnostics；PO/TO/PATO/ENVO 仍保持 deferred。
8. **为 C publication 编写 provider capability tests**：验证 immutable PUT、HEAD/hash/size、ready marker、conditional pointer CAS、fencing、Range/CORS、cache window、orphan cleanup 和 unknown-state reconciliation；Object Lock/versioning 不能替代应用层 manifest/CAS。
9. **为 D 双搜索建立独立 contract**：Internal Search API 与 External Search API 分开路由、依赖、缓存、错误、provenance 和限流；定义 rank tiers、签名 cursor、manifest digest binding、字段 allowlist、敏感扫描和 Worker/API/静态目录 fallback。
10. **在用户设计确认和 targeted Oracle review 后再编写实施计划**：只有 A0、A1、B-pre-ADR 的证据包完成，且材料性架构变化已复审，才允许进入产品实现、迁移、依赖变更或部署修改。

## 9. 来源

### 项目与官方技术资料

- Ontology/PostgreSQL/control-plane accepted design：[`docs/superpowers/specs/2026-07-15-ontology-postgresql-control-plane-design.md`](../superpowers/specs/2026-07-15-ontology-postgresql-control-plane-design.md)
- Deepwork research summaries：[`.slim/deepwork/ontology-postgresql-refactor.md`](../../.slim/deepwork/ontology-postgresql-refactor.md)
- Repository baseline：[`README.md`](../../README.md)、[`docs/design/architecture.md`](../design/architecture.md)、[`docs/design/multispecies-portal-product-architecture-design.md`](../design/multispecies-portal-product-architecture-design.md)
- FastAPI：[官方文档](https://fastapi.tiangolo.com/)
- PostgreSQL：[官方文档](https://www.postgresql.org/docs/)
- Redis：[官方文档](https://redis.io/docs/)
- Celery：[官方文档](https://docs.celeryq.dev/)
- MiniSearch：[官方仓库](https://github.com/lucaong/minisearch)
- MinIO：[Object Lock 文档](https://min.io/docs/minio/linux/administration/object-management/object-retention.html)
- Vite：[官方文档](https://vite.dev/)
- React：[官方文档](https://react.dev/)
- OBO Foundry：[官方页面](https://obofoundry.org/)
- Gene Ontology：[官方页面](https://geneontology.org/)
- NCBI Taxonomy：[官方页面](https://www.ncbi.nlm.nih.gov/taxonomy)
- Sequence Ontology：[官方页面](http://www.sequenceontology.org/)
- Relations Ontology：[官方仓库](https://github.com/oborel/obo-relations)
- Evidence and Conclusion Ontology：[官方页面](https://www.evidenceontology.org/)

### 知乎社区观察入口（非权威，仅作可追溯的社区背景）

本次深度研究只接受与官方/仓库证据相互印证的社区观察；知乎不作为规范、项目能力或安全结论的唯一来源。以下入口用于回溯相关主题，不替代 A/B 级证据：

- [知乎：数据湖/数据平台与对象存储元数据治理检索](https://www.zhihu.com/search?type=content&q=%E6%95%B0%E6%8D%AE%E5%B9%B3%E5%8F%B0%20%E5%AF%B9%E8%B1%A1%E5%AD%98%E5%82%A8%20PostgreSQL%20Redis)
- [知乎：静态站点搜索与 Web Worker 检索](https://www.zhihu.com/search?type=content&q=%E9%9D%99%E6%80%81%E7%AB%99%E7%82%B9%20Web%20Worker%20%E6%90%9C%E7%B4%A2%20%E7%B4%A2%E5%BC%95)
- [知乎：数据发布版本、审批、审计与回滚](https://www.zhihu.com/search?type=content&q=%E6%95%B0%E6%8D%AE%E5%8F%91%E5%B8%83%20%E7%89%88%E6%9C%AC%20%E5%AE%A1%E6%89%B9%20%E5%AE%A1%E8%AE%A1%20%E5%9B%9E%E6%BB%9A)
