"""scanpy task tests: execution, MinIO I/O, result_summary, failure paths.

No docker, no DB, no real scanpy/numpy/matplotlib: a stub scanpy module
(MagicMock) is injected via ``monkeypatch`` of ``_get_scanpy``, the S3
client is faked, and job status lives in a fake session.  Covers idempotent
re-delivery, parameter whitelisting/defaults, the result_summary contract,
scrubbed failures, the timeout path and Celery registration.
"""

from __future__ import annotations

import signal
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from soymutdb_worker.shared import JobPayload
from soymutdb_worker.tasks.analyses import scanpy as scanpy_module
from soymutdb_worker.tasks.analyses.scanpy import (
    ANALYSIS_SCANPY_TASK,
    AnalysisTimeoutError,
)


class _FakeResult:
    def __init__(self, rows: list, rowcount: int | None = None):
        self._rows = rows
        self.rowcount = rowcount

    def first(self):
        return self._rows[0] if self._rows else None


def _extract(value):
    """Unwrap BindParameter / enum members to plain values."""
    while hasattr(value, "value") and not isinstance(value, str):
        value = value.value
    return value


class FakeSession:
    """Tracks status/result_summary writes against ``analysis_jobs``."""

    def __init__(self, status: str | None = "queued", rowcount: int = 1):
        self.status = status
        self.rowcount = rowcount
        self.result_summary: Any = None
        self.error_message: str | None = None

    def execute(self, stmt, params=None):
        table = getattr(stmt, "table", None)
        if table is not None and table.name == "analysis_jobs":
            values = {
                getattr(k, "name", k): _extract(v)
                for k, v in dict(getattr(stmt, "_values", {}) or {}).items()
            }
            if "status" in values:
                self.status = values["status"]
            if "result_summary" in values:
                self.result_summary = values["result_summary"]
            if "error_message" in values:
                self.error_message = values["error_message"]
            return _FakeResult([], rowcount=self.rowcount)
        return _FakeResult(
            [(self.status,)] if self.status is not None else [], rowcount=self.rowcount
        )


class FakeTask:
    def __init__(self):
        self.states = []

    def update_state(self, **kwargs):
        self.states.append(kwargs)


class FakeS3:
    """Stands in for the boto3 client: downloads write local files."""

    def __init__(self):
        self.downloads: list[tuple[str, str, str]] = []

    def download_file(self, bucket: str, key: str, local_path: str):
        self.downloads.append((bucket, key, local_path))
        Path(local_path).write_bytes(b"fake h5ad bytes")


def _call_task(task: Any, *args, **kwargs):
    """Invoke the raw task function (bypassing Celery's bound-task wrapper)."""
    return task.run.__func__(*args, **kwargs)


def _payload(
    job_id: str | None = None,
    task_name: str = ANALYSIS_SCANPY_TASK,
    input_objects: list[str] | None = None,
    params: dict | None = None,
    analysis_type: str = "scanpy",
) -> dict:
    job_id = job_id or str(uuid.uuid4())
    now = datetime.now(UTC)
    keys = input_objects or [f"analyses/{job_id}/input/matrix.h5ad"]
    p = JobPayload(
        job_id=job_id,
        task_name=task_name,
        payload={
            "job_id": job_id,
            "analysis_type": analysis_type,
            "input_objects": keys,
            "params": params or {},
        },
        idempotency_key=f"scanpy:{job_id}",
        created_at=now,
        updated_at=now,
    )
    return p.model_dump(mode="json")


@contextmanager
def _fake_db(session: FakeSession):
    yield session


# ---------------------------------------------------------------------------
# Fake scanpy
# ---------------------------------------------------------------------------


class _FakeRGNames:
    """Structured-array stand-in: ``names[group]`` -> list of genes."""

    def __init__(self, groups, n_genes: int):
        self.dtype = SimpleNamespace(names=list(groups))
        self._n = n_genes

    def __getitem__(self, group: str):
        return [f"gene_{group}_{i}" for i in range(self._n)]


class _FakeRGField:
    """Structured-array stand-in for logfoldchanges/pvals_adj/scores."""

    def __init__(self, n_genes: int):
        self._n = n_genes

    def __getitem__(self, group: str):
        return [round(0.5 + i / 10, 3) for i in range(self._n)]


def _fake_adata(
    n_cells: int = 100,
    n_genes: int = 50,
    groups: tuple = ("0", "1"),
    n_marker_genes: int = 12,
):
    """A fake AnnData: real scalar attrs + MagicMock elsewhere.

    ``adata[:, mask]`` returns the same object so the HVG subsetting step
    keeps the configured ``n_obs`` / ``n_vars`` for the summary.
    """
    adata = MagicMock()
    adata.n_obs = n_cells
    adata.n_vars = n_genes
    adata.__getitem__.return_value = adata
    adata.obs["leiden"].value_counts.return_value.to_dict.return_value = {
        "0": 60,
        "1": 40,
    }
    # A real dict so uns["rank_genes_groups"] survives MagicMock __getitem__.
    adata.uns = {
        "rank_genes_groups": {
            "names": _FakeRGNames(groups, n_marker_genes),
            "logfoldchanges": _FakeRGField(n_marker_genes),
            "pvals_adj": _FakeRGField(n_marker_genes),
            "scores": _FakeRGField(n_marker_genes),
        }
    }
    return adata


def _fake_scanpy(adata: Any) -> MagicMock:
    """A scanpy stand-in: pp/tl/pl submodules auto-mock; read_h5ad wired."""
    sc = MagicMock()
    sc.read_h5ad.return_value = adata
    return sc


def _monkeypatch_environment(
    monkeypatch,
    session: FakeSession,
    captured: dict | None = None,
    *,
    pipeline_error: Exception | None = None,
    scanpy_missing: bool = False,
) -> dict:
    """Wire fakes for S3, DB, scanpy and the matplotlib renderer."""
    captured = captured if captured is not None else {}
    monkeypatch.setattr(scanpy_module, "ANALYSES_BUCKET", "analyses")
    monkeypatch.setattr(scanpy_module, "get_db", lambda: _fake_db(session))
    s3 = FakeS3()
    monkeypatch.setattr(scanpy_module, "get_s3_client", lambda: s3)
    captured["s3"] = s3
    uploads = []
    monkeypatch.setattr(
        scanpy_module,
        "upload_file",
        lambda local, s3path, **kw: uploads.append(s3path),
    )
    captured["uploads"] = uploads

    if scanpy_missing:
        def missing() -> Any:
            raise RuntimeError(
                "scanpy is not installed in the worker image - cannot run "
                "scRNA-seq analysis"
            )

        monkeypatch.setattr(scanpy_module, "_get_scanpy", missing)
    else:
        adata = _fake_adata()
        sc = _fake_scanpy(adata)
        captured["sc"] = sc
        captured["adata"] = adata
        monkeypatch.setattr(scanpy_module, "_get_scanpy", lambda: sc)

    if pipeline_error is not None:
        def boom(*a: Any, **kw: Any) -> Any:
            raise pipeline_error

        monkeypatch.setattr(scanpy_module, "run_scanpy_pipeline", boom)

    # The real renderer needs matplotlib (absent locally) - stub it to
    # produce a small PNG in the temp dir (upload_file is mocked anyway).
    def fake_render(sc_m: Any, adata_m: Any, path: Path):
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\nfake-umap-png")

    monkeypatch.setattr(scanpy_module, "_render_umap_png", fake_render)
    return captured


# ---------------------------------------------------------------------------
# Registration / idempotency
# ---------------------------------------------------------------------------


def test_task_is_registered_with_analyses_queue() -> None:
    from soymutdb_worker.main import celery_app

    assert ANALYSIS_SCANPY_TASK in celery_app.tasks
    task = celery_app.tasks[ANALYSIS_SCANPY_TASK]
    assert task.name == ANALYSIS_SCANPY_TASK
    assert task.queue == "analyses"


def test_redelivery_of_succeeded_job_is_skipped(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="succeeded")
    captured = _monkeypatch_environment(monkeypatch, session)

    result = _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)

    assert result["skipped"] is True
    assert session.status == "succeeded"
    # No pipeline work, no uploads, no downloads.
    assert captured["sc"].read_h5ad.call_count == 0
    assert captured["uploads"] == []
    assert captured["s3"].downloads == []


def test_cancelled_job_is_skipped(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="cancelled")
    _monkeypatch_environment(monkeypatch, session)

    result = _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)

    assert result["skipped"] is True


def test_missing_job_row_is_skipped(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status=None)
    _monkeypatch_environment(monkeypatch, session)

    result = _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)

    assert result["skipped"] is True

# ---------------------------------------------------------------------------
# Success paths
# ---------------------------------------------------------------------------


def test_successful_run_uploads_and_summarizes(monkeypatch) -> None:
    """Outputs uploaded under analyses/{job}/output/, summary persisted."""
    payload = _payload()
    job_id = payload["payload"]["job_id"]
    session = FakeSession(status="queued")
    captured = _monkeypatch_environment(monkeypatch, session)

    result = _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)

    assert result["skipped"] is False
    assert result["umap_png"] == f"analyses/{job_id}/output/umap.png"
    assert result["markers_csv"] == f"analyses/{job_id}/output/markers.csv"
    # Both outputs uploaded to the analyses bucket under the job output prefix.
    assert captured["uploads"] == [
        f"analyses/analyses/{job_id}/output/umap.png",
        f"analyses/analyses/{job_id}/output/markers.csv",
    ]
    # The single download came from the job-scoped input prefix.
    assert len(captured["s3"].downloads) == 1
    assert captured["s3"].downloads[0][1] == f"analyses/{job_id}/input/matrix.h5ad"
    assert captured["s3"].downloads[0][2].endswith("input.h5ad")
    # read_h5ad consumed the downloaded local path.
    read_path = captured["sc"].read_h5ad.call_args[0][0]
    assert read_path.endswith("input.h5ad")
    # Result summary persisted on the job row.
    assert session.status == "succeeded"
    assert session.result_summary is not None
    summary = session.result_summary
    assert summary["n_cells"] == 100
    assert summary["n_genes"] == 50
    assert summary["n_clusters"] == 2
    assert summary["cluster_sizes"] == {"0": 60, "1": 40}
    assert summary["umap_png"] == f"analyses/{job_id}/output/umap.png"
    assert summary["markers_csv"] == f"analyses/{job_id}/output/markers.csv"
    # top_markers capped at 10 genes per cluster, ordered.
    assert set(summary["top_markers"]) == {"0", "1"}
    for group in ("0", "1"):
        assert len(summary["top_markers"][group]) == 10
        assert summary["top_markers"][group][0] == f"gene_{group}_0"
        assert summary["top_markers"][group][9] == f"gene_{group}_9"
    assert result["result_summary"] == summary


def test_default_params_applied(monkeypatch) -> None:
    """Empty params use the whitelist defaults."""
    payload = _payload(params={})
    session = FakeSession(status="queued")
    captured = _monkeypatch_environment(monkeypatch, session)
    sc = captured["sc"]
    adata = captured["adata"]

    _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)

    sc.pp.filter_cells.assert_called_once_with(adata, min_genes=200)
    sc.pp.filter_genes.assert_called_once_with(adata, min_cells=3)
    sc.pp.normalize_total.assert_called_once_with(adata, target_sum=1e4)
    sc.pp.log1p.assert_called_once_with(adata)
    # use_hvg defaults to True -> HVG + subsetting happen.
    sc.pp.highly_variable_genes.assert_called_once_with(
        adata, n_top_genes=2000
    )
    adata.__getitem__.assert_called()
    sc.pp.scale.assert_called_once_with(adata, max_value=10)
    sc.tl.pca.assert_called_once_with(adata, svd_solver="arpack")
    sc.pp.neighbors.assert_called_once_with(adata)
    sc.tl.umap.assert_called_once_with(adata)
    sc.tl.leiden.assert_called_once_with(adata, resolution=1.0)
    sc.tl.rank_genes_groups.assert_called_once_with(
        adata, groupby="leiden", method="wilcoxon"
    )
    assert session.status == "succeeded"


def test_param_override_and_hvg_off(monkeypatch) -> None:
    """Explicit params override defaults; use_hvg=False skips HVG."""
    payload = _payload(
        params={"min_genes": 100, "resolution": 0.5, "use_hvg": False}
    )
    session = FakeSession(status="queued")
    captured = _monkeypatch_environment(monkeypatch, session)
    sc = captured["sc"]
    adata = captured["adata"]

    _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)

    sc.pp.filter_cells.assert_called_once_with(adata, min_genes=100)
    sc.tl.leiden.assert_called_once_with(adata, resolution=0.5)
    sc.pp.highly_variable_genes.assert_not_called()
    adata.__getitem__.assert_not_called()
    assert session.status == "succeeded"


def test_string_params_are_coerced(monkeypatch) -> None:
    """Numeric strings are coerced to int/float; bool strings to bool."""
    payload = _payload(
        params={
            "min_genes": "150",
            "n_top_genes": "500",
            "resolution": "2.5",
            "use_hvg": "true",
        }
    )
    session = FakeSession(status="queued")
    captured = _monkeypatch_environment(monkeypatch, session)
    sc = captured["sc"]
    adata = captured["adata"]

    _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)

    sc.pp.filter_cells.assert_called_once_with(adata, min_genes=150)
    sc.pp.highly_variable_genes.assert_called_once_with(adata, n_top_genes=500)
    sc.tl.leiden.assert_called_once_with(adata, resolution=2.5)
    assert session.status == "succeeded"


def test_legacy_kwargs_dispatch_still_works(monkeypatch) -> None:
    job_id = str(uuid.uuid4())
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session)

    result = _call_task(
        scanpy_module.run_scanpy,
        FakeTask(),
        job_id=job_id,
        input_objects=[f"analyses/{job_id}/input/legacy.h5ad"],
        params={"resolution": 2.0},
    )

    assert result["skipped"] is False
    assert result["job_id"] == job_id
    assert session.status == "succeeded"
    assert session.result_summary["n_clusters"] == 2


# ---------------------------------------------------------------------------
# Validation failures (rejected before the job is claimed)
# ---------------------------------------------------------------------------


def test_disallowed_param_is_rejected(monkeypatch) -> None:
    payload = _payload(params={"output": "/etc/passwd"})
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session)

    with pytest.raises(ValueError, match="Disallowed scanpy parameter"):
        _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)

    assert session.status == "queued"


def test_bad_param_values_are_rejected(monkeypatch) -> None:
    for bad in ({"resolution": -1}, {"min_genes": 0}, {"use_hvg": "maybe"}):
        payload = _payload(params=bad)
        session = FakeSession(status="queued")
        _monkeypatch_environment(monkeypatch, session)
        with pytest.raises(ValueError):
            _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)
        assert session.status == "queued"


def test_two_input_objects_rejected(monkeypatch) -> None:
    job_id = str(uuid.uuid4())
    payload = _payload(
        job_id=job_id,
        input_objects=[
            f"analyses/{job_id}/input/a.h5ad",
            f"analyses/{job_id}/input/b.h5ad",
        ],
    )
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session)

    with pytest.raises(ValueError, match="exactly 1 input h5ad object"):
        _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)

    assert session.status == "queued"


def test_non_h5ad_input_rejected(monkeypatch) -> None:
    job_id = str(uuid.uuid4())
    payload = _payload(
        job_id=job_id,
        input_objects=[f"analyses/{job_id}/input/matrix.mtx"],
    )
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session)

    with pytest.raises(ValueError, match="must be an .h5ad file"):
        _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)

    assert session.status == "queued"


def test_input_key_outside_job_prefix_is_rejected(monkeypatch) -> None:
    job_id = str(uuid.uuid4())
    payload = _payload(
        job_id=job_id,
        input_objects=[f"analyses/{uuid.uuid4()}/input/other.h5ad"],
    )
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session)

    with pytest.raises(ValueError, match="outside the job's input prefix"):
        _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)

    assert session.status == "queued"


def test_wrong_task_name_in_payload_is_rejected() -> None:
    payload = _payload(task_name="soymutdb_worker.tasks.analyses.run_fastp")
    with pytest.raises(ValueError, match="does not match"):
        _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)


def test_wrong_analysis_type_is_rejected(monkeypatch) -> None:
    payload = _payload(analysis_type="fastp")
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session)

    with pytest.raises(ValueError, match="not handled by run_scanpy"):
        _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)

    assert session.status == "queued"


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_failed_run_marks_job_failed_with_scrubbed_error(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="queued")
    _monkeypatch_environment(
        monkeypatch,
        session,
        pipeline_error=RuntimeError("\x00\x01boom \t\t  raw scanpy traceback\n\n\n"),
    )

    with pytest.raises(RuntimeError, match="boom"):
        _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)

    assert session.status == "failed"
    assert session.error_message is not None
    assert "boom" in session.error_message
    # Control characters / raw log layout are scrubbed from the stored error.
    assert "\x00" not in session.error_message
    assert "\x01" not in session.error_message
    assert "  " not in session.error_message


def test_timeout_marks_job_failed(monkeypatch) -> None:
    """An AnalysisTimeoutError from the pipeline lands the job in failed."""
    payload = _payload()
    session = FakeSession(status="queued")
    _monkeypatch_environment(
        monkeypatch,
        session,
        pipeline_error=AnalysisTimeoutError("scanpy analysis timed out after 1200s"),
    )

    with pytest.raises(AnalysisTimeoutError):
        _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)

    assert session.status == "failed"
    assert session.error_message is not None
    assert "timed out" in session.error_message


def test_scanpy_missing_marks_job_failed(monkeypatch) -> None:
    """scanpy not importable -> clear RuntimeError and a failed job."""
    payload = _payload()
    session = FakeSession(status="queued")
    _monkeypatch_environment(monkeypatch, session, scanpy_missing=True)

    with pytest.raises(RuntimeError, match="scanpy is not installed"):
        _call_task(scanpy_module.run_scanpy, FakeTask(), payload=payload)

    assert session.status == "failed"
    assert "scanpy is not installed" in (session.error_message or "")


# ---------------------------------------------------------------------------
# Timeout guard / output helpers
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="POSIX only")
def test_pipeline_timeout_fires(monkeypatch) -> None:
    """A real SIGALRM aborts a sleeping pipeline with AnalysisTimeoutError."""
    with pytest.raises(AnalysisTimeoutError, match="timed out after 1s"):
        with scanpy_module.pipeline_timeout(1):
            time.sleep(2)


def test_pipeline_timeout_decorator_wiring(monkeypatch) -> None:
    """pipeline_timeout arms and cancels signal.alarm around the block."""
    alarms: list[int] = []
    monkeypatch.setattr(scanpy_module.signal, "alarm", lambda s: alarms.append(s))

    with scanpy_module.pipeline_timeout(1200):
        pass

    assert alarms == [1200, 0]


def test_pipeline_timeout_disabled_for_nonpositive() -> None:
    with scanpy_module.pipeline_timeout(0):
        pass  # no-op, no exception


def test_write_markers_csv_flattens_rank_genes_groups(tmp_path) -> None:
    from soymutdb_worker.tasks.analyses.scanpy import _write_markers_csv

    groups = ("0", "1")
    rgg = {
        "names": _FakeRGNames(groups, 3),
        "logfoldchanges": _FakeRGField(3),
        "pvals_adj": _FakeRGField(3),
        "scores": _FakeRGField(3),
    }
    path = tmp_path / "markers.csv"
    _write_markers_csv(rgg, list(groups), path)

    lines = path.read_text().splitlines()
    assert lines[0] == "cluster,rank,gene,logfoldchange,pvals_adj,score"
    assert len(lines) == 1 + 2 * 3
    assert lines[1] == "0,1,gene_0_0,0.5,0.5,0.5"
    assert lines[4] == "1,1,gene_1_0,0.5,0.5,0.5"


def test_validate_params_defaults() -> None:
    assert scanpy_module.validate_params(None) == {
        "min_genes": 200,
        "min_cells": 3,
        "n_top_genes": 2000,
        "resolution": 1.0,
        "use_hvg": True,
    }
    assert scanpy_module.validate_params({"use_hvg": False})["use_hvg"] is False
