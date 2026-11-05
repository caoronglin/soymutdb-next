# Published component-schema descriptions and titles

`packages/api-client/openapi.json` publishes **257 `description` strings** on
component-schema nodes across **169 schemas**, and **2320 `title` strings**
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

The digest and the generated-client door are independent: the client door is
bound to the committed literal, so the decisive co-revert trips **both**. A
legitimate prose change must move the digest in the same commit as both
artifacts and say why.

## The title half

Every landed `title` guard pins key **order** (`_title_last` in the snapshot
contract), the normalizer's spelling, or the top-level `info.title` — none
reads the published title **values**. The generator emits a JSDoc block only
for annotated nodes (1232 of 2320 titles render), so the surface is not a
one-to-one map; a sub-multiset check against the snapshot would be
self-referential and pass on a coordinated co-revert of both halves.

Second decisive ablation on live bytes: byte-preserving rewrite of one
published `title` in the snapshot **and** its first-prose JSDoc line in the
generated client, with both provenance blob ids re-pinned — all twelve wired
OpenAPI guards and the whole contracts layer stay `SMOKE PASS`. Two
independent digests close it:

* `_SCHEMA_TITLE_DIGEST` — sha256 over canonical sorted
  `(schema path, title)` rows of all 2320 published titles, read from nowhere;
* `_CLIENT_TITLE_DIGEST` — sha256 over the 1232 generated JSDoc first-prose
  lines, read from nowhere. A co-revert of both halves moves **both**, so
  re-pinning one still trips the other;
* `_EXPECTED_TITLE_ROWS` (2320) / `_EXPECTED_TITLE_SCHEMAS` (362) /
  `_EXPECTED_CLIENT_TITLE_LINES` (1232) — exact count doors.

The companion asserts both digests remain independent literals in the guard
source (second-file plant), so a one-file edit cannot retire the evidence.

## Wiring

`scripts/test_openapi_schema_descriptions.py` is listed in `smoke.sh`'s
contracts `tests=()` array. The guard has no `--self-test` wire, so
`check_contracts_self_test_teeth.py` (20 wired guards) and
`check_contracts_registry_collection.py` (59 suites / 32 guard calls) are
unchanged. The companion suite is both a pytest target and a standalone
stdlib runner; it proves the decisive co-revert on both surfaces, one-sided
edits on each half, count-door teeth, same-count rotations, each digest's
independence, the reviewed synthetic lines, and the second-file source plant.

## Boundaries

Guard reads committed bytes only (`json` + `re` + stdlib): no Python 3.15, no
API import, no wheel, no database, no workspace install. It does not parse
multi-line JSDoc continuation text — the generator's rendering of those is a
second, brittle ledger. First lines carry the identity; the digest carries the
full value.
