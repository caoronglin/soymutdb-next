# Published OpenAPI `x-*` extension key-set

## The surface

`packages/api-client/openapi.json` publishes 183 operation-level `x-*` rows
(`x-idempotent` × 182, `x-pagination` × 1) and two document-level extensions
(`x-error-codes`, `x-error-status`). `openapi-typescript` drops every one of
them, so the generated `openapi.d.ts` has no second half that could disagree:
a snapshot-only edit is invisible to any two-artifact comparison.

Every landed guard reads *one* extension's presence or values:

- `test_openapi_behavior_contracts.py` — `x-idempotent` flags by method,
  `x-pagination` values against `_PAGINATION_BASELINE`, 429/500 sets;
- `check_error_code_catalog.py` / `check_api_error_code_vocabulary.py` —
  `x-error-codes` contents;
- `check_error_code_contract.py` — `x-error-status` bindings.

None pins the **complete set of extension keys**. Adding a phantom key such as
`x-audit-anchor` to one operation (or at the document root) is a byte-preserving
snapshot edit; re-pinning both `_PINNED_ARTIFACTS` blob ids is the documented
"one deliberate reviewed action" beside a regenerate. On live `77ba9a6b` that
pair left all 12 `check_openapi_*` guards `rc=0` and the whole 60-suite
contracts layer `SMOKE PASS / 1102 passed + 41 subtests + 10 env-bound / 0
failed`.

## The fixed point

Inside the already-wired `scripts/test_openapi_behavior_contracts.py`, zero new
wiring and zero generated artifacts:

- `_EXTENSION_SURFACE_DIGEST` — hand-written sha256 over canonical sorted
  `(METHOD, path, key)` operation rows plus sorted `TOP|key` root rows, read
  from nowhere;
- `_EXPECTED_OPERATION_EXTENSION_ROWS` / `_EXPECTED_EXTENSION_KEYS` /
  `_EXPECTED_TOP_EXTENSION_KEYS` — exact count doors, so an added, dropped or
  relocated key is named with its own reason;
- `_extension_key_errors()` is appended to `failures()`, and a same-count
  relocation of one `x-idempotent` flag is caught only by the digest.

A legitimate new extension re-pins the literal and the count doors in the same
commit as the injection and says why. The existing positive control
`test_a_genuinely_new_pagination_contract_stays_green_with_a_repin` repins all
four literals together and stays green.

## Second door

`scripts/test_openapi_auth_surface_floor.py::ExtensionKeySetSecondDoorTests`
asserts the literal, the comparison and both count doors are still present in
the guarded source, and that a phantom extension is rejected by that module.
A single-file edit cannot delete the evidence.

## Decisive A/B (identical drifted bytes)

Byte-preserving insertion of `x-audit-anchor` into one operation, both
provenance blob ids honestly re-pinned:

| tree | verdict |
| --- | --- |
| clean live `77ba9a6b` guard on drifted bytes | `SMOKE PASS / 0 failed` |
| this guard on the same bytes | `SMOKE FAIL`, names `_EXTENSION_SURFACE_DIGEST` and both count doors |

Opinion flips on the guard alone. Restore → `SMOKE PASS`.
