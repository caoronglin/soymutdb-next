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

`--self-test` plants five drifts (one-sided snapshot rename, one-sided
generated rename, coordinated rename, coordinated content-less drop,
coordinated content drop) and asserts each is caught; the clean tree must pass
first. `scripts/test_openapi_response_surface.py` (9 cases) pins the literal's
independence, the count doors, and the wiring from a second file.

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
