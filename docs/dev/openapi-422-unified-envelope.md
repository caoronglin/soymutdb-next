# 422 must advertise the envelope the runtime sends

## The defect

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

## The fix

- `main.py`: replace `setdefault("422")` with an override that always sets the
  response content schema to `ValidationErrorResponse`, while **preserving a
  route's richer 422 description** (`/api/v1/variants/export` documents the
  domain refusals that share the 422 status).
- `openapi.json`: the 235 auto 422 refs become `ValidationErrorResponse`.
- `openapi.d.ts`: regenerated with the pinned `openapi-typescript 7.13.0` /
  `typescript 5.9.3`; verified byte-identical to a fresh regeneration of the
  committed snapshot before and after the change.
- `export_contract.py::normalize()` remains a fixed point on the new snapshot,
  so a real Python 3.15 export reproduces it without drift.

## Guard

`scripts/test_openapi_422_unified_envelope.py` reads committed bytes only
(stdlib, no 3.15 venv, no PostgreSQL) and asserts:

1. every operation declares a 422 whose schema is `ValidationErrorResponse`;
2. the generated client does not type any 422 body as `HTTPValidationError`;
3. `main.py` overrides rather than `setdefault`s the 422 and still registers
   `validation_exception_handler`;
4. `ValidationErrorResponse` is actually defined in the document;
5. the guard is wired into `smoke.sh --profile contracts`.

Each branch is mutation-tested in-file; ablations on the working tree (revert
`main.py`, revert snapshot refs, revert client refs, delete the schema, drop
the smoke wiring) each turn the guard red, and restoring returns green.

`apps/api/tests/test_openapi_contract.py::test_every_422_advertises_the_unified_envelope`
pins the same invariant on the schema built from live `app.main` in the 3.15
pytest lane.

## Verification (record it, don't round it)

- `python3 scripts/test_openapi_422_unified_envelope.py` — 8 checks OK.
- Regeneration with the pinned tool produces a byte-identical `openapi.d.ts`.
- `export_contract.py::normalize()` is a fixed point on the new snapshot.
- A real `pnpm --filter @soymutdb/api-client generate:api-client` / `check:contract`
  needs Python 3.15 + the API venv + `pnpm install`; run it in CI before merge.
- Full API pytest / runtime smoke / E2E / images were not run here — do not
  sign them on the strength of this document.
