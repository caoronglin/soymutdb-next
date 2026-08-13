"""GWAS job service – submission, status lookup, result presigning.

Submission follows the established J0 pattern (identical to BLAST/analyses):
the ``gwas_jobs`` row and the transactional-outbox event are written in the
**same database transaction**, so submission never depends on the Celery
broker being reachable.  A background dispatcher forwards the event
afterwards; the worker (``soymutdb_worker.tasks.gwas.run_gwas``) advances the
status and stores the outputs under ``gwas/{job_id}/output/`` in MinIO.

Object keys are re-validated here (defense in depth): every input must live
under ``gwas/`` and contain a ``/input/`` segment, and — when S3 is
reachable — the uploaded objects are checked for existence and size before
the job is accepted (the worker re-checks sizes when it downloads).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.exceptions import AuthorizationError, NotFoundError, ValidationError
from ..core.security import RoleName, has_role
from ..core.task_contract import GWAS_RUN_TASK
from ..models.gwas import GwasJob, GwasJobStatus
from ..schemas.gwas import (
    GwasFileType as GwasSchemaFileType,
)
from ..schemas.gwas import (
    GwasJobResponse,
    GwasResultResponse,
    GwasSubmitRequest,
)
from ..schemas.gwas import GwasJobStatus as GwasSchemaJobStatus
from ..schemas.gwas import GwasMethod as GwasSchemaMethod
from ..services.presign import (
    MAX_UPLOAD_SIZE,
    UPLOAD_EXPIRES_IN,
    generate_upload_url,
    sanitize_filename,
)
from ..utils.s3 import generate_presigned_url, get_file_size
from .job_service import build_job_payload
from .outbox_service import create_outbox_event

settings = get_settings()

#: Object-key namespace for GWAS inputs; every key must start with this exact
#: segment (trailing slash boundary enforced).
GWAS_PREFIX: str = "gwas"

#: Sanitized filename charset – keeps generated keys predictable.
_FILENAME_RE = re.compile(r"[^A-Za-z0-9._+-]+")

#: Parameter whitelist: name → (type, minimum, maximum).  Unknown keys are
#: rejected outright; values are range-checked here and stored verbatim in
#: the job's ``params`` JSONB for the worker.
_PARAM_SPECS: dict[str, tuple[type, Any, Any]] = {
    "num_threads": (int, 1, 64),
    "max_p_value_threads": (int, 1, 64),
    "max_permutations": (int, 0, 1_000_000),
}

#: Maximum delivery attempts per GWAS job (broker-level retries only; the
#: worker itself is idempotent on top of this).
_GWAS_MAX_ATTEMPTS: int = 3

#: Maximum characters of error text exposed to clients.
_MAX_ERROR_LEN = 2000


def _sanitize_error(message: str | None) -> str | None:
    """Trim error text for client responses (printable chars only)."""
    if not message:
        return None
    clean = "".join(ch for ch in message if ch.isprintable() or ch in "\n\t")
    return clean.strip()[:_MAX_ERROR_LEN] or None


def build_upload_key(job_id: str | uuid.UUID, filename: str) -> str:
    """Build the object key for a new GWAS input upload.

    Shape: ``gwas/{job_id}/input/{uuid}-{sanitized-filename}``.  The random
    prefix guarantees key uniqueness and makes the filename opaque.
    """
    name = sanitize_filename(filename)
    return f"{GWAS_PREFIX}/{job_id}/input/{uuid.uuid4()}-{name}"


def validate_gwas_key(object_key: str) -> str:
    """Validate an object key against the ``gwas/`` namespace.

    Rejects keys outside ``gwas/`` (including look-alike prefixes such as
    ``gwas-evil/...``), absolute paths, empty segments, traversal segments
    (``.`` / ``..``) and keys without an ``/input/`` segment.  Returns the
    key unchanged on success, raises :class:`ValueError` otherwise.
    """
    if not object_key or object_key.startswith("/"):
        raise ValueError("object_key must not be empty or absolute")
    if "//" in object_key:
        raise ValueError("object_key must not contain empty segments")
    segments = object_key.split("/")
    if any(seg in {"", ".", ".."} for seg in segments):
        raise ValueError("object_key must not contain traversal segments")
    if not object_key.startswith(f"{GWAS_PREFIX}/"):
        raise ValueError(f"object_key must live under '{GWAS_PREFIX}/'")
    if "/input/" not in object_key:
        raise ValueError("object_key must contain an '/input/' segment")
    return object_key


class GwasService:
    """GWAS job management service."""

    # -- upload presigning -------------------------------------------------

    def create_upload(self, filename: str) -> dict[str, Any]:
        """Return a pre-signed PUT URL + object key (stateless, nothing persisted)."""
        job_id = uuid.uuid4()
        object_key = build_upload_key(job_id, filename)
        upload_url = generate_upload_url(object_key, expires_in=UPLOAD_EXPIRES_IN)
        return {
            "upload_url": upload_url,
            "object_key": object_key,
            "expires_in": UPLOAD_EXPIRES_IN,
            "max_upload_size": MAX_UPLOAD_SIZE,
        }

    # -- submission --------------------------------------------------------

    @staticmethod
    def _check_uploaded_objects(request: GwasSubmitRequest) -> None:
        """Best-effort existence + size check of the uploaded input objects.

        When S3 is reachable, every referenced object must exist and stay
        under ``MAX_UPLOAD_SIZE`` (the worker re-checks sizes at download
        time, so an unavailable S3 endpoint never blocks submission).
        """
        for key in (
            request.phenotype_object_key,
            request.genotype_object_key,
            request.kinship_object_key,
            request.covariate_object_key,
        ):
            if key is None:
                continue
            try:
                size = get_file_size(f"{settings.s3_gwas_bucket}/{key}")
            except Exception:
                # S3 unreachable or object missing: the worker will fail the
                # job with a clear error instead of blocking submission.
                continue
            if size > MAX_UPLOAD_SIZE:
                raise ValidationError(
                    f"Input file {key!r} exceeds the {MAX_UPLOAD_SIZE}-byte limit"
                )

    async def submit_job(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        request: GwasSubmitRequest,
    ) -> GwasJobResponse:
        """Create a GWAS job and queue its dispatch via the transactional outbox.

        Business record + outbox event are committed atomically; no Celery
        broker round-trip happens inside this transaction.
        """
        # Re-validate every object key at the service boundary.
        for key in (
            request.phenotype_object_key,
            request.genotype_object_key,
            request.kinship_object_key,
            request.covariate_object_key,
        ):
            if key is None:
                continue
            try:
                validate_gwas_key(key)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc

        clean_params = self._validate_params(request.params)
        self._check_uploaded_objects(request)

        job = GwasJob(
            id=uuid.uuid4(),
            user_id=user_id,
            method=request.method.value,
            object_type=request.object_type.value,
            phenotype_file_path=request.phenotype_object_key,
            genotype_file_path=request.genotype_object_key,
            kinship_file_path=request.kinship_object_key,
            covariate_file_path=request.covariate_object_key,
            params=clean_params,
            status=GwasJobStatus.PENDING,
            submitted_at=datetime.now(UTC),
        )
        db.add(job)
        await db.flush()

        job_payload = build_job_payload(
            job_id=job.id,
            task_name=GWAS_RUN_TASK,
            payload={
                "job_id": str(job.id),
                "method": job.method,
                "object_type": job.object_type,
                "phenotype_object_key": job.phenotype_file_path,
                "genotype_object_key": job.genotype_file_path,
                "kinship_object_key": job.kinship_file_path,
                "covariate_object_key": job.covariate_file_path,
                "params": clean_params,
            },
            idempotency_key=f"gwas:{job.id}",
            max_attempts=_GWAS_MAX_ATTEMPTS,
        )
        await create_outbox_event(
            db,
            aggregate_type="gwas_job",
            aggregate_id=str(job.id),
            event_type="gwas_job.run",
            payload=job_payload.model_dump(mode="json"),
        )

        await db.commit()
        await db.refresh(job)

        return self._job_to_response(job)

    @staticmethod
    def _validate_params(params: dict[str, Any]) -> dict[str, Any]:
        """Return only whitelisted, range-checked parameters.

        Raises :class:`ValidationError` for unknown keys or out-of-range
        values (mirrors ``analyses_service._validate_params``).
        """
        clean: dict[str, Any] = {}
        for name, value in params.items():
            spec = _PARAM_SPECS.get(name)
            if spec is None:
                raise ValidationError(
                    f"Unknown parameter {name!r} for GWAS; "
                    f"allowed: {sorted(_PARAM_SPECS)}"
                )
            param_type, lo, hi = spec
            if not isinstance(value, param_type) or (
                isinstance(value, bool) and param_type is not bool
            ):
                raise ValidationError(
                    f"Parameter {name!r} must be of type {param_type.__name__}"
                )
            if lo is not None and value < lo:
                raise ValidationError(f"Parameter {name!r} must be >= {lo}")
            if hi is not None and value > hi:
                raise ValidationError(f"Parameter {name!r} must be <= {hi}")
            clean[name] = value
        return clean

    # -- status / results --------------------------------------------------

    async def get_job(self, db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID, user_roles: list[str]) -> GwasJobResponse:
        result = await db.execute(select(GwasJob).where(GwasJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundError(f"GWAS job {job_id} not found")
        self._authorize_job(job.user_id, user_id, user_roles)
        return self._job_to_response(job)

    async def get_result(
        self, db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID, user_roles: list[str]
    ) -> GwasResultResponse:
        """Return the status-aware result envelope for a GWAS job.

        Non-completed jobs carry no URLs; completed jobs get pre-signed
        download URLs for the Manhattan data JSON, the QQ data JSON and the
        self-contained ``Manhattan_QQ.html`` report.
        """
        result = await db.execute(select(GwasJob).where(GwasJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundError(f"GWAS job {job_id} not found")
        self._authorize_job(job.user_id, user_id, user_roles)

        base = GwasResultResponse(
            job_id=str(job.id),
            method=GwasSchemaMethod(job.method),
            status=GwasSchemaJobStatus(job.status),
            error_message=_sanitize_error(job.error_message),
            completed_at=job.completed_at,
        )

        if job.status != GwasJobStatus.COMPLETED or not job.result_summary:
            return base

        summary = job.result_summary
        bucket = settings.s3_gwas_bucket

        def _url(key: str | None) -> str | None:
            if not key:
                return None
            return generate_presigned_url(f"{bucket}/{key}", expires_in=3600)

        return GwasResultResponse(
            job_id=str(job.id),
            method=GwasSchemaMethod(job.method),
            status=GwasSchemaJobStatus(job.status),
            manhattan_url=_url(summary.get("manhattan_object")),
            qq_url=_url(summary.get("qq_object")),
            report_url=_url(summary.get("html_object")),
            assoc_url=_url(summary.get("assoc_object")),
            n_variants=summary.get("n_variants"),
            error_message=None,
            completed_at=job.completed_at,
        )

    @staticmethod
    def _authorize_job(owner_id, user_id, user_roles) -> None:
        if owner_id != user_id and not has_role(user_roles, RoleName.ADMINISTRATOR):
            raise AuthorizationError("You do not have permission to access this GWAS job")

    @staticmethod
    def _job_to_response(job: GwasJob) -> GwasJobResponse:
        return GwasJobResponse(
            job_id=str(job.id),
            method=GwasSchemaMethod(job.method),
            status=GwasSchemaJobStatus(job.status),
            object_type=GwasSchemaFileType(job.object_type),
            submitted_at=job.submitted_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=_sanitize_error(job.error_message),
            result=job.result_summary if job.status == GwasJobStatus.COMPLETED else None,
        )


__all__ = [
    "GWAS_PREFIX",
    "GwasService",
    "build_upload_key",
    "validate_gwas_key",
]
