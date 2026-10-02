# 数据发布与 Release 主链实施计划

> **已归档（2026-10-01）**：已被现行计划取代的历史实施计划。继任：`docs/aegis/plans/` 与 `docs/aegis/INDEX.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一条由 PostgreSQL 权威状态机驱动的 MinIO 分片上传、七类数据适配器导入、Release 组装、原子发布与可审计回滚主链。

**Architecture:** API 只负责管理员鉴权、预签名 multipart 会话、对象登记和状态机命令；大文件始终由浏览器直传 MinIO，不经过 FastAPI 内存。PostgreSQL 保存 `data_sets`、`import_tasks`、`releases`、关系表、manifest/provenance、active 指针和审计；事务内写业务状态与 outbox，worker 使用幂等适配器完成入库。所有数据集完成 ready、manifest 完成且 JBrowse/BLAST/下载/API 检查通过后，发布事务只在行锁保护下切换 `active_release` 指针；构建和 smoke 不在切指针事务中执行。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2 async、Alembic、PostgreSQL、Celery、MinIO/S3 multipart presigned URL、ClickHouse `variant_facts` ReplacingMergeTree、cyvcf2、pytest/pytest-asyncio。

---

## 约束与现状基线

- 规格来源：完整阅读 `docs/superpowers/specs/2026-08-13-data-publishing-and-search-ia-design.md`，本计划覆盖第 2、3、4、9 节；第 5—8 节不在本核心链实施范围。
- 当前 Alembic 最新版本是 `0013`，其 `down_revision = "0012"`；新迁移必须创建为 `apps/api/migrations/versions/0014_data_publishing_release_core.py`，`down_revision = "0013"`，不得重编号已有迁移。
- 当前 `ImportTask` 仍是 `queued/running/completed/failed`，`Release` 仍是 `draft/staging/active/archived`；实现时用新业务状态替换发布主链字段/枚举，并在 API 响应中只暴露新状态。
- `apps/api/app/services/outbox_service.py` 已提供 `create_outbox_event()`、`claim_pending()` 与 `FOR UPDATE SKIP LOCKED`；新服务必须复用，不得自行直接依赖 broker。
- `apps/api/app/services/presign.py` 已有安全的 S3 key 校验和 presigned PUT；multipart 会话需要在同一服务中增加专用 `gwas/` 或数据发布命名空间，不得把整文件读入 FastAPI。
- `apps/worker/src/soymutdb_worker/tasks/ingest.py` 已有未提交修改，且包含当前 VCF 的确定性 ID、cyvcf2、ANN 解析、批量 ClickHouse 写入和 GFF3/品系计数任务。以下步骤只允许在现有函数旁增量加入适配器协议、状态回写和七类入口；不得重写该文件整体、不得删除或覆盖现有 VCF 逻辑。若工作区中的版本与本计划基线不同，以现场文件为准，仅在其稳定函数签名上加薄适配层。

## 文件结构映射与所有权

### 新建文件

- `apps/api/app/models/data_publishing.py`：`DataSet`、`ReleaseDataSet`、`ActiveRelease`、`Provenance` ORM 模型及导入/数据集状态枚举；只负责持久化结构。
- `apps/api/app/services/import_state_machine.py`：导入状态转换表、服务端校验、失败重试规则和带审计的转换函数；不负责 Celery 实际执行。
- `apps/api/app/services/release_service.py`：Release 创建/组装、验证门禁、行锁原子发布、上一版本回滚、manifest 和审计；不负责构建 JBrowse。
- `apps/api/app/schemas/data_publishing.py`：multipart、数据集、导入状态、Release 命令/响应的 Pydantic 类型，作为 OpenAPI 输入输出契约。
- `apps/api/tests/test_import_state_machine.py`：导入状态机的纯单元测试。
- `apps/api/tests/test_release_service.py`：Release 门禁、锁、原子切换、回滚和审计的服务测试。
- `apps/api/tests/test_admin_data_publishing.py`：管理员 API、multipart、状态命令和幂等 API 测试。
- `apps/worker/src/soymutdb_worker/tasks/data_adapters.py`：七类适配器的协议、输入输出统计类型、轻量注册表和非 VCF 适配器实现；复用 `ingest.py` 的既有 VCF 函数，不复制其解析代码。
- `apps/worker/tests/test_data_adapters.py`：七类适配器的 fixture、幂等、校验和失败进度测试。
- `apps/api/migrations/versions/0014_data_publishing_release_core.py`：一次性创建/扩展本主链所需表、枚举、约束、索引及 `import_tasks`/`releases` 增量字段。

### 修改文件

- `apps/api/app/models/import_task.py`：把状态、对象引用、`data_set_id`、Release、幂等键、错误详情和重试字段映射到数据库；保持已有导入任务可被查询。
- `apps/api/app/models/content.py`：将 `ReleaseStatus` 与 `Release` 扩展为 `draft/validated/ready/published/rolled_back`，补齐 assembly、manifest、理由、审批和发布时间字段。
- `apps/api/app/models/auth.py`：不改变 `AuditLog` 结构；只在需要时补结构化 action 常量/辅助函数，继续复用 `new_value`/`old_value` 保存状态迁移和证据。
- `apps/api/app/models/outbox.py`：若迁移需要，补 `idempotency_key` 唯一约束或通过现有 `payload`/aggregate 唯一索引支撑；保留已有 dispatcher 语义。
- `apps/api/app/models/__init__.py`：导入并导出新增模型和枚举，确保 `Base.metadata` 完整。
- `apps/api/app/api/v1/admin_imports.py`：改为调用 multipart、对象登记、数据集创建、状态转换和 outbox 服务；保留管理员鉴权，移除“先 commit 再 dispatch”的非原子路径。
- `apps/api/app/api/v1/admin.py`：新增或挂载 Release 组装、验证、发布、回滚端点；统一调用共享 admin helper，保留现有 audit 查询端点。
- `apps/api/app/services/presign.py`：新增 multipart initiate/sign-part/complete 的 MinIO 包装和 `data/{data_set_id}/...` key 校验；只传 URL/ETag，不传文件字节。
- `apps/api/app/services/outbox_service.py`：增加按业务幂等键的同事务创建/查询 helper，避免重复 dispatch；不改变已有 BLAST/分析调用方。
- `apps/api/app/services/clickhouse_service.py`：增加发布导入专用批量写入函数，固定 `variant_facts` 表名、绑定参数，并明确 ReplacingMergeTree 使用稳定 `variant_id/release_key`；现有查询 API 不改。
- `apps/worker/src/soymutdb_worker/tasks/ingest.py`：只增量接入 `ImportTask` 状态回写/进度回调、复用 `data_adapters` 注册表和 VCF adapter wrapper；保留现有 `import_vcf`、`import_gff3`、`import_mutant_lines` 函数及其当前未提交改动。
- `apps/api/app/core/task_contract.py`：注册七类导入/验证任务名称和 `QUEUE_INGEST`，由 API/worker 共用。
- `packages/jobs-py/src/soymutdb_jobs/contract.py`：若该共享契约文件存在对应常量，补齐同名任务和 payload 版本；只加新常量，不改既有任务名。
- `apps/worker/tests/test_ingest.py`：在现有确定性 VCF helper 测试旁增加状态回写和 wrapper 测试；不改已有断言。

---

## 状态与接口契约（实现时必须保持一致）

### 导入状态机

```python
class ImportStatus(str, enum.Enum):
    UPLOADING = "uploading"
    VALIDATING = "validating"
    INGESTING = "ingesting"
    READY = "ready"
    PUBLISHED = "published"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"

IMPORT_TRANSITIONS: dict[ImportStatus, frozenset[ImportStatus]] = {
    ImportStatus.UPLOADING: frozenset({ImportStatus.VALIDATING, ImportStatus.FAILED}),
    ImportStatus.VALIDATING: frozenset({ImportStatus.INGESTING, ImportStatus.FAILED}),
    ImportStatus.INGESTING: frozenset({ImportStatus.READY, ImportStatus.FAILED}),
    ImportStatus.READY: frozenset({ImportStatus.PUBLISHED, ImportStatus.FAILED}),
    ImportStatus.PUBLISHED: frozenset({ImportStatus.ROLLED_BACK}),
    ImportStatus.FAILED: frozenset({ImportStatus.UPLOADING, ImportStatus.VALIDATING, ImportStatus.INGESTING}),
    ImportStatus.ROLLED_BACK: frozenset(),
}

async def transition_import(
    db: AsyncSession,
    *,
    import_task_id: int,
    target: ImportStatus,
    actor_id: uuid.UUID,
    evidence: dict[str, Any] | None = None,
) -> ImportTask: ...
```

服务端必须按当前状态、对象 complete 校验、适配器校验结果和前置状态判断；前端传入的 `stage.x.completed` 只能作为命令，不得直接写 status。失败保留 `error_detail`、`failed_batch` 和进度，重试只能从 `failed` 进入允许的阶段，并复用同一数据集/对象及新的 outbox event。

### 发布状态机与服务签名

```python
class ReleaseStatus(str, enum.Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    READY = "ready"
    PUBLISHED = "published"
    ROLLED_BACK = "rolled_back"

async def validate_release(
    db: AsyncSession, *, release_id: int, actor_id: uuid.UUID
) -> Release: ...

async def mark_release_ready(
    db: AsyncSession, *, release_id: int, actor_id: uuid.UUID,
    manifest: dict[str, Any], readiness: dict[str, bool]
) -> Release: ...

async def publish_release(
    db: AsyncSession, *, release_id: int, actor_id: uuid.UUID,
    reason: str, request_id: str | None = None
) -> Release: ...

async def rollback_release(
    db: AsyncSession, *, release_id: int, actor_id: uuid.UUID,
    reason: str, request_id: str | None = None
) -> tuple[Release, Release]: ...
```

`publish_release()` 必须在 `async with db.begin()` 内 `SELECT active_release FOR UPDATE` 和 `SELECT release FOR UPDATE`，确认目标为 `ready`、所有关联数据集为 `ready`、manifest 完整、上一 active（若存在）不是同一目标，再更新指针、目标 Release 状态/时间/操作者并插入 `AuditLog(action="release_published")`。JBrowse bundle、BLAST 数据库、下载文件和门户/API smoke 必须在此前的 `mark_release_ready()` 门禁中完成；发布事务不调用构建器、不发网络请求，解决规格第 4 节“提交后触发构建”与原子发布验收之间的时序矛盾。提交后只通过 outbox 发 `release_pointer_changed` 做缓存/通知刷新。

## 任务清单

### Task 1: 建立数据模型与 0014 迁移

**Files:**
- Create: `apps/api/migrations/versions/0014_data_publishing_release_core.py`
- Create: `apps/api/app/models/data_publishing.py`
- Modify: `apps/api/app/models/import_task.py`
- Modify: `apps/api/app/models/content.py`
- Modify: `apps/api/app/models/__init__.py`
- Test: `apps/api/tests/test_data_publishing_models.py`

- [ ] **Step 1: 写模型 RED 测试**

```python
def test_release_and_dataset_states_are_exactly_the_approved_vocabulary():
    assert {state.value for state in ImportStatus} == {
        "uploading", "validating", "ingesting", "ready", "published", "failed", "rolled_back"
    }
    assert {state.value for state in ReleaseStatus} == {
        "draft", "validated", "ready", "published", "rolled_back"
    }

def test_import_task_has_idempotency_and_dataset_foreign_key():
    table = ImportTask.__table__
    assert {"data_set_id", "idempotency_key", "error_detail", "failed_batch"} <= set(table.c.keys())
    assert any(fk.target_fullname == "data_sets.id" for fk in table.c.data_set_id.foreign_keys)
```

- [ ] **Step 2: 运行 RED 测试**

Run: `cd apps/api && pytest tests/test_data_publishing_models.py -q`

Expected: `2 failed`，失败原因分别是新枚举/字段尚未定义。

- [ ] **Step 3: 实现 ORM 和迁移**

`data_publishing.py` 使用整数主键与现有 `TimestampMixin`，字段至少如下：

```python
class DataSet(Base, TimestampMixin):
    __tablename__ = "data_sets"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    release_id: Mapped[int | None] = mapped_column(ForeignKey("releases.id", ondelete="SET NULL"))
    source_objects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(Enum(ImportStatus, name="import_status_enum"), nullable=False, server_default="uploading")
    validation_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

class ReleaseDataSet(Base):
    __tablename__ = "release_data_sets"
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id", ondelete="CASCADE"), primary_key=True)
    data_set_id: Mapped[int] = mapped_column(ForeignKey("data_sets.id", ondelete="CASCADE"), primary_key=True)

class ActiveRelease(Base):
    __tablename__ = "active_release"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    release_id: Mapped[int | None] = mapped_column(ForeignKey("releases.id", ondelete="RESTRICT"))

class Provenance(Base, TimestampMixin):
    __tablename__ = "provenance"
    id: Mapped[int] = mapped_column(primary_key=True)
    data_set_id: Mapped[int] = mapped_column(ForeignKey("data_sets.id", ondelete="CASCADE"), index=True)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(1024), nullable=False)
    tool: Mapped[str | None] = mapped_column(String(128))
    tool_version: Mapped[str | None] = mapped_column(String(64))
```

`ImportTask` 增加 `data_set_id`、`release_id`、`idempotency_key`（非空、唯一）、`object_key`、`error_detail`、`failed_batch`、`retry_count`；保留 `celery_task_id` 和进度列。`Release` 增加 `assembly`、`manifest`、`active_at`、`rolled_back_at`、`reason`、`approved_by`，把状态枚举改为批准词汇。迁移创建 `data_sets`、`release_data_sets`、`active_release`（插入 id=1 空指针）、`provenance`，扩展旧表，并创建 `uq_import_tasks_idempotency_key`、外键和状态索引。迁移 downgrade 按依赖逆序删除。

- [ ] **Step 4: 运行 GREEN 与迁移检查**

Run: `cd apps/api && pytest tests/test_data_publishing_models.py -q && alembic upgrade head && alembic downgrade 0013 && alembic upgrade head`

Expected: 模型测试 `2 passed`；迁移 upgrade/downgrade/upgrade 均退出码 0，最终 head 为 `0014`。

### Task 2: 实现导入状态机、审计和失败重试

**Files:**
- Create: `apps/api/app/services/import_state_machine.py`
- Modify: `apps/api/app/models/import_task.py`
- Modify: `apps/api/app/models/auth.py`
- Test: `apps/api/tests/test_import_state_machine.py`

- [ ] **Step 1: 写纯状态转换 RED 测试**

```python
def test_import_transitions_reject_skipping_validation():
    with pytest.raises(InvalidStateTransition, match="uploading -> ingesting"):
        assert_transition(ImportStatus.UPLOADING, ImportStatus.INGESTING)

def test_failed_import_can_retry_from_validation_but_published_cannot():
    assert_transition(ImportStatus.FAILED, ImportStatus.VALIDATING)
    with pytest.raises(InvalidStateTransition):
        assert_transition(ImportStatus.PUBLISHED, ImportStatus.INGESTING)
```

- [ ] **Step 2: 运行 RED**

Run: `cd apps/api && pytest tests/test_import_state_machine.py -q`

Expected: `2 failed`，因为 `InvalidStateTransition` 和转换表尚未实现。

- [ ] **Step 3: 实现服务端转换**

实现 `assert_transition(current: ImportStatus, target: ImportStatus) -> None` 和前述 `transition_import()`。函数用 `select(ImportTask).where(...).with_for_update()` 读取当前行；验证 target 在表中、`failed` 重试目标只允许 `validating/ingesting`（若重新上传则先由上传 API 转 uploading）、非失败状态不允许 retry；更新 `status`、`error_detail`、`failed_batch` 和时间，`db.add(AuditLog(action=f"import_{target.value}", resource_type="import_task", resource_id=str(id), old_value=..., new_value=...))`，只 `flush()` 不 commit，让调用方把状态和 outbox 放入同一事务。

- [ ] **Step 4: 写事务审计 RED 测试并实现**

```python
async def test_transition_writes_structured_audit_in_same_session(db, admin_user):
    task = await make_task(db, status=ImportStatus.UPLOADING)
    await transition_import(db, import_task_id=task.id, target=ImportStatus.VALIDATING,
                            actor_id=admin_user.id, evidence={"sha256": "a" * 64})
    logs = (await db.execute(select(AuditLog).where(AuditLog.resource_id == str(task.id)))).scalars().all()
    assert logs[-1].action == "import_validating"
    assert logs[-1].new_value["status"] == "validating"
```

Run before implementation: `cd apps/api && pytest tests/test_import_state_machine.py::test_transition_writes_structured_audit_in_same_session -q`

Expected RED: `ImportTask` remains in `uploading` or the audit row is absent. After implementation, expected `1 passed`.

### Task 3: 增加 MinIO multipart 直传与对象登记 API

**Files:**
- Modify: `apps/api/app/services/presign.py`
- Create: `apps/api/app/schemas/data_publishing.py`
- Modify: `apps/api/app/api/v1/admin_imports.py`
- Test: `apps/api/tests/test_admin_data_publishing.py`

- [ ] **Step 1: 写 multipart RED 测试**

```python
async def test_multipart_flow_returns_presigned_part_urls_and_never_reads_body(client, admin_headers, mock_s3):
    mock_s3.create_multipart_upload.return_value = {"UploadId": "u-1"}
    response = await client.post("/api/v1/admin/imports/uploads/multipart",
        headers=admin_headers, json={"filename": "genome.fa.gz", "type": "fasta", "part_count": 2})
    assert response.status_code == 201
    assert response.json()["upload_id"] == "u-1"
    assert len(response.json()["parts"]) == 2
    assert "file_bytes" not in response.json()

async def test_complete_requires_etags_and_sha256(client, admin_headers):
    response = await client.post("/api/v1/admin/imports/uploads/multipart/u-1/complete",
        headers=admin_headers, json={"parts": [{"part_number": 1, "etag": "e1"}], "sha256": "bad"})
    assert response.status_code == 422
```

- [ ] **Step 2: 运行 RED**

Run: `cd apps/api && pytest tests/test_admin_data_publishing.py -k multipart -q`

Expected: `2 failed`，因为 multipart 路由和 schema 尚不存在。

- [ ] **Step 3: 实现 presign 函数和路由**

实现精确签名：

```python
def initiate_multipart_upload(*, data_set_id: int, filename: str, content_type: str, bucket: str) -> MultipartSession: ...
def sign_multipart_part(*, object_key: str, upload_id: str, part_number: int, bucket: str) -> str: ...
def complete_multipart_upload(*, object_key: str, upload_id: str, parts: list[CompletedPart], sha256: str, bucket: str) -> CompletedObject: ...
```

key 固定为 `gwas/data_sets/{data_set_id}/{uuid}-{sanitized_filename}`；校验 part number 为 1—10000、ETag 非空、sha256 为 64 位十六进制。路由只接受元数据，调用 boto3 `create_multipart_upload`、`generate_presigned_url("upload_part", ...)`、`complete_multipart_upload`，成功后以 `source_objects` 登记 key、upload id、大小、ETag、sha256、content type，并将 ImportTask 从 uploading 转 validating；完整校验失败调用 abort，不把对象内容读入 API。所有路由调用共享 `require_admin()`（从 admin helper 提取，不能保留两份权限实现）。

- [ ] **Step 4: 运行 GREEN 和安全检查**

Run: `cd apps/api && pytest tests/test_admin_data_publishing.py -k multipart -q`

Expected: `2 passed`，响应只包含预签名 URL、upload id、对象 key 和登记证据；`rg -n "request\.body|UploadFile|read\(" apps/api/app/api/v1/admin_imports.py apps/api/app/services/presign.py` 不出现 multipart 文件读取实现。

### Task 4: 建立 outbox 幂等导入创建与管理员导入 API

**Files:**
- Modify: `apps/api/app/services/outbox_service.py`
- Modify: `apps/api/app/api/v1/admin_imports.py`
- Modify: `apps/api/app/core/task_contract.py`
- Modify: `packages/jobs-py/src/soymutdb_jobs/contract.py`
- Test: `apps/api/tests/test_admin_data_publishing.py`

- [ ] **Step 1: 写幂等 RED 测试**

```python
async def test_same_import_idempotency_key_returns_one_task_and_one_outbox(db, admin_user):
    first = await create_import_command(db, actor_id=admin_user.id, idempotency_key="import:42",
                                        data_set_id=42, import_type="vcf")
    second = await create_import_command(db, actor_id=admin_user.id, idempotency_key="import:42",
                                         data_set_id=42, import_type="vcf")
    assert first.id == second.id
    assert await count_outbox(db, aggregate_id=str(first.id)) == 1
```

- [ ] **Step 2: 运行 RED**

Run: `cd apps/api && pytest tests/test_admin_data_publishing.py::test_same_import_idempotency_key_returns_one_task_and_one_outbox -q`

Expected: `1 failed`，现有 endpoint 会重复创建任务且没有原子 outbox。

- [ ] **Step 3: 实现同事务命令**

增加：

```python
async def get_or_create_idempotent_event(
    db: AsyncSession, *, aggregate_type: str, aggregate_id: str,
    event_type: str, idempotency_key: str, payload: dict[str, Any]
) -> tuple[OutboxEvent, bool]: ...
```

用唯一 `idempotency_key` 查询/捕获 `IntegrityError`，在同一个 `db.begin()` 中创建 DataSet、ImportTask、OutboxEvent；payload 固定含 `import_task_id`、`data_set_id`、`type`、`object_key`、`idempotency_key`、`payload_version`。七类任务常量为 `import_fasta/import_gff3/import_vcf/import_blast_db/import_seed/import_expression/import_homolog`，统一队列 `ingest`。删除现有“commit 后直接 dispatch”路径；由 dispatcher 使用 event_id 作为 Celery task_id。API 的 retry 先服务端校验 failed 状态，再创建新 attempt 的 outbox，不修改 idempotency key。

- [ ] **Step 4: 运行 GREEN**

Run: `cd apps/api && pytest tests/test_admin_data_publishing.py::test_same_import_idempotency_key_returns_one_task_and_one_outbox -q`

Expected: `1 passed`，数据库中一个 ImportTask、一个 pending outbox event，broker 不在 HTTP 请求事务内被直接调用。

### Task 5: 实现七类 worker 适配器与增量 ingest 接入

**Files:**
- Create: `apps/worker/src/soymutdb_worker/tasks/data_adapters.py`
- Modify: `apps/worker/src/soymutdb_worker/tasks/ingest.py`
- Modify: `apps/worker/tests/test_ingest.py`
- Create: `apps/worker/tests/test_data_adapters.py`
- Modify: `apps/api/app/services/clickhouse_service.py`

- [ ] **Step 1: 写适配器 RED 测试**

```python
@pytest.mark.parametrize("kind", ["fasta", "gff3", "vcf", "blast_db", "seed_data", "expression_csv", "homolog_csv"])
def test_all_approved_types_are_registered(kind):
    assert get_adapter(kind).kind == kind

def test_vcf_adapter_uses_stable_id_and_variant_facts(monkeypatch, vcf_fixture):
    calls = []
    monkeypatch.setattr("soymutdb_worker.tasks.ingest.get_clickhouse_client", lambda: FakeCH(calls))
    result = get_adapter("vcf").run(ImportContext(release_id="r1", file_key=vcf_fixture, assembly="a1"))
    assert result.inserted >= 1
    assert calls[0].table == "variant_facts"
    assert calls[0].rows[0][0] == compute_variant_id("r1", vcf_fixture, "chr1", 1, "A", "G")
```

- [ ] **Step 2: 运行 RED**

Run: `cd apps/worker && pytest tests/test_data_adapters.py -q`

Expected: `2 failed`，因为注册表和 adapter protocol 尚不存在。

- [ ] **Step 3: 实现 adapter protocol 与七类行为**

使用以下类型，不在 adapter 中访问 API ORM：

```python
@dataclass(frozen=True)
class ImportContext:
    import_task_id: int
    data_set_id: int
    release_id: str
    file_key: str
    assembly: str | None = None

@dataclass(frozen=True)
class AdapterResult:
    records: int
    inserted: int
    skipped: int
    evidence: dict[str, Any]

class DataAdapter(Protocol):
    kind: str
    def validate(self, context: ImportContext) -> dict[str, Any]: ...
    def run(self, context: ImportContext, *, progress: ProgressCallback | None = None) -> AdapterResult: ...
```

注册表必须精确包含七类。FASTA 解析并写 assembly/chromosome，生成 `.fai` 索引并登记 provenance；GFF3 写 `genes/transcripts/exons/aliases`，检查 assembly 与 FASTA 一致；VCF wrapper 直接调用现有 `ingest.import_vcf(release_id, file_key, assembly_key, batch_size)`，保留当前确定性 ID、ANN、zygosity 和 batch insert，ClickHouse 表固定 `variant_facts`，以 stable variant id 配合 ReplacingMergeTree 去重并校验 release/sample；BLAST DB 调 `makeblastdb` 到数据集专属目录，登记 `blast_databases` 及派生索引 provenance；Seed 写 seed 请求/库存表；Expression/Homolog 使用 PostgreSQL `INSERT ... ON CONFLICT (...) DO UPDATE/NOTHING`，唯一键分别固定为规格对应的业务 identity，不使用无界内存集合。

- [ ] **Step 4: 增加进度/失败回写，但不重写 ingest.py**

在 `ingest.py` 现有任务旁新增一个薄 wrapper：

```python
@celery_app.task(name="soymutdb_worker.tasks.ingest.run_import_adapter", queue="ingest")
def run_import_adapter(import_task_id: int, data_set_id: int, kind: str,
                       release_id: str, file_key: str, assembly: str = "") -> dict[str, Any]:
    context = ImportContext(import_task_id=import_task_id, data_set_id=data_set_id,
                            release_id=release_id, file_key=file_key, assembly=assembly or None)
    try:
        update_import_progress(import_task_id, status="ingesting", progress=0)
        result = get_adapter(kind).run(context, progress=update_import_progress)
        update_import_progress(import_task_id, status="ready", progress=100, evidence=result.evidence)
        return asdict(result)
    except Exception as exc:
        update_import_progress(import_task_id, status="failed", error_detail=str(exc), failed_batch=current_batch())
        raise
```

该 wrapper 只能调用已有 `import_vcf` 或新 adapter；不得替换现有 1—626 行 VCF/GFF3 函数。状态回写通过窄 HTTP/数据库 repository，并以 `import_task_id` 幂等更新；部分批次失败时记录 batch 边界，重试从 adapter 的 checkpoint 继续。

- [ ] **Step 5: 运行 GREEN 与现有回归**

Run: `cd apps/worker && pytest tests/test_data_adapters.py tests/test_ingest.py -q`

Expected: 新增 adapter 测试和原有 6 个 helper 测试全部 PASS；VCF 测试确认重复运行产生相同 ID，GFF3/FASTA/BLAST/Seed/Expression/Homolog 均返回具体 evidence，不再是静默 no-op。

### Task 6: Release 组装、验证门禁与 manifest

**Files:**
- Create: `apps/api/app/services/release_service.py`
- Modify: `apps/api/app/api/v1/admin.py`
- Modify: `apps/api/app/schemas/data_publishing.py`
- Test: `apps/api/tests/test_release_service.py`

- [ ] **Step 1: 写 Release RED 测试**

```python
async def test_validate_release_rejects_dataset_not_ready(db, release, actor):
    await attach_dataset(db, release, status=ImportStatus.INGESTING)
    with pytest.raises(ReleaseNotReady, match="all data sets must be ready"):
        await validate_release(db, release_id=release.id, actor_id=actor.id)

async def test_ready_requires_jbrowse_blast_download_api_smoke(db, release, actor):
    evidence = {"jbrowse": True, "blast": True, "downloads": True, "api": False}
    with pytest.raises(ReleaseNotReady, match="api"):
        await mark_release_ready(db, release_id=release.id, actor_id=actor.id,
                                 manifest={"version": "r1", "provenance": []}, readiness=evidence)
```

- [ ] **Step 2: 运行 RED**

Run: `cd apps/api && pytest tests/test_release_service.py -q`

Expected: `2 failed`，因为 release service 尚未存在。

- [ ] **Step 3: 实现 draft→validated→ready 门禁**

`validate_release()` 锁定 Release，要求至少一个数据集且每个关联 `DataSet.status == ready`，检查 assembly 一致、每个 source object 有 sha256/ETag、provenance 完整，然后写 `validated` 和 `release_validated` 审计。`mark_release_ready()` 只接受全部四项 readiness：`jbrowse`, `blast`, `downloads`, `api` 均为 True；manifest 结构为：

```python
manifest = {
    "release_id": str(release.id), "version": release.version,
    "assembly": release.assembly,
    "datasets": [{"id": ds.id, "type": ds.type, "sha256": sha256, "objects": keys}],
    "provenance": [{"source": p.source, "tool": p.tool, "tool_version": p.tool_version,
                    "sha256": p.checksum_sha256}],
}
```

只在验证后的 manifest 和 smoke 证据持久化后写 `ready`，同时审计 `release_ready`。JBrowse bundle、makeblastdb、下载 manifest 和 API smoke 在此服务被调用前由构建 pipeline 完成；服务只验证证据，不在事务里执行外部工作。

- [ ] **Step 4: 运行 GREEN**

Run: `cd apps/api && pytest tests/test_release_service.py -q`

Expected: `2 passed`，不满足任一数据集或任一 readiness 门禁时 Release 不会进入 ready。

### Task 7: 行锁保护的原子发布、指针切换和回滚

**Files:**
- Modify: `apps/api/app/services/release_service.py`
- Modify: `apps/api/app/api/v1/admin.py`
- Modify: `apps/api/app/services/outbox_service.py`
- Test: `apps/api/tests/test_release_service.py`

- [ ] **Step 1: 写并发/原子发布 RED 测试**

```python
async def test_publish_changes_pointer_and_release_in_one_transaction(db, ready_release, actor):
    published = await publish_release(db, release_id=ready_release.id, actor_id=actor.id, reason="approved")
    pointer = await db.scalar(select(ActiveRelease).where(ActiveRelease.id == 1))
    assert pointer.release_id == ready_release.id
    assert published.status == ReleaseStatus.PUBLISHED.value
    assert await count_audit(db, action="release_published", resource_id=str(ready_release.id)) == 1

async def test_publish_rejects_second_ready_release_when_lock_conflicts(db, release_a, release_b, actor):
    await publish_release(db, release_id=release_a.id, actor_id=actor.id, reason="first")
    with pytest.raises(ReleaseNotReady, match="active release transition"):
        await publish_release(db, release_id=release_b.id, actor_id=actor.id, reason="stale")
```

- [ ] **Step 2: 运行 RED**

Run: `cd apps/api && pytest tests/test_release_service.py -k publish -q`

Expected: `2 failed`，因为 active 指针尚未被服务更新，且没有发布行锁。

- [ ] **Step 3: 实现发布事务**

在 `publish_release()` 中使用：

```python
async with db.begin():
    pointer = (await db.execute(select(ActiveRelease).where(ActiveRelease.id == 1)
                                .with_for_update())).scalar_one()
    target = (await db.execute(select(Release).where(Release.id == release_id)
                               .with_for_update())).scalar_one()
    if target.status != ReleaseStatus.READY.value or not await release_is_ready(db, target.id):
        raise ReleaseNotReady("release must be ready before publishing")
    previous_id = pointer.release_id
    pointer.release_id = target.id
    target.status = ReleaseStatus.PUBLISHED.value
    target.active_at = datetime.now(UTC)
    target.published_at = target.active_at
    target.published_by = actor_id
    target.reason = reason
    db.add(AuditLog(user_id=actor_id, action="release_published", resource_type="release",
                    resource_id=str(target.id), old_value={"active_release_id": previous_id},
                    new_value={"active_release_id": target.id, "reason": reason,
                               "manifest_sha256": manifest_digest(target.manifest)}))
    await create_outbox_event(db, aggregate_type="release", aggregate_id=str(target.id),
                              event_type="release_pointer_changed",
                              payload={"previous_release_id": previous_id, "release_id": target.id})
```

若旧的 `active_release` 状态仍为 published，先保持历史 published，不伪造 archived；门户/API/JBrowse/BLAST/download 的读取入口均必须通过 active 指针解析。事务提交后 outbox dispatcher 刷新缓存/通知，不能在提交前暴露新版本。

- [ ] **Step 4: 实现回滚并测试**

回滚服务先锁指针和目标，查找按 `active_at DESC` 的上一 `published` Release，要求理由非空；在同一事务将指针切回上一版本、当前版本改 `rolled_back` 并写 `rolled_back_at`/`reason`，写 `AuditLog(action="release_rolled_back", old_value={"from": current_id}, new_value={"to": previous_id, "reason": reason})` 和 outbox。没有上一版本时拒绝回滚并保持指针不变。

```python
async def test_rollback_requires_reason_and_restores_previous_pointer(db, published_a, published_b, actor):
    await publish_release(db, release_id=published_a.id, actor_id=actor.id, reason="a")
    await publish_release(db, release_id=published_b.id, actor_id=actor.id, reason="b")
    restored, rolled = await rollback_release(db, release_id=published_b.id, actor_id=actor.id, reason="bad checksum")
    assert restored.id == published_a.id
    assert rolled.status == ReleaseStatus.ROLLED_BACK.value
    assert (await db.scalar(select(ActiveRelease).where(ActiveRelease.id == 1))).release_id == published_a.id
```

Run: `cd apps/api && pytest tests/test_release_service.py -k "publish or rollback" -q`

Expected: `3 passed`（原子发布、冲突拒绝、回滚），审计 action 和理由可查询。

### Task 8: 管理员 Release/导入 API 与契约测试

**Files:**
- Modify: `apps/api/app/api/v1/admin_imports.py`
- Modify: `apps/api/app/api/v1/admin.py`
- Modify: `apps/api/app/schemas/data_publishing.py`
- Test: `apps/api/tests/test_admin_data_publishing.py`

- [ ] **Step 1: 写 HTTP RED 测试**

```python
async def test_release_publish_requires_confirmation_reason(client, admin_headers, ready_release):
    response = await client.post(f"/api/v1/admin/releases/{ready_release.id}/publish",
        headers=admin_headers, json={"confirm": False, "reason": ""})
    assert response.status_code == 422

async def test_release_publish_returns_manifest_and_status(client, admin_headers, ready_release):
    response = await client.post(f"/api/v1/admin/releases/{ready_release.id}/publish",
        headers=admin_headers, json={"confirm": True, "reason": "release QA passed"})
    assert response.status_code == 200
    assert response.json()["status"] == "published"
    assert response.json()["manifest"]
```

- [ ] **Step 2: 运行 RED**

Run: `cd apps/api && pytest tests/test_admin_data_publishing.py -k release -q`

Expected: `2 failed`，因为新 Release 命令端点不存在或仍接受无理由发布。

- [ ] **Step 3: 实现端点和请求 schema**

新增端点：`POST /api/v1/admin/releases`、`POST /api/v1/admin/releases/{release_id}/validate`、`POST /api/v1/admin/releases/{release_id}/ready`、`POST /api/v1/admin/releases/{release_id}/publish`、`POST /api/v1/admin/releases/{release_id}/rollback`、`GET /api/v1/admin/releases/{release_id}`。publish/rollback body 为 `ReleaseActionRequest(confirm: Literal[True], reason: str = Field(min_length=1, max_length=2000))`；所有转换从 `get_current_user` 取得 actor，服务端验证状态和数据集，不信任请求中的 status。每个 endpoint 返回真实 status、manifest、readiness、active_release_id、audit action；错误返回 request id 和稳定业务错误码。导入 detail 返回 source objects、provenance、progress、error_detail、retryable。

- [ ] **Step 4: 运行 GREEN 和 OpenAPI 生成检查**

Run: `cd apps/api && pytest tests/test_admin_data_publishing.py -k release -q && python -m app.openapi_export --check`

Expected: `2 passed`；OpenAPI 检查通过，publish/rollback 的 `confirm`、`reason`、状态枚举与实现一致。

### Task 9: API/worker 集成验收与未提交 ingest 协调

**Files:**
- Modify: `apps/api/tests/test_data_publishing_integration.py`
- Modify: `apps/worker/tests/test_data_publishing_integration.py`
- Modify: `apps/worker/src/soymutdb_worker/tasks/ingest.py`（仅必要的薄 wrapper）

- [ ] **Step 1: 写端到端 RED 测试**

```python
async def test_import_to_ready_to_publish_to_rollback(api_db, fake_minio, fake_worker, admin_user):
    task = await create_multipart_and_complete(api_db, fake_minio, kind="fasta")
    await fake_worker.run(task)
    release = await assemble_release(api_db, task.data_set_id)
    await validate_release(api_db, release.id, admin_user.id)
    await mark_release_ready(api_db, release.id, admin_user.id,
                             manifest=fixture_manifest(),
                             readiness={"jbrowse": True, "blast": True, "downloads": True, "api": True})
    await publish_release(api_db, release.id, admin_user.id, "QA")
    previous = await create_and_publish_previous_release(api_db, admin_user.id)
    restored, _ = await rollback_release(api_db, release.id, admin_user.id, "found annotation issue")
    assert restored.id == previous.id
```

- [ ] **Step 2: 运行集成 RED**

Run: `pytest apps/api/tests/test_data_publishing_integration.py apps/worker/tests/test_data_publishing_integration.py -q`

Expected: FAIL only at missing core chain pieces;不要用失败输出替代实现。

- [ ] **Step 3: 增量接合 worker**

确认 `ingest.py` 的现有未提交变更仍保留：`compute_variant_id()`、`parse_snpeff_ann()`、`import_vcf()` 的批量字段与 `import_gff3()` 的现有解析不得被 formatter/重构覆盖。只加入 adapter import、`run_import_adapter()` 入口和最小的状态 repository 注入；对现有函数用 wrapper 传入 `release_id/file_key/assembly_key`，不改变旧调用方参数顺序。若现场 diff 已增加同名入口，复用它并只补缺失状态回写，不创建第二个任务名。测试应同时覆盖旧 helper 和新端到端路径。

- [ ] **Step 4: 运行 GREEN**

Run: `pytest apps/api/tests/test_data_publishing_models.py apps/api/tests/test_import_state_machine.py apps/api/tests/test_release_service.py apps/api/tests/test_admin_data_publishing.py apps/worker/tests/test_ingest.py apps/worker/tests/test_data_adapters.py apps/api/tests/test_data_publishing_integration.py apps/worker/tests/test_data_publishing_integration.py -q`

Expected: 所有新增/现有相关测试 PASS；七类导入均产生可追踪 evidence，失败可 retry，发布和回滚均产生结构化审计。

### Task 10: 规格对照、自审与工作区审查

**Files:**
- Review only: `docs/superpowers/specs/2026-08-13-data-publishing-and-search-ia-design.md`
- Review only: all files listed above

- [ ] **Step 1: 逐条对照规格第 2—4、9 节**

逐项确认并在测试结果中保留证据：React/Admin 不绕过后端状态机；MinIO multipart 预签名、part、complete 和 checksum；`data_sets`、增强 `import_tasks`、增强 `releases`、`release_data_sets`、单行 `active_release`、`provenance`、复用 `AuditLog`；两套状态机及每步服务端校验；`idempotency_key` 与 outbox 同事务；Release 行锁；FASTA/GFF3/VCF/BLAST DB/Seed/Expression/Homolog 七类适配器；Replacing 去重、on_conflict；部分批次失败可重试；ready 门禁包含 JBrowse/BLAST/download/API smoke；事务内只切指针、写 manifest/audit/outbox；回滚上一 active、理由和审计。

- [ ] **Step 2: 扫描计划占位符和未定义名称**

Run: `rg -n -i 'placeholder|未定义|待补' docs/superpowers/plans/2026-08-13-data-publishing-release-core-plan.md`

Expected: 无输出。再核对所有代码块中的函数/类型均在本计划定义或现有基线文件中存在；`ImportStatus`、`ReleaseStatus`、`ImportContext`、`AdapterResult`、`publish_release`、`rollback_release` 的字段和签名必须前后一致。

- [ ] **Step 3: 运行静态检查和精确相关测试**

Run: `cd apps/api && ruff check app/models/data_publishing.py app/services/import_state_machine.py app/services/release_service.py app/api/v1/admin_imports.py app/api/v1/admin.py && cd ../worker && ruff check src/soymutdb_worker/tasks/data_adapters.py src/soymutdb_worker/tasks/ingest.py`

Expected: 两个 ruff 命令均 PASS；若仓库没有 ruff，改用项目已配置的 lint 命令并记录实际命令，不把未运行的全库 lint 宣称为通过。

- [ ] **Step 4: 审查工作区差异但不执行 Git 写操作**

运行：`git diff -- docs/superpowers/plans/2026-08-13-data-publishing-release-core-plan.md`

Expected: 只看到本计划文件的新增内容；不得执行 `git add`、`git commit`、`git reset`、`git checkout`、`git stash` 或覆盖任何现有未提交文件。

## 已知风险与协调策略

1. **`ingest.py` 未提交修改冲突：** 实施者必须先读取并保留现场 diff；本计划只允许增量 wrapper/adapter 注册和状态回写。禁止整文件替换、自动格式化全文件、删除现有 VCF/GFF3 函数或把现有确定性 ID 改回计数器。若状态回写需要改现有函数，只通过可选 callback/default 参数或外层 wrapper，保证原有测试和调用签名继续工作。
2. **ClickHouse ReplacingMergeTree 可见性延迟：** 稳定 variant id 只保证最终去重，ready 门禁必须执行目标 release 的查询/smoke，不能只检查 insert 成功；`OPTIMIZE ... FINAL` 由 worker 在既有 VCF 路径中按现有策略执行，失败应进入 failed/evidence，而不是静默 ready。
3. **PostgreSQL 枚举与旧状态数据：** 规格明确无历史数据兼容回填，但开发数据库可能已有旧 schema；0014 应在干净数据库验证，旧 `ReleaseStatus`/`ImportTaskStatus` 引用必须同步更新，禁止为旧状态增加未批准的隐式转换。
4. **multipart 完成与对象一致性：** MinIO complete 成功不等于内容 checksum 已验证；complete API 必须登记客户端 sha256，并由 validating worker 对对象做流式 checksum/格式校验。checksum 不匹配时保留对象证据、标记 failed、禁止 ingest。
5. **外部构建时序：** JBrowse、BLAST、下载和 smoke 必须先产出不可变 manifest/evidence，再允许 ready；publish 事务只能切换 PostgreSQL 指针。任何实现“publish 后再构建、构建失败后回指针”的方案都不满足本计划的原子发布验收。
6. **并发与重复消息：** outbox dispatcher 可能重复投递；worker 需以 `import_task_id + idempotency_key` 和稳定 ClickHouse variant id/SQL on-conflict 保证重复消费无副作用。Release publish/rollback 必须锁 `active_release` 和目标 Release，并在冲突时返回明确业务错误。
