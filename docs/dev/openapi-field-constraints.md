# Published field-level constraint pin

`packages/api-client/openapi.json` publishes 815 JSON Schema constraint values
across 207 component schemas: `minimum`, `maximum`, `exclusiveMinimum`,
`exclusiveMaximum`, `minLength`, `maxLength`, `minItems`, `maxItems`, `pattern`,
`format`, `multipleOf`. They are part of the public contract — runtime
validation enforces them, and a client generated from the document can read
them.

## Why no other guard sees them

The generated `packages/api-client/src/generated/openapi.d.ts` emits JSDoc
tags for `@description`, `@default`, `@enum`, `@constant` — but **none** of
these numeric/string constraints. There is no second half for a two-artifact
comparison to agree with. Every wired fixed point reads a different surface:

- `check_openapi_published_enums.py` walks only `enum` / `const`;
- the body baselines (`_RESPONSE_BODY_BASELINE`, `_BODY_PAIR_DIGEST`,
  `_INLINE_BODY_BASELINE`) read bodies, not property schemas;
- the operationId, parameter and response-surface digests do not descend into
  `components.schemas` properties;
- `_PINNED_ARTIFACTS` is provenance blob ids, and re-pinning them is the
  documented "one reviewed action" beside a regenerate.

Decisive ablation on the shipped tip: a byte-preserving `maxItems: 100 → 999`
edit in the snapshot, with both provenance blob ids honestly re-pinned, leaves
all eight wired OpenAPI guards, their eight `--self-test` suites and all ten
companion suites `rc=0`. Nothing reports that a published constraint changed.

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
  `format` / `minimum` / `pattern` (e.g.
  `ExportManifestResponse.properties.format`) is **not** a `format`
  constraint on the map. A naive flat-key walk overcounts by 11; both readers
  in this guard agree on 815.
- `--self-test` plants five drifts (coordinated retype, one-sided drop,
  one-sided add, keyword rename, a mutation on a keyword-named property) into
  in-memory copies and asserts each is caught; the clean tree must pass first.

`scripts/test_openapi_field_constraints.py` is the companion suite: it proves
the digest is a source literal, that a same-count permutation still moves it,
that a same-commit re-pin stays green, and that the wiring is pinned in all
three floors.

## Changing the contract

A legitimate change moves the snapshot **and** re-pins the digest in the same
commit, with a reason — exactly like `_ERROR_RESPONSE_BASELINE` /
`_BODY_PAIR_DIGEST`. The guard's plain run compares the committed artifact to
the literal, so an edited number with untouched bytes is rejected on a bare
clone, in a squash and on a shallow checkout.

## Wiring

The guard is wired into `smoke_contracts()` via `--self-test`, with its
companion in `tests=()`, and pinned in all three floors:
`REQUIRED_GUARD_CALLS` + `PINNED_SUITES` (registry), `_WIRED_SELF_TESTS` +
`_SIGNATURES` + `_EVIDENCE_PER_CASE` (teeth). The teeth guard runs the
`--self-test` as a real process and requires its pinned evidence; dropping any
one of the five wiring lines fails closed.
