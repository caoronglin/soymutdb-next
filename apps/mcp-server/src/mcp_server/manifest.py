"""SoyMutDB MCP server manifest (B1): tool inventory, version, auth notes.

Consumed by ``server.py`` at startup and by the smoke tests; kept as a plain
module (no build-time codegen) so the MCP server can run without the API
package installed.
"""

from __future__ import annotations

SERVER_NAME = "soymutdb"
VERSION = "0.1.0"

#: Transport-level and application-level auth notes (oracle-aligned).
AUTH: dict[str, str] = {
    "transport": (
        "Optional X-MCP-Key header on the transport layer (reserved; "
        "enforcement lands with the G3 gateway gate)."
    ),
    "api": (
        "SOYMUTDB_MCP_API_TOKEN is forwarded as 'Authorization: Bearer' on "
        "every internal REST call to apps/api."
    ),
    "rate_limit": (
        "60 req/min per client - placeholder note; real enforcement is "
        "implemented by the G3 gate (429 + async quota)."
    ),
}

#: Tool inventory (B1 stubs; real implementations land in B4).
TOOLS: list[dict[str, str]] = [
    {
        "name": "gene_by_id",
        "type": "read",
        "description": "Look up a soybean gene by gene id.",
        "endpoint": "GET /api/v1/genes/{gene_id}",
        "status": "stub",
    },
    {
        "name": "variant_by_region",
        "type": "read",
        "description": "List variants in a genomic region.",
        "endpoint": "GET /api/v1/variants/region",
        "status": "stub",
    },
    {
        "name": "news_list",
        "type": "read",
        "description": "List published news articles (category / pagination).",
        "endpoint": "GET /api/v1/news",
        "status": "stub",
    },
    {
        "name": "stats_summary",
        "type": "read",
        "description": "Homepage statistics summary.",
        "endpoint": "GET /api/v1/stats/dashboard",
        "status": "stub",
    },
    {
        "name": "seqfetch",
        "type": "read",
        "description": "Extract sequences by gene ids or chromosome interval.",
        "endpoint": "POST /api/v1/tools/seqfetch",
        "status": "stub",
    },
    {
        "name": "blast_submit",
        "type": "write",
        "description": (
            "Submit a BLAST job. Async submit + poll contract is defined in "
            "B4; jobs are bound to the submitter token (IDOR protection)."
        ),
        "endpoint": "POST /api/v1/blast/jobs",
        "status": "stub",
    },
    {
        "name": "analyses_query",
        "type": "write",
        "description": "Query analysis job status / results.",
        "endpoint": "GET /api/v1/analyses/{job_id}",
        "status": "stub",
    },
]

MANIFEST: dict[str, object] = {
    "server": SERVER_NAME,
    "version": VERSION,
    "auth": AUTH,
    "tools": TOOLS,
}

__all__ = ["AUTH", "MANIFEST", "SERVER_NAME", "TOOLS", "VERSION"]
