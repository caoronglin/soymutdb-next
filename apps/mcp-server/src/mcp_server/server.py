"""SoyMutDB MCP server (B1 skeleton).

FastMCP instance with stub tools over **Streamable HTTP**.  Every tool is a
thin passthrough to the internal SoyMutDB REST API (apps/api) via httpx:

- base URL  : ``SOYMUTDB_API_BASE`` (default ``http://localhost:8000``)
- auth      : ``SOYMUTDB_MCP_API_TOKEN`` forwarded as ``Authorization: Bearer``
- rate limit: 60 req/min per client — placeholder; the G3 gate implements
  real enforcement (429 + async quota) on the transport/gateway layer.

Tool contracts (stubs):
- read:   gene_by_id / variant_by_region / news_list / stats_summary / seqfetch
- write:  blast_submit (async submit + poll contract lands in B4) / analyses_query

Run (local)::

    SOYMUTDB_API_BASE=http://localhost:8000 \\
    SOYMUTDB_MCP_API_TOKEN=... \\
    python -m mcp_server.server --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import argparse
import os
from typing import Any

import httpx
from fastmcp import FastMCP

from .manifest import MANIFEST

# ---------------------------------------------------------------------------
# Configuration (env-driven)
# ---------------------------------------------------------------------------

API_BASE: str = os.environ.get("SOYMUTDB_API_BASE", "http://localhost:8000").rstrip("/")
API_TOKEN: str = os.environ.get("SOYMUTDB_MCP_API_TOKEN", "")

#: Per-request HTTP timeout (seconds).  BLAST submission can take a moment;
#: long-running SSE/streaming is handled by the transport, not here.
HTTP_TIMEOUT = 30.0


def _headers() -> dict[str, str]:
    """Auth headers for internal API calls (bearer token passthrough)."""
    headers = {"Accept": "application/json"}
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
    return headers


async def _api_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET against the internal API; raises on transport/HTTP errors."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(
            f"{API_BASE}{path}", params=params, headers=_headers()
        )
        response.raise_for_status()
        return response.json()


async def _api_post(
    path: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """POST against the internal API; raises on transport/HTTP errors."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.post(
            f"{API_BASE}{path}", json=payload or {}, headers=_headers()
        )
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# MCP server + tool stubs
# ---------------------------------------------------------------------------

mcp = FastMCP(
    MANIFEST["server"],
    instructions=(
        "SoyMutDB knowledge assistant. Read tools query the public API; "
        "write tools require a configured service token. BLAST submissions "
        "are asynchronous - poll analyses_query for status (contract lands "
        "in B4)."
    ),
    version=str(MANIFEST["version"]),
)


@mcp.tool(
    name="gene_by_id",
    description="Look up a soybean gene by gene id (read-only).",
)
async def gene_by_id(gene_id: str, assembly_id: int | None = None) -> dict[str, Any]:
    """STUB: GET {API_BASE}/api/v1/genes/{gene_id}.

    TODO(B4): map API response into a compact MCP result shape; add error
    mapping for unknown genes.  Rate limit: 60/min (G3 gate).
    """
    params = {"assembly_id": assembly_id} if assembly_id is not None else None
    return await _api_get(f"/api/v1/genes/{gene_id}", params=params)


@mcp.tool(
    name="variant_by_region",
    description="List variants in a genomic region (read-only).",
)
async def variant_by_region(
    assembly: str,
    chromosome: str,
    start: int,
    end: int,
    max_results: int = 1000,
) -> dict[str, Any]:
    """STUB: GET {API_BASE}/api/v1/variants/region.

    TODO(B4): paginate / cap results; contract per manifest.
    """
    return await _api_get(
        "/api/v1/variants/region",
        params={
            "assembly": assembly,
            "chromosome": chromosome,
            "start": start,
            "end": end,
            "max_results": max_results,
        },
    )


@mcp.tool(
    name="news_list",
    description="List published news articles, optionally by category (read-only).",
)
async def news_list(
    category: str | None = None, page: int = 1, page_size: int = 20
) -> dict[str, Any]:
    """STUB: GET {API_BASE}/api/v1/news."""
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if category:
        params["category"] = category
    return await _api_get("/api/v1/news", params=params)


@mcp.tool(
    name="stats_summary",
    description="Homepage statistics summary (read-only).",
)
async def stats_summary() -> dict[str, Any]:
    """STUB: GET {API_BASE}/api/v1/stats/dashboard."""
    return await _api_get("/api/v1/stats/dashboard")


@mcp.tool(
    name="seqfetch",
    description=(
        "Extract sequences: {'genes': [...]} batch mode or "
        "{'assembly': ..., 'region': 'chr1:1000-2000'} interval mode "
        "(read-only)."
    ),
)
async def seqfetch(
    genes: list[str] | None = None,
    assembly: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    """STUB: POST {API_BASE}/api/v1/tools/seqfetch."""
    payload: dict[str, Any] = {}
    if genes:
        payload["genes"] = genes
    if assembly:
        payload["assembly"] = assembly
    if region:
        payload["region"] = region
    return await _api_post("/api/v1/tools/seqfetch", payload)


@mcp.tool(
    name="blast_submit",
    description=(
        "Submit a BLAST job (write). Asynchronous: returns a job handle; "
        "poll with analyses_query / blast job status. Requires the write "
        "bearer token."
    ),
)
async def blast_submit(
    query_sequence: str,
    program: str = "blastn",
    database: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """STUB: POST {API_BASE}/api/v1/blast/jobs.

    TODO(B4): async submit + poll contract (job handle, analyses_query),
    submitter-token job binding (IDOR protection).  Rate limit: 60/min (G3).
    """
    payload: dict[str, Any] = {
        "query_sequence": query_sequence,
        "program": program,
        "params": params or {},
    }
    if database:
        payload["database"] = database
    return await _api_post("/api/v1/blast/jobs", payload)


@mcp.tool(
    name="analyses_query",
    description="Query analysis job status / results (write-category tool).",
)
async def analyses_query(job_id: str) -> dict[str, Any]:
    """STUB: GET {API_BASE}/api/v1/analyses/{job_id}.

    TODO(B4): bind job to the submitter token (IDOR), map statuses.
    """
    return await _api_get(f"/api/v1/analyses/{job_id}")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the FastMCP server over Streamable HTTP."""
    parser = argparse.ArgumentParser(
        prog="soymutdb-mcp",
        description="SoyMutDB MCP server (Streamable HTTP).",
    )
    parser.add_argument("--host", default="0.0.0.0", help="bind address")
    parser.add_argument("--port", type=int, default=9000, help="bind port")
    args = parser.parse_args()
    mcp.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
