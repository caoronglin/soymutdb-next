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

import re
import uuid
from datetime import UTC, datetime, timedelta

from soymutdb_jobs.blast_catalog import (
    is_searchable_build_state,
)
from soymutdb_jobs.blast_search import PROGRAM_DATABASE_TYPES, normalize_query
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.blast_capability import PUBLIC_JOB_MARKER, verify_blast_capability
from ..core.config import get_settings
from ..core.exceptions import (
    AuthorizationError,
    NotFoundError,
    RateLimitExceededError,
    ValidationError,
)
from ..core.security import RoleName, has_role
from ..core.task_contract import BLAST_BUILD_INDEX_TASK, BLAST_RUN_TASK
from ..models.auth import User
from ..models.blast import (
    BlastDatabase,
    BlastDbType,
    BlastHit,
    BlastIndexBuild,
    BlastJob,
    BlastJobStatus,
)
from ..models.genomic import Assembly
from ..schemas.blast import (
    BlastDatabaseResponse,
    BlastGenomeTargetResponse,
    BlastIndexBuildRequest,
    BlastIndexBuildResponse,
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
from .outbox_service import create_outbox_event, enqueue_task_event
from .release_context import ReleaseContext

settings = get_settings()


#: Maximum characters of error text exposed to clients.
_MAX_ERROR_LEN = 2000


def _sanitize_error(message: str | None) -> str | None:
    """Trim error text for client responses (printable chars only)."""
    if not message:
        return None
    clean = "".join(ch for ch in message if ch.isprintable() or ch in "\n\t")
    return clean.strip()[:_MAX_ERROR_LEN] or None


def _worker_parameters(
    params: BlastParameters, program: BlastProgram = BlastProgram.BLASTP,
    engine: str = "diamond",
) -> dict:
    validated = params.canonical_parameters(program.value, engine)
    return {key: value for key, value in validated.items()
            if key not in {"evalue", "max_target_seqs"}}


class BlastService:
    """BLAST job management service."""

    async def list_databases(
        self,
        db: AsyncSession,
        *,
        release_context: ReleaseContext,
    ) -> list[BlastDatabaseResponse]:
        """List ready supported indexes in the published release.

        Unfinished indexes stay private to the catalog control plane. Program
        compatibility is enforced again at selection; the release join hides
        unpublished assemblies.
        """
        result = await db.execute(
            select(BlastDatabase)
            .join(Assembly, BlastDatabase.assembly_id == Assembly.id)
            .where(
                BlastDatabase.is_active.is_(True),
                BlastDatabase.engine.in_(["diamond", "ncbi_blast"]),
                BlastDatabase.build_status.in_(["published", "ready"]),
                Assembly.release_id == release_context.release_id,
            )
        )
        rows: list[BlastDatabaseResponse] = []
        for bd in result.scalars().all():
            if not self._is_runnable_database(bd):
                continue
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
                    engine=bd.engine,
                    sequence_type=bd.sequence_type,
                    annotation_version=bd.annotation_version,
                    source_url=bd.source_url,
                    sequence_count=bd.sequence_count,
                    total_length=bd.total_length,
                    fasta_sha256=bd.fasta_sha256,
                    index_version=bd.index_version,
                    build_status=bd.build_status,
                    is_default=bd.is_default,
                    license=bd.license,
                    created_at=bd.created_at,
                    assembly_name=assembly.name if assembly is not None else None,
                    assembly_version=(assembly.version if assembly is not None else None),
                    assembly_is_default=(assembly.is_default if assembly is not None else None),
                    release_id=(assembly.release_id if assembly is not None else None),
                )
            )
        return rows

    async def request_index_build(
        self,
        db: AsyncSession,
        request: BlastIndexBuildRequest,
        *,
        user_id: uuid.UUID | None,
        release_context: ReleaseContext,
    ) -> BlastIndexBuildResponse:
        """Record an immutable index build request and enqueue worker execution.

        No ``makeblastdb`` call happens in this HTTP request. The catalog row
        starts ``pending``/inactive and becomes searchable only after the
        worker validates and publishes a new content-addressed identity.
        Rebuilds always create a fresh row, never overwrite a published one.
        """
        from sqlalchemy import select


        # The catalog's assembly/release identity is authoritative and is
        # never trusted from the request body. get_ncbi_db_path binds the
        # manifest's assembly_id/release_id to the numeric assemblies.id and
        # release key of the searched job, so they must be frozen here.
        assembly = (await db.execute(
            select(Assembly).where(
                Assembly.name == request.assembly_name,
                Assembly.release_id == release_context.release_id,
            )
        )).scalar_one_or_none()
        if assembly is None:
            raise NotFoundError("assembly not found in the published release")

        existing = (await db.execute(
            select(BlastDatabase.id).where(BlastDatabase.name == request.name)
        )).scalar_one_or_none()
        if existing is not None:
            raise ValidationError(
                "BLAST database name already exists; use a new name for a rebuild"
            )

        catalog = BlastDatabase(
            name=request.name,
            db_type=request.db_type,
            assembly_id=assembly.id,
            file_path="",  # worker-local index path is never stored or exposed
            engine="ncbi_blast",
            sequence_type=request.sequence_type,
            annotation_version=request.annotation_version,
            source_url=request.source_url,
            license=request.license,
            build_status="pending",
            is_active=False,
            is_default=False,
            provenance={"source_version": request.source_version},
        )
        db.add(catalog)
        await db.flush()

        build = BlastIndexBuild(
            id=uuid.uuid4(),
            database_id=catalog.id,
            state="pending",
            source_object_key=request.source_object_key,
            db_type=request.db_type,
            build_metadata=request.build_metadata(
                assembly_id=str(assembly.id),
                assembly_version=assembly.version,
                release_id=release_context.release_key,
            ),
            requested_by=user_id,
        )
        db.add(build)
        await db.flush()

        await enqueue_task_event(
            db,
            event_type="blast_index.build",
            aggregate_type="blast_index_build",
            aggregate_id=str(build.id),
            task_name=BLAST_BUILD_INDEX_TASK,
            kwargs={"build_id": str(build.id)},
        )
        await db.commit()
        await db.refresh(build)
        return self._build_to_response(build, catalog.name)

    async def get_index_build(
        self, db: AsyncSession, build_id: uuid.UUID
    ) -> BlastIndexBuildResponse:
        from sqlalchemy import select

        build = (await db.execute(
            select(BlastIndexBuild).where(BlastIndexBuild.id == build_id)
        )).scalar_one_or_none()
        if build is None:
            raise NotFoundError(f"BLAST index build {build_id} not found")
        name = (await db.execute(
            select(BlastDatabase.name).where(BlastDatabase.id == build.database_id)
        )).scalar_one_or_none() or ""
        return self._build_to_response(build, name)

    @staticmethod
    def _build_to_response(build: BlastIndexBuild, name: str) -> BlastIndexBuildResponse:
        return BlastIndexBuildResponse(
            build_id=str(build.id),
            database_id=build.database_id or 0,
            name=name,
            state=build.state,
            db_type=build.db_type,
            index_identity=build.index_identity,
            sequence_count=build.sequence_count,
            total_length=build.total_length,
            error_message=build.error_message,
            created_at=build.created_at,
            started_at=build.started_at,
            completed_at=build.completed_at,
        )



    async def resolve_genome_target(
        self,
        db: AsyncSession,
        job_id: uuid.UUID,
        subject_id: str,
        *,
        user_id: uuid.UUID | None = None,
        user_roles: list[str] | None = None,
        public_token: str | None = None,
    ) -> BlastGenomeTargetResponse:
        """Resolve one BLAST subject to a gene locus in the job's own namespace.

        Amino-acid alignment coordinates from ``blastp``/``blastx``/``tblastn``
        describe residues, not bases. They are never used to build a genome
        location. The subject identifier must resolve through an explicit,
        assembly- and release-scoped gene/alias/transcript relation; anything
        else is reported as unresolved with a reason.
        """
        from sqlalchemy import select

        from ..models.genomic import Gene, GeneAlias, Transcript

        def unresolved(reason: str) -> BlastGenomeTargetResponse:
            return BlastGenomeTargetResponse(status="unresolved", reason=reason)

        subject = subject_id.strip()
        if not subject or len(subject) > 256 or any(ord(ch) < 32 for ch in subject):
            return unresolved("invalid_subject_id")
        if public_token is not None:
            verify_blast_capability(public_token, job_id)
        result = await db.execute(select(BlastJob).where(BlastJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundError(f"BLAST job {job_id} not found")
        self._authorize_read(job, user_id, user_roles, public_token)
        if job.status != BlastJobStatus.COMPLETED:
            return unresolved("job_not_completed")
        # For blastp/blastx/tblastn the hit's subject_start/end are residue
        # positions. Nothing below reads them: the locus comes only from the
        # resolved gene record in the job's own assembly/release.
        database = getattr(job, "database", None)
        assembly = getattr(database, "assembly", None) if database is not None else None
        if assembly is None or assembly.release_id is None:
            return unresolved("assembly_mismatch")
        release_id = int(assembly.release_id)
        assembly_id = int(assembly.id)

        gene = (await db.execute(
            select(Gene).where(
                Gene.accession == subject,
                Gene.assembly_id == assembly_id,
            )
        )).scalar_one_or_none()
        resolution = "gene_accession"
        if gene is None:
            alias_rows = (await db.execute(
                select(GeneAlias).join(Gene, GeneAlias.gene_id == Gene.gene_pk).where(
                    GeneAlias.alias == subject,
                    Gene.assembly_id == assembly_id,
                )
            )).scalars().all()
            if len(alias_rows) == 1:
                gene = (await db.execute(
                    select(Gene).where(Gene.gene_pk == alias_rows[0].gene_id)
                )).scalar_one_or_none()
                resolution = "gene_alias"
            elif len(alias_rows) > 1:
                return unresolved("ambiguous_subject")
        if gene is None:
            transcript_rows = (await db.execute(
                select(Transcript).join(Gene, Transcript.gene_id == Gene.gene_pk).where(
                    Transcript.id == subject,
                    Gene.assembly_id == assembly_id,
                )
            )).scalars().all()
            if len(transcript_rows) == 1:
                gene = (await db.execute(
                    select(Gene).where(Gene.gene_pk == transcript_rows[0].gene_id)
                )).scalar_one_or_none()
                resolution = "transcript_id"
            elif len(transcript_rows) > 1:
                return unresolved("ambiguous_subject")
        if gene is None:
            return unresolved("subject_not_found")
        if gene.assembly_id != assembly_id:
            return unresolved("assembly_mismatch")
        chromosome = getattr(gene, "chromosome", None)
        name = getattr(chromosome, "name", None) if chromosome is not None else None
        if (
            not name or gene.start is None or gene.end is None
            or gene.start < 1 or gene.end < gene.start
        ):
            return unresolved("no_genomic_coordinates")
        return BlastGenomeTargetResponse(
            status="resolved",
            gene_id=gene.accession,
            chromosome=name,
            start=int(gene.start),
            end=int(gene.end),
            strand=gene.strand,
            release_id=release_id,
            assembly_id=assembly_id,
            assembly_name=assembly.name,
            locus=f"{name}:{int(gene.start)}-{int(gene.end)}",
            resolution=resolution,
        )

    @staticmethod
    def _is_runnable_database(database: BlastDatabase) -> bool:
        """Catalog preparation must never dispatch an index to the wrong runner."""
        return (
            database.is_active is True
            and database.engine in {"diamond", "ncbi_blast"}
            and is_searchable_build_state(database.build_status)
            and database.db_type in {BlastDbType.PROT, BlastDbType.NUCL}
            and (database.engine != "diamond" or database.db_type == BlastDbType.PROT)
        )

    @staticmethod
    async def _get_active_database(
        db: AsyncSession,
        release_context: ReleaseContext,
        *conditions: ColumnElement[bool],
        engine: str = "ncbi_blast",
        program: str = "blastp",
    ) -> BlastDatabase | None:
        """Fetch one ready program/engine-compatible index in the published release.

        Only executable ``blast_databases`` rows of the *resolved release* are the
        database whitelist: anything not matching is refused here (defense in
        depth on top of the schema-level name format check). The release join
        is what stops a job from targeting another release's database.
        """
        result = await db.execute(
            select(BlastDatabase)
            .join(Assembly, BlastDatabase.assembly_id == Assembly.id)
            .where(
                BlastDatabase.is_active.is_(True),
                BlastDatabase.engine.in_(["diamond", "ncbi_blast"]),
                BlastDatabase.build_status.in_(["published", "ready"]),
                Assembly.release_id == release_context.release_id,
                BlastDatabase.engine == engine,
                BlastDatabase.db_type == PROGRAM_DATABASE_TYPES[program],
                *conditions,
            )
            .order_by(BlastDatabase.is_default.desc(), BlastDatabase.id)
            .limit(1)
        )
        database = result.scalar_one_or_none()
        return database if (
            database and BlastService._is_runnable_database(database)
            and database.engine == engine
            and database.db_type == PROGRAM_DATABASE_TYPES[program]
        ) else None

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
                db, release_context, BlastDatabase.id == request.database_id,
                engine=request.engine, program=request.program.value
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
                db, release_context, BlastDatabase.name == request.database,
                engine=request.engine, program=request.program.value
            )
            if blast_db is None:
                raise NotFoundError(f"BLAST database {request.database!r} not found or inactive")
            return blast_db

        # Neither identifier given: fall back to the configured default
        # database, then to the release's default assembly.
        if settings.blast_default_db:
            blast_db = await self._get_active_database(
                db, release_context, BlastDatabase.name == settings.blast_default_db,
                engine=request.engine, program=request.program.value
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
                db, release_context, BlastDatabase.assembly_id == assembly.id,
                engine=request.engine, program=request.program.value
            )
            if blast_db is not None:
                return blast_db

        raise NotFoundError(
            "No BLAST database selected and no default database configured; "
            "pass database/database_id or configure blast_default_db"
        )

    async def _enforce_user_limit(self, db: AsyncSession, user_id: uuid.UUID | None) -> None:
        """Serialize reservations on the authoritative user row in this transaction.

        The lock remains held through job/outbox insertion and commit. Counting
        without this lock lets concurrent requests all observe the last slot.
        NULL legacy expiry is conservatively active; public jobs use peer quotas.
        """
        if user_id is None:
            return
        user = await db.execute(select(User.id).where(User.id == user_id).with_for_update())
        if user.scalar_one_or_none() is None:
            raise NotFoundError("BLAST submitting account not found")
        active_count = await db.scalar(
            select(func.count()).select_from(BlastJob).where(
                BlastJob.user_id == user_id,
                BlastJob.status.in_([BlastJobStatus.PENDING, BlastJobStatus.RUNNING]),
                (BlastJob.expires_at.is_(None)) | (BlastJob.expires_at > datetime.now(UTC)),
            )
        )
        if active_count >= settings.blast_max_active_jobs_per_user:
            raise RateLimitExceededError(
                "Too many active BLAST jobs; wait for an existing job to finish",
                retry_after=60,
            )

    async def submit_job(
        self,
        db: AsyncSession,
        user_id: uuid.UUID | None,
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
        blast_db = await self._resolve_database(db, request, release_context=release_context)

        # Program ↔ database-type compatibility.
        expected_type = PROGRAM_DATABASE_TYPES[request.program.value]
        db_type = getattr(blast_db.db_type, "value", blast_db.db_type)
        if db_type != expected_type:
            raise ValidationError(
                f"Program {request.program.value} cannot search a '{db_type}' database"
            )

        if len(request.query_sequence) > settings.blast_max_length:
            raise ValidationError(f"Query sequence exceeds max length {settings.blast_max_length}")
        # Defense in depth: the schema validates the alphabet at the API
        # boundary; re-check here for programmatic callers.
        validate_sequence_charset(request.query_sequence, request.program.value)

        if user_id is None and len(request.query_sequence) > settings.blast_public_max_length:
            raise ValidationError(
                f"Public query exceeds max length {settings.blast_public_max_length}"
            )
        normalized = normalize_query(request.query_sequence, request.program.value)
        if request.engine == "ncbi_blast" and (
            not isinstance(blast_db.index_version, str)
            or not re.fullmatch(r"[a-f0-9]{64}", blast_db.index_version)
            or not isinstance(blast_db.fasta_sha256, str)
            or not re.fullmatch(r"[a-f0-9]{64}", blast_db.fasta_sha256)
        ):
            raise ValidationError("NCBI index requires verified identity and FASTA checksum")
        worker_params = _worker_parameters(request.parameters, request.program, request.engine)
        await self._enforce_user_limit(db, user_id)
        index_metadata = {
            "engine": request.engine,
            "database_type": str(blast_db.db_type),
            "index_identity": blast_db.index_version,
            "fasta_sha256": blast_db.fasta_sha256,
            "index_version": blast_db.index_version,
            "annotation_version": blast_db.annotation_version,
        }
        search_provenance = {
            **index_metadata,
            "release_id": release_context.release_id,
            "assembly_id": blast_db.assembly_id,
            "assembly_name": getattr(blast_db.assembly, "name", release_context.assembly),
        }
        job = BlastJob(
            id=uuid.uuid4(),
            user_id=user_id,
            program=request.program.value,
            database_id=blast_db.id,
            query_sequence=normalized.normalized_fasta,
            parameters=(
                {**worker_params, "_search_provenance": search_provenance, PUBLIC_JOB_MARKER: True}
                if user_id is None else {**worker_params, "_search_provenance": search_provenance}
            ),
            status=BlastJobStatus.PENDING,
            submitted_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + (
                timedelta(seconds=settings.blast_public_token_ttl_seconds)
                if user_id is None else timedelta(days=7)
            ),
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
                **index_metadata,
                "database": blast_db.name,
                "sequence": job.query_sequence,
                "evalue": request.parameters.evalue,
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
        *,
        public_token: str | None = None,
    ) -> BlastJobResponse:
        if public_token is not None:
            verify_blast_capability(public_token, job_id)
        result = await db.execute(select(BlastJob).where(BlastJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundError(f"BLAST job {job_id} not found")
        self._authorize_read(job, user_id, user_roles, public_token)
        response = self._job_to_response(job)
        if public_token is not None:
            response.result_url = None
            response.error_message = self._public_error(job.error_message)
        if self._expired(job):
            response.status = BlastSchemaJobStatus.EXPIRED
            response.result_url = None
        return response



    async def cancel_job(
        self,
        db: AsyncSession,
        job_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        user_roles: list[str] | None = None,
        *,
        public_token: str | None = None,
    ) -> BlastJobResponse:
        """Cancel a pending/running BLAST job, identically for both engines.

        A worker that already claimed the job finishes its current run, but
        ``begin_run`` skips terminal rows and ``mark_succeeded`` is guarded on
        ``status == running``, so a late success cannot overwrite the cancel.
        """
        if public_token is not None:
            verify_blast_capability(public_token, job_id)
        result = await db.execute(
            select(BlastJob).where(BlastJob.id == job_id).with_for_update()
        )
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundError(f"BLAST job {job_id} not found")
        self._authorize_read(job, user_id, user_roles, public_token)
        if job.status not in (BlastJobStatus.PENDING, BlastJobStatus.RUNNING):
            raise ValidationError(
                f"Only pending or running BLAST jobs can be cancelled (status={job.status})"
            )
        job.status = BlastJobStatus.CANCELLED
        job.completed_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(job)
        return self._job_to_response(job)

    async def retry_job(
        self,
        db: AsyncSession,
        job_id: uuid.UUID,
        user_id: uuid.UUID | None,
        user_roles: list[str] | None = None,
        *,
        release_context: ReleaseContext,
    ) -> BlastJobResponse:
        """Retry a failed/expired job as a NEW job, for both engines alike.

        Results and indexes are immutable: retry never mutates the original
        row, never reuses its job id, and re-resolves the database in the
        published release so a stale provenance cannot be replayed.
        """
        result = await db.execute(select(BlastJob).where(BlastJob.id == job_id))
        original = result.scalar_one_or_none()
        if original is None:
            raise NotFoundError(f"BLAST job {job_id} not found")
        self._authorize_job(original.user_id, user_id, user_roles)
        if original.status not in (BlastJobStatus.FAILED, BlastJobStatus.EXPIRED):
            raise ValidationError(
                f"Only failed or expired BLAST jobs can be retried (status={original.status})"
            )
        if user_id is None:
            raise AuthorizationError("Anonymous BLAST jobs cannot be retried")
        provenance = (original.parameters or {}).get("_search_provenance", {})
        engine = provenance.get("engine", "diamond")
        request = BlastSubmitRequest(
            engine=engine,
            program=BlastProgram(original.program),
            database_id=original.database_id,
            query_sequence=original.query_sequence,
            parameters=BlastParameters(
                evalue=float((original.parameters or {}).get("evalue", 1e-5)),
                max_target_seqs=int(
                    (original.parameters or {}).get("max_target_seqs", 50)
                ),
            ),
        )
        return await self.submit_job(
            db, user_id, request, release_context=release_context
        )

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
            await db.scalar(select(func.count()).select_from(BlastJob).where(*conditions)) or 0
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
        public_token: str | None = None,
    ) -> BlastResultResponse:
        """Retrieve the status-aware result envelope for a BLAST job.

        Non-completed jobs return ``hits=None`` (never a placeholder); only
        completed jobs carry a real hit list — an empty list means BLAST
        genuinely produced zero hits.
        """
        capability_expiry = (
            verify_blast_capability(public_token, job_id) if public_token is not None else None
        )
        result = await db.execute(select(BlastJob).where(BlastJob.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise NotFoundError(f"BLAST job {job_id} not found")
        self._authorize_read(job, user_id, user_roles, public_token)
        error_message = (
            self._public_error(job.error_message) if public_token is not None
            else _sanitize_error(job.error_message)
        )
        base = BlastResultResponse(
            job_id=str(job.id),
            status=BlastSchemaJobStatus(job.status),
            program=BlastProgram(job.program),
            database_id=job.database_id,
            query_id="query",
            query_len=job.query_len,
            error_message=error_message,
            completed_at=job.completed_at,
        )

        if self._expired(job):
            base.status = BlastSchemaJobStatus.EXPIRED
            return base
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

        stats_stmt = select(func.min(BlastHit.evalue), func.max(BlastHit.bit_score)).where(
            BlastHit.job_id == job.id
        )
        best_evalue, best_bit_score = (await db.execute(stats_stmt)).first() or (
            None,
            None,
        )

        total_hits = job.hit_count if job.hit_count is not None else len(page)

        download_url = None
        if job.result_path:
            deadline = min(
                value for value in (job.expires_at, capability_expiry,
                                    datetime.now(UTC) + timedelta(hours=1))
                if value is not None
            )
            ttl = int((deadline - datetime.now(UTC)).total_seconds())
            download_url = generate_presigned_url(
                f"{settings.s3_blast_bucket}/{job.result_path}",
                expires_in=max(1, ttl),
            ) if ttl > 0 else None

        return BlastResultResponse(
            job_id=str(job.id),
            status=BlastSchemaJobStatus(job.status),
            program=BlastProgram(job.program),
            database_id=job.database_id,
            query_id="query",
            query_len=job.query_len,
            hits=[
                BlastHitSchema(
                    query_id=getattr(h, "query_id", None),
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
    def _expired(job: BlastJob) -> bool:
        return job.status == BlastJobStatus.EXPIRED or (
            job.expires_at is not None and job.expires_at <= datetime.now(UTC)
        )

    @staticmethod
    def _public_error(message: str | None) -> str | None:
        # Worker diagnostics may contain local index paths; no diagnostic text
        # is needed to poll an anonymous job safely.
        return "BLAST search failed" if message else None

    @classmethod
    def _authorize_read(cls, job, user_id, user_roles, public_token) -> None:
        if public_token is not None:
            if job.user_id is not None or (job.parameters or {}).get(PUBLIC_JOB_MARKER) is not True:
                raise AuthorizationError("This capability cannot access this BLAST job")
            return
        cls._authorize_job(job.user_id, user_id, user_roles)

    @staticmethod
    def _authorize_job(owner_id, user_id, user_roles) -> None:
        if not has_role(user_roles or [], RoleName.ADMINISTRATOR) and (
            owner_id is None or user_id is None or owner_id != user_id
        ):
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
            engine=(job.parameters or {}).get("_search_provenance", {}).get("engine", "diamond"),
            database_id=job.database_id,
            database=database.name if database is not None else None,
            query_sequence=job.query_sequence,
            parameters={
                key: value for key, value in (job.parameters or {}).items()
                if key != PUBLIC_JOB_MARKER
            },
            hit_count=job.hit_count or 0,
            submitted_at=job.submitted_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=job.error_message,
            result_url=job.result_path,
            release_id=(job.parameters or {}).get("_search_provenance", {}).get(
                "release_id", assembly.release_id if assembly is not None else None
            ),
            assembly_name=(job.parameters or {}).get("_search_provenance", {}).get(
                "assembly_name", assembly.name if assembly is not None else None
            ),
        )
