"""BLAST results endpoint tests (no docker: fake async session + mocked S3).

The results envelope must be status-aware: pending/running/failed jobs carry
``hits=None`` (never a placeholder), completed jobs carry the real hit list
(empty list = genuine zero hits) plus statistics and a pre-signed download
URL for the raw MinIO object.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.core.exceptions import AuthorizationError, NotFoundError
from app.models.blast import BlastHit, BlastJob, BlastJobStatus
from app.schemas.blast import BlastResultResponse, BlastSubmitProgram
from app.services.blast_service import BlastService


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

    def first(self):
        return self._rows[0] if self._rows else None


class FakeDbSession:
    """AsyncSession stand-in serving one job row plus optional hit rows.

    Statements are routed on the SQL text so a catalog/assembly lookup can
    never be answered with the job row: answering everything with the job is
    what hides "read a catalog column off ``BlastJob``" defects.
    """

    def __init__(self, job: BlastJob | None, hits: list[BlastHit] | None = None):
        self.job: BlastJob | None = job
        self.hits = hits or []
        #: (min evalue, max bit score) returned for the aggregate query
        self.best: tuple[float, float] | None = None
        #: Catalog row the job points at (``None`` models a stale job).
        self.database = None

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "min(" in sql and "max(" in sql:
            return _Result([self.best] if self.best else [])
        if "FROM blast_hits" in sql:
            return _Result(self.hits)
        if "FROM blast_databases" in sql:
            return _Result([self.database] if self.database else [])
        if "FROM assemblies" in sql:
            assembly = getattr(self.database, "assembly", None)
            return _Result([assembly] if assembly else [])
        return _Result([self.job])

    async def scalar(self, stmt):
        return 1 if self.job is not None else 0


def _make_job(status: BlastJobStatus, *, result_path: str | None = None) -> BlastJob:
    return BlastJob(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        program=BlastSubmitProgram.BLASTP.value,
        database_id=1,
        query_sequence="ATGCAAGCTTAGCTAGGCTAGGCTAGGC",
        parameters={},
        status=status.value,
        result_path=result_path,
        error_message=(
            "Something went wrong inside the alignment step"
            if status == BlastJobStatus.FAILED
            else None
        ),
        submitted_at=datetime.now(UTC),
        started_at=datetime.now(UTC) if status == BlastJobStatus.RUNNING else None,
        completed_at=(
            datetime.now(UTC)
            if status in (BlastJobStatus.COMPLETED, BlastJobStatus.FAILED)
            else None
        ),
        expires_at=datetime.now(UTC) + timedelta(days=7),
        hit_count=2 if status == BlastJobStatus.COMPLETED else 0,
        query_len=120 if status == BlastJobStatus.COMPLETED else None,
    )


def _make_hit(job_id: uuid.UUID, hsp_num: int = 1) -> BlastHit:
    return BlastHit(
        job_id=job_id,
        hsp_num=hsp_num,
        subject_id=f"Glyma.01G000100.{hsp_num}",
        subject_title="soybean gene",
        percent_identity=98.5,
        alignment_length=120,
        mismatches=1,
        gap_opens=1,
        query_start=1,
        query_end=120,
        subject_start=10,
        subject_end=129,
        evalue=1e-40,
        bit_score=200.5,
        query_strand="plus",
        subject_strand="plus",
    )


class TestResultsEnvelope:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("program", ["blastp", "blastn", "blastx", "tblastn", "tblastx"])
    @pytest.mark.parametrize("query", [">q\nMKTIIA*", ">q\nMKTIIA\n>q\nMKTIIA", ">empty\n"])
    async def test_historical_queries_and_lengths_survive_service_read(
        self, program: str, query: str
    ) -> None:
        job = _make_job(BlastJobStatus.COMPLETED)
        job.program = program
        job.query_sequence = query
        job.query_len = 7  # historical stop-inclusive length; never recompute
        session = FakeDbSession(job)
        service = BlastService()
        detail = await service.get_job(session, job.id, job.user_id, ["researcher"])
        result = await service.get_result(session, job.id, job.user_id, ["researcher"])
        assert detail.query_sequence == query
        assert detail.program.value == program
        assert result.program.value == program
        assert result.query_len == 7
        assert result.status.value == "completed"

    async def _get(self, session: FakeDbSession, job_id: uuid.UUID):
        user_id = session.job.user_id if session.job is not None else uuid.uuid4()
        return await BlastService().get_result(session, job_id, user_id, ["researcher"])

    @pytest.mark.asyncio
    async def test_pending_job_returns_status_without_hits(self) -> None:
        job = _make_job(BlastJobStatus.PENDING)
        session = FakeDbSession(job)
        response = await self._get(session, job.id)
        assert isinstance(response, BlastResultResponse)
        assert response.status.value == "pending"
        assert response.hits is None
        assert response.total_hits is None
        assert response.search_stats is None
        assert response.error_message is None
        assert response.download_url is None

    @pytest.mark.asyncio
    async def test_running_job_returns_status_without_hits(self) -> None:
        job = _make_job(BlastJobStatus.RUNNING)
        session = FakeDbSession(job)
        response = await self._get(session, job.id)
        assert response.status.value == "running"
        assert response.hits is None
        assert response.download_url is None

    @pytest.mark.asyncio
    async def test_failed_job_returns_sanitized_error(self) -> None:
        job = _make_job(BlastJobStatus.FAILED)
        session = FakeDbSession(job)
        response = await self._get(session, job.id)
        assert response.status.value == "failed"
        assert response.hits is None
        assert response.error_message is not None
        assert "alignment" in response.error_message
        assert response.completed_at is not None

    @pytest.mark.asyncio
    async def test_missing_job_raises_not_found(self) -> None:
        job = _make_job(BlastJobStatus.PENDING)
        session = FakeDbSession(job)
        session.job = None  # simulate missing row
        with pytest.raises(NotFoundError):
            await self._get(session, job.id)

    @pytest.mark.asyncio
    @patch("app.services.blast_service.generate_presigned_url")
    async def test_completed_job_returns_real_hits_and_download_url(self, mock_presign) -> None:
        mock_presign.return_value = "https://minio.example/presigned-raw"
        job = _make_job(BlastJobStatus.COMPLETED, result_path="blast-results/x.json")
        session = FakeDbSession(job, hits=[_make_hit(job.id, 1), _make_hit(job.id, 2)])
        session.best = (1e-40, 200.5)

        response = await self._get(session, job.id)

        assert response.status.value == "completed"
        assert response.query_len == 120
        assert response.total_hits == 2
        assert response.hits is not None and len(response.hits) == 2
        first = response.hits[0]
        assert first.subject_id == "Glyma.01G000100.1"
        assert first.evalue == 1e-40
        assert first.bit_score == 200.5
        assert first.percent_identity == 98.5
        assert response.search_stats == {
            "total_hits": 2,
            "hits_returned": 2,
            "best_evalue": 1e-40,
            "best_bitscore": 200.5,
        }
        assert response.download_url == "https://minio.example/presigned-raw"
        # Raw object key contains the job id; presigned URL generated from it.
        call_s3_path = mock_presign.call_args.args[0]
        assert call_s3_path.endswith("blast-results/x.json")

    @pytest.mark.asyncio
    @patch("app.services.blast_service.generate_presigned_url")
    async def test_completed_job_with_zero_hits_is_not_a_placeholder(self, mock_presign) -> None:
        mock_presign.return_value = "https://minio.example/presigned-raw"
        job = _make_job(BlastJobStatus.COMPLETED, result_path="blast-results/x.json")
        job.hit_count = 0
        session = FakeDbSession(job, hits=[])  # genuine zero-hit result
        session.best = None

        response = await self._get(session, job.id)

        assert response.status.value == "completed"
        assert response.hits == []
        assert response.total_hits == 0
        assert response.search_stats is not None
        assert response.search_stats["total_hits"] == 0

    @pytest.mark.asyncio
    async def test_pagination_passes_limit_and_offset(self) -> None:
        job = _make_job(BlastJobStatus.COMPLETED, result_path="blast-results/x.json")
        session = FakeDbSession(job, hits=[_make_hit(job.id, 1)])
        session.best = (1e-40, 200.5)
        with patch("app.services.blast_service.generate_presigned_url") as mock_p:
            mock_p.return_value = "https://x"
            response = await BlastService().get_result(
                session, job.id, job.user_id, ["researcher"], limit=10, offset=20
            )
        assert response.total_hits == 2  # from job.hit_count, not the page
        assert len(response.hits or []) == 1


class TestBlastOwnership:
    @pytest.mark.asyncio
    async def test_cross_user_blast_status_is_forbidden(self) -> None:
        job = _make_job(BlastJobStatus.PENDING)
        session = FakeDbSession(job)
        with pytest.raises(AuthorizationError):
            await BlastService().get_job(session, job.id, uuid.uuid4(), ["researcher"])

    @pytest.mark.asyncio
    async def test_owner_blast_status_is_allowed(self) -> None:
        job = _make_job(BlastJobStatus.PENDING)
        session = FakeDbSession(job)
        response = await BlastService().get_job(session, job.id, job.user_id, ["researcher"])
        assert response.job_id == str(job.id)

    @pytest.mark.asyncio
    async def test_administrator_can_read_other_users_blast_results(self) -> None:
        job = _make_job(BlastJobStatus.PENDING)
        session = FakeDbSession(job)
        response = await BlastService().get_result(session, job.id, uuid.uuid4(), ["administrator"])
        assert response.job_id == str(job.id)

    @pytest.mark.asyncio
    async def test_cross_user_blast_results_are_forbidden(self) -> None:
        job = _make_job(BlastJobStatus.PENDING)
        with pytest.raises(AuthorizationError):
            await BlastService().get_result(
                FakeDbSession(job), job.id, uuid.uuid4(), ["researcher"]
            )

    @pytest.mark.asyncio
    async def test_job_list_returns_normalized_portal_fields(self) -> None:
        job = _make_job(BlastJobStatus.COMPLETED)
        response = await BlastService().list_jobs(
            FakeDbSession(job), job.user_id, ["researcher"], page=1, page_size=5
        )
        assert response.total == 1
        assert response.items[0].job_id == str(job.id)
        assert response.items[0].query_sequence == job.query_sequence
        assert response.items[0].hit_count == 2
