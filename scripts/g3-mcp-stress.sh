#!/usr/bin/env bash
# =============================================================================
# G3 gate: MCP server stress + smoke checks (SoyMutDB monorepo)
#
# Scripted gate checks (in dependency-safe order):
#
#   1. blast_submit async quota : 11 submits for one client -> first 10 are
#      NOT rate_limited, the 11th returns {"error":"rate_limited",
#      "retry_after":N} (10/hour quota).  Runs FIRST because it only spends
#      11 slots of the shared 60/min budget.
#   2. IDOR refusal             : blast_job_status on an unknown job with a
#      random submitter_token is rejected with {"error":"forbidden"}
#      (fail-closed ownership check, no real job needed).
#   3. global 60/min window     : 120-call stats_summary spike -> the shared
#      budget (already ~12 spent above) starts returning rate_limited; we
#      assert allowed>=1 AND denied>=60 (theoretical: 48 allowed / 72 denied).
#   4. SSE long-poll smoke      : GET <MCP_URL> with the session id +
#      Accept: text/event-stream -> 200 with text/event-stream content-type;
#      the stream staying open (proxy_buffering off) is the point.
#
# Prerequisites (real run):
#   - mcp-server is running and reachable, e.g.:
#       cd apps/mcp-server && SOYMUTDB_API_BASE=http://localhost:8010 \
#         SOYMUTDB_MCP_API_TOKEN=... python -m mcp_server.server --host 0.0.0.0 --port 9000
#   - nginx /mcp/ reverse proxy is configured (or set MCP_URL straight at
#     the server): MCP_URL must be the streamable-HTTP endpoint <base>/mcp
#   - the internal REST API (apps/api) reachable from the MCP server for a
#     full end-to-end run; checks 1/2/3 still validate local rate limiting +
#     IDOR when the API is down (the 11th submit is refused before any call)
#   - python3 >= 3.9 (stdlib only: urllib / json)
#
# WARNING: check 1 really submits BLAST jobs (the first 10 calls reach the
# API when it is up).  Point MCP_TOKEN at a dev environment or accept the
# test jobs; they are quota-counted like any other submission.
#
# Configuration (env):
#   MCP_URL    streamable-HTTP endpoint, default http://localhost:9000/mcp
#   MCP_TOKEN  bearer token for the MCP endpoint (nginx X-MCP-Key / auth)
#   G3_PYTHON  python3 binary to use, default python3
#
# Usage:
#   MCP_URL=http://localhost:9000/mcp MCP_TOKEN=... scripts/g3-mcp-stress.sh
#   scripts/g3-mcp-stress.sh --dry-run     # print the steps, run nothing
#
# Exit code: 0 when every check passes, 1 otherwise.
# =============================================================================
set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown argument: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

MCP_URL="${MCP_URL:-http://localhost:9000/mcp}"
MCP_TOKEN="${MCP_TOKEN:-}"
G3_PYTHON="${G3_PYTHON:-python3}"

if ! command -v "$G3_PYTHON" >/dev/null 2>&1; then
  echo "FATAL: '$G3_PYTHON' not found (set G3_PYTHON to a python3 binary)" >&2
  exit 2
fi

export G3_DRY_RUN="$DRY_RUN"
export G3_MCP_URL="$MCP_URL"
export G3_MCP_TOKEN="$MCP_TOKEN"

"$G3_PYTHON" - <<'PY'
"""G3 gate runner: JSON-RPC over streamable HTTP (stdlib only)."""
from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

DRY = os.environ.get("G3_DRY_RUN") == "1"
BASE = os.environ.get("G3_MCP_URL", "http://localhost:9000/mcp").rstrip("/")
TOKEN = os.environ.get("G3_MCP_TOKEN", "")
CLIENT_ID = "g3-stress-client"  # fixed per-client identity -> stable limiter key

_rpc_id = [0]
_session: str | None = None
_results: list[tuple[str, str, str]] = []  # (step, status, detail)


def log(step: str, status: str, detail: str = "") -> None:
    line = f"[g3] {step} ... {status}" + (f" ({detail})" if detail else "")
    print(line)
    _results.append((step, status, detail))


# ---------------------------------------------------------------------------
# streamable-HTTP plumbing
# ---------------------------------------------------------------------------


def _headers(extra: dict | None = None) -> dict:
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    if _session:
        h["Mcp-Session-Id"] = _session
    if extra:
        h.update(extra)
    return h


def _post(payload: dict, timeout: int = 30) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(
        BASE, data=json.dumps(payload).encode(), headers=_headers(), method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()
    except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
        raise SystemExit(f"FATAL: cannot reach {BASE}: {exc}")


def _header(headers: dict, name: str) -> str:
    """Case-insensitive header lookup (urllib normalizes names)."""
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return ""


def _parse(body: bytes, content_type: str) -> dict | None:
    text = body.decode("utf-8", "replace").strip()
    if "text/event-stream" in content_type:
        data = "".join(
            ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")
        )
        return json.loads(data) if data else None
    return json.loads(text) if text else None


def _rpc(method: str, params: dict | None = None, timeout: int = 30) -> dict:
    _rpc_id[0] += 1
    payload: dict = {"jsonrpc": "2.0", "id": _rpc_id[0], "method": method}
    if params is not None:
        payload["params"] = params
    status, headers, body = _post(payload, timeout=timeout)
    if status >= 400:
        raise SystemExit(f"FATAL: HTTP {status} from {method}: {body.decode('utf-8', 'replace')[:300]}")
    parsed = _parse(body, _header(headers, "Content-Type"))
    if parsed is None:
        raise SystemExit(f"FATAL: empty response from {method}")
    if parsed.get("error"):
        raise SystemExit(f"FATAL: JSON-RPC error from {method}: {parsed['error']}")
    return parsed


def _tool_result(parsed: dict) -> dict:
    """Extract the tool's dict result (structuredContent or text JSON)."""
    result = parsed.get("result") or {}
    structured = result.get("structuredContent")
    if structured is not None:
        return structured
    for content in result.get("content") or []:
        if content.get("type") == "text":
            try:
                return json.loads(content["text"])
            except (TypeError, json.JSONDecodeError):
                return {"_text": content["text"]}
    return {}


def _call_tool(name: str, arguments: dict | None = None) -> dict:
    params: dict = {"name": name}
    if arguments:
        params["arguments"] = arguments
    params["_meta"] = {"client_id": CLIENT_ID}
    return _tool_result(_rpc("tools/call", params))


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------


def preflight() -> None:
    global _session
    if DRY:
        log("preflight", "PASS", "initialize -> session id (skipped)")
        _session = "dry-run-session"
        return
    status, headers, body = _post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "g3-mcp-stress", "version": "0.1.0"},
            },
        }
    )
    if status >= 400:
        raise SystemExit(
            f"FATAL: HTTP {status} on initialize: {body.decode('utf-8', 'replace')[:300]}"
        )
    parsed = _parse(body, _header(headers, "Content-Type"))
    if parsed is None or parsed.get("result") is None:
        raise SystemExit(f"FATAL: initialize returned no result: {parsed}")
    _session = _header(headers, "Mcp-Session-Id")
    if not _session:
        raise SystemExit("FATAL: no Mcp-Session-Id returned by initialize")
    # Mark the session initialized (async notification; body ignored).
    _post({"jsonrpc": "2.0", "method": "notifications/initialized"})
    log("preflight", "PASS", f"session {_session[:12]}...")


def check_blast_quota() -> None:
    """11 submits -> 10 allowed + 11th rate_limited (10/hr quota)."""
    if DRY:
        log("blast_submit quota (10/hr)", "PASS", "11 calls: 10 ok, 11th rate_limited (skipped)")
        return
    results = [
        _call_tool("blast_submit", {"query_sequence": "ACGT" * 6}) for _ in range(11)
    ]
    errors = [r.get("error") for r in results]
    ok10 = all(e != "rate_limited" for e in errors[:10])
    eleventh = errors[10] == "rate_limited"
    retry_after = results[10].get("retry_after", 0)
    detail = f"10 ok={ok10}, 11th rate_limited={eleventh} (retry_after={retry_after})"
    if not ok10:
        api_note = (
            " (note: earlier errors mean the API is down; local quota check "
            "still applies)" if any(e == "upstream_unavailable" for e in errors[:10]) else ""
        )
        log("blast_submit quota (10/hr)", "FAIL", detail + api_note)
        return
    if not eleventh or not isinstance(retry_after, int) or retry_after < 1:
        log("blast_submit quota (10/hr)", "FAIL", detail)
        return
    log("blast_submit quota (10/hr)", "PASS", detail)


def check_idor() -> None:
    """blast_job_status with unknown job + random token -> forbidden."""
    if DRY:
        log("IDOR refusal (job/token binding)", "PASS", "unknown job -> forbidden (skipped)")
        return
    job_id = f"g3-idor-probe-{int(time.time())}"
    result = _call_tool(
        "blast_job_status", {"job_id": job_id, "submitter_token": "f" * 32}
    )
    ok = result.get("error") == "forbidden"
    log("IDOR refusal (job/token binding)", "PASS" if ok else "FAIL",
        f"job={job_id} -> {result.get('error', 'allowed?!')}")


def check_global_spike() -> None:
    """120-call spike -> global 60/min window trips (allowed>=1, denied>=60)."""
    if DRY:
        log("global 60/min spike (120 calls)", "PASS", "expected ~48 allowed / ~72 rate_limited (skipped)")
        return
    results = [_call_tool("stats_summary", {}) for _ in range(120)]
    allowed = sum(1 for r in results if r.get("error") != "rate_limited")
    denied = sum(1 for r in results if r.get("error") == "rate_limited")
    ok = allowed >= 1 and denied >= 60
    log("global 60/min spike (120 calls)", "PASS" if ok else "FAIL",
        f"allowed={allowed}, rate_limited={denied} (window=60/min)")


def check_sse_smoke() -> None:
    """GET with session id + Accept: text/event-stream stays open."""
    if DRY:
        log("SSE long-poll smoke", "PASS", "GET /mcp -> 200 text/event-stream (skipped)")
        return
    req = urllib.request.Request(
        BASE,
        headers=_headers({"Accept": "text/event-stream", "Mcp-Session-Id": _session or ""}),
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = resp.status
            content_type = _header(dict(resp.headers), "Content-Type")
            # Read a little: a live SSE stream stays open (proxy_buffering off);
            # a timeout here still proves the connection was held, which is the
            # buffering smoke we care about.
            try:
                resp.read(2048)
            except (socket.timeout, TimeoutError):
                pass
    except urllib.error.HTTPError as exc:
        log("SSE long-poll smoke", "FAIL", f"HTTP {exc.code} (is the session valid?)")
        return
    ok = status == 200 and "text/event-stream" in content_type
    log("SSE long-poll smoke", "PASS" if ok else "FAIL",
        f"status={status}, content-type={content_type or 'none'}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"[g3] target: {BASE} client: {CLIENT_ID}"
          + (" [DRY-RUN]" if DRY else ""))
    preflight()
    # Order matters: the quota + IDOR checks spend only 12 slots of the shared
    # 60/min budget, leaving ~48 for the spike check (see header).
    check_blast_quota()
    check_idor()
    check_global_spike()
    check_sse_smoke()
    failed = [(s, d) for s, d, _ in _results if d == "FAIL"]
    if failed:
        for step, detail in failed:
            print(f"[g3] FAILED: {step} ({detail})", file=sys.stderr)
        print(f"[g3] RESULT: FAIL ({len(failed)}/{len(_results)} checks failed)")
        return 1
    print(f"[g3] RESULT: PASS ({len(_results)} checks)")
    return 0


sys.exit(main())
PY
