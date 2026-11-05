# Per-operation OpenAPI response surface pin

`packages/api-client/openapi.json` and `src/generated/openapi.d.ts` are both
exports of `app.main:app`. Guards that compare them to each other prove
self-consistency, not truth. Every published operation declares a set of
response codes, and `openapi-typescript` types exactly that set as the keys of
`operations[...].responses`. A coordinated regenerate that renames one success
status on both halves moves both artifacts together.

## The gap this closes

On live bytes (808 response entries across 268 operations), a byte-preserving
`204 -> 205` rename in both halves plus a re-pin of
`test_openapi_snapshot_body_integrity._PINNED_ARTIFACTS` (the guard's own
documented "one deliberate reviewed action" alongside a regenerate) left
**every** wired OpenAPI guard `rc=0`. The generated TypeScript type for
`POST /api/v1/auth/logout` silently changed from `responses.204` to
`responses.205` — a client-visible contract break that no fixed point pinned.

Why the existing guards cannot see it:

* `_BODY_PAIR_DIGEST` / `_RESPONSE_BODY_BASELINE` / `_REQUEST_BODY_BASELINE`
  only see responses carrying a `$ref` body. All **12** declared `204`
  responses are content-less, so they appear in **zero** body pairs.
* `_ERROR_RESPONSE_BASELINE` only pins 4xx/5xx codes; success codes are
  outside it.
* `_SNAPSHOT_FLOOR` is a `(paths, schemas)` floor, not a per-operation pin.
* `_PINNED_ARTIFACTS` is a provenance blob id. Re-pinning both ids is the
  documented action that accompanies a legitimate regenerate, so a co-revert
  that re-pins them stays green.
* `check_openapi_inline_body_integrity._INLINE_BODY_BASELINE` keys inline
  bodies per operation, but a content-less `204` has no body at all.

## The pin

`scripts/check_openapi_response_surface.py` reads committed bytes only
(`json` + `re` + stdlib; no Python 3.15, no API import, no wheel, no DB). It
pins:

* `_RESPONSE_SURFACE_DIGEST` — a hand-written sha256 over the canonical sorted
  `(METHOD, path, status, has_content)` tuple set, independent of both
  artifacts. A co-revert of both halves still changes it.
* `_EXPECTED_RESPONSE_ENTRIES` (808) / `_EXPECTED_OPERATION_COUNT` (268) —
  exact count doors a same-count permutation cannot satisfy alone.
* three-way agreement: snapshot per-operation response set, generated `paths`
  -> `operations` reference map, and generated `operations` interface response
  keys. A one-sided edit is named by `(METHOD, path, status)`.
* `content?: never` vs `content: {` in the generated client, so a dropped or
  added body on either half is reported;
* the response `description` in both halves, so a coordinated docstring
  regenerate is named by the digest and by the two-surface agreement.

`--self-test` plants ten drifts (one-sided snapshot/client status renames,
coordinated status rename, coordinated content-less drop, coordinated content
drop, coordinated response-description retype, coordinated operation-summary
retype, one-sided snapshot/client summary retypes, published summary dropped)
and asserts each is caught; the clean tree must pass first.
`scripts/test_openapi_response_surface.py` (17 cases) pins both literals'
independence, the count doors, the wiring, and the summary plant from a second
file.

## Wiring

Five points, all in one commit because the floors fail closed on unpinned
additions:

* `scripts/smoke.sh` — `--self-test` guard call + `tests=()` row;
* `scripts/check_contracts_registry_collection.py` — `REQUIRED_GUARD_CALLS`
  entry + `PINNED_SUITES` entry;
* `scripts/check_contracts_self_test_teeth.py` — `_WIRED_SELF_TESTS` entry +
  `_SIGNATURES` evidence regex.

A legitimate contract change must move the digest in the same commit as the
two artifacts and say why, exactly like `_ERROR_RESPONSE_BASELINE` /
`_BODY_PAIR_DIGEST`. Re-deriving the digest from the artifacts under guard
would make the pin self-referential — the whole failure this file replaces.

## Follow-up: the description column

The first landed version pinned `(METHOD, path, status, has_content)` only.
Measured on the shipped tree, a coordinated regenerate that changes one
response's `description` in **both** halves (snapshot `description` and the
generated `@description` comment), with the two provenance blob ids re-pinned,
left this guard `rc=0`, its 9 companion cases green, and **all eight** wired
OpenAPI guards green. No status, body or content shape moved, so every other
fixed point was blind to it too.

The digest now carries the description (schema `v2`), the two-surface
agreement compares `(has_content, description)` per status, `--self-test`
plants the coordinated retype (6 cases), and the companion suite has two
second-file checks for it (11 cases). A same-commit re-pin of a legitimate
docstring change still stays green.

## Follow-up: the operation ``summary`` column

The description follow-up still left one client-visible field unguarded.
``openapi-typescript`` prints each operation's ``summary`` as the first
``* text`` line of the JSDoc block in the ``paths`` interface (a one-line
``/** text */`` for some routers, a multi-line ``/**`` for others). No landed
guard reads it: ``_RESPONSE_SURFACE_DIGEST`` walks ``responses`` only, and
``_PINNED_ARTIFACTS`` is a provenance blob id that a regenerate re-pins in the
same deliberate act.

Measured on the shipped tree, a coordinated retype of one ``summary`` in
**both** halves (snapshot ``summary`` and generated JSDoc), with the two
provenance blob ids re-pinned, left **every wired OpenAPI guard ``rc=0``**.
``/** Liveness */`` silently became ``/** Liveness probe (edited) */`` and
nothing named it.

The guard now adds a second independent literal:

* ``_OPERATION_SUMMARY_DIGEST`` — a hand-written sha256 over the canonical
  sorted ``(METHOD, path, operationId, summary)`` tuple set, read from
  nowhere. A co-revert of both halves still changes it.
* ``_EXPECTED_SUMMARY_OPERATIONS`` (268) — an exact count door.
* generated JSDoc summary == published summary for every operation, so a
  one-sided edit is named by ``(METHOD, path)``.

Decisive ablation: replacing the digest comparison with self-agreement and
the JSDoc comparison with the snapshot value makes the coordinated retype
``rc=0`` again; restoring both names it. ``test_the_summary_plant_is_load_bearing``
pins those two comparisons in a second file, so a single-file edit cannot
delete the evidence. No ``smoke.sh`` / ``PINNED_SUITES`` /
``REQUIRED_GUARD_CALLS`` change was needed — the extension lives inside an
already-wired guard.

## Request-body surface follow-up

The two earlier pins left one more client-visible column unguarded:
`requestBody.required`. `openapi-typescript` renders it as the optional marker
on the `requestBody` line of each `operations[...]` definition:

| snapshot | generated |
| --- | --- |
| `requestBody.required: true` | `requestBody: {` |
| `requestBody.required: false` | `requestBody?: {` |
| no `requestBody` | `requestBody?: never;` |

86 of 268 operations publish a required body. No landed guard reads that flag:
the body baselines count `$ref` bodies, `_RESPONSE_SURFACE_DIGEST` walks
`responses`, `_OPERATION_SUMMARY_DIGEST` walks `summary`, and
`_PINNED_ARTIFACTS` is a provenance blob id that a regenerate re-pins in the
same deliberate act.

Measured on live bytes, a byte-preserving coordinated co-revert — flip
`POST /api/v1/auth/register`'s `required` to `false` in the snapshot, change
the generated marker to `requestBody?: {`, and honestly re-pin both provenance
blob ids — left **all eight wired OpenAPI guards `rc=0`** and the full
`smoke.sh --profile contracts` layer green. Dropping the body entirely, and a
same-count permutation moving a body between operations, were equally silent.

The guard now adds a fourth independent literal:

* `_REQUEST_BODY_SURFACE_DIGEST` — a hand-written sha256 over the canonical
  sorted `(METHOD, path, operationId, state)` rows, `state` being
  `absent` / `true` / `false`. Read from nowhere, so a co-revert of both halves
  still changes it.
* `_EXPECTED_REQUEST_BODY_BEARING_OPERATIONS` (86) — an exact count door.
* generated marker == published state for every operation, so a one-sided edit
  is named by `(METHOD, path)`.

`--self-test` grew 10 -> 15 cases (one-sided snapshot / one-sided generated /
coordinated co-revert / dropped body / same-count permutation); the companion
grew 17 -> 23 cases and pins the literal, the count door, and both comparisons
from a second file. No `smoke.sh` / `PINNED_SUITES` / `REQUIRED_GUARD_CALLS` /
teeth change was needed — the extension lives inside an already-wired guard,
so it does not contend with the in-flight wiring edits in #272 / #273.

## Declared response headers (fourth independent literal)

`responses.*.headers` is the last operation-level surface with no fixed point.
`openapi-typescript` renders each declared header as a named optional property
in that status's `headers: { ... }` block, with the header `description` as a
JSDoc `@description` line above it. That text is client-visible.

On live bytes (`ebfa4c5f`), a byte-preserving coordinated co-revert — retype
the one `Retry-After` header's description in both `openapi.json` and
`openapi.d.ts`, then re-pin both `_PINNED_ARTIFACTS` blob ids as the body
guard's own docstring instructs — left **all ten OpenAPI guards `rc=0`, 212
pytest cases passed, and `SMOKE PASS`**. The `_RESPONSE_SURFACE_DIGEST` walks
`(status, description, has_content)` only; the body baselines see `$ref`
bodies; `check_openapi_inline_body_integrity` sees inline schemas. None reads
`headers`.

`_RESPONSE_HEADER_SURFACE_DIGEST` is a hand-written sha256 over the canonical
sorted `(method, path, status, name, description, schema)` rows, read from
nowhere. A count door (`_EXPECTED_RESPONSE_HEADERS = 1`) and a cross-artifact
agreement door (snapshot vs generated `headers` blocks) name one-sided edits.
Four new `--self-test` cases cover the one-sided retypes, the decisive
co-revert, and a dropped header; five companion cases pin the digest literal,
the count door, and the comparison from a second file. Zero new wiring: the
guard is already registered, pinned and wired into `smoke_contracts()`.

After the fix, the same co-revert gives `SMOKE FAIL / 1 failed` with
`published response headers drifted: _RESPONSE_HEADER_SURFACE_DIGEST pins
5685ec6b... but the snapshot derives ...`; restoring the bytes returns
`SMOKE PASS`. Re-pin the literal in the same commit as an intentional contract
change, with a reason — do not make the guard agree with itself.

## The generated half's independent literal

Every fixed point above walks the **snapshot**. Doors 2/3 compare the two
halves to each other, so they prove self-consistency, not truth. On live
`9a7c3e52`, a byte-preserving coordinated co-revert — retype one `200`
response description in both `openapi.json` and `openapi.d.ts` — plus one
honest re-pin of `_RESPONSE_SURFACE_DIGEST` to the new rows (the guard's own
documented "one deliberate reviewed action") leaves **nothing** to object:

- Door 1 is silent because its literal was re-pinned to the drifted rows;
- Doors 2/3 agree because both halves moved together;
- the four other digest literals (summary / request body / response header /
  inline body) never read response `description` or `content` presence;
- all **twelve wired `check_openapi_*` guards** report `rc=0` on the drifted
  worktree (measured with the digest and both `_PINNED_ARTIFACTS` blob ids
  honestly re-pinned).

Read the layer number from the ref, not from the clean tree: the drifted
clean-main worktree reports **`SMOKE FAIL / 2 failed, 1101 passed, 41 subtests,
10 environment-bound`**, not `SMOKE PASS / 1103`. `1103` is the *clean*
`9a7c3e52` reading. Both of the two failures are in the existing companion
(`test_coordinated_description_co_revert_is_rejected` and
`test_the_digest_covers_the_description_column`) and are plant artifacts, not
detection: each hardcodes `/** @description Successful Response */` and
rewrites it to `OK`, so against an already-drifted committed tree the first
lands on a neighbouring operation (a spurious disagreement) and the second
sees no change at all (its assertion cannot fire). Neither is an independent
fixed point over the generated half. The guard-level gap is real and the A/B
is decisive; the whole-layer claim was a clean-tree number pasted onto a
drifted-tree sentence.

A client-visible `@description Successful Response` line changed to `OK` with
one reviewed edit and no independent fixed point left to name it. This is the
same genus #320 closed one column over for component-schema `@description`
lines, applied to the operation-level response surface.

`_CLIENT_RESPONSE_SURFACE_DIGEST` closes it: a hand-written sha256 over the
canonical sorted `(symbol, status, has_content, description)` rows of the
**generated** `operations` interface, read from nowhere. A one-sided client
retype moves it; a coordinated co-revert moves it even when the snapshot
digest is honestly re-pinned. A legitimate regenerate must now re-pin **both**
digest literals, move both artifacts, and say why — one reviewed edit is no
longer enough. `_EXPECTED_CLIENT_RESPONSE_ENTRIES` (808) is the exact count
door, named even when the digest is re-pinned.

Zero new wiring: the guard, its companion and its `--self-test` call are
already collected by `smoke_contracts()` and pinned by the registry and teeth
guards. The companion grows 29 -> 36 cases (decisive one-re-pin co-revert,
both-digests-must-move, one-sided client retype, independence from a second
file, count door, weakening control, source plant); the in-file `--self-test`
grows 19 -> 22 cases plus a positive control proving an honest double re-pin
is the reviewed regenerate and stays green.

## Response-status declaration order

`openapi-typescript` prints each operation's response codes in the snapshot's
**insertion order** inside `export interface operations`, so that sequence is a
published shape (IDE completion order on the response union, object key
enumeration). Every landed fixed point above is a `sorted()` row set:
`_RESPONSE_SURFACE_DIGEST`, `_CLIENT_RESPONSE_SURFACE_DIGEST`, the summary /
request-body / header / inline-body digests, all count doors and the three-way
cross-artifact agreement. A coherent swap of two adjacent status blocks —
each keeping its own `@description` and content — leaves every one of them
unchanged. Re-pinning both `_PINNED_ARTIFACTS` blob ids beside that regenerate
keeps the whole contracts layer green while the client-visible declaration
sequence silently changes.

Decisive two-tree A/B on live `e3b4b33f` bytes: the same drifted artifacts
(byte-identical between runs, both provenance blobs honestly re-pinned) give
`rc=0` on the pre-fix guard and `rc=1` on the fixed one, naming both literals.

Two independent hand-written literals close it:

- `_RESPONSE_STATUS_ORDER_DIGEST` — sha256 over canonical
  `(METHOD, path, operationId, index, status)` rows of the snapshot, in
  declaration order, read from nowhere;
- `_CLIENT_RESPONSE_STATUS_ORDER_DIGEST` — the same positional rows parsed
  from the generated `operations` blocks, a second independent literal;
- `_EXPECTED_RESPONSE_STATUS_ORDER_ROWS` (808) — exact count door on both halves.

A one-sided reorder re-pins one literal and stays red on the other. A
coordinated co-revert of both halves moves both. Deriving either expected
value from the artifact under guard would make the pin self-referential, which
is the shape this file refuses. Both must be re-pinned in the same commit as
both artifacts, with a reason.

Zero new wiring: the guard, its companion and its standalone `--self-test`
call are already registered. The in-file `--self-test` grows 22 -> 28 cases
(decisive both-halves swap, two one-sided swaps, two one-sided re-pins, honest
double re-pin positive control); the companion grows 36 -> 42 cases, pinning
the literals, the count door, the ablation plants and the door's source shape
from a second file so a single-file edit cannot hide it.
