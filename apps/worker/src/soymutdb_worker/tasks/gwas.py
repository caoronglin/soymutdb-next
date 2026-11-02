"""GWAS association tasks (EMMAX / GEMMA).

Design follows the BLAST task pattern (``tasks/blast.py``) with the same
hardening:

- ``subprocess.run`` is always called **without** ``shell=True`` and with a
  minimal environment (no ambient secrets leak into the child; only PATH /
  HOME / TMPDIR / LANG plus thread-count hints).
- The engine (``emmax`` / ``gemma``) is validated against a whitelist before
  execution; all parameters travel as validated JSON from the API whitelist.
- Resource limits: memory (``ulimit``), wall-clock timeout, output file size
  cap and input file size cap (checked before download).
- Inputs are downloaded into a per-job temporary directory from MinIO
  (``gwas/{job}/input/``); outputs land in ``gwas/{job}/output/`` with
  checksum/size metadata and are returned via pre-signed URLs.
- Association output is parsed into flat rows; Manhattan (-log10 p per SNP
  with chromosome bucketing) and QQ (observed vs expected -log10 p with
  genomic-control lambda) data are computed with numpy and stored as JSON;
  a self-contained ``Manhattan_QQ.html`` report (Plotly CDN) is rendered.
- Errors are scrubbed (input paths removed, truncated) before they are
  persisted to ``gwas_jobs.error_message``; no secrets are logged.
- Job status is tracked through the shared contract (``soymutdb_jobs``) via
  the narrow :class:`GwasJobStore` repository — the worker never imports API
  models.  Transitions are validated by the shared state machine and every
  status write is idempotent, so crash-restart re-deliveries of the same
  outbox event never double-apply.

**EMMAX / GEMMA binaries are an ops-side installation**: the worker assumes
``emmax`` / ``gemma`` are on ``PATH`` (or inside ``SOYMUTDB_GWAS_BIN_DIR``,
default ``/usr/local/bin``).  The task fails with a clear message when the
binary is missing — see ``docs/ops/multi-genome-blast.md`` (GWAS section)
for installation guidance.
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
import uuid
from contextlib import ExitStack
from pathlib import Path

from celery import Task
from dominate.tags import script as script_tag

from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.repositories import GwasJobStore
from soymutdb_worker.shared import GWAS_RUN_TASK, JobPayload
from soymutdb_worker.tasks.notifications import notify_completed, notify_failed
from soymutdb_worker.utils.db import get_db
from soymutdb_worker.utils.html_report import HTMLReport, embed_json
from soymutdb_worker.utils.s3 import (
    download_file,
    generate_presigned_url,
    get_file_size,
    upload_file,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Directory where the EMMAX / GEMMA binaries live (ops-installed).  The
#: binaries must be executable by the worker user.
GWAS_BIN_DIR = Path(get_setting("GWAS_BIN_DIR", "/usr/local/bin"))

#: Hard ceiling for a single input file (bytes).
GWAS_MAX_INPUT_SIZE = int(get_setting("GWAS_MAX_INPUT_SIZE", str(500 * 1024 * 1024)))
#: Hard ceiling for a single output file (bytes).
GWAS_MAX_OUTPUT_SIZE = int(get_setting("GWAS_MAX_OUTPUT_SIZE", str(512 * 1024 * 1024)))
#: Wall-clock timeout for the engine subprocess (seconds).
GWAS_MAX_RUNTIME_SECONDS = int(get_setting("GWAS_MAX_RUNTIME", "3600"))
#: Virtual-memory limit for the engine subprocess (MB).
GWAS_MAX_MEMORY_MB = int(get_setting("GWAS_MAX_MEMORY_MB", "8192"))
#: MinIO bucket for GWAS inputs/outputs.
GWAS_S3_BUCKET = get_setting("S3_GWAS_BUCKET", "gwas")

#: Engine whitelist (validated before any filesystem access).
ALLOWED_METHODS = frozenset({"emmax", "gemma"})

#: Minimal environment for the engine child process: only what the binaries
#: need (PATH including the ops-installed bin dir + thread-count hints).
#: Anything else from the worker's environment (tokens, keys, …) must not
#: leak into the child.
def _gwas_subprocess_env(num_threads: int = 1) -> dict[str, str]:
    path = os.environ.get("PATH", "/usr/bin:/bin")
    return {
        "PATH": f"{GWAS_BIN_DIR}:{path}",
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "LANG": "C",
        "OMP_NUM_THREADS": str(max(1, num_threads)),
        "OPENBLAS_NUM_THREADS": str(max(1, num_threads)),
    }


#: Maximum characters of error text persisted to ``gwas_jobs.error_message``.
MAX_ERROR_LENGTH = 4000


def sanitize_error_message(
    message: str,
    *,
    paths: list[str] | None = None,
    max_len: int = MAX_ERROR_LENGTH,
) -> str:
    """Scrub and truncate an error message before it is persisted/logged.

    Removes absolute input paths (they can embed the worker host layout),
    drops control characters, collapses whitespace and caps the length so
    ``gwas_jobs.error_message`` never echoes user payloads or secrets.
    """
    for path in paths or []:
        if path:
            message = message.replace(path, "<input-path>")
    message = "".join(ch for ch in message if ch.isprintable() or ch in "\n\t")
    message = " ".join(message.split())
    return message[:max_len]


def validate_method(method: str) -> str:
    """Validate that *method* is an allowed GWAS engine name."""
    if method not in ALLOWED_METHODS:
        raise ValueError(
            f"Invalid GWAS method: {method!r}. Allowed: {sorted(ALLOWED_METHODS)}"
        )
    return method


def validate_input_key(key: str, owner_id: str | uuid.UUID) -> str:
    """Validate an owner-bound GWAS input object key."""
    if not key or key.startswith("/") or not key.startswith("gwas/"):
        raise ValueError(f"Invalid GWAS input key: {key!r}")
    if "//" in key:
        raise ValueError(f"Invalid GWAS input key: {key!r}")
    segments = key.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError(f"Invalid GWAS input key: {key!r}")
    if len(segments) != 5 or segments[3] != "input":
        raise ValueError(
            "Invalid GWAS input key shape; expected "
            "gwas/{owner_id}/{session_id}/input/{filename}"
        )
    if segments[1] != str(owner_id):
        raise ValueError("GWAS input key does not belong to payload owner")
    try:
        uuid.UUID(segments[1])
        uuid.UUID(segments[2])
    except ValueError as exc:
        raise ValueError("GWAS input owner and session must be UUIDs") from exc
    return key


def resolve_binary(method: str) -> Path:
    """Locate the engine binary, with an ops-facing error when missing.

    The binaries are **not** shipped with the worker image; operators must
    install them (see module docstring).  ``GWAS_BIN_DIR`` is preferred,
    then plain ``PATH`` lookup.
    """
    validate_method(method)
    direct = GWAS_BIN_DIR / method
    if direct.is_file() and os.access(direct, os.X_OK):
        return direct
    found = shutil.which(method)
    if found:
        return Path(found)
    raise RuntimeError(
        f"GWAS engine binary {method!r} not found in {GWAS_BIN_DIR} or PATH. "
        "Install EMMAX/GEMMA on the worker host (see docs/ops "
        "multi-genome-blast.md, GWAS section) and set SOYMUTDB_GWAS_BIN_DIR "
        "if the binaries live outside /usr/local/bin."
    )


def _set_subprocess_limits() -> None:
    """Set memory and file-size limits for the child process via ``resource``."""
    mem_bytes = GWAS_MAX_MEMORY_MB * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    except (ValueError, OSError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (GWAS_MAX_OUTPUT_SIZE, GWAS_MAX_OUTPUT_SIZE))
    except (ValueError, OSError):
        pass


# ---------------------------------------------------------------------------
# Engine command construction
# ---------------------------------------------------------------------------


def build_engine_command(
    method: str,
    binary: Path,
    tmpdir: Path,
    *,
    phenotype_path: Path,
    genotype_path: Path | None,
    kinship_path: Path | None,
    covariate_path: Path | None,
    num_threads: int = 1,
) -> list[str]:
    """Build the engine command as a pure arg list (no shell interpolation).

    EMMAX: ``emmax -v -d 10 -t <tped-prefix> -p <pheno> [-k <kinship>] -o <out>``
    GEMMA: ``gemma -t <tped-prefix> -p <pheno> [-k <kinship>] [-c <cov>] -o <out>``
    (``-o`` is the *output prefix*; GEMMA writes ``output/<prefix>.assoc.txt``,
    EMMAX writes ``<prefix>.ps`` in the working directory.)
    """
    out_prefix = tmpdir / "result"
    if method == "emmax":
        if genotype_path is None:
            raise ValueError("EMMAX requires a genotype file (TPED/BED)")
        cmd = [
            str(binary),
            "-v",
            "-d", "10",
            "-t", str(genotype_path),
            "-p", str(phenotype_path),
            "-o", str(out_prefix),
        ]
        if kinship_path is not None:
            cmd += ["-k", str(kinship_path)]
        if covariate_path is not None:
            cmd += ["-c", str(covariate_path)]
        return cmd

    # GEMMA
    cmd = [str(binary), "-o", str(out_prefix)]
    if genotype_path is not None:
        cmd += ["-t", str(genotype_path)]
    cmd += ["-p", str(phenotype_path)]
    if kinship_path is not None:
        cmd += ["-k", str(kinship_path)]
    if covariate_path is not None:
        cmd += ["-c", str(covariate_path)]
    if kinship_path is not None:
        cmd += ["-lmm", "4"]
    return cmd


def run_engine(
    method: str,
    tmpdir: Path,
    *,
    phenotype_path: Path,
    genotype_path: Path | None,
    kinship_path: Path | None,
    covariate_path: Path | None,
    num_threads: int = 1,
) -> Path:
    """Run the engine subprocess (no shell) and return the assoc output path."""
    binary = resolve_binary(method)
    cmd = build_engine_command(
        method,
        binary,
        tmpdir,
        phenotype_path=phenotype_path,
        genotype_path=genotype_path,
        kinship_path=kinship_path,
        covariate_path=covariate_path,
        num_threads=num_threads,
    )

    logger.info("Running GWAS (%s): %s", method, binary.name)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=GWAS_MAX_RUNTIME_SECONDS,
        preexec_fn=_set_subprocess_limits,
        env=_gwas_subprocess_env(num_threads),
        shell=False,
        cwd=str(tmpdir),
    )

    if result.returncode != 0:
        stderr_scrubbed = sanitize_error_message(
            result.stderr or f"exit code {result.returncode}",
            paths=[str(tmpdir)],
        )
        logger.error("GWAS %s failed (rc=%d): %s", method, result.returncode, stderr_scrubbed)
        raise RuntimeError(
            f"GWAS execution failed (rc={result.returncode}): {stderr_scrubbed}"
        )

    # Locate the association output: GEMMA writes ``output/<prefix>.assoc.txt``,
    # EMMAX writes ``<prefix>.ps``.
    candidates = sorted(tmpdir.rglob("result*.assoc.txt")) + sorted(
        tmpdir.rglob("result*.ps")
    )
    if not candidates:
        raise RuntimeError(
            f"GWAS {method} produced no association output in {tmpdir}"
        )
    out = candidates[0]
    if out.stat().st_size > GWAS_MAX_OUTPUT_SIZE:
        raise RuntimeError(f"GWAS output exceeds the {GWAS_MAX_OUTPUT_SIZE}-byte limit")
    return out


# ---------------------------------------------------------------------------
# Association output parsing
# ---------------------------------------------------------------------------

#: Column aliases accepted when parsing association output, mapped to the
#: canonical row keys.
_P_COLUMNS = ("p", "p_wald", "p_lrt", "p_score")
_SNP_COLUMNS = ("snp", "rs", "snpid", "marker")
_CHR_COLUMNS = ("chr", "chrom", "chromosome")
_POS_COLUMNS = ("ps", "pos", "bp", "position")
_BETA_COLUMNS = ("beta", "b")
_SE_COLUMNS = ("se", "std_err")
_AF_COLUMNS = ("af", "maf", "allele_freq")


def parse_assoc_file(path: Path) -> list[dict]:
    """Parse an EMMAX ``.ps`` or GEMMA ``.assoc.txt`` file into flat rows.

    Header is detected from the first non-comment line; columns are matched
    case-insensitively by alias.  Rows without a parsable p-value are
    skipped.  Returns::

        [{"snp": str, "chr": str, "pos": int, "p": float, "beta": float|None,
          "se": float|None, "af": float|None}, ...]
    """
    header_idx: dict[str, int] = {}
    rows: list[dict] = []
    with open(path) as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if not header_idx:
                cols = [column.strip().lower() for column in line.split("\t")]
                header_idx = {
                    name: idx for idx, name in enumerate(cols) if name
                }
                continue
            fields = [field.strip() for field in line.split("\t")]
            if not any(fields):
                continue
            parsed = _parse_assoc_row(fields, header_idx)
            if parsed is not None:
                rows.append(parsed)
    return rows


def _parse_assoc_row(fields: list[str], header_idx: dict[str, int]) -> dict | None:
    def get(aliases: tuple[str, ...]) -> str | None:
        for alias in aliases:
            idx = header_idx.get(alias)
            if idx is not None and idx < len(fields):
                return fields[idx]
        return None

    raw_p = get(_P_COLUMNS)
    if raw_p is None:
        return None
    try:
        p = float(raw_p)
    except (TypeError, ValueError):
        return None
    if not (0.0 <= p <= 1.0):
        return None

    def _opt_float(aliases: tuple[str, ...]) -> float | None:
        raw = get(aliases)
        if raw is None or raw in {"NA", "nan", ""}:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    pos_raw = get(_POS_COLUMNS)
    pos = 0
    if pos_raw is not None and pos_raw not in {"NA", ""}:
        try:
            pos = int(float(pos_raw))
        except (TypeError, ValueError):
            pos = 0
    return {
        "snp": get(_SNP_COLUMNS) or "",
        "chr": get(_CHR_COLUMNS) or "",
        "pos": pos,
        "p": p,
        "beta": _opt_float(_BETA_COLUMNS),
        "se": _opt_float(_SE_COLUMNS),
        "af": _opt_float(_AF_COLUMNS),
    }

# ---------------------------------------------------------------------------
# Manhattan / QQ computation (numpy)
# ---------------------------------------------------------------------------

#: Genome-wide significance (-log10 of 5e-8) and suggestive (-log10 of 1e-5)
#: thresholds embedded in the manhattan JSON for plot annotations.
GWAS_SIGNIFICANCE = 5e-8
GWAS_SUGGESTIVE = 1e-5


def manhattan_data(rows: list[dict]) -> dict:
    """Compute Plotly-ready Manhattan data.

    Points are bucketed per chromosome in input order with a cumulative
    x-index; ``-log10(p)`` is capped at 320 (p clipped to 1e-320).
    """
    chromosomes: list[str] = []
    points: list[dict] = []
    x_index = 0
    for row in rows:
        p = float(row["p"])
        p_clamped = max(p, 1e-320)
        chr_name = row["chr"] or "unknown"
        if chr_name not in chromosomes:
            chromosomes.append(chr_name)
        points.append(
            {
                "chr": chr_name,
                "pos": int(row["pos"]),
                "snp": row["snp"],
                "p": p,
                "neglog10p": round(-math.log10(p_clamped), 6),
                "index": x_index,
            }
        )
        x_index += 1
    return {
        "chromosomes": chromosomes,
        "points": points,
        "n_variants": len(points),
        "thresholds": {
            "genomewide_neglog10": round(-math.log10(GWAS_SIGNIFICANCE), 4),
            "suggestive_neglog10": round(-math.log10(GWAS_SUGGESTIVE), 4),
        },
    }


def qq_data(rows: list[dict]) -> dict:
    """Compute Plotly-ready QQ data: observed vs expected -log10 p plus the
    genomic-control inflation factor lambda.

    Expected values are the order-statistic quantiles
    ``-log10((rank - 0.5) / n)``; lambda is the median chi-square statistic
    (1 df) divided by the theoretical median 0.4549.  The 1-df chi-square
    quantile is computed from the normal quantile via the Acklam inverse
    erf approximation (no scipy dependency).
    """
    n = len(rows)
    if n == 0:
        return {"observed": [], "expected": [], "n": 0, "lambda_gc": None}
    import numpy as np

    pvalues = np.asarray([max(float(r["p"] or 1.0), 1e-320) for r in rows], dtype=float)
    observed = np.sort(-np.log10(pvalues))
    ranks = np.arange(1, n + 1, dtype=float)
    expected = -np.log10((ranks - 0.5) / n)

    # lambda_gc: median(chi2_1df(1-p)) / 0.4549
    median_p = float(np.median(pvalues))
    median_chi2 = _chi2_quantile_1df(1.0 - median_p)
    lambda_gc = round(median_chi2 / 0.4549, 6) if median_chi2 > 0 else None

    return {
        "observed": [round(float(v), 6) for v in observed],
        "expected": [round(float(v), 6) for v in expected],
        "n": n,
        "lambda_gc": lambda_gc,
    }


def _chi2_quantile_1df(q: float) -> float:
    """Quantile of the chi-square distribution with 1 df at probability *q*.

    Uses x = z(q)² with z the standard-normal quantile (Acklam's inverse
    erf approximation); valid for q in (0, 1).
    """
    if q <= 0.0:
        return 0.0
    if q >= 1.0:
        return math.inf
    # Normal quantile via inverse erf (Acklam).
    z = _normal_quantile(q)
    return z * z


def _normal_quantile(p: float) -> float:
    """Standard-normal quantile via Acklam's rational approximation.

    Accurate to ~1e-9 over the full (0, 1) range; used only for the 1-df
    chi-square quantile of the GC lambda estimate (no scipy dependency).
    """
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    return _acklam_z(p)


def _acklam_z(p: float) -> float:
    """Acklam's rational approximation of the normal quantile at probability p."""
    a = (-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00)
    b = (-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00)
    p_low = 0.02425
    p_high = 1.0 - p_low
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
            ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
        )
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
    )


# ---------------------------------------------------------------------------
# HTML report rendering
# ---------------------------------------------------------------------------

#: Plotly CDN bundle used by the self-contained report.
_PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"

#: Chart script (Plotly API calls).  Expects ``MANHATTAN`` / ``QQ`` consts
#: (embedded via :func:`soymutdb_worker.utils.html_report.embed_json`).
_PLOTLY_JS = """\
const chrTicks = [];
let cum = 0;
MANHATTAN.chromosomes.forEach(chr => {
  const pts = MANHATTAN.points.filter(pt => pt.chr === chr);
  const start = pts.length ? pts[0].index : cum;
  const end = pts.length ? pts[pts.length - 1].index : cum;
  chrTicks.push({ chr, mid: (start + end) / 2, end });
  cum = end + 1;
});
const colors = ["#2f6f4f", "#9db4a0"];
const traces = MANHATTAN.chromosomes.map((chr, i) => ({
  x: MANHATTAN.points.filter(pt => pt.chr === chr).map(pt => pt.index),
  y: MANHATTAN.points.filter(pt => pt.chr === chr)
    .map(pt => pt.neglog10p),
  mode: "markers", type: "scattergl", name: chr,
  marker: { size: 4, color: colors[i % colors.length] },
  customdata: MANHATTAN.points.filter(pt => pt.chr === chr)
    .map(pt => [pt.snp, pt.pos, pt.p]),
  hovertemplate: "%{customdata[0]}<br>chr %{customdata[1]}:%{customdata[2]}"
    + "<br>-log10(p)=%{y:.3f}<extra></extra>"
}));
traces.push({
  x: [0, MANHATTAN.n_variants],
  y: [MANHATTAN.thresholds.genomewide_neglog10,
      MANHATTAN.thresholds.genomewide_neglog10],
  mode: "lines", name: "genome-wide",
  line: { dash: "dash", color: "red" }
});
Plotly.newPlot("manhattan", traces, {
  title: "Manhattan plot",
  xaxis: {
    title: "chromosome",
    tickvals: chrTicks.map(t => t.mid),
    ticktext: chrTicks.map(t => t.chr),
  },
  yaxis: { title: "-log10(p)" }, margin: { t: 60 }
});
Plotly.newPlot("qq", [{
  x: QQ.expected, y: QQ.observed, mode: "markers", type: "scatter",
  marker: { size: 4, color: "#2f6f4f" }, name: "observed"
}, {
  x: [0, Math.max(...QQ.expected, 0.001)],
  y: [0, Math.max(...QQ.expected, 0.001)],
  mode: "lines", name: "expected", line: { color: "#999" }
}], {
  title: "QQ plot (lambda_GC = " + (QQ.lambda_gc ?? "n/a") + ")",
  xaxis: { title: "expected -log10(p)" },
  yaxis: { title: "observed -log10(p)" }, margin: { t: 60 }
});
"""


def render_report_html(manhattan: dict, qq: dict, method: str) -> str:
    """Render a self-contained ``Manhattan_QQ.html`` (Plotly via CDN).

    Built with the shared dominate-based :class:`HTMLReport`; chart data is
    embedded via ``embed_json`` so variant/snp strings cannot break out of
    the ``<script>`` block.
    """
    report = HTMLReport(title=f"SoyMutDB GWAS report ({method})")
    report.head.add(script_tag(src=_PLOTLY_CDN, charset="utf-8"))
    report.add_heading(f"GWAS — {method}", level=1)
    report.add_paragraph(
        f"variants: {manhattan['n_variants']} "
        f"· lambda_GC: {qq.get('lambda_gc', 'n/a')}",
        cls="meta",
    )
    report.add_chart_div("manhattan")
    report.add_chart_div("qq")
    report.add_script(
        f"const MANHATTAN = {embed_json(manhattan)};\n"
        f"const QQ = {embed_json(qq)};\n"
        + _PLOTLY_JS
    )
    report.add_footer()
    return report.render()


def _result_file_metadata(output_path: Path) -> tuple[str, int]:
    """Return ``(sha256_hex, size_bytes)`` of a result file."""
    digest = hashlib.sha256()
    with open(output_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest(), output_path.stat().st_size


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name=GWAS_RUN_TASK,
    queue="analyses",
)
def run_gwas(
    self: Task,
    payload: dict | None = None,
    *,
    job_id: str | None = None,
    owner_id: str | None = None,
    method: str | None = None,
    object_type: str = "snp",
    phenotype_object_key: str | None = None,
    genotype_object_key: str | None = None,
    kinship_object_key: str | None = None,
    covariate_object_key: str | None = None,
    params: dict | None = None,
) -> dict:
    """Execute a GWAS association run asynchronously.

    Two call styles are accepted:

    1. **Outbox contract** (canonical): ``payload`` is a serialized
       :class:`soymutdb_jobs.schemas.JobPayload` (versioned, idempotent).
    2. **Legacy kwargs** (compat for direct dispatches): the individual
       ``job_id`` / ``method`` / ``phenotype_object_key`` / ... kwargs.

    Job status is advanced through the shared state machine and the narrow
    :class:`GwasJobStore` repository: pending -> running -> completed /
    failed.  Re-deliveries of the same event (same ``idempotency_key`` /
    ``task_id``) are detected via the job's current status and skipped.
    """
    # ── Resolve payload (outbox contract) or legacy kwargs ────────────────
    if payload is not None:
        job_payload = JobPayload.model_validate(payload)
        if job_payload.task_name != GWAS_RUN_TASK:
            raise ValueError(
                f"Payload task_name {job_payload.task_name!r} does not match "
                f"task {GWAS_RUN_TASK!r}"
            )
        job_id = str(job_payload.job_id)
        idempotency_key = job_payload.idempotency_key
        p = job_payload.payload
        owner_id = p.get("owner_id")
        if not owner_id:
            raise ValueError("GWAS payload requires owner_id")
        method = str(p["method"])
        # ``object_type`` is part of the payload contract but does not change
        # execution (format validation happens at parse time).
        phenotype_object_key = str(p["phenotype_object_key"])
        genotype_object_key = p.get("genotype_object_key")
        kinship_object_key = p.get("kinship_object_key")
        covariate_object_key = p.get("covariate_object_key")
        params = p.get("params") or {}
    else:
        if job_id is None:
            raise TypeError("run_gwas requires a JobPayload or a legacy job_id kwarg")
        if owner_id is None:
            raise TypeError("legacy dispatch requires owner_id")
        if method is None or phenotype_object_key is None:
            raise TypeError("legacy dispatch requires method and phenotype_object_key")
        idempotency_key = f"gwas:{job_id}"

    logger.info(
        "Starting GWAS job %s (idempotency_key=%s): %s phenotype=%s",
        job_id,
        idempotency_key,
        method,
        phenotype_object_key,
    )

    # Validate inputs before doing any work
    validate_method(method)
    validate_input_key(phenotype_object_key, owner_id)
    for key in (genotype_object_key, kinship_object_key, covariate_object_key):
        if key is not None:
            validate_input_key(key, owner_id)
    params = params or {}
    num_threads = int(params.get("num_threads", 1) or 1)
    if not (1 <= num_threads <= 64):
        raise ValueError("num_threads must be within 1..64")

    # ── Idempotent job claim (shared transition validation) ──────────────
    with get_db() as session:
        decision = GwasJobStore(session).begin_run(job_id)
    if decision == "skip":
        logger.info("GWAS job %s skipped (terminal/unknown status)", job_id)
        return {"job_id": job_id, "skipped": True, "idempotency_key": idempotency_key}

    self.update_state(state="STARTED", meta={"progress": 5})

    try:
        with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as downloads:
            tmpdir_path = Path(tmpdir)

            # ── Download inputs (with size caps) ─────────────────────────
            def _download(key: str) -> Path:
                size = get_file_size(f"{GWAS_S3_BUCKET}/{key}")
                if size > GWAS_MAX_INPUT_SIZE:
                    raise RuntimeError(
                        f"Input file {key!r} exceeds the {GWAS_MAX_INPUT_SIZE}-byte limit"
                    )
                local = tmpdir_path / Path(key).name
                downloaded = downloads.enter_context(
                    download_file(
                        f"{GWAS_S3_BUCKET}/{key}", local_path=str(local)
                    )
                )
                return Path(downloaded)

            phenotype_path = _download(phenotype_object_key)
            self.update_state(state="STARTED", meta={"progress": 15})
            genotype_path = (
                _download(genotype_object_key) if genotype_object_key else None
            )
            kinship_path = _download(kinship_object_key) if kinship_object_key else None
            covariate_path = (
                _download(covariate_object_key) if covariate_object_key else None
            )
            self.update_state(state="STARTED", meta={"progress": 30})

            # ── Run the engine ───────────────────────────────────────────
            assoc_path = run_engine(
                method,
                tmpdir_path,
                phenotype_path=phenotype_path,
                genotype_path=genotype_path,
                kinship_path=kinship_path,
                covariate_path=covariate_path,
                num_threads=num_threads,
            )
            self.update_state(state="STARTED", meta={"progress": 70})

            # ── Parse + compute Manhattan / QQ ───────────────────────────
            rows = parse_assoc_file(assoc_path)
            if not rows:
                raise RuntimeError(
                    f"GWAS {method} produced no usable association rows "
                    f"(expected EMMAX .ps or GEMMA .assoc.txt columns)"
                )
            manhattan = manhattan_data(rows)
            qq = qq_data(rows)
            html = render_report_html(manhattan, qq, method)
            self.update_state(state="STARTED", meta={"progress": 90})

            # ── Persist outputs to MinIO ─────────────────────────────────
            def _write_json(path: Path, obj: dict) -> None:
                path.write_text(json.dumps(obj))

            manhattan_path = tmpdir_path / "manhattan.json"
            qq_path = tmpdir_path / "qq.json"
            html_path = tmpdir_path / "Manhattan_QQ.html"
            assoc_tsv_path = tmpdir_path / f"assoc.{method}.tsv"
            _write_json(manhattan_path, manhattan)
            _write_json(qq_path, qq)
            html_path.write_text(html)
            assoc_tsv_path.write_text(_rows_to_tsv(rows))

            prefix = f"{job_id}/output"
            objects: list[tuple[Path, str]] = [
                (manhattan_path, f"{prefix}/manhattan.json"),
                (qq_path, f"{prefix}/qq.json"),
                (html_path, f"{prefix}/Manhattan_QQ.html"),
                (assoc_tsv_path, f"{prefix}/assoc.{method}.tsv"),
            ]
            for local, s3_key in objects:
                checksum, size = _result_file_metadata(local)
                upload_file(
                    str(local),
                    f"{GWAS_S3_BUCKET}/{s3_key}",
                    metadata={"checksum": checksum, "size": str(size)},
                )

            top_snps = sorted(
                rows, key=lambda r: (float(r["p"]), r["snp"])
            )[:20]

            result_summary = {
                "manhattan_object": f"{prefix}/manhattan.json",
                "qq_object": f"{prefix}/qq.json",
                "html_object": f"{prefix}/Manhattan_QQ.html",
                "assoc_object": f"{prefix}/assoc.{method}.tsv",
                "method": method,
                "n_variants": len(rows),
                "n_significant": int(
                    sum(1 for r in rows if float(r["p"]) <= GWAS_SIGNIFICANCE)
                ),
                "lambda_gc": qq.get("lambda_gc"),
                "top_snps": top_snps,
            }

            with get_db() as session:
                GwasJobStore(session).mark_succeeded(
                    job_id, result_summary=result_summary
                )

            # In-app + optional desktop notification (D2); anonymous jobs
            # (no user_id) are skipped internally.
            notify_completed(job_id, kind="gwas")

            presigned = generate_presigned_url(
                f"{GWAS_S3_BUCKET}/{prefix}/Manhattan_QQ.html", expires_in=86400
            )
            logger.info(
                "GWAS job %s completed: %d variants", job_id, len(rows)
            )
            return {
                "job_id": job_id,
                "method": method,
                "n_variants": len(rows),
                "manhattan_object": f"{prefix}/manhattan.json",
                "qq_object": f"{prefix}/qq.json",
                "html_object": f"{prefix}/Manhattan_QQ.html",
                "report_url": presigned,
                "result_summary": result_summary,
            }

    except Exception as e:
        error_text = sanitize_error_message(
            str(e), paths=[f"{GWAS_S3_BUCKET}/{phenotype_object_key}"]
        )
        logger.error("GWAS job %s failed: %s", job_id, error_text)
        try:
            with get_db() as session:
                GwasJobStore(session).mark_failed(job_id, error=error_text)
        except Exception as db_err:
            logger.error("Failed to update GWAS job status: %s", db_err)
        notify_failed(job_id, kind="gwas", error=error_text)
        raise


def _rows_to_tsv(rows: list[dict]) -> str:
    """Render parsed association rows back to a TSV document."""
    header = "snp\tchr\tpos\tp\tbeta\tse\taf"
    lines = [header]
    for r in rows:
        lines.append(
            "\t".join(
                [
                    str(r["snp"]),
                    str(r["chr"]),
                    str(r["pos"]),
                    f"{float(r['p']):.6g}",
                    "" if r["beta"] is None else f"{r['beta']:.6g}",
                    "" if r["se"] is None else f"{r['se']:.6g}",
                    "" if r["af"] is None else f"{r['af']:.6g}",
                ]
            )
        )
    return "\n".join(lines) + "\n"
