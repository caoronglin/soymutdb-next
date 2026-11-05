# Published schema `required` fields pin

## What is pinned

`packages/api-client/openapi.json` publishes **1076** `(schema path, required
field)` declarations across **282** component schemas (including the seven
nested `$defs` copies pydantic emits for the error envelopes).
`openapi-typescript` renders each one as a non-optional property in the
generated `components["schemas"]` interface; every other field gets a `?`.
A client compiled against the document relies on that distinction, so
requiredness is part of the public contract, not an internal detail.

`scripts/check_openapi_required_fields.py` pins the whole surface to an
independent, hand-written literal:

- `_REQUIRED_FIELD_DIGEST` — sha256 of the canonical sorted `(path, field)`
  rows, read from nowhere. Exported from the snapshot alone, so a coordinated
  regenerate of both artifacts still moves it.
- `_EXPECTED_REQUIRED_ROWS` / `_EXPECTED_SCHEMAS` — exact count doors that a
  same-count permutation cannot satisfy alone.
- the generated client's per-component optional-marker set is checked against
  the **pinned** required rows, not against the snapshot. A one-sided edit that
  makes a field optional in only one half is named by schema and field.

## Why no other fixed point sees it

| Guard | Reads | Blind to requiredness |
| --- | --- | --- |
| `check_openapi_field_constraints.py` | JSON Schema constraint keywords | `required` is not a constraint keyword |
| `check_openapi_operation_id_floor.py` / `_parameter_floor.py` / `_response_surface.py` / `_annotations.py` | per-operation facts | not component property schemas |
| `check_openapi_inline_body_integrity.py` / `test_openapi_snapshot_body_integrity.py` | which component a body names | not fields inside it |
| `check_openapi_published_enums.py` | value domains | not requiredness |
| `check_openapi_document_metadata.py` | top-level `info` / `tags` | not component schemas |
| `test_openapi_snapshot_contract.py` | per-schema **field sets** + nullable defaults | never asserts which fields are required; a co-revert keeps the equality true |
| `_PINNED_ARTIFACTS` | blob ids of the two artifacts | re-pinning both is the documented "one deliberate reviewed action" beside a regenerate |

## Decisive ablation (live bytes)

Byte-preserving removal of `key` from `AdminPluginResponse.required` in the
snapshot, the matching `key: string;` → `key?: string;` in the generated
client, and re-pinning both blob ids in
`test_openapi_snapshot_body_integrity._PINNED_ARTIFACTS`:

- all ten wired OpenAPI guards and their `--self-test` suites: `rc=0`;
- `bash scripts/smoke.sh --profile contracts`: **SMOKE PASS**.

The generated TypeScript silently changes a guaranteed field into an optional
one. With this guard wired, the same drift is caught by the digest and by the
client-optional check.

## Adding a required field

1. Make the intentional source/artifact change.
2. Recompute `_REQUIRED_FIELD_DIGEST` with the guard's own `_digest(rows(...))`
   and update `_EXPECTED_REQUIRED_ROWS` / `_EXPECTED_SCHEMAS` in the **same
   commit**.
3. Say why in the PR. Re-deriving the digest from the artifact under guard
   would make the pin self-referential.
4. `check_openapi_baseline_sync.py` is deliberately not extended: the digest
   literal here is a same-commit reviewed edit of one guard file, and the
   companion suite's `test_the_digest_is_an_independent_literal` pins that it
   is not re-derived from the snapshot.

## Wiring

- `scripts/smoke.sh` — `tests=()` row for the companion and a
  `--self-test` guard call in `smoke_contracts()`;
- `scripts/check_contracts_registry_collection.py` — `PINNED_SUITES` and
  `REQUIRED_GUARD_CALLS` floors;
- `scripts/check_contracts_self_test_teeth.py` — `_WIRED_SELF_TESTS`,
  `_SIGNATURES`, and `_EVIDENCE_PER_CASE` (the guard prints per-case
  `PASS self-test:` lines, so no drift plant is needed).

All three wiring points are read back by
`scripts/test_openapi_required_fields.py::test_the_wiring_is_pinned_in_all_three_places`.
