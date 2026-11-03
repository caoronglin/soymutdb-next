"""SoyMutDB MCP server (B4): real tool implementations.

FastMCP server over **Streamable HTTP**.  Every tool is a thin passthrough
to the internal SoyMutDB REST API (apps/api) via httpx:

- base URL  : ``SOYMUTDB_API_BASE`` (default ``http://localhost:8010``)
- auth      : ``SOYMUTDB_MCP_API_TOKEN`` forwarded as ``Authorization: Bearer``
  on every internal REST call
- rate limit: global 60 req/min per MCP client (all tools) + 10
  ``blast_submit`` calls/hr per client — enforced by ``ratelimit.py``
  (Redis fixed window shared across workers, falling back to in-memory
  when Redis is unavailable); exceeds return
  ``{"error": "rate_limited", "retry_after": N}``

Write-path IDOR protection (oracle R4): ``blast_submit`` generates a random
``submitter_token`` and binds it to the job id in an in-memory ownership
registry; ``blast_job_status`` / ``analyses_query`` require that token and
reject any caller that does not present the binding (``forbidden``).  The
registry is process-local — see README for the multi-process (Redis) note.

Error contract (all tools return plain dicts):

- API 404  -> ``{"error": "not_found", ...}``
- API 422  -> ``{"error": "validation", "details": [...]}``
- API 401/403 -> ``{"error": "unauthorized" | "forbidden", ...}``
- API 429  -> ``{"error": "rate_limited", "retry_after": N}``
- transport failure -> ``{"error": "upstream_unavailable", ...}``
- local limit exceeded -> ``{"error": "rate_limited", "retry_after": N}``

Run (local)::

    SOYMUTDB_API_BASE=http://localhost:8010 \\
    SOYMUTDB_MCP_API_TOKEN=... \\
    python -m mcp_server.server --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import uuid
from typing import Any

import httpx
from fastmcp import Context, FastMCP
from fastmcp.server.auth import AccessToken, AuthProvider

from .manifest import MANIFEST
from .ratelimit import GLOBAL_LIMITER, SUBMIT_LIMITER

# ---------------------------------------------------------------------------
# Configuration (env-driven)
# ---------------------------------------------------------------------------

API_BASE: str = os.environ.get("SOYMUTDB_API_BASE", "http://localhost:8010").rstrip("/")
API_TOKEN: str = os.environ.get("SOYMUTDB_MCP_API_TOKEN", "")

#: Per-request HTTP timeout (seconds).
HTTP_TIMEOUT = 30.0
logger = logging.getLogger("mcp.audit")

#: In-memory job ownership registry: ``job_id -> submitter_token``.
#: Populated by ``blast_submit``; consulted (and enforced) by the poll tools.
#: Process-local by design (B4); swap for Redis when scaling out (G3).
_JOB_OWNERSHIP: dict[str, str] = {}


def _authenticate_request(authorization: str | None) -> bool:
    return bool(API_TOKEN) and authorization == f"Bearer {API_TOKEN}"


class _McpTokenAuth(AuthProvider):
    async def verify_token(self, token: str) -> AccessToken | None:
        if not _authenticate_request(f"Bearer {token}"):
            return None
        return AccessToken(token=token, client_id="soymutdb", scopes=[])


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class RateLimitedError(Exception):
    """Local rate-limit rejection (global window or blast_submit quota)."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"rate limit exceeded, retry in {retry_after}s")
        self.retry_after = retry_after


class ApiError(Exception):
    """Non-2xx response from the internal API (envelope already parsed)."""

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        details: Any = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details
        self.retry_after = retry_after


class UpstreamUnavailable(Exception):
    """Transport-level failure talking to the internal API."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# Internal API plumbing
# ---------------------------------------------------------------------------


def _headers() -> dict[str, str]:
    """Auth headers for internal API calls (bearer token passthrough)."""
    headers = {"Accept": "application/json"}
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
    return headers


def _parse_api_error(status_code: int, body: Any, headers: Any) -> ApiError:
    """Map an API error body onto our canonical error codes."""
    code = "http_error"
    message = f"upstream HTTP {status_code}"
    details: Any = None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            code = err.get("code") or code
            message = err.get("message") or message
            details = err.get("details")
        if body.get("errors"):  # 422 field-level errors (sanitised by the API)
            details = body["errors"]

    retry_after: int | None = None
    try:
        raw = (headers or {}).get("Retry-After") or (headers or {}).get("retry-after")
        if raw is not None:
            retry_after = max(1, int(raw))
    except (TypeError, ValueError):
        retry_after = None

    if status_code == 404:
        return ApiError(404, "not_found", message, details)
    if status_code == 422:
        return ApiError(422, "validation", message, details)
    if status_code == 401:
        return ApiError(401, "unauthorized", message, details)
    if status_code == 403:
        return ApiError(403, "forbidden", message, details)
    if status_code == 429:
        return ApiError(429, "rate_limited", message, details, retry_after)
    return ApiError(status_code, "upstream_error", message, details)


async def _api_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    """Call the internal API and return the parsed JSON body.

    Raises :class:`ApiError` on HTTP >= 400 and :class:`UpstreamUnavailable`
    on transport failures.  Success responses are returned verbatim (the
    API has no success envelope — schemas are returned directly).
    """
    request_id = uuid.uuid4().hex
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.request(
                method,
                f"{API_BASE}{path}",
                params=params,
                json=payload,
                headers=_headers(),
            )
    except httpx.TimeoutException as exc:
        raise UpstreamUnavailable(f"upstream request timed out: {path}") from exc
    except httpx.TransportError as exc:
        raise UpstreamUnavailable(f"upstream unreachable: {exc}") from exc

    try:
        response_body = response.json()
    except ValueError:
        response_body = None
    upstream_request_id = (
        response.headers.get("X-Request-ID")
        or (response_body.get("request_id") if isinstance(response_body, dict) else None)
        or request_id
    )
    logger.info(json.dumps({
        "event": "mcp_upstream_request",
        "method": method,
        "path": path,
        "status": response.status_code,
        "request_id": upstream_request_id,
    }, sort_keys=True))
    if response.status_code >= 400:
        raise _parse_api_error(response.status_code, response_body, response.headers)
    return response_body if response_body is not None else {}


# ---------------------------------------------------------------------------
# Rate limiting + caller identity
# ---------------------------------------------------------------------------


def _caller_key(ctx: Context | None) -> str:
    """Per-client identity for rate limiting / quota accounting."""
    # FastMCP's client_id is metadata supplied by the client, not an
    # authentication fact. Until an authenticated principal is exposed by the
    # transport, fail closed to one shared anonymous budget.
    return "authenticated" if API_TOKEN else "anonymous"


def _enforce_rate_limit(ctx: Context | None, *, submit_quota: bool = False) -> None:
    """Global 60/min check (+ blast_submit 10/hr quota); raise on exceed."""
    key = _caller_key(ctx)
    allowed, retry_after = GLOBAL_LIMITER.check(key)
    if not allowed:
        raise RateLimitedError(retry_after)
    if submit_quota:
        allowed, retry_after = SUBMIT_LIMITER.check(key)
        if not allowed:
            raise RateLimitedError(retry_after)


def _rate_limit_error(
    ctx: Context | None, *, submit_quota: bool = False
) -> dict[str, Any] | None:
    """Return an error dict when rate-limited, else None (tool entry guard)."""
    try:
        _enforce_rate_limit(ctx, submit_quota=submit_quota)
    except RateLimitedError as exc:
        return _error_result(exc)
    return None


def _error_result(exc: Exception) -> dict[str, Any]:
    """Convert ApiError / UpstreamUnavailable / RateLimitedError to a dict."""
    if isinstance(exc, RateLimitedError):
        return {"error": "rate_limited", "retry_after": exc.retry_after}
    if isinstance(exc, ApiError):
        result: dict[str, Any] = {"error": exc.error_code, "message": exc.message}
        if exc.details is not None:
            result["details"] = exc.details
        if exc.retry_after is not None:
            result["retry_after"] = exc.retry_after
        return result
    if isinstance(exc, UpstreamUnavailable):
        return {"error": "upstream_unavailable", "message": exc.message}
    return {"error": "upstream_error", "message": str(exc)}


async def _safe_call(awaitable: Any) -> Any:
    """Await an API call, converting known failures into error dicts."""
    try:
        return await awaitable
    except (RateLimitedError, ApiError, UpstreamUnavailable) as exc:
        return _error_result(exc)


def _is_error(data: Any) -> bool:
    return isinstance(data, dict) and "error" in data


# ---------------------------------------------------------------------------
# IDOR protection (oracle R4): submitter-token job binding
# ---------------------------------------------------------------------------


def _bind_job(job_id: str, submitter_token: str) -> None:
    _JOB_OWNERSHIP[job_id] = submitter_token


def _check_ownership(job_id: str, submitter_token: str) -> dict[str, Any] | None:
    """Return an error dict when the caller is not the job owner, else None.

    Fails closed: jobs with no binding (never submitted through this MCP
    server, or the registry was reset) are refused.
    """
    bound = _JOB_OWNERSHIP.get(job_id)
    if bound is None:
        return {
            "error": "forbidden",
            "message": "job is not bound to this MCP server (no submitter token)",
        }
    if bound != submitter_token:
        return {
            "error": "forbidden",
            "message": "job does not belong to this submitter token",
        }
    return None


# ---------------------------------------------------------------------------
# MCP server + tools
# ---------------------------------------------------------------------------

mcp = FastMCP(
    MANIFEST["server"],
    instructions=(
        "SoyMutDB knowledge assistant. Read tools query the public API; "
        "write tools require the configured service token. BLAST "
        "submissions are asynchronous: blast_submit returns a "
        "submitter_token, and blast_job_status / analyses_query poll the "
        "job (the token is the ownership proof - keep it private)."
    ),
    version=str(MANIFEST["version"]),
    auth=_McpTokenAuth(),
)


@mcp.tool(
    name="gene_by_id",
    description="Look up a soybean gene by gene id (read-only).",
)
async def gene_by_id(
    gene_id: str, assembly_id: int | None = None, ctx: Context | None = None
) -> dict[str, Any]:
    """GET {API_BASE}/api/v1/genes/{gene_id} → compact gene record."""
    rate_err = _rate_limit_error(ctx)
    if rate_err is not None:
        return rate_err
    params = {"assembly_id": assembly_id} if assembly_id is not None else None
    data = await _safe_call(
        _api_request("GET", f"/api/v1/genes/{gene_id}", params=params)
    )
    if _is_error(data):
        return data
    return {
        "gene_id": data.get("gene_id") or data.get("id"),
        "assembly_id": data.get("assembly_id"),
        "chromosome": data.get("chromosome"),
        "start": data.get("start"),
        "end": data.get("end"),
        "strand": data.get("strand"),
        "name": data.get("name"),
        "biotype": data.get("biotype"),
        "description": data.get("description"),
        "variant_count": data.get("variant_count"),
        "transcript_count": len(data.get("transcripts") or []),
        "aliases": data.get("aliases") or [],
    }


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
    ctx: Context | None = None,
) -> dict[str, Any]:
    """GET {API_BASE}/api/v1/variants/region → {count, variants}."""
    rate_err = _rate_limit_error(ctx)
    if rate_err is not None:
        return rate_err
    # The API caps max_results at 10_000; clamp here so callers never 422.
    max_results = max(1, min(int(max_results), 10_000))
    data = await _safe_call(
        _api_request(
            "GET",
            "/api/v1/variants/region",
            params={
                "assembly": assembly,
                "chromosome": chromosome,
                "start": start,
                "end": end,
                "max_results": max_results,
            },
        )
    )
    if _is_error(data):
        return data
    variants = [
        {
            "variant_id": v.get("variant_id") or v.get("id"),
            "chromosome": v.get("chromosome"),
            "position": v.get("position"),
            "ref_allele": v.get("ref_allele"),
            "alt_allele": v.get("alt_allele"),
            "variant_type": v.get("variant_type"),
            "quality": v.get("quality"),
            "filter_status": v.get("filter_status"),
            "allele_frequency": v.get("allele_frequency"),
        }
        for v in data
        if isinstance(v, dict)
    ]
    return {"count": len(variants), "variants": variants}


@mcp.tool(
    name="news_list",
    description="List published news articles, optionally by category (read-only).",
)
async def news_list(
    category: str | None = None,
    page: int = 1,
    page_size: int = 20,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """GET {API_BASE}/api/v1/news → paginated list."""
    rate_err = _rate_limit_error(ctx)
    if rate_err is not None:
        return rate_err
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 200))
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if category:
        params["category"] = category
    data = await _safe_call(_api_request("GET", "/api/v1/news", params=params))
    if _is_error(data):
        return data
    items = [
        {
            "id": a.get("id"),
            "title_en": a.get("title_en"),
            "title_zh": a.get("title_zh"),
            "slug": a.get("slug"),
            "category": a.get("category"),
            "cover_url": a.get("cover_url"),
            "published_at": a.get("published_at"),
        }
        for a in data.get("items") or []
        if isinstance(a, dict)
    ]
    return {
        "items": items,
        "total": data.get("total", len(items)),
        "page": data.get("page", page),
        "page_size": data.get("page_size", page_size),
    }


@mcp.tool(
    name="stats_summary",
    description="Homepage statistics summary (read-only).",
)
async def stats_summary(ctx: Context | None = None) -> dict[str, Any]:
    """GET {API_BASE}/api/v1/stats/dashboard → dashboard counters."""
    rate_err = _rate_limit_error(ctx)
    if rate_err is not None:
        return rate_err
    data = await _safe_call(_api_request("GET", "/api/v1/stats/dashboard"))
    if _is_error(data):
        return data
    return {
        "total_variants": data.get("total_variants"),
        "total_genes": data.get("total_genes"),
        "total_mutant_lines": data.get("total_mutant_lines"),
        "total_phenotypes": data.get("total_phenotypes"),
        "assemblies_count": data.get("assemblies_count"),
        "current_release": data.get("current_release"),
        "last_updated": data.get("last_updated"),
    }


@mcp.tool(
    name="seqfetch",
    description=(
        "Extract sequences from an explicit assembly: "
        "{'assembly': ..., 'genes': [...]} batch mode or "
        "{'assembly': ..., 'region': 'chr1:1000-2000'} interval mode "
        "(read-only)."
    ),
)
async def seqfetch(
    genes: list[str] | None = None,
    assembly: str | None = None,
    region: str | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """POST {API_BASE}/api/v1/tools/seqfetch → FASTA / download URL."""
    rate_err = _rate_limit_error(ctx)
    if rate_err is not None:
        return rate_err
    payload: dict[str, Any] = {}
    if assembly:
        payload["assembly"] = assembly
    if genes:
        payload["genes"] = genes[:200]
    if region:
        payload["region"] = region
    data = await _safe_call(_api_request("POST", "/api/v1/tools/seqfetch", payload=payload))
    if _is_error(data):
        return data
    return {
        "format": data.get("format"),
        "assembly": assembly,
        "sequence": data.get("sequence"),
        "count": data.get("count", 0),
        "truncated": data.get("truncated", False),
        "missing": data.get("missing") or [],
        "download_url": data.get("download_url"),
        "expires_in": data.get("expires_in"),
    }


@mcp.tool(
    name="blast_submit",
    description=(
        "Submit a BLAST job (write). NCBI BLAST+ is the default engine; "
        "pass engine='diamond' explicitly for DIAMOND. Asynchronous: returns a job handle "
        "plus a submitter_token that proves ownership for later polls "
        "(blast_job_status / analyses_query). Requires the write bearer "
        "token; quota 10 submissions/hour/client."
    ),
)
async def blast_submit(
    query_sequence: str,
    program: str = "blastp",
    engine: str = "ncbi_blast",
    database: str | None = None,
    database_id: int | None = None,
    params: dict[str, Any] | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """POST {API_BASE}/api/v1/blast/jobs → {job_id, status, submitter_token}."""
    rate_err = _rate_limit_error(ctx, submit_quota=True)
    if rate_err is not None:
        return rate_err
    payload: dict[str, Any] = {
        "engine": engine,
        "program": program,
        "query_sequence": query_sequence,
    }
    if database:
        payload["database"] = database
    if database_id is not None:
        payload["database_id"] = database_id
    if params:
        payload["parameters"] = params
    data = await _safe_call(
        _api_request("POST", "/api/v1/blast/jobs", payload=payload)
    )
    if _is_error(data):
        return data

    job_id = data.get("job_id")
    submitter_token = uuid.uuid4().hex
    if job_id:
        _bind_job(str(job_id), submitter_token)
    return {
        "job_id": job_id,
        "status": data.get("status"),
        "engine": data.get("engine", engine),
        "program": data.get("program"),
        "database_id": data.get("database_id"),
        "submitted_at": data.get("submitted_at"),
        "submitter_token": submitter_token,
        "poll": "blast_job_status",
    }


@mcp.tool(
    name="blast_job_status",
    description=(
        "Poll the status of a BLAST job previously submitted via "
        "blast_submit (write-category). Pass the submitter_token returned "
        "by blast_submit; jobs cannot be read across submitter tokens "
        "(IDOR protection)."
    ),
)
async def blast_job_status(
    job_id: str, submitter_token: str, ctx: Context | None = None
) -> dict[str, Any]:
    """GET {API_BASE}/api/v1/blast/jobs/{job_id} (ownership-checked)."""
    rate_err = _rate_limit_error(ctx)
    if rate_err is not None:
        return rate_err
    denied = _check_ownership(job_id, submitter_token)
    if denied is not None:
        return denied
    data = await _safe_call(
        _api_request("GET", f"/api/v1/blast/jobs/{job_id}")
    )
    if _is_error(data):
        return data
    return {
        "job_id": data.get("job_id"),
        "status": data.get("status"),
        "program": data.get("program"),
        "submitted_at": data.get("submitted_at"),
        "started_at": data.get("started_at"),
        "completed_at": data.get("completed_at"),
        "error_message": data.get("error_message"),
        "result_url": data.get("result_url"),
    }


@mcp.tool(
    name="analyses_query",
    description=(
        "Query analysis job status / results (write-category). Pass the "
        "submitter_token returned by blast_submit; jobs cannot be read "
        "across submitter tokens (IDOR protection)."
    ),
)
async def analyses_query(
    job_id: str, submitter_token: str, ctx: Context | None = None
) -> dict[str, Any]:
    """GET {API_BASE}/api/v1/analyses/{job_id} (ownership-checked)."""
    rate_err = _rate_limit_error(ctx)
    if rate_err is not None:
        return rate_err
    denied = _check_ownership(job_id, submitter_token)
    if denied is not None:
        return denied
    data = await _safe_call(
        _api_request("GET", f"/api/v1/analyses/{job_id}")
    )
    if _is_error(data):
        return data
    return {
        "job_id": data.get("job_id"),
        "analysis_type": data.get("analysis_type"),
        "status": data.get("status"),
        "error_message": data.get("error_message"),
        "result": data.get("result"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
    }


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
