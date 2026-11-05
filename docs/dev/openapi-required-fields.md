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

## The tuple/map surface (Phase 2)

The same guard file now also pins the **positional and cardinality** keywords,
which no fixed point named before: `prefixItems`, `minProperties`,
`maxProperties`, `discriminator` — **9 rows** across the component schemas.

None of the guards in the table above reads them, and none *can*:

| Keyword | Why no two-artifact check sees it | Client-visible how |
| --- | --- | --- |
| `prefixItems` | not in `_FIELD_CONSTRAINT_DIGEST`'s `_KEYS` | a **positional tuple** |
| `minProperties` / `maxProperties` | bounds a map printed as index sig | not expressible in TS |
| `discriminator` | dropped; printed as a `@constant` note | names the switcher |

Four published tuples carry `prefixItems` (`ExpPatternResponse.value_range`,
`SequenceAlignResponse.query_range` / `.target_range`,
`SequenceCapabilitiesResponse.k_range`). Retyping one slot changes the
argument the caller may pass.

**Decisive ablation (live `ebfa4c5f`)** — byte-preserving
`query_range` second slot `integer → string` in the snapshot, the matching
`number, number` → `number, string` in the generated tuple, both
`_PINNED_ARTIFACTS` blob ids honestly re-pinned:

| Guard | Drifted bytes |
| --- | --- |
| all eleven other `check_openapi_*` | `rc=0` |
| `check_openapi_required_fields.py` **before** this change | `rc=0` `OK (...)` |
| `check_openapi_required_fields.py` **after** this change | `rc=1`, names `_VALUE_DIGEST` |
| `bash scripts/smoke.sh --profile contracts` before | **SMOKE PASS / 922 passed** |
| `bash scripts/smoke.sh --profile contracts` after | **SMOKE PASS / 932 passed** |

The new literals are deliberately **separate** from `_REQUIRED_FIELD_DIGEST`:
requiredness is a set of field names, these are ordered slots and integer
bounds. Folding them together would make "the tuple's second slot is now a
string" report as "a required field moved", and the failure reason would lose
its resolution.

Two doors, with distinct jobs, each proven by its own positive control:

- **Door 4** (`_VALUE_DIGEST` + count door + per-keyword counts) catches a
  **coordinated** regenerate of both halves, because the literal is
  independent of both. A same-count rotation of two map bounds moves it while
  every count and the row set stay put.
- **Door 5** compares every published tuple's **slot types in order** against
  the generated tuple, so a **one-sided** edit is named by field with both
  shapes quoted. It compares types, not just arity: an arity-only door would
  let a client-side retype pass, which the `--self-test` case
  `one-sided client tuple slot retype` exists to prevent.

`_ts_slot()` maps a published slot to the TypeScript type; anything it does
not model renders as `UNMODELLED(...)`, which is distinct from every modelled
type, so a future slot type fails loudly instead of passing by being unknown.

**Self-agreeing ablation** (`pinned_value_digest = actual_value`): the
`--self-test` reports exactly three `NOT caught` — `coordinated tuple slot
retype (both halves)`, `coordinated maxProperties retype`, `same-count map
bound rotation` — `rc=1`, with the six required-field cases and the two
one-sided cases still caught. Restore → `13 cases, 0 failure(s)`.

## Adding a required field

1. Make the intentional source/artifact change.
2. Recompute `_REQUIRED_FIELD_DIGEST` with the guard's own `_digest(rows(...))`
   and update `_EXPECTED_REQUIRED_ROWS` / `_EXPECTED_SCHEMAS` in the **same
   commit**.
3. Say why in the PR. Re-deriving the digest from the artifact under guard
   would make the pin self-referential.
For a tuple/map keyword, do the same with `_VALUE_DIGEST` /
`_EXPECTED_VALUE_ROWS` / `_EXPECTED_VALUE_BY_KEYWORD`. A `prefixItems` change
must also move the generated tuple, since Door 5 compares slot types.

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
