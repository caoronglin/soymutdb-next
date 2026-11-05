"""SoyMutDB MCP server manifest (B4): tool inventory, schemas, auth, limits.

Consumed by ``server.py`` at startup and by the tests; kept as a plain
module (no build-time codegen) so the MCP server can run without the API
package installed.

Every tool entry carries:
- ``type``: read (public data) or write (researcher-grade, bearer token)
- ``inputs``: MCP parameter name -> shape/notes
- ``outputs``: shape of the structured dict returned by the tool
- ``auth`` / ``rate_limit``: enforcement notes
"""

from __future__ import annotations

SERVER_NAME = "soymutdb"
VERSION = "0.2.0"

#: Transport-level and application-level auth notes (oracle-aligned).
AUTH: dict[str, str] = {
    "transport": (
        "Every Streamable HTTP request requires Authorization: Bearer "
        "<SOYMUTDB_MCP_API_TOKEN>; missing, incorrect, or unconfigured tokens "
        "fail closed."
    ),
    "api": (
        "SOYMUTDB_MCP_API_TOKEN is forwarded as 'Authorization: Bearer' on "
        "every internal REST call to apps/api."
    ),
    "rate_limit": (
        "Redis-backed fixed windows enforce 60 req/min across all tools and "
        "10 blast_submit calls/hour, with an in-memory fallback when Redis is "
        "unavailable. Exceeded calls return "
        "{'error': 'rate_limited', 'retry_after': N}."
    ),
    "idor": (
        "blast_submit returns a random submitter_token bound to the job id "
        "in the MCP server's process-local ownership registry; "
        "blast_job_status / analyses_query require that token and refuse "
        "cross-token reads (fail closed: unbound jobs are refused)."
    ),
}

#: Tool inventory (B4: implemented; schemas below match server.py).
TOOLS: list[dict[str, object]] = [
    {
        "name": "gene_by_id",
        "type": "read",
        "description": "Look up a soybean gene by gene id.",
        "endpoint": "GET /api/v1/genes/{gene_id}",
        "status": "implemented",
        "auth": "public (API bearer forwarded when configured)",
        "rate_limit": "global 60/min per client",
        "inputs": {
            "gene_id": "str, required — gene id, e.g. 'Glyma.01G000100'",
            "assembly_id": "int, optional — restrict to a genome assembly",
            "release_id": "int, optional — released data release to read "
            "(sent as X-SoyMutDB-Release); omitted = the API's active release",
        },
        "outputs": {
            "gene_id": "str | None",
            "assembly_id": "str | int | None",
            "chromosome": "str",
            "start": "int",
            "end": "int",
            "strand": "str",
            "name": "str | None",
            "biotype": "str",
            "description": "str | None",
            "variant_count": "int",
            "transcript_count": "int",
            "aliases": "list[str]",
        },
    },
    {
        "name": "variant_by_region",
        "type": "read",
        "description": "List variants in a genomic region.",
        "endpoint": "GET /api/v1/variants/region",
        "status": "implemented",
        "auth": "public (API bearer forwarded when configured)",
        "rate_limit": "global 60/min per client",
        "inputs": {
            "assembly": "str, required — assembly name",
            "chromosome": "str, required",
            "start": "int, required (>= 0)",
            "end": "int, required (>= 0)",
            "max_results": "int, default 1000, clamped to [1, 10000]",
            "release_id": "int, optional — released data release to read "
            "(sent as X-SoyMutDB-Release); omitted = the API's active release",
        },
        "outputs": {
            "count": "int — number of variants returned",
            "variants": "list of {variant_id, chromosome, position, "
            "ref_allele, alt_allele, variant_type, quality, "
            "filter_status, allele_frequency}",
        },
    },
    {
        "name": "news_list",
        "type": "read",
        "description": "List published news articles (category / pagination).",
        "endpoint": "GET /api/v1/news",
        "status": "implemented",
        "auth": "public (API bearer forwarded when configured)",
        "rate_limit": "global 60/min per client",
        "inputs": {
            "category": "str, optional — filter by category",
            "page": "int, default 1 (>= 1)",
            "page_size": "int, default 20, clamped to [1, 200]",
        },
        "outputs": {
            "items": "list of {id, title_en, title_zh, slug, category, "
            "cover_url, published_at}",
            "total": "int",
            "page": "int",
            "page_size": "int",
        },
    },
    {
        "name": "stats_summary",
        "type": "read",
        "description": "Homepage statistics summary.",
        "endpoint": "GET /api/v1/stats/dashboard",
        "status": "implemented",
        "auth": "public (API bearer forwarded when configured)",
        "rate_limit": "global 60/min per client",
        "inputs": {
            "release_id": "int, optional — released data release the counters "
            "are aggregated for (sent as X-SoyMutDB-Release); omitted = the "
            "API's active release",
        },
        "outputs": {
            "total_variants": "int",
            "total_genes": "int",
            "total_mutant_lines": "int",
            "total_phenotypes": "int",
            "assemblies_count": "int",
            "current_release": "str | None",
            "last_updated": "datetime (ISO string) | None",
        },
    },
    {
        "name": "seqfetch",
        "type": "read",
        "description": "Extract sequences from one explicit assembly by gene ids or chromosome interval.",
        "endpoint": "POST /api/v1/tools/seqfetch",
        "status": "implemented",
        "auth": "public (API bearer forwarded when configured); scoped by the "
        "explicit 'assembly' input, not by a release pin",
        "rate_limit": "global 60/min per client",
        "inputs": {
            "genes": "list[str], optional — batch mode (<= 200 ids; requires assembly)",
            "assembly": "str, required for either gene-list or region mode",
            "region": "str, optional — 1-based interval 'chr1:1000-2000'",
        },
        "outputs": {
            "format": "str ('fasta')",
            "assembly": "str | None — assembly used for all returned sequences",
            "sequence": "str | None — inline FASTA when under the size cap",
            "count": "int",
            "truncated": "bool",
            "missing": "list[str] — requested ids not found",
            "download_url": "str | None — pre-signed URL for large results",
            "expires_in": "int | None",
        },
    },
    {
        "name": "blast_submit",
        "type": "write",
        "description": (
            "Submit a BLAST job. Asynchronous: returns a job handle plus a "
            "submitter_token that proves ownership for later polls."
        ),
        "endpoint": "POST /api/v1/blast/jobs",
        "status": "implemented",
        "auth": "bearer (SOYMUTDB_MCP_API_TOKEN) — API requires researcher+",
        "rate_limit": "global 60/min + blast_submit quota 10/hour per client",
        "inputs": {
            "query_sequence": "str, required (>= 10 chars; FASTA header "
            "optional; amino-acid alphabet checked by the API)",
            "engine": "str, default 'ncbi_blast' — explicit engine selector; "
            "use 'diamond' only when selecting the DIAMOND backend",
            "program": "str, default 'blastp' — one of blastn, blastp, "
            "blastx, tblastn, tblastx; forwarded unchanged to the selected engine",
            "database": "str, optional — database name alias",
            "database_id": "int, optional — numeric database id",
            "params": "dict, optional — search parameters (evalue, "
            "max_target_seqs, matrix, ...) sent as 'parameters'",
        },
        "outputs": {
            "job_id": "str",
            "status": "str ('pending' | ...)",
            "engine": "str ('ncbi_blast' | 'diamond')",
            "program": "str",
            "database_id": "int",
            "submitted_at": "datetime (ISO string)",
            "submitter_token": "str — ownership proof for blast_job_status / "
            "analyses_query; keep private",
            "poll": "str ('blast_job_status')",
        },
    },
    {
        "name": "blast_job_status",
        "type": "write",
        "description": (
            "Poll the status of a BLAST job submitted via blast_submit "
            "(ownership-checked)."
        ),
        "endpoint": "GET /api/v1/blast/jobs/{job_id}",
        "status": "implemented",
        "auth": "bearer (SOYMUTDB_MCP_API_TOKEN)",
        "rate_limit": "global 60/min per client",
        "inputs": {
            "job_id": "str, required — job handle from blast_submit",
            "submitter_token": "str, required — token returned by "
            "blast_submit; cross-token reads are refused (forbidden)",
        },
        "outputs": {
            "job_id": "str",
            "status": "str ('pending' | 'running' | 'completed' | 'failed' "
            "| 'cancelled' | 'expired')",
            "program": "str",
            "submitted_at": "datetime (ISO string)",
            "started_at": "datetime (ISO string) | None",
            "completed_at": "datetime (ISO string) | None",
            "error_message": "str | None",
            "result_url": "str | None",
        },
    },
    {
        "name": "analyses_query",
        "type": "write",
        "description": (
            "Query analysis job status / results (ownership-checked)."
        ),
        "endpoint": "GET /api/v1/analyses/{job_id}",
        "status": "implemented",
        "auth": "bearer (SOYMUTDB_MCP_API_TOKEN)",
        "rate_limit": "global 60/min per client",
        "inputs": {
            "job_id": "str, required — job handle",
            "submitter_token": "str, required — token returned by "
            "blast_submit; cross-token reads are refused (forbidden)",
        },
        "outputs": {
            "job_id": "str",
            "analysis_type": "str ('fastp' | 'scanpy')",
            "status": "str ('pending' | 'queued' | 'running' | 'succeeded' "
            "| 'failed' | ...)",
            "error_message": "str | None",
            "result": "dict | None — worker-written summary when done",
            "created_at": "datetime (ISO string)",
            "updated_at": "datetime (ISO string)",
        },
    },
]

#: Canonical error shapes returned by every tool (dict payloads).
ERRORS: dict[str, str] = {
    "not_found": "API 404 — resource does not exist",
    "validation": "API 422 — invalid input; 'details' carries field errors",
    "unauthorized": "API 401 — bearer token missing/expired",
    "forbidden": "API 403, or IDOR rejection — job not owned by this "
    "submitter_token",
    "rate_limited": "local or API 429 — retry after 'retry_after' seconds",
    "upstream_error": "other non-2xx from the API (status_code in body)",
    "upstream_unavailable": "transport failure reaching the API",
}

MANIFEST: dict[str, object] = {
    "server": SERVER_NAME,
    "version": VERSION,
    "auth": AUTH,
    "tools": TOOLS,
    "errors": ERRORS,
}

__all__ = ["AUTH", "ERRORS", "MANIFEST", "SERVER_NAME", "TOOLS", "VERSION"]
