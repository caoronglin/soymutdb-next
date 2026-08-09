"""fastp QC task for online analyses (single-/paired-end FASTQ).

Execution model (mirrors :mod:`soymutdb_worker.tasks.blast`):

- Inputs are downloaded from MinIO (object keys ``analyses/{job_id}/input/``)
  into a private temp dir (``TemporaryDirectory`` cleans up on every exit
  path, including exceptions).
- ``fastp`` is executed with ``subprocess.run`` **without** ``shell=True``,
  a pure argument list, a minimal environment (no ambient secrets), a
  wall-clock timeout and resource limits (memory + output file size) applied
  via ``preexec_fn``.
- All pipeline parameters pass a whitelist mapping (payload name → fastp CLI
  flag); unknown parameters are rejected, never forwarded.
- On success, ``fastp.html`` + ``fastp.json`` are uploaded to
  ``analyses/{job_id}/output/`` in the analyses bucket and the parsed QC
  statistics are persisted to ``analysis_jobs.result_summary`` through the
  narrow :class:`AnalysisJobStore` repository (guarded status transitions:
  queued → running → succeeded/failed).
- Errors are scrubbed (control characters stripped, whitespace collapsed,
  truncated) before persisting to ``error_message``; full logs are never
  stored.
- Re-deliveries of the same outbox event (same job) are idempotent: a job
  that already reached a terminal state is skipped.

The ``fastp`` binary is assumed to be installed in the worker image
(``fastp`` must be on ``PATH``; the Dockerfile change is owned by the W1-A
track).  Presence is checked with :func:`shutil.which` at run time.
"""

from __future__ import annotations

import json
import logging
import os
import resource
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from celery import Task

from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.repositories import AnalysisJobStore
from soymutdb_worker.shared import JobPayload
from soymutdb_worker.tasks.notifications import notify_completed, notify_failed
from soymutdb_worker.utils.db import get_db
from soymutdb_worker.utils.s3 import get_s3_client, upload_file

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Contract (W1-A owns the canonical constants in ``soymutdb_jobs.contract``;
# these mirror them so this module stays importable without jobs-py installed)
# ---------------------------------------------------------------------------

#: Mirrors ``soymutdb_jobs.contract.ANALYSIS_FASTP_TASK``.
ANALYSIS_FASTP_TASK: str = "soymutdb_worker.tasks.analyses.run_fastp"
#: Mirrors ``soymutdb_jobs.contract.QUEUE_ANALYSES``.
QUEUE_ANALYSES: str = "analyses"

#: MinIO bucket for analysis inputs/outputs.  The API presign service uses
#: the same bucket (``settings.s3_analyses_bucket``, default ``analyses``).
ANALYSES_BUCKET = get_setting("S3_ANALYSES_BUCKET", "analyses")

# ---------------------------------------------------------------------------
# Configuration / limits
# ---------------------------------------------------------------------------

FASTP_MAX_RUNTIME = int(get_setting("FASTP_MAX_RUNTIME", "600"))  # seconds
FASTP_MAX_OUTPUT_SIZE = int(
    get_setting("FASTP_MAX_OUTPUT_SIZE", str(1024 * 1024 * 1024))  # 1 GB
)
FASTP_MAX_MEMORY_MB = int(get_setting("FASTP_MAX_MEMORY_MB", "4096"))
#: A fastp.json report should stay far below this; cap parsing to avoid
#: pathological files (RLIMIT_FSIZE already caps the raw output).
FASTP_MAX_JSON_SIZE = int(get_setting("FASTP_MAX_JSON_SIZE", str(64 * 1024 * 1024)))

#: Max characters of error text persisted to ``analysis_jobs.error_message``.
MAX_ERROR_LENGTH = 4000

#: Minimal environment for the fastp child process: only a PATH is needed;
#: anything else from the worker's environment (tokens, keys, …) must not
#: leak into the child.
FASTP_SUBPROCESS_ENV = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "HOME": "/tmp",
    "TMPDIR": "/tmp",
    "LANG": "C",
}

#: Whitelisted pipeline parameters: payload name → fastp CLI flag.
#: Value-taking flags get ``[flag, str(value)]``; boolean flags (``cut_*``,
#: ``detect_adapter_for_pe``, ``trim_poly_g``) are passed as bare flags when
#: truthy and omitted when falsy (fastp defaults them to off).
FASTP_PARAM_FLAGS: dict[str, str] = {
    # Read trimming
    "trim_front1": "--trim_front1",
    "trim_tail1": "--trim_tail1",
    "trim_front2": "--trim_front2",
    "trim_tail2": "--trim_tail2",
    # Quality filtering
    "quality_phred": "--qualified_quality_phred",
    "unqualified_percent_limit": "--unqualified_percent_limit",
    "n_base_limit": "--n_base_limit",
    "min_length": "--length_required",
    "max_length": "--length_limit",
    "average_qual": "--average_qual",
    # Sliding-window cutting
    "cut_front": "--cut_front",
    "cut_tail": "--cut_tail",
    "cut_right": "--cut_right",
    "cut_window_size": "--cut_window_size",
    "cut_mean_quality": "--cut_mean_quality",
    # Adapter trimming
    "adapter_sequence": "--adapter_sequence",
    "adapter_sequence_r2": "--adapter_sequence_r2",
    "detect_adapter_for_pe": "--detect_adapter_for_pe",
    "trim_poly_g": "--trim_poly_g",
    # Concurrency (maps to fastp's --thread)
    "thread": "--thread",
}

#: Parameters that are bare flags (no value on the command line).
FASTP_BOOL_PARAMS = frozenset(
    {"cut_front", "cut_tail", "cut_right", "detect_adapter_for_pe", "trim_poly_g"}
)
#: CLI flags corresponding to :data:`FASTP_BOOL_PARAMS`.
FASTP_BOOL_FLAGS = frozenset(FASTP_PARAM_FLAGS[name] for name in FASTP_BOOL_PARAMS)

#: Fastq reads extension map (R1/R2 placeholders for the CLI).
_IN_R1, _IN_R2 = "input_R1.fastq.gz", "input_R2.fastq.gz"
_OUT_R1, _OUT_R2 = "output_R1.fastq.gz", "output_R2.fastq.gz"
_JSON_NAME, _HTML_NAME = "fastp.json", "fastp.html"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def sanitize_error_message(message: str, max_len: int = MAX_ERROR_LENGTH) -> str:
    """Scrub and truncate an error message before it is persisted/logged.

    Drops control characters, collapses whitespace and caps the length so
    ``analysis_jobs.error_message`` never echoes raw child output verbatim.
    """
    message = "".join(ch for ch in message if ch.isprintable() or ch in "\n\t")
    message = " ".join(message.split())
    return message[:max_len]


def validate_input_objects(objects: list[str], job_id: str) -> list[str]:
    """Validate and normalize the input object keys.

    Every key must live under ``analyses/{job_id}/input/`` (job-scoped, no
    traversal), and exactly one (single-end) or two (paired-end) keys are
    accepted.  Returns the normalized keys (in processing order).
    """
    if not isinstance(objects, list) or not objects:
        raise ValueError("input_objects must be a non-empty list")
    if len(objects) not in (1, 2):
        raise ValueError(
            f"fastp accepts exactly 1 (single-end) or 2 (paired-end) input "
            f"objects, got {len(objects)}"
        )
    job_prefix = f"analyses/{job_id}/input/"
    normalized: list[str] = []
    for key in objects:
        if not isinstance(key, str) or not key:
            raise ValueError("input_objects must contain non-empty string keys")
        if not key.startswith(job_prefix):
            raise ValueError(
                f"input object {key!r} is outside the job's input prefix "
                f"{job_prefix!r}"
            )
        if ".." in key.split("/"):
            raise ValueError(f"input object key must not contain traversal segments: {key!r}")
        normalized.append(key)
    return normalized


def validate_params(params: dict | None) -> dict[str, str]:
    """Validate that every parameter key is whitelisted.

    Returns a cleaned mapping ``{cli_flag: str_value}`` ready to be appended
    to the fastp argument list (boolean flags map to ``"true"``).
    """
    if not params:
        return {}
    cleaned: dict[str, str] = {}
    for key, value in params.items():
        if key not in FASTP_PARAM_FLAGS:
            raise ValueError(f"Disallowed fastp parameter: {key!r}")
        if value is None:
            continue
        if key in FASTP_BOOL_PARAMS:
            # Bare flag when truthy; omitted when falsy.
            if bool(value):
                cleaned[FASTP_PARAM_FLAGS[key]] = "true"
        else:
            cleaned[FASTP_PARAM_FLAGS[key]] = str(value)
    return cleaned


# ---------------------------------------------------------------------------
# fastp execution
# ---------------------------------------------------------------------------


def _set_subprocess_limits() -> None:
    """Set memory and file-size limits for the child process via ``resource``.

    Called as a ``preexec_fn`` so limits apply only to the fastp child.
    """
    mem_bytes = FASTP_MAX_MEMORY_MB * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    except (ValueError, OSError):
        pass  # May not be supported on all platforms
    try:
        resource.setrlimit(
            resource.RLIMIT_FSIZE, (FASTP_MAX_OUTPUT_SIZE, FASTP_MAX_OUTPUT_SIZE)
        )
    except (ValueError, OSError):
        pass


def build_fastp_command(
    *,
    input_paths: list[Path],
    output_paths: list[Path],
    json_path: Path,
    html_path: Path,
    params: dict | None,
) -> list[str]:
    """Build the fastp argument list (no shell string involved).

    Single-end: ``fastp -i in.fq.gz -o out.fq.gz -j fastp.json -h fastp.html``
    Paired-end: additionally ``-I`` / ``-O`` for the second mate.
    """
    binary = shutil.which("fastp")
    if binary is None:
        raise RuntimeError(
            "fastp binary not found in PATH — the worker image must install "
            "fastp (see infra/docker/Dockerfile.worker)"
        )
    if len(input_paths) != len(output_paths) or len(input_paths) not in (1, 2):
        raise ValueError("fastp expects exactly 1 or 2 input/output path pairs")

    cmd: list[str] = [binary]
    cmd.extend(["-i", str(input_paths[0]), "-o", str(output_paths[0])])
    if len(input_paths) == 2:
        cmd.extend(["-I", str(input_paths[1]), "-O", str(output_paths[1])])
    cmd.extend(["-j", str(json_path), "-h", str(html_path)])

    cleaned = validate_params(params)
    for flag, value in cleaned.items():
        if value == "true" and flag in FASTP_BOOL_FLAGS:
            cmd.append(flag)
        else:
            cmd.extend([flag, value])
    return cmd


def run_fastp_command(
    *,
    input_paths: list[Path],
    output_paths: list[Path],
    json_path: Path,
    html_path: Path,
    params: dict | None = None,
) -> None:
    """Run fastp with ``subprocess.run`` (no shell, isolated environment)."""
    cmd = build_fastp_command(
        input_paths=input_paths,
        output_paths=output_paths,
        json_path=json_path,
        html_path=html_path,
        params=params,
    )
    logger.info("Running fastp: %s", " ".join(cmd))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=FASTP_MAX_RUNTIME,
        preexec_fn=_set_subprocess_limits,
        env=FASTP_SUBPROCESS_ENV,
        shell=False,
    )
    if result.returncode != 0:
        stderr_scrubbed = sanitize_error_message(
            result.stderr or f"exit code {result.returncode}"
        )
        logger.error("fastp failed (rc=%d): %s", result.returncode, stderr_scrubbed)
        raise RuntimeError(
            f"fastp execution failed (rc={result.returncode}): {stderr_scrubbed}"
        )


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------


def parse_fastp_json(path: Path) -> dict[str, Any]:
    """Parse a fastp JSON report into the ``result_summary`` document.

    fastp >= 0.23 nests everything under ``summary``; older releases keep
    ``before_filtering`` / ``after_filtering`` at the top level — both are
    handled.  The returned document is plain JSON:

    ``before_filtering`` / ``after_filtering`` hold ``reads``, ``bases``,
    ``q30_rate`` and ``duplication`` (duplication is only computed by fastp
    before filtering); ``output`` carries the uploaded object keys.
    """
    if path.stat().st_size > FASTP_MAX_JSON_SIZE:
        raise RuntimeError(
            f"fastp.json exceeds the {FASTP_MAX_JSON_SIZE}-byte parsing cap"
        )
    with open(path) as f:
        data = json.load(f)
    summary = data.get("summary") or data

    def _stats(block: dict) -> dict[str, Any]:
        return {
            "reads": block.get("total_reads"),
            "bases": block.get("total_bases"),
            "q30_rate": block.get("q30_rate"),
            "duplication": block.get("duplication_rate"),
        }

    before = _stats(summary.get("before_filtering") or {})
    after = _stats(summary.get("after_filtering") or {})
    filtering = summary.get("filtering_result") or {}

    return {
        "before_filtering": before,
        "after_filtering": after,
        "filtering_result": {
            "passed_filter_reads": filtering.get("passed_filter_reads"),
            "low_quality_reads": filtering.get("low_quality_reads"),
            "too_many_N_reads": filtering.get("too_many_N_reads"),
            "too_short_reads": filtering.get("too_short_reads"),
        },
        "output": {},  # filled by the task with the uploaded object keys
    }


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name=ANALYSIS_FASTP_TASK,
    queue=QUEUE_ANALYSES,
)
def run_fastp(
    self: Task,
    payload: dict | None = None,
    *,
    job_id: str | None = None,
    input_objects: list[str] | None = None,
    params: dict | None = None,
) -> dict:
    """Execute a fastp QC run asynchronously.

    Two call styles are accepted:

    1. **Outbox contract** (canonical): ``payload`` is a serialized
       :class:`soymutdb_jobs.schemas.JobPayload` whose ``payload`` carries
       the analysis fields (``job_id``, ``analysis_type``, ``input_objects``,
       ``params``).
    2. **Legacy kwargs** (compat for direct dispatches): ``job_id`` /
       ``input_objects`` / ``params``.

    Job status advances queued -> running -> succeeded/failed through the
    shared state machine and the narrow :class:`AnalysisJobStore` repository;
    re-deliveries of the same event (same job) are skipped once the job is
    terminal.
    """
    # ── Resolve payload (outbox contract) or legacy kwargs ────────────────
    if payload is not None:
        job_payload = JobPayload.model_validate(payload)
        if job_payload.task_name != ANALYSIS_FASTP_TASK:
            raise ValueError(
                f"Payload task_name {job_payload.task_name!r} does not match "
                f"task {ANALYSIS_FASTP_TASK!r}"
            )
        job_id = str(job_payload.job_id)
        p = job_payload.payload
        analysis_type = str(p.get("analysis_type", "fastp"))
        if analysis_type != "fastp":
            raise ValueError(
                f"analysis_type {analysis_type!r} is not handled by run_fastp"
            )
        input_objects = p.get("input_objects")
        params = p.get("params")
        idempotency_key = job_payload.idempotency_key
    else:
        if job_id is None:
            raise TypeError("run_fastp requires a JobPayload or a legacy job_id kwarg")
        if input_objects is None:
            raise TypeError("legacy dispatch requires input_objects")
        idempotency_key = f"fastp:{job_id}"

    # Validate inputs before doing any work (raises before the job is claimed
    # so invalid dispatches fail loudly instead of wedging the row).
    keys = validate_input_objects(input_objects or [], job_id)
    cleaned_params = validate_params(params)
    paired = len(keys) == 2

    logger.info(
        "Starting fastp job %s (idempotency_key=%s, paired=%s)",
        job_id,
        idempotency_key,
        paired,
    )

    # ── Idempotent job claim (shared transition validation) ──────────────
    with get_db() as session:
        decision = AnalysisJobStore(session).begin_run(job_id)
    if decision == "skip":
        logger.info("fastp job %s skipped (terminal/unknown status)", job_id)
        return {"job_id": job_id, "skipped": True, "idempotency_key": idempotency_key}

    self.update_state(state="STARTED", meta={"progress": 5})

    try:
        s3 = get_s3_client()
        with tempfile.TemporaryDirectory(prefix=f"fastp_{job_id}_") as tmpdir:
            tmp = Path(tmpdir)

            # ── Download inputs from MinIO ────────────────────────────────
            rel_names = [_IN_R1, _IN_R2][: len(keys)]
            input_paths = [tmp / name for name in rel_names]
            for key, local in zip(keys, input_paths):
                s3.download_file(ANALYSES_BUCKET, key, str(local))
            self.update_state(state="STARTED", meta={"progress": 20})

            # ── Run fastp (no shell, isolated env, limits) ────────────────
            # ``params`` is validated again inside ``run_fastp_command``
            # (single source of truth for CLI construction); the earlier
            # ``validate_params`` call above is a fail-fast check only.
            output_paths = [tmp / name for name in ([_OUT_R1, _OUT_R2][: len(keys)])]
            json_path = tmp / _JSON_NAME
            html_path = tmp / _HTML_NAME
            run_fastp_command(
                input_paths=input_paths,
                output_paths=output_paths,
                json_path=json_path,
                html_path=html_path,
                params=params,
            )
            self.update_state(state="STARTED", meta={"progress": 80})

            # ── Parse QC statistics ───────────────────────────────────────
            summary = parse_fastp_json(json_path)
            self.update_state(state="STARTED", meta={"progress": 90})

            # ── Upload report + stats to MinIO (key contains the job id) ──
            out_prefix = f"analyses/{job_id}/output"
            json_key = f"{out_prefix}/{_JSON_NAME}"
            html_key = f"{out_prefix}/{_HTML_NAME}"
            upload_file(str(json_path), f"{ANALYSES_BUCKET}/{json_key}")
            upload_file(str(html_path), f"{ANALYSES_BUCKET}/{html_key}")
            summary["output"] = {"html": html_key, "json": json_key}

            self.update_state(state="STARTED", meta={"progress": 100})

            logger.info(
                "fastp job %s completed: %s reads before filtering",
                job_id,
                summary["before_filtering"].get("reads"),
            )

            # ── Persist summary + mark succeeded (guarded, one tx) ────────
            with get_db() as session:
                AnalysisJobStore(session).mark_succeeded(
                    job_id, result_summary=summary
                )

            # In-app + optional desktop notification (D2); anonymous jobs
            # (no user_id) are skipped internally.
            notify_completed(job_id, kind="fastp")

            return {
                "job_id": job_id,
                "skipped": False,
                "result_summary": summary,
                "html_object": html_key,
                "json_object": json_key,
                "idempotency_key": idempotency_key,
            }

    except Exception as e:
        error_text = sanitize_error_message(str(e))
        logger.error("fastp job %s failed: %s", job_id, error_text)
        try:
            with get_db() as session:
                AnalysisJobStore(session).mark_failed(job_id, error=error_text)
        except Exception as db_err:
            logger.error("Failed to update fastp job status: %s", db_err)
        notify_failed(job_id, kind="fastp", error=error_text)
        raise
