"""SRA Run widget data source.

Fetches SRA run metadata from NCBI's runinfo CSV endpoint and returns a
context dict suitable for the ``sra_run.html`` Jinja2 template.

No-fabrication contract
-----------------------
On a failed fetch the template receives ``run=None`` and ``fetch_error`` set, so
it can render an explicit "unavailable" state. The previous implementation kept
the bundled demo record and merely rewrote its ``Run`` field to whatever
accession was requested, so an arbitrary SRR rendered demo metadata as if it
were real. The bundled fixture is used only when
``SOYMUTDB_DEMO_FIXTURES_ENABLED=true`` and the request is for the fixture's own
accession.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

import httpx

from ...core.config import get_settings
from .sample_data import SRA_SRR30334525

logger = logging.getLogger(__name__)

_RUNINFO_URL = "https://trace.ncbi.nlm.nih.gov/Traces/sra-db-be/runinfo"
_TIMEOUT = 10.0


#: The one accession the bundled fixture actually describes.
_DEMO_ACCESSION = "SRR30334525"


async def sra_run_context(
    params: dict[str, Any], db: Any | None = None
) -> dict[str, Any]:
    """Return template context for the SRA run detail widget.

    Params:
        run: SRA run accession (e.g. ``SRR30334525``).

    On a failed live fetch ``run`` is ``None`` and ``fetch_error`` is set, so the
    template can show an explicit unavailable state instead of fixture data
    presented as the requested record.
    """
    run_acc = str(params.get("run") or _DEMO_ACCESSION).strip()
    ctx: dict[str, Any] = {
        "run": None,
        "run_accession": run_acc,
        "fetch_error": None,
        "is_fallback": False,
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
        else:
            ctx["fetch_error"] = "No data returned from NCBI"
    except Exception as exc:
        # This module uses the stdlib logger (not structlog), so keyword
        # "fields" would raise TypeError and turn a fetch failure into a 500.
        logger.warning("sra_run_fetch_failed run=%s error=%s", run_acc, exc)
        # Explicit demo mode: the fixture is only usable for its own accession.
        if get_settings().demo_fixtures_enabled and run_acc == _DEMO_ACCESSION:
            ctx["run"] = dict(SRA_SRR30334525)
            ctx["run"]["sra_url"] = (
                f"https://trace.ncbi.nlm.nih.gov/Traces/sra?run={run_acc}"
            )
            ctx["is_fallback"] = True
            ctx["fetch_error"] = (
                f"Live fetch failed ({type(exc).__name__}); showing the bundled "
                "demo fixture for this accession."
            )
        else:
            ctx["fetch_error"] = (
                f"SRA metadata for {run_acc} is temporarily unavailable "
                f"(live fetch failed: {type(exc).__name__})."
            )

    return ctx
