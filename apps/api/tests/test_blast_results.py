"""BLAST results endpoint tests (no docker: fake async session + mocked S3).

The results envelope must be status-aware: pending/running/failed jobs carry
``hits=None`` (never a placeholder), completed jobs carry the real hit list
(empty list = genuine zero hits) plus statistics and a pre-signed download
URL for the raw MinIO object.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.core.exceptions import NotFoundError
from app.models.blast import BlastHit, BlastJob, BlastJobStatus
from app.schemas.blast import BlastProgram, BlastResultResponse
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
    """AsyncSession stand-in serving one job row plus optional hit rows."""

    def __init__(self, job: BlastJob | None, hits: list[BlastHit] | None = None):
        self.job: BlastJob | None = job
        self.hits = hits or []
        #: (min evalue, max bit score) returned for the aggregate query
        self.best: tuple[float, float] | None = None

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "min(" in sql and "max(" in sql:
            return _Result([self.best] if self.best else [])
        if "blast_hits" in sql:
            return _Result(self.hits)
        return _Result([self.job])


def _make_job(status: BlastJobStatus, *, result_path: str | None = None) -> BlastJob:
    return BlastJob(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        program=BlastProgram.BLASTN.value,
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
        expires_at=datetime.now(UTC),
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
    async def _get(self, session: FakeDbSession, job_id: uuid.UUID):
        return await BlastService().get_result(session, job_id)

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
    async def test_completed_job_returns_real_hits_and_download_url(
        self, mock_presign
    ) -> None:
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
    async def test_completed_job_with_zero_hits_is_not_a_placeholder(
        self, mock_presign
    ) -> None:
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
                session, job.id, limit=10, offset=20
            )
        assert response.total_hits == 2  # from job.hit_count, not the page
        assert len(response.hits or []) == 1
