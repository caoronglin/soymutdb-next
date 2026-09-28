"""BLAST service – job submission and result retrieval.

Job submission writes the BLAST job row and a transactional-outbox event in
the **same database transaction**, so submission no longer depends on the
Celery broker being reachable.  A background dispatcher forwards the event
to the worker afterwards.

Results are stored by the worker in two places: the parsed hits land in the
``blast_hits`` table (via migration 0008) and the raw output file goes to
MinIO under ``blast-results/{job_id}.json``.  :meth:`get_result` returns a
status-aware envelope: pending/running/failed jobs carry no hit list (never a
placeholder), completed jobs carry the real hits plus a pre-signed download
URL for the raw output.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.exceptions import AuthorizationError, NotFoundError, ValidationError
from ..core.security import RoleName, has_role
from ..core.task_contract import BLAST_RUN_TASK
from ..models.blast import BlastDatabase, BlastDbType, BlastHit, BlastJob, BlastJobStatus
from ..models.genomic import Assembly
from ..schemas.blast import (
    BlastDatabaseResponse,
    BlastJobListResponse,
    BlastJobResponse,
    BlastParameters,
    BlastProgram,
    BlastResultResponse,
    BlastSubmitRequest,
    validate_sequence_charset,
)
from ..schemas.blast import (
    BlastHit as BlastHitSchema,
)
from ..schemas.blast import (
    BlastJobStatus as BlastSchemaJobStatus,
)
from ..utils.s3 import generate_presigned_url
from .job_service import build_job_payload
from .outbox_service import create_outbox_event
from .release_context import ReleaseContext

settings = get_settings()

#: Which database types each program may search against (db_type whitelist).
_PROGRAM_DB_TYPES: dict[BlastProgram, frozenset[str]] = {
    BlastProgram.BLASTN: frozenset({BlastDbType.NUCL.value}),
    BlastProgram.BLASTP: frozenset({BlastDbType.PROT.value}),
    BlastProgram.BLASTX: frozenset({BlastDbType.PROT.value}),
    BlastProgram.TBLASTN: frozenset({BlastDbType.NUCL.value}),
    BlastProgram.TBLASTX: frozenset({BlastDbType.NUCL.value}),
}

#: Client-facing parameter names → worker whitelisted CLI names.  ``evalue``,
#: ``word_size`` and ``max_target_seqs`` travel as top-level payload keys (the
#: worker reads them directly), so they are intentionally absent here.
_PARAMETER_NAME_MAP: dict[str, str] = {
    "gap_open": "gapopen",
    "gap_extend": "gapextend",
    "matrix": "matrix",
    "dust": "dust",
    "soft_masking": "soft_masking",
}

#: Maximum characters of error text exposed to clients.
_MAX_ERROR_LEN = 2000


def _sanitize_error(message: str | None) -> str | None:
    """Trim error text for client responses (printable chars only)."""
    if not message:
        return None
    clean = "".join(ch for ch in message if ch.isprintable() or ch in "\n\t")
    return clean.strip()[:_MAX_ERROR_LEN] or None


def _worker_parameters(params: BlastParameters) -> dict:
    """Map validated request parameters to worker-whitelisted CLI parameters.

    ``percent_identity`` is a client-side filter only and is intentionally
    dropped (the worker rejects unknown parameter keys).  Boolean flags are
    rendered as ``yes``/``no`` for the BLAST CLI.
    """
    out: dict = {}
    if params.gap_open is not None:
        out["gapopen"] = params.gap_open
    if params.gap_extend is not None:
        out["gapextend"] = params.gap_extend
    if params.matrix:
        out["matrix"] = params.matrix
    if params.dust is not None:
        out["dust"] = "yes" if params.dust else "no"
    if params.soft_masking is not None:
        out["soft_masking"] = "yes" if params.soft_masking else "no"
    return out


class BlastService:
    """BLAST job management service."""

    async def list_databases(
        self,
        db: AsyncSession,
        *,
        release_context: ReleaseContext,
    ) -> list[BlastDatabaseResponse]:
        """List active databases whose assembly is in the published release.

        Without the release join this listed every active row, including the
        databases of draft releases whose data has not been published.
        """
        result = await db.execute(
            select(BlastDatabase)
            .join(Assembly, BlastDatabase.assembly_id == Assembly.id)
            .where(
                BlastDatabase.is_active.is_(True),
                Assembly.release_id == release_context.release_id,
            )
        )
        rows: list[BlastDatabaseResponse] = []
        for bd in result.scalars().all():
            # ``BlastDatabase.assembly`` is lazy="joined", so it is loaded
            # together with each row (guard with getattr for detached rows).
            assembly = getattr(bd, "assembly", None)
            rows.append(
                BlastDatabaseResponse(
                    id=bd.id,
                    name=bd.name,
                    db_type=bd.db_type,
                    assembly_id=bd.assembly_id,
                    is_active=bd.is_active,
                    created_at=bd.created_at,
                    assembly_name=assembly.name if assembly is not None else None,
                    assembly_version=(
                        assembly.version if assembly is not None else None
                    ),
                    assembly_is_default=(
                        assembly.is_default if assembly is not None else None
                    ),
                    release_id=(
                        assembly.release_id if assembly is not None else None
                    ),
                )
            )
        return rows

    @staticmethod
    async def _get_active_database(
        db: AsyncSession,
        release_context: ReleaseContext,
        *conditions: ColumnElement[bool],
    ) -> BlastDatabase | None:
        """Fetch one active database row in the published release.

        The active ``blast_databases`` rows of the *resolved release* are the
        database whitelist: anything not matching is refused here (defense in
        depth on top of the schema-level name format check). The release join
        is what stops a job from targeting another release's database.
        """
        result = await db.execute(
            select(BlastDatabase)
            .join(Assembly, BlastDatabase.assembly_id == Assembly.id)
            .where(
                BlastDatabase.is_active.is_(True),
                Assembly.release_id == release_context.release_id,
                *conditions,
            )
        )
        return result.scalar_one_or_none()

    async def _resolve_database(
        self,
        db: AsyncSession,
        request: BlastSubmitRequest,
        *,
        release_context: ReleaseContext,
    ) -> BlastDatabase:
        """Resolve the target database within the published release.

        Priority: ``database_id`` → ``database`` (name) → configured default
        (``settings.blast_default_db``) → the release's default assembly.
        Both ``database_id`` and ``database`` may be given; they must agree.

        Every branch is constrained to the resolved release's assemblies, so a
        job can never target a database that belongs to a draft or another
        release — including through the "default" fallbacks, which previously
        picked any ``Assembly.is_default`` row across all releases.
        """
        if request.database_id is not None:
            blast_db = await self._get_active_database(
                db, release_context, BlastDatabase.id == request.database_id
            )
            if blast_db is None:
                raise NotFoundError(
                    f"BLAST database id {request.database_id} not found or inactive"
                )
            if request.database is not None and blast_db.name != request.database:
                raise ValidationError(
                    f"database_id {request.database_id} and database "
                    f"{request.database!r} do not match"
                )
            return blast_db

        if request.database is not None:
            blast_db = await self._get_active_database(
                db, release_context, BlastDatabase.name == request.database
            )
            if blast_db is None:
                raise NotFoundError(
                    f"BLAST database {request.database!r} not found or inactive"
                )
            return blast_db

        # Neither identifier given: fall back to the configured default
        # database, then to the release's default assembly.
        if settings.blast_default_db:
            blast_db = await self._get_active_database(
                db, release_context, BlastDatabase.name == settings.blast_default_db
            )
            if blast_db is not None:
                return blast_db

        assembly_result = await db.execute(
            select(Assembly).where(
                Assembly.is_default.is_(True),
                Assembly.release_id == release_context.release_id,
            )
        )
        assembly = assembly_result.scalars().first()
        if assembly is not None:
            blast_db = await self._get_active_database(
                db, release_context, BlastDatabase.assembly_id == assembly.id
            )
            if blast_db is not None:
                return blast_db

        raise NotFoundError(
            "No BLAST database selected and no default database configured; "
            "pass database/database_id or configure blast_default_db"
        )

    async def submit_job(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        request: BlastSubmitRequest,
        *,
        release_context: ReleaseContext,
    ) -> BlastJobResponse:
        """Create a BLAST job and queue its dispatch via the transactional outbox.

        Business record + outbox event are committed atomically; no Celery
        broker round-trip happens inside this transaction. The searched
        database is resolved inside ``release_context``.
        """
        # Validate the database exists, is active, and belongs to the
        # published release (the active-DB table is the database whitelist).
        blast_db = await self._resolve_database(
            db, request, release_context=release_context
        )

        # Program ↔ database-type compatibility.
        allowed_types = _PROGRAM_DB_TYPES.get(request.program)
        db_type = getattr(blast_db.db_type, "value", blast_db.db_type)
        if allowed_types is not None and db_type not in allowed_types:
            raise ValidationError(
                f"Program {request.program.value} cannot search a "
                f"'{db_type}' database"
            )

        if len(request.query_sequence) > settings.blast_max_length:
            raise ValidationError(
                f"Query sequence exceeds max length {settings.blast_max_length}"
            )
        # Defense in depth: the schema validates the alphabet at the API
        # boundary; re-check here for programmatic callers.
        validate_sequence_charset(request.query_sequence, request.program.value)

        worker_params = _worker_parameters(request.parameters)
        job = BlastJob(
            id=uuid.uuid4(),
            user_id=user_id,
            program=request.program.value,
            database_id=blast_db.id,
            query_sequence=request.query_sequence,
            parameters=worker_params,
            status=BlastJobStatus.PENDING,
            submitted_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        db.add(job)
        await db.flush()

        # The outbox event carries the full versioned JobPayload; the worker
        # validates it with the shared schema before doing any work.
        job_payload = build_job_payload(
            job_id=job.id,
            task_name=BLAST_RUN_TASK,
            payload={
                "job_id": str(job.id),
                "program": job.program,
                "database": blast_db.name,
                "sequence": job.query_sequence,
                "evalue": request.parameters.evalue,
                "word_size": request.parameters.word_size,
                "max_target_seqs": request.parameters.max_target_seqs,
                "parameters": worker_params,
                # Provenance: the worker (and any later reader of the result)
                # must know which release/assembly namespace was searched.
                "release_key": release_context.release_key,
                "assembly": release_context.assembly,
                "assembly_id": blast_db.assembly_id,
            },
            idempotency_key=f"blast:{job.id}",
            max_attempts=settings.blast_max_attempts,
        )
        await create_outbox_event(
            db,
            aggregate_type="blast_job",
            aggregate_id=str(job.id),
            event_type="blast_job.run",
            payload=job_payload.model_dump(mode="json"),
        )

        await db.commit()
        await db.refresh(job)

        return self._job_to_response(job)

    async def get_job(
        self,
        db: AsyncSession,
        job_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        user_roles: list[str] | None = None,
    ) -> BlastJobResponse:
        result = await db.execute(select(BlastJob).where(BlastJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundError(f"BLAST job {job_id} not found")
        self._authorize_job(job.user_id, user_id, user_roles)
        return self._job_to_response(job)

    async def list_jobs(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        user_roles: list[str] | None = None,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
    ) -> BlastJobListResponse:
        conditions = []
        if not has_role(user_roles or [], RoleName.ADMINISTRATOR):
            conditions.append(BlastJob.user_id == user_id)
        if status:
            conditions.append(BlastJob.status == status)

        total = int(
            await db.scalar(
                select(func.count()).select_from(BlastJob).where(*conditions)
            )
            or 0
        )
        stmt = (
            select(BlastJob)
            .where(*conditions)
            .order_by(BlastJob.submitted_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        jobs = list((await db.execute(stmt)).scalars().all())
        return BlastJobListResponse(
            items=[self._job_to_response(job) for job in jobs],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_result(
        self,
        db: AsyncSession,
        job_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        user_roles: list[str] | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> BlastResultResponse:
        """Retrieve the status-aware result envelope for a BLAST job.

        Non-completed jobs return ``hits=None`` (never a placeholder); only
        completed jobs carry a real hit list — an empty list means BLAST
        genuinely produced zero hits.
        """
        result = await db.execute(select(BlastJob).where(BlastJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundError(f"BLAST job {job_id} not found")
        self._authorize_job(job.user_id, user_id, user_roles)

        base = BlastResultResponse(
            job_id=str(job.id),
            status=BlastSchemaJobStatus(job.status),
            program=BlastProgram(job.program),
            database_id=job.database_id,
            query_id="query",
            query_len=job.query_len,
            error_message=_sanitize_error(job.error_message),
            completed_at=job.completed_at,
        )

        if job.status != BlastJobStatus.COMPLETED:
            return base

        # Completed: real hits from the database, ordered by significance.
        hits_stmt = (
            select(BlastHit)
            .where(BlastHit.job_id == job.id)
            .order_by(BlastHit.evalue.asc(), BlastHit.bit_score.desc())
            .offset(offset)
            .limit(limit)
        )
        hits_result = await db.execute(hits_stmt)
        page = list(hits_result.scalars().all())

        stats_stmt = select(
            func.min(BlastHit.evalue), func.max(BlastHit.bit_score)
        ).where(BlastHit.job_id == job.id)
        best_evalue, best_bit_score = (await db.execute(stats_stmt)).first() or (
            None,
            None,
        )

        total_hits = job.hit_count if job.hit_count is not None else len(page)

        download_url = None
        if job.result_path:
            download_url = generate_presigned_url(
                f"{settings.s3_blast_bucket}/{job.result_path}",
                expires_in=3600,
            )

        return BlastResultResponse(
            job_id=str(job.id),
            status=BlastSchemaJobStatus(job.status),
            program=BlastProgram(job.program),
            database_id=job.database_id,
            query_id="query",
            query_len=job.query_len,
            hits=[
                BlastHitSchema(
                    hsp_num=h.hsp_num,
                    subject_id=h.subject_id,
                    subject_title=h.subject_title or "",
                    percent_identity=h.percent_identity,
                    alignment_length=h.alignment_length,
                    mismatches=h.mismatches,
                    gap_opens=h.gap_opens,
                    query_start=h.query_start,
                    query_end=h.query_end,
                    subject_start=h.subject_start,
                    subject_end=h.subject_end,
                    evalue=h.evalue,
                    bit_score=h.bit_score,
                    query_strand=h.query_strand,
                    subject_strand=h.subject_strand,
                )
                for h in page
            ],
            total_hits=total_hits,
            search_stats={
                "total_hits": total_hits,
                "hits_returned": len(page),
                "best_evalue": best_evalue,
                "best_bitscore": best_bit_score,
            },
            error_message=None,
            completed_at=job.completed_at,
            download_url=download_url,
        )

    @staticmethod
    def _authorize_job(owner_id, user_id, user_roles) -> None:
        if owner_id != user_id and not has_role(user_roles, RoleName.ADMINISTRATOR):
            raise AuthorizationError("You do not have permission to access this BLAST job")

    @staticmethod
    def _job_to_response(job: BlastJob) -> BlastJobResponse:
        database = getattr(job, "database", None)
        # Provenance is read through the database row (the job stores only the
        # database id): a stored result must state which release and assembly it
        # was computed against.
        assembly = getattr(database, "assembly", None) if database is not None else None
        return BlastJobResponse(
            job_id=str(job.id),
            status=BlastSchemaJobStatus(job.status),
            program=BlastProgram(job.program),
            database_id=job.database_id,
            database=database.name if database is not None else None,
            query_sequence=job.query_sequence,
            parameters=job.parameters or {},
            hit_count=job.hit_count or 0,
            submitted_at=job.submitted_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=job.error_message,
            result_url=job.result_path,
            release_id=(assembly.release_id if assembly is not None else None),
            assembly_name=(assembly.name if assembly is not None else None),
        )
