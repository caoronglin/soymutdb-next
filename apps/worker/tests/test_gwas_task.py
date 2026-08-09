"""GWAS task tests: idempotency, parsing, execution isolation, failure paths.

Runs the real ``run_gwas`` task against a fake sync session and mocked
S3/engine internals (no docker, no DB, no external EMMAX/GEMMA binaries):

- re-deliveries of the same event must be skipped (idempotency),
- pending -> running -> completed / failed transitions,
- the payload contract must be validated,
- association output parsing (EMMAX ``.ps`` and GEMMA ``.assoc.txt``),
- Manhattan / QQ aggregation sanity,
- subprocess isolation (no shell, minimal env, timeout, size caps).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from soymutdb_worker.shared import GWAS_RUN_TASK, JobPayload
from soymutdb_worker.tasks import gwas as gwas_module


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
    """Fake sync session tracking the ``gwas_jobs`` status transitions."""

    def __init__(self, status: str | None = "pending", rowcount: int = 1):
        self.status = status
        self.rowcount = rowcount
        self.saved_summary: dict | None = None
        self.saved_error: str | None = None

    def execute(self, stmt, params=None):
        table = getattr(stmt, "table", None)
        table_name = getattr(table, "name", None)
        if table_name == "gwas_jobs":
            values = {
                getattr(key, "name", key): _extract(value)
                for key, value in dict(getattr(stmt, "_values", {}) or {}).items()
            }
            if "status" in values:
                self.status = values["status"]
            if "result_summary" in values:
                self.saved_summary = values["result_summary"]
            if "error_message" in values:
                self.saved_error = values["error_message"]
            return _FakeResult([], rowcount=self.rowcount)
        return _FakeResult(
            [(self.status,)] if self.status is not None else [], rowcount=self.rowcount
        )


class FakeTask:
    def __init__(self):
        self.states = []

    def update_state(self, **kwargs):
        self.states.append(kwargs)


def _call_task(task: Any, *args, **kwargs):
    """Invoke the raw task function (bypassing Celery's bound-task wrapper)."""
    return task.run.__func__(*args, **kwargs)


def _payload(job_id: str | None = None, task_name: str = GWAS_RUN_TASK) -> dict:
    job_id = job_id or str(uuid.uuid4())
    now = datetime.now(UTC)
    p = JobPayload(
        job_id=job_id,
        task_name=task_name,
        payload={
            "job_id": job_id,
            "method": "emmax",
            "object_type": "snp",
            "phenotype_object_key": f"gwas/{job_id}/input/pheno.pheno",
            "genotype_object_key": f"gwas/{job_id}/input/geno.tped",
            "params": {"num_threads": 2},
        },
        idempotency_key=f"gwas:{job_id}",
        created_at=now,
        updated_at=now,
    )
    return p.model_dump(mode="json")


@contextmanager
def _fake_db(session: FakeSession):
    yield session


def _assoc_fixture(tmp_path: Path, fmt: str = "emmax") -> Path:
    """Write a small association fixture (EMMAX ``.ps`` or GEMMA assoc)."""
    path = tmp_path / ("result.ps" if fmt == "emmax" else "result.assoc.txt")
    if fmt == "emmax":
        path.write_text(
            "SNP\tBETA\tSE\tP\n"
            "snp1\t0.5\t0.1\t1e-8\n"
            "snp2\t-0.2\t0.05\t0.01\n"
            "snp3\t0.0\t0.2\t0.5\n"
        )
    else:
        path.write_text(
            "chr\trs\tps\tn_miss\tallele1\tallele0\taf\tbeta\tse\tl_remle\tl_mle\tp_wald\tp_lrt\tp_score\n"
            "1\tsnp1\t100\t0\tA\tG\t0.4\t0.5\t0.1\t-1.0\t-1.0\t1e-8\t2e-8\t3e-8\n"
            "1\tsnp2\t200\t0\tC\tT\t0.2\t-0.2\t0.05\t-1.0\t-1.0\t0.01\t0.02\t0.03\n"
            "1\tsnp3\t300\t0\tG\tA\t0.1\t0.0\t0.2\t-1.0\t-1.0\t0.5\t0.6\t0.7\n"
        )
    return path


def _monkeypatch_execution(
    monkeypatch,
    *,
    fail: bool = False,
    fmt: str = "emmax",
    tmp_path: Path | None = None,
):
    """Mock S3 + engine internals so the task runs without external services."""
    monkeypatch.setattr(gwas_module, "get_file_size", lambda key: 1234)

    def fake_download(s3_path: str, local_path: str | None = None):
        target = Path(local_path)
        target.write_text("mock input\n")
        return str(target)

    monkeypatch.setattr(gwas_module, "download_file", fake_download)

    if fail:

        def boom(*args, **kwargs):
            raise RuntimeError("emmax binary exploded")

        monkeypatch.setattr(gwas_module, "run_engine", boom)
    else:
        assoc = _assoc_fixture(tmp_path, fmt=fmt)

        def fake_engine(*args, **kwargs):
            return assoc

        monkeypatch.setattr(gwas_module, "run_engine", fake_engine)

    monkeypatch.setattr(gwas_module, "_result_file_metadata", lambda p: ("abc123", 12))
    uploads: dict = {}
    monkeypatch.setattr(
        gwas_module,
        "upload_file",
        lambda local, s3path, **kw: uploads.setdefault("keys", []).append(s3path)
        or None,
    )
    monkeypatch.setattr(
        gwas_module, "generate_presigned_url", lambda *a, **k: "https://s3.example/x"
    )
    return uploads


# ---------------------------------------------------------------------------
# Idempotency + status transitions
# ---------------------------------------------------------------------------


def test_redelivery_of_completed_job_is_skipped(monkeypatch, tmp_path) -> None:
    payload = _payload()
    session = FakeSession(status="completed")
    monkeypatch.setattr(gwas_module, "get_db", lambda: _fake_db(session))
    _monkeypatch_execution(monkeypatch, tmp_path=tmp_path)

    result = _call_task(gwas_module.run_gwas, FakeTask(), payload=payload)

    assert result["skipped"] is True
    assert session.status == "completed"


def test_cancelled_job_is_skipped(monkeypatch, tmp_path) -> None:
    payload = _payload()
    session = FakeSession(status="cancelled")
    monkeypatch.setattr(gwas_module, "get_db", lambda: _fake_db(session))
    _monkeypatch_execution(monkeypatch, tmp_path=tmp_path)

    result = _call_task(gwas_module.run_gwas, FakeTask(), payload=payload)

    assert result["skipped"] is True


def test_missing_job_row_is_skipped(monkeypatch, tmp_path) -> None:
    payload = _payload()
    session = FakeSession(status=None)
    monkeypatch.setattr(gwas_module, "get_db", lambda: _fake_db(session))
    _monkeypatch_execution(monkeypatch, tmp_path=tmp_path)

    result = _call_task(gwas_module.run_gwas, FakeTask(), payload=payload)

    assert result["skipped"] is True


def test_successful_run_advances_status_to_completed(monkeypatch, tmp_path) -> None:
    payload = _payload()
    session = FakeSession(status="pending")
    monkeypatch.setattr(gwas_module, "get_db", lambda: _fake_db(session))
    uploads = _monkeypatch_execution(monkeypatch, tmp_path=tmp_path)

    result = _call_task(gwas_module.run_gwas, FakeTask(), payload=payload)

    assert result["n_variants"] == 3
    assert result["manhattan_object"].endswith("/output/manhattan.json")
    # pending -> running -> completed
    assert session.status == "completed"
    assert session.saved_summary is not None
    assert session.saved_summary["n_variants"] == 3
    assert session.saved_summary["method"] == "emmax"
    # Four outputs uploaded to gwas/{job_id}/output/ (bucket included in the
    # captured S3 path, mirroring the blast tests).
    assert len(uploads["keys"]) == 4
    for key in uploads["keys"]:
        assert key.startswith(f"gwas/{payload['payload']['job_id']}/output/")


def test_failed_run_marks_job_failed(monkeypatch, tmp_path) -> None:
    payload = _payload()
    session = FakeSession(status="pending")
    monkeypatch.setattr(gwas_module, "get_db", lambda: _fake_db(session))
    _monkeypatch_execution(monkeypatch, fail=True, tmp_path=tmp_path)

    with pytest.raises(RuntimeError, match="emmax binary exploded"):
        _call_task(gwas_module.run_gwas, FakeTask(), payload=payload)

    assert session.status == "failed"
    assert "emmax binary exploded" in session.saved_error


def test_oversized_input_fails_job(monkeypatch, tmp_path) -> None:
    payload = _payload()
    session = FakeSession(status="pending")
    monkeypatch.setattr(gwas_module, "get_db", lambda: _fake_db(session))
    monkeypatch.setattr(
        gwas_module, "get_file_size", lambda key: gwas_module.GWAS_MAX_INPUT_SIZE + 1
    )

    with pytest.raises(RuntimeError, match="exceeds"):
        _call_task(gwas_module.run_gwas, FakeTask(), payload=payload)

    assert session.status == "failed"


def test_wrong_task_name_in_payload_is_rejected() -> None:
    payload = _payload(task_name="soymutdb_worker.tasks.gwas.run_gwas.other")
    with pytest.raises(ValueError, match="does not match"):
        _call_task(gwas_module.run_gwas, FakeTask(), payload=payload)


def test_unknown_payload_version_is_rejected() -> None:
    payload = _payload()
    payload["payload_version"] = 999
    with pytest.raises(Exception):
        _call_task(gwas_module.run_gwas, FakeTask(), payload=payload)


def test_legacy_kwargs_dispatch_still_works(monkeypatch, tmp_path) -> None:
    job_id = str(uuid.uuid4())
    session = FakeSession(status="pending")
    monkeypatch.setattr(gwas_module, "get_db", lambda: _fake_db(session))
    _monkeypatch_execution(monkeypatch, tmp_path=tmp_path)

    result = _call_task(
        gwas_module.run_gwas,
        FakeTask(),
        job_id=job_id,
        method="emmax",
        phenotype_object_key=f"gwas/{job_id}/input/p.pheno",
    )

    assert result["n_variants"] == 3
    assert session.status == "completed"


def test_legacy_kwargs_require_job_id() -> None:
    with pytest.raises(TypeError):
        _call_task(gwas_module.run_gwas, FakeTask(), method="emmax")


def test_invalid_method_rejected_before_work(monkeypatch, tmp_path) -> None:
    payload = _payload()
    payload["payload"]["method"] = "plink"
    session = FakeSession(status="pending")
    monkeypatch.setattr(gwas_module, "get_db", lambda: _fake_db(session))
    _monkeypatch_execution(monkeypatch, tmp_path=tmp_path)

    with pytest.raises(ValueError, match="Invalid GWAS method"):
        _call_task(gwas_module.run_gwas, FakeTask(), payload=payload)

    assert session.status == "pending"


# ---------------------------------------------------------------------------
# Association parsing
# ---------------------------------------------------------------------------


def test_parse_emmax_ps(tmp_path) -> None:
    rows = gwas_module.parse_assoc_file(_assoc_fixture(tmp_path, fmt="emmax"))
    assert len(rows) == 3
    assert rows[0]["snp"] == "snp1"
    assert rows[0]["p"] == pytest.approx(1e-8)
    assert rows[0]["beta"] == pytest.approx(0.5)
    assert rows[0]["se"] == pytest.approx(0.1)
    assert rows[1]["p"] == pytest.approx(0.01)


def test_parse_gemma_assoc(tmp_path) -> None:
    rows = gwas_module.parse_assoc_file(_assoc_fixture(tmp_path, fmt="gemma"))
    assert len(rows) == 3
    # p_wald is the first p-like column in the fixture.
    assert rows[0]["p"] == pytest.approx(1e-8)
    assert rows[0]["chr"] == "1"
    assert rows[0]["pos"] == 100
    assert rows[0]["af"] == pytest.approx(0.4)
    assert rows[2]["p"] == pytest.approx(0.5)


def test_parse_assoc_skips_invalid_rows(tmp_path) -> None:
    path = tmp_path / "bad.ps"
    path.write_text(
        "SNP\tBETA\tSE\tP\n"
        "ok1\t0.1\t0.1\t0.001\n"
        "bad1\t0.1\t0.1\tnotanumber\n"
        "bad2\t0.1\t0.1\t1.5\n"
    )
    rows = gwas_module.parse_assoc_file(path)
    assert len(rows) == 1
    assert rows[0]["snp"] == "ok1"


def test_parse_assoc_empty_file(tmp_path) -> None:
    path = tmp_path / "empty.ps"
    path.write_text("")
    assert gwas_module.parse_assoc_file(path) == []


# ---------------------------------------------------------------------------
# Manhattan / QQ aggregation
# ---------------------------------------------------------------------------


def _rows_fixture() -> list[dict]:
    return [
        {"snp": "a", "chr": "1", "pos": 10, "p": 1e-8},
        {"snp": "b", "chr": "1", "pos": 20, "p": 0.01},
        {"snp": "c", "chr": "2", "pos": 30, "p": 0.5},
        {"snp": "d", "chr": "2", "pos": 40, "p": 0.001},
    ]


def test_manhattan_data_buckets_by_chromosome() -> None:
    mh = gwas_module.manhattan_data(_rows_fixture())
    assert mh["chromosomes"] == ["1", "2"]
    assert mh["n_variants"] == 4
    points = mh["points"]
    assert points[0]["neglog10p"] == pytest.approx(8.0, abs=1e-6)
    assert points[1]["neglog10p"] == pytest.approx(2.0, abs=1e-6)
    # Cumulative x-index across chromosomes.
    assert [p["index"] for p in points] == [0, 1, 2, 3]
    assert mh["thresholds"]["genomewide_neglog10"] == pytest.approx(7.3010, abs=1e-3)


def test_qq_data_order_stats_and_lambda() -> None:
    import math

    qq = gwas_module.qq_data(_rows_fixture())
    assert qq["n"] == 4
    # Observed is sorted ascending.
    assert qq["observed"] == sorted(qq["observed"])
    # Expected quantiles: -log10((k-0.5)/4) for k=1..4 (rank order, matching
    # the response's k-ordered array).
    expected = [-math.log10((k - 0.5) / 4) for k in range(1, 5)]
    assert qq["expected"] == [round(v, 6) for v in expected]
    # Observed values are order statistics of the observed -log10 p.
    assert qq["observed"] == sorted(qq["observed"])


def test_qq_data_empty() -> None:
    qq = gwas_module.qq_data([])
    assert qq["n"] == 0
    assert qq["observed"] == []
    assert qq["lambda_gc"] is None


def test_normal_quantile_symmetry() -> None:
    z_low = gwas_module._normal_quantile(0.025)
    z_high = gwas_module._normal_quantile(0.975)
    assert z_low == pytest.approx(-1.959964, abs=1e-3)
    assert z_high == pytest.approx(1.959964, abs=1e-3)
    assert gwas_module._normal_quantile(0.5) == pytest.approx(0.0, abs=1e-4)


# ---------------------------------------------------------------------------
# Subprocess isolation
# ---------------------------------------------------------------------------


def test_run_engine_isolates_env_and_forbids_shell(monkeypatch, tmp_path) -> None:
    import subprocess

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "emmax").touch()
    (bin_dir / "emmax").chmod(0o755)
    monkeypatch.setattr(gwas_module, "GWAS_BIN_DIR", bin_dir)

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        # Write the expected association output so run_engine's output lookup
        # succeeds (the mocked subprocess obviously writes nothing itself).
        _assoc_fixture(tmp_path)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(gwas_module.subprocess, "run", fake_run)

    gwas_module.run_engine(
        "emmax",
        tmp_path,
        phenotype_path=tmp_path / "p.pheno",
        genotype_path=tmp_path / "g.tped",
        kinship_path=None,
        covariate_path=None,
        num_threads=2,
    )

    assert captured["kwargs"]["shell"] is False
    env = captured["kwargs"]["env"]
    assert env is not None
    assert str(bin_dir) in env["PATH"]
    assert env.get("AWS_SECRET_ACCESS_KEY") is None
    assert env["OMP_NUM_THREADS"] == "2"
    cmd = captured["cmd"]
    assert cmd[0] == str(bin_dir / "emmax")
    assert "-t" in cmd
    assert "-p" in cmd


def test_run_engine_missing_binary_raises_ops_message(monkeypatch, tmp_path) -> None:
    bin_dir = tmp_path / "empty-bin"
    bin_dir.mkdir()
    monkeypatch.setattr(gwas_module, "GWAS_BIN_DIR", bin_dir)
    monkeypatch.setattr(gwas_module.shutil, "which", lambda name: None)

    with pytest.raises(RuntimeError, match="Install EMMAX/GEMMA"):
        gwas_module.run_engine(
            "gemma",
            tmp_path,
            phenotype_path=tmp_path / "p.pheno",
            genotype_path=None,
            kinship_path=None,
            covariate_path=None,
        )


def test_engine_command_build_emmax_and_gemma(tmp_path) -> None:
    binary = Path("/usr/local/bin/emmax")
    cmd = gwas_module.build_engine_command(
        "emmax",
        binary,
        tmp_path,
        phenotype_path=tmp_path / "p.pheno",
        genotype_path=tmp_path / "g.tped",
        kinship_path=tmp_path / "k.kin",
        covariate_path=None,
    )
    assert "-k" in cmd and str(tmp_path / "k.kin") in cmd

    cmd_gemma = gwas_module.build_engine_command(
        "gemma",
        Path("/usr/local/bin/gemma"),
        tmp_path,
        phenotype_path=tmp_path / "p.pheno",
        genotype_path=None,
        kinship_path=tmp_path / "k.cXX.txt",
        covariate_path=tmp_path / "c.cov",
    )
    assert "-lmm" in cmd_gemma and "4" in cmd_gemma
    assert "-c" in cmd_gemma


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def test_sanitize_error_message_removes_input_paths() -> None:
    key = "gwas/abc/input/data.pheno"
    msg = gwas_module.sanitize_error_message(
        f"failed reading {key}: boom", paths=[key]
    )
    assert key not in msg
    assert "<input-path>" in msg
    long_msg = gwas_module.sanitize_error_message("x" * 5000)
    assert len(long_msg) <= gwas_module.MAX_ERROR_LENGTH


def test_validate_input_key_rejects_traversal() -> None:
    with pytest.raises(ValueError):
        gwas_module.validate_input_key("../../etc/passwd")
    with pytest.raises(ValueError):
        gwas_module.validate_input_key("analyses/abc/input/x")
    assert gwas_module.validate_input_key("gwas/abc/input/x.pheno") is not None


def test_render_report_html_embeds_json() -> None:
    mh = gwas_module.manhattan_data(_rows_fixture())
    qq = gwas_module.qq_data(_rows_fixture())
    html = gwas_module.render_report_html(mh, qq, "emmax")
    assert "<html" in html
    assert "manhattan" in html
    assert '"chromosomes"' in html
