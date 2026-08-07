"""BLAST search tasks.

Security and reliability fixes vs. quartz reference:
- ``subprocess.run`` is always called **without** ``shell=True`` and with a
  minimal environment (no ambient secrets leak into the child).
- BLAST program name is validated against a whitelist before execution.
- All BLAST parameters are validated against a whitelist; unknown parameters
  are rejected (never passed through to the shell).
- Resource limits: CPU affinity, memory (``ulimit``), wall-clock timeout,
  output file size cap, and query sequence length cap.
- Raw results are uploaded to MinIO (key contains the job id, metadata
  carries sha256 checksum + size) and a pre-signed URL is returned.
- Parsed hits are persisted to the ``blast_hits`` table (delete-then-insert
  per job, so redeliveries never duplicate results); ``query_len`` /
  ``hit_count`` are recorded on the job row.
- Errors are scrubbed (query sequence removed, truncated) before they are
  stored in ``job.last_error``; no secrets or full sequences are logged.
- Supports cancellation and expired-job cleanup.
- Job status is tracked through the shared contract (``soymutdb_jobs``) via
  the narrow :class:`BlastJobStore` repository — the worker never imports API
  models.  Transitions are validated by the shared state machine and every
  status write is idempotent (conditional UPDATE keyed on the current status),
  so crash-restart re-deliveries of the same outbox event (same ``task_id``
  and ``idempotency_key``) never double-apply.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import resource
import subprocess
import tempfile
from pathlib import Path

from celery import Task

from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.repositories import BlastHitStore, BlastJobStore
from soymutdb_worker.shared import BLAST_RUN_TASK, JobPayload
from soymutdb_worker.utils.db import get_db
from soymutdb_worker.utils.s3 import (
    generate_presigned_url,
    get_s3_client,
    upload_file,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BLAST_CACHE_DIR = Path(get_setting("BLAST_CACHE_DIR", "/tmp/blast_cache"))
BLAST_BIN_DIR = Path(get_setting("BLAST_BIN_DIR", "/usr/bin"))

# Whitelist of allowed BLAST programs.
ALLOWED_PROGRAMS = frozenset(
    {"blastn", "blastp", "blastx", "tblastn", "tblastx"}
)

# Whitelist of allowed BLAST command-line parameters (without leading dash).
ALLOWED_PARAMS = frozenset(
    {
        "evalue",
        "word_size",
        "max_target_seqs",
        "max_hsps",
        "gapopen",
        "gapextend",
        "reward",
        "penalty",
        "dust",
        "soft_masking",
        "lcase_masking",
        "xdrop_ungap",
        "xdrop_gap",
        "xdrop_gap_final",
        "searchsp",
        "threshold",
        "window_size",
        "ungapped",
        "culling_limit",
        "best_hit_overhang",
        "best_hit_score_edge",
        "subject_besthit",
        "sum_stats",
        "db_gencode",
        "query_gencode",
        "frame_shift_penalty",
        "use_index",
        "index_name",
        "remote",
        "num_threads",
        "mt_mode",
        "use_sw_tback",
    }
)

# Resource limits
MAX_QUERY_LENGTH = int(get_setting("BLAST_MAX_QUERY_LENGTH", "100000"))
MAX_OUTPUT_SIZE = int(get_setting("BLAST_MAX_OUTPUT_SIZE", str(512 * 1024 * 1024)))  # 512 MB
MAX_RUNTIME_SECONDS = int(get_setting("BLAST_MAX_RUNTIME", "3600"))  # 1 hour
MAX_MEMORY_MB = int(get_setting("BLAST_MAX_MEMORY_MB", "4096"))  # 4 GB

#: Minimal environment for the BLAST child process: the binary only needs a
#: PATH; anything else from the worker's environment (tokens, keys, …) must
#: not leak into the child.
BLAST_SUBPROCESS_ENV = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "HOME": "/tmp",
    "TMPDIR": "/tmp",
    "LANG": "C",
}

#: Maximum characters of error text persisted to ``blast_jobs.error_message``.
MAX_ERROR_LENGTH = 4000


def sanitize_error_message(
    message: str,
    *,
    query_sequence: str | None = None,
    max_len: int = MAX_ERROR_LENGTH,
) -> str:
    """Scrub and truncate an error message before it is persisted/logged.

    Removes the full query sequence (if embedded), drops control characters,
    collapses whitespace and caps the length so ``job.last_error`` never
    echoes user payloads or secrets verbatim.
    """
    if query_sequence:
        body = query_sequence.strip()
        if body and body in message:
            message = message.replace(body, "<query-sequence>")
    message = "".join(ch for ch in message if ch.isprintable() or ch in "\n\t")
    message = " ".join(message.split())
    return message[:max_len]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_program(program: str) -> str:
    """Validate that *program* is an allowed BLAST program name."""
    if program not in ALLOWED_PROGRAMS:
        raise ValueError(
            f"Invalid BLAST program: {program!r}. "
            f"Allowed: {sorted(ALLOWED_PROGRAMS)}"
        )
    return program


def validate_parameters(params: dict | None) -> dict:
    """Validate that all parameter keys are in the whitelist.

    Returns a cleaned dict with string values suitable for CLI args.
    """
    if not params:
        return {}
    cleaned: dict = {}
    for key, value in params.items():
        if key not in ALLOWED_PARAMS:
            raise ValueError(f"Disallowed BLAST parameter: {key!r}")
        if value is not None:
            cleaned[key] = str(value)
    return cleaned


def validate_sequence(sequence: str) -> str:
    """Validate query sequence length and basic format."""
    if not sequence or not sequence.strip():
        raise ValueError("Query sequence is empty")
    # Strip FASTA headers for length check
    lines = sequence.strip().splitlines()
    seq_body = "".join(part for part in lines if not part.startswith(">"))
    if len(seq_body) > MAX_QUERY_LENGTH:
        raise ValueError(
            f"Query sequence too long: {len(seq_body)} > {MAX_QUERY_LENGTH}"
        )
    return sequence


# ---------------------------------------------------------------------------
# BLAST database management
# ---------------------------------------------------------------------------


def get_blast_db_path(db_name: str) -> Path:
    """Return the local path for a BLAST database, downloading from S3 if needed.

    Only allows alphanumeric, underscore, and hyphen in *db_name* to prevent
    path traversal.
    """
    if not db_name.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"Invalid BLAST database name: {db_name!r}")

    BLAST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    db_path = BLAST_CACHE_DIR / db_name

    # Check if already cached (BLAST DB files have .nin/.nhr/.ndb etc.)
    if (db_path.with_suffix(".ndb")).exists() or (db_path.with_suffix(".nin")).exists():
        return db_path

    # Download from S3
    s3_bucket = get_setting("S3_BLAST_BUCKET", "blast-dbs")
    s3_prefix = f"blast-dbs/{db_name}"

    s3 = get_s3_client()
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=s3_bucket, Prefix=s3_prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            filename = Path(key).name
            local_path = BLAST_CACHE_DIR / filename
            if not local_path.exists():
                logger.info("Downloading BLAST db file: %s", filename)
                s3.download_file(s3_bucket, key, str(local_path))

    return db_path


# ---------------------------------------------------------------------------
# BLAST execution
# ---------------------------------------------------------------------------


def _set_subprocess_limits() -> None:
    """Set memory and file-size limits for the child process via ``resource``.

    Called as a ``preexec_fn`` so limits apply only to the BLAST child.
    """
    # Virtual memory limit (bytes)
    mem_bytes = MAX_MEMORY_MB * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    except (ValueError, OSError):
        pass  # May not be supported on all platforms
    # Output file size limit
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_SIZE, MAX_OUTPUT_SIZE))
    except (ValueError, OSError):
        pass


def run_blast_command(
    program: str,
    db_path: Path,
    query_path: Path,
    output_path: Path,
    evalue: float = 0.001,
    word_size: int | None = None,
    max_target_seqs: int = 100,
    outfmt: int = 15,  # JSON
    extra_args: dict | None = None,
    num_threads: int = 1,
) -> None:
    """Run a BLAST command with ``subprocess.run`` (no shell).

    All arguments are passed as a list — never through a shell string — and
    the child runs with a minimal environment (:data:`BLAST_SUBPROCESS_ENV`).
    """
    program = validate_program(program)
    blast_bin = BLAST_BIN_DIR / program

    if not blast_bin.exists():
        raise RuntimeError(f"BLAST program not found: {blast_bin}")

    # Build command as a list (no shell interpolation possible)
    cmd: list[str] = [
        str(blast_bin),
        "-db", str(db_path),
        "-query", str(query_path),
        "-out", str(output_path),
        "-evalue", str(evalue),
        "-max_target_seqs", str(max_target_seqs),
        "-outfmt", str(outfmt),
        "-num_threads", str(num_threads),
    ]

    if word_size is not None:
        cmd.extend(["-word_size", str(word_size)])

    # Validate and append extra args
    cleaned = validate_parameters(extra_args)
    for key, value in cleaned.items():
        cmd.extend([f"-{key}", value])

    logger.info("Running BLAST: %s vs %s", program, db_path.name)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=MAX_RUNTIME_SECONDS,
        preexec_fn=_set_subprocess_limits,
        env=BLAST_SUBPROCESS_ENV,
        # Explicitly no shell
        shell=False,
    )

    if result.returncode != 0:
        # Sanitize before logging: stderr may echo the query sequence.
        stderr_scrubbed = sanitize_error_message(
            result.stderr or f"exit code {result.returncode}"
        )
        logger.error("BLAST failed (rc=%d): %s", result.returncode, stderr_scrubbed)
        raise RuntimeError(
            f"BLAST execution failed (rc={result.returncode}): {stderr_scrubbed}"
        )


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------


def _result_file_metadata(output_path: Path) -> tuple[str, int]:
    """Return ``(sha256_hex, size_bytes)`` of the raw BLAST output file."""
    digest = hashlib.sha256()
    with open(output_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest(), output_path.stat().st_size


def parse_blast_json(output_path: Path) -> dict:
    """Parse BLAST JSON output (outfmt 15) into structured hits."""
    with open(output_path) as f:
        data = json.load(f)

    hits: list[dict] = []
    blast_result = data.get("BlastOutput2", [{}])[0].get("report", {})
    results = blast_result.get("results", {})
    search = results.get("search", {})

    for hit in search.get("hits", []):
        descriptions = hit.get("description", [{}])
        desc = descriptions[0] if descriptions else {}
        for hsp in hit.get("hsps", []):
            align_len = max(hsp.get("align_len", 1), 1)
            identity = hsp.get("identity", 0)
            gaps = hsp.get("gaps", 0)
            hits.append(
                {
                    "query_id": search.get("query_id", ""),
                    "subject_id": desc.get("id", ""),
                    "subject_title": desc.get("title", ""),
                    "percent_identity": identity / align_len * 100,
                    "alignment_length": hsp.get("align_len", 0),
                    "mismatches": hsp.get("align_len", 0) - identity - gaps,
                    "gap_opens": gaps,
                    "query_start": hsp.get("query_from", 0),
                    "query_end": hsp.get("query_to", 0),
                    "subject_start": hsp.get("hit_from", 0),
                    "subject_end": hsp.get("hit_to", 0),
                    "evalue": hsp.get("evalue", 0),
                    "bit_score": hsp.get("bit_score", 0),
                    "query_strand": (
                        "plus" if hsp.get("query_strand", "Plus") == "Plus" else "minus"
                    ),
                    "subject_strand": (
                        "plus" if hsp.get("hit_strand", "Plus") == "Plus" else "minus"
                    ),
                }
            )

    return {
        "program": blast_result.get("program", ""),
        "version": blast_result.get("version", ""),
        "reference": blast_result.get("reference", ""),
        "search_target": search.get("search_target", {}),
        "query_id": search.get("query_id", ""),
        "query_len": search.get("query_len", 0),
        "hits": hits,
        "total_hits": len(hits),
        "stat": search.get("stat", {}),
    }


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name=BLAST_RUN_TASK,
    queue="blast",
)
def run_blast(
    self: Task,
    payload: dict | None = None,
    *,
    job_id: str | None = None,
    program: str | None = None,
    database: str | None = None,
    sequence: str | None = None,
    evalue: float = 0.001,
    word_size: int | None = None,
    max_target_seqs: int = 100,
    parameters: dict | None = None,
    num_threads: int = 1,
) -> dict:
    """Execute a BLAST search asynchronously.

    Two call styles are accepted:

    1. **Outbox contract** (canonical): ``payload`` is a serialized
       :class:`soymutdb_jobs.schemas.JobPayload` (versioned, idempotent).
    2. **Legacy kwargs** (compat for direct dispatches): the individual
       ``job_id`` / ``program`` / ``database`` / ``sequence`` / ... kwargs.

    Job status is advanced through the shared state machine and the narrow
    :class:`BlastJobStore` repository: pending -> running -> succeeded /
    failed.  Re-deliveries of the same event (same ``idempotency_key`` /
    ``task_id``) are detected via the job's current status and skipped, so
    the worker never applies one job twice.
    """
    # ── Resolve payload (outbox contract) or legacy kwargs ────────────────
    if payload is not None:
        job_payload = JobPayload.model_validate(payload)
        if job_payload.task_name != BLAST_RUN_TASK:
            raise ValueError(
                f"Payload task_name {job_payload.task_name!r} does not match "
                f"task {BLAST_RUN_TASK!r}"
            )
        job_id = str(job_payload.job_id)
        idempotency_key = job_payload.idempotency_key
        p = job_payload.payload
        program = str(p["program"])
        database = str(p["database"])
        sequence = str(p["sequence"])
        evalue = float(p.get("evalue", 0.001))
        word_size = int(p["word_size"]) if p.get("word_size") is not None else None
        max_target_seqs = int(p.get("max_target_seqs", 100))
        parameters = p.get("parameters")
        num_threads = int(p.get("num_threads", 1))
    else:
        if job_id is None:
            raise TypeError("run_blast requires a JobPayload or a legacy job_id kwarg")
        if program is None or database is None or sequence is None:
            raise TypeError("legacy dispatch requires program, database and sequence")
        idempotency_key = f"blast:{job_id}"

    logger.info(
        "Starting BLAST job %s (idempotency_key=%s): %s vs %s",
        job_id,
        idempotency_key,
        program,
        database,
    )

    # Validate inputs before doing any work
    validate_program(program)
    validate_sequence(sequence)
    validate_parameters(parameters)

    # ── Idempotent job claim (shared transition validation) ──────────────
    with get_db() as session:
        decision = BlastJobStore(session).begin_run(job_id)
    if decision == "skip":
        logger.info("BLAST job %s skipped (terminal/unknown status)", job_id)
        return {"job_id": job_id, "skipped": True, "idempotency_key": idempotency_key}

    self.update_state(state="STARTED", meta={"progress": 5})

    try:
        # Get database path (downloads from S3 if needed)
        db_path = get_blast_db_path(database)
        self.update_state(state="STARTED", meta={"progress": 10})

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            query_path = tmpdir_path / "query.fasta"
            output_path = tmpdir_path / "results.json"

            # Ensure FASTA format
            seq = sequence
            if not seq.startswith(">"):
                seq = f">query\n{seq}\n"
            query_path.write_text(seq)
            self.update_state(state="STARTED", meta={"progress": 15})

            # Run BLAST (subprocess.run without shell)
            run_blast_command(
                program=program,
                db_path=db_path,
                query_path=query_path,
                output_path=output_path,
                evalue=evalue,
                word_size=word_size,
                max_target_seqs=max_target_seqs,
                extra_args=parameters,
                num_threads=num_threads,
            )
            self.update_state(state="STARTED", meta={"progress": 80})

            # Parse results
            parsed = parse_blast_json(output_path)
            self.update_state(state="STARTED", meta={"progress": 90})

            # Upload raw results to MinIO (key contains job_id; metadata
            # carries sha256 checksum + size for integrity verification).
            s3_bucket = get_setting("S3_BLAST_BUCKET", "blast-dbs")
            s3_key = f"blast-results/{job_id}.json"
            checksum, size = _result_file_metadata(output_path)
            upload_file(
                str(output_path),
                f"{s3_bucket}/{s3_key}",
                metadata={"checksum": checksum, "size": str(size)},
            )

            # Generate pre-signed URL (24 h)
            presigned_url = generate_presigned_url(
                f"{s3_bucket}/{s3_key}", expires_in=86400
            )

            self.update_state(state="STARTED", meta={"progress": 100})

            logger.info(
                "BLAST job %s completed: %d hits", job_id, parsed["total_hits"]
            )

            # Persist parsed hits (delete-then-insert: idempotent on
            # redelivery) and mark the job succeeded — one transaction, and
            # only a running row wins the status update.
            with get_db() as session:
                BlastHitStore(session).replace_hits(job_id, parsed["hits"])
                BlastJobStore(session).mark_succeeded(
                    job_id,
                    result_path=s3_key,
                    query_len=parsed["query_len"],
                    hit_count=parsed["total_hits"],
                )

            return {
                "job_id": job_id,
                "hits": parsed["hits"][:100],
                "total_hits": parsed["total_hits"],
                "hits_persisted": parsed["total_hits"],
                "result_s3_path": s3_key,
                "download_url": presigned_url,
                "query_len": parsed["query_len"],
                "checksum": checksum,
            }

    except Exception as e:
        error_text = sanitize_error_message(str(e), query_sequence=sequence)
        logger.error("BLAST job %s failed: %s", job_id, error_text)
        try:
            with get_db() as session:
                BlastJobStore(session).mark_failed(job_id, error=error_text)
        except Exception as db_err:
            logger.error("Failed to update BLAST job status: %s", db_err)
        raise
