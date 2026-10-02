# Module TSV Import Foundation Implementation Plan

> **已归档（2026-10-01）**：已被现行计划取代的历史实施计划。继任：`docs/aegis/plans/` 与 `docs/aegis/INDEX.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make module TSV uploads perform a real, idempotent, release-scoped PostgreSQL import and reliably dispatch the next pipeline task.

**Architecture:** Extend the existing ImportTask/DataSet/outbox state machine instead of creating a second job system. A strict server-owned schema registry validates TSV files before a worker bulk-loads rows into release-scoped staging records; only a fully validated transaction becomes ready and emits `static_publish_requested`.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Celery, pytest, testcontainers.

---

## File Structure

- Create `apps/api/app/models/module_data.py`: module schema, dataset version, and release-scoped row models.
- Create `apps/api/app/services/module_schema_registry.py`: server-owned TSV schemas and row validation.
- Create `apps/api/app/services/module_import_service.py`: transactional staging/upsert/finalize operations.
- Create `apps/api/app/api/v1/admin_modules.py`: schema download and module-import endpoints.
- Create `apps/api/migrations/versions/0015_module_tsv_imports.py`: new tables and enum value.
- Modify `apps/api/app/models/import_task.py`: add `module_tsv` import type.
- Modify `apps/api/app/services/outbox_service.py`: typed task payload constructor.
- Modify `apps/api/app/core/outbox_dispatcher.py`: reject malformed task events and dispatch named tasks.
- Modify `apps/api/app/api/v1/admin_imports.py`: create the import event with a task name.
- Modify `apps/worker/src/soymutdb_worker/tasks/data_adapters.py`: strict TSV adapter.
- Modify `apps/worker/src/soymutdb_worker/tasks/ingest.py`: persist state and call the API-side import service contract.
- Test `apps/api/tests/test_outbox.py`, `apps/api/tests/test_task_dispatch.py`, `apps/api/tests/test_module_schema_registry.py`, `apps/api/tests/test_module_import_service.py`.
- Test `apps/worker/tests/test_data_adapters.py`, `apps/worker/tests/test_ingest.py`.

### Task 1: Repair The Outbox Task Contract

- [ ] **Step 1: Add failing payload tests**

In `apps/api/tests/test_outbox.py`, assert that task-producing events contain a non-empty `task_name` and `kwargs`:

```python
def test_import_requested_contains_dispatch_contract(db_session):
    event = enqueue_task_event(
        db_session,
        event_type="import_requested",
        aggregate_type="import_task",
        aggregate_id="import-1",
        task_name="soymutdb_worker.tasks.ingest.run_import_adapter",
        kwargs={"import_task_id": "import-1"},
    )
    assert event.payload["task_name"] == "soymutdb_worker.tasks.ingest.run_import_adapter"
    assert event.payload["kwargs"] == {"import_task_id": "import-1"}
```

- [ ] **Step 2: Verify the test fails**

Run: `apps/api/.venv/bin/python -m pytest apps/api/tests/test_outbox.py -q`

Expected: FAIL because the current enqueue helper does not write `task_name`.

- [ ] **Step 3: Add one typed enqueue helper**

In `apps/api/app/services/outbox_service.py`, add:

```python
def enqueue_task_event(
    session: Session,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    task_name: str,
    kwargs: dict[str, object],
) -> OutboxEvent:
    if not task_name.strip():
        raise ValueError("task_name is required")
    return create_outbox_event(
        session,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload={"task_name": task_name, "kwargs": kwargs},
    )
```

Update import and release event producers to use it. In `apps/api/app/core/outbox_dispatcher.py`, validate `task_name` and pass `kwargs` to `celery_app.send_task`.

- [ ] **Step 4: Add malformed-event behavior**

In `apps/api/tests/test_task_dispatch.py`, assert malformed task events are marked failed with `last_error="missing task_name"` and are not sent to Celery.

- [ ] **Step 5: Run targeted tests**

Run: `apps/api/.venv/bin/python -m pytest apps/api/tests/test_outbox.py apps/api/tests/test_task_dispatch.py apps/api/tests/test_release_service.py -q`

Expected: PASS.

### Task 2: Add Release-Scoped Module Models

- [ ] **Step 1: Write model tests**

Create `apps/api/tests/test_module_import_service.py` with assertions that two releases may contain the same logical row key without collision and that one release cannot contain duplicates.

```python
def test_module_rows_are_unique_per_release(db_session, module_schema):
    first = ModuleDataRow(module_key="genes", release_id="r1", row_key="Glyma.01G1", data={"gene_id": "Glyma.01G1"})
    second = ModuleDataRow(module_key="genes", release_id="r2", row_key="Glyma.01G1", data={"gene_id": "Glyma.01G1"})
    db_session.add_all([first, second])
    db_session.commit()
```

- [ ] **Step 2: Add models and migration**

Create models with these stable fields:

```python
class ModuleSchema(Base):
    __tablename__ = "module_schemas"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    columns: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    unique_key: Mapped[list[str]] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class ModuleDataRow(Base):
    __tablename__ = "module_data_rows"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    module_key: Mapped[str] = mapped_column(String(80), index=True)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("releases.id"), index=True)
    row_key: Mapped[str] = mapped_column(String(512))
    data: Mapped[dict[str, object]] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("module_key", "release_id", "row_key"),)
```

Migration `0015_module_tsv_imports.py` creates the tables, indexes, and the `module_tsv` import type using the repository's existing enum migration style.

- [ ] **Step 3: Verify migration and tests**

Run from `apps/api`: `.venv/bin/alembic upgrade head`

Run: `apps/api/.venv/bin/python -m pytest apps/api/tests/test_data_publishing_models.py apps/api/tests/test_module_import_service.py -q`

Expected: migration succeeds and tests PASS.

### Task 3: Implement Strict TSV Schema Validation

- [ ] **Step 1: Add registry tests**

Create `apps/api/tests/test_module_schema_registry.py` covering exact delimiter, UTF-8, required columns, extra-column rejection, scalar conversion, unique key, maximum rows, and row-numbered errors.

```python
def test_gene_module_rejects_wrong_headers():
    result = validate_tsv("genes", b"gene\tchromosome\nG1\tChr01\n")
    assert result.ok is False
    assert result.errors[0].code == "header_mismatch"

def test_gene_module_reports_duplicate_key():
    data = b"gene_id\tchromosome\tstart\tend\nG1\tChr01\t1\t9\nG1\tChr01\t10\t20\n"
    result = validate_tsv("genes", data)
    assert result.errors[0].row == 3
    assert result.errors[0].code == "duplicate_key"
```

- [ ] **Step 2: Implement the schema registry**

Create immutable definitions in `module_schema_registry.py`:

```python
MODULE_SCHEMAS = {
    "genes": ModuleTsvSchema(
        columns=(
            TsvColumn("gene_id", "string", required=True),
            TsvColumn("chromosome", "string", required=True),
            TsvColumn("start", "integer", required=True, minimum=1),
            TsvColumn("end", "integer", required=True, minimum=1),
            TsvColumn("mutation_feature", "string", required=False),
        ),
        unique_key=("gene_id",),
        max_rows=2_000_000,
    ),
}
```

Use `csv.DictReader(io.StringIO(text), delimiter="\t")`; reject NUL bytes, invalid UTF-8, duplicate headers, missing headers, unknown headers, blank keys, and `end < start`. Return typed rows and bounded diagnostics.

- [ ] **Step 3: Add downloadable schema endpoint**

In `admin_modules.py`, expose `GET /admin/modules/{module_key}/template` returning a TSV header and example row from the registry. Require administrator permission.

- [ ] **Step 4: Run validation tests**

Run: `apps/api/.venv/bin/python -m pytest apps/api/tests/test_module_schema_registry.py -q`

Expected: PASS.

### Task 4: Perform A Real Transactional Import

- [ ] **Step 1: Add rollback and idempotency tests**

Extend `test_module_import_service.py`:

```python
def test_failed_import_exposes_no_rows(db_session, release):
    with pytest.raises(ModuleImportError):
        import_rows(db_session, module_key="genes", release_id=release.id, rows=[valid_row, invalid_row])
    assert count_rows(db_session, "genes", release.id) == 0

def test_same_checksum_retry_is_idempotent(db_session, release):
    first = import_rows(db_session, module_key="genes", release_id=release.id, rows=[valid_row], checksum="sha256:x")
    second = import_rows(db_session, module_key="genes", release_id=release.id, rows=[valid_row], checksum="sha256:x")
    assert second.dataset_id == first.dataset_id
    assert count_rows(db_session, "genes", release.id) == 1
```

- [ ] **Step 2: Implement staging and finalize**

`module_import_service.py` must delete only the current failed staging transaction, bulk insert typed rows, store validation evidence, mark the dataset ready, and enqueue:

```python
enqueue_task_event(
    session,
    event_type="static_publish_requested",
    aggregate_type="dataset",
    aggregate_id=str(dataset.id),
    task_name="soymutdb_worker.tasks.static_publish.build_static_release",
    kwargs={"release_id": str(release_id), "dataset_id": str(dataset.id)},
)
```

Do not change `ActiveRelease` in this transaction.

- [ ] **Step 3: Replace the counting adapter**

In `data_adapters.py`, introduce `ModuleTsvAdapter` that downloads the uploaded object, calls the strict validator, and invokes the import service through the existing repository/API boundary. Remove `module_tsv` from any generic `CsvUpsertAdapter` mapping.

- [ ] **Step 4: Persist worker state**

Replace the logging-only state update in `ingest.py` with updates to `ImportTask.status`, progress, error summary, validation evidence, timestamps, and audit log. Each transition must use `ImportStateMachine`.

- [ ] **Step 5: Run API and worker tests**

Run: `apps/api/.venv/bin/python -m pytest apps/api/tests/test_module_import_service.py apps/api/tests/test_import_state_machine.py apps/api/tests/test_admin_uploads.py -q`

Run: `apps/api/.venv/bin/python -m pytest apps/worker/tests/test_data_adapters.py apps/worker/tests/test_ingest.py -q`

Expected: PASS.

### Task 5: Expose The Admin Import Contract

- [ ] **Step 1: Add API tests**

Test that administrators can create `module_tsv` imports with `module_key`, `schema_version`, `release_id`, object key, checksum, and idempotency key; non-admin users receive 403; unknown schemas receive 422.

- [ ] **Step 2: Extend request schemas and route**

Add the fields to the existing admin import request without weakening existing import types. The route must create ImportTask, DataSet, and the named outbox event in one transaction.

- [ ] **Step 3: Verify contract and OpenAPI**

Run: `apps/api/.venv/bin/python -m pytest apps/api/tests/test_admin_uploads.py apps/api/tests/test_openapi_contract.py apps/api/tests/test_task_contract.py -q`

Expected: PASS with an updated generated client contract if required.

### Task 6: Phase Verification

- [ ] Run: `apps/api/.venv/bin/python -m pytest apps/api/tests/test_outbox.py apps/api/tests/test_task_dispatch.py apps/api/tests/test_module_schema_registry.py apps/api/tests/test_module_import_service.py apps/api/tests/test_import_state_machine.py -q`
- [ ] Run: `apps/api/.venv/bin/python -m pytest apps/worker/tests/test_data_adapters.py apps/worker/tests/test_ingest.py -q`
- [ ] Run: `pnpm --filter @soymutdb/api-client check:contract`
- [ ] Run: `apps/api/.venv/bin/ruff check apps/api/app/services/module_schema_registry.py apps/api/app/services/module_import_service.py apps/api/app/api/v1/admin_modules.py`

Expected: all targeted checks pass; a deliberately invalid TSV leaves the prior active release and public rows unchanged.
