# Plan B：双物种数据平面与本体基础实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` (or an equivalent task-by-task execution workflow) to implement this plan. Every checkbox is a separately reviewable task. Do not batch destructive migration, production cutover, or unrelated cleanup into this plan.

**目标：** 在 A0/A1 已提供事实、契约、授权和 outbox 证据后，以 expand-only 方式建立双物种科学数据基础、不可变数据集版本、受治理 ontology closure、legacy adapter 和最小 ClickHouse scope-binding 证明。

**范围：** B-pre-ADR 受控 walking skeleton，以及 B domain/ontology foundation。

**不包含：** 生产 schema 破坏性替换、Gene/Transcript 主键替换、全量 ClickHouse 重写、完整 phenotype/inference、公开 publication/promotion、PO 默认导入、依赖升级或自动提交。

**前置闸门：**

1. **Gate B-pre-ADR：** 仅在 disposable/controlled environment 中同时跑通 Glycine max（大豆）与一个待决定的第二物种；输出规模、对象存储、压缩、RPO/RTO、provider capability、静态搜索边界和 ClickHouse scope-binding 证据。不能改生产 schema。
2. **Gate B：** 仅在 A0、A1 已通过，且 Gate B-pre-ADR 证据包已评审后，才实施领域/ontology foundation 的 Alembic expand migration、真实小样本导入和双读兼容层。Gate B 结束仍不代表 publication、write-cutover 或 destructive contract 获准。

## 1. 现状与实现边界

先以代码事实而非设计名称为准：

- `apps/api/app/models/genomic.py` 的 `Assembly.species` 是自由文本；`Gene.id` 和 `Transcript.id` 是旧字符串主键，必须保留。
- `apps/api/app/models/content.py` 的 `Release` 同时承载旧数据/发布含义；首阶段只默认映射为 `DatasetRelease`，缺少完整内容 revision、构建输入、manifest、审批和部署证据时写入 unresolved，不推断 historic `PublicationRelease`。
- `apps/api/app/models/variant.py` 的 PostgreSQL `VariantSummary` 及 `MutantLine` 仍保留；大体量 variant facts 在 ClickHouse `variant_facts`。
- `apps/api/app/services/clickhouse_service.py` 当前通过 `_build_where()` 绑定 `assembly`，但没有 dataset/object-version/publication 语义；本计划只增加可回滚的 scope-binding proof，不重写事实表。
- `infra/clickhouse/init.sql` 的 `variant_facts` 以 `(release_id, assembly_id, chromosome, position, ...)` 排序；现有列不应被解释成新的 `rl_dataset_release_id` 事实。
- `apps/api/tests/conftest.py` 使用 `Base.metadata.create_all()`，不能作为 Alembic 验收；B 的 migration test 必须使用真实 Alembic 链路，测试夹具可另加受控扩展夹具。
- `apps/worker/src/soymutdb_worker/tasks/ingest.py` 的 `compute_variant_id()` 以 release/file/坐标/等位基因计算稳定 ID；B 只须把输入 scope 绑定证据传入并验证，不替换 ID 算法。
- `rl_species.public_slug` 是独立、永久且不可普通更新的公共身份；TaxID、学名、俗名和 alias 不属于 slug identity，必须通过独立的 versioned mapping/history 追加解释。

所有新增第一方函数、变量、类型、模块和测试夹具使用 `rl_` 前缀；Alembic revision、框架钩子、已有公共接口和第三方符号除外。非显然规则必须写简短中文 why-comment，例如：

```python
rl_scope_key = f"{rl_species_tax_id}:{rl_assembly_accession}"
# 为什么：旧 assembly/species 是自由文本，先以不可变 scope key 隔离，避免同名组装跨物种误合并。
```

## 2. 工作方式、TDD 与回滚总则

- 每个任务先写失败测试或 contract fixture，再写最小实现，再运行针对性测试；禁止先建“大而全”模型再补测试。
- 每次 migration 只做 expand：新增表、列、索引、外键、诊断和映射；不删除旧列、不改旧主键、不改变旧 API 默认结果。
- backfill 采用可暂停批次和幂等键；冲突、缺失或跨 scope 项进入 `rl_unresolved_mapping`/`rl_diagnostic`，不静默修正。
- rollback 边界：B-pre-ADR 可直接销毁 disposable 数据库、对象前缀和测试 ClickHouse 数据库；B migration rollback 仅在没有任何新表被生产消费者依赖且 A0 已验证 downgrade 路径时允许。真实导入后的“回滚”优先使用新 change set/withdrawn event，不删除历史事实。
- 任何 production write、active pointer、publication、PK replacement、contract/drop、ClickHouse destructive DDL 都停止并要求新的 ADR/用户授权。
- 不执行 `git commit`、`git push`、依赖升级、自动生成提交或修改计划之外的文件。

## 3. Gate B-pre-ADR：受控双物种 walking skeleton

### 3.1 任务 B0：冻结 fixture-selection 决策步骤

- [ ] 在 `docs/superpowers/plans/` 之外不写决策文档；在执行记录/评审附件中建立一个明确的 **second-species fixture-selection decision step**，并在实现前由 Data Steward/Reviewer 签字。
- [ ] 固定候选筛选字段：TaxID 可验证、assembly accession 可追溯、最小 gene/transcript 样本可合法再分发、source release/license 明确、数据量可在 controlled environment 完成、至少一个 ontology assertion/evidence 可解析。
- [ ] 大豆 fixture 固定为受控最小样本，覆盖至少两个 assembly-scoped gene/object、一个 transcript-parent 关系、一个 dataset release、一个 raw artifact 和一个下载记录。
- [ ] 第二物种只在该 decision step 通过后确定；不能用“复制 Glycine max 数据并改 species 字符串”代替第二物种。若证据不足，使用受控 fixture 仅作模型测试并将 `fixture_status=synthetic_controlled`，不得进入 public manifest。
- [ ] 若真实植物结构/发育语义仅 PO 才能表达，记录 PO scope decision；没有证据则不导入 PO。

**验收：** 两个物种的 TaxID、scientific name、assembly accession、fixture provenance、license status 和 fixture status 都可被测试读取；第二物种选择理由和拒绝候选可审计。

### 3.2 任务 B1：controlled storage 与输入封装

新增受控 fixture/脚本应落在现有测试边界内，建议路径：

- `apps/api/tests/fixtures/rl_dual_species/`：不可变小型 TSV/JSON/FASTA metadata fixture；不提交受限真实数据或凭据。
- `apps/api/tests/test_rl_dual_species_walking_skeleton.py`：跨层 contract test。
- `apps/worker/src/soymutdb_worker/tasks/`：仅在已有 worker 注册方式确认后新增 `rl_` import task；不得假设 `ingestion`/`ingest` 注册名。
- `apps/api/app/services/rl_scope_service.py`、`rl_dataset_service.py`、`rl_legacy_adapter.py`：service 层只保留短事务，查询不散落在 router。

输入 envelope 必须完整记录：

```python
rl_input_envelope = {
    "species_tax_id": 3847,
    "assembly_accession": "GCF-example",
    "dataset_version": "fixture-2026-07-19.1",
    "source_namespace": "fixture.glycine_max",
    "artifact_id": "registered-artifact-id",
    "artifact_sha256": "64-lower-hex-digest",
    "license_status": "approved",
    "fixture_status": "controlled",
}
```

```python
def rl_assert_input_envelope(rl_payload: dict[str, object]) -> None:
    rl_required = {
        "species_tax_id", "assembly_accession", "dataset_version",
        "source_namespace", "artifact_id", "artifact_sha256",
        "license_status", "fixture_status",
    }
    rl_missing = rl_required.difference(rl_payload)
    if rl_missing:
        raise ValueError(f"missing input envelope fields: {sorted(rl_missing)}")
    # 为什么：不可变 digest 和许可状态是可发布资格的输入，不允许由导入器在缺失时猜默认值。
```

**验收命令与预期：**

```bash
cd apps/api
pytest -q tests/test_rl_dual_species_walking_skeleton.py
```

预期：两个 fixture 均可加载；缺字段、错误 TaxID、空 digest、`unknown/pending/restricted` license 均失败且产生可断言 error code；不触碰生产数据库。

### 3.3 任务 B2：walking skeleton 端到端链路

- [ ] 以受控 PostgreSQL schema、受控对象存储前缀和独立 ClickHouse database 运行：Taxonomy → Species → AssemblyScope → scientific object → DatasetRelease → ObjectVersion → Manifest → raw artifact → 最小页面/search/download projection。
- [ ] 所有对象引用同时携带 `species_id`/TaxID、`assembly_scope_id`、`dataset_release_id`；任一 scope 缺失时返回明确 unresolved/bounded error。
- [ ] manifest 只引用 registered artifact ID、digest、size、content type、license evidence 和 canonical provenance；不得把 local path、bucket secret、presigned URL 或 internal object ID 放入 public projection。
- [ ] 页面、搜索、下载只读 controlled manifest-backed projection；不让 public path 直接查询 ORM live rows。
- [ ] 记录实际：raw/compressed/decompressed bytes、object count、shard/doc count、Worker load/query P50/P95、memory peak、ClickHouse query latency、RPO/RTO、provider read-after-write/CAS/Range/CORS 能力。

最小检查函数示例：

```python
def rl_assert_manifest_scope(rl_manifest: dict[str, object]) -> None:
    rl_scope = rl_manifest.get("scope_ledger")
    if not isinstance(rl_scope, dict):
        raise AssertionError("scope ledger is required")
    for rl_key in ("scope_type", "species", "assembly", "dataset"):
        if rl_key not in rl_scope:
            raise AssertionError(f"scope ledger missing {rl_key}")
    # 为什么：scope ledger 防止页面、下载和索引从不同快照拼接，缺失上下文不能默认为当前物种。
```

**Gate B-pre-ADR 退出标准：**

- [ ] soybean + 第二物种完整 walking skeleton 通过；跨物种 identity 不碰撞。
- [ ] 旧 `Release`/旧 Gene/Transcript/Variant API 的 controlled dual-read compare 有差异清单；未知映射进入 unresolved。
- [ ] 固定初始 Internal Search ceilings：最大 shard 数、最大文档数、单次 timeout、`limit` 上限、Worker memory ceiling、压缩/解压大小；超限返回 bounded error/API/static-directory fallback，不换引擎。
- [ ] ClickHouse proof 证明 scope binding 可加入而不改变旧事实或查询结果；未证明前禁止修改 `variant_facts` 主排序/分区。
- [ ] 评审包包含 fixture-selection decision、命令输出、digest、规模、provider boundary、回滚步骤和剩余风险。Gate B 未通过不得执行 B migration。

## 4. Gate B：expand-only domain foundation

### 4.1 任务 B3：逻辑模型与物理映射

在 A0 的实际 Alembic/schema reconciliation 结果之上，新增模型建议分文件，避免把 `genomic.py`/`content.py` 进一步变成跨域巨型模块：

- `apps/api/app/models/rl_species.py`：`RlSpecies`、`RlTaxonomyName`、`RlTaxonomyHistory`、`RlAssemblyScope`。
- `apps/api/app/models/rl_scientific_object.py`：`RlScientificObject`、`RlScientificObjectLifecycleEvent`。
- `apps/api/app/models/rl_dataset.py`：`RlDatasetRelease`、`RlDatasetManifest`、`RlDatasetObjectVersion`、`RlDatasetChangeSet`、`RlDatasetChange`。
- `apps/api/app/models/rl_ontology.py`：source/release/release-set/term/synonym/relation/replacement。
- `apps/api/app/models/rl_assertion.py`：assertion/evidence/ECO mapping。
- `apps/api/app/models/rl_import.py`：import run/stage/diagnostic/retry/unresolved/license evidence。
- `apps/api/app/models/rl_legacy.py`：旧 ID/Release mapping 和 adapter status。

代表性 SQL 形状如下；实际列类型、命名、FK 和 index 必须先依据 A0 reconciliation 调整：

```sql
CREATE TABLE rl_species (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    public_slug varchar(128) NOT NULL,
    status varchar(32) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_rl_species_public_slug UNIQUE (public_slug)
);

CREATE TABLE rl_species_taxonomy_mapping (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    species_id uuid NOT NULL REFERENCES rl_species(id),
    ncbi_tax_id bigint NOT NULL,
    scientific_name varchar(512) NOT NULL,
    common_name varchar(512),
    taxonomy_release_id uuid NOT NULL,
    valid_from timestamptz NOT NULL,
    valid_to timestamptz,
    mapping_digest char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (species_id, taxonomy_release_id, mapping_digest)
);

CREATE TABLE rl_species_name_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    species_id uuid NOT NULL REFERENCES rl_species(id),
    name_kind varchar(32) NOT NULL,
    name_value varchar(512) NOT NULL,
    source_namespace varchar(128) NOT NULL,
    taxonomy_release_id uuid NOT NULL,
    mapping_digest char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (species_id, name_kind, name_value, taxonomy_release_id, mapping_digest)
);

CREATE TABLE rl_assembly_scope (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    species_id uuid NOT NULL REFERENCES rl_species(id),
    source_namespace varchar(128) NOT NULL,
    assembly_accession varchar(256) NOT NULL,
    assembly_version varchar(128),
    is_default_public boolean NOT NULL DEFAULT false,
    status varchar(32) NOT NULL,
    UNIQUE (species_id, source_namespace, assembly_accession)
);

CREATE UNIQUE INDEX uq_rl_assembly_one_default
    ON rl_assembly_scope (species_id)
    WHERE is_default_public;

CREATE TABLE rl_scientific_object (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    object_type varchar(64) NOT NULL,
    source_namespace varchar(128) NOT NULL,
    source_identity varchar(512) NOT NULL,
    assembly_scope_id uuid NOT NULL REFERENCES rl_assembly_scope(id),
    parent_object_id uuid REFERENCES rl_scientific_object(id),
    public_stable_id varchar(512) NOT NULL,
    lifecycle varchar(32) NOT NULL,
    UNIQUE (object_type, source_namespace, source_identity,
            assembly_scope_id, parent_object_id)
);

CREATE TABLE rl_dataset_release (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    assembly_scope_id uuid NOT NULL REFERENCES rl_assembly_scope(id),
    dataset_version varchar(128) NOT NULL,
    manifest_digest char(64) NOT NULL,
    lifecycle varchar(32) NOT NULL,
    UNIQUE (assembly_scope_id, dataset_version),
    UNIQUE (manifest_digest)
);

CREATE TABLE rl_dataset_object_version (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_release_id uuid NOT NULL REFERENCES rl_dataset_release(id),
    scientific_object_id uuid NOT NULL REFERENCES rl_scientific_object(id),
    representation_digest char(64) NOT NULL,
    representation_role varchar(64) NOT NULL DEFAULT 'canonical',
    source_artifact_id uuid NOT NULL,
    UNIQUE (dataset_release_id, scientific_object_id, representation_role)
);
```

`RlScientificObject` 的 service-level identity key 必须按实体 policy 校验：Gene 为 namespace + source identity + assembly scope；Transcript 还必须有 parent Gene 且 parent scope 相同。canonical IRI 冲突写 diagnostic，不合并。

`RlSpecies` 只拥有 `public_slug` 这一项永久公共身份：数据库必须对 `public_slug` 建立独立的全局 unique constraint，且服务层禁止普通 update。TaxID、scientific name、common name、alias 和其解释版本都存于 `RlSpeciesTaxonomyMapping`/`RlSpeciesNameHistory`；Taxonomy release 变化只能追加新 mapping/history row，不能更新旧 row 或通过改写 `RlSpecies` 重新解释历史。为什么：slug 是稳定 URL 身份，分类学名称与 TaxID 是随来源版本变化的解释，二者混用会让旧快照被静默改写。

### 4.2 任务 B4：Alembic expand migration 与 migration tests

- [ ] A0 确认 current head 后，在 `apps/api/migrations/versions/` 新增一个独立 revision（revision 名按 A0 事实，不预设数字），只创建 `rl_*` 表、约束、索引和必要兼容列。
- [ ] migration 不修改 `releases.id`、`genes.id`、`transcripts.id`、`variant_facts`；不把旧 `Release` 直接 rename 成 DatasetRelease。
- [ ] backfill 仅建立 `rl_legacy_release_mapping` 和 unresolved 状态，不宣称旧 release 曾公开。
- [ ] 每一张新表的 `upgrade()`/可逆 `downgrade()` 都有 schema inspection test；必须实际验证 `public_slug` 的独立永久 unique constraint、普通 slug update 拒绝、TaxID/name mapping/history 追加而非旧 row update、partial unique、digest format、scope FK 和 append-only event protection。

命令（在 A0 指定的 disposable PostgreSQL URL 下执行）：

```bash
cd apps/api
alembic current
alembic upgrade head
alembic downgrade <B_PREVIOUS_REVISION>
alembic upgrade head
pytest -q tests/test_rl_migrations.py tests/test_rl_legacy_mapping.py
```

预期：`upgrade → downgrade（仅可逆部分）→ upgrade` 成功；第二次 upgrade 幂等；旧表/列/主键仍存在；重复 `public_slug` 被 PostgreSQL 拒绝；对已存在 Species 执行普通 slug update 被服务层/数据库保护拒绝；TaxID、scientific/common/alias 变化通过新 taxonomy mapping/history row 追加，旧 species identity 与旧 mapping row 不变；非法跨 scope FK、重复 digest、重复 object version、第二 default assembly 被 PostgreSQL 拒绝。若 A0 证明此 downgrade 不安全，必须明确标记该 revision irreversible、保留备份/兼容结构，不伪造普通 downgrade 可恢复。

测试必须区别 `Base.metadata.create_all()` 与 Alembic：`tests/test_rl_migrations.py` 不得只调用 `create_all()`；现有 `apps/api/tests/conftest.py` 夹具可继续供旧测试使用，但 B migration test 必须执行 CLI/同期 migration runner。

### 4.3 任务 B5：Species/Taxonomy、AssemblyScope 与科学对象服务

- [ ] 在 `apps/api/app/services/rl_species_service.py` 中实现 create/register/resolve，要求 TaxID、name source、status、license/provenance 完整；`public_slug` 只在创建时注册且永久唯一，普通 update 必须拒绝；TaxID、scientific/common/alias 变化通过 taxonomy mapping/name history 追加保存。
- [ ] 在 `apps/api/app/services/rl_scientific_object_service.py` 中实现 `rl_register_scientific_object()`、`rl_resolve_scientific_object()`、`rl_record_lifecycle_event()`；禁止 label、display name 或 surrogate key 替代科学身份。
- [ ] 在 `apps/api/app/api/v1/` 新增 router 前先写 OpenAPI contract test；router 只做协议、认证和 capability 检查，service 负责事务。
- [ ] 旧 `Assembly.species` 仅作为 adapter 输入；新 scope 以 Taxonomy + accession 建立，不回写旧自由文本。
- [ ] 旧 Gene/Transcript 通过 mapping 建立 `legacy_id → scientific_object_id`；跨 namespace、assembly、parent mismatch 进入 unresolved。

代表性 Species 服务保护：

```python
async def rl_append_species_taxonomy_mapping(
    rl_session: AsyncSession,
    *,
    rl_species_id: UUID,
    rl_tax_id: int,
    rl_scientific_name: str,
    rl_common_name: str | None,
    rl_taxonomy_release_id: UUID,
    rl_mapping_digest: str,
) -> RlSpeciesTaxonomyMapping:
    rl_species = await rl_get_species(rl_session, rl_species_id)
    if rl_species is None:
        raise RlScopeError("species_not_found")
    rl_mapping = RlSpeciesTaxonomyMapping(
        species_id=rl_species_id,
        ncbi_tax_id=rl_tax_id,
        scientific_name=rl_scientific_name,
        common_name=rl_common_name,
        taxonomy_release_id=rl_taxonomy_release_id,
        mapping_digest=rl_mapping_digest,
        valid_from=datetime.now(timezone.utc),
    )
    rl_session.add(rl_mapping)
    # 为什么：TaxID/名称是版本化解释，追加新 mapping 才能重建旧 release 的历史含义。
    await rl_session.flush()
    return rl_mapping


async def rl_update_species_slug(*_args: object, **_kwargs: object) -> NoReturn:
    raise RlIdentityError("public_slug_is_permanent")
```

`rl_update_species_slug()` 不是新的运行时服务，而是领域命令的明确拒绝契约；任何 ORM 普通 update 都必须被数据库触发器/权限边界或 service guard 拦截并有测试证据。TaxID/name history 只能通过追加 mapping/history 命令写入，不能以 update 旧历史行实现。

代表性服务代码：

```python
async def rl_register_gene_object(
    rl_session: AsyncSession,
    *,
    rl_namespace: str,
    rl_source_id: str,
    rl_assembly_scope_id: UUID,
    rl_parent_gene_id: UUID | None = None,
) -> RlScientificObject:
    rl_scope = await rl_get_assembly_scope(rl_session, rl_assembly_scope_id)
    if rl_scope is None:
        raise RlScopeError("assembly_scope_not_found")
    if rl_parent_gene_id is not None:
        raise RlIdentityError("gene_cannot_have_parent")
    rl_object = RlScientificObject(
        object_type="gene",
        source_namespace=rl_namespace,
        source_identity=rl_source_id,
        assembly_scope_id=rl_assembly_scope_id,
        public_stable_id=f"{rl_namespace}:{rl_source_id}",
        lifecycle="active",
    )
    rl_session.add(rl_object)
    # 为什么：身份一旦写入就只允许生命周期事件变化，避免重导入覆盖历史解释。
    await rl_session.flush()
    return rl_object
```

### 4.4 任务 B6：DatasetRelease、Manifest、ObjectVersion、ChangeSet

- [ ] `RlDatasetRelease` 的 manifest digest、assembly scope 和 dataset version 不可原地改变。
- [ ] `RlDatasetManifest` 保存成员 object version、字段/schema、source release、license decision、统计、input artifact digest 和 closure digest。
- [ ] `RlDatasetObjectVersion` 默认每个 `(dataset_release_id, scientific_object_id)` 一个 canonical version；多表示只有 B-pre-ADR 证明需要且显式 `representation_role`/`schema_variant` 后才允许。
- [ ] `RlDatasetChangeSet` 追加新增、修订、withdraw、merge、split、replace；旧 object/version 不删除，change 绑定 reason/evidence/effective release。
- [ ] manifest build 拒绝 mixed species/assembly、缺成员、digest 不一致、license 非 approved、unresolved diagnostics 未处理的 release。

```python
@dataclass(frozen=True)
class RlDatasetChange:
    rl_change_type: Literal["add", "revise", "withdraw", "merge", "split", "replace"]
    rl_before_object_version_id: UUID | None
    rl_after_object_version_id: UUID | None
    rl_reason: str
    rl_evidence_digest: str
    rl_effective_dataset_release_id: UUID

    def rl_validate(self) -> None:
        if self.rl_change_type == "withdraw" and self.rl_after_object_version_id is not None:
            raise ValueError("withdraw cannot silently create a replacement")
        if not self.rl_reason or len(self.rl_evidence_digest) != 64:
            raise ValueError("change set requires evidence-bearing reason and digest")
        # 为什么：撤回、合并和替代必须能重放，不能靠覆盖当前行丢失历史。
```

### 4.5 任务 B7：Legacy adapters、dual-read、unresolved queue

- [ ] 新增 `apps/api/app/services/rl_legacy_adapter.py`，适配旧 `Release`、Gene/Transcript、Variant、MutantLine、Expression、Homolog 的读取。
- [ ] adapter 返回 `mapping_status`（`resolved`/`unresolved`/`ambiguous`/`withdrawn`）、species、assembly、dataset evidence、source namespace 和 diagnostic IDs。
- [ ] legacy endpoint 默认保留旧 response shape；新增 optional scope/evidence envelope，不破坏已有 client。
- [ ] dual-read compare 在 controlled environment 同时读 legacy 与 new projection，分类 exact match、normalized match、missing、conflict、unresolved；差异不得静默吞掉。
- [ ] write-through/consumer cutover 不在 B 执行；B 只实现受控 command 入口和 shadow compare，生产 write-cutover 留待 A0/A1/C/D 后另行授权。

```python
class RlLegacyMappingResult(TypedDict):
    legacy_id: str
    scientific_object_id: str | None
    mapping_status: Literal["resolved", "unresolved", "ambiguous", "withdrawn"]
    scope: dict[str, str | int | None]
    diagnostic_ids: list[str]


async def rl_adapt_legacy_gene(rl_gene_id: str) -> RlLegacyMappingResult:
    rl_candidates = await rl_lookup_mapping(rl_gene_id)
    if len(rl_candidates) != 1:
        await rl_enqueue_unresolved(rl_gene_id, reason="non_unique_legacy_mapping")
        return {
            "legacy_id": rl_gene_id,
            "scientific_object_id": None,
            "mapping_status": "ambiguous" if rl_candidates else "unresolved",
            "scope": {"species": None, "assembly": None, "dataset": None},
            "diagnostic_ids": ["legacy_mapping_non_unique"],
        }
    return rl_mapping_to_result(rl_candidates[0])
```

**为什么：** legacy compatibility must reveal uncertainty rather than making old string IDs look like governed scientific identity.

### 4.6 任务 B8：ClickHouse non-destructive scope-binding proof

- [ ] 不修改 `infra/clickhouse/init.sql` 的现有 `variant_facts` 分区、排序、列语义，先用独立 proof table/view 或 controlled shadow insert 验证 binding。
- [ ] proof row 至少保存 old `release_id`/`assembly_id`、`rl_dataset_release_id`、`rl_assembly_scope_id`、source artifact digest、object-version digest、mapping status 和 proof run ID；未知 mapping 不写作 resolved。
- [ ] 在 `apps/api/app/services/clickhouse_service.py` 增加可选、白名单化的 `rl_scope_binding` filter，旧调用无该参数时生成完全相同 SQL/结果；参数仍通过 `parameters=` 绑定。
- [ ] 在 `apps/api/tests/test_rl_clickhouse_scope_binding.py` mock client，断言没有 user-controlled table/column interpolation，并对 same release/assembly、wrong scope、unresolved mapping 做结果断言。
- [ ] 在 controlled ClickHouse 中比较 old query 与 scoped query 的行数、variant IDs、position ordering、latency；不执行 `ALTER TABLE ... DROP`、重分区、ReplacingMergeTree replacement 或全量 backfill。

代表性查询契约：

```python
def rl_build_scope_predicate(rl_scope: RlScopeFilter) -> tuple[str, dict[str, object]]:
    rl_conditions = ["assembly_key = %(rl_assembly)s"]
    rl_params: dict[str, object] = {"rl_assembly": rl_scope.assembly_key}
    if rl_scope.dataset_release_key is not None:
        rl_conditions.append("dataset_release_key = %(rl_dataset)s")
        rl_params["rl_dataset"] = rl_scope.dataset_release_key
    # 为什么：scope 是身份/发布边界，必须与用户输入值分离绑定，不能拼接列名或表名。
    return " AND ".join(rl_conditions), rl_params
```

如果旧 ClickHouse 表没有 `dataset_release_key`，proof 必须在 shadow table/view 完成，不能假装生产事实已有该列。Gate B 只验收“可绑定且旧查询无回归”的证据，不验收 ClickHouse rewrite。

### 4.7 任务 B9：Ontology source/release/release-set/closure

首批 source/release-set 固定为 **NCBI Taxonomy、GO、SO、RO、ECO**：

- `apps/api/app/models/rl_ontology.py`：`RlOntologySource`、`RlOntologyRelease`、`RlOntologyReleaseSet`、`RlOntologyReleaseSetMember`、`RlOntologyDependencyEdge`、`RlOntologyTerm`、`RlOntologySynonym`、`RlOntologyRelation`、`RlOntologyReplacement`。
- 每个 source/release 保存 public URI、version IRI/accession、raw artifact ID/SHA-256、parser/normalizer/validator version、SPDX/license URL、attribution、redistribution status、release state。
- release set 保存有序 member list、dependency closure digest、Taxonomy mapping release、evidence-code→ECO mapping release 和 closure config digest。
- closure builder 必须解析所有 parent、relation predicate、replacement、xref、TaxID、ECO、annotation source；缺依赖进入 unresolved，不能用“当前最新版”补齐。
- canonical IRI/normalized ID 冲突写 diagnostic/resolution，不静默合并。
- term lifecycle 保留 obsolete/deprecated/do_not_annotate；`replaced_by` 是候选替代，`consider` 永远人工 review，不自动 redirect。
- 首阶段只存 asserted facts；inferred relation 必须拒绝，除非另有 inference ADR。

### 4.8 任务 B10：terms、synonyms、relations、replacements

导入器按 source release snapshot 写入 append-only rows：

```python
class RlTermSnapshot(BaseModel):
    rl_release_id: UUID
    rl_namespace: str
    rl_local_id: str
    rl_canonical_iri: AnyUrl
    rl_label: str
    rl_definition: str | None = None
    rl_lifecycle: Literal["active", "obsolete", "deprecated", "do_not_annotate"]
    rl_replacement_candidates: tuple[str, ...] = ()


class RlRelationSnapshot(BaseModel):
    rl_release_set_id: UUID
    rl_subject_term_id: UUID
    rl_predicate_term_id: UUID
    rl_object_term_id: UUID
    rl_asserted: bool = True
    rl_source_release_id: UUID
```

验收约束：同一 release 中 duplicate synonym/relation/replacement 被去重或诊断；predicate 不在 frozen release set 中则拒绝；obsolete/do-not-annotate term 不得成为新 public assertion target；replacement 关系必须保留原 term 与 policy decision。

### 4.9 任务 B11：Assertions、evidence、ECO 与 annotation scope

- [ ] `RlAnnotationAssertion` 绑定 exact `rl_dataset_object_version_id` 与 exact `rl_dataset_release_id`，保存 subject namespace/identity、term、taxon、assembly/dataset scope、relation、qualifier、negation、raw evidence code、ECO mapping release、reference、with/from、extension、assigned_by、source release 和 asserted time。
- [ ] `RlEvidenceCodeMapping` 以 release set 固定 raw evidence code → ECO term；unknown raw code 进入 diagnostic，不补当前 ECO。
- [ ] `RlEvidence` 保存 reference/citation、source artifact digest、license evidence、parser/validator version 和 owner。
- [ ] 校验 species/taxon/assembly/dataset 与 object scope 一致；跨 scope 只有注册的 cross-scope policy + evidence 才能通过。
- [ ] 不支持 qualifier、negation 或 relation 不降级为普通正向关系；阻断 public approval 并保留原始断言/diagnostic。

```python
def rl_validate_assertion_scope(
    rl_assertion: RlAssertionInput,
    rl_object: RlDatasetObjectVersion,
) -> None:
    if rl_assertion.dataset_release_id != rl_object.dataset_release_id:
        raise RlDiagnosticError("assertion_dataset_scope_mismatch")
    if rl_assertion.assembly_scope_id != rl_object.assembly_scope_id:
        raise RlDiagnosticError("assertion_assembly_scope_mismatch")
    if rl_assertion.raw_evidence_code and not rl_assertion.eco_mapping_release_id:
        raise RlDiagnosticError("raw_evidence_unmapped")
    # 为什么：断言的生物学意义依赖 exact object/scope/release，跨快照拼接会制造不可复现事实。
```

### 4.10 任务 B12：Import stages、diagnostics、retry 与 license gates

导入状态机必须按阶段追加记录，而不是覆盖一个 `status`：

```text
registered
  → license_checked
  → downloaded_verified
  → detected
  → parsed
  → normalized
  → mapped
  → closure_checked
  → quality_checked
  → review_required | accepted | rejected
```

新增建议路径：

- `apps/api/app/services/rl_import_service.py`：stage transitions、idempotency、retry policy、safe cancel。
- `apps/api/app/services/rl_diagnostic_service.py`：error code/count/sample/impact scope/recommended repair/evidence digest/resolution event。
- `apps/api/tests/test_rl_import_diagnostics.py`：阶段、retry、cancel、license gate、unresolved assertions。
- `apps/worker/src/soymutdb_worker/tasks/rl_ontology_import.py`：worker task，必须在 `apps/worker/src/soymutdb_worker/main.py` 的实际注册路径经 contract test 确认。

diagnostic 最少字段：`diagnostic_id`、`import_run_id`、stage、severity、error_code、count、bounded sample、scope、source artifact digest、parser version、retryable、resolution status、resolution evidence digest、created_at。retry 只能重试同一 immutable input digest + stage + idempotency key；修复后的输入必须产生新 import run。

license gate：

- `approved` 才能进入 dataset manifest/public projection。
- `unknown`、`pending`、`restricted` 必须保留 raw artifact 和诊断，但阻断 dataset/public approval。
- source release 与 dataset source 分别保存 SPDX/URL/attribution/redistribution status；不能只检查 ontology source 而忽略 annotation/data source。
- license policy decision 本身冻结进 manifest；不能在构建时读取“当前策略”替代历史证据。

### 4.11 任务 B13：PO decision 与明确延期项

- [ ] 对 PO 只实现 `scope decision` 输入/记录，不默认建立 PO source release。
- [ ] 决策步骤检查真实首批大豆/第二物种 fixture 是否有 plant structure/development assertion，GO/SO/RO/ECO 是否不足以表达；若没有证据，记录 `deferred_no_evidence`。
- [ ] TO/PATO/ENVO、大规模 phenotype remodeling、完整 OWL inference、graph database、search cluster、ClickHouse rewrite 均写入 deferred list 和触发条件。
- [ ] 后续若要纳入 PO，必须新建有输入样本、license、owner、closure 规模、public projection、rollback 和容量证据的 ADR；B 不执行。

## 5. 测试与验收矩阵

### 5.1 单元/TDD

- `tests/test_rl_identity_policy.py`：永久 `public_slug` identity、重复 slug 拒绝、普通 slug update 拒绝、TaxID/name mapping history append-only、Gene/Transcript identity、parent/scope mismatch、canonical IRI conflict。
- `tests/test_rl_manifest_invariants.py`：digest、member completeness、single canonical representation、license/publication block。
- `tests/test_rl_ontology_closure.py`：NCBI Taxonomy + GO + SO + RO + ECO closure、missing dependency、obsolete/replacement/consider、unregistered predicate。
- `tests/test_rl_assertions.py`：ECO mapping、raw evidence、qualifier/negation、exact dataset/object scope。
- `tests/test_rl_import_diagnostics.py`：stage transitions、retry same digest、new run after changed input、bounded sample、safe cancel。
- `tests/test_rl_legacy_adapter.py`：resolved/unresolved/ambiguous/withdrawn、dual-read difference classification。
- `tests/test_rl_clickhouse_scope_binding.py`：parameter binding、old/new result equality、wrong scope rejection、no destructive SQL.

### 5.2 集成/迁移

```bash
cd apps/api
pytest -q tests/test_rl_migrations.py tests/test_rl_identity_policy.py \
  tests/test_rl_manifest_invariants.py tests/test_rl_ontology_closure.py \
  tests/test_rl_assertions.py tests/test_rl_import_diagnostics.py \
  tests/test_rl_legacy_adapter.py tests/test_rl_clickhouse_scope_binding.py
```

预期：全部通过；若 testcontainers/controlled ClickHouse 未可用，测试必须明确 skip 原因并由 B-pre-ADR evidence command 补齐，不能以 SQLite 或 `create_all()` 替代 PostgreSQL migration proof。

### 5.3 双物种验收

- 两物种各至少一个 assembly scope、两个 scientific object、一个 transcript-parent 或等价关系、一个 dataset object version、一个 manifest、一个 raw artifact、一个 license evidence、一个 assertion/evidence。
- 两物种各有独立且永久唯一的 `public_slug`；重复 slug 创建失败，普通 slug update 失败；TaxID、scientific/common/alias 变化只新增 taxonomy mapping/name history，旧 Species identity 和旧解释仍可按 release 重放。
- 同一 source identity 在不同 assembly/species 不被合并；不同 source namespace 同名 label 不被合并。
- 页面/search/download 的 scope ledger 显示正确 TaxID、species、assembly、dataset、manifest digest；不含内部 ID/path/credential/presigned URL/diagnostic。
- old endpoint 默认行为无破坏；new envelope 能说明 mapping status 和 unresolved 原因。
- ClickHouse old query 不变；scoped proof 只增加受控过滤/影子绑定，结果和排序有证据。

## 6. Gate B 退出、停线与回滚

**Gate B 通过条件：**

1. A0/A1 评审通过记录可定位，且 B-pre-ADR evidence package 已签收。
2. Alembic expand migration 在 disposable PostgreSQL 完成真实 upgrade/downgrade（或有明确 irreversible boundary、备份和保留兼容结构）。
3. 两物种真实/受控小样本通过 identity、dataset version、manifest、ontology closure、assertion、license 和 import diagnostics 测试。
4. `public_slug` duplicate/update rejection 与 TaxID/name mapping-history append-only proof 通过；旧 Species identity 和旧历史解释未被更新覆盖。
5. legacy dual-read compare 和 unresolved queue 可重放；没有静默跨 scope 合并。
6. ClickHouse scope-binding proof 非破坏、参数化、旧查询无回归；没有事实重写。
7. PO、phenotype/inference、destructive PK/cutover、full ClickHouse rewrite 均保持 deferred。

**立即停线条件：** A0 发现实际 schema 与预期不一致；migration 需要 drop/rename/PK change；license 未知却要进 manifest；closure 缺依赖却要继续；scope mismatch 被当成 resolved；ClickHouse 需要重分区；worker task registration 无法证明；或测试只能依赖 `Base.metadata.create_all()`。

**回滚：**

- B-pre-ADR：停止 worker、删除 controlled DB/ClickHouse proof DB 和未登记对象前缀，保留 digest、logs、diagnostics 和评审证据。
- B migration：在无消费者依赖时按已验证 downgrade 移除 expand 结构；有新事实依赖时不删除行，改用 forward-fix/withdrawn change set，恢复旧应用仍依赖旧表。
- ontology/import：不覆盖旧 release/term/assertion；标记 rejected/withdrawn，建立新 release set 或新 import run。
- Species identity：不改 `public_slug`，不更新旧 TaxID/name mapping/history；分类学变化只追加新 mapping/history，若新解释不合规则标记 rejected/unresolved 并保留旧解释。
- legacy adapter：关闭 feature flag/route capability，继续旧读；不删除 mapping history。
- ClickHouse：不回滚旧事实；停止 scoped proof consumer，恢复旧 query path；shadow table/view 可独立销毁，生产 `variant_facts` 不执行 destructive rollback。

## 7. 实施后自审清单

- [ ] 本计划只会新增/修改目标实现文件和测试文件；当前交付阶段只写本计划文件。
- [ ] 所有新增第一方符号使用 `rl_`，已有公共接口、migration framework 和第三方符号例外。
- [ ] 非显然身份、scope、版本、license、migration、性能和安全规则都有中文 why-comment。
- [ ] `public_slug` 与 TaxID/name history 语义已分离：slug 独立永久唯一且普通 update 被拒绝；TaxID、scientific/common/alias 只经 versioned mapping/history 追加，不覆盖旧解释。
- [ ] 两个显式 gates、A0/A1 prerequisite、second-species fixture decision、PO defer 和所有 destructive defer 均可定位。
- [ ] 命令包含 migration、unit/integration、ClickHouse proof 和 expected outcomes；测试没有把 `create_all()` 当 migration proof。
- [ ] 没有任何自动 commit、push、依赖升级、生产 cutover 或未授权文件修改。
