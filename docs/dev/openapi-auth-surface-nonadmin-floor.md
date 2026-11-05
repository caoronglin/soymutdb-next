# OpenAPI auth surface: the non-admin protected floor and the projection pin

Two fixed points live in `scripts/check_openapi_auth_surface.py`, and they
measure two different things:

| literal | rows | what a change to it means |
| --- | --- | --- |
| `NON_ADMIN_PROTECTED` | 48 | a reviewed operation lost or gained the bearer requirement |
| `_SECURITY_PROJECTION_DIGEST` | 268 | an operation moved between protected and public |

They are deliberately not the same pin. The floor is a reviewed allowlist of
operations a human chose to protect; the digest is the *whole* published
projection, so it also covers the 122 admin operations (which check 2 only
sweeps in one direction) and the 98 public ones. A count-preserving swap
between protected and public moves neither the floor's size nor either count
door -- only the digest.

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

## Phase 2: the projection pin (why the floor was not enough)

The floor above answers "did a reviewed operation lose the requirement". It
does **not** answer "which operations publish `security` at all", and nothing
else did either:

- `openapi-typescript` drops `security` from the generated client on purpose,
  so there is **no second half**. Every guard in this repository that compares
  two artifacts is structurally blind here.
- `_OPERATION_ID_DIGEST` / `_PARAMETER_DIGEST` / `_RESPONSE_SURFACE_DIGEST` /
  `_OPERATION_SUMMARY_DIGEST` / `_ANNOTATION_DIGEST` walk the same operations
  and never read the field.
- `_FIELD_CONSTRAINT_DIGEST` walks component property schemas, not operations.
- Check 2 (`/api/v1/admin/*` must bear) is one-directional: it names an admin
  operation that *lost* the requirement and is silent about one that is not in
  the document at all.

Decisive ablation on live bytes (`bfb3919d`): delete `security` from all 170
operations in the snapshot, leave `main.py`'s projection untouched, and re-pin
the two provenance blob ids exactly as `test_openapi_snapshot_body_integrity.py`
documents for one reviewed regenerate.

| guard / suite | clean tree | after the ablation |
| --- | --- | --- |
| `check_openapi_response_surface.py` | `rc=0` | `rc=0` |
| `check_openapi_operation_parameter_floor.py` | `rc=0` | `rc=0` |
| `check_openapi_operation_id_floor.py` | `rc=0` | `rc=0` |
| `check_openapi_operation_annotations.py` | `rc=0` | `rc=0` |
| `check_openapi_field_constraints.py` | `rc=0` | `rc=0` |
| `check_openapi_inline_body_integrity.py` | `rc=0` | `rc=0` |
| `check_openapi_published_enums.py` | `rc=0` | `rc=0` |
| `check_openapi_baseline_sync.py` | `rc=0` | `rc=0` |
| `test_openapi_behavior_contracts.py` (26 cases) | 26 passed | 26 passed |
| `check_openapi_auth_surface.py` | `rc=0` | `rc=1`, named by the digest |

The last row is the point: **only the guard that already had a signal could
see it** -- and on the pre-pin guard its own `--self-test` then died in its
*setup control*, which is how the hole surfaced.

`_SECURITY_PROJECTION_DIGEST` is sha256 over `"\n".join(header + rows)`,
where `header` is `soymutdb-security-projection/v1` and each row is
`METHOD|path|operationId|protected`, for all 268 operations. `protected` is
the published fact (`bool(security)`), not "does it name HTTPBearer", so a
scheme swap moves it too.
`_EXPECTED_PROJECTED = 170` and `_EXPECTED_HIDDEN_OPS = 98` are exact count
doors; a same-count permutation satisfies neither the digest nor them
together.

Re-pinning is a reviewed edit: update the literal in the same commit as the
re-export and say why. Deriving it from the snapshot would make the pin agree
with itself, which is the failure it exists to replace.

### Non-duplication, as a test

Two negative controls keep this pin from quietly retargeting a surface someone
else owns:

- `test_the_pin_does_not_duplicate_the_response_surface_guard` -- the sibling
  guard that walks the same 268 operations must still read no `security`.
- `test_the_pin_does_not_duplicate_the_behavior_contracts_suite` -- that suite
  reads `x-idempotent`, `x-pagination`, the error envelope and the 429/500
  sets; it must not start reading the bearer requirement either.

And one positive control on the pin's own precision:
`test_a_count_preserving_move_is_caught_only_by_the_digest` swaps one
operation out of the protected set and another in, then asserts the digest
fires while both count doors stay silent. A pin that fired on the counts would
be a count check wearing a digest's name.

## Validation (this branch, CPython 3.11.2, Node 26.13.0)

- `pytest scripts/test_openapi_auth_surface_floor.py -q` — 17 passed
- `python3 scripts/check_openapi_auth_surface.py` — OK
- `python3 scripts/check_openapi_auth_surface.py --self-test` — OK (14 ablations)
- `bash scripts/smoke.sh --profile contracts` — `SMOKE PASS / 921 passed
  + 5 subtests + 10 env-bound / 0 failed` (clean base: 911)
  (the layer size is unchanged: this phase adds no wire, no registry row and
  no teeth entry -- `smoke.sh`, `check_contracts_registry_collection.py` and
  `check_contracts_self_test_teeth.py` are the three files #272/#273/#281
  kept colliding in)
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
