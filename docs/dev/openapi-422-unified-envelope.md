# Error responses must advertise the envelope the runtime sends

## The first defect (PR #154)

`apps/api/app/main.py` registers `validation_exception_handler` for every
`RequestValidationError`. That handler **always** returns the unified error
envelope (`ValidationErrorResponse`): `error` / `request_id` / `status_code`
plus a sanitised, field-level `errors` array. FastAPI's default 422 shape
(`HTTPValidationError`, a flat `detail` list) is never emitted.

`_build_openapi_schema` documented that envelope with
`responses.setdefault("422", ...)`. `get_openapi` populates the auto 422
first, so `setdefault` was a no-op on 235 of 266 operations. Both committed
artifacts — `packages/api-client/openapi.json` and the generated
`src/generated/openapi.d.ts` — typed 422 as `HTTPValidationError` for those
operations. A consumer writing error handling against the generated client
wrote a branch for a shape that never arrives and no branch for `errors`.

The two artifacts agreed with each other byte-for-byte. A diff gate cannot see
this class of defect: equality of two generated products is not evidence that
the source declares the truth. This is the same genus as PR #103 (an
undeclared 404 typed as unreachable), one status over.

Fix: `main.py` overrides (not `setdefault`s) the 422, preserving a route's
richer 422 description; both artifacts were regenerated with the pinned tool.

## The second defect: a guard that only banned one name

The guard added with that fix checked the generated client for the literal
`HTTPValidationError` body spelling. Three regressions stayed green against
it — each reproduced on the live tree before this change:

| Regression | Old guard | Reason |
| --- | --- | --- |
| Retype one 422 body in `openapi.d.ts` as `ErrorResponse` | GREEN | Wrong shape, but not the one banned name |
| Delete one operation's `500` response from the snapshot | GREEN | Guard never looked at 500 in the JSON half |
| Retype one `500` response as `HTTPValidationError` | GREEN | Guard only scanned 422 refs |

In all three, `openapi.json` and `openapi.d.ts` still agreed with each other,
so `check-contract.sh`'s byte diff could not see it either. A guard that
looks for one bad spelling is not a guard against a wrong shape.

## The contract

`apps.api.app.main` registers four handlers. Every one emits `ErrorResponse`
except the 422 handler, which emits `ValidationErrorResponse`:

| Handler | Status | Body |
| --- | --- | --- |
| `soy_mut_db_exception_handler` | domain status | `ErrorResponse` |
| `http_exception_handler` | HTTP status | `ErrorResponse` |
| `validation_exception_handler` | 422 | `ValidationErrorResponse` |
| `unhandled_exception_handler` | 500 | `ErrorResponse` |

Therefore every operation must declare a `422` (`ValidationErrorResponse`) and
a `500` (`ErrorResponse`), and every other declared 4xx/5xx response (today
409 and 429) must use `ErrorResponse`. No operation may declare a 4xx/5xx body
the runtime does not send.

## Guards

`scripts/test_openapi_422_unified_envelope.py` reads committed bytes only
(stdlib, no 3.15 venv, no PostgreSQL) and asserts:

1. every operation declares a 422 and a 500, each with the exact runtime schema;
2. every other declared 4xx/5xx response uses `ErrorResponse`;
3. the generated client contains **exactly as many** `ErrorResponse` and
   `ValidationErrorResponse` response bodies as the snapshot declares — so a
   dropped, retyped or *one-sidedly* added body changes a count instead of
   hiding behind a banned-name check;
4. the declared error-response distribution (`422`/`500` on every operation,
   plus `409` x3 and `429` x1) is pinned to an exact baseline. The equality
   check is self-referential: `expected` is recomputed from the supplied JSON,
   so a snapshot and client edited **together** still agree. A coordinated
   drop OR add (e.g. inventing a `418` on both halves) is caught only by this
   independent fixed point, the same idiom as `_SNAPSHOT_FLOOR`;
5. `main.py` overrides rather than `setdefault`s the 422, still registers all
   four handlers, and both declared schemas are defined in the document;
6. the guard is wired into `smoke.sh --profile contracts`.

It keeps its original file name (and therefore its existing wiring), so this
change adds no entry to the shared `tests[]` array that dozens of in-flight PRs
are editing. 16 in-file mutation cases cover every branch, including the three
regressions above and the coordinated add/drop blind spot.

The adjacent `scripts/test_openapi_snapshot_contract.py` had no `__main__`
block: a direct run printed nothing and exited 0, which reads as a pass to
anything that only checks the exit code. This PR gives it a standalone runner
and a self-test that pins the runner. Keeping that check inside the snapshot
guard itself (not in the envelope guard) avoids making the 6 in-flight owners
of this file turn red on a file they do not own.

The baseline pins the **declared error surface**, not the endpoint count: a
legitimate new endpoint adds its own 422/500, so `_ERROR_RESPONSE_BASELINE`
must be updated in that same commit with a reason. An exact pin in both
directions is deliberate — an error status the runtime never sends is as wrong
as a dropped one.

`apps/api/tests/test_error_envelope_openapi_floor.py` pins the same contract on
the schema built from the live `app.main:app` in the 3.15 pytest lane, with a
floor on the number of non-422/500 error responses so the assertion cannot
pass vacuously. The offline guard covers the committed artifacts; this one
covers the builder that produces them.

## Verification (record it, don't round it)

- `python3 scripts/test_openapi_422_unified_envelope.py` — 16 checks OK.
- `python3 scripts/test_openapi_snapshot_contract.py` — 19 checks OK, with a
  real `__main__` runner; removing it reproduces the old silent rc=0.
- On the unmodified live tree, the three regressions above are GREEN against
  the old guard and RED against the new one. A coordinated add of a `418` to
  **both** artifacts — GREEN against the unpatched count guard — is RED now.
- Checked against **73** open PR heads: 7 carry the guard (this PR + 6 valid
  owners #160/#162/#164/#165/#166/#167), all GREEN; the other 66 forked before
  #154 and never owned the file (their `deleted file` diff is stale, not a
  conflict). `merge-tree --write-tree` over the full 73-head matrix: 0 new
  conflicts, 0 resolved.
- `apps/api/tests/test_error_envelope_openapi_floor.py` needs the Python 3.15
  API venv; it was **not** executed in the CPython 3.11 sandbox and is not
  counted in any local pass number. A real
  `pnpm --filter @soymutdb/api-client generate:api-client` / `check:contract`,
  full API pytest, runtime smoke, E2E and images were not run here — CI is the
  authority, do not sign them on the strength of this document.
