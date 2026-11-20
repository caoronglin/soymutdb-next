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

## The component-to-component `$ref` wiring (Phase 3)

A third surface in the same file is the **intra-schema `$ref` topology**: which
component each property-level `$ref` inside `components.schemas` points at.
`packages/api-client/openapi.json` publishes **229** such refs across **145**
owner schemas, naming **140** distinct targets. `openapi-typescript` renders
each one as a `components["schemas"]["<target>"]` line inside that owner's
block in the generated client — the TypeScript a consumer compiles against.

No landed fixed point reads *which* component a property points at:

| Guard | Reads | Blind to |
| --- | --- | --- |
| `test_openapi_snapshot_contract.py` | that every `$ref` resolves to a defined name | which name |
| `test_openapi_snapshot_body_integrity.py` / `check_openapi_inline_body_integrity.py` | `$ref` bodies under `paths.*.responses` / `requestBody` | refs inside a schema |
| `check_openapi_published_enums.py` | value domains | `$ref` topology |
| `_REQUIRED_FIELD_DIGEST` / `_VALUE_DIGEST` | required arrays and positional/cardinality keywords | `$ref` targets |
| `_PINNED_ARTIFACTS` | blob ids of the two artifacts | re-pinning both is the documented "one deliberate reviewed action" beside a regenerate |

**Decisive ablation (live `c3e88a49b`)** — byte-preserving swap of the two
array-item refs inside `AdminDashboardSeries`
(`ImportThroughputPoint` ↔ `QueryLatencyPoint`) in **both** artifacts, with
both `_PINNED_ARTIFACTS` blob ids honestly re-pinned:

| Reading | Old guard | New guard |
| --- | --- | --- |
| all 11 other wired `check_openapi_*` (plain + `--self-test`) | `rc=0` | `rc=0` — zero false positives |
| all 14 `test_openapi_*` suites | green | green |
| `check_openapi_required_fields.py` | `rc=0 OK` | **`rc=1`**, names `_SCHEMA_REF_DIGEST` **and** `_CLIENT_SCHEMA_REF_DIGEST` |

The generated client silently types `import_throughput` as
`QueryLatencyPoint` and `query_latency` as `ImportThroughputPoint`. It is a
pure **permutation**: every count, the set of owners, the set of targets, and
the `(owner, target)` multiset are unchanged. Only a positional fixed point
can see it, so the client reader captures the **property name** on each ref
line too — a multiset of targets alone is blind to exactly this drift.

### Three doors, each with a distinct job

- **Door 6** — `_SCHEMA_REF_DIGEST`: a hand-written sha256 over the canonical
  sorted `(owner, dotted path, target)` rows, read from the snapshot alone.
  Three exact count doors (`229` rows / `145` owners / `140` targets) name a
  drop or add without relying on the digest. A coordinated regenerate of both
  halves still moves this literal, because it is derived from neither.
- **Door 7** — `_CLIENT_SCHEMA_REF_DIGEST`: a **second** independent sha256 over
  the canonical sorted `(owner, field, target, occurrence)` rows of the
  generated client's `components["schemas"]["..."]` lines. Two independent
  fixed points are the point: re-pinning only the snapshot digest cannot
  silence the client door, and a co-revert that makes both halves agree still
  moves both. The reader is scoped to the `components.schemas` interface, so
  an 8-space-indented `parameters` / `responses` / `requestBody` sub-block is
  never mistaken for a component definition.
- **Door 8** — named positional agreement: the snapshot's
  `(owner, field, target)` multiset must equal the client's, so a one-sided
  edit is named by owner, field and target. `_ref_field()` normalises a free-form
  map's `additionalProperties` path to the client's `[key: string]` index
  signature, which is the only shape where the two halves spell the field
  differently.

`_schema_ref_digest` includes the full dotted path (`items`, `anyOf`, ...), so
a ref moved one wrapper deeper is caught even when the field and target are
unchanged.

### Self-agreeing ablation (`pinned = actual`)

Four shapes on the same coordinated swap; only one is a legal green:

| Shape | Result |
| --- | --- |
| no re-pin | RED (2 failures) |
| only `_SCHEMA_REF_DIGEST` re-pinned | RED (`_CLIENT_SCHEMA_REF_DIGEST`) |
| only `_CLIENT_SCHEMA_REF_DIGEST` re-pinned | RED (`_SCHEMA_REF_DIGEST`) |
| **both digests honestly re-pinned in the same commit** | **GREEN** |

Any intermediate commit is red, so a reviewer never sees a false green. This
is the same "legal change path" as Phase 2.

### Adding or moving a component ref

1. Make the intentional source/artifact change.
2. Recompute **both** `_SCHEMA_REF_DIGEST` and `_CLIENT_SCHEMA_REF_DIGEST`
   with `_schema_ref_digest(schema_ref_rows(...))` and
   `_client_schema_ref_digest(client_schema_ref_rows(...))`, update the exact
   count doors, all in the **same commit**, and say why. Re-deriving either
   literal from the artifact under guard would make the pin agree with itself.
3. `smoke.sh` / registry / teeth are deliberately **not** extended: the guard
   is already wired through `--self-test`, and the teeth case floor is a
   *minimum*. Adding self-test cases (13 → 18) and companion cases (21 → 30)
   needs no wiring edit, so this phase touches only the three files below.

Files changed in this phase: `scripts/check_openapi_required_fields.py`,
`scripts/test_openapi_required_fields.py`, `docs/dev/openapi-required-fields.md`.

## Door 9 — published scalar `type` assignment

`openapi.json` publishes **3050** scalar `type` values on schema nodes
(component roots, properties, `anyOf`/`oneOf` branches, `items`, nested
`$defs` copies). `openapi-typescript` turns each property's type into the
TypeScript declaration a consumer compiles against, so `integer` → `number`
and `string` → `string` are client-visible facts. No landed fixed point read
the value:

- `_FIELD_CONSTRAINT_DIGEST` walks constraint keywords, not `type`;
- `_REQUIRED_FIELD_DIGEST` walks required-field names;
- `_VALUE_DIGEST` walks positional/cardinality keywords;
- the enum baseline walks value domains, the response/operation digests walk
  paths, and `test_openapi_snapshot_contract.py` checks key order and field
  sets but never the type value;
- `_PINNED_ARTIFACTS` is a provenance blob id — re-pinning both beside a
  regenerate is the documented reviewed act.

Decisive ablation on live bytes: byte-preserving `integer → string` rewrite of
`AdminDashboardStats.totalUsers` in **both** artifacts, with both blob ids
honestly re-pinned, left every wired `check_openapi_*` guard, every
`test_openapi_*` suite and `smoke.sh --profile contracts` `SMOKE PASS` while
the generated client silently retyped a numeric metric.

`check_openapi_required_fields.py` now pins two independent literals:

- `_SCHEMA_TYPE_DIGEST` — sha256 over canonical sorted `(schema path, type)`
  rows, read from nowhere. A co-revert of both halves still moves it.
- `_CLIENT_PROPERTY_TYPE_DIGEST` — a second, separately hand-written sha256
  over `(component, field, TS type)` rows parsed from the generated component
  blocks. Re-pinning only the snapshot side cannot silence a retyped
  declaration.
- `_EXPECTED_SCHEMA_TYPE_ROWS` / `_EXPECTED_SCHEMA_TYPE_BY_TYPE` /
  `_EXPECTED_CLIENT_PROPERTY_ROWS` — exact count and distribution doors; a
  same-count rotation between two sibling properties is caught positionally.

`--self-test` adds six Door 9 cases (coordinated co-revert, both one-sided
halves, single-digest re-pin stays red, same-count rotation, and a coordinated
retype of a property literally named `type`) and the companion suite pins each
literal's independence and each failure direction on committed bytes.

Five component schemas publish a property literally named `type` —
`FieldError`, `ImportCreateRequest`, `MultipartStartRequest`,
`NotificationResponse`, `ValidationError` — plus a sixth row from the nested
`ValidationErrorResponse/$defs/FieldError` copy. An earlier walker skipped any
child key named `type` after consuming the scalar keyword, so those six rows
never entered `_SCHEMA_TYPE_DIGEST`: a byte-preserving retype of one such row
in **both** artifacts, with the generated client's independent literal also
re-pinned, left every door green. The walker now tests the child's **value**,
not its key name — a `type` keyword is a scalar and is consumed, while a
`type`-named property is a dict and is walked into. The census is 3050 and the
companion pins all six by path. #316 fixed the same bug genus on the `title`
column; this is the `type` column's turn.
