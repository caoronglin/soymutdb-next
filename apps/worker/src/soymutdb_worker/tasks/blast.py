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
import math
import os
import resource
import shutil
import subprocess
import tempfile
from pathlib import Path

from celery import Task
from soymutdb_jobs.blast_search import normalize_query
from soymutdb_jobs.protein_fasta import ProteinFastaError, parse_protein_fasta

from soymutdb_worker.blast_index import verify_index
from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.repositories import BlastHitStore, BlastJobStore
from soymutdb_worker.shared import BLAST_RUN_TASK, JobPayload
from soymutdb_worker.tasks.notifications import notify_completed, notify_failed
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

#: The one aligner this deployment runs. DIAMOND replaces NCBI BLAST entirely:
#: there is no second engine, no auto-routing and no fallback, so a job cannot
#: end up parsed by a tool it was not built for.
DIAMOND_BIN = Path(get_setting("DIAMOND_BIN", shutil.which("diamond") or "/usr/bin/diamond"))
#: Also the documented default columns; explicit names pin our parser contract.
DIAMOND_OUTFMT6_COLUMNS = (
    "qseqid",
    "sseqid",
    "pident",
    "length",
    "mismatch",
    "gapopen",
    "qstart",
    "qend",
    "sstart",
    "send",
    "evalue",
    "bitscore",
)
#: Parameter name -> DIAMOND's kebab-case flag, for the subset that means the
#: same thing in DIAMOND. Anything not listed is rejected rather than guessed
#: at: passing a flag DIAMOND does not define aborts the run.
DIAMOND_PARAM_FLAGS = {
    "evalue": "--evalue",
    "max_target_seqs": "--max-target-seqs",
    "max_hsps": "--max-hsps",
    "threads": "--threads",
    "query_gencode": "--query-gencode",
    "id": "--id",
    "quiet": "--quiet",
    "gapopen": "--gapopen",
    "gapextend": "--gapextend",
    "matrix": "--matrix",
}
DIAMOND_ALLOWED_PARAMS = frozenset(DIAMOND_PARAM_FLAGS)


#: Multi-genome BLAST database whitelist / path mapping (assembly → index path).
#: Populated from the ``BLAST_DATABASE_PATHS`` setting — a JSON object mapping
#: database name (as stored in ``blast_databases.name``) to the local BLAST
#: index directory on the worker host, e.g.::
#:
#:     {"wm82.a2.v1": "/data/genomes/wm82.a2.v1/wm82.a2.v1",
#:      "zh13.a1.v1": "/data/genomes/zh13.a1.v1/zh13.a1.v1"}
#:
#: This supports ``{assembly}/{assembly}.fasta``-style layouts: the value is
#: the ``diamond makedb`` index basename (without the ``.dmnd`` suffix), not the
#: ``.fasta`` file.  **Data preparation is an ops-side step** — one entry per
#: genome assembly, protein indexes built with ``diamond makedb`` and present
#: on the worker host (or in the S3 ``blast-dbs/`` prefix for legacy
#: downloads).  A ``makeblastdb`` product is not a DIAMOND index and is
#: rejected.
#:
#: When configured, this mapping is the authoritative whitelist: database
#: names outside it are rejected before any filesystem/S3 access.  When empty
#: (legacy single-genome deployments) the legacy cache + S3-download path is
#: used with the strict alphanumeric name check.
def load_database_paths(raw: str) -> dict[str, str]:
    """Invalid operator configuration must not disable the database whitelist."""
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("BLAST_DATABASE_PATHS must be a valid JSON object") from exc
    if not isinstance(parsed, dict) or any(
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(path, str)
        or not path.strip()
        for name, path in parsed.items()
    ):
        raise ValueError("BLAST_DATABASE_PATHS must map nonempty names to nonempty path strings")
    return parsed


BLAST_DATABASE_PATHS = load_database_paths(get_setting("BLAST_DATABASE_PATHS", "{}"))

#: Explicit NCBI catalog mapping, separate from DIAMOND's existing mapping.
#: Values are immutable local prefixes: <root>/<64-character identity>/db.
NCBI_BLAST_DATABASE_PATHS = load_database_paths(get_setting("NCBI_BLAST_DATABASE_PATHS", "{}"))
NCBI_BLAST_BIN_DIR = Path(get_setting("NCBI_BLAST_BIN_DIR", "/usr/bin"))


def get_ncbi_db_path(
    database: str, *, index_identity: str, fasta_sha256: str, database_type: str,
    release_key: str, assembly_id: str,
) -> Path:
    """Resolve only a configured immutable index and verify frozen provenance."""
    configured = NCBI_BLAST_DATABASE_PATHS.get(database)
    if configured is None:
        raise ValueError("NCBI database is not configured on this worker")
    path = Path(configured)
    if not path.is_absolute() or path.name != "db" or path.parent.name != index_identity:
        raise ValueError("NCBI database index identity mismatch")
    verified = verify_index(
        path.parent.parent, index_identity,
        blastdbcmd_bin=NCBI_BLAST_BIN_DIR / "blastdbcmd",
    )
    request = verified["manifest"]["request"]
    metadata = request["metadata"]
    if (
        request["source_sha256"] != fasta_sha256
        or request["db_type"] != database_type
        or str(metadata["release_id"]) != str(release_key)
        or str(metadata["assembly_id"]) != str(assembly_id)
    ):
        raise ValueError("NCBI database provenance mismatch")
    return path


#: Program set per engine. DIAMOND has no nucleotide search, so the four
#: remaining NCBI programs belong to ``ncbi_blast`` and are rejected before any
#: index is touched. One shared set is exactly the bug this replaces: the task
#: routes blastn/blastx/tblastn/tblastx to the NCBI runner, but a blastp-only
#: whitelist refused them first. ``ENGINE_PROGRAMS["diamond"]`` is what this
#: module validates against; it is not the platform program set.
ENGINE_PROGRAMS = {
    #: DIAMOND is protein-to-protein only.
    "diamond": frozenset({"blastp"}),
    #: NCBI BLAST+ runs all five standard searches.
    "ncbi_blast": frozenset({"blastn", "blastp", "blastx", "tblastn", "tblastx"}),
}
#: Union kept under the historical name for callers that probe the vocabulary.
ALLOWED_PROGRAMS = frozenset().union(*ENGINE_PROGRAMS.values())
#: The DIAMOND executable program set, named for the backend it describes.
DIAMOND_PROGRAMS = ENGINE_PROGRAMS["diamond"]

# Resource limits
MAX_QUERY_LENGTH = int(get_setting("BLAST_MAX_QUERY_LENGTH", "100000"))
MAX_OUTPUT_SIZE = int(get_setting("BLAST_MAX_OUTPUT_SIZE", str(512 * 1024 * 1024)))  # 512 MB
MAX_RUNTIME_SECONDS = int(get_setting("BLAST_MAX_RUNTIME", "3600"))  # 1 hour
MAX_MEMORY_MB = int(get_setting("BLAST_MAX_MEMORY_MB", "4096"))  # 4 GB
MAX_THREADS = int(get_setting("BLAST_MAX_THREADS", "4"))
if MAX_THREADS < 1:
    raise ValueError("BLAST_MAX_THREADS must be a positive integer")

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


def validate_program(program: str, engine: str = "diamond") -> str:
    """Validate *program* against the program set of *engine*.

    The engine decides the vocabulary: DIAMOND is protein-only (``blastp``),
    NCBI BLAST+ runs all five standard searches. Validating against the union
    would let a DIAMOND job reach the runner with a program it cannot execute,
    and validating against DIAMOND alone is what made every nucleotide search
    fail before the index was even opened.
    """
    allowed = ENGINE_PROGRAMS.get(engine, ENGINE_PROGRAMS["diamond"])
    if program not in allowed:
        raise ValueError(
            f"Unsupported program: {program!r} for engine {engine!r}; "
            f"allowed: {sorted(allowed)}"
        )
    return program


def _executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _require_diamond() -> Path:
    """Fail loudly instead of silently degrading to a different aligner."""
    if not _executable(DIAMOND_BIN):
        raise RuntimeError(
            f"DIAMOND binary not found or not executable: {DIAMOND_BIN}. "
            "Install diamond-aligner or set SOYMUTDB_DIAMOND_BIN."
        )
    return DIAMOND_BIN


def _positive_threads(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("threads must be a positive integer within BLAST_MAX_THREADS")
    if isinstance(value, str) and not value.isdecimal():
        raise ValueError("threads must be a positive integer within BLAST_MAX_THREADS")
    count = int(value)
    if not 1 <= count <= MAX_THREADS:
        raise ValueError(f"threads must be between 1 and BLAST_MAX_THREADS={MAX_THREADS}")
    return count


def _thread_budget(num_threads: int, parameters: dict, key: str) -> int:
    budget = _positive_threads(num_threads)
    selected = _positive_threads(parameters.pop(key, budget))
    if selected > budget:
        raise ValueError(f"parameter {key!r} exceeds submitted thread budget {budget}")
    return selected


def validate_diamond_parameters(params: dict | None) -> dict:
    """Validate job parameters against DIAMOND's flag vocabulary.

    DIAMOND's vocabulary is narrow and its flags are kebab-case. Anything not
    in :data:`DIAMOND_PARAM_FLAGS` is rejected rather than passed through:
    an unknown flag aborts the search an hour into a queue, and a *known-word*
    BLAST flag such as ``-dust`` fails just as late.
    """
    if not params:
        return {}
    cleaned: dict = {}
    for key, value in params.items():
        if key not in DIAMOND_ALLOWED_PARAMS:
            raise ValueError(f"Disallowed DIAMOND parameter: {key!r}")
        if key == "threads":
            cleaned[key] = str(_positive_threads(value))
            continue
        if key == "quiet":
            if not isinstance(value, bool):
                raise ValueError("DIAMOND quiet must be a boolean")
            cleaned[key] = value
            continue
        if key == "id":
            try:
                identity = float(value)
            except (ValueError, TypeError) as exc:
                raise ValueError("DIAMOND id must be a percentage in [0, 100]") from exc
            if isinstance(value, bool) or not math.isfinite(identity) or not 0 <= identity <= 100:
                raise ValueError("DIAMOND id must be a percentage in [0, 100]")
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif isinstance(value, (int, float, str)):
            text = str(value)
        else:
            raise ValueError(f"Invalid DIAMOND parameter value for {key!r}")
        if "\n" in text or "\r" in text or "\x00" in text:
            raise ValueError(f"Invalid characters in DIAMOND parameter {key!r}")
        cleaned[key] = text
    return cleaned


def validate_sequence(sequence: str) -> str:
    """Validate query sequence length and basic format."""
    if not sequence or not sequence.strip():
        raise ValueError("Query sequence is empty")
    # Strip FASTA headers for length check
    lines = sequence.strip().splitlines()
    seq_body = "".join(part for part in lines if not part.startswith(">"))
    if len(seq_body) > MAX_QUERY_LENGTH:
        raise ValueError(f"Query sequence too long: {len(seq_body)} > {MAX_QUERY_LENGTH}")
    return sequence


# ---------------------------------------------------------------------------
# BLAST database management
# ---------------------------------------------------------------------------


class DatabaseIndexUnavailable(RuntimeError):
    """The selected format is absent; distinct from transport/configuration errors."""


def _index_file(base: Path, suffix: str) -> Path:
    # Append: with_suffix would truncate an assembly version such as wm82.a2.v1.
    return Path(f"{base}{suffix}")


def _nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except FileNotFoundError:
        return False


def _database_ready(base: Path) -> bool:
    path = base if base.suffix == ".dmnd" else _index_file(base, ".dmnd")
    return _nonempty_file(path)


def get_blast_db_path(db_name: str) -> Path:
    """Resolve a whitelisted DIAMOND index; never guess its format.

    Local mappings use a shared index basename (or an explicit .dmnd path).
    Legacy S3 objects remain in blast-dbs/; filenames must be the exact
    ``<db_name>.dmnd`` before an atomic download enters the cache.
    """
    if not db_name:
        raise ValueError("BLAST database name is empty")
    if db_name in BLAST_DATABASE_PATHS:
        mapped = Path(BLAST_DATABASE_PATHS[db_name])
        if not _database_ready(mapped):
            raise DatabaseIndexUnavailable(f"Missing DIAMOND index for {db_name!r}: {mapped}")
        return mapped
    if BLAST_DATABASE_PATHS:
        raise ValueError(
            f"BLAST database {db_name!r} is not in the allowed database "
            f"whitelist: {sorted(BLAST_DATABASE_PATHS)}"
        )
    if not db_name.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"Invalid BLAST database name: {db_name!r}")

    BLAST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    db_path = BLAST_CACHE_DIR / db_name
    if _database_ready(db_path):
        return db_path

    s3_bucket = get_setting("S3_BLAST_BUCKET", "blast-dbs")
    s3_prefix = f"blast-dbs/{db_name}"
    s3 = get_s3_client()
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=s3_bucket, Prefix=s3_prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            filename = Path(key).name
            # Prefix listings can include neighbouring databases/directories.
            if filename != f"{db_name}.dmnd" or key not in {
                f"blast-dbs/{filename}",
                f"{s3_prefix}/{filename}",
            }:
                continue
            local_path = BLAST_CACHE_DIR / filename
            if not local_path.is_file() or local_path.stat().st_size == 0:
                logger.info("Downloading DIAMOND db file: %s", filename)
                with tempfile.NamedTemporaryFile(dir=BLAST_CACHE_DIR, delete=False) as handle:
                    temporary = Path(handle.name)
                try:
                    s3.download_file(s3_bucket, key, str(temporary))
                    temporary.replace(local_path)
                finally:
                    temporary.unlink(missing_ok=True)

    if not _database_ready(db_path):
        raise DatabaseIndexUnavailable(f"Missing DIAMOND index for {db_name!r} after S3 download")
    return db_path


# ---------------------------------------------------------------------------
# DIAMOND execution
# ---------------------------------------------------------------------------


# `preexec_fn` runs inside the forked child, so the limits below can only be set
# on platforms that implement them; a missing RLIMIT is expected and must not
# abort the search. Both clauses therefore catch and ignore. This function was
# unimportable for a while (`except ValueError, OSError:` is Python 2 syntax),
# which is why the worker's per-child limits are only trusted after a real
# subprocess search, not after an import check.


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


def build_diamond_command(
    program: str,
    db_path: Path,
    query_path: Path,
    output_path: Path,
    evalue: float,
    max_target_seqs: int,
    num_threads: int,
    extra_args: dict | None,
) -> list[str]:
    """Argument list for one DIAMOND search (no shell interpolation possible).

    Split out from :func:`run_blast_command` so the exact argv can be asserted
    without spawning a process — the flags are the part most likely to be wrong,
    and they are wrong silently (`--max-target-seqs` misspelled makes DIAMOND
    exit non-zero, but `--evalue` given BLAST's `-evalue` spelling does too, and
    both only surface as an opaque rc=1 an hour into a queue).
    """
    cleaned = validate_diamond_parameters(extra_args)
    threads = _thread_budget(num_threads, cleaned, "threads")
    cmd: list[str] = [
        str(DIAMOND_BIN),
        program,
        "--db",
        str(db_path),
        "--query",
        str(query_path),
        "--out",
        str(output_path),
        "--outfmt",
        "6",
        *DIAMOND_OUTFMT6_COLUMNS,
        # 2.1.14 reserves large per-bin hit buffers. One bin respects RLIMIT_AS
        # on small searches; block-size alone did not fix allocation failures.
        "--bin",
        "1",
    ]
    for key, default in (("evalue", evalue), ("threads", threads)):
        if key not in cleaned:
            cmd.extend([DIAMOND_PARAM_FLAGS[key], str(default)])
    if "max_target_seqs" not in cleaned:
        # DIAMOND defaults to 25; honor the submitted job's limit instead.
        cmd.extend(["--max-target-seqs", str(max_target_seqs)])
    for key, value in cleaned.items():
        if key == "quiet":
            if value:
                cmd.append("--quiet")
        else:
            cmd.extend([DIAMOND_PARAM_FLAGS[key], value])
    return cmd


def run_blast_command(
    program: str,
    db_path: Path,
    query_path: Path,
    output_path: Path,
    evalue: float = 0.001,
    word_size: int | None = None,
    max_target_seqs: int = 100,
    outfmt: int = 15,
    extra_args: dict | None = None,
    num_threads: int = 1,
    engine: str | None = None,
) -> None:
    """Run one DIAMOND search with ``subprocess.run`` (no shell).

    All arguments are passed as a list — never through a shell string — and
    the child runs with a minimal environment (:data:`BLAST_SUBPROCESS_ENV`).

    ``word_size`` / ``outfmt`` / ``engine`` remain in the signature so that a
    queued payload written before the engine was reduced still loads; any
    non-default value is rejected rather than silently ignored.
    """
    # DIAMOND has no nucleotide search: resolve its own program set.
    program = validate_program(program, "diamond")
    if word_size is not None:
        raise ValueError(
            "word_size is a retired NCBI BLAST option; DIAMOND blastp has no equivalent"
        )
    if engine not in (None, "diamond", "auto"):
        raise ValueError(
            f"Unknown aligner {engine!r}; this path runs the DIAMOND backend"
        )
    if outfmt != 15:
        raise ValueError("outfmt is fixed: DIAMOND always writes the 12-column tabular format")
    _require_diamond()
    cmd = build_diamond_command(
        program,
        db_path,
        query_path,
        output_path,
        evalue,
        max_target_seqs,
        num_threads,
        extra_args,
    )

    logger.info("Running diamond %s: %s vs %s", program, db_path.name, query_path.name)

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
        stderr_scrubbed = sanitize_error_message(result.stderr or f"exit code {result.returncode}")
        logger.error("DIAMOND failed (rc=%d): %s", result.returncode, stderr_scrubbed)
        raise RuntimeError(f"DIAMOND execution failed (rc={result.returncode}): {stderr_scrubbed}")


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


def parse_diamond_tabular(output_path: Path) -> dict:
    """Parse DIAMOND's ``--outfmt 6`` output into structured hits.

    This is the only output parser: DIAMOND cannot emit BLAST's ``outfmt 15``,
    and with a single engine there is nothing left to dispatch between.

    Columns are the ones :data:`DIAMOND_OUTFMT6_COLUMNS` asked for:
    qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue
    bitscore.

    ``percent_identity`` is ``pident`` verbatim (DIAMOND already reports a
    percentage); the BLAST parser computed it from identity/length because
    ``outfmt 15`` reports a raw count. Copying that arithmetic here would divide
    a percentage by an alignment length and report ~0.03% identity.
    """
    hits: list[dict] = []
    query_id = ""
    with open(output_path, encoding="utf-8", errors="replace") as handle:
        for line_number, raw in enumerate(handle, 1):
            line = raw.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < len(DIAMOND_OUTFMT6_COLUMNS):
                raise ValueError(
                    f"DIAMOND output line {line_number} has {len(fields)} fields, "
                    f"expected {len(DIAMOND_OUTFMT6_COLUMNS)}"
                )
            (
                qseqid,
                sseqid,
                pident,
                length,
                mismatch,
                gapopen,
                qstart,
                qend,
                sstart,
                send,
                evalue,
                bitscore,
            ) = fields[: len(DIAMOND_OUTFMT6_COLUMNS)]
            query_id = query_id or qseqid
            query_start = int(qstart)
            query_end = int(qend)
            subject_start = int(sstart)
            subject_end = int(send)
            hits.append(
                {
                    "query_id": qseqid,
                    "subject_id": sseqid,
                    "subject_title": "",
                    "percent_identity": float(pident),
                    "alignment_length": int(length),
                    "mismatches": int(mismatch),
                    "gap_opens": int(gapopen),
                    "query_start": query_start,
                    "query_end": query_end,
                    "subject_start": subject_start,
                    "subject_end": subject_end,
                    "evalue": float(evalue),
                    "bit_score": float(bitscore),
                    # Coordinates only encode direction relative to each other,
                    # so a hit whose subject runs backwards is on the minus
                    # strand. BLAST JSON states this explicitly; outfmt 6 does
                    # not.
                    "query_strand": "plus" if query_end >= query_start else "minus",
                    "subject_strand": "plus" if subject_end >= subject_start else "minus",
                }
            )

    return {
        "program": "",
        "version": "",
        "reference": "DIAMOND",
        "search_target": {},
        "query_id": query_id,
        "query_len": 0,
        "hits": hits,
        "total_hits": len(hits),
        "stat": {},
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
    engine: str = "diamond",
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
        # Missing engine means a legacy DIAMOND job, never an implicit reroute.
        engine = str(p.get("engine", "diamond"))
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
    if engine == "diamond":
        validate_program(program, "diamond")
        validate_sequence(sequence)
    elif engine == "ncbi_blast":
        # NCBI runs all five programs and validates its own query alphabet.
        validate_program(program, "ncbi_blast")
        normalize_query(sequence, program, max_length=MAX_QUERY_LENGTH)
    else:
        raise ValueError("Unsupported BLAST engine")

    # ── Idempotent job claim (shared transition validation) ──────────────
    with get_db() as session:
        decision = BlastJobStore(session).begin_run(job_id)
    if decision == "skip":
        logger.info("BLAST job %s skipped (terminal/unknown status)", job_id)
        return {"job_id": job_id, "skipped": True, "idempotency_key": idempotency_key}

    self.update_state(state="STARTED", meta={"progress": 5})

    try:
        # Validate parameters and freeze the index before touching the filesystem.
        if engine == "diamond":
            cleaned = validate_diamond_parameters(parameters)
            db_path = get_blast_db_path(database)
        else:
            if payload is None:
                raise ValueError("NCBI execution requires a versioned provenance payload")
            from soymutdb_worker.ncbi_blast import validate_program_database

            validate_program_database(program, p.get("database_type"))
            db_path = get_ncbi_db_path(
                database, index_identity=p.get("index_identity", ""),
                fasta_sha256=p.get("fasta_sha256", ""),
                database_type=p.get("database_type", ""),
                release_key=p.get("release_key", ""), assembly_id=p.get("assembly_id", ""),
            )
            cleaned = dict(parameters or {})
        self.update_state(state="STARTED", meta={"progress": 10})

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            query_path = tmpdir_path / "query.fasta"
            # DIAMOND writes tabular output; the extension must say so.
            output_path = tmpdir_path / "results.txt"

            # Validate before the filesystem or the search binary is touched.
            # A direct or redelivered dispatch never passes through the API,
            # and DIAMOND reports an empty record as an opaque
            # "Missing fields in input line" only after the job is running.
            # The shared parser is the same owner the API validated with, so
            # acceptance cannot differ between the two.
            if engine == "diamond":
                try:
                    query = parse_protein_fasta(sequence)
                except ProteinFastaError as exc:
                    raise ValueError(f"query_sequence: {exc}") from exc
                query_path.write_text(query.to_fasta)
                self.update_state(state="STARTED", meta={"progress": 15})
                run_blast_command(
                    program=program, db_path=db_path, query_path=query_path,
                    output_path=output_path, evalue=evalue, word_size=word_size,
                    max_target_seqs=max_target_seqs, extra_args=cleaned,
                    num_threads=num_threads,
                )
                parsed = parse_diamond_tabular(output_path)
                parsed["query_len"] = query.query_length
            else:
                from soymutdb_worker.ncbi_blast import run_search

                query = normalize_query(sequence, program, max_length=MAX_QUERY_LENGTH)
                query_path.write_text(query.normalized_fasta)
                self.update_state(state="STARTED", meta={"progress": 15})
                search_parameters = {
                    **cleaned, "evalue": evalue, "max_target_seqs": max_target_seqs,
                    "num_threads": num_threads,
                }
                if word_size is not None:
                    search_parameters["word_size"] = word_size
                parsed = run_search(
                    program=program, db_type=p["database_type"], db_path=db_path,
                    query_path=query_path, output_path=output_path,
                    parameters=search_parameters, bin_dir=NCBI_BLAST_BIN_DIR,
                )
                parsed["query_len"] = query.query_length
            self.update_state(state="STARTED", meta={"progress": 80})
            self.update_state(state="STARTED", meta={"progress": 90})

            # Upload raw results to MinIO (key contains job_id; metadata
            # carries sha256 checksum + size for integrity verification).
            s3_bucket = get_setting("S3_BLAST_BUCKET", "blast-dbs")
            s3_key = f"blast-results/{job_id}.txt"
            checksum, size = _result_file_metadata(output_path)
            upload_file(
                str(output_path),
                f"{s3_bucket}/{s3_key}",
                metadata={"checksum": checksum, "size": str(size)},
            )

            # Generate pre-signed URL (24 h)
            presigned_url = generate_presigned_url(f"{s3_bucket}/{s3_key}", expires_in=86400)

            self.update_state(state="STARTED", meta={"progress": 100})

            logger.info("BLAST job %s completed: %d hits", job_id, parsed["total_hits"])

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
                    execution_metadata=(
                        {"engine": engine, "binary": parsed["binary"],
                         "raw_sha256": checksum, "raw_bytes": size}
                        if engine == "ncbi_blast" and "binary" in parsed else None
                    ),
                )

            # In-app + optional desktop notification (D2): resolves the job
            # owner from the job row; anonymous jobs are skipped internally.
            notify_completed(job_id, kind="blast")

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
        # Notification is best-effort and must never mask the original error.
        try:
            notify_failed(job_id, kind="blast", error=error_text)
        except Exception:
            pass
        raise
