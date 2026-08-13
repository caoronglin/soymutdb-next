"""GWAS submission via transactional outbox + status/result envelopes.

No docker: the service is exercised against a fake async session (same
pattern as ``test_blast_outbox.py``).  Submission must write the job row and
the outbox event in one transaction, must NOT touch the Celery broker, must
validate method / object-key namespace / parameter whitelist / upload size,
and status/result lookups must return status-aware envelopes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.task_contract import GWAS_RUN_TASK
from app.models.gwas import GwasJob, GwasJobStatus
from app.models.outbox import OutboxEvent, OutboxEventStatus
from app.schemas.gwas import GwasMethod, GwasSubmitRequest
from app.services import gwas_service as gwas_module
from app.services.gwas_service import GwasService, validate_gwas_key


class _Scalars:
    def __init__(self, items: list):
        self._items = items

    def all(self) -> list:
        return self._items


class _Result:
    def __init__(self, rows: list):
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeDbSession:
    """AsyncSession stand-in recording adds/commits for one transaction."""

    def __init__(self, job: GwasJob | None = None):
        self.job = job
        self.added: list[Any] = []
        self.commits = 0
        self.flushes = 0

    async def execute(self, stmt, params=None):
        if "gwas_jobs" in str(stmt):
            return _Result([self.job] if self.job else [])
        return _Result([])

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj) -> None:
        pass


def _make_request(**overrides: Any) -> GwasSubmitRequest:
    base = dict(
        method=GwasMethod.EMMAX,
        phenotype_object_key=f"gwas/{uuid.uuid4()}/input/{uuid.uuid4()}-trait.pheno",
    )
    base.update(overrides)
    return GwasSubmitRequest(**base)


def _make_job(status: GwasJobStatus = GwasJobStatus.PENDING) -> GwasJob:
    return GwasJob(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        method="emmax",
        object_type="snp",
        phenotype_file_path=f"gwas/{uuid.uuid4()}/input/x.pheno",
        params={"num_threads": 2},
        status=status.value,
        submitted_at=datetime.now(UTC),
    )


def _patch_upload_check(monkeypatch, size: int | None = None) -> None:
    """Make the S3 existence/size check deterministic in tests.

    ``size=None`` simulates an unreachable S3 (no error, worker enforces).
    """
    if size is None:

        def _missing(key: str) -> int:
            raise RuntimeError("S3 unreachable")

        monkeypatch.setattr(gwas_module, "get_file_size", _missing)
    else:
        monkeypatch.setattr(gwas_module, "get_file_size", lambda key: size)


async def test_submit_job_writes_job_and_outbox_event_in_one_transaction(
    monkeypatch,
) -> None:
    session = FakeDbSession()
    _patch_upload_check(monkeypatch, size=1024)
    service = GwasService()

    response = await service.submit_job(session, uuid.uuid4(), _make_request())

    assert session.commits == 1
    assert session.flushes >= 1

    job = next(obj for obj in session.added if isinstance(obj, GwasJob))
    event = next(obj for obj in session.added if isinstance(obj, OutboxEvent))
    assert job.status == GwasJobStatus.PENDING

    assert event.aggregate_type == "gwas_job"
    assert event.aggregate_id == str(job.id)
    assert event.status == OutboxEventStatus.PENDING
    assert event.attempt_count == 0
    payload = event.payload
    assert payload["task_name"] == GWAS_RUN_TASK
    assert payload["payload_version"] == 1
    assert payload["job_id"] == str(job.id)
    assert payload["idempotency_key"] == f"gwas:{job.id}"
    assert payload["payload"]["method"] == "emmax"
    assert payload["payload"]["phenotype_object_key"] == job.phenotype_file_path
    assert payload["payload"]["params"] == {}

    assert response.job_id == str(job.id)
    assert response.status.value == "pending"


async def test_submit_job_forwards_whitelisted_params(monkeypatch) -> None:
    session = FakeDbSession()
    _patch_upload_check(monkeypatch, size=1024)
    service = GwasService()

    request = _make_request(
        method=GwasMethod.GEMMA,
        params={"num_threads": 4, "max_p_value_threads": 2},
    )
    response = await service.submit_job(session, uuid.uuid4(), request)

    job = next(obj for obj in session.added if isinstance(obj, GwasJob))
    assert job.params == {"num_threads": 4, "max_p_value_threads": 2}
    assert job.method == "gemma"
    assert response.method.value == "gemma"


async def test_submit_job_rejects_unknown_parameter(monkeypatch) -> None:
    from app.core.exceptions import ValidationError

    session = FakeDbSession()
    _patch_upload_check(monkeypatch, size=1024)
    service = GwasService()

    request = _make_request(params={"evil_flag": True})
    with pytest.raises(ValidationError, match="Unknown parameter"):
        await service.submit_job(session, uuid.uuid4(), request)

    assert session.added == []
    assert session.commits == 0


async def test_submit_job_rejects_out_of_range_parameter(monkeypatch) -> None:
    from app.core.exceptions import ValidationError

    session = FakeDbSession()
    _patch_upload_check(monkeypatch, size=1024)
    service = GwasService()

    request = _make_request(params={"num_threads": 999})
    with pytest.raises(ValidationError, match="num_threads"):
        await service.submit_job(session, uuid.uuid4(), request)


async def test_submit_job_rejects_key_outside_gwas_namespace(monkeypatch) -> None:
    from app.core.exceptions import ValidationError

    session = FakeDbSession()
    _patch_upload_check(monkeypatch, size=1024)
    service = GwasService()

    request = _make_request(phenotype_object_key="analyses/abc/input/x.pheno")
    with pytest.raises(ValidationError, match="gwas/"):
        await service.submit_job(session, uuid.uuid4(), request)


async def test_submit_job_rejects_traversal_key(monkeypatch) -> None:
    from pydantic import ValidationError

    session = FakeDbSession()
    _patch_upload_check(monkeypatch, size=1024)
    service = GwasService()

    # The schema itself refuses traversal segments at request construction.
    with pytest.raises(ValidationError, match="traversal"):
        _make_request(
            phenotype_object_key="gwas/abc/input/../../etc/passwd.pheno"
        )

    # Service-level re-validation refuses the same key programmatically.
    from app.core.exceptions import ValidationError as DomainValidationError

    request = GwasSubmitRequest(
        method=GwasMethod.EMMAX,
        phenotype_object_key="gwas/abc/input/p.pheno",
    )
    # Bypass the schema shape check by swapping in a traversal key directly.
    with pytest.raises(DomainValidationError, match="traversal"):
        await service.submit_job(
            session,
            uuid.uuid4(),
            request.model_copy(
                update={
                    "phenotype_object_key": "gwas/abc/input/../../etc/passwd.pheno"
                }
            ),
        )


async def test_submit_job_rejects_oversized_upload(monkeypatch) -> None:
    from app.core.exceptions import ValidationError
    from app.services.presign import MAX_UPLOAD_SIZE

    session = FakeDbSession()
    _patch_upload_check(monkeypatch, size=MAX_UPLOAD_SIZE + 1)
    service = GwasService()

    with pytest.raises(ValidationError, match="exceeds"):
        await service.submit_job(session, uuid.uuid4(), _make_request())

    assert session.commits == 0


async def test_submit_job_schema_rejects_bad_phenotype_extension() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="phenotype file"):
        _make_request(
            phenotype_object_key=f"gwas/{uuid.uuid4()}/input/{uuid.uuid4()}-data.fastq"
        )


async def test_get_job_returns_status_and_result_when_completed() -> None:
    job = _make_job(status=GwasJobStatus.COMPLETED)
    job.result_summary = {
        "manhattan_object": "gwas/abc/output/manhattan.json",
        "qq_object": "gwas/abc/output/qq.json",
        "html_object": "gwas/abc/output/Manhattan_QQ.html",
        "n_variants": 42,
    }
    session = FakeDbSession(job=job)
    service = GwasService()

    response = await service.get_job(session, job.id, job.user_id, ["researcher"])

    assert response.status.value == "completed"
    assert response.result["n_variants"] == 42


async def test_get_job_returns_no_result_while_pending() -> None:
    session = FakeDbSession(job=_make_job(status=GwasJobStatus.PENDING))
    service = GwasService()

    response = await service.get_job(session, session.job.id, session.job.user_id, ["researcher"])

    assert response.status.value == "pending"
    assert response.result is None


async def test_get_job_unknown_id_raises_not_found() -> None:
    from app.core.exceptions import NotFoundError

    service = GwasService()
    with pytest.raises(NotFoundError):
        await service.get_job(FakeDbSession(), uuid.uuid4(), uuid.uuid4(), ["researcher"])


async def test_get_result_completed_returns_presigned_urls(monkeypatch) -> None:
    job = _make_job(status=GwasJobStatus.COMPLETED)
    # Keys are written by the worker as {job_id}/output/... (bucket is
    # prepended by the API when presigning).
    job.result_summary = {
        "manhattan_object": "abc/output/manhattan.json",
        "qq_object": "abc/output/qq.json",
        "html_object": "abc/output/Manhattan_QQ.html",
        "assoc_object": "abc/output/assoc.emmax.tsv",
        "n_variants": 7,
    }
    seen: list[str] = []
    monkeypatch.setattr(
        gwas_module,
        "generate_presigned_url",
        lambda s3_path, **kw: seen.append(s3_path) or f"https://minio/{s3_path}",
    )
    service = GwasService()

    response = await service.get_result(
        FakeDbSession(job=job), job.id, job.user_id, ["researcher"]
    )

    assert response.status.value == "completed"
    assert response.manhattan_url == "https://minio/gwas/abc/output/manhattan.json"
    assert response.report_url == "https://minio/gwas/abc/output/Manhattan_QQ.html"
    assert response.n_variants == 7
    assert len(seen) == 4
    assert all(path.startswith("gwas/abc/output/") for path in seen)


async def test_get_result_running_returns_no_urls() -> None:
    session = FakeDbSession(job=_make_job(status=GwasJobStatus.RUNNING))
    service = GwasService()

    response = await service.get_result(
        session, session.job.id, session.job.user_id, ["researcher"]
    )

    assert response.status.value == "running"
    assert response.manhattan_url is None
    assert response.report_url is None


def test_validate_gwas_key_accepts_input_key() -> None:
    key = f"gwas/{uuid.uuid4()}/input/abc.pheno"
    assert validate_gwas_key(key) == key


@pytest.mark.asyncio
async def test_gwas_reads_reject_cross_user_and_allow_owner_and_admin() -> None:
    from app.core.exceptions import AuthorizationError

    job = _make_job()
    service = GwasService()
    session = FakeDbSession(job=job)
    with pytest.raises(AuthorizationError):
        await service.get_job(session, job.id, uuid.uuid4(), ["researcher"])
    assert (await service.get_job(session, job.id, job.user_id, ["researcher"])).job_id == str(job.id)
    assert (await service.get_job(session, job.id, uuid.uuid4(), ["administrator"])).job_id == str(job.id)

    with pytest.raises(AuthorizationError):
        await service.get_result(session, job.id, uuid.uuid4(), ["researcher"])


def test_validate_gwas_key_rejects_lookalike_prefix() -> None:
    with pytest.raises(ValueError, match="gwas/"):
        validate_gwas_key("gwas-evil/abc/input/x.pheno")
    with pytest.raises(ValueError, match="gwas/"):
        validate_gwas_key("analyses/abc/input/x.pheno")
