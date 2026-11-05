# Published component-schema descriptions

`packages/api-client/openapi.json` publishes **257 `description` strings** on
component-schema nodes across **169 schemas**. `openapi-typescript` renders each
as an `@description` line in the generated `components["schemas"]` JSDoc — the
prose an IDE shows a caller hovering a field. Multi-line descriptions become
`@description <first line>` plus indented continuation lines; the generator
also emits exactly one synthetic line,
`@description discriminator enum property added by openapi-typescript`.

## The gap this guard closes

Every other wired fixed point reads a different surface:

| Fixed point | What it walks |
| --- | --- |
| `_FIELD_CONSTRAINT_DIGEST` | constraint keywords + `default`; `description` is not in `_KEYS` |
| `_REQUIRED_FIELD_DIGEST` | `required` arrays and generated `?:` markers |
| `_ANNOTATION_DIGEST` / `_RESPONSE_SURFACE_DIGEST` / summary digest | operations, not component schemas |
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

## Wiring

`scripts/test_openapi_schema_descriptions.py` is listed in `smoke.sh`'s
contracts `tests=()` array. The guard has no `--self-test` wire, so
`check_contracts_self_test_teeth.py` (20 wired guards) and
`check_contracts_registry_collection.py` (59 suites / 32 guard calls) are
unchanged. The companion suite is both a pytest target and a standalone
stdlib runner; it proves the decisive co-revert, one-sided edits on each
half, count-door teeth, a three-value same-count rotation, the digest's
independence, and the reviewed synthetic client line.

## Boundaries

Guard reads committed bytes only (`json` + `re` + stdlib): no Python 3.15, no
API import, no wheel, no database, no workspace install. It does not parse
multi-line JSDoc continuation text — the generator's rendering of those is a
second, brittle ledger. First lines carry the identity; the digest carries the
full value.
