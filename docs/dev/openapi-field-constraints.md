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

## Phase 5 — the generated `@example` half is value-pinned, not just counted

Door 5 pinned the generated half's **cardinality** (7 strict `@example` tags)
and the snapshot half's **values** (the independent `_EXAMPLE_DIGEST`); the
generated half's own values were pinned only *transitively* through that
snapshot digest. Rewriting one `@example` value in `openapi.d.ts` alone
(`Jane Doe` → `John Roe`) keeps all 7 tags, leaves the snapshot digest and
both count doors silent, and — once `generated_blob` is honestly re-pinned —
passes the whole contracts layer as SMOKE PASS. That is a
hand-edit-of-generated-file shape rather than a regenerate shape, and the
published contract value still cannot move silently because the snapshot
digest covers the same 7 values, but door 5 must not be read as "the generated
half is pinned". (Door 6 pins the *positions* of the 896 `@default` tags; it
does not read `@example` values.)

Phase 4 / door 7 pins the *values* of the 896 generated `@default` tags; it
does not read `@example`. This phase is the orthogonal column on the other
JSDoc projection, hence door 8 / Phase 5. The two land in the same commit on
one branch, so the guard file has a single ledger for all five doors.

Door 8 closes the asymmetry inside the same already-registered guard, with zero
new wiring: once the snapshot digest matches its literal and the tag count is
exact, the generated `@example` values are compared **in order** against the
digest-pinned snapshot projection. Ordered comparison (not a multiset) also
catches a same-count permutation that moves one tag's value onto another field.
Door 8 deliberately stands down when the snapshot digest drifts, so a
snapshot-side change is named by door 5 with full failure resolution rather
than being double-counted. Combined read data on this branch: `--self-test`
16 → 21 cases (19 for door 7 + 2 for door 8), companion suite 32 → 46 passed,
`openapi.json` / `openapi.d.ts` byte-for-byte unchanged, and the three hot
wiring files untouched.

## Phase 4 — published `additionalProperties` shape

`openapi.json` publishes **102** `additionalProperties` nodes across
`components.schemas`: 49 `true`, 35 `false`, and 18 schema-valued (`$ref`,
primitive `type`, or `anyOf`). `openapi-typescript` renders the 67 non-`false`
nodes as `[key: string]: <type>;` index signatures inside the generated
`components["schemas"]` block; a `false` node renders **no line at all**.
This is client-visible: a caller compiles against whether an object is open
or closed, and against the value type.

No fixed point read it:

* `_FIELD_CONSTRAINT_DIGEST` walks `_KEYS` (scalar constraints + `default`);
  `additionalProperties` is a schema shape, not a scalar keyword;
* `_REQUIRED_FIELD_DIGEST` / `_VALUE_DIGEST` walk `required` arrays and
  positional/cardinality keywords;
* the enum, example, description, title, parameter and response guards walk
  their own columns;
* `_PINNED_ARTIFACTS` is provenance blob ids — re-pinning both is the
  documented "one reviewed action" beside a regenerate.

**Decisive ablation (live `b651c259`)**: flip
`AdminSiteBrandResponse.additionalProperties` `false -> true` in the snapshot
and add its `[key: string]: unknown;` line to the generated client (both
halves agree), honestly re-pin both blob ids:

| gate | result |
| --- | --- |
| all 12 `scripts/check_openapi_*.py` guards (plain + `--self-test`) | `rc=0` |
| all `scripts/test_openapi_*.py` companion suites | `299 passed` |
| `bash scripts/smoke.sh --profile contracts` | `SMOKE PASS` |

An object silently became open and nothing named it.

### The fix (zero new wiring)

Extend the already-wired guard; `smoke.sh` / registry / teeth untouched:

* `_ADDITIONAL_PROPERTIES_DIGEST` — hand-written sha256 over canonical sorted
  `(dotted path, canonical JSON value)` rows, read from nowhere.
* `_CLIENT_ADDITIONAL_PROPERTIES_DIGEST` — a second hand-written sha256 over
  the generated `(component, index-signature type)` rows. Checking the client
  against the snapshot under guard would pass on exactly the co-revert above;
  the client half is pinned to its own literal instead.
* `_EXPECTED_ADDITIONAL_PROPERTIES = 102` /
  `_EXPECTED_CLIENT_ADDITIONAL_PROPERTIES = 67` — exact count doors.
* Door 10 — derive the client projection from the snapshot and compare
  multisets; one-sided drops/retypes are named by component. A coordinated
  co-revert is caught by the two digests, not by agreement.
* `--self-test` → **27 cases**: the decisive co-revert, its same-commit
  re-pin positive control, both one-sided rewrites, a coordinated type retype
  and a dropped node. Gutting both digest doors to `actual = pinned` makes the
  self-test `rc=1` — the floor is not vacuous.
* Companion → **53 cases**, including the independent-literal AST
  assertion, the co-revert / re-pin pair, count-door and client-door weight,
  and a gutted-guard (`actual = pinned`) check from a second file.

A legitimate change re-pins **both** literals (and the client count when the
line count moves) in the same commit as both artifacts and says why.

## Phase 6 — the field a generated `@example` tag is printed under (door 11)

Phase 5 / door 8 pins the generated half's **values**, but it compares a flat,
unlabelled sequence of the 7 `@example` values against the snapshot's values
in document order. Field identity is not part of that comparison. The generator
prints each tag *inside a property's doc block*, so which field carries the tag
is itself a published fact — and door 8 cannot see it.

**Decisive ablation on live `9a7c3e52`**: drop the `@example` tag from
`LoginRequest.username` and add a second identical tag to
`LoginRequest.email`. Both fields publish `researcher@univ.edu`, so the flat
value sequence is unchanged; all 7 tags survive, the snapshot is untouched,
both count doors and `_EXAMPLE_DIGEST` stay green. Re-pin `generated_blob`
honestly (the generated file really did change) and the result is **all 12
wired `check_openapi_*` guards `rc=0`, companion 53 passed, whole contracts
layer `SMOKE PASS / 1103 passed + 41 subtests / 0 failed`**. A tag relocated
between two doc blocks shipped silently. This is the shape a flat positional
comparison is structurally blind to, and it is one layer deeper than the
"count is not a value" residual Phase 5 closed.

### The fix (zero new wiring, one ledger)

Extend the same already-registered guard; `smoke.sh` / registry / teeth /
`REQUIRED_GUARD_CALLS` / `_WIRED_SELF_TESTS` untouched:

* `generated_example_rows()` — reads the generated `@example` tags labelled
  with their `(component, field)`. Uses `finditer`, not `search`: a doc block
  may carry two tags, and a reader that quietly reads less is the same failure
  mode as a guard that quietly checks less.
* `example_projection()` — reads the snapshot's published examples per field
  in document order. Compared against the **digest-pinned** snapshot rather
  than a second hand-written literal, so the generated half inherits
  `_EXAMPLE_DIGEST`'s reviewed re-pin contract and there is no new number to
  keep in sync.
* Compared **per field, values in order**: a dropped tag names the one field
  that lost it instead of shifting every later tag and naming six innocent
  neighbours; ordered values within a field still catch a same-count
  permutation.
* Door 11 stands down when `_EXAMPLE_DIGEST` has drifted (a snapshot-side
  rewrite stays door 5's alone) or when the tag cardinality moved (the count
  door names it once). Door 8 stands down when door 11 is wired on — door 11
  is strictly stronger, so a value drift is reported once, not twice. The
  `--self-test` off-control (`pin_example_fields=False`) proves both halves
  are load-bearing.

`--self-test` **27 → 32 cases**, companion **53 → 60 passed** (7 new cases
from a second file: relocation named per field, off-control silent,
`finditer` reader, stray tag resolved by the count door alone, mirror control,
zero-new-wiring, plants registered). `openapi.json` / `openapi.d.ts`
byte-for-byte unchanged — this adds a reader, it touches neither artifact.

### Division of labour (positive controls)

| drift | fires |
| --- | --- |
| one tag relocated between two same-value fields | door 11 only, both fields named |
| one generated value rewritten | door 11 only (`UserCreate.full_name`) |
| two distinct values swapped | door 11 only, both fields named |
| a stray second tag on one field | count door only; door 11 stands down |
| a snapshot-side example value rewrite | `_EXAMPLE_DIGEST` only; door 11 silent |
| with door 11 disabled | the relocation is silent again |

A legitimate regenerate that moves a tag between fields must move the
snapshot's `examples` in the same commit with a reason; no literal re-pin is
needed for door 11 itself, because its authority is the digest-pinned
snapshot projection.

## Phase 7 — an independent literal for the generated `@example` values (door 12)

Phase 6 / door 11 pins *which field* prints each of the 7 `@example` tags, but
both door 8 and door 11 read the **snapshot** as their reference while the
generator reads `openapi.d.ts`. A regenerate that moves one value in **both
halves** is invisible to any two-artifact comparison by construction. The only
surviving witness was `_EXAMPLE_DIGEST` — and a regenerate *requires* you to
re-pin it, honestly, with a reason, alongside the two provenance blob ids.
Re-pinning those three is the "one deliberate act" the topology already
blesses; none of them is a literal for the value the client actually renders.

**Decisive ablation on live `9a7c3e52` / `8d5cb898`**: `Jane Doe` → `John Roe`
in `UserCreate.full_name`'s snapshot `examples` *and* its generated `@example`
tag, `_EXAMPLE_DIGEST` re-pinned to the derived value, both blob ids honestly
re-pinned:

| gate | result |
| --- | --- |
| `check_openapi_field_constraints.py` plain + `--self-test` | `rc=0` / `32 cases, 0` |
| all 12 wired `check_openapi_*` guards | `rc=0` |
| door 5 / door 11 | zero failures |
| `smoke.sh --profile contracts` | `SMOKE FAIL / 12 failed` — all from
  the guard's `str.replace` plants and `_PINNED_ARTIFACTS` blob ids, not from
  a witness that the published value is right |

The layer that caught it was plant fragility plus provenance re-pinning, not a
fixed point on the value. A hand re-pin of `snapshot_blob` / `generated_blob`
fixes all 12 without touching the value. This is the same genus as
"`_TABLE_DIGEST` cannot see an absent row": a digest over a projection whose
reference is the projection.

### The fix (zero new wiring, one ledger)

Extend the same already-registered guard; `smoke.sh` / registry / teeth /
`REQUIRED_GUARD_CALLS` / `_WIRED_SELF_TESTS` untouched:

* `_GENERATED_EXAMPLE_VALUE_DIGEST` — hand-written sha256 over canonical
  sorted `(component, field, value)` rows read from the 7 generated tags, in
  the `_DEFAULT_TAG_VALUE_DIGEST` mould. One literal, read from nowhere,
  separate from `_EXAMPLE_DIGEST` so a dropped tag and a retyped value do not
  read as the same drift.
* Exact row-count constant `_EXPECTED_GENERATED_EXAMPLE_VALUE_ROWS = 7`.
* **Door 12 stands down whenever the two halves already disagree**, so a
  one-sided rewrite keeps door 11's named-field failure, a snapshot-side
  rewrite stays door 5's alone, and a cardinality drift stays with the count
  door. What is left is the coordinated shape: both halves publish the same
  *new* value, all counts hold, and the snapshot digest has been honestly
  re-pinned — every two-artifact door is silent and only this literal names it.
  **Sound for a single cause, deferred for concurrent ones**: door 12 stands
  down on a three-clause conjunction — the snapshot digest matches (door 5
  silent), the generated tag count matches (count door silent), and
  `example_field_drift(...)` is empty (door 11 silent). It therefore defers to
  *any* concurrent drift that owns a door — door 5, the count door, or door 11
  — not only to a one-sided field drift. A generated-side stray tag, for
  instance, trips the count door (`8 != 7`) and leaves door 12 unnamed. Resolve
  the concurrent drift and door 12 re-arms; revert the commit and nothing
  ships. Delayed, not permanent — a resolution-order effect, and the
  conjunction's arity is pinned from a second file.
* **Precedence: replacement, not addition.** `_GENERATED_EXAMPLE_VALUE_DIGEST`
  *replaces* the generated-half reference door 12 would otherwise derive from
  `generated_example_rows()` — it does not sit beside it. Door 11 still reads
  `example_projection(document)`, the snapshot it guards. That conjunction is
  what makes the shape deterministic: a coordinated both-halves move lands on a
  reference door 11 also trusts, so door 11 stays silent and is never
  pre-empted, and only the literal names the value; a concurrent decoy gives
  door 11 a real disagreement to name first, so door 12 defers instead of
  closing over it.
* A reviewed regenerate now re-pins **two** literals in the same commit as
  both artifacts, with a reason. Re-pinning only `_EXAMPLE_DIGEST` (the shape
  the topology used to bless) no longer agrees; that off-control is planted.

`openapi.json` / `openapi.d.ts` byte-for-byte unchanged — this adds a reader
and one literal, it touches neither artifact. `--self-test` **32 → 35 cases**,
companion **60 → 71 passed** (+11). The contracts layer's wiring line count
is unchanged.

### Division of labour (positive controls)

| drift | fires |
| --- | --- |
| value rewritten in both halves + `_EXAMPLE_DIGEST` re-pinned | door 12 only |
| one-sided generated value rewrite | door 11 only, field named |
| same-value tag relocated between two fields | door 11 only, both fields named |
| snapshot-side value rewrite | `_EXAMPLE_DIGEST` only; door 12 silent |
| a stray second tag | count door only; door 12 stands down |
| coordinated rewrite + generated-side stray tag | count door only; door 12 silent |
| reviewed regenerate re-pins both literals | green |
| regenerate re-pins only `_EXAMPLE_DIGEST` | door 12 |

### Residual acknowledged, not asked for

Door 11 compares `sorted()` over `(component, field)`, so the **file order** of
the doc blocks is unpinned: a regenerate that reorders properties moves only
`generated_blob`. Narrow, same family. Not this phase.

**Unrelated pre-existing gap, flagged once:** 912 of the 919 generated doc
blocks carry no `@example`, and `_DEFAULT_TAG_DIGEST` pins presence of
`@default` tags only, so *which fields print a doc block at all* is unpinned.
Historical and wider; not proposed here.
