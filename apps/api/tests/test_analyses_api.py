"""Analyses API tests – no docker / no real MinIO.

Covers (all with mocks/fakes):
- pre-signed URL generation (PUT/GET) via ``unittest.mock`` on boto3
- object-key prefix validation (traversal / cross-job references rejected)
- job submission writing job row + outbox event in one transaction
- status lookup, download presigning, parameter whitelist
- RBAC: 401 unauthenticated, 403 viewer, 200 researcher/administrator

The HTTP-level tests build their own app with a fake database session so
they never touch testcontainers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthorizationError,
    SoyMutDBError,
    http_exception_handler,
    soy_mut_db_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.security import RoleName, create_access_token
from app.models.analysis_job import AnalysisJob, AnalysisJobStatus, AnalysisType
from app.models.auth import Role, User
from app.models.outbox import OutboxEvent, OutboxEventStatus

# ---------------------------------------------------------------------------
# Fake database session (unit-level, no docker)
# ---------------------------------------------------------------------------


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

    def __init__(self, job: AnalysisJob | None = None, user: User | None = None):
        self.job = job
        self.user = user
        self.added: list[Any] = []
        self.commits = 0
        self.flushes = 0

    async def execute(self, stmt, params=None):
        text = str(stmt)
        if "FROM users" in text:
            return _Result([self.user] if self.user else [])
        if "FROM analysis_jobs" in text:
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


def _make_user(role: RoleName = RoleName.RESEARCHER) -> User:
    return User(
        id=uuid.uuid4(),
        username="tester",
        email="tester@soymutdb.local",
        password_hash="x",
        is_active=True,
        is_deleted=False,
        role_rel=Role(id=1, name=role.value),
    )


def _make_job(
    *,
    status: AnalysisJobStatus = AnalysisJobStatus.QUEUED,
    user_id: uuid.UUID | None = None,
) -> AnalysisJob:
    now = datetime.now(UTC)
    return AnalysisJob(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        analysis_type=AnalysisType.FASTP.value,
        input_objects=[f"analyses/{uuid.uuid4()}/input/abc.fq.gz"],
        params={"thread": 4},
        status=status,
        result_summary=None,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Pre-signed URL generation and key validation (pure mocks, no S3)
# ---------------------------------------------------------------------------


class TestPresign:
    def test_generate_upload_url_put(self):
        from unittest.mock import MagicMock, patch

        from app.services.presign import generate_upload_url

        s3 = MagicMock()
        s3.generate_presigned_url.return_value = "https://minio/put"
        with patch("app.services.presign.get_s3_client", return_value=s3):
            url = generate_upload_url("analyses/j/input/a.fq.gz")
        assert url == "https://minio/put"
        s3.generate_presigned_url.assert_called_once_with(
            "put_object",
            Params={"Bucket": "analyses", "Key": "analyses/j/input/a.fq.gz"},
            ExpiresIn=3600,
        )

    def test_generate_download_url_get(self):
        from unittest.mock import MagicMock, patch

        from app.services.presign import generate_download_url

        s3 = MagicMock()
        s3.generate_presigned_url.return_value = "https://minio/get"
        with patch("app.services.presign.get_s3_client", return_value=s3):
            url = generate_download_url(
                "analyses/j/input/a.fq.gz", expires_in=600
            )
        assert url == "https://minio/get"
        s3.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "analyses", "Key": "analyses/j/input/a.fq.gz"},
            ExpiresIn=600,
        )

    def test_generate_upload_url_custom_bucket(self):
        from unittest.mock import MagicMock, patch

        from app.services.presign import generate_upload_url

        s3 = MagicMock()
        with patch("app.services.presign.get_s3_client", return_value=s3):
            generate_upload_url("analyses/j/input/a.fq.gz", bucket="other")
        assert s3.generate_presigned_url.call_args.kwargs["Params"]["Bucket"] == "other"

    def test_build_upload_key_shape(self):
        from app.services.presign import build_upload_key

        job_id = uuid.uuid4()
        key = build_upload_key(job_id, "sample_R1.fastq.gz")
        assert key.startswith(f"analyses/{job_id}/input/")
        assert key.endswith("-sample_R1.fastq.gz")

    def test_build_upload_key_sanitizes_filename(self):
        from app.services.presign import build_upload_key

        key = build_upload_key(uuid.uuid4(), "../../etc/passwd")
        assert ".." not in key
        assert key.endswith("-passwd")
        # the sanitized filename segment never contains a separator
        assert "/" not in key.rsplit("/", 1)[1]

    def test_build_upload_key_rejects_empty(self):
        from app.services.presign import build_upload_key

        with pytest.raises(ValueError):
            build_upload_key(uuid.uuid4(), "..")


class TestKeyValidation:
    def _rejects(self, key: str):
        from app.services.presign import validate_analyses_key

        with pytest.raises(ValueError):
            validate_analyses_key(key)

    def test_accepts_valid_key(self):
        from app.services.presign import validate_analyses_key

        key = "analyses/ab12/input/x.fq.gz"
        assert validate_analyses_key(key) == key

    def test_rejects_lookalike_prefix(self):
        self._rejects("analyses-evil/x.fq.gz")
        self._rejects("analysess/x.fq.gz")

    def test_rejects_outside_namespace(self):
        self._rejects("blast-results/x.json")
        self._rejects("")

    def test_rejects_absolute_and_traversal(self):
        self._rejects("/analyses/x.fq.gz")
        self._rejects("analyses/a/../b.fq.gz")
        self._rejects("analyses/a/./b.fq.gz")
        self._rejects("analyses//b.fq.gz")
        self._rejects("analyses/a/..")

    def test_job_key_rejects_cross_job(self):
        from app.services.presign import validate_job_object_key

        job_id = uuid.uuid4()
        other = uuid.uuid4()
        assert validate_job_object_key(
            f"analyses/{job_id}/input/a.fq.gz", job_id
        ) == f"analyses/{job_id}/input/a.fq.gz"
        with pytest.raises(ValueError):
            validate_job_object_key(f"analyses/{other}/input/a.fq.gz", job_id)


# ---------------------------------------------------------------------------
# Service layer: submission, lookup, download (fake session, no docker)
# ---------------------------------------------------------------------------


class TestSubmitJob:
    async def test_submit_creates_job_and_outbox_event_in_one_transaction(self):
        from app.schemas.analyses import AnalysesSubmitRequest
        from app.services.analyses_service import AnalysesService

        session = FakeDbSession(user=_make_user())
        service = AnalysesService()
        job_id = uuid.uuid4()
        request = AnalysesSubmitRequest(
            input_objects=[f"analyses/{job_id}/input/sample_R1.fastq.gz"],
            params={"thread": 8, "quality_phred": 20},
        )

        response = await service.submit_job(
            session, uuid.uuid4(), AnalysisType.FASTP, request
        )

        assert session.commits == 1
        assert response.status == "queued"
        job = next(obj for obj in session.added if isinstance(obj, AnalysisJob))
        event = next(obj for obj in session.added if isinstance(obj, OutboxEvent))
        assert job.status == AnalysisJobStatus.QUEUED
        assert job.params == {"thread": 8, "quality_phred": 20}

        assert event.aggregate_type == "analysis_job"
        assert event.aggregate_id == str(job.id)
        assert event.status == OutboxEventStatus.PENDING
        payload = event.payload
        from app.core.task_contract import ANALYSIS_FASTP_TASK

        assert payload["task_name"] == ANALYSIS_FASTP_TASK
        assert payload["payload_version"] == 1
        assert payload["idempotency_key"] == f"analyses:{job.id}"
        assert payload["payload"]["analysis_type"] == "fastp"
        assert payload["payload"]["params"] == {"thread": 8, "quality_phred": 20}

    async def test_submit_scanpy_task_name(self):
        from app.schemas.analyses import AnalysesSubmitRequest
        from app.services.analyses_service import AnalysesService

        session = FakeDbSession(user=_make_user())
        service = AnalysesService()
        request = AnalysesSubmitRequest(
            input_objects=[f"analyses/{uuid.uuid4()}/input/matrix.h5ad"],
            params={"min_genes": 200, "use_hvg": True},
        )
        await service.submit_job(session, uuid.uuid4(), AnalysisType.SCANPY, request)
        event = next(obj for obj in session.added if isinstance(obj, OutboxEvent))
        assert event.payload["task_name"] == "soymutdb_worker.tasks.analyses.run_scanpy"

    async def test_submit_rejects_key_outside_analyses(self):
        from app.core.exceptions import ValidationError
        from app.schemas.analyses import AnalysesSubmitRequest
        from app.services.analyses_service import AnalysesService

        session = FakeDbSession(user=_make_user())
        service = AnalysesService()
        request = AnalysesSubmitRequest(
            input_objects=["blast-results/evil.json"], params={}
        )
        with pytest.raises(ValidationError):
            await service.submit_job(
                session, uuid.uuid4(), AnalysisType.FASTP, request
            )
        assert session.added == []
        assert session.commits == 0

    async def test_submit_rejects_traversal_key(self):
        from app.core.exceptions import ValidationError
        from app.schemas.analyses import AnalysesSubmitRequest
        from app.services.analyses_service import AnalysesService

        session = FakeDbSession(user=_make_user())
        service = AnalysesService()
        request = AnalysesSubmitRequest(
            input_objects=["analyses/../blast-results/x.json"], params={}
        )
        with pytest.raises(ValidationError):
            await service.submit_job(
                session, uuid.uuid4(), AnalysisType.FASTP, request
            )

    async def test_submit_rejects_unknown_param(self):
        from app.core.exceptions import ValidationError
        from app.schemas.analyses import AnalysesSubmitRequest
        from app.services.analyses_service import AnalysesService

        session = FakeDbSession(user=_make_user())
        service = AnalysesService()
        request = AnalysesSubmitRequest(
            input_objects=[f"analyses/{uuid.uuid4()}/input/a.fq.gz"],
            params={"evil_flag": True},
        )
        with pytest.raises(ValidationError):
            await service.submit_job(
                session, uuid.uuid4(), AnalysisType.FASTP, request
            )
        assert session.commits == 0

    async def test_submit_rejects_out_of_range_param(self):
        from app.core.exceptions import ValidationError
        from app.schemas.analyses import AnalysesSubmitRequest
        from app.services.analyses_service import AnalysesService

        session = FakeDbSession(user=_make_user())
        service = AnalysesService()
        request = AnalysesSubmitRequest(
            input_objects=[f"analyses/{uuid.uuid4()}/input/a.fq.gz"],
            params={"thread": 0},
        )
        with pytest.raises(ValidationError):
            await service.submit_job(
                session, uuid.uuid4(), AnalysisType.FASTP, request
            )


class TestGetJob:
    async def test_get_job_pending_result_is_none(self):
        from app.services.analyses_service import AnalysesService

        job = _make_job(status=AnalysisJobStatus.QUEUED)
        session = FakeDbSession(job=job)
        response = await AnalysesService().get_job(session, job.id, job.user_id, ["researcher"])
        assert response.job_id == str(job.id)
        assert response.analysis_type.value == "fastp"
        assert response.status.value == "queued"
        assert response.result is None

    async def test_get_job_completed_result_present(self):
        from app.services.analyses_service import AnalysesService

        job = _make_job(status=AnalysisJobStatus.SUCCEEDED)
        job.result_summary = {"reads_after_trimming": 1_000_000}
        session = FakeDbSession(job=job)
        response = await AnalysesService().get_job(session, job.id, job.user_id, ["researcher"])
        assert response.status.value == "succeeded"
        assert response.result == {"reads_after_trimming": 1_000_000}

    async def test_get_job_not_found(self):
        from app.core.exceptions import NotFoundError
        from app.services.analyses_service import AnalysesService

        session = FakeDbSession(job=None)
        with pytest.raises(NotFoundError):
            await AnalysesService().get_job(session, uuid.uuid4(), uuid.uuid4(), ["researcher"])

    async def test_cross_user_analysis_status_is_forbidden(self):
        from app.services.analyses_service import AnalysesService

        job = _make_job()
        with pytest.raises(AuthorizationError):
            await AnalysesService().get_job(
                FakeDbSession(job=job), job.id, uuid.uuid4(), ["researcher"]
            )

    async def test_owner_analysis_status_is_allowed(self):
        from app.services.analyses_service import AnalysesService

        job = _make_job()
        response = await AnalysesService().get_job(
            FakeDbSession(job=job), job.id, job.user_id, ["researcher"]
        )
        assert response.job_id == str(job.id)

    async def test_administrator_can_read_other_users_analysis_status(self):
        from app.services.analyses_service import AnalysesService

        job = _make_job()
        response = await AnalysesService().get_job(
            FakeDbSession(job=job), job.id, uuid.uuid4(), ["administrator"]
        )
        assert response.job_id == str(job.id)


class TestDownloadUrl:
    async def test_download_url_ok(self):
        from unittest.mock import patch

        from app.services.analyses_service import AnalysesService

        job = _make_job()
        session = FakeDbSession(job=job)
        key = f"analyses/{job.id}/input/a.fq.gz"
        with patch(
            "app.services.analyses_service.generate_download_url",
            return_value="https://minio/get?x=1",
        ):
            response = await AnalysesService().get_download_url(
                session, job.id, key, job.user_id, ["researcher"]
            )
        assert response.download_url == "https://minio/get?x=1"
        assert response.expires_in == 600

    async def test_download_url_rejects_cross_job_key(self):
        from app.core.exceptions import ValidationError
        from app.services.analyses_service import AnalysesService

        job = _make_job()
        session = FakeDbSession(job=job)
        other_key = f"analyses/{uuid.uuid4()}/input/a.fq.gz"
        with pytest.raises(ValidationError):
            await AnalysesService().get_download_url(
                session, job.id, other_key, job.user_id, ["researcher"]
            )

    async def test_cross_user_analysis_download_is_forbidden(self):
        from app.services.analyses_service import AnalysesService

        job = _make_job()
        key = f"analyses/{job.id}/input/a.fq.gz"
        with pytest.raises(AuthorizationError):
            await AnalysesService().get_download_url(
                FakeDbSession(job=job), job.id, key, uuid.uuid4(), ["researcher"]
            )

    async def test_administrator_can_download_other_users_analysis(self):
        from unittest.mock import patch
        from app.services.analyses_service import AnalysesService

        job = _make_job()
        key = f"analyses/{job.id}/input/a.fq.gz"
        with patch(
            "app.services.analyses_service.generate_download_url",
            return_value="https://minio/get?sig=admin",
        ):
            response = await AnalysesService().get_download_url(
                FakeDbSession(job=job), job.id, key, uuid.uuid4(), ["administrator"]
            )
        assert response.download_url == "https://minio/get?sig=admin"


# ---------------------------------------------------------------------------
# HTTP layer: RBAC (401 / 403 / 200), upload endpoint, size ceiling
# ---------------------------------------------------------------------------


@pytest.fixture
async def api_app():
    """Minimal app with the full v1 router and a fake DB session."""
    from fastapi.exceptions import RequestValidationError

    from app.api.v1.router import api_router
    from app.core.database import get_db

    session = FakeDbSession(user=None)

    async def override_get_db() -> AsyncSession:
        yield session

    application = FastAPI(title="Analyses Test API")
    application.include_router(api_router, prefix="/api/v1")
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.add_exception_handler(Exception, http_exception_handler)
    application.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )
    application.add_exception_handler(Exception, unhandled_exception_handler)
    application.dependency_overrides[get_db] = override_get_db
    application.state.fake_session = session
    return application


@pytest.fixture
async def api_client(api_app):
    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_header(user: User) -> dict[str, str]:
    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}


class TestRBAC:
    async def test_unauthenticated_401(self, api_client):
        r = await api_client.get(f"/api/v1/analyses/{uuid.uuid4()}")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "authentication_failed"

    async def test_blast_status_unauthenticated_401(self, api_client):
        r = await api_client.get(f"/api/v1/blast/jobs/{uuid.uuid4()}")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "authentication_failed"

    async def test_viewer_403(self, api_client, api_app):
        user = _make_user(RoleName.VIEWER)
        api_app.state.fake_session.user = user
        r = await api_client.get(
            f"/api/v1/analyses/{uuid.uuid4()}", headers=_auth_header(user)
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "forbidden"

    async def test_researcher_allowed(self, api_client, api_app):
        user = _make_user(RoleName.RESEARCHER)
        api_app.state.fake_session.user = user
        job = _make_job(user_id=user.id)
        api_app.state.fake_session.job = job
        r = await api_client.get(
            f"/api/v1/analyses/{job.id}", headers=_auth_header(user)
        )
        assert r.status_code == 200
        body = r.json()
        assert body["job_id"] == str(job.id)
        assert body["status"] == "queued"
        assert body["result"] is None

    async def test_administrator_allowed(self, api_client, api_app):
        user = _make_user(RoleName.ADMINISTRATOR)
        api_app.state.fake_session.user = user
        api_app.state.fake_session.job = _make_job()
        r = await api_client.get(
            f"/api/v1/analyses/{api_app.state.fake_session.job.id}",
            headers=_auth_header(user),
        )
        assert r.status_code == 200

    async def test_upload_requires_auth(self, api_client):
        r = await api_client.post(
            "/api/v1/analyses/uploads",
            json={"filename": "a.fq.gz", "size": 1000, "content_type": "application/gzip"},
        )
        assert r.status_code == 401

    async def test_upload_size_over_limit_422(self, api_client, api_app):
        user = _make_user(RoleName.RESEARCHER)
        api_app.state.fake_session.user = user
        r = await api_client.post(
            "/api/v1/analyses/uploads",
            json={"filename": "big.fq.gz", "size": 500 * 1024 * 1024 + 1},
            headers=_auth_header(user),
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "validation_error"


class TestUploadEndpoint:
    async def test_upload_returns_presigned_put_url(self, api_client, api_app):
        from unittest.mock import patch

        user = _make_user(RoleName.RESEARCHER)
        api_app.state.fake_session.user = user
        with patch(
            "app.api.v1.analyses.generate_upload_url",
            return_value="https://minio/put?sig=1",
        ):
            r = await api_client.post(
                "/api/v1/analyses/uploads",
                json={
                    "filename": "sample_R1.fastq.gz",
                    "size": 12345,
                    "content_type": "application/gzip",
                },
                headers=_auth_header(user),
            )
        assert r.status_code == 200
        body = r.json()
        assert body["upload_url"] == "https://minio/put?sig=1"
        assert body["object_key"].startswith("analyses/")
        assert body["object_key"].endswith("-sample_R1.fastq.gz")
        assert body["expires_in"] == 3600

    async def test_upload_rejects_path_filename_422(self, api_client, api_app):
        user = _make_user(RoleName.RESEARCHER)
        api_app.state.fake_session.user = user
        r = await api_client.post(
            "/api/v1/analyses/uploads",
            json={"filename": "../evil.fq.gz", "size": 1000},
            headers=_auth_header(user),
        )
        assert r.status_code == 422

    async def test_submit_endpoint_201(self, api_client, api_app):
        from unittest.mock import patch

        user = _make_user(RoleName.RESEARCHER)
        api_app.state.fake_session.user = user
        key = f"analyses/{uuid.uuid4()}/input/sample.fq.gz"
        with patch(
            "app.services.analyses_service.build_job_payload"
        ) as mock_payload, patch(
            "app.services.analyses_service.create_outbox_event"
        ) as mock_outbox:
            from app.core.jobs_package import ensure_jobs_package  # noqa: F401

            mock_payload.return_value.model_dump.return_value = {"ok": True}
            r = await api_client.post(
                "/api/v1/analyses/fastp/submit",
                json={"input_objects": [key], "params": {"thread": 4}},
                headers=_auth_header(user),
            )
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "queued"
        assert uuid.UUID(body["job_id"])
        assert mock_outbox.called
        # job row was persisted through the fake session
        assert any(
            isinstance(obj, AnalysisJob)
            for obj in api_app.state.fake_session.added
        )

    async def test_submit_rejects_bad_object_key_422(self, api_client, api_app):
        user = _make_user(RoleName.RESEARCHER)
        api_app.state.fake_session.user = user
        r = await api_client.post(
            "/api/v1/analyses/fastp/submit",
            json={"input_objects": ["blast-results/x.json"], "params": {}},
            headers=_auth_header(user),
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "validation_error"

    async def test_submit_invalid_type_422(self, api_client, api_app):
        user = _make_user(RoleName.RESEARCHER)
        api_app.state.fake_session.user = user
        r = await api_client.post(
            "/api/v1/analyses/deseq/submit",
            json={"input_objects": ["analyses/x/input/a.fq.gz"], "params": {}},
            headers=_auth_header(user),
        )
        assert r.status_code == 422

    async def test_download_endpoint_rejects_cross_job_422(self, api_client, api_app):
        user = _make_user(RoleName.RESEARCHER)
        api_app.state.fake_session.user = user
        job = _make_job(user_id=user.id)
        api_app.state.fake_session.job = job
        r = await api_client.get(
            f"/api/v1/analyses/{job.id}/download",
            params={"object_key": f"analyses/{uuid.uuid4()}/input/other.fq.gz"},
            headers=_auth_header(user),
        )
        assert r.status_code == 422

    async def test_download_endpoint_ok(self, api_client, api_app):
        from unittest.mock import patch

        user = _make_user(RoleName.RESEARCHER)
        api_app.state.fake_session.user = user
        job = _make_job(user_id=user.id)
        api_app.state.fake_session.job = job
        key = f"analyses/{job.id}/input/a.fq.gz"
        with patch(
            "app.services.analyses_service.generate_download_url",
            return_value="https://minio/get?sig=1",
        ):
            r = await api_client.get(
                f"/api/v1/analyses/{job.id}/download",
                params={"object_key": key},
                headers=_auth_header(user),
            )
        assert r.status_code == 200
        body = r.json()
        assert body["download_url"] == "https://minio/get?sig=1"
        assert body["expires_in"] == 600
