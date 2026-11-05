# Published operation parameters: the client-visible shape nobody pinned

`packages/api-client/openapi.json` publishes **467** parameters across **268**
operations. They are not documentation: `openapi-typescript` turns each one
into a property of the generated `operations[*].parameters` object. A renamed,
retyped or dropped parameter changes the TypeScript a consumer compiles
against.

The offline OpenAPI guards cover value domains (enum/`const`), `$ref` and
inline bodies, inline path-parameter enums, `operationId` symbol names,
document metadata, auth `security`, and error envelopes. **None reads the
operation-parameter surface.** A parameter is none of those, and the two
artifacts are both exports of `app.main:app`, so comparing them to each other
proves self-consistency, not truth.

## The hole, measured on committed bytes

On live `main` (`86f54069`), rename one query parameter in **both** halves
together — the snapshot's `paths.*.*.parameters[].name` and the generated
client's `query` property — then re-pin the two provenance blob ids in
`test_openapi_snapshot_body_integrity._PINNED_ARTIFACTS` (the "one deliberate
reviewed action" that guard's own docstring admits). Every wired OpenAPI guard
stays `rc=0` and the full contracts layer prints
`SMOKE PASS / 754 passed + 5 subtests + 10 env-bound / 0 failed`. The two
surfaces still agree with each other; nothing says the old parameter was ever
published. A coordinated regenerate of a renamed request field is exactly
this shape.

## The fix

`scripts/check_openapi_operation_parameter_floor.py` reads committed bytes
only (`json` + `re` + stdlib: no Python 3.15, no API import, no wheel, no
database, no workspace install) and pins three doors:

1. `_PARAMETER_DIGEST` — a **hand-written** sha256 over the canonical sorted
   `(METHOD, path, operationId, index, name, in, required, schema)` tuple set,
   read from nowhere. A co-revert of both halves changes the row set, so the
   digest moves even while every consistency check below still agrees.
   `_EXPECTED_PARAMETER_COUNT` and `_EXPECTED_OPERATION_COUNT` are two
   count-level doors.
2. Two-surface agreement: the snapshot's `(in, name, required)` identity set
   per operation == the generated `operations[*].parameters` property set.
   A one-sided edit is named by operation and parameter.
3. Shape invariants: a location outside `query`/`header`/`path`/`cookie` is
   not publishable, and a duplicate `(operation, in, name)` is a broken
   contract.

Re-deriving the digest from the artifacts under guard would make the pin
self-referential — the exact failure this replaces. A legitimate change must
move the digest in the same commit as both artifacts and say why, the same
idiom as `_OPERATION_ID_DIGEST` / `_PUBLISHED_ENUM_BASELINE` /
`_BODY_PAIR_DIGEST`. The companion suite
`scripts/test_openapi_operation_parameter_floor.py` proves the co-revert and
each one-sided drift fail, that the literal is a real AST assignment, that the
wiring cannot be dropped silently, and that the in-file `--self-test`
ablations stay load-bearing under pytest collection.

## Wiring

- `scripts/smoke.sh`: one `tests=()` row (the companion suite) and one
  standalone `check_openapi_operation_parameter_floor.py --self-test` call.
- `scripts/check_contracts_registry_collection.py`: the new standalone call
  is added to `REQUIRED_GUARD_CALLS`. Since #223 that floor is set-equality
  and fails closed on an unpinned addition, so the pin is mandatory.
  `PINNED_SUITES` is a floor, not an allowlist — adding a suite needs no edit
  there.

Both entry points are covered: `--self-test` runs before any suite is
collected, and the collected suite asserts the wiring from a second file.
Dropping either leaves a named red, not a green `SMOKE PASS`.
