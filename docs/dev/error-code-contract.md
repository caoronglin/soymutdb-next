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

`--self-test` proves eleven negative shapes are rejected.

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
