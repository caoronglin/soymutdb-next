# Published `operationId`: the client-visible symbol nobody pinned

`packages/api-client/openapi.json` publishes **268** `operationId` values.
They are not documentation: `openapi-typescript` turns each one into a key of
the generated `operations` interface and a `operations["<id>"]` reference
inside `paths`. Consumers import those symbol names. A handler rename that is
regenerated consistently changes the public TypeScript surface.

Every offline OpenAPI guard read *which schema* a response names, which
components exist, which paths exist, which tags are declared, or which error
bodies are declared. **None read `operationId`**, and the two artifacts are
both exports of `app.main:app`, so comparing them to each other proves
self-consistency, not truth.

## The hole, measured on committed bytes

On live `main` (`04752bc5`), retype one `operationId` in **both** halves
together — the snapshot's `paths.*.*.operationId`, the generated
`operations["..."]` reference, and the generated interface key — then re-pin
the two provenance blob ids in
`test_openapi_snapshot_body_integrity._PINNED_ARTIFACTS` (the "one deliberate
reviewed action" that guard's own docstring admits). Every wired guard stays
`rc=0`: the five OpenAPI guards, the contracts-registry guard, all 147
OpenAPI/MCP pytest cases, and the full contracts layer `SMOKE PASS / 0 failed`.
The three surfaces still agree with each other; nothing says the old symbol
was ever published. A coordinated regenerate of a renamed handler is exactly
this shape.

## The fix

`scripts/check_openapi_operation_id_floor.py` reads committed bytes only
(`json` + `re` + stdlib: no Python 3.15, no API import, no wheel, no database,
no workspace install) and pins three doors:

1. `_OPERATION_ID_DIGEST` — a **hand-written** sha256 over the canonical
   sorted `(METHOD path, operationId)` pair set, read from nowhere. A
   co-revert of both halves changes the pair set, so the digest moves even
   while every consistency check below still agrees. `_EXPECTED_OPERATION_COUNT`
   is a second count-level door.
2. Three-way agreement: snapshot map == generated `paths` → `operations`
   reference map == generated `operations` interface key set. A one-sided
   edit (snapshot only, or one generated surface only) is named by key.
3. Shape invariants: uniqueness (two operations sharing a symbol collapse
   the generated type table) and valid TypeScript property names.

Re-deriving the digest from the artifacts under guard would make the pin
self-referential — the exact failure this replaces. A legitimate rename must
move the digest in the same commit as both artifacts and say why, the same
idiom as `_ERROR_RESPONSE_BASELINE` / `_SNAPSHOT_FLOOR` /
`_BODY_PAIR_DIGEST`. The companion suite
`scripts/test_openapi_operation_id_floor.py` proves the co-revert and each
one-sided drift fail, that the literal is a real AST assignment, that the
wiring cannot be dropped silently, and that the in-file `--self-test`
ablations stay load-bearing under pytest collection.

## Wiring

- `scripts/smoke.sh`: one `tests=()` row (the companion suite) and one
  standalone `check_openapi_operation_id_floor.py --self-test` call.
- `scripts/check_contracts_registry_collection.py`: the new standalone call
  is added to `REQUIRED_GUARD_CALLS`. Since #223 that floor is set-equality
  and fails closed on an unpinned addition, so the pin is mandatory.

Both entry points are covered: `--self-test` runs before any suite is
collected, and the collected suite asserts the wiring from a second file.
Dropping either leaves a named red, not a green `SMOKE PASS`.
