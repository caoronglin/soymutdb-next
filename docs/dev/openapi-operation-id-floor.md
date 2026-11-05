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

## Phase 2 — the path declaration order (a permutation, not a retype)

Every fixed point above walks a **sorted** row set, and
``test_openapi_snapshot_contract.py``'s path-order reader compares the two
artifacts to each other. ``openapi-typescript`` prints ``paths`` in the
snapshot's own document order, so the generated interface's key sequence is
client-visible (IDE completion order, object key enumeration). Swapping two
whole path blocks in **both** artifacts -- byte-preserving, same pair set,
same 268 operations, same 238 paths, same normalized export bytes, both
``_PINNED_ARTIFACTS`` blob ids honestly re-pinned -- leaves all twelve wired
``check_openapi_*`` guards ``rc=0`` and the whole contracts layer
``SMOKE PASS``. This is the same-count rotation shape that a sorted digest
cannot see: no value changed, only the sequence.

The guard adds two more independent literals, read from nowhere:

- ``_PATH_ORDER_DIGEST`` -- sha256 over the snapshot's ``index|path`` rows in
  document order;
- ``_CLIENT_PATH_ORDER_DIGEST`` -- a second sha256 over the generated
  ``export interface paths`` key sequence, so re-pinning only the snapshot
  side cannot silence the client door;
- ``_EXPECTED_PATH_COUNT`` (238) -- exact count door;
- a named per-index agreement: a one-sided reorder reports the first index
  where the two halves disagree.

``--self-test`` grows 11 → 18 cases: the decisive coordinated swap, the same
swap with **both** literals re-pinned (the one green shape), re-pinning only
one side (still red), both one-sided reorders, and the count/digest doors.
``scripts/test_openapi_operation_id_floor.py`` grows 13 → 20 cases, asserting
both literals are module-level strings, that the swap is named by both doors
while the sorted digest and three-way agreement stay silent, and that the
self-test plants are load-bearing from a second file. The teeth guard's
``_CASE_FLOOR`` moves 11 → 18 in the same commit. Zero wiring churn: the guard
and its companion were already collected, so ``smoke.sh`` /
``PINNED_SUITES`` / ``REQUIRED_GUARD_CALLS`` are byte-identical.

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

Phase 2 adds no new caller: it extends the already-wired guard and its
already-collected companion. The teeth guard's reviewed case floor is the
only third file that moves, because the guard's `--self-test` gained seven
new ablation cases.
