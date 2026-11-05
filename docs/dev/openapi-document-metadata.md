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
   running app export metadata diverging from the snapshot. All three keyword
   values are read from the parsed `FastAPI(...)` call, not from a whole-file
   substring: a decoy comment containing `description=OPENAPI_DESCRIPTION`
   cannot keep this check green after the real kwargs are unwired. Reading the
   keyword *expression* proves its spelling, not what the name resolves to, so
   the guard also resolves the referenced root names with the stdlib symbol
   table: a rebinding of `OPENAPI_DESCRIPTION` / `OPENAPI_TAGS` / `settings`
   inside `create_app` (before `FastAPI(...)`) is rejected, because the running
   app would then export different bytes while the call-site text, the
   module-level literal, the snapshot and the golden all stay put. A bare
   `global` declaration is **not** rejected: it binds to the module scope the
   constant already lives in, so the value `FastAPI(...)` reads is unchanged;
   a `global` plus a rebind is rejected. A same-name local in a nested helper
   is a different scope and is not flagged. Scope resolution sees bindings, not
   contents, so the guard separately rejects in-place mutation of a watched
   constant (`OPENAPI_TAGS.clear()`, `.append(...)`, item/attribute assignment):
   the name still resolves to the module-level object, but the object itself
   has been hollowed. Any method call on a watched root must be in a reviewed
   read-only allowlist, so an unknown shape fails closed. The AST passes answer
   "does this call read the locked values"; they do not answer "could this
   module run at all". `__debug__ = 1` is the live example: `ast.parse` and
   `symtable` both accept it, every pass above stays silent, and `compile()`
   alone rejects it — GREEN on bytes that can never be imported. So the guard
   also asks `compile()`, the authority that matches the runtime; a rejection
   is a clean FAIL (`create_app() would not run`). Shapes `symtable` rejects
   but `ast.parse` accepts (e.g. duplicate parameters) yield the other clean
   FAIL, not an escaping traceback.

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

The pytest face pins the ablation table by **exact count and case label**, not
a `>=` floor: an older-world floor (`ablations >= 22`) stays green when the
one case that catches the AST-vs-substring wiring regression is deleted
together with the guard it protects, because the count merely returns to the
old value. `self_test()` returns the registered case labels alongside the
counts, `test_every_ablation_is_caught` asserts the exact count (`== 27` at
this cut) and that the five wiring rows are present and driven by their
mutators — `description/tags unwired with decoy comment` (parsed call vs
whole-file substring), `description/tags shadowed by local rebinding`
(name resolution, not spelling), `description/tags mutated in place`
(in-place mutation, not binding), `create_app would not run (compiler
rejects it)` (`compile()` as the runtime authority, not just a parser), and
`create_app does not compile under symtable` (clean FAIL, no traceback). `test_ablation_count_pin_is_not_vacuous`
materializes the exact revert-and-delete regression to prove the pin itself
would go red. `test_local_rebinding_of_wiring_names_is_rejected` rebuilds a
spelling-only guard on in-memory bytes to prove the name-resolution check is
load-bearing; `test_in_place_mutation_of_wiring_names_is_rejected` rebuilds a
resolution-only guard to prove the mutation check is load-bearing.
A count written into an assert grows its own tree; the pin must
name what it guards, and the table must have a row for each shape the guard
claims to reject.

## Verification / not claimed

Stdlib guard + 27 self-test ablations (including the coordinated co-revert,
the decoy-comment wiring case, the local-rebinding name-resolution case, the
in-place-mutation case, the compile()-reject clean-FAIL case and the
symtable-reject clean-FAIL case) run on
CPython 3.11 without the API venv. The real 3.15 export lane, full API/worker
pytest, turbo, Playwright E2E and OCI are CI's authority; they are not signed
here. A new golden file is committed,
so `generate:api-client` must not overwrite it (it is not an output of the
generator).

## The tag catalog is both an invariant and a derived quantity

`info.title` / `info.version` / `info.description` are **invariants**: their
value *is* the contract, so the golden lock is the right authority. The tag
catalog's **completeness** is a different kind of fact: it is a derived
quantity that moves whenever a router is added, removed, or retagged.

A lock can freeze the six names it was written with. It cannot notice a
seventh router showed up — the stale lock stays green, and a
`declared-but-unused` entry is invisible too. This is the same argument as
`#162`: freezing a derived expectation by copying its current value produces a
table that rots. So the guard asserts an **invariant**, not a value:

    every tag a router emits (``tags=[...]`` in ``APIRouter(...)`` / route
    decorators) == every tag the published operations carry
    (``paths.*.*.tags[]``) == the declared catalog (top-level ``tags[]``)

Both sides are read from committed bytes. Router source is upstream of the
export and the operation tags are downstream of it, so this is an authority
that does not move with the catalog. Three consequences:

- **The bless channel is closed for tags.** Before this invariant, editing
  `main.py` + `openapi.json` + the golden to agree on an *invented* tag made
  the guard green (the three-way lock is green by design). Now it fails with
  `phantom entries: made-up`, because no router emits that name. A legitimate
  `description` prose edit still uses the documented three-way path.
- **Blessing the golden cannot move this invariant.** It reads no golden
  content. A stale or edited lock is caught by checks 1–3; an incomplete
  catalog is caught here. The two failure modes are independent.
- **A frozen name table is not used.** Adding a real router plus a catalog
  entry in source + golden + snapshot stays green (a positive control in the
  self-test), which is exactly what a hand-maintained constant table would
  break.

### Measurement that motivated this cut

On the tree before this change the published catalog declared **6** tags while
operations carried **50** distinct names (`undeclared = 44`). The 50 operation
tags were *exactly* the `tags=[...]` literals in router source, confirming the
catalog — not the routers — was the stale side. Note that the `admin-*` family
is **not** an existing taxonomy rule: nothing in committed bytes names it, and
none of the `admin-*` operations also carried the declared `admin` rollup. So
the invariant is plain `emitted == used == declared`, with no prefix exception
invented for the sake of making today's tree pass.

The `49` / `undeclared = 43` reading in the `#178` handoff is **not** a
pre-cut version of the `50` above; it belongs to a different tree. Byte-counted
across the four relevant commits:

| tree | declared | used | undeclared | `exports` in snapshot `paths` |
| --- | --- | --- | --- | --- |
| `79de2bb6` (`#178` head) | 6 | **49** | 43 | no |
| `05a1d4bb` (live `main`, parent of this cut) | 6 | **50** | 44 | yes |
| `675543b0` (first cut) | 49 | 50 | 1 | yes |
| `cec19db4` (this head) | 50 | 50 | 0 | yes |

`export_query.py` landed on `main` between `#178` and this change, so `used`
was already `50` on the tree this PR was cut from. The `49` belongs to the
`#178` snapshot and must be read with `79de2bb6`; quoting both numbers without
their tree makes them look contradictory. Readings here are always
`(tree, declared, used)`, not a bare scalar.

A live example arrived while this cut was being prepared: `export_query.py`
landed on `main` with `tags=["exports"]` between `#178` and this change. The
guard, rebased onto that `main`, went **red** with `tag catalog is incomplete:
exports` — precisely the "next router makes the lock stale" case. Adding the
one catalog entry (source + golden + snapshot) turned it green without editing
any constant table of tag names.

### Legitimate change: adding or retiring a router

1. Add/remove/retag the router in `apps/api/app/**` (the real source).
2. Update `OPENAPI_TAGS` in `apps/api/app/main.py` **and**
   `openapi-document-metadata.golden.json` **and** regenerate
   `packages/api-client/openapi.json` (the snapshot's top-level `tags` come
   from `create_app(..., openapi_tags=OPENAPI_TAGS)`).
3. Keep the three in agreement — the golden edit is the reviewable act, as
   above. The guard then proves the catalog is complete against router source.

A router whose tag is not declared fails with `tag catalog is incomplete`
naming the tag. A declared tag no router emits fails with `phantom entries`
naming it. Neither requires anyone to edit a constant table of tag names.

### Guard scope / not claimed

The router-side reader restricts itself to `APIRouter(...)` and route-decorator
calls with a literal `tags=[...]`, so unrelated `tags=` kwargs (e.g.
`bleach.clean(..., tags=[...])`) cannot be mistaken for a declaration. A
non-literal `tags=` expression is a pass-through and is deliberately skipped.
It is a stdlib `ast` read of committed bytes, not an import of the app: no
Python 3.15 venv, no FastAPI, no service. That also means it cannot prove a
router is *registered* on the app — it proves the published tag set and the
declared catalog track the router source that owns them. Registration remains
the runtime export lane's job (`check-contract.sh`).
