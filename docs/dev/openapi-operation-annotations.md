# OpenAPI operation annotation floor

`scripts/check_openapi_operation_annotations.py` pins per-operation
`description` prose and `deprecated` flags to a hand-written literal.
Operation `summary` is owned by `check_openapi_response_surface.py` (#269);
this guard deliberately does not duplicate that fixed point.

## Why

`openapi.json` and `src/generated/openapi.d.ts` are both exports of
`app.main:app`. Comparing them proves self-consistency, not truth.
`openapi-typescript` renders each operation's `summary` as the first line of
the doc comment above the method in the generated `paths` interface, the
`description` under `@description`, and `deprecated` as `@deprecated`. Those
strings are client-visible: generated SDK consumers read them as
documentation.

On live main **after #269 landed**, a coordinated regenerate that rewrote one
operation `description` in **both** halves (byte-preserving edits, both
agreeing), with both provenance blob ids re-pinned exactly as
`test_openapi_snapshot_body_integrity.py` documents for one reviewed
regenerate action, kept every wired OpenAPI guard `rc=0` and the whole
contracts layer `SMOKE PASS / 850 + 5 + 10 / 0 failed`. #269's
`_OPERATION_SUMMARY_DIGEST` walks `(method, path, operationId, summary)` only;
the operationId / parameter / response-surface digests pin structural facts;
the document-metadata golden freezes document-level `info` and the tag
catalog; the body digests see bodies only. No fixed point read per-operation
description prose or deprecation flags.

## What is pinned

* `_ANNOTATION_DIGEST` — sha256 over canonical sorted
  `(METHOD, path, operationId, description, deprecated)` tuples.
  Hand-written; regenerating it from the artifacts would make it
  self-referential. A summary-only change does NOT move this digest -- that
  is #269's job, and the companion suite pins the non-duplication.
* Exact count doors: 268 operations, 209 descriptions, 2 deprecated.
* Three-way agreement: snapshot annotations vs generated `paths` doc
  comments vs generated `operations` symbols. One-sided drifts are named by
  method and path. Both inline `/** ... */` and multi-line doc blocks are
  parsed. The summary line is still compared (as a cross-artifact agreement
  check), but it is not part of the independent literal.
* Wiring: an active standalone `--self-test` call inside `smoke_contracts()`.
  A commented-out line does not satisfy it.

A legitimate contract change must move the digest and the two artifacts in
the same commit and say why.

## Wiring

One commit, so both equality floors fail closed on an unpinned addition:

* `smoke.sh`: standalone `--self-test` call and `tests=()` companion row.
* `check_contracts_registry_collection.py`: `REQUIRED_GUARD_CALLS` and
  `PINNED_SUITES`.
* `check_contracts_self_test_teeth.py`: `_WIRED_SELF_TESTS`, `_SIGNATURES`,
  and `_EVIDENCE_PER_CASE` (this guard prints per-case evidence, so a summary
  line cannot fake it).

`--self-test` plants seven drifts (one-sided summary/description/deprecated,
coordinated description co-revert, dropped summary, dropped wire) into copies
of the bytes. The coordinated case is the one #269 cannot see.
`scripts/test_openapi_operation_annotations.py` (13 cases) pins the literal's
independence, the count doors, the wiring from all three places, and each
negative direction from a second file.

stdlib-only: no Python 3.15 venv, API import, wheel, database or workspace
install.
