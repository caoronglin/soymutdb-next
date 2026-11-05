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

## Phase 2 — published parameter `description` prose (Doors 4 and 5)

`openapi.json` publishes **20** `description` strings on operation parameters.
`openapi-typescript` renders each as an `@description` line inside the
generated `operations[*].parameters` doc block — prose an IDE shows a caller.
The parameter digest above walks `(method, path, name, in, required, schema)`
and deliberately does **not** read `description`; the operation-annotation
guard walks operation-level prose, not parameter prose; the behavior-contract
suite checks `x-idempotent` / `x-pagination` / envelope facts. No landed fixed
point reads this surface.

**Decisive ablation on live bytes**: retype
`GET /api/v1/genes/region-structure`'s `include_parts` description in the
snapshot **and** the matching `@description` line in the generated client
(both halves agree), honestly re-pin both `_PINNED_ARTIFACTS` blob ids:

| check | reading |
| --- | --- |
| all 12 wired `check_openapi_*` guards | `rc=0` |
| `bash scripts/smoke.sh --profile contracts` | `SMOKE PASS` |

One client-visible prose line changes and nothing names it.

### The two doors

- `_PARAMETER_DESCRIPTION_DIGEST` — hand-written sha256 over canonical sorted
  `(METHOD, path, operationId, index, name, in, description)` rows, read from
  nowhere. A coordinated co-revert of both halves still moves it.
  `_EXPECTED_PARAMETER_DESCRIPTIONS` is the exact count door; a same-count
  rotation of two descriptions leaves it green and is caught by the digest.
- `_CLIENT_PARAMETER_DESCRIPTION_DIGEST` — a **separate** hand-written literal
  over the generated half's canonical `(operationId, field, first line)` rows,
  plus `_EXPECTED_CLIENT_PARAMETER_DESCRIPTIONS`. Two independent fixed points
  are the point: re-pinning only the snapshot digest does not silence the
  client door, and a coordinated co-revert cannot pass by making both halves
  agree. One-sided edits are named by operation and field.

`_client_parameter_descriptions()` reads only each operation's
`parameters: { ... }` section up to `responses: {`, so the many
`@description` lines on response/body doc blocks cannot be mistaken for a
parameter description.

### Self-consistency ablation

Re-deriving both pins from the artifacts under guard (`pinned = actual`) makes
exactly two self-test cases `NOT caught`: the coordinated co-revert and the
single-digest re-pin. `--self-test` rc=1, zero collateral; restore returns
`18 cases, 0 failure(s)`.

### Legitimate change

Move both digests, both count doors, and both artifacts in the **same commit**,
and say why. Re-deriving a digest from the artifact under guard makes the pin
self-referential. Zero new wiring: `smoke.sh`,
`check_contracts_registry_collection.py`, `check_contracts_self_test_teeth.py`
and `_WIRED_SELF_TESTS` are untouched.
