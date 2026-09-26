# SoyMutDB MCP Server

Model Context Protocol server for SoyMutDB (FastMCP, **Streamable HTTP**).
Serves as the machine-access layer: an LLM/agent can query genes, variants,
news and statistics, submit BLAST jobs, and query analysis status over an
authenticated transport.

> **Status: B4 implemented.** Eight tools proxy the internal REST API with
> response shaping, bearer-authenticated Streamable HTTP, shared rate limits,
> asynchronous BLAST polling, and submitter-token job binding. Job ownership is
> still process-local; use a shared registry before scaling MCP horizontally.

## Tools

| Tool              | Type   | Backing endpoint            | Notes |
|-------------------|--------|-----------------------------|-------|
| `gene_by_id`      | read   | `GET /api/v1/genes/{id}`    | |
| `variant_by_region` | read | `GET /api/v1/variants/region` | |
| `news_list`       | read   | `GET /api/v1/news`          | category + pagination |
| `stats_summary`   | read   | `GET /api/v1/stats/dashboard` | |
| `seqfetch`        | read   | `POST /api/v1/tools/seqfetch` | assembly-scoped genes[] or region mode |
| `blast_submit`    | write  | `POST /api/v1/blast/jobs`   | async; returns job + submitter token |
| `blast_job_status` | write | `GET /api/v1/blast/jobs/{id}` | ownership-checked polling |
| `analyses_query`  | write  | `GET /api/v1/analyses/{id}` | ownership-checked result polling |

Full machine-readable inventory in `mcp_server/manifest.py`
(`MANIFEST["tools"]`, plus `MANIFEST["auth"]`).

## Auth

- Transport: every `POST /mcp` requires
  `Authorization: Bearer <SOYMUTDB_MCP_API_TOKEN>`; an unset, missing, or
  incorrect token fails closed.
- Internal API: the configured token is forwarded on every REST call. The API
  still enforces its own public/RBAC policy; read/write labels describe tool
  semantics, not a transport-auth bypass.
- Job reads: `blast_job_status` and `analyses_query` require the random
  submitter token returned by `blast_submit`.
- Rate limit: shared Redis fixed windows enforce 60 calls/minute and 10 BLAST
  submissions/hour, with an in-memory fallback when Redis is unavailable.

## Local run

```bash
pip install -e apps/mcp-server          # or: pip install fastmcp httpx uvicorn
cd apps/mcp-server
SOYMUTDB_API_BASE=http://localhost:8010 \
SOYMUTDB_MCP_API_TOKEN=... \
python -m mcp_server.server --host 0.0.0.0 --port 9000
```

Streamable HTTP endpoint: `POST /mcp` (JSON-RPC). Streamed responses use
the same endpoint. The compatibility path `POST /mcp/` requires the same
bearer header and returns `308` to `/mcp`.

## Docker Compose

```bash
docker compose up -d mcp-server
```

The compose service `mcp-server` builds this directory, listens on
container port `9000` (not published to the host; only reachable via the
nginx proxy), and depends on a healthy `api` service.

## nginx reverse proxy (SSE requirements)

`infra/nginx/conf.d/default.conf` exposes the canonical FastMCP endpoint at
`/mcp`:

```nginx
location = /mcp/ {
    if ($http_authorization = "") { return 401; }
    return 308 /mcp;
}

location = /mcp {
    # Nginx checks presence; FastMCP validates the bearer secret.
    if ($http_authorization = "") { return 401; }
    limit_req zone=auth burst=10 nodelay;
    proxy_pass http://mcp-server:9000;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header X-Request-ID $request_id_to_forward;
    # SSE: NEVER buffer the upstream stream
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 600s;   # keep streamed sessions alive
    proxy_send_timeout 600s;
    proxy_connect_timeout 10s;
}
```

> **Why**: FastMCP's Streamable HTTP transport sends streamed responses.
> With default `proxy_buffering on`, nginx buffers the stream until the
> connection closes, truncating SSE messages — the oracle R3 requirement
> mandates `proxy_buffering off` + `proxy_read_timeout 600s` +
> `proxy_http_version 1.1`.

## Environment variables

| Variable                  | Default                 | Purpose |
|---------------------------|-------------------------|---------|
| `SOYMUTDB_API_BASE`       | `http://localhost:8010` | Internal API base URL |
| `SOYMUTDB_MCP_API_TOKEN`  | *(empty)*               | Transport and internal API bearer token |

## Tests

```bash
cd apps/mcp-server
PYTHONPATH=src /path/to/python -m pytest tests -q
```
