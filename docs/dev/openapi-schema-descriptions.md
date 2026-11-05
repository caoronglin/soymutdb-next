# Published component-schema descriptions and titles

`packages/api-client/openapi.json` publishes **257 `description` strings** on
component-schema nodes across **169 schemas**, and **2327 `title` strings**
across all **362 schemas**. `openapi-typescript` renders each description as an
`@description` line and each title as the first prose line of a
`components["schemas"]` JSDoc block — the prose an IDE shows a caller hovering
a field. Multi-line descriptions become `@description <first line>` plus
indented continuation lines; the generator also emits exactly one synthetic
`@description discriminator enum property added by openapi-typescript` line and
one synthetic `Title` JSDoc line.

## The gap this guard closes

Every other wired fixed point reads a different surface:

| Fixed point | What it walks |
| --- | --- |
| `_FIELD_CONSTRAINT_DIGEST` | constraint keywords + `default`; `description` is not in `_KEYS` |
| `_REQUIRED_FIELD_DIGEST` | `required` arrays and generated `?:` markers |
| `_ANNOTATION_DIGEST` / `_RESPONSE_SURFACE_DIGEST` / summary digest | operations, not schemas |
| document-metadata lock | top-level `info` and the tag catalog |
| inline-body / body baselines | body shapes |
| `_PINNED_ARTIFACTS` | provenance blob ids (re-pinning both is one reviewed action) |

Decisive ablation on live bytes: rewrite one property's `description` in the
snapshot and the matching `@description` line in the generated client
(byte-preserving, both halves agree), re-pin both blob ids — all eleven wired
OpenAPI guards, their `--self-test` suites and the whole contracts layer stay
`SMOKE PASS`. A client-visible doc line changes and nothing pins it.

## What `check_openapi_schema_descriptions.py` pins

* `_SCHEMA_DESCRIPTION_DIGEST` — a hand-written sha256 over canonical sorted
  `(schema path, description)` rows, exported from the snapshot alone. A
  co-revert of both halves still changes it. Re-deriving it from the guarded
  artifact would make the pin self-referential.
* `_EXPECTED_ROWS` (257) / `_EXPECTED_SCHEMAS` (169) — exact count doors. A
  drop/add is named even when the digest is re-pinned; a same-count rotation
  cannot hide behind the counts.
* The generated client's `@description` first-line multiset, compared against
  the **pinned** snapshot rows (plus the one documented synthetic line), not
  against the snapshot under guard. A one-sided JSDoc rewrite is named, and a
  coordinated regenerate cannot pass by making both halves agree on a drift.

The digest and the generated-client multiset door are independent of each
other on a one-sided edit, but the multiset's expected rows are derived from
the **snapshot under guard**, not a literal. So a coordinated co-revert that
rewrites both halves and honestly re-pins `_SCHEMA_DESCRIPTION_DIGEST` in one
commit makes Door 3 agree with itself and pass — that is the failure below.

## The description half's second literal

The title half already carries two independent generated-client literals
(Door 6 sorted digest and Door 7 positional triples). The description half
carried only Door 1 (snapshot digest) and Door 3 (a multiset derived from the
snapshot). That asymmetry is a real hole on live `8bcf0ec5`:

1. **Same-count rotation.** Rotate three distinct `@description` lines between
   fields in the generated client only. The line count, the multiset, every
   count door and Door 3 are unchanged; all twelve wired OpenAPI guards stay
   `rc=0` and the contracts layer stays `SMOKE PASS`. A client-visible label
   moves to the wrong field and nothing names it.
2. **Decisive co-revert with an honest re-pin.** Rewrite one description in
   both halves (byte-preserving, all occurrences) and re-pin
   `_SCHEMA_DESCRIPTION_DIGEST` to the new rows. Door 1 goes silent, Door 3
   derives its expectation from the new snapshot and agrees, and the whole
   layer is green — a client-visible prose line changes with one reviewed
   re-pin and no independent fixed point left to object.

Door 3b closes both shapes:

* `_CLIENT_DESCRIPTION_SEQUENCE_DIGEST` — a hand-written sha256 over the 258
  generated `@description` lines **in document order**, read from nowhere. A
  multiset is order-blind; this one is not, so the rotation moves it, and a
  co-revert must re-pin it as a second, separate literal;
* `_EXPECTED_CLIENT_DESCRIPTION_LINES` (258) — exact count door, named even
  when the digest is re-pinned.

The companion carries the #289 lesson from the start: the rotation test asserts
the count **and** the value multiset are unchanged inside the failing case, so
the digest is the only thing that can be doing the work. It also proves the
literal is a source-level constant (AST plant), the count door is load-bearing,
a snapshot-only re-pin stays red, and that re-pinning both digest literals
silences the two digest doors while Door 3 remains the pinned-multiset
authority. A legitimate change must move both artifacts, both digests and the
pinned rows in one commit and say why.

## The title half

Every landed `title` guard pins key **order** (`_title_last` in the snapshot
contract), the normalizer's spelling, or the top-level `info.title` — none
reads the published title **values**. The generator emits a JSDoc block only
for annotated nodes (1232 of 2327 titles render), so the surface is not a
one-to-one map; a sub-multiset check against the snapshot would be
self-referential and pass on a coordinated co-revert of both halves.

Second decisive ablation on live bytes: byte-preserving rewrite of one
published `title` in the snapshot **and** its first-prose JSDoc line in the
generated client, with both provenance blob ids re-pinned — all twelve wired
OpenAPI guards and the whole contracts layer stay `SMOKE PASS`. Two
independent digests close it:

* `_SCHEMA_TITLE_DIGEST` — sha256 over canonical sorted
  `(schema path, title)` rows of all 2327 published titles, read from nowhere;
* `_CLIENT_TITLE_DIGEST` — sha256 over the 1232 generated JSDoc first-prose
  lines, read from nowhere. A co-revert of both halves moves **both**, so
  re-pinning one still trips the other;
* `_EXPECTED_TITLE_ROWS` (2327) / `_EXPECTED_TITLE_SCHEMAS` (362) /
  `_EXPECTED_CLIENT_TITLE_LINES` (1232) — exact count doors.

The companion asserts both digests remain independent literals in the guard
source (second-file plant), so a one-file edit cannot retire the evidence.

## The positional half

`_CLIENT_TITLE_DIGEST` sorts its input, so it pins the *multiset* of generated
title lines and nothing about *which field* carries which label. Two
same-count lines swapping places keeps the multiset, both counts and every
digest above intact.

Third decisive ablation on live bytes: swap two leading JSDoc lines in the
generated client only, leaving `openapi.json` untouched. Before this door the
whole contracts layer stayed `SMOKE PASS` — the label an IDE shows for one
field had moved to its sibling and nothing named it. Doors 7 and 8 close it:

* `_CLIENT_TITLE_ROWS_DIGEST` — sha256 over canonical sorted
  `component|field|title` triples of the 1952 generated title rows, read from
  nowhere. The field name is in the key, so a rotation moves it;
* `_EXPECTED_CLIENT_TITLE_ROWS` (1952) — exact count door;
* positional cross-artifact door — every generated triple is compared with the
  **pinned** snapshot row for that `(component, field)`, so a one-sided edit
  is named by component and field rather than only moving a digest.

These seven components publish a property literally named `title` whose value
is `Title` (`AdminPublicationResponse`, `ExternalArticlePreviewResponse`,
`LiteratureRecord`, `NotificationResponse`, `PublicationCreate`,
`PublicationUpdate`, `app__schemas__content__PublicationResponse`). An earlier
walker skipped the `title` key after consuming it, so those seven rows never
entered `_SCHEMA_TITLE_DIGEST`: a byte-preserving rewrite of one in the
snapshot alone, with both provenance blob ids re-pinned, kept all twelve wired
OpenAPI guards and the whole contracts layer `SMOKE PASS`. The walker now
recurses into the `title` key itself, the census is 2327, and the positional
cross-artifact door needs no exception list — those rows are published values,
not synthetic generator lines. The companion pins the seven by path.

## Wiring

`scripts/test_openapi_schema_descriptions.py` is listed in `smoke.sh`'s
contracts `tests=()` array. The guard has no `--self-test` wire, so
`check_contracts_self_test_teeth.py` (20 wired guards) and
`check_contracts_registry_collection.py` (61 suites / 32 guard calls) are
unchanged — this phase adds **zero wiring**. The companion suite is both a
pytest target and a standalone stdlib runner; it proves the decisive co-revert
on both surfaces, one-sided edits on each half, count-door teeth, same-count
rotations, each digest's independence, the reviewed synthetic line, the seven
`title`-named rows, the description sequence literal's independence, and the
second-file source plant.

## Boundaries

Guard reads committed bytes only (`json` + `re` + stdlib): no Python 3.15, no
API import, no wheel, no database, no workspace install. Multi-line JSDoc
continuation text is now pinned by Door 3c (below); the earlier note that the
guard "does not parse" it is superseded by that phase.

## Door 9 — component-property declaration order

`openapi.json` publishes **2083** direct component-property declarations
across **335** schemas that render a standalone interface block.
`openapi-typescript` prints each component's fields in the snapshot's
insertion order, so the generated interface's field sequence is itself a
published, client-visible shape (IDE completion order, object key
enumeration). Every landed digest on this surface walks *values* —
descriptions, titles, types, requiredness, constraints — or *field sets*;
none reads the positional `(component, index, field)` triple.

**Decisive ablation on live bytes:** byte-preserving swap of two adjacent
`AboutContentResponse` properties in **both** artifacts, with both
`_PINNED_ARTIFACTS` blob ids honestly re-pinned, left all twelve wired
`check_openapi_*.py` guards, every `test_openapi_*` suite and
`bash scripts/smoke.sh --profile contracts` at **SMOKE PASS** while two
client-visible declarations silently swapped positions.

`check_openapi_schema_descriptions.py` now pins two independent literals:

- `_PROPERTY_ORDER_DIGEST` — sha256 over canonical sorted
  `(component, index, field)` rows from the snapshot, read from nowhere.
- `_CLIENT_PROPERTY_ORDER_DIGEST` — a second, separately hand-written sha256
  over the same triples parsed from the generated `components.schemas`
  blocks. Re-pinning only the snapshot side leaves this door red on a
  coordinated co-revert.
- `_EXPECTED_PROPERTY_ORDER_ROWS` / `_EXPECTED_PROPERTY_ORDER_SCHEMAS` /
  `_EXPECTED_CLIENT_PROPERTY_ORDER_ROWS` — exact count doors.
- A named positional cross-artifact door reports a one-sided reorder by
  component and index, so the two digests are not the only net.

The companion suite (`test_openapi_schema_descriptions.py`, collected by the
contracts layer) adds eight cases: row equality across halves, literal
independence, the decisive coordinated co-revert, both one-sided halves,
single-digest re-pin staying red, count doors, and the module-level literal
check. Zero new wiring, zero generated-artifact changes.


## Description continuation prose (Door 3c)

The generated client renders **204** indented `*     ...` continuation lines
across **50** component-schema description nodes, and no landed fixed point
read them. `_SCHEMA_DESCRIPTION_DIGEST` pins the snapshot's full description
string; `_CLIENT_DESCRIPTION_SEQUENCE_DIGEST` and the first-line multiset read
only `@description` first lines. On the landed tree a coordinated reword of
one continuation line in both the snapshot and `openapi.d.ts`, with both
provenance blob ids honestly re-pinned and both description literals
re-derived, kept the guard and every other wired OpenAPI guard green. The
client-visible IDE hover text changed and nothing pinned it.

Door 3c adds a **third** hand-written literal in this guard:

- `_CLIENT_DESCRIPTION_CONTINUATION_DIGEST` — sha256 over canonical sorted
  `(component|description|index|prose)` rows read from the committed generated
  bytes, not from the snapshot under guard. Only JSDoc blocks carrying an
  `@description` first line own continuation rows; a `@default` block that
  renders a multi-line array is excluded (its indented lines are a value, not
  published prose).
- `_EXPECTED_CLIENT_CONTINUATION_ROWS` (204) / `_EXPECTED_CLIENT_CONTINUATION_NODES`
  (50) — exact count doors.

The row is keyed by `(component, description, index)`, so a one-sided rewrite,
a dropped line, a same-count relocation between two description nodes, and the
coordinated co-revert all move the digest. This is the component-schema share
of the same continuation projection as the operation `paths` door in
`check_openapi_operation_annotations.py` (#314), split across two generated
interfaces. Both are folded into already-wired guards with **zero wiring
churn** — no `smoke.sh`, `PINNED_SUITES`, teeth, or registry edit. Eight
companion cases cover the clean tree, the literal's independence, the count
doors, the one-sided rewrite, the drop, the same-count relocation, the
decisive honest co-revert, and the guard docstring naming the three Door 3c
literals.

A legitimate prose change must recompute `_CLIENT_DESCRIPTION_CONTINUATION_DIGEST`
in the same commit as both artifacts and say why. Re-deriving it from the
artifact under guard would make the pin self-referential.
