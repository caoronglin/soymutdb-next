"""scanpy scRNA-seq analysis task for online analyses (single h5ad input).

Execution model (mirrors :mod:`soymutdb_worker.tasks.analyses.fastp`):

- The single input h5ad is downloaded from MinIO (object key under
  ``analyses/{job_id}/input/``) into a private temp dir
  (``TemporaryDirectory`` cleans up on every exit path, including
  exceptions).
- The standard preprocessing + clustering pipeline runs in-process with the
  worker image's scanpy install: ``filter_cells`` / ``filter_genes`` →
  ``normalize_total`` + ``log1p`` → HVG subsetting (``use_hvg``) → ``scale``
  → ``pca`` → ``neighbors`` → ``umap`` → ``leiden`` →
  ``rank_genes_groups``.
- A wall-clock timeout (default 1200 s) is applied to the whole analysis
  phase via ``SIGALRM`` (Celery prefork runs tasks in the child's main
  thread, where POSIX signal timers work); when it fires the pipeline aborts
  with :class:`AnalysisTimeoutError` and the job lands in ``failed``.
- ``scanpy`` (and ``matplotlib``) are imported lazily at run time: the worker
  image installs them (W1-A pyproject), but the module stays importable in
  environments without them (e.g. the local test venv, where tests inject a
  stub via ``monkeypatch``).
- All pipeline parameters pass a whitelist with defaults; unknown parameters
  are rejected, never forwarded.
- On success, ``umap.png`` + ``markers.csv`` are uploaded to
  ``analyses/{job_id}/output/`` and the summary is persisted to
  ``analysis_jobs.result_summary`` through the narrow
  :class:`AnalysisJobStore` repository (guarded status transitions).
- Errors are scrubbed (see :func:`fastp.sanitize_error_message`) before
  persisting to ``error_message``; raw logs are never stored.
- Re-deliveries of the same outbox event (same job) are idempotent: a job
  that already reached a terminal state is skipped.
"""

from __future__ import annotations

import csv
import logging
import signal
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from celery import Task

from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.repositories import AnalysisJobStore
from soymutdb_worker.shared import JobPayload
from soymutdb_worker.tasks.analyses.fastp import sanitize_error_message
from soymutdb_worker.utils.db import get_db
from soymutdb_worker.utils.s3 import get_s3_client, upload_file

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Contract (W1-A owns the canonical constants in ``soymutdb_jobs.contract``;
# these mirror them so this module stays importable without jobs-py installed)
# ---------------------------------------------------------------------------

#: Mirrors ``soymutdb_jobs.contract.ANALYSIS_SCANPY_TASK``.
ANALYSIS_SCANPY_TASK: str = "soymutdb_worker.tasks.analyses.run_scanpy"
#: Mirrors ``soymutdb_jobs.contract.QUEUE_ANALYSES``.
QUEUE_ANALYSES: str = "analyses"

#: MinIO bucket for analysis inputs/outputs.  The API presign service uses
#: the same bucket (``settings.s3_analyses_bucket``, default ``analyses``).
ANALYSES_BUCKET = get_setting("S3_ANALYSES_BUCKET", "analyses")

# ---------------------------------------------------------------------------
# Configuration / limits
# ---------------------------------------------------------------------------

#: Wall-clock cap for the whole analysis phase (download → pipeline → upload).
SCANPY_MAX_RUNTIME = int(get_setting("SCANPY_MAX_RUNTIME", "1200"))  # seconds

#: Output object names under ``analyses/{job_id}/output/``.
_UMAP_NAME = "umap.png"
_MARKERS_NAME = "markers.csv"

#: Whitelisted pipeline parameters with their defaults (payload name →
#: default).  ``min_genes`` / ``min_cells`` / ``n_top_genes`` are counts,
#: ``resolution`` is a positive float, ``use_hvg`` is a boolean.
SCANPY_PARAM_DEFAULTS: dict[str, Any] = {
    "min_genes": 200,  # filter_cells: min genes per cell
    "min_cells": 3,  # filter_genes: min cells per gene
    "n_top_genes": 2000,  # highly_variable_genes n_top_genes
    "resolution": 1.0,  # leiden resolution
    "use_hvg": True,  # subset to highly variable genes before PCA
}

#: Number of top markers per cluster kept in ``result_summary.top_markers``
#: (keeps the JSONB document small; markers.csv carries the full table).
TOP_MARKERS_PER_CLUSTER = 10


class AnalysisTimeoutError(RuntimeError):
    """Raised when the scanpy pipeline exceeds :data:`SCANPY_MAX_RUNTIME`."""


# ---------------------------------------------------------------------------
# Timeout guard
# ---------------------------------------------------------------------------


@contextmanager
def pipeline_timeout(seconds: int) -> Iterator[None]:
    """Wall-clock timeout for the whole analysis phase via ``SIGALRM``.

    The handler raises :class:`AnalysisTimeoutError` from wherever the
    pipeline is executing; the task's ``finally``-free except-path marks the
    job failed.  Only usable from the main thread on POSIX — Celery prefork
    runs tasks there — and degrades to a no-op elsewhere (or on platforms
    without ``SIGALRM``, e.g. Windows).
    """
    if (
        seconds <= 0
        or not hasattr(signal, "SIGALRM")
        or threading.current_thread() is not threading.main_thread()
    ):
        yield
        return

    def _handler(signum: int, frame: Any) -> None:  # noqa: ARG001
        raise AnalysisTimeoutError(
            f"scanpy analysis timed out after {seconds}s"
        )

    previous = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_input_objects(objects: list[str] | None, job_id: str) -> str:
    """Validate and normalize the input object keys.

    Exactly one key is accepted, it must end in ``.h5ad`` and live under
    ``analyses/{job_id}/input/`` (job-scoped, no traversal).  Returns the
    normalized key.
    """
    if not isinstance(objects, list) or len(objects) != 1:
        raise ValueError(
            "scanpy accepts exactly 1 input h5ad object, "
            f"got {len(objects) if isinstance(objects, list) else 'n/a'}"
        )
    key = objects[0]
    if not isinstance(key, str) or not key:
        raise ValueError("input_objects must contain a non-empty string key")
    job_prefix = f"analyses/{job_id}/input/"
    if not key.startswith(job_prefix):
        raise ValueError(
            f"input object {key!r} is outside the job's input prefix "
            f"{job_prefix!r}"
        )
    if ".." in key.split("/"):
        raise ValueError(f"input object key must not contain traversal segments: {key!r}")
    if not key.endswith(".h5ad"):
        raise ValueError(
            f"scanpy input object must be an .h5ad file, got {key!r}"
        )
    return key


def _coerce_int(name: str, value: Any, minimum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer, got {value!r}") from None
    if number < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {number}")
    return number


def _coerce_float(name: str, value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {value!r}") from None
    if number <= 0:
        raise ValueError(f"{name} must be > 0, got {number}")
    return number


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
    raise ValueError(f"use_hvg must be a boolean, got {value!r}")


def validate_params(params: dict | None) -> dict[str, Any]:
    """Validate and normalize the pipeline parameters.

    Every key must be whitelisted (:data:`SCANPY_PARAM_DEFAULTS`); unknown
    parameters raise :class:`ValueError`.  Returns the merged mapping of
    defaults overridden by the validated payload values.
    """
    cleaned: dict[str, Any] = {}
    if params is not None:
        if not isinstance(params, dict):
            raise ValueError("params must be a dict")
        for key, value in params.items():
            if key not in SCANPY_PARAM_DEFAULTS:
                raise ValueError(f"Disallowed scanpy parameter: {key!r}")
            if value is None:
                continue
            if key in ("min_genes", "min_cells", "n_top_genes"):
                cleaned[key] = _coerce_int(key, value, minimum=1)
            elif key == "resolution":
                cleaned[key] = _coerce_float(key, value)
            elif key == "use_hvg":
                cleaned[key] = _coerce_bool(value)
    merged = dict(SCANPY_PARAM_DEFAULTS)
    merged.update(cleaned)
    return merged


# ---------------------------------------------------------------------------
# scanpy import (lazy: the worker image ships it, the local venv does not)
# ---------------------------------------------------------------------------


def _get_scanpy() -> Any:
    """Import scanpy at run time (worker image dependency)."""
    try:
        import scanpy as sc

        return sc
    except ImportError as e:
        raise RuntimeError(
            "scanpy is not installed in the worker image — cannot run "
            "scRNA-seq analysis (see apps/worker/pyproject.toml)"
        ) from e


# ---------------------------------------------------------------------------
# Analysis pipeline
# ---------------------------------------------------------------------------


def _rgg_field(rgg: Any, name: str, group: str, rank: int) -> Any:
    """Read one cell of a scanpy structured array, tolerating missing fields."""
    try:
        return rgg[name][group][rank - 1]
    except (KeyError, TypeError, IndexError):
        return ""


def _write_markers_csv(rgg: Any, group_names: list[str], path: Path) -> None:
    """Flatten scanpy's structured ``rank_genes_groups`` result to CSV.

    One row per (cluster, gene) with columns
    ``cluster,rank,gene,logfoldchange,pvals_adj,score``; the full table is
    uploaded to MinIO (``top_markers`` in the JSON summary is capped).
    """
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["cluster", "rank", "gene", "logfoldchange", "pvals_adj", "score"]
        )
        for group in group_names:
            for rank, gene in enumerate(rgg["names"][group], start=1):
                writer.writerow(
                    [
                        group,
                        rank,
                        gene,
                        _rgg_field(rgg, "logfoldchanges", group, rank),
                        _rgg_field(rgg, "pvals_adj", group, rank),
                        _rgg_field(rgg, "scores", group, rank),
                    ]
                )


def _render_umap_png(sc: Any, adata: Any, path: Path) -> None:
    """Render the UMAP coloured by leiden cluster to *path* (Agg backend)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    axes = sc.pl.umap(adata, color="leiden", show=False)
    if hasattr(axes, "figure"):
        fig = axes.figure
    else:
        fig = axes[0].figure
    fig.savefig(str(path), dpi=150, bbox_inches="tight")
    plt.close(fig)


def run_scanpy_pipeline(
    *,
    input_path: Path,
    output_dir: Path,
    params: dict[str, Any],
    sc: Any,
) -> dict[str, Any]:
    """Run the standard preprocessing + clustering pipeline.

    Returns the plain-JSON ``result_summary`` body (MinIO object keys are
    filled in by the task after the uploads).  *sc* is the scanpy module
    (already imported by the caller), which keeps this function testable
    with a stub.
    """
    logger.info("scanpy: reading h5ad %s", input_path)
    adata = sc.read_h5ad(str(input_path))

    # Preprocessing / filtering (params already validated)
    sc.pp.filter_cells(adata, min_genes=params["min_genes"])
    sc.pp.filter_genes(adata, min_cells=params["min_cells"])
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    if params["use_hvg"]:
        sc.pp.highly_variable_genes(adata, n_top_genes=params["n_top_genes"])
        adata = adata[:, adata.var["highly_variable"]]

    # Dimensionality reduction + clustering
    sc.pp.scale(adata, max_value=10)
    sc.tl.pca(adata, svd_solver="arpack")
    sc.pp.neighbors(adata)
    sc.tl.umap(adata)
    sc.tl.leiden(adata, resolution=params["resolution"])
    sc.tl.rank_genes_groups(adata, groupby="leiden", method="wilcoxon")

    n_cells = int(adata.n_obs)
    n_genes = int(adata.n_vars)

    # Cluster sizes: leiden labels → per-cluster cell counts.
    value_counts = adata.obs["leiden"].value_counts()
    cluster_sizes = {str(k): int(v) for k, v in value_counts.to_dict().items()}

    # Top markers (capped per cluster for the JSON summary).
    rgg = adata.uns["rank_genes_groups"]
    group_names = list(rgg["names"].dtype.names)
    top_markers: dict[str, list[str]] = {}
    for group in group_names:
        top_markers[group] = [
            str(g) for g in rgg["names"][group][:TOP_MARKERS_PER_CLUSTER]
        ]

    # Output artifacts (full markers table + UMAP figure).
    _write_markers_csv(rgg, group_names, output_dir / _MARKERS_NAME)
    _render_umap_png(sc, adata, output_dir / _UMAP_NAME)

    return {
        "n_cells": n_cells,
        "n_genes": n_genes,
        "n_clusters": len(group_names),
        "cluster_sizes": cluster_sizes,
        "top_markers": top_markers,
    }


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name=ANALYSIS_SCANPY_TASK,
    queue=QUEUE_ANALYSES,
)
def run_scanpy(
    self: Task,
    payload: dict | None = None,
    *,
    job_id: str | None = None,
    input_objects: list[str] | None = None,
    params: dict | None = None,
) -> dict:
    """Execute a scanpy scRNA-seq analysis asynchronously.

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
        if job_payload.task_name != ANALYSIS_SCANPY_TASK:
            raise ValueError(
                f"Payload task_name {job_payload.task_name!r} does not match "
                f"task {ANALYSIS_SCANPY_TASK!r}"
            )
        job_id = str(job_payload.job_id)
        p = job_payload.payload
        analysis_type = str(p.get("analysis_type", "scanpy"))
        if analysis_type != "scanpy":
            raise ValueError(
                f"analysis_type {analysis_type!r} is not handled by run_scanpy"
            )
        input_objects = p.get("input_objects")
        params = p.get("params")
        idempotency_key = job_payload.idempotency_key
    else:
        if job_id is None:
            raise TypeError("run_scanpy requires a JobPayload or a legacy job_id kwarg")
        if input_objects is None:
            raise TypeError("legacy dispatch requires input_objects")
        idempotency_key = f"scanpy:{job_id}"

    # Validate inputs before doing any work (raises before the job is claimed
    # so invalid dispatches fail loudly instead of wedging the row).
    key = validate_input_objects(input_objects or [], job_id)
    cleaned_params = validate_params(params)

    logger.info(
        "Starting scanpy job %s (idempotency_key=%s, input=%s)",
        job_id,
        idempotency_key,
        key,
    )

    # ── Idempotent job claim (shared transition validation) ──────────────
    with get_db() as session:
        decision = AnalysisJobStore(session).begin_run(job_id)
    if decision == "skip":
        logger.info("scanpy job %s skipped (terminal/unknown status)", job_id)
        return {"job_id": job_id, "skipped": True, "idempotency_key": idempotency_key}

    self.update_state(state="STARTED", meta={"progress": 5})

    try:
        # Whole analysis phase (download → pipeline → upload) runs under the
        # wall-clock guard; a timeout aborts it with AnalysisTimeoutError and
        # lands the job in failed below.
        with pipeline_timeout(SCANPY_MAX_RUNTIME):
            s3 = get_s3_client()
            with tempfile.TemporaryDirectory(prefix=f"scanpy_{job_id}_") as tmpdir:
                tmp = Path(tmpdir)

                # ── Download input h5ad from MinIO ────────────────────────
                input_path = tmp / "input.h5ad"
                s3.download_file(ANALYSES_BUCKET, key, str(input_path))
                self.update_state(state="STARTED", meta={"progress": 20})

                # ── Run the scanpy pipeline ───────────────────────────────
                sc = _get_scanpy()
                summary = run_scanpy_pipeline(
                    input_path=input_path,
                    output_dir=tmp,
                    params=cleaned_params,
                    sc=sc,
                )
                self.update_state(state="STARTED", meta={"progress": 80})

                # ── Upload artifacts to MinIO (keys contain the job id) ───
                out_prefix = f"analyses/{job_id}/output"
                umap_key = f"{out_prefix}/{_UMAP_NAME}"
                markers_key = f"{out_prefix}/{_MARKERS_NAME}"
                upload_file(str(tmp / _UMAP_NAME), f"{ANALYSES_BUCKET}/{umap_key}")
                upload_file(str(tmp / _MARKERS_NAME), f"{ANALYSES_BUCKET}/{markers_key}")
                summary["umap_png"] = umap_key
                summary["markers_csv"] = markers_key

                self.update_state(state="STARTED", meta={"progress": 100})

                logger.info(
                    "scanpy job %s completed: %s cells, %s clusters",
                    job_id,
                    summary["n_cells"],
                    summary["n_clusters"],
                )

                # ── Persist summary + mark succeeded (guarded, one tx) ────
                with get_db() as session:
                    AnalysisJobStore(session).mark_succeeded(
                        job_id, result_summary=summary
                    )

                return {
                    "job_id": job_id,
                    "skipped": False,
                    "result_summary": summary,
                    "umap_png": umap_key,
                    "markers_csv": markers_key,
                    "idempotency_key": idempotency_key,
                }

    except Exception as e:
        error_text = sanitize_error_message(str(e))
        logger.error("scanpy job %s failed: %s", job_id, error_text)
        try:
            with get_db() as session:
                AnalysisJobStore(session).mark_failed(job_id, error=error_text)
        except Exception as db_err:
            logger.error("Failed to update scanpy job status: %s", db_err)
        raise
