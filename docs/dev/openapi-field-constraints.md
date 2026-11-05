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
- `--self-test` plants eight drifts (coordinated `maxItems` retype, one-sided
  drop, one-sided add, keyword rename, a mutation on a keyword-named property,
  coordinated `default` retype, one-sided `default` drop, a mutation on the
  `default`-named property) and asserts each is caught; the clean tree must
  pass first.

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
companion in `tests=()`, and pinned in all three floors (unchanged by the
`default` extension — no new guard, no new wiring row):
`REQUIRED_GUARD_CALLS` + `PINNED_SUITES` (registry), `_WIRED_SELF_TESTS` +
`_SIGNATURES` + `_EVIDENCE_PER_CASE` (teeth). The teeth guard runs the
`--self-test` as a real process and requires its pinned evidence; dropping any
one of the five wiring lines fails closed.
