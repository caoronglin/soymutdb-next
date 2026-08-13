"""Analyses job service – submission, status lookup, download presigning.

Submission writes the ``analysis_jobs`` row and a transactional-outbox event
in the **same database transaction** (the established J0 pattern, identical
to ``BlastService.submit_job``): no Celery broker round-trip happens inside
the transaction.  The background dispatcher forwards the event afterwards;
until the worker registers the analyses tasks (W1-C/D), events simply wait
in the outbox and submission still succeeds.

Object keys are re-validated here (defense in depth): every input object must
live under ``analyses/`` and downloads under the requesting job's own prefix
``analyses/{job_id}/``.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.exceptions import AuthorizationError, NotFoundError, ValidationError
from ..core.security import RoleName, has_role
from ..core.jobs_package import ensure_jobs_package  # noqa: F401  (sys.path bootstrap)
from ..core.task_contract import ANALYSIS_FASTP_TASK, ANALYSIS_SCANPY_TASK
from ..models.analysis_job import AnalysisJob, AnalysisJobStatus, AnalysisType
from ..schemas.analyses import (
    AnalysesDownloadResponse,
    AnalysesJobListResponse,
    AnalysesJobResponse,
    AnalysesSubmitRequest,
    AnalysesSubmitResponse,
)
from ..schemas.analyses import (
    AnalysisJobStatus as AnalysisJobStatusSchema,
)
from ..schemas.analyses import (
    AnalysisType as AnalysisTypeSchema,
)
from ..services.presign import (
    DOWNLOAD_EXPIRES_IN,
    generate_download_url,
    validate_analyses_key,
    validate_job_object_key,
)
from .job_service import build_job_payload
from .outbox_service import create_outbox_event

settings = get_settings()

# ---------------------------------------------------------------------------
# Task contract (W1-A owned – we only consume the constants).
# ---------------------------------------------------------------------------
_ANALYSES_TASKS: dict[AnalysisType, str] = {
    AnalysisType.FASTP: ANALYSIS_FASTP_TASK,
    AnalysisType.SCANPY: ANALYSIS_SCANPY_TASK,
}

#: Parameter whitelist: name → (type, minimum, maximum).  Unknown keys are
#: rejected outright; values are range-checked here and stored verbatim in
#: the job's ``params`` JSONB for the worker.
_PARAM_SPECS: dict[AnalysisType, dict[str, tuple[type, Any, Any]]] = {
    AnalysisType.FASTP: {
        "trim_front1": (int, 0, 1000),
        "trim_tail1": (int, 0, 1000),
        "quality_phred": (int, 0, 40),
        "thread": (int, 1, 64),
    },
    AnalysisType.SCANPY: {
        "min_genes": (int, 1, 100_000),
        "min_cells": (int, 1, 1_000_000),
        "n_top_genes": (int, 1, 100_000),
        "resolution": (float, 0.1, 10.0),
        "use_hvg": (bool, None, None),
    },
}

#: Maximum delivery attempts per analysis job (broker-level retries only).
_ANALYSES_MAX_ATTEMPTS: int = 3


def _validate_params(
    analysis_type: AnalysisType, params: dict[str, Any]
) -> dict[str, Any]:
    """Return only whitelisted, range-checked parameters.

    Raises :class:`ValidationError` for unknown keys or out-of-range values.
    """
    specs = _PARAM_SPECS[analysis_type]
    clean: dict[str, Any] = {}
    for name, value in params.items():
        spec = specs.get(name)
        if spec is None:
            raise ValidationError(
                f"Unknown parameter {name!r} for {analysis_type.value}; "
                f"allowed: {sorted(specs)}"
            )
        param_type, lo, hi = spec
        if not isinstance(value, param_type) or isinstance(value, bool) and param_type is not bool:
            raise ValidationError(
                f"Parameter {name!r} must be of type {param_type.__name__}"
            )
        if lo is not None and value < lo:
            raise ValidationError(f"Parameter {name!r} must be >= {lo}")
        if hi is not None and value > hi:
            raise ValidationError(f"Parameter {name!r} must be <= {hi}")
        clean[name] = value
    return clean


class AnalysesService:
    """Analysis job management service."""

    async def submit_job(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        analysis_type: AnalysisType,
        request: AnalysesSubmitRequest,
    ) -> AnalysesSubmitResponse:
        """Create an analysis job and queue dispatch via the transactional outbox.

        Business record + outbox event are committed atomically; the Celery
        broker is never touched inside this transaction.
        """
        for key in request.input_objects:
            try:
                validate_analyses_key(key)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc

        clean_params = _validate_params(analysis_type, request.params)

        job = AnalysisJob(
            id=uuid.uuid4(),
            user_id=user_id,
            analysis_type=analysis_type.value,
            input_objects=list(request.input_objects),
            params=clean_params,
            status=AnalysisJobStatus.QUEUED,
        )
        db.add(job)
        await db.flush()

        job_payload = build_job_payload(
            job_id=job.id,
            task_name=_ANALYSES_TASKS[analysis_type],
            payload={
                "job_id": str(job.id),
                "analysis_type": analysis_type.value,
                "input_objects": list(request.input_objects),
                "params": clean_params,
            },
            idempotency_key=f"analyses:{job.id}",
            max_attempts=_ANALYSES_MAX_ATTEMPTS,
        )
        await create_outbox_event(
            db,
            aggregate_type="analysis_job",
            aggregate_id=str(job.id),
            event_type=f"analysis_job.{analysis_type.value}.run",
            payload=job_payload.model_dump(mode="json"),
        )

        await db.commit()
        await db.refresh(job)

        return AnalysesSubmitResponse(job_id=str(job.id), status="queued")

    async def get_job(
        self, db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID | None = None, user_roles: list[str] | None = None
    ) -> AnalysesJobResponse:
        result = await db.execute(select(AnalysisJob).where(AnalysisJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundError(f"Analysis job {job_id} not found")
        self._authorize_job(job.user_id, user_id, user_roles)
        return self._job_to_response(job)

    async def list_jobs(
        self, db: AsyncSession, user_id: uuid.UUID, limit: int
    ) -> AnalysesJobListResponse:
        """Return the current user's most recent jobs, newest first.

        Only the caller's own jobs are visible (``user_id`` filter); the
        public list endpoint never exposes other users' analyses.
        """
        result = await db.execute(
            select(AnalysisJob)
            .where(AnalysisJob.user_id == user_id)
            .order_by(AnalysisJob.created_at.desc())
            .limit(limit)
        )
        jobs = result.scalars().all()
        return AnalysesJobListResponse(
            items=[self._job_to_response(job) for job in jobs]
        )

    async def get_download_url(
        self,
        db: AsyncSession,
        job_id: uuid.UUID,
        object_key: str,
        user_id: uuid.UUID | None = None,
        user_roles: list[str] | None = None,
    ) -> AnalysesDownloadResponse:
        """Return a pre-signed GET URL for one of the job's own objects.

        The key must be under ``analyses/{job_id}/`` – cross-job references
        are rejected before any presigning happens.
        """
        result = await db.execute(select(AnalysisJob).where(AnalysisJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundError(f"Analysis job {job_id} not found")
        self._authorize_job(job.user_id, user_id, user_roles)

        try:
            validate_job_object_key(object_key, job.id)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        download_url = generate_download_url(
            object_key, expires_in=DOWNLOAD_EXPIRES_IN
        )
        return AnalysesDownloadResponse(
            download_url=download_url, expires_in=DOWNLOAD_EXPIRES_IN
        )

    @staticmethod
    def _authorize_job(owner_id, user_id, user_roles) -> None:
        if owner_id != user_id and not has_role(user_roles, RoleName.ADMINISTRATOR):
            raise AuthorizationError("You do not have permission to access this analysis job")

    @staticmethod
    def _job_to_response(job: AnalysisJob) -> AnalysesJobResponse:
        result = (
            job.result_summary
            if job.status == AnalysisJobStatus.SUCCEEDED
            else None
        )
        return AnalysesJobResponse(
            job_id=str(job.id),
            analysis_type=AnalysisTypeSchema(job.analysis_type),
            status=AnalysisJobStatusSchema(job.status),
            error_message=job.error_message,
            result=result,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
