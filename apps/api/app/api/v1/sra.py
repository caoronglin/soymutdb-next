"""SRA Run Browser endpoints — JSON metadata for NCBI SRA accessions.

Endpoints:
    GET /sra/run/{accession} — return JSON metadata for a single SRA run,
        fetched live from NCBI's runinfo CSV endpoint with a 1-hour Redis cache.

The live fetch uses httpx.AsyncClient with a 10-second timeout.  Results are
cached in Redis keyed by accession so repeated loads are instant and we avoid
hammering NCBI.  On cache miss + network failure we fall back to bundled
sample data for the demo accession SRR30334525.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from ...core.database import get_redis
from ...widgets.data_sources.sample_data import SRA_SRR30334525, SOYBEAN_SRA_SAMPLES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sra", tags=["sra"])

_RUNINFO_URL = "https://trace.ncbi.nlm.nih.gov/Traces/sra-db-be/runinfo"
_TIMEOUT = 10.0
_CACHE_TTL_SECONDS = 3600  # 1 hour
_CACHE_PREFIX = "sra:run:"


def _cache_key(accession: str) -> str:
    return f"{_CACHE_PREFIX}{accession.upper()}"


def _parse_runinfo_csv(text: str) -> dict[str, str] | None:
    """Parse the NCBI runinfo CSV response and return the first data row."""
    try:
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            return None
        return dict(rows[0])
    except Exception:
        return None


def _enrich_run(run: dict[str, str], accession: str) -> dict[str, str]:
    """Add derived convenience fields to a raw runinfo row."""
    enriched = dict(run)
    enriched["sra_url"] = f"https://trace.ncbi.nlm.nih.gov/Traces/sra?run={accession}"
    # Short date (YYYY-MM-DD)
    release = enriched.get("ReleaseDate", "")
    if release and len(release) >= 10:
        enriched["release_date_short"] = release[:10]
    else:
        enriched["release_date_short"] = release
    return enriched


async def _fetch_run_from_ncbi(accession: str) -> dict[str, Any] | None:
    """Fetch run metadata from NCBI; return None on any failure."""
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, follow_redirects=True
        ) as client:
            resp = await client.get(_RUNINFO_URL, params={"acc": accession})
            resp.raise_for_status()
        row = _parse_runinfo_csv(resp.text)
        if row is None:
            return None
        return _enrich_run(row, accession)
    except Exception as exc:
        logger.warning("sra_fetch_failed", accession=accession, error=str(exc))
        return None


@router.get("/run/{accession}", summary="Get SRA run metadata (JSON)")
async def get_sra_run(accession: str) -> dict[str, Any]:
    """Return JSON metadata for an SRA run accession (SRR/DRR/ERR).

    Results are cached in Redis for 1 hour.  On network failure a sensible
    fallback object is returned so the UI can still render.
    """
    accession = accession.strip().upper()
    if not accession or len(accession) < 6:
        raise HTTPException(status_code=400, detail="Invalid SRA accession")

    redis = get_redis()

    # 1. Try Redis cache
    try:
        cached = await redis.get(_cache_key(accession))
        if cached:
            try:
                return json.loads(cached)
            except (json.JSONDecodeError, TypeError):
                pass  # corrupt cache entry — fall through
    except Exception:
        logger.debug("sra_redis_unavailable", accession=accession)

    # 2. Fetch live from NCBI
    live = await _fetch_run_from_ncbi(accession)
    if live is not None:
        payload: dict[str, Any] = {
            "run": live,
            "accession": accession,
            "source": "ncbi",
            "cached": False,
        }
        try:
            await redis.setex(
                _cache_key(accession),
                _CACHE_TTL_SECONDS,
                json.dumps(payload),
            )
        except Exception:
            pass
        return payload

    # 3. Fallback — bundled sample data
    if accession == "SRR30334525":
        fallback = _enrich_run(dict(SRA_SRR30334525), accession)
        return {
            "run": fallback,
            "accession": accession,
            "source": "fallback",
            "cached": False,
            "error": "Live NCBI fetch failed; showing bundled sample data",
        }

    # 4. Unknown accession + network failure — return a minimal stub
    stub = {
        "Run": accession,
        "sra_url": f"https://trace.ncbi.nlm.nih.gov/Traces/sra?run={accession}",
        "ScientificName": "unknown",
        "LibraryStrategy": "unknown",
        "Platform": "unknown",
        "release_date_short": "",
    }
    return {
        "run": stub,
        "accession": accession,
        "source": "stub",
        "cached": False,
        "error": "Unable to fetch metadata from NCBI and accession is not in local cache",
    }


@router.get("/samples", summary="List curated SRA samples (default species: soybean)")
async def list_soybean_samples() -> dict[str, Any]:
    """Return a small curated list of SRA runs for the current default species
    (soybean, Glycine max) for demo / quick-load purposes.  This is static data
    bundled with the backend."""
    enriched = []
    for s in SOYBEAN_SRA_SAMPLES:
        r = dict(s)
        acc = r.get("Run", "")
        r.setdefault("sra_url", f"https://trace.ncbi.nlm.nih.gov/Traces/sra?run={acc}")
        release = r.get("ReleaseDate", "")
        r["release_date_short"] = release[:10] if len(release) >= 10 else release
        enriched.append(r)
    # Include the demo Zea mays run too so users can see it
    demo = _enrich_run(dict(SRA_SRR30334525), "SRR30334525")
    return {
        "samples": enriched,
        "demo": demo,
        "total": len(enriched) + 1,
    }
