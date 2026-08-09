# SoyMutDB MCP Server

Model Context Protocol server for SoyMutDB (FastMCP, **Streamable HTTP**).
Serves as the machine-access layer: an LLM/agent can query genes, variants,
news and statistics, and (with a write token) submit BLAST jobs / query
analysis status.

> **Status: B1 skeleton.** All tools are registered passthrough stubs that
> call the internal REST API. Real business contracts (BLAST async
> submit+poll, job binding / IDOR protection, response shaping) land in **B4**;
> rate limiting (60 req/min per client) is enforced by the **G3** gate.

## Tools (B1)

| Tool              | Type   | Backing endpoint            | Notes |
|-------------------|--------|-----------------------------|-------|
| `gene_by_id`      | read   | `GET /api/v1/genes/{id}`    | |
| `variant_by_region` | read | `GET /api/v1/variants/region` | |
| `news_list`       | read   | `GET /api/v1/news`          | category + pagination |
| `stats_summary`   | read   | `GET /api/v1/stats/dashboard` | |
| `seqfetch`        | read   | `POST /api/v1/tools/seqfetch` | genes[] or region mode |
| `blast_submit`    | write  | `POST /api/v1/blast/jobs`   | async; poll contract in B4 |
| `analyses_query`  | write  | `GET /api/v1/analyses/{id}` | job status/result |

Full machine-readable inventory in `mcp_server/manifest.py`
(`MANIFEST["tools"]`, plus `MANIFEST["auth"]`).

## Auth

- Read tools: no auth (public API endpoints).
- Write tools: `SOYMUTDB_MCP_API_TOKEN` is forwarded to the API as
  `Authorization: Bearer`. The API itself enforces RBAC (researcher+ for
  BLAST submission).
- Transport: optional `X-MCP-Key` header is reserved for the G3 gateway.
- Rate limit: 60 req/min per client (placeholder until G3).

## Local run

```bash
pip install -e apps/mcp-server          # or: pip install fastmcp httpx uvicorn
cd apps/mcp-server
SOYMUTDB_API_BASE=http://localhost:8000 \
SOYMUTDB_MCP_API_TOKEN=... \
python -m mcp_server.server --host 0.0.0.0 --port 9000
```

Streamable HTTP endpoint: `POST /mcp/` (JSON-RPC), SSE transport available
at `/mcp/sse` (when enabled by the transport).

## Docker Compose

```bash
docker compose up -d mcp-server
```

The compose service `mcp-server` builds this directory, listens on
container port `9000` (not published to the host; only reachable via the
nginx proxy), and depends on a healthy `api` service.

## nginx reverse proxy (SSE requirements)

`infra/nginx/conf.d/default.conf` exposes the server at `/mcp/`:

```nginx
location ^~ /mcp/ {
    proxy_pass http://mcp-server:9000;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    # SSE: NEVER buffer the upstream stream
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 600s;   # keep SSE sessions alive
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
| `SOYMUTDB_API_BASE`       | `http://localhost:8000` | Internal API base URL |
| `SOYMUTDB_MCP_API_TOKEN`  | *(empty)*               | Bearer token for write tools |

## Tests

```bash
cd apps/mcp-server
PYTHONPATH=src /path/to/python -m pytest tests -q
```
