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

## Door 4 — the snapshot's own HTTP method order

The three doors above are all **sorted sets** of `(METHOD path)` pairs. A
byte-preserving swap of two adjacent methods under one path leaves every pair
intact, so the digest, the count and all three agreement doors stay green.
What changes is the snapshot's own method sequence — the published record of
FastAPI's router-registration order, which OpenAPI tooling displays. On live
`c7f41448c`, swapping `post`/`get` under `/api/v1/blast/jobs` and honestly
re-pinning both `_PINNED_ARTIFACTS` blob ids left all twelve wired
`check_openapi_*.py` guards, every `--self-test` suite and the whole contracts
layer `SMOKE PASS / 1190 passed + 41 subtests + 10 env-bound / 0 failed`.

`openapi-typescript` emits the `paths` interface's methods in a **fixed**
order (`get, put, post, delete, ...`) regardless of the snapshot, so there is
no generated half to compare against. The path-order test in
`test_openapi_snapshot_contract.py` compares path *keys*, not method order.
A two-artifact check is structurally incapable of seeing this drift; a
hand-written literal is the only possible fixed point.

- `_METHOD_SEQUENCE_DIGEST` — sha256 over canonical sorted
  `(path, index, METHOD)` rows, where `index` is the method's position in that
  path's insertion order. Swapping two methods changes both rows, so a
  same-count rotation cannot satisfy it. Read from nowhere.
- `_EXPECTED_METHOD_ROWS` (268) — exact count door.

The guard's `--self-test` grows from 18 to **22** cases: the swap is named, the
same swap with the literal honestly re-pinned stays green (both limbs keep the
door load-bearing), and a bumped count or bumped digest each fail. The teeth
guard's reviewed case floor (`_CASE_FLOOR` in
`scripts/check_contracts_self_test_teeth.py`) moves 18 → 22 in the same
commit — the one wiring edit, and it is what makes the four new cases
load-bearing rather than decorative. The section
above calls the path-order phase "zero wiring churn"; that was true of #342
itself. This phase is the first on this guard that must move the floor,
because it is the first to add self-test cases after #342 raised it to 18.
The companion suite grows to 24 checks, including a module-level AST
assertion that the pin is a real string constant and that the docstring names
both literals. Zero generated-artifact bytes.

A legitimate reorder must recompute `_METHOD_SEQUENCE_DIGEST` with
`_method_sequence_digest()` and move it in the **same commit** as the
snapshot, with a reason.
