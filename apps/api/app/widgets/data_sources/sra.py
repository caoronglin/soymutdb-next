"""SRA Run widget data source.

Fetches SRA run metadata from NCBI's runinfo CSV endpoint and returns a
context dict suitable for the ``sra_run.html`` Jinja2 template.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

import httpx

from .sample_data import SRA_SRR30334525

logger = logging.getLogger(__name__)

_RUNINFO_URL = "https://trace.ncbi.nlm.nih.gov/Traces/sra-db-be/runinfo"
_TIMEOUT = 10.0


async def sra_run_context(
    params: dict[str, Any], db: Any | None = None
) -> dict[str, Any]:
    """Return template context for the SRA run detail widget.

    Params:
        run: SRA run accession (e.g. ``SRR30334525``).

    Falls back to bundled sample data on network failure.
    """
    run_acc = str(params.get("run", "SRR30334525")).strip()
    ctx: dict[str, Any] = {
        "run": dict(SRA_SRR30334525),  # copy so we don't mutate module-level
        "run_accession": run_acc,
        "fetch_error": None,
        "is_fallback": True,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(_RUNINFO_URL, params={"acc": run_acc})
            resp.raise_for_status()

        # Parse CSV response (first line is header, second is data).
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        if rows:
            ctx["run"] = dict(rows[0])
            ctx["run"]["sra_url"] = (
                f"https://trace.ncbi.nlm.nih.gov/Traces/sra?run={run_acc}"
            )
            ctx["is_fallback"] = False
        else:
            ctx["fetch_error"] = "No data returned from NCBI"
    except Exception as exc:
        logger.warning(
            "sra_run_fetch_failed", run=run_acc, error=str(exc)
        )
        ctx["fetch_error"] = f"Live fetch failed ({type(exc).__name__}); showing sample data"
        # If the requested accession is SRR30334525 we already have accurate data
        if run_acc != "SRR30334525":
            ctx["run"] = {**SRA_SRR30334525, "Run": run_acc, "sra_url": f"https://trace.ncbi.nlm.nih.gov/Traces/sra?run={run_acc}"}

    return ctx
