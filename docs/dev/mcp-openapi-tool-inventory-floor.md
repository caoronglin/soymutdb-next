# MCP tool inventory: a reviewed lower bound

`scripts/test_mcp_openapi_parity.py` reconciles three declarations of the MCP
REST surface — `apps/mcp-server/src/mcp_server/manifest.py` (`TOOLS`),
`server.py` (`@mcp.tool` + `_api_request`), and the published
`packages/api-client/openapi.json`. It pins, per tool, that the endpoint
resolves to a published operation, that the server calls the same method/path,
that `type` agrees with the operation's `security`, and that the two tool sets
agree.

## The hole

All four checks derive their expectation from the three declarations they
compare. Agreement is the property, and a coordinated edit moves all three
together. On live `main` (measured at `7468858a`), injecting each of these
shapes into the three declarations returned **zero** failures:

| Coordinated shape | Unmodified guard |
| --- | --- |
| Delete `news_list` from manifest + server + snapshot (and remove the path from `openapi.json`) | `[]` — green |
| Rename `news_list`'s endpoint across all three | `[]` — green |
| Flip `news_list` from `read` to `write`, and add `HTTPBearer` to the operation | `[]` — green |

Only emptying the **entire** manifest was caught (`manifest.py declares no MCP
tools`). Losing one published tool — or silently moving it to another REST
operation, or changing its audience — was invisible. This is the same genus as
the #154 / #190 / #199 / #203 series: `check-contract.sh` proves
*export == snapshot*, which is self-consistency, not truth. A fact pinned only
against bytes derived from the same export can be co-reverted.

## The fix

`PINNED_MCP_TOOLS` is a hand-written, reviewed literal in the guard —
`name -> (endpoint, type)` for the eight published tools. It is read from no
other file, so no coordinated edit of the three declarations can move it.
`check()` compares it as a **lower bound** in three directions:

- a pinned name that no longer appears in the manifest (`missing`);
- a pinned tool whose `endpoint` changed (`moved`);
- a pinned tool whose `type` changed (`audience changed`).

Extras are deliberately allowed: a genuinely new, consistent tool still passes
with no edit to this literal (the guard's documented "no allowlist for new
tools" property, kept as a positive control). A deliberate retirement or rename
is an explicit, reviewable edit to `PINNED_MCP_TOOLS` in the same commit as the
three declarations — not a silent consequence of running the export.

## Verification (CPython 3.11.2, committed bytes only)

| Check | Result |
| --- | --- |
| `python3 scripts/test_mcp_openapi_parity.py` | OK (8 tools, 268 operations) |
| `... --self-test` | 15 cases, 0 failures (11 old + 4 new) |
| `pytest scripts/test_mcp_openapi_parity.py -q` | 15 passed |
| one-tool co-revert, unmodified guard / this guard | `0` errors (green) / `1` named failure (red) |
| endpoint rename / audience flip | both red on this guard |
| `smoke.sh --profile contracts` | SMOKE PASS (see the PR for the exact count) |

The guard already runs as a `tests=()` row in `smoke.sh`; no shared-file edit
was needed, so this phase has zero file overlap with the in-flight PRs.

Not run here (prerequisite missing, never counted as a pass): a real
`generate:api-client` re-export (3.15 toolchain), the full API/worker pytest,
turbo, Playwright E2E, OCI. CI `verify` terminal state is the authority; the
root-group CPU core-hours `Prepare` pre-freeze is a quota gate, not a test
result, and `pending`/`error` is not signed as green.
