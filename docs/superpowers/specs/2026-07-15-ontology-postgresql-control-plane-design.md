# Ontology、PostgreSQL 与受治理控制面设计

**状态：** 用户已确认；Oracle Gate 1 与最终 targeted confirmation 已通过；待实施计划审核  
**范围：** SoyMutDB Next 多物种门户的本体治理、PostgreSQL 权威元数据、管理员控制面、版本化静态发布与双搜索系统  
**不包含：** 产品代码、数据库迁移、依赖升级、部署修改或实施授权  
**关联基线：** [多物种门户产品与架构设计](../../design/multispecies-portal-product-architecture-design.md)、[多物种门户功能与体验设计说明](2026-07-12-multispecies-portal-design-spec.md)

**研究证据：** [2026-07-19 技术栈与同类项目研究](../../research/2026-07-19-technology-stack-and-comparable-projects-research.md)。该研究中的知乎内容仅是与官方文档/仓库相互印证的非权威社区观察，不单独改变架构决策。

## 修订记录

- 2026-07-15：初稿进入 Oracle Gate 1，未获批准。
- 2026-07-15：根据 C-01—C-10、I-01—I-08 修订；补充科学对象/数据集快照、ontology closure、迁移闸门、独立历史、跨存储 promotion、可执行内部搜索、审计账本、物理约束矩阵和早期多物种数据平面验证。仍保持草案，不代表实施授权。
- 2026-07-15：根据预 Oracle 精度检查补充实体策略身份、完整物理约束、断言校验、内容 revision 快照、跨 provider reconcile、固定搜索分层、retention 审批和 registered artifact 引用；仍保持草案，不代表实施授权。
- 2026-07-15：根据 Gate 1 re-review 补充最终 publication approval、独立 deployment approval、可恢复 promotion saga、CAS 后 verifying/补偿、数据对象主键、closure 外部引用、分区审计链和静态搜索初始边界；仍保持草案，不代表实施授权。
- 2026-07-15：Oracle Gate 1 最终复审通过，无剩余阻断项；仅批准进入用户设计评审，不授权产品实现、数据库迁移、依赖升级或部署修改。
- 2026-07-19：根据技术栈/同类项目研究和已接受 UX delta 做局部设计精化；保留全部 Oracle Gate 1 publication-correctness 决策，补充运行时与迁移路径 reconciliation、公开制品校验、JBrowse 资源校验、scope/provenance/诊断 UX 和比较项目的明确不采用项。该精化待 targeted Oracle review 与用户确认，不构成产品实现授权。
- 2026-07-19：targeted Oracle review 以“通过但需编辑”反馈了公共投影安全边界、制品 capability profiles、孤儿制品清理保护、ontology 路径边界以及 C/D 验收分工。当前修订正在闭环；Gate 1 正确性保持不变，文档待最终 targeted confirmation 与用户评审，不构成产品实现授权。
- 2026-07-19：最终 targeted Oracle confirmation 通过，无剩余阻断项。公开投影 allowlist、制品 capability profile、孤儿制品保护、ontology 路径边界和 C/D 验收分工均已闭环；设计可进入用户评审，用户确认前仍不授权产品实现、数据库迁移、依赖升级或部署修改。
- 2026-07-19：用户明确回复“确认设计”。设计评审门已关闭，允许进入 Deepwork Phase 2 编写和审核分阶段实施/委派计划；在该计划通过 Oracle 复核前，仍不授权产品实现、数据库迁移、依赖升级或部署修改。

## 1. 决策摘要与边界

目标链路为：

```text
受限管理控制台
  → FastAPI 模块化单体控制面 + PostgreSQL 权威治理库
  → 冻结输入的生成中心（Worker/SSG/Search Builder）
  → MinIO/S3/POSIX 不可变制品 + CDN 静态门户
                         ↘ 内部已发布资源搜索 API
                          ↘ 外部来源搜索适配器（隔离）
```

固定决策：

1. PostgreSQL 是治理、审批、manifest 元数据和公开指针的权威事务源；Redis 只用于缓存、锁、限流、进度提示和受控去重，不能承载科学事实、发布真相或永久审计。
2. 原始本体、原始导入文件、规范化文档分片和公开页面均为对象存储中的不可变 artifact；公共端只读取已发布 manifest 引用的版本化资源。
3. 内部搜索只面向 manifest 引用的公开规范化文档分片；外部搜索只经 allowlist 适配器访问第三方来源。两者不共享结果、错误、缓存、比较资格或版本语义。
4. 保留现有 FastAPI 模块化单体、React/Vite/Tailwind/Radix/TanStack 和 TypeScript Worker 方向；不引入新的搜索集群或控制面服务，不捆绑 Node、Vite、FastAPI、PostgreSQL、Redis 升级。
5. Gene/Transcript 既有字符串主键、ClickHouse 变异事实和旧自由文本字段首阶段不替换、不删除。新增第一方代码/业务对象命名使用 `rl_` 前缀；框架约定、迁移名、第三方 API 和既有公共接口除外。非显然业务规则、授权、版本转换、迁移安全和性能选择须配简短中文“为什么”注释。
6. 研究只确认保留现有控制面与前端基线，不授权升级。A0 必须核对 README、API/Worker Python 要求、Node/前端运行时说明，以及 `migrations` 与开发 Compose `alembic` 目录/运行时 wiring 的实际关系；不以文档或目录名称推断迁移事实，也不产生 package upgrade mandate。

同类项目的可借鉴模式限于静态门户/collection manifest、assembly/stable identity、release/archive、source adapter、ontology catalogue 和 JBrowse bounded visualization。明确不采用 graph database、Solr/Elasticsearch、InterMine runtime、full ontology tree/inference UI 或 microservice rewrite；除非独立的 measured ADR 证明规模、SLO、授权或数据模型需要，否则不增加这些运行时。

**跨切面工程规则：** 所有新增第一方业务函数、变量、类型、组件、服务和测试夹具使用 `rl_` 前缀；必须添加简短中文“为什么”注释来说明非显然的业务规则、安全边界、版本转换、迁移保护或性能取舍；每个阶段均受本设计的用户确认与 Oracle 复核门控制，未通过不得宣称完成或获得实施授权。

## 2. A0 硬闸门：事实、契约与迁移先行

A0 是第一项计划/执行阶段；在其证据完成前，禁止生产迁移、生产写入切换和 publication 实现，但不阻止编写本详细实施计划。它是硬门槛，不是建议：

- 盘点实际 Alembic revision、已部署 PostgreSQL schema、ORM metadata、OpenAPI、前端调用和 worker 注册；生成逐项 reconciliation 报告。ORM 与迁移不一致时，以实际 schema/历史为事实，不假定目标表已存在。
- 在 disposable PostgreSQL 上使用真实 Alembic 链路运行 `upgrade → downgrade（仅可逆部分）→ upgrade`、备份恢复和空库重建；`Base.metadata.create_all()` 不构成迁移验收。PostgreSQL 测试/Compose 版本差异必须先有独立兼容 ADR，不能借本设计升级。
- 设计并验证 expand/backfill/unresolved review/write-cutover（或 write-through）/dual-read compare/consumer cutover/contract 的顺序、回滚条件、负责人和证据。expand 可逆；contract 可能不可逆，恢复依赖备份、保留兼容列/影子结构或前向修复，不能承诺普通 downgrade 即可恢复。
- 旧 `Release` 默认只映射为 `DatasetRelease`。只有存在完整的内容 revision、构建输入、制品 manifest、审批和部署证据时，才可映射为 historic `PublicationRelease`；缺证据必须标记 unresolved，不得推断“曾公开”。
- A0 输出 OpenAPI/client contract、数据差异报告、未解析队列、备份恢复记录、迁移 rehearsal 和消费者切换清单；任一缺失即禁止生产迁移、写入切换或 publication 实现。
- A0 还输出运行时/迁移 wiring reconciliation：README 与 API/Worker Python 约束、Node/前端构建约束、Alembic 配置、迁移目录、Compose 挂载和实际入口必须逐项对应；发现 `migrations` 与开发 Compose `alembic` 路径或 worker/API 要求不一致时，记录为事实差异和验证项，不通过版本升级解决。

## 3. 科学身份、数据集快照与兼容层

### 3.1 稳定对象与不可变数据版本

`rl_release_subject_link` 不再承担快照语义。它只能作为旧系统兼容投影，或在有明确生命周期的映射表中保存历史关联。

```text
rl_scientific_object
  ├─ entity-policy-aware stable identity（namespace + local identity + required scope/parent）
  ├─ object_type / species / assembly_scope
  └─ lifecycle history（active, withdrawn, merged, split）

rl_dataset_release
  ├─ dataset manifest（对象、字段、来源、许可、统计、校验）
  └─ immutable rl_dataset_object_version[]
       └─ object + dataset + source namespace + assembly scope + frozen representation
```

- `rl_scientific_object` 表示跨数据集可持续引用的科学对象；身份规则按实体策略确定：Gene 的唯一键为 `source_namespace + source_identity + assembly_scope`；Transcript 除此之外还必须绑定父 Gene 的 source identity/object relationship。label、显示名和数据库 surrogate key 不能代替科学身份。canonical IRI 冲突进入 diagnostic/resolution，不得静默合并身份。
- public stable ID 必须在其声明的实体类型、namespace、assembly scope（Transcript 还包括父 Gene）范围内唯一，并由服务层和数据库约束共同保证。相同 source identity 出现在不同 species/assembly 时不得合并：先按 assembly scope 分隔，若仍冲突则进入 unresolved mapping，要求注册新的 source namespace 或显式源内 disambiguation；禁止静默覆盖或猜测。
- `rl_dataset_object_version` 表示该对象在某个数据集版本中的冻结表示。版本记录 canonical object reference、assembly scope、输入 artifact/manifest digest、规范化器版本、来源和生命周期；已发布字段不可原地改写，只能创建新版本或新的 change set。
- `rl_dataset_release` 是由 dataset manifest 固定的一组对象版本、关系、注释、来源和许可证据。manifest digest 是数据快照身份的一部分；相同 digest 才可声称输入相同。
- dataset lifecycle 使用追加式 change set：新增、修订、撤回、合并、拆分和替代均记录前后对象版本、原因、证据、生效 dataset release 和兼容解析规则。撤回不删除旧版本；合并/拆分保留旧 identity 和指向。
- source namespace 与 assembly scope 都是身份约束的一部分。Gene/Transcript 旧字符串 ID 通过 adapter 映射到 `rl_scientific_object`，不得静默跨 namespace 或跨 assembly 复用；Transcript 的父 Gene 关系必须可解析且 scope 一致。
- 旧 `Release`、旧 Gene/Transcript、Variant、MutantLine、Expression 等接口由 legacy adapter 提供双读/写入过渡；adapter 必须返回 scope、dataset/publication 证据和 `mapping_status`，不能把未知映射伪装成已发布。
- 首个垂直切片必须同时跑通大豆和一个第二物种的最小真实/受控数据 walking skeleton，覆盖 namespace、assembly scope、对象版本、manifest、页面、搜索和下载；不能等到最后阶段才发现模型只适用于大豆。

### 3.2 逻辑聚合与约束意图

以下是可验证的逻辑契约，不是未经 reconciliation 的物理表 SQL：

| 聚合 | 必须表达 |
|---|---|
| `rl_species` / `rl_assembly_scope` | NCBI TaxID、学名/别名、assembly accession、物种与组装边界、状态 |
| `rl_scientific_object` | namespace、源内 identity、对象类型、生命周期、canonical public ID |
| `rl_dataset_release` / `rl_dataset_object_version` | dataset version、manifest digest、冻结输入、scope、对象版本、change set |
| `rl_legacy_release_mapping` | 旧 Release→DatasetRelease 默认映射，Publication 映射所需证据和 unresolved 原因 |
| `rl_ontology_source` / `rl_ontology_release` | 来源、版本 IRI、原始 artifact URI/SHA-256、许可证、解析/规范化版本、digest |
| term/relation/assertion 聚合 | 版本化术语、谓词、断言、证据、映射和审查决策 |
| import / diagnostic | 输入、阶段、诊断、重试、统计、人工处置和不可变输入 digest |
| publication manifest/artifact/pointer | 冻结输入、制品清单、digest、环境、当前公开指针和 fencing 信息 |
| approval/deployment histories | 绑定快照、命令 digest、目标/修订 hash、策略和追加式结果 |

## 4. Ontology release、闭包与证据治理

### 4.1 Release set 与依赖闭包

一次可治理/可发布的 ontology 不是单一文件，而是不可变 `ontology_release_set`：

- 包含 source release、依赖 source release、版本化 NCBI Taxonomy mapping、evidence-code→ECO mapping release、解析器/规范化器/验证器版本和许可证证据。
- 构建器计算依赖 closure：所有关系谓词、父级/替代项、xrefs、TaxID、ECO term 和 annotation source 均必须在 set 或明确允许的外部 immutable reference 中；每个外部 reference 必须有 URI、digest、版本和许可证，并纳入 closure digest；缺失依赖进入 unresolved，不能以“当前最新版”补齐。
- set 保存有序成员清单、规范化规则和不可变 SHA-256 digest。相同成员版本、映射版本、配置和 closure digest 才是同一 ontology input。
- NCBI Taxonomy mapping/history 按版本保存 TaxID、名称、合并/删除/替代历史和映射来源；更新产生新 mapping release，不改写历史解释。
- 原始 OWL/OBO/GAF/JSON 等放入不可变对象前缀；PostgreSQL 保存 provenance、digest、解析结果、诊断、许可证和治理状态。

### 4.2 关系、断言和 owner/resolution

- 关系保留 subject、predicate term、object、ontology release set、asserted/inferred、来源和有效范围；谓词必须是受治理 term（通常来自 RO/BFO），不能压成任意字符串。canonical IRI 或 normalized local ID 冲突进入 diagnostic/resolution，不能静默合并成同一 term identity。
- 断言至少保留 subject namespace/identity、term、taxon、assembly/dataset scope、relation、qualifier/negation、原始 evidence code、ECO mapping release、reference、with/from、extension、assigned-by、注释来源 release 和时间。
- ontology relation 的 owner 是其声明来源/维护方；annotation assertion 的 owner 是 `assigned_by`/提交方。项目治理者负责接受、拒绝、冲突 resolution，不冒充原始 owner。
- resolution 必须是追加式 decision：`accepted_as_asserted`、`rejected`、`superseded`、`needs_review` 等，并绑定 reviewer、policy revision、理由、时间和输入 digest；不能通过覆盖原行消除冲突。治理接受 ontology release 不等于该术语/断言立即进入 public visibility；公开可见性还需 dataset/publication manifest、许可和发布审批。
- `obsolete`、`deprecated`、`do_not_annotate` 保留历史；`replaced_by` 可按策略形成候选，`consider` 只能进入人工审核。新断言不得指向禁止状态。

### 4.2.1 断言校验与推理边界

- annotation subject 必须是目标 `rl_dataset_object_version`，且该版本必须属于断言声明的 exact dataset release；assembly、species、taxon 必须与对象和 dataset scope 一致，跨 scope 只能走已登记且有证据的 cross-scope policy。
- term、predicate、ECO 必须在冻结的 ontology release set 内解析；原始 evidence code 必须按该 set 的 evidence-code→ECO mapping release 处理。obsolete/do-not-annotate term、未知 TaxID、悬空 reference、未解析 raw evidence 均产生 diagnostic；未解决项阻断 public approval，但原始输入和诊断必须保留。
- 不支持的 qualifier、negation 或 relation 按 policy 阻断 public approval并保留原断言/诊断，不得静默降级为普通正向关系。ontology release 的 governance acceptance 与 public visibility 始终分离。
- 第一阶段只存储来源明确声明的 asserted facts；inferred relation 一律禁止写入公开事实，直到单独批准 inference ADR。BFO predicate 只有在 BFO source release 已注册为 release set member 时才允许引用，否则拒绝。

### 4.3 首批范围与许可证

首批为 NCBI Taxonomy、GO、SO、RO、ECO；PO 仅在首批数据确实需要植物结构/发育语义时通过单独 scope decision 纳入；TO/PATO/ENVO、完整 OWL 推理和大规模表型重构延后。每个 source release 和 dataset source 独立保存 SPDX/URL/归属/再分发状态；`unknown/pending/restricted` 不能进入公开 manifest。manifest 快照许可证证据和 policy decision，不引用构建时“当前策略”。

## 5. 控制面、审批和三条独立追加历史

### 5.1 能力与输入

服务端按显式 capability 授权，前端隐藏不是安全控制。管理员只能选择服务端创建并登记的 upload session、artifact/object ID、immutable template/provider ID 和 schema 校验后的配置；管理命令、manifest 和 promotion 只能引用这些 registered IDs。URI 仅用于 provenance/evidence 展示和追溯，不能作为任意 infrastructure input；不得提交任意路径、Shell、secret、数据库连接或环境变量。break-glass 需短时会话、MFA/重新认证、单独审计，默认关闭。

### 5.2 三个独立历史

审批/状态是三条彼此独立的 append-only history，不是单个状态字段覆盖：

1. **Dataset approval history：** 每次候选、校验、补救、提交、审核、接受/拒绝/过期均为不可变 event；当前投影可重建。accepted event 绑定 dataset manifest digest、ontology release-set digest、license/policy decision、scope 和 quorum。
2. **Publication build/approval history：** 每次 freeze、queue、build、validation、`artifact_ready → submitted_for_publication_review → approved_for_promotion | rejected | expired` 均为不可变 event；build 只能使用批准 revision 和冻结输入，生成完成、校验通过且不可变的 final manifest/artifact digest。最终 publication approval 是独立的追加式审批决定，作用于该 completed validated immutable final manifest digest，并保存在本 publication build/approval history 中。
3. **Deployment-attempt history：** 每次 promotion、失败、补偿、回滚尝试均为新 attempt event；environment-specific deployment approval 是独立 decision binding，必须引用有效的 publication approval ID、artifact manifest digest、environment、policy/quorum/expiry 和 fencing 条件。该 deployment approval 不重新计算或修改 publication approval；promotion 只有在两项 approval 均有效时才可执行。rollback 是指向已验证旧 manifest 的新 deployment attempt，绝不修改旧 approval、build 或 deployment 历史，也不把旧 attempt 标成“从未发生”。

每个高风险 approval binding 必须不可变地包含：canonical command payload digest、target identity/revision hash、冻结输入或 artifact manifest digest、policy revision、environment、quorum/审批者、expiry、职责分离结果、request/correlation/idempotency key。immutable approval policy 只包含 policy revision、eligible rules 和 required quorum；实际 approver 是按该 policy 追加记录的 event，不把 event 重新哈希进 policy digest，避免循环依赖。执行时重新计算并逐项比较；不匹配即拒绝。状态转移、失败和补偿都写独立 audit event；Redis/任务队列不能制造成功事实。

## 6. Publication promotion：数据库、对象存储与 CDN

### 6.1 权威与条件更新

`rl_publication_pointer` 是控制面记录的公开指针，但“只有 PostgreSQL 指针原子更新”不足以保证对外可见原子性。对外真实 authority 是 **公开静态入口所读取的 versioned pointer/ready marker**；PostgreSQL、对象存储和 CDN 必须由 protocol 绑定，任何单层成功都不能单独宣称 promotion 成功。

### 6.2 协议顺序：可恢复 saga

Promotion 是可恢复 saga，不是跨 PostgreSQL、对象存储和 CDN 的 distributed atomic commit；任何外部 I/O 均不在 PostgreSQL transaction 内持有。

1. **Prepare DB transaction：** 验证已获 publication approval 的 final immutable manifest、独立 environment deployment approval、ready artifact set、expected pointer revision 和 fencing 条件；锁定环境并持久化 immutable pointer intent，写入 `promoting`，随后提交事务。artifact composition、artifact write、ready marker 和 final manifest validation 已在 §5.2 的 build/validation history 完成，promotion 不创建、拼装或重写它们。
2. **External CAS：** 在 PostgreSQL 事务之外，使用经过测试的 provider capability adapter，对 public pointer 执行 conditional/CAS switch；pointer 携带 manifest digest、generation、fencing token 和 deployment attempt ID。失败只记录外部诊断，不伪造数据库成功事实。
3. **Finalize DB transaction：** 重新读取 public pointer、ready marker、CDN/provider observation 和 PostgreSQL ledger，追加 observation；只有 CAS 已证明且 smoke/CDN 检查通过时，才将 `verifying → active`。否则追加 `failed` 或 `unknown`，保留可恢复 saga 状态。

对象存储和 CDN 的 artifact composition/write/ready 工作必须在 build/validation 生命周期中完成：隔离 immutable prefix、HEAD/hash/size/content-type/权限/路由检查、ready marker 和最终 manifest 均在 `artifact_ready` 前结束。promotion 只切换已完成的 final ready artifact set；不进行新的 artifact composition 或 manifest rewrite。

在成功 CAS 之前失败，旧 active pointer 保持不变，attempt 可按同一 binding 重试或进入 `failed/unknown`；该规则不适用于已经 proven successful CAS 的情况。

成功 CAS 后 attempt 必须先为 `verifying`，即使 pointer 已经可读也绝不能直接 active。若 smoke/CDN health proven failure，记录 transient exposure、cache window 和 diagnostics，并创建新的 fenced compensation deployment attempt，将 pointer CAS 到 prior verified manifest；补偿 attempt 必须验证 CDN cache window 和最终 digest 一致性，不能修改原 attempt。若 pointer、ready marker 或 CDN 状态不确定，标记 `unknown`、冻结后续 promotion、要求人工 resolution，禁止盲目反向切换。

公开 pointer 必须同时携带 `manifest_digest`、`generation`、`fencing_token` 和 `deployment_attempt_id`。每个对象存储/CDN provider 使用经过测试的 capability adapter，明确其 conditional write/CAS、rename、read-after-write、purge/TTL 和失败语义，不把供应商能力假定为一致。

发布/下载/JBrowse 入口的用户可见摘要必须绑定同一 release：页面先给出 compact 的 Species/TaxID/Assembly/Dataset/Publication scope ledger，展开后显示 canonical URL、manifest digest、来源/许可和当前可用性。`rl_scientific_context_bar` 因此是可检查的 scope ledger，不只是导航切换器；为什么：研究对象的 scope 与 manifest 证据必须可在用户操作前复核，避免跨 assembly 或跨 release 的隐式切换。

对象存储观察还必须覆盖 artifact 已写入但 manifest/pointer 未登记、manifest 已登记但对象不可读、ready marker 与 digest 不一致、以及 orphan artifact 的 divergence。artifact 只有在证明不存在来自 manifest、build、pointer intent、deployment、approval、audit、legal hold、recovery window 的引用，并且经过 grace period 后，才可列为 cleanup candidate；为什么：孤儿判断不能因单次扫描遗漏历史证据而破坏可回滚或审计材料。active manifest 引用的不可读 artifact 是 integrity incident，必须进入 compensation 或 `unknown`，绝不能清理。reconciler 只能按 registered artifact ID、manifest digest、generation 和 fencing/attempt 证据归类为可重试、可清理或 `unknown`；该观察是有限的 artifact lifecycle validation，不改变 Prepare → External CAS → Finalize saga，也不能把清理动作当作 publication success。

reconciler 按以下规则处理不确定结果：

- (a) public pointer 已切换，但 PostgreSQL commit 或结果记录失败：读取 pointer 与 ready marker，比较 digest、generation、fencing 和 attempt ID；若数据库已有同一 intent，则幂等补写同一 attempt 的 observation；若没有可证明的同一 binding，则标记 `unknown`，冻结后续 promotion，交人工 resolution，禁止盲目反向切换。
- (b) DB intent/attempt 已提交，但 public CAS 失败：在未证明 CAS 成功时保留旧 pointer，记录 provider error 和 attempt event；仅在同一 fencing/attempt 下重试 CAS。超过策略次数后标记 `failed` 或 `unknown` 并冻结 promotion，不修改旧成功历史。
- (c) worker retry 无法区分超时前成功或失败：以 attempt ID、fencing token、manifest digest 查询 DB ledger、ready marker 和 public pointer；同一 binding 只允许幂等 finalize，不能新建不同 payload 的成功结果；无法判定时进入 `unknown` 人工 resolution。

### 6.3 恢复目标

默认目标需在实施前由容量和业务确认；设计契约要求记录 RPO、RTO、最大 cache window、artifact reachability retention、备份位置和恢复演练结果。保留策略按 active、审批/审计引用、manifest 引用、法律 hold 和灾备窗口计算可达性，不能固定成“只留 12 个”。每次恢复演练须验证 PostgreSQL、对象存储 pointer/manifest、CDN 入口和内部搜索均能重建到同一 digest。

## 7. 审计 outbox、任务 dispatch 与限制管理

业务审计 outbox 与任务 dispatch outbox 分离：

- `rl_audit_outbox` 与业务写入同一 PostgreSQL 事务，包含 actor、capability、目标、环境、approval binding、命令 digest、sanitized diff、结果和 correlation/idempotency；其消费者只负责投递最终账本。授权失败、校验失败和 rolled-back transaction 也走 failure-audit path，记录拒绝/失败事实和原因，但不能写入 success fact。
- `rl_task_dispatch_outbox` 只表达待执行的构建、校验、reconcile 等任务，带 task payload digest、attempt、lease、重试和去重键；任务投递失败不改变业务成功事实。
- 最终 `rl_audit_ledger` 为 append-only，按分区保存带 serial sequence 的 hash chain，并周期性写入 checkpoint/root digest；保存 canonical event、时间、actor、结果、证据引用和链校验结果。高风险审计至少保留 365 天；法律 hold 可延长，归档需可验证恢复。
- retention 管理不能删除/改写 ledger 事件，只能针对已过期且无 hold 的归档对象执行受控生命周期动作，并产生审计事件。任何 retention policy 变更都必须单独审批、重新认证并写入审计；普通 retention manager 不得缩短高风险最短保留期或绕过 legal hold。高风险单运营者 safeguard 仅允许：重新认证、至少 15 分钟冷静期、预配置通知和明确 policy；不能用普通确认框绕过 quorum。

## 8. 物理约束、不可变性与更新矩阵

实现必须把下列约束落实为可验证的 PostgreSQL/服务层约束；具体列名、索引名和 SQL 待 A0 reconciliation 后确定：

| 对象 | 唯一/检查要求 | 冻结后允许更新 |
|---|---|---|
| `rl_species` | `public_slug` 非空、格式合法且永久唯一；TaxID/名称映射受版本约束 | 仅追加名称/生命周期历史；不改 public slug |
| assembly scope | legacy Assembly mapping 一对一；accession 在 species + source namespace 内唯一；每 species 最多一个 partial-unique default public assembly；species 必须匹配 Taxonomy | 显式 supersede/change set；不改历史 assembly identity |
| scientific object | Gene 用 `(source_namespace, source_identity, assembly_scope)` 唯一；Transcript 再绑定 parent Gene source identity/object；type、scope、parent 组合合法；public stable ID 在声明范围内唯一 | 生命周期 event、canonical link；不改源身份或 parent |
| dataset release/object version | dataset version 对 assembly 永久唯一；主唯一键为 `(dataset_release_id, scientific_object_id)`；representation digest 为不可变字段；如确需多种表示，必须有显式 `representation_role`/`schema_variant`，并将其纳入唯一键，禁止以 digest 隐式制造多重版本 | 仅追加新版本、撤回或 change set |
| dataset manifest | manifest digest 唯一且内容不可变；成员必须存在且同 scope | metadata projection/审计，不改 digest |
| ontology term identity/snapshot | `(source, normalized_local_id)` 唯一；`(identity, ontology_release)` 唯一；closure 完整、许可状态受检 | 新 release/snapshot、resolution event；不改旧快照 |
| ontology release set | member/dependency 组合唯一，set member 清单与 dependency edge 去重；digest 不变 | 新 release set、resolution event |
| synonym/relation/replacement | 按 release、subject/predicate/object 或 synonym canonical form、replacement type 去重；scope/evidence 合法 | resolution/supersede event，不覆盖原事实 |
| approval binding | command/target/input/policy/env/quorum/expiry digest 绑定；approver 去重、拒绝 self-approval、expiry 必须可检查 | 只能追加 reject/expire/execute 结果 |
| artifact/manifest | publication 内 artifact path/object ID 唯一；SHA-256 必须为固定格式和长度，路径、大小、类型与 manifest 一致；published path 不覆盖 | 新 artifact；旧 artifact 只改变 reachability/hold 投影 |
| publication pointer | 每环境至多一个 active pointer；pointer version、generation、CAS/fencing、attempt ID 必须一致 | 新 deployment attempt；不更新旧 attempt |
| audit ledger | event sequence 与前 digest 链接；canonical payload 可重算 | 归档索引/hold 投影，不改事件正文 |

所有冻结/approved/active 字段（source identity、scope、manifest/artifact digest、command payload、审批 binding、历史事件正文、已批准 revision、active pointer）禁止 ORM 普通 update；允许更新必须通过领域命令生成新 event。内容、navigation、module 也只能以 immutable revision snapshot/digest 被 manifest 引用；冻结后不能改变快照，content-version 的唯一策略须在 A0 与实际 schema/consumer reconciliation 后确定。跨对象 scope、生命周期和许可检查必须在服务层与数据库可表达部分双重验证。

## 9. 静态生成与 Internal Search API 契约

### 9.1 确定性构建

SSG、规范化文档、下载包、sitemap 和 manifest 使用同一 publication identity、冻结输入和 generation。内容、navigation、module 只能引用已登记的 immutable revision snapshot/digest，不能读取冻结后仍可变的业务行。构建输入显式固定：数据/ontology/映射 digest、代码/模板 revision、配置、时钟（使用 manifest 的 frozen build time）、locale、timezone、排序规则、压缩器及版本、随机性种子（无随机则声明），并输出 checksums/SBOM/license evidence。管理命令和 manifest 只接受 server-created registered artifact/object ID；URI 仅作 provenance/evidence，禁止任意基础设施输入。禁止读取“当前最新”或未批准草稿。

制品目录只使用 immutable versioned paths；不再生成或依赖旧式游标目录。失败制品隔离，manifest 最后写入并由协议校验后才可 promotion。

每类公开制品必须绑定版本化 `rl_public_projection_schema`，并以其 field allowlist 作为 PRIMARY security boundary；敏感字段扫描是 defense-in-depth，不得替代 allowlist。该 schema/allowlist 覆盖静态 HTML/JSON、search documents/facets/serialized index/directory/API envelope、scope ledger、ontology term projection、provenance/citation 的 summary/expanded/export、JBrowse config/track metadata/launch summary，以及 download catalog/license/sidecar metadata。为什么：公开投影必须由发布时冻结的结构契约决定，不能由模板、搜索引擎或 Worker 临时推断可见字段。

所有公开投影显式禁止 internal object ID、bucket/key、internal URI、presigned/temporary URL、upload session、secret/token（包括 query 中的 token）、unpublished source/diagnostic、internal approval identity 和 restricted policy detail。公开 provenance/citation 只允许 public stable source/version/license/citation、public artifact digest 和 canonical URL；admin evidence 仍受 permission 保护，不因 expanded/export 而公开。scope ledger 必须包含 `scope_type`，只表达该投影适用的 scope levels；不适用的 Species/Assembly/Dataset/Publication level 必须显式标为 unavailable 或 not-applicable，绝不默认填充 assembly/dataset。为什么：缺失上下文与错误默认上下文都可能造成跨版本误读。

扫描仍需检查敏感字段、结构异常和投影/manifest digest 一致性；扫描失败阻断 `artifact_ready`。大体量 binary scientific payload 不使用通用文本扫描替代治理，而按批准的 dataset schema 与 artifact policy 验证；结构化 exports/configs 必须使用 `rl_public_projection_schema` 字段 allowlist。Worker、搜索引擎和 JBrowse 均不得自行扩大公开字段或承担授权。

所有 artifact 先执行 common artifact validation：注册 ID、immutable path、content-type、长度、digest、manifest membership、权限、路由可达性和 ready marker。随后按 capability profile 追加检查：JBrowse random-access track profile 仅在 adapter/format/origin 要求时验证 sidecar、CORS、Range，并将 config、track data、sidecar 的 scope 与 digest 全部绑定；download profile 仅在声明 random/partial/resume、浏览器跨 origin 消费、格式要求 sidecar 或记录的 size threshold 触发时验证 Range/CORS/sidecar。JBrowse 仍只是 visualization subsystem；为什么：能力检查必须匹配实际消费方式，不能把某一类资源的条件误施加到全部制品。

### 9.2 Phase-one Internal Search

第一阶段不承诺旧式游标目录。provider 是一个有界、确定性的 manifest-backed provider：

- 只读 manifest 引用的公开规范化 document shards；范围限定为已发布物种/assembly/dataset、固定最大 shard 数、单次 `limit` 上限、请求超时和结果上限。超出边界返回可解释的 bounded error 或静态目录链接，不偷偷扫描 ORM。
- 查询规范化规则、字段、facet、过滤器、排序均版本化。固定 rank tiers 依次为：exact stable ID、stable-ID prefix、exact alias、title match、summary/body match；同 tier 再以 canonical URL、必要时 object type、stable ID 作为 tie-breaker。该 ranking profile、provider capabilities、边界和版本必须写入 SearchManifest，不能依赖数据库自然顺序。
- provider 不得宣称可进行无界扫描；只在 manifest 声明的最大 shard、文档数、时间和结果边界内工作，超出即返回 bounded error 或静态目录入口。
- cursor 是签名/编码的 continuation token，包含 last rank、完整 sort tuple、position，并绑定 publication manifest digest、scope、canonical query、filter、sort schema、limit 和 provider version。输入任一项变化、manifest 不再保留或 digest 不匹配时明确 invalidated，不能继续解释旧 cursor。
- API envelope 固定返回 `publication_release_id`、dataset scope、stable public ID、canonical URL、provenance、result origin、match explanation 和比较/导出资格。Worker 可以提供更丰富的 fuzzy/prefix 行为，但只共享 envelope 和公开字段/ provenance；不承诺与 API 相同 ranking 或 cursor。
- API envelope 还必须返回由 `rl_public_projection_schema` 约束的 scope ledger（含 `scope_type`、适用 levels、显式 unavailable/not-applicable）、scope explanation 和 `manifest_digest`；公开结果必须能说明“为何属于当前 scope、来自哪一个已发布 manifest”，但 provenance/citation 仅返回 public stable source/version/license/citation、public artifact digest 和 canonical URL。为什么：匹配结果可用不等于上下文正确，用户必须能检查版本边界而不是依赖界面默认值。
- API、Worker、静态目录均不得泄露未公开字段。Worker 校验 manifest/schema/config/hash 失败时调用 API；若 JS、Worker、API 均不可用，静态 directory/index 页面仍能按其固定 publication/dataset/version scope、类型和首字母/分页导航，作为无 JS/service failure fallback。

MiniSearch 可作为 Worker 的实现细节，序列化格式不是长期公共 API。外部搜索仍是独立 endpoint、缓存、限流、超时/熔断和 provenance；外部失败不影响本地搜索。

## 10. 注释、公共语义与 UI 方向

所有 annotation 的 subject、term、taxon、assembly、dataset scope 必须一致；跨 scope 关系只能以显式 cross-scope relation 和 policy 允许的证据表达。公共 manifest 冻结许可证证据、ontology release set、policy decision、citation、生成时间和 digest。

公共端保持静态优先，信息架构为 Discover / Explore / Analyze / Resources；页面始终显示 Species → Assembly → Dataset Release → Publication Release、证据、来源、许可证和生命周期。Admin 采用“科研仪器/Scientific Field Manual”方向：高密度任务工具、低动效、清晰状态、键盘/读屏可用，禁止营销式随机指标、装饰性动画、玻璃化面板和仅靠颜色表达状态。组件名和新业务代码遵守 `rl_` 规则。

UX 语义精化如下，均是设计契约而非已实现能力：

- `rl_ontology_term` 支持 compact、expanded 和 historical 三种阅读状态。compact 显示 human label、namespace/stable ID、release 和生命周期；expanded 仅显示 published release-set 预计算 path 或 bounded ancestor summary，不提供 full ontology tree/inference UI，并显示 source、evidence、license、digest 与 replacement candidates；historical 保留旧 CURIE、旧 release、obsolete/merged/split 原因和可追溯链接。`replaced_by` 仅按政策允许的明确替代展示；`consider` 永远是人工审核候选，不自动 redirect。
- `rl_provenance_citation_panel` 统一 summary、expanded 和 export 行为：公开三种视图只显示 public stable source/version/license/citation、public artifact digest 和 canonical URL；admin evidence 的输入 artifact、内部诊断和审批细节按权限显示。三个视图必须引用同一冻结 snapshot，为什么：引用信息不能因 UI 展开或导出重新推断“当前最新”来源。
- JBrowse 启动前展示由 `rl_public_projection_schema` 约束的 release-pinned launch summary（适用 scope、Species、Assembly、Dataset/Publication、manifest digest、config/track 版本和来源）；若消费方缺少该 artifact capability profile 所声明的能力，UI 必须报告精确缺失项（如 sidecar、Range、CORS、origin 或 digest mismatch），不使用泛化 unavailable，也不猜测或切换到其他 release。
- Admin 发布中心显示 review-evidence matrix 与三条 history timeline：冻结输入、质量/许可/引用、SSG/index/download/hash/SBOM、search/router impact、可访问性/视觉证据、审批职责分离、deployment attempt 和 rollback target 必须逐项呈现；阻断项保持不可操作，不以按钮文案声称已完成四眼审批。
- ontology/import/closure/license/publication failure 进入 `rl_diagnostic_workspace`，显示 error code、阶段、数量、样例、影响 scope、推荐修复、重试/安全取消、resolution decision 和 evidence digest；诊断不能被覆盖式状态更新删除。

## 11. 阶段顺序与验收闸门

顺序固定为 **A0 → A1 → B-pre-ADR → B → C → D → E → F**：

### A0 — 事实与契约闸门

完成上文 Alembic/schema/ORM/OpenAPI reconciliation、README/API/Worker runtime-version documentation reconciliation、`migrations`/开发 Compose `alembic` 目录与运行时 wiring reconciliation、备份恢复、迁移 rehearsal、旧 Release 证据分类、未解析队列、consumer contract 和禁止生产迁移的证据包；不产生 package upgrade mandate。

### A1 — 控制面安全骨架

完成 capability matrix、typed command、approval binding、三条 append-only history、audit/task outbox 分离、ledger hash chain、幂等/并发/失败补偿测试和错误 UI。任何 UI 入口没有后端契约则移除或禁用。

### B-pre-ADR — 数据平面与双物种 walking skeleton

在不改生产 schema 的受控环境，跑通大豆与第二物种的 Species/Taxonomy、Assembly scope、`rl_scientific_object`、dataset object version、manifest、原始 artifact、最小页面/搜索/下载路径；记录规模、对象存储、压缩、RPO/RTO 和 provider 边界，并在 Phase D 前固定初始静态搜索上限：最大 shard 数、最大文档数、单次 timeout、limit 上限和 Worker 内存上限。需要升级或新运行时组件时先独立 ADR。

### B — 领域与 ontology closure

经 A0 批准后实施兼容层、dataset/change set、ontology source/release set/closure、taxonomy history、ECO mapping、annotation scope、许可证和 import diagnostics；真实小样本必须同时覆盖大豆与第二物种。

### C — 确定性 publication 与 promotion

完成冻结输入、构建证据、不可变制品、各公开制品类的 `rl_public_projection_schema`/allowlist、敏感字段扫描、common artifact validation 与按需 capability profiles；验证 pointer/ready marker/CAS/fencing、CDN cache window、partial-failure 与受引用/hold/recovery-window/grace-period 保护的 object-store divergence/orphan reconciliation、reachability retention 和恢复演练；三条历史独立验收。C 只验收构建时制品能力与公开投影安全边界，不宣称消费者 UX 或搜索/JBrowse fallback 已实现；所有 divergence 仍按 saga 证据处理，不能绕过 CAS/fencing。

### D — 双搜索与科学 UX 垂直切片

在 C 的已验证制品能力之上，验收 bounded Internal Search API、签名 cursor、scope explanation/manifest digest API envelope、Worker envelope、无 JS 静态目录回退，以及完全隔离的 External Search API；D 只验证消费者/search/JBrowse 对已声明 capability 缺失、hash mismatch、历史 manifest、外部超时的精确错误与 fallback UX，确认 Worker 非授权边界和两套搜索隔离，不重复宣称 C 的 projection allowlist、扫描或 provider capability build validation。

### E — Admin 工作区与真实业务闭环

按工作台、数据发布、站点内容、发布中心、治理重组；加入 inspectable scope ledger、ontology compact/expanded/historical term、summary/expanded/export provenance-citation、release-pinned JBrowse summary、review-evidence matrix、history timeline 和 `rl_diagnostic_workspace` 语义；只有契约、权限、审批、审计和回滚闭环的功能才显示为可用。第二物种完成端到端发布/回滚证明。

### F — 基准、清理与演进

测量真实数据规模下构建、内存、P50/P95、移动端和恢复指标；只有证据触发时才为 provider/分片/引擎增加独立 ADR。清理不触及保留期、legal hold 或仍可达的证据。

每阶段需有契约、授权、状态机、迁移、制品、搜索、可访问性、备份恢复和回滚证据；在 Oracle 复核与用户确认前不得进入实现阶段。

## 12. 待确认事项与自审结论

仍需用户/Oracle 明确的决策仅有：生产对象存储是 MinIO、S3 还是 POSIX 兼容实现；第二物种及其最小数据集；RPO/RTO、cache window 和容量上限；以及是否因真实植物结构数据纳入 PO。以上未确认项均已有安全默认路径，不得阻塞本设计进入再次评审，也不得在实施时擅自推断。

本次自审已确认：全文不再使用旧式游标目录承诺；不再声称仅 PostgreSQL pointer 即足够原子；不再使用把 dataset、publication、build、deployment 混为一体的三状态描述；旧 Release 到 historic publication 有证据门槛；scope、digest、审批绑定、失败补偿、审计保留、迁移 contract 和第二物种验证均有可执行契约。
