# Published inline-body `title` pin

## What is pinned

`packages/api-client/openapi.json` publishes **68** `title` strings on the
inline (non-`$ref`) `application/json` response schemas. The exporter names
one per operation (`Response Liveness Api V1 Health Live Get`, ...). They are
part of the published document, but `openapi-typescript` drops them entirely:
`src/generated/openapi.d.ts` contains none of them. There is no generated half
to disagree, so the only possible fixed point is a reviewed literal — the same
shape as the `securitySchemes` descriptions in
`check_openapi_auth_surface.py` (#315).

`scripts/check_openapi_inline_body_integrity.py` deliberately strips `title`
in `_strip_title()` before classifying an inline schema shape; folding 68
prose strings into `_INLINE_BODY_BASELINE` would churn 75 reviewed entries and
lose the failure resolution. But nothing else read their *values*.

## Decisive ablation (live `9a7c3e52`)

Byte-preserving rewrite of one published title in the snapshot
(`Response Liveness Api V1 Health Live Get` -> `Response Liveness X`), with
`_PINNED_ARTIFACTS.snapshot_blob` honestly re-pinned:

- all 12 wired `check_openapi_*` guards: `rc=0`;
- `bash scripts/smoke.sh --profile contracts`: **SMOKE PASS / 1103 passed +
  41 subtests + 10 env-bound / 0 failed** (git-backed committed drift tree).

A published value changed and the whole contracts layer said nothing.

## The fix

`_INLINE_TITLE_DIGEST` — hand-written sha256 of the canonical sorted
`(operation, media, title)` rows, read from the committed snapshot only and
never derived from the artifact under guard. Plus an exact count door
(`_EXPECTED_INLINE_TITLES = 68`). A legitimate retype re-pins the literal in
the same commit as the snapshot, with a reason.

`failures()` gains `title_digest` / `expected_titles` injection so the in-file
plants can prove the door is load-bearing. `--self-test` grows 11 -> 17
checks (six new plants: literal-is-a-literal, coordinated rewrite, digest
load-bearing vs count door, derived-expectation control, count door, source
plant). Zero new wiring: the guard is already registered, pinned and invoked
with `--self-test` from `smoke.sh`; `PINNED_SUITES`, `REQUIRED_GUARD_CALLS`,
`_WIRED_SELF_TESTS`, `smoke.sh`, `ci-job-steps.sh`, teeth, registry,
`check_openapi_baseline_sync.py`, `openapi.json`, `openapi.d.ts` and
`_PINNED_ARTIFACTS` are byte-identical to live main.

## Decisive two-tree A/B (byte-identical drifted, git-backed trees)

| Tree | Guard | Result |
| --- | --- | --- |
| OLD (live `9a7c3e52`) | unmodified | all 12 `check_openapi_*` `rc=0`; `SMOKE PASS / 1103 + 41 + 10 / 0` |
| NEW | this phase | exactly one guard `rc=1`, naming `_INLINE_TITLE_DIGEST`; other 11 `rc=0`; `SMOKE FAIL / 3 failed, 1100 passed` |

The 3 layer failures are the drift propagating into the teeth evidence check
and the baseline-sync check — both correctly fail closed, no unrelated suite
damage. Clean NEW tree: `SMOKE PASS / 1103 passed + 41 subtests + 10
env-bound / 0 failed`, guard `--self-test` 17 checks / 0, 14 companion suites
345 passed.

Re-deriving the literal from the drifted snapshot makes the door silent (the
in-file `test_repinning_the_title_digest_from_the_drifted_tree_is_not_enough`
plant pins exactly that), which is why the value must stay a hand-written
literal and an intentional change must move it in the same commit as the
snapshot.

## Adding or retyping an inline-body title

1. Make the intentional source/artifact change.
2. Recompute `_INLINE_TITLE_DIGEST` with
   `_inline_title_digest(inline_title_rows(...))`, update
   `_EXPECTED_INLINE_TITLES`, both in the **same commit** as the snapshot,
   and say why.
3. Do not re-derive the literal from the artifact under guard at runtime.
