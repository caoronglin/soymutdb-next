"""BLAST service – job submission and result retrieval."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.exceptions import NotFoundError, ValidationError
from ..core.task_contract import BLAST_RUN_TASK
from ..core.task_dispatch import dispatch_task
from ..models.blast import BlastDatabase, BlastJob, BlastJobStatus
from ..schemas.blast import (
    BlastProgram,
    BlastJobStatus as BlastSchemaJobStatus,
    BlastDatabaseResponse,
    BlastJobResponse,
    BlastResultResponse,
    BlastSubmitRequest,
)

settings = get_settings()


class BlastService:
    """BLAST job management service."""

    async def list_databases(self, db: AsyncSession) -> list[BlastDatabaseResponse]:
        result = await db.execute(
            select(BlastDatabase).where(BlastDatabase.is_active.is_(True))
        )
        return [
            BlastDatabaseResponse(
                id=bd.id,
                name=bd.name,
                db_type=bd.db_type,
                assembly_id=bd.assembly_id,
                is_active=bd.is_active,
                created_at=bd.created_at,
            )
            for bd in result.scalars().all()
        ]

    async def submit_job(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        request: BlastSubmitRequest,
    ) -> BlastJobResponse:
        """Create a BLAST job record and dispatch it to the Celery worker."""
        # Validate the database exists and is active.
        bd_result = await db.execute(
            select(BlastDatabase).where(
                BlastDatabase.id == request.database_id,
                BlastDatabase.is_active.is_(True),
            )
        )
        blast_db = bd_result.scalar_one_or_none()
        if blast_db is None:
            raise NotFoundError(
                f"BLAST database {request.database_id} not found or inactive"
            )

        if len(request.query_sequence) > settings.blast_max_length:
            raise ValidationError(
                f"Query sequence exceeds max length {settings.blast_max_length}"
            )

        job = BlastJob(
            id=uuid.uuid4(),
            user_id=user_id,
            program=request.program.value,
            database_id=request.database_id,
            query_sequence=request.query_sequence,
            parameters=request.parameters.model_dump(exclude_none=True),
            status=BlastJobStatus.PENDING,
            submitted_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        dispatch_task(
            BLAST_RUN_TASK,
            identifier=job.id,
            kwargs={
                "job_id": str(job.id),
                "program": job.program,
                "database": blast_db.name,
                "sequence": job.query_sequence,
                "evalue": request.parameters.evalue,
                "word_size": request.parameters.word_size,
                "max_target_seqs": request.parameters.max_target_seqs,
                "parameters": job.parameters,
            },
            queue="blast",
        )

        return self._job_to_response(job)

    async def get_job(self, db: AsyncSession, job_id: uuid.UUID) -> BlastJobResponse:
        result = await db.execute(select(BlastJob).where(BlastJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundError(f"BLAST job {job_id} not found")
        return self._job_to_response(job)

    async def get_result(
        self, db: AsyncSession, job_id: uuid.UUID
    ) -> BlastResultResponse:
        """Retrieve parsed BLAST results for a completed job."""
        result = await db.execute(select(BlastJob).where(BlastJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundError(f"BLAST job {job_id} not found")
        if job.status != BlastJobStatus.COMPLETED:
            raise ValidationError(f"Job {job_id} is not completed (status={job.status})")

        # In production, fetch the result file from S3 and parse it.
        return BlastResultResponse(
            job_id=str(job.id),
            program=BlastProgram(job.program),
            database_id=job.database_id,
            query_id="query",
            query_len=0,
            hits=[],
            total_hits=0,
            search_stats={},
            completed_at=job.completed_at or datetime.now(timezone.utc),
        )

    @staticmethod
    def _job_to_response(job: BlastJob) -> BlastJobResponse:
        return BlastJobResponse(
            job_id=str(job.id),
            status=BlastSchemaJobStatus(job.status),
            program=BlastProgram(job.program),
            database_id=job.database_id,
            submitted_at=job.submitted_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=job.error_message,
            result_url=job.result_path,
        )
