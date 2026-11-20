# Unified error-code contract

## Problem

Every API error returns the same `ErrorResponse` envelope with a stable
`error.code`. The published catalog (`openapi.json` → `x-error-codes`) was
built from the `SoyMutDBError` exception hierarchy only. But
`http_exception_handler` falls back to `http_error` for a generic
`HTTPException` whose status has no dedicated domain code (400, 413, 500, 503,
and any unmapped status). That code was emitted at runtime yet absent from the
catalog — a client could receive a code it could not discover from the
contract.

There was also no machine-readable binding from a stable code to the HTTP
status that emits it, and `packages/api-client/error-codes.json` (regenerated
by `generate:api-client`) was not checked by any gate.

## Single source of truth

`apps/api/app/core/exceptions.py` owns the whole contract:

| Export | Meaning |
| --- | --- |
| `error_code_catalog()` | every emitted code, including `http_error` |
| `error_status_map()` | code → status, derived from the hierarchy |
| `HTTP_STATUS_ERROR_CODES` | status → code map the generic handler consumes |
| `error_status_contract()` | combined `by_code` + `http_exception` document |

`app.main:_build_openapi_schema` publishes them as `x-error-codes` and
`x-error-status`. `http_error` maps to `null` in `by_code` because it is the
multi-status fallback, not one status. The generic handler reads the same
`HTTP_STATUS_ERROR_CODES`, so the published map and the runtime decision cannot
drift.

`packages/api-client/error-codes.json` stays a generated artifact of
`error_code_catalog()`; it is not a second source of truth.

## Guard

`scripts/check_error_code_contract.py` reads committed bytes only (snapshot,
`error-codes.json`, source). It fails when:

- `error-codes.json` disagrees with `x-error-codes`;
- the catalog omits a code that the source emits (including `http_error`);
- `x-error-status` is missing, or `by_code` keys disagree with the catalog;
- the `http_error` fallback is pinned to a single status, or the
  status→code map / fallback is altered;
- the published `by_code` / `http_exception` values disagree with what
  `error_status_map()` / `error_status_contract()` actually return from the
  exception hierarchy.

The guard runs the contract functions themselves in isolation (imports
stubbed, no API venv): a leftover `HTTP_ERROR_CODE` constant or a status
flipped in the source and snapshot together no longer passes on vocabulary
alone. It is wired into `packages/api-client/scripts/check-contract.sh`
**before** the export, so it needs neither the 3.15 venv nor a regenerated
document. This is the complement of `check-contract.sh`'s document diff:
reverting backend, snapshot and generated client together cannot co-revert a
guard that reads the source hierarchy itself.
`scripts/test_check_error_code_contract.py` pins the wiring and the exact
published code set and status binding from a second file.

`--self-test` proves fifteen negative shapes are rejected.

A coordinate change that updates the hierarchy *and* every dependent published
value would also agree with a fresh export; no byte-reading guard can detect
that. Such a semantic change needs a reviewed contract update, which is what
the hand-pinned `PUBLISHED_CODES` in the wiring test is for.

## Runtime evidence

`http_exception_handler` emits `http_error` for a generic 400
(`test_http_exception_fallback_code_is_published`), and `not_found` for 404.
`apps/api/tests/test_openapi_contract.py` asserts the published catalog equals
`error_code_catalog()` and that `x-error-status` equals `error_status_map()`.

## What this does NOT do

It does not add per-operation 400/401/403/404/413/503 response declarations.
Those codes are still undocumented at the operation level (only 422/429/500
are attached globally). That is a separate, larger contract change; this one
pins the error-code vocabulary and its status binding so later work has a
verifiable base. `check-contract.sh` remains the sole judge of export ↔
snapshot ↔ client byte equality.

## The published code → status map has its own fixed point

`check()` compares `x-error-status.by_code` with the **executed**
`error_status_map()` from `exceptions.py`. That equality is necessary but not
sufficient: it is satisfied by a coordinated co-revert that moves one
exception's `status_code` in the source **and** its published `by_code` binding
in the snapshot. The existing `status co-revert in source and snapshot`
self-test case does not close this — it flips `NotFoundError`, which also moves
`plugin_disabled`, so two codes drift and the equality check fires by accident.
A **single-code** co-revert (`AuthorizationError` 403 → 409, plus
`by_code.forbidden` 403 → 409) leaves every agreement check consistent and the
whole contracts layer `SMOKE PASS / 1102 passed` on live bytes, with the
provenance blob id honestly re-pinned.

`x-error-status.by_code` is client-visible: it tells a caller which HTTP status
a stable `error.code` arrives on. It therefore gets an independent literal,
read from nowhere:

- `_BY_CODE_DIGEST` — sha256 over the canonical sorted `(code, status)` rows,
  13 bindings including the `http_error → null` fallback. A same-count rotation
  of two statuses moves it while every count and the key set stay put.
- `_EXPECTED_BY_CODE_ROWS` (13) — exact count door.

Kept separate from `HTTP_STATUS_CODES` (the three status → code pairs for the
generic handler) and from the executed-contract equality. Folding them would
report a retyped domain status as a generic-handler mismatch and lose the
failure reason. `check_error_code_catalog.py` and
`check_api_error_code_vocabulary.py` stay unchanged: they own the code catalog
and its golden lock, not the status map.

`--self-test` grows 11 → **15 cases**. The new plants are the decisive
single-code co-revert, a one-sided published retype, a same-count rotation, and
the co-reverted extra `http_exception` row. The companion grows 13 → **25**
cases (second-file literal pin, both directions of the "equality stays true but
the digest fires" positive control, count-door load-bearing proof, source-plant
pin, and the sibling-map witnesses).

Zero wiring churn: this door lives inside an already-wired guard, so
`smoke.sh` / `PINNED_SUITES` / `REQUIRED_GUARD_CALLS` / teeth floors are
untouched. A legitimate status change must re-pin `_BY_CODE_DIGEST` in the
same commit as the source and both artifacts, with a reason.

## The generic-handler map has its own fixed point too

`x-error-status.http_exception` is the other half of the same
`error_status_contract()` return value, and it had the same hole. The
`HTTP_STATUS_CODES` literal pins the three status → code **values** and the
executed equality compares source against snapshot, but nothing pinned the
exact key set. Adding a fourth binding to the `HTTP_STATUS_ERROR_CODES` source
literal **and** to the snapshot together -- with the `snapshot_blob`
provenance id honestly re-pinned -- leaves all twelve `check_openapi_*` guards,
the three error-code guards and the whole contracts layer `SMOKE PASS` on live
`9a7c3e52`. The executed map still equals the published one, every pinned
value is intact, and the row count is free to grow.

So it gets the same treatment, in the same guard, with a separate namespace so
a failure names the right half:

- `_HTTP_EXCEPTION_DIGEST` -- sha256 over the canonical sorted
  `status|json(code)` rows, four entries including the `fallback`.
- `_EXPECTED_HTTP_EXCEPTION_ROWS` (4) -- exact count door.

This is not a second ledger over an already-pinned cell: the sibling map was
unowned. It is the same reviewed edit as the `by_code` half, applied once, so a
future reader sees one guard and two independent literals rather than two PRs
chasing the same export. A legitimate new generic-handler binding must re-pin
`_HTTP_EXCEPTION_DIGEST` in the same commit as the source and both artifacts,
with a reason.
