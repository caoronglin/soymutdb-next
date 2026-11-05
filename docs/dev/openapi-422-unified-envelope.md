# Error responses must advertise the envelope the runtime sends

## The first defect (PR #154)

`apps/api/app/main.py` registers `validation_exception_handler` for every
`RequestValidationError`. That handler **always** returns the unified error
envelope (`ValidationErrorResponse`): `error` / `request_id` / `status_code`
plus a sanitised, field-level `errors` array. FastAPI's default 422 shape
(`HTTPValidationError`, a flat `detail` list) is never emitted.

`_build_openapi_schema` documented that envelope with
`responses.setdefault("422", ...)`. `get_openapi` populates the auto 422
first, so `setdefault` was a no-op on 235 of 266 operations. Both committed
artifacts — `packages/api-client/openapi.json` and the generated
`src/generated/openapi.d.ts` — typed 422 as `HTTPValidationError` for those
operations. A consumer writing error handling against the generated client
wrote a branch for a shape that never arrives and no branch for `errors`.

The two artifacts agreed with each other byte-for-byte. A diff gate cannot see
this class of defect: equality of two generated products is not evidence that
the source declares the truth. This is the same genus as PR #103 (an
undeclared 404 typed as unreachable), one status over.

Fix: `main.py` overrides (not `setdefault`s) the 422, preserving a route's
richer 422 description; both artifacts were regenerated with the pinned tool.

## The second defect: a guard that only banned one name

The guard added with that fix checked the generated client for the literal
`HTTPValidationError` body spelling. Three regressions stayed green against
it — each reproduced on the live tree before this change:

| Regression | Old guard | Reason |
| --- | --- | --- |
| Retype one 422 body in `openapi.d.ts` as `ErrorResponse` | GREEN | Wrong shape, but not the one banned name |
| Delete one operation's `500` response from the snapshot | GREEN | Guard never looked at 500 in the JSON half |
| Retype one `500` response as `HTTPValidationError` | GREEN | Guard only scanned 422 refs |

In all three, `openapi.json` and `openapi.d.ts` still agreed with each other,
so `check-contract.sh`'s byte diff could not see it either. A guard that
looks for one bad spelling is not a guard against a wrong shape.

## The contract

`apps.api.app.main` registers four handlers. Every one emits `ErrorResponse`
except the 422 handler, which emits `ValidationErrorResponse`:

| Handler | Status | Body |
| --- | --- | --- |
| `soy_mut_db_exception_handler` | domain status | `ErrorResponse` |
| `http_exception_handler` | HTTP status | `ErrorResponse` |
| `validation_exception_handler` | 422 | `ValidationErrorResponse` |
| `unhandled_exception_handler` | 500 | `ErrorResponse` |

Therefore every operation must declare a `422` (`ValidationErrorResponse`) and
a `500` (`ErrorResponse`), and every other declared 4xx/5xx response (today
409 and 429) must use `ErrorResponse`. No operation may declare a 4xx/5xx body
the runtime does not send.

## Guards

`scripts/test_openapi_422_unified_envelope.py` reads committed bytes only
(stdlib, no 3.15 venv, no PostgreSQL) and asserts:

1. every operation declares a 422 and a 500, each with the exact runtime schema;
2. every other declared 4xx/5xx response uses `ErrorResponse`;
3. the generated client contains **exactly as many** `ErrorResponse` and
   `ValidationErrorResponse` response bodies as the snapshot declares — so a
   dropped, retyped or *one-sidedly* added body changes a count instead of
   hiding behind a banned-name check;
4. the declared error-response distribution (`422`/`500` on every operation,
   plus `409` x3 and `429` x1) is pinned to an exact baseline. The equality
   check is self-referential: `expected` is recomputed from the supplied JSON,
   so a snapshot and client edited **together** still agree. A coordinated
   drop OR add (e.g. inventing a `418` on both halves) is caught only by this
   independent fixed point, the same idiom as `_SNAPSHOT_FLOOR`;
5. `main.py` overrides rather than `setdefault`s the 422, still registers all
   four handlers, and both declared schemas are defined in the document;
6. the guard is wired into `smoke.sh --profile contracts`.

It keeps its original file name (and therefore its existing wiring), so this
change adds no entry to the shared `tests[]` array that dozens of in-flight PRs
are editing. 16 in-file mutation cases cover every branch, including the three
regressions above and the coordinated add/drop blind spot.

The adjacent `scripts/test_openapi_snapshot_contract.py` had no `__main__`
block: a direct run printed nothing and exited 0, which reads as a pass to
anything that only checks the exit code. This PR gives it a standalone runner
and a self-test that pins the runner. Keeping that check inside the snapshot
guard itself (not in the envelope guard) avoids making the 6 in-flight owners
of this file turn red on a file they do not own.

The baseline pins the **declared error surface**, not the endpoint count: a
legitimate new endpoint adds its own 422/500, so `_ERROR_RESPONSE_BASELINE`
must be updated in that same commit with a reason. An exact pin in both
directions is deliberate — an error status the runtime never sends is as wrong
as a dropped one.

`apps/api/tests/test_error_envelope_openapi_floor.py` pins the same contract on
the schema built from the live `app.main:app` in the 3.15 pytest lane, with a
floor on the number of non-422/500 error responses so the assertion cannot
pass vacuously. The offline guard covers the committed artifacts; this one
covers the builder that produces them.

## Verification (record it, don't round it)

- `python3 scripts/test_openapi_422_unified_envelope.py` — 16 checks OK.
- `python3 scripts/test_openapi_snapshot_contract.py` — 19 checks OK, with a
  real `__main__` runner; removing it reproduces the old silent rc=0.
- On the unmodified live tree, the three regressions above are GREEN against
  the old guard and RED against the new one. A coordinated add of a `418` to
  **both** artifacts — GREEN against the unpatched count guard — is RED now.
- Checked against **73** open PR heads: 7 carry the guard (this PR + 6 valid
  owners #160/#162/#164/#165/#166/#167), all GREEN; the other 66 forked before
  #154 and never owned the file (their `deleted file` diff is stale, not a
  conflict). `merge-tree --write-tree` over the full 73-head matrix: 0 new
  conflicts, 0 resolved.
- `apps/api/tests/test_error_envelope_openapi_floor.py` needs the Python 3.15
  API venv; it was **not** executed in the CPython 3.11 sandbox and is not
  counted in any local pass number. A real
  `pnpm --filter @soymutdb/api-client generate:api-client` / `check:contract`,
  full API pytest, runtime smoke, E2E and images were not run here — CI is the
  authority, do not sign them on the strength of this document.

## The third defect: nothing counted success bodies

Both guards above pin error responses. Neither counts a `2xx` body, so three
defects stayed green against the pair — reproduced on live `6d6c32b9`:

| Regression | 422 guard | Snapshot guard | Body guard |
| --- | --- | --- | --- |
| Delete one operation's `200` content from `openapi.json` | GREEN | GREEN (path and schema floors still hold) | **FAIL** |
| Retype a `200` from `GeneListResponse` to another existing schema | GREEN | GREEN | **FAIL** |
| Client regenerated from a newer backend than the snapshot | GREEN | GREEN (field-set check is per schema, not per response) | **FAIL** |

The envelope guard cannot see the first two because it only iterates
`4xx`/`5xx`, and `_ERROR_RESPONSE_BASELINE` pins *status codes*, not bodies.
The snapshot guard's `_SNAPSHOT_FLOOR` is a count of paths and schemas — a
`200` that keeps its path is above the floor either way.

`scripts/test_openapi_snapshot_body_integrity.py` addresses it: for every
component a path operation references, the snapshot's declared count and the
generated client's printed count must agree, and the client may not reference
a component the snapshot does not define. Its first version pinned
`_CLIENT_BODY_TOTAL` (807) as an independent fixed point and used a one-sided
per-component equality; it caught a body dropped or retyped in **one** half,
and the three regressions in the table above, but — see the fourth defect
below — not a coordinated drift of both halves.

`_CLIENT_BODY_TOTAL` (807) is larger than the snapshot's 722 component response
bodies because the pinned generator also prints request bodies (82 components,
85 occurrences).

## The fourth defect: the first body guard was still self-referential

The first two independent fixed points above (`_ERROR_RESPONSE_BASELINE` and
`_CLIENT_BODY_TOTAL`) closed the coordinated error-response edit. The body
guard as first committed did **not** apply that idiom to its own per-component
equality: it recomputed `expected` from whichever JSON it was given, kept a
one-sided `have < want` check, and pinned only the aggregate client total.
Three drifts stayed GREEN against all three guards, each reproduced on live
bytes with byte-preserving edits:

| Coordinated drift (both halves together) | 422 guard | Snapshot guard | Body guard v1 |
| --- | --- | --- | --- |
| Retype one request body (`UserCreate` → `NewsCreate`) | GREEN | GREEN | **GREEN** |
| Shift one occurrence between doubled request components | GREEN | GREEN | **GREEN** |
| Move one `200` between two existing success components | GREEN | GREEN | **GREEN** |

In all three the total stays 807, both artifacts agree with each other, and no
component is undeclared — `expected` moved with the supplied JSON, so equality
held. The 85 request-body lines had **no per-component assertion at all**; they
were the named gap. The success-response side had the same hole.

The fix is two more independent fixed points, literals in the guard and not
derived from either artifact:

- `_RESPONSE_BODY_BASELINE` — the exact count of each component referenced from
  a path operation's `responses` (136 components, 722 occurrences);
- `_REQUEST_BODY_BASELINE` — the exact count of each component referenced from
  a path operation's `requestBody` (82 components, 85 occurrences).

The snapshot's response and request distributions must each equal their
baseline exactly, and the generated client's per-component counts must equal
the sum of the two baselines exactly — two-directional, nothing one-sided,
nothing self-referential. A regenerate that drifts both halves together now
fails on the baseline, not on a difference between the halves. `_CLIENT_BODY_TOTAL`
stays as a loud aggregate first signal.

A baseline is only a fixed point if the commit that turns it red cannot also
re-pin it. `_PINNED_ARTIFACTS` records the git blob id of both artifacts the
literals were counted from, and `_baseline_moved_with_the_artifacts()` recomputes
those ids from the committed bytes on every run. So a regenerate that drifts both
halves and bumps the counts in one commit also has to re-pin the blob ids in the
same diff, and a re-pin that does not match the artifacts it claims to describe
is rejected on its own message.

### The residual: distribution is not topology

Those two baselines pin **how many** of each component exist, not **which
operation** declares each one. A permutation of two same-count bodies —
`/api/v1/auth/register` and `/api/v1/auth/login` swapping `UserCreate` /
`LoginRequest` in both artifacts together — preserves all 807 occurrences,
keeps both halves agreeing and leaves no component undeclared, yet the client
types the wrong request body on the login form. 105 of 136 response components
and 79 of 82 request components sit at count 1, so nearly any two are
swappable. The same holds on the response side. This is the coordinated-drift
class one level down: both halves still move together, they just have to
preserve the multiset rather than the total. It is **closed**, by a third fixed
point added in the same PR:

- `_BODY_PAIR_DIGEST` — `sha256` of the sorted
  `(method, path, status|requestBody, component)` tuples, one literal covering
  topology and distribution at once (807 pairs →
  `f3382283236a34ddf96d10ce984a36bc6266f87d2c63de13aa066f54611a3ecc`). Regenerate
  with the canonical form in the guard docstring: uppercase the method, sort by
  the tuple itself, join fields with one space and records with `\n`, no trailing
  newline. The two baselines stay as the readable diagnostic; the digest is the
  strict pin.

| Coordinated drift (both halves together) | Baselines only | With digest |
| --- | --- | --- |
| Permute two count-1 request bodies (register/login) | **GREEN** | **FAIL** |
| Permute two count-1 success responses | **GREEN** | **FAIL** |
| Pristine committed bytes | GREEN | GREEN |

Verified on the committed tree: 18 checks, `OK`, rc=0, collected by pytest (18
passed). In-file mutation cases cover all five drifts above, the two repin cases,
the two permutations, plus client-only, snapshot-only, undeclared-component and
smoke-wiring regressions; byte-preserving working-tree ablations of each drift
go red and restore green.

## The baselines are literals, so bumping one is a one-file edit

Everything above rests on fixed points written in the guards' own source:
`_ERROR_RESPONSE_BASELINE`, `_RESPONSE_BODY_BASELINE` /
`_REQUEST_BODY_BASELINE` / `_CLIENT_BODY_TOTAL`, `_BODY_PAIR_DIGEST` and
`_SNAPSHOT_FLOOR`. That is the only shape that catches a coordinated edit of
both artifacts — and it creates the last hole in the chain: the fixed point is a
**literal**. Raising a baseline is one edit to one file, and every guard goes
green again with `openapi.json` and `openapi.d.ts` untouched.

The guards' own instructions are the escape hatch: *"update the baseline in the
same commit and say why"*. Nothing checked that the same-commit part happened.
The numbers in this document have already drifted from that instruction once
(#184 repaired 800/266 to 807/268 on live bytes), which is what a number with
no enforcement behind it looks like.

`scripts/check_openapi_baseline_sync.py` (wired into `smoke.sh --profile
contracts`, mutation-tested by `scripts/test_openapi_baseline_sync.py`) closes
it with two independent doors:

1. **semantic** — the pinned literal must equal the number recomputed from the
   committed artifacts. Needs no git, so it holds on a shallow CI checkout and
   under a squash commit where a parent diff would lie. This is the door that
   makes "bump a number" fail on its own;
2. **history** — a literal that moved between the base commit and `HEAD` must
   sit in a commit where the artifact it pins also changed. This is the case
   door 1 cannot see: a number edited to match a tree that was never committed
   is self-consistent by construction. `--ref` / `--base` make the comparison
   explicit where history is truncated.

`_SNAPSHOT_FLOOR` is deliberately excluded. It is a floor, not an equality, and
it moves on every API-growing commit — "the artifacts changed in an ancestor"
is already true there and would be a vacuous check. Its equality cousin is
`_RESPONSE_BODY_BASELINE`: gained paths must grow the response distribution,
and that is what fires.
