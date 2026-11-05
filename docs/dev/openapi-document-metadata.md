# OpenAPI document-level metadata: freezing the published contract

## The gap

`packages/api-client/scripts/check-contract.sh` proves **self-consistency**:
a fresh export from `app.main:app` equals the committed `openapi.json`, and the
generated `openapi.d.ts` equals a regeneration from that snapshot. It does not
prove the published document still says the *reviewed* contract.

The top-level `info`/`tags` block is a special blind spot:

- `openapi-typescript` drops `info` and top-level `tags` entirely, so
  `openapi.d.ts` carries neither `info.title`, `info.version`,
  `info.description` nor the tag catalog. The snapshot is the **only** committed
  artifact carrying them.
- `normalize()` in `export_contract.py` walks `components.schemas` only, so
  `test_snapshot_is_a_fixed_point_of_the_export_normalizer` cannot see a
  metadata edit: a mutated `info`/`tags` is still a fixed point.
- Every OpenAPI guard in the series pins per-operation or per-schema facts —
  422 (`#154`), behavior constants (`#166`), response bodies (`#168`), auth
  surface (`#169`), envelope shape (`#171`). None reads `info`/`tags`.
- The source of truth is a set of **mutable** literals in `main.py`
  (`OPENAPI_DESCRIPTION`, `OPENAPI_TAGS`, the `version=` kwarg) and
  `core/config.py` (`app_name`). Change a constant, re-export the snapshot:
  both halves agree, `check-contract.sh` stays green, the published contract
  drifts. This is a *coordinated co-revert*, the same genus as `#154`/`#155`.

## Why "published == source" is not enough

A guard that asserts the snapshot equals the source constants is **vacuous**
against that co-revert: both sides move together by construction. This is the
argument `#162` makes for the kernel error codes — *a derived expectation
cannot freeze a value*. Pinning pydantic's `required` inference offline would
be the same mistake one level down (`#171`'s shape gap): a copy of the
generator's rules rots the moment the generator changes.

The `info`/`tags` facts are plain literals, so no generator inference needs
copying — but they still need an authority that does **not** move with the
source.

## The fix: a hand-written golden lock

`packages/api-client/openapi-document-metadata.golden.json` is a reviewed,
hand-authored lock on the published contract: `title`, `version`,
`description`, and the ordered `tags` catalog. It is **not** generated from
`main.py` or `openapi.json`.

`scripts/check_openapi_document_metadata.py` (stdlib only; no Python 3.15
venv, no FastAPI import, no service, no pydantic) compares three things against
committed bytes:

1. **Published == golden.** Catches the coordinated co-revert: source and
   snapshot agree with each other but not with the reviewed lock.
2. **Source == golden.** Catches a source-only drift that would mislead the
   next regeneration into publishing a contract nobody reviewed.
3. **`create_app()` still feeds the constants into `FastAPI(...)`.** Catches a
   rewiring (hardcoded title, dropped description/tags) that would make the
   running app export metadata diverging from the snapshot.

It also rejects a hollow / duplicate-key golden, checks the tag catalog is
non-empty and each tag has a name and description, and stays honest about its
single-artifact premise: if a future generator starts emitting `info`/`tags`
into `openapi.d.ts`, the guard fails loudly so a human re-derives the wiring
instead of trusting a stale assumption.

### What a legitimate change looks like

Editing `title`/`version`/`description`/`tags` is a deliberate contract change:
edit the golden **and** the source constant in the same reviewed commit, then
regenerate the snapshot. A three-way co-revert of source + snapshot + golden is
therefore green *by design* — the golden edit is the reviewable act. A two-way
co-revert of source + snapshot is red. This is the boundary between "internal
consistency" and "published contract".

### Wiring

`scripts/test_openapi_document_metadata_guard.py` is the thin pytest face,
registered in `smoke.sh`'s `tests[]` at a quiet anchor (after
`test_site_artifact_isolation.py`) so no in-flight branch uses that line as
hunk context. The guard asserts its own registration; a dropped entry is a loud
failure. It runs in the dependency-free contracts layer (`smoke.sh --profile
contracts`), which is what CI's "Contract suites" stage invokes.

## Verification / not claimed

Stdlib guard + 17 in-file ablations (including the coordinated co-revert) run
on CPython 3.11 without the API venv. The real 3.15 export lane, full
API/worker pytest, turbo, Playwright E2E and OCI are CI's authority; they are
not signed here. A new golden file is committed, so `generate:api-client` must
not overwrite it (it is not an output of the generator).
