# Published field-level constraint pin

`packages/api-client/openapi.json` publishes 1712 field-level values across
263 component schemas: 815 JSON Schema constraint rows (`minimum`, `maximum`,
`exclusiveMinimum`, `exclusiveMaximum`, `minLength`, `maxLength`, `minItems`,
`maxItems`, `pattern`, `format`, `multipleOf`) plus 897 `default` values. They
are part of the public contract — runtime validation enforces them, and a
client generated from the document can read them.

## Why no other guard sees them

The generated `packages/api-client/src/generated/openapi.d.ts` emits JSDoc
tags for `@description`, `@default`, `@enum`, `@constant` — but **none** of
these numeric/string constraints. For `default` the second half *does* exist:
the generator renders `@default 0` from the snapshot value. That is not a
defence. A coordinated regenerate that rewrites `default: 0 -> 999999` in the
snapshot **and** the matching `@default` line, then honestly re-pins both
provenance blob ids, leaves every two-artifact check self-consistent. Only an
independent literal can see it. Every wired fixed point reads a different
surface:

- `check_openapi_published_enums.py` walks only `enum` / `const`;
- the body baselines (`_RESPONSE_BODY_BASELINE`, `_BODY_PAIR_DIGEST`,
  `_INLINE_BODY_BASELINE`) read bodies, not property schemas;
- the operationId, parameter and response-surface digests do not descend into
  `components.schemas` properties;
- `_PINNED_ARTIFACTS` is provenance blob ids, and re-pinning them is the
  documented "one reviewed action" beside a regenerate.

Decisive ablations on the shipped tip: a byte-preserving `maxItems: 100 → 999`
edit, and the coordinated `default: 0 → 999999` co-revert in both halves with
both blob ids re-pinned — both leave all wired OpenAPI guards, their
`--self-test` suites and the whole contracts layer green. Nothing reports that
a published value changed. The `default` case is why that column joined this
pin (schema `v2`) rather than getting a second two-artifact comparison.

**#282 folded `default` into `_FIELD_CONSTRAINT_DIGEST` but did not carry
a floor on the generated half.** #284 had one (`_EXPECTED_JSDOC_DEFAULTS`,
896 tags) yet was superseded by #282 under the one-ledger rule, so the
increment was dropped. Measured on live `ebfa4c5f`: delete one `@default`
JSDoc line from `openapi.d.ts` and honestly re-pin both provenance blob ids
→ 12 wired OpenAPI guards `rc=0`, `SMOKE PASS / 922 passed + 5 subtests +
10 env-bound / 0 failed`. A published default tag could vanish with no
report. This is the sharp version of the same handoff: the merged PR and
the superseded one were each right, and the only non-duplicate thing in
the superseded one nearly sank with it. See Phase 3.

## The pin

`scripts/check_openapi_field_constraints.py` reads committed bytes only
(`json` + stdlib; no Python 3.15 venv, no API import, no wheel).

- `_FIELD_CONSTRAINT_DIGEST` — a hand-written sha256 over the canonical sorted
  `(path, key, value)` rows of every real schema node. It is a literal read
  from nowhere, not derived from the artifact under guard; re-deriving it under
  guard would make the pin self-referential.
- `_EXPECTED_CONSTRAINT_ROWS`, `_EXPECTED_SCHEMAS`, `_EXPECTED_BY_KEY` —
  exact shape doors, so a drop/add/retype is named even before the digest.
- A dict is a schema node only when it carries a schema marker
  (`type`, `$ref`, `anyOf`, `oneOf`, `allOf`, `enum`, `const`, `items`).
  `properties` maps are name → schema, not schemas: a field literally named
  `format` / `minimum` / `pattern` / `default` (e.g.
  `ExportManifestResponse.properties.format`,
  `SettingFieldSchema.properties.default`) is **not** a constraint on the map;
  the map entry is a name → schema, while the property's own schema node may
  legitimately carry those keywords. A naive flat-key walk overcounts; both
  readers in this guard agree on 1712 rows / 263 schemas.
- `--self-test` plants eight constraint/default drifts, six `examples` drifts
  (Phase 2) and two generated `@default` tag drifts (Phase 3) — 16 cases,
  each asserted caught; the clean tree must pass first.

`scripts/test_openapi_field_constraints.py` is the companion suite: it proves
the digest is a source literal, that a same-count permutation still moves it,
that a same-commit re-pin stays green, and that the wiring is pinned in all
three floors.

## Changing the contract

A legitimate change moves the snapshot **and** the generated client, re-pins
`_FIELD_CONSTRAINT_DIGEST`, `_EXAMPLE_DIGEST`, `_DEFAULT_TAG_DIGEST` and their
count doors in the same commit, with a reason — exactly like
`_ERROR_RESPONSE_BASELINE` / `_BODY_PAIR_DIGEST`. The guard's plain run
compares both committed artifacts to the literals, so an edited value or a
dropped tag with untouched pins is rejected on a bare clone, in a squash
and on a shallow checkout.

## Wiring

The guard is wired into `smoke_contracts()` via `--self-test`, with its
companion in `tests=()`, and pinned in all three floors (unchanged by the
`default` extension — no new guard, no new wiring row):
`REQUIRED_GUARD_CALLS` + `PINNED_SUITES` (registry), `_WIRED_SELF_TESTS` +
`_SIGNATURES` + `_EVIDENCE_PER_CASE` (teeth). The teeth guard runs the
`--self-test` as a real process and requires its pinned evidence; dropping any
one of the five wiring lines fails closed.

## Phase 2 — the published `examples` projection (door 5)

`openapi.json` publishes 7 `examples` arrays on property schemas
(`LoginRequest` × 3, `UserCreate` × 4). The generator renders each as a
`* @example <value>` JSDoc tag in `openapi.d.ts`. That second half is **not** a
defence: a coordinated regenerate that rewrites all 7 values in the snapshot
*and* the 7 `@example` tags, then honestly re-pins both provenance blob ids,
leaves every two-artifact check self-consistent.

Decisive ablation on live `ebfa4c5f`: all 7 values rewritten in both halves +
both blob ids re-pinned →

| reader | result |
| --- | --- |
| 12 wired OpenAPI guards | all `rc=0` |
| 12 OpenAPI `test_*` suites | 187 passed |
| `smoke.sh --profile contracts` | SMOKE PASS / 922 + 5 + 10 / 0 |

`_FIELD_CONSTRAINT_DIGEST` walks the scalar constraint/default keywords only;
`examples` is a list-valued sibling and is not one of `_KEYS`. No operation
digest descends into these property nodes. This column had **zero fixed
points** — not "one guard with a weak signal", which is the sharper failure
mode than a simple unread field.

### The pin, and why it is a separate door

- `_EXAMPLE_DIGEST` — a second hand-written sha256 over canonical sorted
  `(path, index, value)` rows of every published `examples` array. Separate
  from `_FIELD_CONSTRAINT_DIGEST` on purpose: folding ordered sample values
  into the scalar-keyword digest would lose failure resolution (a dropped
  `@example` tag would read as a constraint drift).
- `_EXPECTED_EXAMPLES = 7` / `_EXPECTED_GENERATED_EXAMPLES = 7` — exact count
  doors on both halves. The generated half uses a strict `^\s*\* @example `
  marker: a `@description` block carrying `user@example.com` makes the naive
  substring count **8**, and must not be inherited as an 8th tag.
- `example_rows()` applies the same schema-marker rule as `rows()`: a field
  literally named `examples` is not the keyword.

Division of labour is pinned by positive controls, not asserted in prose:

| ablation | fires |
| --- | --- |
| coordinated co-revert (both halves + blob re-pin) | `_EXAMPLE_DIGEST` only (1) |
| same-count value swap | `_EXAMPLE_DIGEST` only; count doors silent |
| one example dropped from the snapshot | digest + `_EXPECTED_EXAMPLES` |
| one generated `@example` tag dropped | `_EXPECTED_GENERATED_EXAMPLES` only |
| forged strict marker invented in prose | `_EXPECTED_GENERATED_EXAMPLES` only |

Without the swap control, door 5 would be nothing but a count check wearing a
digest-shaped coat. The complement — the real `@description` decoy line is
*not* counted — is a clean-tree reverse invariant pinned from the companion
suite, not an ablation.

### Non-duplication, made testable

- `_KEYS` still contains no `examples`; `_FIELD_CONSTRAINT_DIGEST` is unchanged
  and still recomputes from the constraint rows alone.
- `test_openapi_behavior_contracts.py` still reads `x-idempotent` /
  `x-pagination`, and the operation digests still do not descend into property
  `examples` — door 5 does not converge with any of them.
- **Zero new wiring**: no `smoke.sh` / `check_contracts_registry_collection.py`
  / `check_contracts_self_test_teeth.py` edit, no new guard file. Those three
  are exactly where #272 / #273 / #281 collided while in flight. The teeth
  `_SIGNATURES` regex is `\d+ cases` (count-independent), so the self-test
  growing 8 → 14 plants needs no floor edit.

Read data: `--self-test` 8 → 14 cases; companion suite 15 → 25 passed;
`openapi.json` / `openapi.d.ts` byte-for-byte unchanged.

## Phase 3 — the generated `@default` tag projection (door 6)

The 897 `default` values have a second published half the snapshot digest does
not read: `openapi-typescript` renders 896 of them as `@default` JSDoc tags on
component property doc blocks in `openapi.d.ts`. (The one exception,
`InlineTarget.kind`, is a `const` discriminator rendered as a literal type, so
the generator emits no tag; 897 snapshot values → 896 generated tags is a
legitimate shape, not a drift.)

Decisive ablation on live `ebfa4c5f`: delete one `@default null` line and
honestly re-pin both provenance blob ids → all 12 wired OpenAPI guards `rc=0`,
`SMOKE PASS / 922 + 5 + 10 / 0`. `_FIELD_CONSTRAINT_DIGEST` reads only the
snapshot, `_EXAMPLE_DIGEST` reads only `examples`, `_PINNED_ARTIFACTS` is
provenance, and `test_openapi_snapshot_contract.py` compares field sets —
none asks "is this tag still here".

### The pin

- `_DEFAULT_TAG_DIGEST` — a hand-written sha256 over canonical sorted
  `(component, field)` rows of the 896 `@default` tags, read from the committed
  `openapi.d.ts` only, not derived from the snapshot under guard.
  `_EXPECTED_DEFAULT_TAGS = 896` is the exact count door.
- The generated half is checked against the *pinned* literal, not against the
  snapshot, so a co-revert of both halves cannot agree on a dropped tag.
- A same-count relocation (a tag moved between two fields in one component)
  fires **only** `_DEFAULT_TAG_DIGEST`; both count doors stay silent. That
  positive control is what makes this a positional fixed point rather than a
  second tally.
- The parser restricts itself to the `components.schemas` region (component
  blocks at 8-space indent, property doc blocks at 12), so same-indent
  `parameters` / `responses` blocks cannot be mistaken for components. Both a
  one-line `/** @default x */` and a multi-line doc block are read.

### Changing the contract

A reviewed regenerate that legitimately drops or moves a `@default` tag must
re-pin `_DEFAULT_TAG_DIGEST` and `_EXPECTED_DEFAULT_TAGS` in the same commit as
`openapi.d.ts`. The companion suite pins the literal from a second file, proves
the two generated JSDoc projections (`@default` and `@example`) are distinct,
and asserts both ablation shapes are named.

## Phase 4 — the value written in each generated `@default` tag (door 7)

Phase 3 pins the *presence and location* of the 896 tags — `(component,
field)` rows — but not the published value written in the tag. That is a
second, genuinely unowned cell, one layer deeper:

**Decisive ablation on live `94dfac2e`**: retype one generated
`@default 10000` → `@default 9999`, leave the snapshot's 897 `default` rows
untouched, and honestly re-pin `generated_blob` in `_PINNED_ARTIFACTS` to the
new bytes. `_DEFAULT_TAG_DIGEST` is unchanged (same `(component, field)`),
`_EXPECTED_DEFAULT_TAGS` holds (896), every other wired OpenAPI guard and the
whole contracts layer stay **`SMOKE PASS / 1017 passed + 41 subtests / 0
failed`**. A client reading the generated fallback value gets `9999` instead
of `10000`, and no fixed point reports it.

### The pin

- `_DEFAULT_TAG_VALUE_DIGEST` — a second hand-written sha256 over canonical
  sorted `(component, field, value)` rows, read from nowhere. Deliberately
  **separate** from `_DEFAULT_TAG_DIGEST`: a dropped tag and a retyped value
  are different drifts with different failure reasons, and folding them into
  one digest would lose that resolution.
- `default_tag_values()` reuses Phase 3's doc-block region and property
  regexes, so the two readers cannot disagree about *which* fields carry a
  tag. The value is the tail of the `@default` line only; trailing
  `* @enum` / `* @constant` / `*/` lines in a multi-line block are not part of
  the published value. The one empty-string default renders as a bare
  `@default` and is counted by its position as `""`.
- Checked against the **literal**, not against the snapshot's `default`
  values: the generator renders floats (`0.00001`), arrays and the empty
  string differently from JSON, so a two-artifact token comparison would be a
  second brittle ledger.

### Division of labour (positive controls, not prose)

| Drift | Doors that fire |
| --- | --- |
| one tag value retyped (`@default 10000 → 9999`) | **Door 7 only** (1 failure); Door 6's location digest and count stay silent |
| two distinct tag values swapped (same count) | **Door 7 only** (1 failure) |
| one `@default` tag dropped | Door 6 count + Door 6 location + Door 7 value |
| one tag relocated between two fields | Door 6 location + Door 7 value; both count doors silent |
| bare `@default` given a value | **Door 7 only** |

A pure retype firing only door 7 is the decisive control: without it, this
would be a count check wearing a digest-shaped coat. A reviewed regenerate
re-pins both digests in the same commit as the client, with a reason.

### Zero new wiring

Door 7 lives in the already-registered `check_openapi_field_constraints.py`.
No `smoke.sh` / registry / teeth edit, no new guard file, no `git config`
change, and `openapi.json` / `openapi.d.ts` byte-for-byte unchanged. The teeth
`_SIGNATURES` regex is `\d+ cases`, so the self-test growing 16 → 19 plants
needs no floor edit. Two Phase-3 companion assertions were reconciled (not
weakened): a tag relocation and a reviewed tag drop now legitimately move the
value rows too, so they re-pin / expect both digests.
