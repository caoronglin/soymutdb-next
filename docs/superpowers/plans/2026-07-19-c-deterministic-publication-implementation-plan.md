# Plan C：确定性 Publication、不可变制品与可恢复 Promotion

> **已归档（2026-10-01）**：已被现行计划取代的历史实施计划。继任：`docs/aegis/plans/` 与 `docs/aegis/INDEX.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` (or an equivalent task-by-task executor) to implement this plan. Execute one narrow task at a time, keep the stated file ownership, run the listed gate before advancing, and stop at any failed gate.

**状态：** 仅实施计划，未授权实现、迁移、依赖变更或部署变更。

**前置硬闸门：** 本计划明确 **blocked on A0/A1/B evidence**。只有以下证据包通过各自审核、并完成用户/Oracle 对实施计划的批准后，才允许执行 C 的第一项代码变更：

- **A0**：实际 Alembic revision、已部署 schema、ORM metadata、OpenAPI/client/consumer、Worker 注册、运行时与迁移 wiring reconciliation；disposable PostgreSQL 的 `upgrade → 可逆部分 downgrade → upgrade`、备份恢复、空库重建、旧 `Release` 证据分类和 unresolved 队列。
- **A1**：`rl_` capability matrix、typed command、approval binding、requester/approver separation、三条独立 append-only histories、`rl_audit_outbox` 与 `rl_task_dispatch_outbox` 的事务边界、hash-chain/retention、幂等/并发/失败补偿证据。
- **B-pre-ADR/B**：大豆与第二物种 walking skeleton、`Species → AssemblyScope → DatasetRelease → immutable ObjectVersion`、ontology release-set closure、许可/诊断证据、对象存储能力和规模基准；至少固定 C 所需的对象存储 provider、RPO/RTO、cache window、保留窗口及构建边界。

若任一前置证据缺失，**不得**创建 C 迁移、写入生产数据库、切换生产 pointer、增加依赖或修改部署配置；可以继续完善本地测试夹具和本计划引用的接口草图，但不得把草图伪装成完成能力。

## 1. 目标、边界与不变量

### 1.1 目标

把现有分离的 SSG、per-Gene static task、搜索/下载资源和 Nginx 静态入口收束为一个由同一 `publication_release_id`、`generation` 和冻结输入驱动的确定性发布链：

```text
approved dataset/content revisions + registered immutable inputs
        ↓ Freeze
FrozenInputSnapshot + immutable revision snapshots
        ↓ Build (Worker/SSG)
registered artifacts → canonical manifest → ready marker
        ↓ common validation + capability profiles + classified smoke
publication approval + deployment approval
        ↓
Prepare DB → External pointer CAS → Finalize DB
        ↓
active revision-aware Nginx/static routes
```

### 1.2 必须保持的三个历史

C 不得把不同事实压成一个 `status` 或一个 `Release`：

1. **Dataset approval history**：由 A1/B 提供，记录数据候选、校验、ontology/许可、接受/拒绝及输入 digest。C 只读取已批准绑定，不覆盖它。
2. **Publication build/approval history**：记录 freeze、queue、build、validation、`artifact_ready`、publication review、approve/reject/expire，绑定不可变 `final_manifest_digest`。C 的 Worker 和 validator 只能追加事件。
3. **Deployment-attempt history**：记录每一次 promotion、CAS observation、verifying、smoke 分类、失败、补偿、rollback、unknown 和人工 resolution。回滚是指向旧 verified manifest 的新 attempt，不修改旧 build、approval 或 deployment event。

`rl_audit_ledger`/`rl_audit_outbox` 是横切证据，不替代上述三条业务历史；`rl_task_dispatch_outbox` 只表达待执行任务，不制造业务成功事实。

### 1.3 C 的明确非范围

- 不实现 D 的 Internal Search/External Search 分离、签名 cursor、Worker/API/static-directory 消费 UX；C 只生成并验证其所需的公开 search artifacts 和 manifest contract。
- 不实现 E 的 Admin 发布中心、scope ledger、ontology UI、provenance panel、JBrowse launch UX 或管理工作区；C 只提供后端可验证的状态、证据和 API/client schema seam。
- 不替换现有 Gene/Transcript 主键，不重写 ClickHouse，不引入 Elasticsearch/OpenSearch/graph database，不升级 Node/Vite/FastAPI/PostgreSQL/Redis，不拆分 FastAPI 服务。
- 不把 Celery/Redis 回调、对象存储通知或 Nginx reload 当作 publication commit；commit 由经过 fencing 的 external pointer CAS 与 Finalize evidence 共同决定。

## 2. 实际基线与缺陷基线（先写测试，再修复）

### 2.1 已读取并纳入实施边界的文件

| 文件 | 现状/复用点 | C 必须修正或封装的边界 |
|---|---|---|
| `apps/api/app/models/content.py`：`Release`、`StaticPage`、`ContentVersion`、`DownloadFile` | 旧 `Release` 混合数据/内容语义；`ContentVersion` 可作为 revision 输入来源；`DownloadFile.file_url` 可含任意 URL | 不把旧 `Release.id` 当 `publication_release_id`；冻结后只引用 immutable revision snapshot；下载地址转为 registered artifact ID/manifest entry |
| `apps/api/app/api/v1/releases.py`：`list_releases`、`get_release` | 只读旧 `Release`，按 `published_at` 排序 | C 的发布 API 不复用该路由作为 pointer truth；增加独立 publication contract 后再兼容映射 |
| `apps/api/app/api/v1/admin_content.py`：`create_page`、`update_page`、`_get_current_version` | 更新 page 行并新增版本，尚未生成 publication freeze | C 只读取 A1/B 已批准且在 freeze transaction 中复制的 revision snapshot；不能读取冻结后变化的 live row |
| `apps/api/app/api/v1/admin_static.py`：`trigger_build` | 写 `ImportTask` 后直接 `send_task`；异常被吞掉；任务名为 `soymutdb_worker.tasks.static.build_static_pages` | 先以 contract test 锁定错误，再改成事务内 task outbox + commit 后 relay；不让 queued 状态伪装为已投递 |
| `apps/worker/src/soymutdb_worker/tasks/static_pages.py`：`build_static_pages` | 注册名是 `soymutdb_worker.tasks.static_pages.build_static_pages`；读取 live Gene/Expression/Homolog；直接写 cache/S3 | 保留 legacy adapter 供旧任务回归；新 `rl_build_publication` 只能读取 FrozenInputSnapshot，写 immutable generation prefix，幂等键绑定 build/generation |
| `apps/worker/src/soymutdb_worker/main.py`：`celery_app`、`include`、`task_routes` | 已加载 `static_pages`，存在队列命名/注册漂移风险；`ingest`/`ingestion`、`stats` 等历史缺陷需核对 | 新任务注册名、队列、payload schema 和 outbox relay 必须由 contract test 覆盖；不依赖 autodiscovery 猜测 |
| `apps/api/app/utils/s3.py`：`get_s3_client`、`file_exists`、`get_file_size`、`stream_file`、`list_objects` | 普通 S3 helper，异常宽泛；无 immutable put、HEAD digest、ready marker、CAS/fencing | 由 provider adapter 包装，明确 provider capability、错误语义和 fake CAS；不把 helper 的成功返回当 publication proof |
| `apps/worker/src/soymutdb_worker/utils/s3.py`：`upload_file`、`upload_large_file`、`list_objects` | 可上传/列举，但可覆盖、无注册表/manifest membership | 新 builder 禁止直接调用任意 upload helper；必须先 register artifact、使用 immutable key 并完成 hash/size/type validation |
| `apps/web/scripts/ssg-build.ts`：`build`、`resolvePageLayout`、`resolveWidgetHtml` | API 不可用时使用 fallback；无 publication identity、冻结时间、manifest、输出 hash | 新 `rl_build_ssg` 接收 FrozenInputSnapshot/registered layout revision；API/fallback 均必须是已冻结输入；禁止 silent latest/fallback 跨 release |
| `apps/web/src/workers/search.worker.ts`：`filterData`、`sortData` | 当前把任意数组传入 Worker，既非 manifest-backed index 也非授权层 | C 只生成公开索引和 SearchManifest；D 才改消费者。C 的 schema scan 必须覆盖 serialized index/document/facet 字段 |
| `infra/nginx/conf.d/default.conf`：`/data/`、`/browser/`、catch-all `/` | `/data/` 已有 Range/CORS；无 revision-aware publication routes/ready guard | 增加版本化 immutable route 与 current-pointer/ready 读取策略；能力按 profile 检查，不把 Range/CORS 施加给所有 artifact |
| `apps/api/tests/test_s3_utils.py`、`tests/e2e/homepage.spec.ts` | 有普通 S3 mock 和当前首页 smoke | 增加 provider/fake CAS、artifact/manifest/smoke 分类测试；E2E 绑定指定 `publication_release_id`，不只验证默认首页 |

### 2.2 任务/队列缺陷 baseline

在任何实现前新增/运行 `apps/worker/tests/test_task_contract.py` 或 A0 确认后的等价路径，固定以下预期：

```python
# 为什么：Celery task name 是跨进程协议；拼写错误时“已入队”不能成为成功事实。
assert rl_task_registry["publication.build"] == (
    "soymutdb_worker.tasks.publication.build_publication"
)
assert rl_task_registry["static.legacy"] == (
    "soymutdb_worker.tasks.static_pages.build_static_pages"
)
assert rl_task_route("publication.build") == "publication"
assert rl_task_route("static.legacy") == "stats"
```

测试还必须显式发现/记录：

- `admin_static.py` 当前发送 `soymutdb_worker.tasks.static.build_static_pages`，而注册实现为 `soymutdb_worker.tasks.static_pages.build_static_pages`；异常被吞掉，任务可能永久 `queued`。
- `main.py` 的现有模块/队列必须与 A0 盘点的历史名称逐项对齐；`ingest`/`ingestion`、`stats` 无对应 task 等缺陷必须在 contract report 中分类，不能由 C 猜测修复。
- `BackgroundTasks`、Redis keyspace notification、Celery result backend 都不构成可靠 outbox/发布事实。

**Baseline 预期输出：** 在未修复代码上测试应明确失败并指出注册名 mismatch；修复 contract seam 后，registry、route、payload schema 测试通过，且 `send_task` 失败只产生 dispatch failure/audit event，不产生 build success。

## 3. 目标文件布局与命名约束

具体物理表名、迁移 revision 和模块目录必须先服从 A0 reconciliation；以下是实施时的最小建议边界，不得绕过实际 schema：

```text
apps/api/app/publication/
  contracts.py              # FrozenInputSnapshot、ArtifactRef、PublicationManifest、SmokeResult
  models.py                 # 仅在 A0 确认物理模型后增加 rl_* model
  repositories.py           # 短事务查询/追加，不持有外部 I/O
  services.py               # freeze、prepare、finalize、reconcile 领域命令
  projection_schema.py      # 版本化公开字段 allowlist
  artifact_validation.py    # common validation + capability profiles
  provider.py               # protocol、S3/MinIO adapter、fake provider/CAS
  saga.py                   # Prepare → CAS → Finalize orchestration
  smoke.py                  # deterministic/transient/unknown classifier
  outbox.py                 # task relay payload/lease/idempotency
apps/api/tests/
  test_publication_contracts.py
  test_public_projection_schema.py
  test_artifact_validation.py
  test_publication_provider.py
  test_publication_saga.py
  test_publication_smoke.py
  test_publication_reconcile.py
apps/worker/src/soymutdb_worker/tasks/publication.py
apps/worker/src/soymutdb_worker/tasks/publication_reconcile.py
apps/worker/tests/test_publication_tasks.py
apps/web/scripts/ssg-build.ts
apps/web/scripts/publication-contract.ts
apps/web/tests/ssg-build.test.ts
infra/nginx/conf.d/default.conf
tests/e2e/publication-smoke.spec.ts
```

新增第一方业务函数、变量、类型、服务和测试夹具使用 `rl_` 前缀；框架回调、Celery task name、配置键、迁移文件名和既有公共接口遵循框架/兼容协议。所有非显然的安全、冻结、版本转换、CAS 或性能规则加短中文 why-comment。

## 4. C0：冻结 C 的输入契约与 revision snapshot

### 4.1 先写的测试

文件：`apps/api/tests/test_publication_contracts.py`。

覆盖：

1. 同一组 dataset/content/navigation/module/artifact input、同一 `frozen_at`、locale、timezone、排序规则、toolchain/lockfile digest 生成相同 `FrozenInputSnapshot.digest`。
2. 任一 live `ContentVersion`、dataset object version、ontology closure、license decision 或 registered artifact 在 freeze 后变化，不改变已保存 snapshot；新变化只能生成新 `generation`。
3. `dataset_release_id` 与 `publication_release_id` 不可互换；旧 `Release.id` 只能产生 `legacy_dataset_mapping`，没有完整内容 revision/build/manifest/approval/deployment evidence 时为 `unresolved`。
4. 不允许 `latest`、未批准 draft、任意 URL/path、secret、shell、upload session 或未注册 object ID 进入 frozen input。
5. revision snapshot 的 canonical JSON 使用固定字段顺序、UTF-8、UTC ISO-8601、固定 decimal/NULL/排序规则，并拒绝 NaN/Infinity。

代表性契约：

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class rl_frozen_input_snapshot:
    publication_release_id: str
    generation: int
    dataset_release_id: str
    dataset_manifest_digest: str
    content_revision_ids: tuple[str, ...]
    navigation_revision_id: str
    module_revision_ids: tuple[str, ...]
    ontology_release_set_digest: str
    license_decision_digest: str
    registered_input_artifact_ids: tuple[str, ...]
    code_revision: str
    lockfile_digest: str
    toolchain_digest: str
    locale: str
    timezone: str
    frozen_at: str
    sort_schema_version: str
    random_seed: str | None
    digest: str

    def assert_publishable(self) -> None:
        # 为什么：发布输入必须可重建；“当前最新”会使同一 publication 不可复现。
        if not self.publication_release_id or not self.dataset_release_id:
            raise ValueError("publication and dataset identities are required")
        if self.random_seed is None and "random" in self.sort_schema_version:
            raise ValueError("randomized build requires a frozen seed")
```

### 4.2 实现顺序

1. 在 A0 确认的事务表/兼容 adapter 上追加 immutable revision snapshot 记录；冻结时在一个短 PostgreSQL transaction 中读取并锁定输入版本，写入 `rl_publication_build_history` 的 `freeze` event 和 `rl_task_dispatch_outbox` 的 build command。
2. 内容不得只保存 `StaticPage` 当前列；复制 `ContentVersion`、navigation/module config 的 canonical snapshot，并绑定 source revision/digest。冻结后禁止 ORM 普通 update 改 digest。
3. `rl_publication_release_id` 必须是独立 identity；旧 `Release` 仅通过 evidence-bearing mapping 进入输入，不改变历史含义。
4. `frozen_at` 是 manifest/build input，不直接调用 wall clock 生成页面文本；压缩器、模板、排序、locale、timezone、随机种子必须进入 digest。

### 4.3 窄门

```bash
cd /mnt/data02/T25ronglin/code/web
python -m pytest apps/api/tests/test_publication_contracts.py -q
```

**预期：** 新增契约测试全绿；输出 `N passed`，并可在同一输入上两次打印相同 snapshot digest。若 A0 schema 尚未确认，测试只能使用 fake repository，不得创建未经批准的 production migration。

## 5. C1：artifact registry、canonical manifest、ready marker 与公开投影边界

### 5.1 Artifact registry

先写 `apps/api/tests/test_artifact_validation.py`，再实现 `apps/api/app/publication/artifact_validation.py`。每个 artifact 必须登记：

```json
{
  "artifact_id": "rl_artifact_01J...",
  "publication_release_id": "pub_2026_07_19_001",
  "generation": 7,
  "kind": "html|json|search_document|search_index|download|jbrowse_config|track|sidecar|sitemap|sbom",
  "immutable_object_key": "publications/pub_2026_07_19_001/generation-000007/<sha256>/genes/Glyma...html.gz",
  "sha256": "64-lower-hex",
  "size_bytes": 12345,
  "content_type": "text/html; charset=utf-8",
  "content_encoding": "gzip",
  "scope": {"species": "glycine-max", "assembly": "Gmax_508_v4", "dataset_release_id": "ds_..."},
  "projection_schema": "rl_public_projection_schema.v1",
  "capability_profile": "static-html.v1",
  "consumption_declaration_digest": "sha256:...",
  "capability_resolver_schema_version": "rl_capability_resolver.v1",
  "resolved_capabilities": {"requires_range": false, "requires_cors": false, "requires_sidecars": false, "requires_resume": false},
  "source_revision_digest": "64-lower-hex",
  "registered_at": "2026-07-19T00:00:00Z"
}
```

测试必须阻断：mutable path、重复 `(publication,generation,path)`、digest/size/type mismatch、未注册 ID、manifest 外对象、internal object ID/bucket/key/URI、presigned URL、upload session、secret/token、unpublished diagnostic/approval identity、active manifest 引用对象不可读。

### 5.2 canonical manifest 与 ready marker

Manifest 是最后写入的 immutable artifact；它只引用已注册、已验证、已完成的 artifact ID，不能包含“待生成”条目。代表性 manifest：

```json
{
  "manifest_schema_version": "rl_publication_manifest.v1",
  "publication_release_id": "pub_2026_07_19_001",
  "generation": 7,
  "dataset_release_id": "ds_soybean_2026_01",
  "input_snapshot_digest": "sha256:...",
  "content_revision_digest": "sha256:...",
  "ontology_release_set_digest": "sha256:...",
  "projection_schema_versions": {
    "html": "rl_public_projection_schema.v1",
    "json": "rl_public_projection_schema.v1",
    "search": "rl_public_projection_schema.v1",
    "download": "rl_public_projection_schema.v1",
    "jbrowse": "rl_public_projection_schema.v1"
  },
  "artifacts": [
    {"artifact_id": "rl_artifact_html_index", "sha256": "...", "size_bytes": 1000},
    {"artifact_id": "rl_artifact_search_manifest", "sha256": "...", "size_bytes": 2000}
  ],
  "previous_verified_manifest_digest": "sha256:...",
  "build_toolchain_digest": "sha256:...",
  "lockfile_digest": "sha256:...",
  "frozen_build_time": "2026-07-19T00:00:00Z",
  "sbom_artifact_id": "rl_artifact_sbom",
  "license_inventory_artifact_id": "rl_artifact_license",
  "manifest_digest": "sha256:..."
}
```

`ready marker` 必须是独立、不可变、带 manifest digest/generation/fencing/attempt 的小对象；写入顺序固定为：所有 artifact → HEAD/hash/size/type/permission/route validation → canonical manifest → ready marker。ready marker 不是 pointer，不代表 active。

### 5.3 `rl_public_projection_schema` allowlist 与 defense-in-depth scan

文件：`apps/api/app/publication/projection_schema.py`、`apps/api/tests/test_public_projection_schema.py`。

每一种公开 artifact class 必须绑定版本化 allowlist，allowlist 是 PRIMARY security boundary；敏感字段扫描只是 defense-in-depth。代表性配置：

```python
rl_public_projection_schema_v1 = {
    "html": {"title", "summary", "canonical_url", "scope_ledger", "citation"},
    "json": {"public_stable_id", "object_type", "scope_ledger", "provenance", "data"},
    "search_document": {"public_stable_id", "object_type", "title", "aliases", "summary", "canonical_url", "scope_ledger"},
    "search_facet": {"facet_name", "public_value", "count"},
    "search_index": {"schema_version", "manifest_digest", "documents", "config_hash"},
    "download_catalog": {"name", "description", "public_artifact_digest", "canonical_url", "license", "size_bytes"},
    "jbrowse_config": {"assembly_name", "tracks", "scope_ledger", "manifest_digest", "config_version"},
    "track_metadata": {"label", "format", "public_artifact_digest", "index_sidecars", "scope_ledger"},
    "provenance": {"public_source", "public_version", "license", "citation", "public_artifact_digest", "canonical_url"}
}

rl_forbidden_public_keys = {
    "internal_id", "object_id", "bucket", "key", "internal_uri", "presigned_url",
    "upload_session_id", "secret", "token", "approval_identity", "diagnostic",
    "unpublished_source", "restricted_policy_detail"
}
```

测试用真实 representative payload 覆盖 nested object、array、query string、compressed JSON/HTML metadata 和 serialized search index；必须证明：

- allowlist 拒绝未知字段，即使敏感扫描没有命中；
- scan 发现 forbidden key、token-like query、internal URI、bucket/key、approval identity 时阻断 `artifact_ready`；
- scope ledger 必须有 `scope_type` 与 applicability；不适用 level 显式为 `unavailable`/`not-applicable`，不默认填 assembly/dataset；
- provenance/citation 只能输出 public stable source/version/license/citation、public digest、canonical URL；admin evidence 不因 expanded/export 公开；
- ontology path 只来自 published release-set 预计算 summary/bounded ancestor，不递归实时查询、不公开内部 term/diagnostic。

### 5.4 窄门

```bash
python -m pytest apps/api/tests/test_artifact_validation.py apps/api/tests/test_public_projection_schema.py -q
```

**预期：** allowlist、forbidden key、manifest membership、ready marker 顺序和 digest mismatch 测试全绿；测试报告明确显示 `artifact_ready` 在任一 scan/validation failure 时不产生。

## 6. C2：common artifact validation 与 conditional capability profiles

### 6.1 Common validation

文件：`apps/api/app/publication/artifact_validation.py`、`apps/api/tests/test_artifact_validation.py`。

所有 artifact 都执行：

1. registered artifact ID 与 immutable path；
2. content-type/content-encoding/长度；
3. SHA-256 和 manifest membership；
4. object permission/visibility 与 public route；
5. HEAD/read-after-write/ready marker/manifest digest；
6. projection schema allowlist 与 defense-in-depth scan；
7. scope、publication/dataset identity、generation 一致；
8. route URL 不含 secret/presigned/temporary token；
9. 失败制品留在隔离 prefix，不覆盖旧 active 或旧 verified prefix。

### 6.2 Consumption declaration → capability resolver

Capability profile 不预先把 `requires_range`、`requires_cors` 或 `requires_sidecars` 固定为无条件布尔值。发布 manifest 只保存不可变的 artifact/profile 身份和经过服务端校验的 consumption declaration；resolver 根据 declaration、artifact metadata 和 B-pre-ADR 已配置的 size threshold 计算本次消费实际需要的能力。为什么：能力是消费方式与资源格式的函数，不应把 JBrowse 或某一种下载方式的条件错误施加给所有制品。

客户端不得提交任意 capability flags、origin、sidecar URL、bucket/key 或 provider 参数。声明只能由服务端根据已注册的 adapter、format、route/origin policy、download mode 和 B-pre-ADR 配置生成；manifest 中冻结 declaration digest、resolver/schema version 和 resolved capability result，构建完成后不可改写。

```python
@dataclass(frozen=True)
class rl_jbrowse_consumption:
    adapter_requires_random_access: bool
    format_requires_sidecar: bool
    browser_cross_origin: bool

@dataclass(frozen=True)
class rl_download_consumption:
    requires_random_access: bool
    requires_resume: bool
    browser_cross_origin: bool
    format_requires_sidecar: bool
    size_bytes: int
    b_pre_adr_size_threshold_bytes: int

@dataclass(frozen=True)
class rl_resolved_capability_profile:
    name: str
    requires_range: bool
    requires_cors: bool
    requires_sidecars: bool
    requires_resume: bool
    declaration_digest: str
    resolver_schema_version: str

def rl_resolve_jbrowse_capabilities(
    declaration: rl_jbrowse_consumption,
) -> rl_resolved_capability_profile:
    # 为什么：JBrowse 只有随机访问、格式 sidecar 或跨 origin 消费确有需要时才加检查。
    return rl_resolved_capability_profile(
        name="jbrowse-consumption.v1",
        requires_range=declaration.adapter_requires_random_access,
        requires_cors=declaration.browser_cross_origin,
        requires_sidecars=declaration.format_requires_sidecar,
        requires_resume=False,
        declaration_digest=rl_digest(declaration),
        resolver_schema_version="rl_capability_resolver.v1",
    )

def rl_resolve_download_capabilities(
    declaration: rl_download_consumption,
) -> rl_resolved_capability_profile:
    rl_large_download = (
        declaration.size_bytes >= declaration.b_pre_adr_size_threshold_bytes
    )
    # 为什么：大文件阈值只来自 B-pre-ADR 配置，不能由请求方临时扩大能力要求。
    return rl_resolved_capability_profile(
        name="download-consumption.v1",
        requires_range=(
            declaration.requires_random_access
            or declaration.requires_resume
            or rl_large_download
        ),
        requires_cors=declaration.browser_cross_origin,
        requires_sidecars=declaration.format_requires_sidecar,
        requires_resume=declaration.requires_resume,
        declaration_digest=rl_digest(declaration),
        resolver_schema_version="rl_capability_resolver.v1",
    )
```

因此，JBrowse 的 `Range` 需求只由 `adapter_requires_random_access` 决定，sidecar 需求只由 `format_requires_sidecar` 决定，CORS 需求只由 `browser_cross_origin` 决定；下载的 `Range` 需求由 `requires_random_access`、`requires_resume` 或 B-pre-ADR size threshold 共同决定，CORS 由 `browser_cross_origin` 决定，sidecar 由 `format_requires_sidecar` 决定。顺序读取、同源、无 sidecar 的普通小下载不会被强制升级为随机访问 profile；跨 origin 只增加 CORS 检查，不自动增加 Range/sidecar。

### 6.3 TDD 与窄门

`apps/api/tests/test_artifact_validation.py` 必须测试 resolver，而不是只测试 profile 名称：

| 消费 | declaration | 预期 resolved capabilities |
|---|---|---|
| JBrowse same-origin sequential, no sidecar | `adapter_requires_random_access=False`, `format_requires_sidecar=False`, `browser_cross_origin=False` | `range=False`, `cors=False`, `sidecars=False`；缺这些能力仍可通过 common validation |
| JBrowse random-access same-origin, sidecar needed | `True`, `True`, `False` | `range=True`, `cors=False`, `sidecars=True`；缺 Range 或 sidecar 失败，缺 CORS 不失败 |
| JBrowse random-access cross-origin, no sidecar | `True`, `False`, `True` | `range=True`, `cors=True`, `sidecars=False`；缺 Range/CORS 失败，缺 sidecar 不失败 |
| Download sequential same-origin, small, no sidecar | `False`, `False`, `False`, `False`, `size < threshold` | `range=False`, `cors=False`, `sidecars=False`, `resume=False` |
| Download random cross-origin, small, no sidecar | `True`, `False`, `True`, `False`, `size < threshold` | `range=True`, `cors=True`, `sidecars=False`, `resume=False` |
| Download sequential same-origin, large, no sidecar | `False`, `False`, `False`, `False`, `size >= threshold` | `range=True`, `cors=False`, `sidecars=False`, `resume=False`；阈值只来自 B-pre-ADR |
| Download sequential cross-origin, sidecar needed | `False`, `False`, `True`, `True`, `size < threshold` | `range=False`, `cors=True`, `sidecars=True`, `resume=False` |
| Download resumable same-origin, sidecar needed | `False`, `True`, `False`, `True`, `size < threshold` | `range=True`, `cors=False`, `sidecars=True`, `resume=True` |

每个正例都必须证明 common validation 仍始终执行；每个负例分别注入缺 Range、错误 CORS、缺 sidecar、sidecar digest mismatch，并证明只有 resolver 判定为必需的能力才阻断 `artifact_ready`。测试还必须拒绝客户端伪造 declaration、任意 threshold、origin、sidecar path 或 profile override，并验证 manifest 中 declaration/resolved result/resolver version 不可变。C 只验收构建 artifact 的 resolver、能力证据和错误分类；D 才消费这些 capability errors 并实现 JBrowse/download 的用户 fallback UX。

```bash
python -m pytest apps/api/tests/test_artifact_validation.py -q
```

**预期：** common validation 与 resolver 的同源/跨源、sidecar-needed/not-needed、sequential/random read 正/负例全绿；测试不能通过把所有 artifact 强制声明为 Range/CORS/sidecar 或 JBrowse profile，也不能通过客户端输入任意 capability declaration。

## 7. C3：S3-compatible protocol、provider adapter 与 fake CAS

### 7.1 Protocol

文件：`apps/api/app/publication/provider.py`、`apps/worker/src/soymutdb_worker/utils/s3.py` 的新 adapter seam、`apps/api/tests/test_publication_provider.py`。

定义最小 provider protocol：

```python
class rl_object_store_protocol(Protocol):
    def put_immutable(self, object_key: str, body: bytes, *, sha256: str, content_type: str) -> None: ...
    def head_verified(self, object_key: str, *, sha256: str, size_bytes: int) -> dict[str, object]: ...
    def get_json(self, object_key: str) -> dict[str, object]: ...
    def put_ready_marker(self, object_key: str, marker: dict[str, object]) -> None: ...
    def read_public_pointer(self, pointer_key: str) -> "rl_public_pointer | None": ...
    def compare_and_swap_pointer(self, pointer_key: str, expected: "rl_pointer_version | None", replacement: "rl_public_pointer") -> "rl_cas_result": ...
    def observe_route(self, route: str) -> "rl_route_observation": ...
```

adapter 要明确记录 provider capability：conditional write/CAS、read-after-write、versioning/Object Lock、rename 语义、HEAD/hash 语义、Range/CORS、cache TTL/purge 和异常是否可判定。Object Lock/versioning 只提供 retention/版本保护，不替代应用层 manifest/CAS/fencing。

### 7.2 Fake provider 必须模拟的故障

`rl_fake_object_store` 用内存或临时目录实现，并可注入：

- PUT 成功/超时/写入后抛错；
- HEAD stale/not-found/digest mismatch；
- ready marker 缺失/错误 digest；
- pointer CAS expected version mismatch；
- CAS 已成功但调用方收到 timeout；
- pointer 成功但 CDN/route 观察暂时旧、永久错误或未知；
- fencing token 过期、旧 token 试图覆盖新 pointer；
- manifest 已登记但对象不可读、对象已写但未注册。

代表性 CAS：

```python
@dataclass(frozen=True)
class rl_public_pointer:
    manifest_digest: str
    generation: int
    fencing_token: int
    deployment_attempt_id: str

def rl_compare_and_swap_pointer(
    current: rl_public_pointer | None,
    expected: rl_public_pointer | None,
    replacement: rl_public_pointer,
) -> bool:
    # 为什么：只有 expected version + fencing token 同时匹配，旧 worker 才不能覆盖新发布。
    if current != expected:
        return False
    if current and replacement.fencing_token <= current.fencing_token:
        return False
    return True
```

### 7.3 窄门

```bash
python -m pytest apps/api/tests/test_publication_provider.py apps/api/tests/test_s3_utils.py -q
```

**预期：** fake/provider contract 在 MinIO-compatible fake 与纯内存 fake 上均通过；明确输出 CAS mismatch、stale read、timeout-after-success、fencing rejection 的可判定分类。不得连接真实生产 bucket。

## 8. C4：task outbox relay、构建任务幂等与 canonical manifest 生成

### 8.1 Outbox 事务契约

文件：A1 已有 outbox model/service 的实际路径；C 新增 `apps/api/app/publication/outbox.py`、`apps/api/tests/test_publication_outbox.py`、Worker `tasks/publication.py`。

冻结命令在同一 DB transaction 追加：

```json
{
  "outbox_id": "rl_task_outbox_...",
  "task_kind": "publication.build",
  "task_name": "soymutdb_worker.tasks.publication.build_publication",
  "payload": {
    "publication_release_id": "pub_...",
    "generation": 7,
    "input_snapshot_digest": "sha256:...",
    "idempotency_key": "publication-build/pub_.../generation-7/input-..."
  },
  "payload_digest": "sha256:...",
  "attempt": 0,
  "lease_owner": null,
  "status": "pending"
}
```

relay 只在 commit 后 claim/lease outbox、调用 `send_task`、记录 Celery ID/dispatch result；发送失败追加 failure audit 并按 lease 重试，不改变 publication approval/build success。relay 本身可重复，必须以 `idempotency_key` 去重。

测试矩阵：transaction rollback 不发送任务；commit 后发送一次；broker timeout 可重试；同一 outbox 重跑不产生不同 payload；task result 丢失不制造 success；发送错误不会把 task 置为 completed。

### 8.2 `rl_build_publication`

文件：`apps/worker/src/soymutdb_worker/tasks/publication.py`、`apps/worker/tests/test_publication_tasks.py`。

任务只接收 `publication_release_id`、`generation`、`input_snapshot_digest`、`idempotency_key`，从 PostgreSQL 读取冻结 snapshot 和 registered IDs；禁止接受任意 `file_path`、shell、bucket/key 或未登记 URL。它执行：

1. claim 同一 build idempotency key；
2. 使用 frozen time/sort/locale/toolchain 构建 Web SSG、detail JSON/HTML、sitemap、search/download/JBrowse artifacts；
3. 每个输出先 hash、register、immutable PUT、HEAD verify；
4. 运行 projection/schema/scan/common validation，并由服务端 resolver 根据已登记 consumption declaration 计算并冻结 capability evidence；
5. 生成 canonical manifest（manifest-last），写 ready marker；
6. 追加 `artifact_ready` 或 failure event；
7. 绝不写 active pointer。

现有 `build_static_pages` 保留为 legacy task，先修正注册名 contract；不得让 legacy live-DB builder 伪装成 C publication builder。

### 8.3 SSG 接缝

在 `apps/web/scripts/ssg-build.ts` 中提取 `rl_build_ssg(snapshot, layoutSnapshot, outputDir)`，保留 `build` CLI 作为兼容壳。禁止在 C 版本中使用当前 `API unavailable → FALLBACK_PAGES` 的隐式跨版本行为；offline fallback 必须来自 snapshot 内已登记的 fallback revision，并把其 digest 写入 manifest。

代表性输入：

```ts
export type rlFrozenSsgInput = {
  publicationReleaseId: string;
  generation: number;
  inputSnapshotDigest: string;
  frozenBuildTime: string;
  locale: string;
  timezone: string;
  sortSchemaVersion: string;
  pageRevisionIds: readonly string[];
  registeredOutputPrefix: string;
  capabilityResolverSchemaVersion: "rl_capability_resolver.v1";
};

export async function rl_build_ssg(input: rlFrozenSsgInput): Promise<rlSsgBuildResult> {
  // 为什么：SSG 不得在构建中重新读取 live API，否则页面和索引会跨快照混合。
  const layouts = await rl_loadFrozenLayouts(input.pageRevisionIds);
  return rl_renderAndHashLayouts(layouts, input.frozenBuildTime, input.registeredOutputPrefix);
}
```

### 8.4 窄门

```bash
python -m pytest apps/api/tests/test_publication_outbox.py apps/worker/tests/test_publication_tasks.py -q
pnpm --filter @soymutdb/web test -- ssg-build
```

**预期：** outbox commit/rollback/relay/duplicate 测试通过；同一 frozen fixture 两次生成相同 artifact digest 和 manifest digest；live DB 在构建中修改不会改变输出；任务重试不会新增不同 generation。

## 9. C5：Prepare DB → External CAS → Finalize DB promotion saga

### 9.1 Prepare DB transaction

文件：`apps/api/app/publication/saga.py`、`apps/api/tests/test_publication_saga.py`。

Prepare 在短 DB transaction 内：

1. 校验 publication approval 绑定的 final manifest digest、A1 deployment approval、environment、policy/quorum/expiry、expected pointer revision；
2. 校验 manifest、ready marker、artifact set、projection validation evidence；
3. 获取/递增 environment fencing token；
4. 创建 immutable `deployment_attempt` 与 pointer intent，状态 `promoting`；
5. 锁住环境的后续 promotion；
6. commit 后才进行外部 I/O。

Prepare 不生成/拼装/重写 manifest，不在 DB transaction 内上传对象，不依赖 Redis lock 作为 correctness。

### 9.2 External CAS

pointer payload 必须同时含：

```json
{
  "manifest_digest": "sha256:...",
  "generation": 7,
  "fencing_token": 42,
  "deployment_attempt_id": "rl_deploy_...",
  "ready_marker_digest": "sha256:..."
}
```

仅同一 expected pointer/version 且 replacement fencing token 更高时 CAS 成功。CAS 返回 success、rejected、provider-error 或 unknown；Celery return、HTTP 200、Nginx reload 或 cache purge 不单独构成成功。

### 9.3 Finalize DB transaction

Finalize 重新读取 PostgreSQL ledger、public pointer、ready marker、route/CDN observation，追加 observation。只有：

- pointer digest/generation/fencing/attempt 完全匹配；
- ready marker 和 manifest digest 一致；
- classified smoke 非 failure；
- provider/CDN observation 足以证明版本一致；

才从 `verifying` 转 `active`。否则进入 `failed` 或 `unknown`。`active` 是 Finalize 结果，不是 CAS 回调结果。

### 9.4 Saga 状态与不可变规则

```text
prepared → promoting → verifying → active
                       ↘ failed
                       ↘ unknown
active → compensation_attempt → verifying → active(prior manifest)
```

已 proven CAS 前失败：旧 active pointer 保持不变，可按同一 binding 重试。已 proven CAS 后 smoke 失败：必须记录 transient exposure，创建新的 fenced compensation attempt，目标为 **CAS-time prior verified manifest**，而不是“当前 DB active”猜测；补偿本身仍走 Prepare → CAS → Finalize。pointer/ready/CDN 不确定：`unknown`、冻结后续 promotion、人工 resolution，禁止盲目反向切换。

### 9.5 TDD 矩阵

至少覆盖：

| 场景 | 预期状态/事实 |
|---|---|
| Prepare approval/manifest mismatch | DB rollback；旧 pointer 不变；failure audit |
| CAS expected version mismatch | `failed`；不得更新 active；可同 binding 重试 |
| CAS provider timeout 且未证明成功 | 旧 pointer 保持；`failed/unknown` 按证据；冻结规则明确 |
| CAS 成功 + deterministic smoke failure | `verifying` 后新 fenced compensation attempt，目标为 CAS-time prior verified |
| CAS 成功 + transient CDN timeout | `verifying`/`unknown` 或按策略补偿；记录 cache window，不伪造旧 pointer 未变化 |
| CAS 成功但 DB commit 失败 | reconcile pointer/ready/attempt；可证明同 intent 才幂等 finalize，否则 `unknown` |
| stale worker old fencing token | CAS rejected；旧 worker 不得覆盖新 pointer |
| duplicate finalize/retry | 同 binding 幂等；不创建不同 payload success |
| unknown pointer/ready observation | 冻结后续 promotion；人工 resolution required |

```bash
python -m pytest apps/api/tests/test_publication_saga.py -q
```

**预期：** 每个 branch 都能从 deployment-attempt history 重建；测试断言三条历史均 append-only，rollback 不修改旧事件。

## 10. C6：smoke 分类、补偿、divergence/orphan/retention/recovery

### 10.1 Deterministic / transient / unknown 分类

文件：`apps/api/app/publication/smoke.py`、`apps/api/tests/test_publication_smoke.py`。

```python
class rl_smoke_class(str, Enum):
    DETERMINISTIC_FAILURE = "deterministic_failure"
    TRANSIENT_FAILURE = "transient_failure"
    UNKNOWN = "unknown"
    PASS = "pass"

def rl_classify_smoke(observation: rl_smoke_observation) -> rl_smoke_result:
    if observation.manifest_digest_mismatch or observation.schema_violation:
        return rl_smoke_result(rl_smoke_class.DETERMINISTIC_FAILURE, "manifest_or_schema_mismatch")
    if observation.provider_timeout or observation.cdn_not_ready:
        return rl_smoke_result(rl_smoke_class.TRANSIENT_FAILURE, "provider_or_cache_window")
    if observation.pointer_unreadable or observation.commit_outcome_unknown:
        return rl_smoke_result(rl_smoke_class.UNKNOWN, "cross_store_state_unknown")
    return rl_smoke_result(rl_smoke_class.PASS, "verified")
```

分类必须先于 compensation：deterministic mismatch 通常直接进入 fenced compensation/failed；transient failure 记录 cache window 和 bounded retry/compensation policy；unknown 冻结 promotion 并需要人工 resolution。不得以“smoke 失败”一个字符串掩盖是否已经暴露新版本。

### 10.2 Divergence 与 orphan reconcile

文件：`apps/api/app/publication/reconcile.py`、`apps/api/tests/test_publication_reconcile.py`、Worker `tasks/publication_reconcile.py`。

reconciler 只按 registered artifact ID、manifest digest、generation、pointer intent、approval/audit/recovery/hold evidence 分类：

- object 已写但 manifest/pointer 未登记：候选 orphan，必须过 grace period；
- manifest 已登记但 object 不可读：integrity incident，不能清理，进入 failed/unknown/compensation；
- ready marker digest 不一致：deterministic failure；
- pointer 已切换但 DB finalize 缺失：同 fencing/attempt 可幂等补写；无法证明同 binding 则 unknown；
- active manifest 引用对象不可读：永不列为 cleanup candidate；
- 仍被 active、manifest、build、pointer intent、deployment、approval、audit、legal hold、recovery window 引用：不可清理。

清理前必须同时满足：无任何引用、无 legal hold、超过 reachability/recovery retention、超过 grace period、通过二次扫描，并追加 retention cleanup audit event。普通 retention manager 不能缩短高风险最短保留期；保留策略变化需重新认证/独立审批。

### 10.3 Recovery drill

在 A0/B 选定的 disposable provider 上演练：

1. 恢复 PostgreSQL control-plane ledger/attempts；
2. 恢复 object manifest、ready marker、public pointer version；
3. 重新 HEAD/hash 验证 active/previous verified artifacts；
4. 验证 Nginx/CDN route 读取同一 manifest digest；
5. 验证内部 search artifact 只来自该 manifest（D 的消费者验收另行进行）；
6. 记录 RPO、RTO、cache window、对象可达 retention、恢复证据 digest。

## 11. C7：revision-aware SSG、Nginx routes 与 classified smoke

### 11.1 版本化路径

文件：`apps/web/scripts/ssg-build.ts`、`infra/nginx/conf.d/default.conf`、必要时 `infra/nginx/nginx.conf`（仅在实际 wiring 需要时）。

所有公开资源使用 immutable path，例如：

```text
/publications/{publication_release_id}/generations/{generation}/manifest.json
/publications/{publication_release_id}/generations/{generation}/ready.json
/publications/{publication_release_id}/generations/{generation}/pages/index.html
/publications/{publication_release_id}/generations/{generation}/search/search-manifest.json
/publications/{publication_release_id}/generations/{generation}/downloads/{artifact_id}
/publications/{publication_release_id}/generations/{generation}/jbrowse/{artifact_id}
```

current pointer route 只能返回已验证的 versioned target/manifest digest；不得把 `/latest` 解释为构建时 live data。建议新增优先级高于 catch-all 的路由契约：

```nginx
# 为什么：public path 只代理已登记的 immutable generation，避免 catch-all 把未发布工作区暴露出去。
location ^~ /publications/ {
    proxy_pass http://web_frontend;
    add_header Cache-Control "public, max-age=31536000, immutable" always;
}

location = /publication-pointer.json {
    proxy_pass http://minio_backend/public-pointers/current.json;
    add_header Cache-Control "no-cache, max-age=0, must-revalidate" always;
    add_header ETag $upstream_http_etag always;
}

location ^~ /public-downloads/ {
    proxy_pass http://minio_backend/publications/;
    # Range/CORS 仅由 download capability profile 宣布，不向所有路径泛化。
}
```

实际 `proxy_pass`、bucket alias、CDN header 和 include 必须以 A0/部署 wiring 及 provider capability test 为准；本计划不允许直接覆盖生产 Nginx。

### 11.2 Classified smoke

文件：`tests/e2e/publication-smoke.spec.ts`。每次 smoke 读取指定环境变量 `RL_PUBLICATION_RELEASE_ID`、`RL_GENERATION`、`RL_MANIFEST_DIGEST`，禁止默认为 live/latest。检查：

- pointer、ready、manifest 三者 digest/generation/fencing/attempt 一致；
- index/page/detail/download/search artifact 的 public scope 一致；
- 缺 JS 时 HTML/canonical/citation/scope ledger 仍可读（D 的完整 fallback UX 不在 C 完成）；
- immutable path 不重定向到未发布路径；
- JBrowse/download 只检查服务端 resolver 从 immutable consumption declaration 解析出的能力；同源/跨源、sidecar-needed/not-needed、顺序/随机读取必须按声明结果分类；
- CDN/Nginx stale observation 按 deterministic/transient/unknown 输出，不把网络超时判成内容 mismatch。

代表性 shell：

```bash
RL_PUBLICATION_RELEASE_ID=pub_test_001 \
RL_GENERATION=7 \
RL_MANIFEST_DIGEST=sha256:... \
pnpm exec playwright test tests/e2e/publication-smoke.spec.ts --project=chromium
```

**预期：** 通过时输出 `publication smoke: PASS manifest=sha256:... generation=7`；确定性失败输出 `DETERMINISTIC_FAILURE` 并阻断 promotion；短暂 provider/CDN 失败输出 `TRANSIENT_FAILURE` 并进入策略化重试/补偿；无法证明 pointer/DB/ready 状态输出 `UNKNOWN` 并冻结后续 promotion。

## 12. C8：端到端 TDD 顺序、命令与证据包

### 12.1 严格执行顺序

1. **Gate C-pre：** A0/A1/B evidence presence check；没有证据只运行 fake contract tests，不改生产 schema/config。
2. **Red C0：** frozen snapshot/revision tests；记录旧 live-read/legacy Release 语义缺陷。
3. **Green C0：** snapshot contract/immutable revision adapter。
4. **Red/Green C1：** registry、manifest-last、ready marker、projection allowlist、scan。
5. **Red/Green C2：** common validation、consumption declaration resolver 与 capability evidence。
6. **Red/Green C3：** provider protocol、MinIO/S3 adapter seam、fake CAS/fencing。
7. **Red/Green C4：** task registry/outbox relay、idempotent Worker build、SSG frozen input。
8. **Red/Green C5：** Prepare/CAS/Finalize saga、three-history append-only、compensation/unknown。
9. **Red/Green C6：** smoke classification、reconcile/orphan/retention/recovery。
10. **Red/Green C7：** revision-aware routes、static artifact smoke；不进入 D/E UI。
11. **Gate C-final：** narrow commands、artifact evidence bundle、Oracle review；失败则回到对应 task，不扩大范围。

### 12.2 命令清单与预期输出

先确认工作区与 Python/Node 事实，不自行升级：

```bash
pwd
git status --short  # 当前目录不是已确认 Git repo 时，记录 not-a-git-repo，不初始化 Git
python --version
node --version
pnpm --version
```

**预期：** 记录实际版本与 A0 reconciliation 的差异；不得因差异执行 package upgrade。

API/Worker 目标测试：

```bash
python -m pytest \
  apps/api/tests/test_publication_contracts.py \
  apps/api/tests/test_public_projection_schema.py \
  apps/api/tests/test_artifact_validation.py \
  apps/api/tests/test_publication_provider.py \
  apps/api/tests/test_publication_outbox.py \
  apps/api/tests/test_publication_saga.py \
  apps/api/tests/test_publication_smoke.py \
  apps/api/tests/test_publication_reconcile.py -q
```

**预期：** 所有 C 单元/contract tests `passed`；failure branch 断言旧 pointer、三条 history、audit/outbox 事实，而不是只断言异常类型。

Worker 任务 contract：

```bash
python -m pytest apps/worker/tests/test_task_contract.py apps/worker/tests/test_publication_tasks.py -q
```

**预期：** canonical Celery names、queue、JSON payload、idempotency、lease/retry 和 legacy static task mapping 全部通过。

TypeScript SSG/build seam：

```bash
pnpm --filter @soymutdb/web typecheck
pnpm --filter @soymutdb/web test -- ssg-build
pnpm --filter @soymutdb/web build
```

**预期：** `rl_build_ssg` 输入/输出类型通过；同一 fixture 的 artifact/manifest digest 可重复；build 不读取未冻结 live API。

Nginx 配置语法（仅在变更已获批准且使用对应容器/配置时）：

```bash
docker compose config
docker compose run --rm nginx nginx -t
```

**预期：** compose config 无 secret 泄露/未知挂载；`nginx -t` 输出 `syntax is ok` 与 `test is successful`。没有批准的部署变更时跳过并记录原因，不通过本命令获得实施授权。

Classified E2E smoke：

```bash
RL_PUBLICATION_RELEASE_ID=pub_test_001 \
RL_GENERATION=7 \
RL_MANIFEST_DIGEST=sha256:... \
pnpm exec playwright test tests/e2e/publication-smoke.spec.ts --project=chromium
```

**预期：** 指定 manifest 通过；错误 digest 明确 `DETERMINISTIC_FAILURE`；注入 CDN timeout 明确 `TRANSIENT_FAILURE`；pointer/DB commit 不确定明确 `UNKNOWN`，且后续 promotion 被冻结。

### 12.3 C-final evidence bundle

在 C-final gate 形成只读证据包（不提交密钥、token、`.env`、presigned URL）：

- frozen input canonical JSON 与 digest；
- revision snapshot 与 source evidence；
- artifact registry、manifest、ready marker、projection schema version、scan report；
- common validation、consumption declaration、resolver decision 和 capability evidence matrix；
- provider/fake CAS/fencing contract report；
- task registry/outbox/relay/idempotency report；
- build/approval/deployment 三历史事件样例与 hash-chain/checkpoint 引用；
- Prepare/CAS/Finalize 全故障矩阵、compensation target 证明、unknown resolution runbook；
- divergence/orphan/retention/recovery drill 记录；
- revision-aware route 与 classified smoke 结果；
- 失败制品隔离、active pointer 未被覆盖、旧 verified manifest 可读的证明。

## 13. 窄门、停止条件与回滚

### Gate C1：冻结/投影安全

通过条件：snapshot digest 可重建；allowlist 是主要边界；forbidden scan、manifest membership、scope applicability 和 ready marker 顺序全绿。失败时停止，不进入 provider/saga。

### Gate C2：制品/provider 能力

通过条件：fake/provider contract 对 immutable PUT、HEAD/hash/size、ready marker、CAS/fencing、consumption declaration resolver、同源/跨源、sidecar-needed/not-needed、顺序/随机读取和错误语义全绿。失败时停止，不切 pointer。

### Gate C3：构建/任务

通过条件：outbox commit 后 relay、canonical task names、Worker 幂等、SSG/legacy generator identity 分离、manifest-last 全绿。失败时保持旧 active，不重试不同 payload。

### Gate C4：Promotion correctness

通过条件：Prepare → External CAS → Finalize、verifying、classified smoke、CAS-time prior verified compensation、unknown freeze 和三历史 append-only 全绿。失败时不得声称发布成功。

### Gate C5：公开入口/recovery

通过条件：revision-aware immutable route、manifest/ready/pointer 一致、divergence/orphan safeguards、recovery drill、specified profile smoke 全绿。失败时不修改生产 Nginx/CDN，保留旧 verified pointer。

### 回滚规则

- 构建失败：删除/隔离 candidate prefix 只在 retention/hold/reference 检查后进行；active 不变。
- CAS 前失败：同一 binding 有界重试或 failed；active 不变。
- CAS 后 deterministic/transient smoke 失败：追加新的 fenced compensation attempt，目标是该 CAS 时记录的 prior verified manifest；不把旧 attempt 改成未发生。
- 状态 unknown：冻结 promotion、保留全部对象和证据、人工 resolution；不得盲目切回或清理。
- 旧 manifest 只能被新 deployment attempt 重新设为 active；不可修改旧 manifest、approval 或历史事件。

## 14. 最终自审

- 本文件只计划 C，且明确 blocked on A0/A1/B evidence。
- 已覆盖 queue/task contract defect baseline、冻结输入、immutable revision snapshots、artifact registry、canonical manifest、ready marker、`rl_public_projection_schema` allowlists、defense-in-depth scan、common validation、consumption declaration/resolver-driven JBrowse/download capabilities、provider/fake CAS、outbox relay、idempotent Worker、Prepare→CAS→Finalize、fencing、smoke classification、compensation、divergence/orphan/retention/recovery、revision-aware SSG/Nginx routes 和 classified smoke。
- 三条 history 保持独立；dataset release 与 publication release 未混用。
- 未实现 D/E UI；C 只提供 D/E 所需 artifact/schema/status seam。
- 所有代表性新增业务符号使用 `rl_` 前缀，并在关键安全/版本/CAS 规则加入中文 why-comments。
- 未留下未决占位项，未要求自动 commit，未修改代码、迁移、依赖或部署文件。
