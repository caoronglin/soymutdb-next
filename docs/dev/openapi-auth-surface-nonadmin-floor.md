# OpenAPI auth surface: the non-admin protected floor

## Phase (one phase, one PR)

Follow-up in the offline OpenAPI guard family, cut by *file ownership* rather
than feature noun, as the roadmap requires. Zero file overlap with the twelve
in-flight PRs on base `05a1d4bb`: none of them touches
`scripts/check_openapi_auth_surface.py`, `scripts/test_openapi_auth_surface_floor.py`,
this document, or `docs/implementation/roadmap.md`. `scripts/smoke.sh` is a
hot file (several open PRs own it), so this phase deliberately adds **no**
standalone guard call there. The companion suite is registered in the gating
`tests[]` array so the contracts layer actually collects it; a plain
`pytest scripts/` run is a local hand-run, not a CI stage. The guard's own
`--self-test` also pins that `NON_ADMIN_PROTECTED` stays a hand-written source
literal.

## The defect

`scripts/check_openapi_auth_surface.py` checks 1/2/4/5 pin the two security
schemes, the per-operation `HTTPBearer` requirement on `/api/v1/admin/*`, the
three public auth-bootstrap operations and the four source files. Check 3 was
meant to protect the rest of the protected surface with:

```python
protected = sum(1 for _, _, o in operations if _bearer(o))
if protected < len(admin):
    found.append(...)
```

That bound **can never fire**. `admin` is a subset of `protected`, so
`protected >= len(admin)` by construction. The committed snapshot has 268
operations: 122 admin (all bearer), 48 non-admin bearer, 98 public. On live
main `05a1d4bb`:

```
python3 -c "... strip security from EVERY non-admin protected op ..."
# protected becomes 122, len(admin) is 122 -> check 3 green
# every admin op still bears -> check 2 green
# unmodified guard: rc=0  "openapi-auth-surface: OK (auth surface pinned)"
```

This is the same genus as the earlier phases in this series (\#154 / \#166 /
\#168 / \#190 / \#199): **a derived expectation cannot freeze a value**.
`check-contract.sh` proves export==snapshot; a coordinated edit that drops
`security` from the 48 non-admin operations and re-exports the snapshot keeps
every self-consistency gate green, because both halves move together. The
guard's own docstring claimed "a wholesale renumbering that keeps admin while
dropping the other 46 protected operations would otherwise go unnoticed" —
the claim described the hole accurately and then used a predicate blind to it.

## The fix

An independent, hand-written literal floor, following the
`_ERROR_RESPONSE_BASELINE` / `_SNAPSHOT_FLOOR` idiom used by the sibling
guards: `NON_ADMIN_PROTECTED` is a reviewed `frozenset` of the 48
`(path, method)` pairs that must require `HTTPBearer`. It is **not** derived
from `openapi.json`. Check 3 now compares the exact published set against it
in both directions:

- `missing` — a pinned operation no longer requires the bearer token
  (a co-revert or a re-export that dropped one);
- `extra` — an operation gained the requirement without a reviewed edit to
  the floor in the same commit as the re-export.

A deliberate change to the protected surface is an explicit, reviewable edit
to that literal in the same commit as the regenerated snapshot, not a silent
consequence of running the export.

## Negative controls (all on real bytes, not hand-waved)

| Injected shape | Unmodified live main | This phase |
| --- | --- | --- |
| Strip `security` from all 48 non-admin protected ops | `rc=0` OK | `rc=1` names 48 missing |
| Drop one non-admin operation's `security` | `rc=0` OK | `rc=1` names 1 missing |
| Add `HTTPBearer` to a public non-admin op | `rc=0` OK | `rc=1` names 1 extra |
| Drop all admin `security` (check 2, control) | `rc=1` | `rc=1` unchanged |

The guard's `--self-test` grew from 7 to 12 ablations: three co-revert shapes
plus two source-level plants that prove the literal-floor pin itself has teeth.
Each is emitted and checked by name. The companion
`scripts/test_openapi_auth_surface_floor.py` (7 pytest cases) exercises
`failures()` on synthetic snapshots and pins that the floor is a literal, not
a `json.load` of the artifact it checks. It is registered in `smoke.sh`'s
gating array; the guard's `--self-test` carries the same pin for the stdlib-only
entry point, so neither door depends on the other being collected.

## Validation (this branch, CPython 3.11.2, Node 26.13.0)

- `pytest scripts/test_openapi_auth_surface_floor.py -q` — 7 passed
- `python3 scripts/check_openapi_auth_surface.py` — OK
- `python3 scripts/check_openapi_auth_surface.py --self-test` — OK (10 ablations)
- `python3 -m unittest scripts.test_ci_job_contracts -q` — 103 OK
- `python3 scripts/check_contracts_registry_collection.py` (plain mode) — OK (44 gating suites, 18 guard calls)
- `python3 scripts/check_contracts_registry_collection.py --self-test` — 33 cases, 0 failure
- `bash scripts/smoke.sh --profile contracts` — **SMOKE PASS / 640 passed + 5 subtests + 10 env-bound / 0 failed**
- `py_compile` on both changed Python files — OK

Not run here (prerequisite missing, reported honestly): `--profile runtime`
needs a disposable PostgreSQL + API venv; `--profile images` needs a Docker
daemon; Playwright E2E needs browsers; a real `generate:api-client` re-export
needs the 3.15 toolchain. A missing prerequisite is SKIPPED, never a pass.

## Scope boundary

No `apps/web/**`, no OpenAPI snapshot re-export, no `scripts/smoke.sh`, no
`test_ci_job_contracts.py`, no git config, no push to another NPC's branch.
The two guards that are red on live main (`check_api_error_code_vocabulary.py`
and `check_error_code_catalog.py`, both `rc=1`, unconsumed by any `scripts/*.sh`
gate) belong to the in-flight error-code phase (\#196 / \#201) and are **not**
touched here.
