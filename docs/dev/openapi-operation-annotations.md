# OpenAPI operation annotation floor

`scripts/check_openapi_operation_annotations.py` pins per-operation
`description` prose and `deprecated` flags to a hand-written literal, plus the
generated doc-comment continuation prose. Operation `summary` is owned by
`check_openapi_response_surface.py` (#269); this guard deliberately does not
duplicate that fixed point.

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
* `_CONTINUATION_DIGEST` — a second hand-written sha256 over canonical sorted
  `(METHOD, path, line index, prose)` rows of the 393 indented continuation
  lines in the generated `paths` doc blocks (104 operations). The snapshot's
  full description is already frozen by `_ANNOTATION_DIGEST`, but the
  three-way agreement compares only `_description_first_line()` — so the
  client-visible rendering of the rest of the prose had no fixed point.
  This is the same genus #297 closed for the generated `@default` tags: pin
  the generated projection the merged guard did not carry. Two exact count
  doors (393 lines, 104 operations) sit beside it; a same-count relocation
  between two operations moves only the digest.

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

`--self-test` plants ten drifts (one-sided summary/description/deprecated,
coordinated description co-revert, dropped summary, dropped wire, one-sided
generated continuation rewrite, dropped continuation line, same-count
continuation relocation) into copies of the bytes. The coordinated case is
the one #269 cannot see; the three continuation plants are the ones no other
wired guard sees.
`scripts/test_openapi_operation_annotations.py` (20 cases) pins both literals'
independence, the count doors, the wiring from all three places, and each
negative direction from a second file.

stdlib-only: no Python 3.15 venv, API import, wheel, database or workspace
install.
