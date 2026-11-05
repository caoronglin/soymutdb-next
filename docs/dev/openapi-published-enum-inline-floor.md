# Published enum components: the inlined-class exemption is a fixed point

`scripts/check_openapi_published_enums.py` compares every value domain the
OpenAPI snapshot publishes against the `Literal` / `StrEnum` / `Enum` that
declares it in `apps/api/app/schemas/**`. Its docstring claimed classes pydantic
flattens inline are "skipped by name, not by guess". That claim was false.

## The vacuous predicate

The guard derived its exemption list from the artifact it guards:

```python
inline_classes = [name for name in enum_classes if name not in components]
...
for name in enum_classes:
    if name in inline_classes:
        continue          # absence proves "pydantic inlined it"
```

`inline_classes` is exactly the set of enum classes missing from
`components.schemas`, so the `continue` fires for every such class by
construction. There is no authority that can disagree. Dropping a real enum
component from the snapshot — the co-revert this guard exists to catch —
reclassified the enum as "inlined" and the check stayed **green**. Measured on
the live `main` tree at landing time: deleting `AnalysisType`, `BlastProgram` or `NewsStatus`
each produced `failures() == []` with `compared` silently dropping 101 → 100;
deleting all 18 published enum components still produced `[]` (101 → 83).

This is the same shape as the `A4` catch in
[`openapi-auth-surface-nonadmin-floor.md`](openapi-auth-surface-nonadmin-floor.md):
`protected < len(admin)` cannot fire because `admin ⊆ protected`. Here the
predicate "is an inline class" is satisfied by the very absence the guard is
supposed to reject. Both read like a lower bound and never trigger; both
docstrings describe the hole correctly while the code leaves it open.

## The fix

`INLINED_ENUM_CLASSES` is now a reviewed literal, the same idiom already used
for `INLINED_MODELS` on the model path in this very file. Absence from
`components.schemas` is never allowed to prove an exemption:

- a source enum class **not** on the list must publish a component; if it does
  not, the guard reports the name and says the declared value domain cannot be
  verified;
- the enum loop skips a missing component cleanly instead of raising
  `KeyError`, so a mutated artifact yields a named failure, not a traceback;
- `--self-test` gains the decisive ablation (`a real enum component
  disappearing is named`). `smoke.sh` already invokes this guard with
  `--self-test`, so the new case is consumed by the contracts layer, not only
  by a hand run.

The 8 names are measured on live `main`, not guessed: they are the enum classes
whose names do not appear under `components.schemas` while their member values
are published inline on the referencing fields. The other 18 enum classes
publish a component today and must keep it. A genuine change in pydantic's
inlining requires editing the literal *and* re-reviewing the value domains.

## Verification (live `main`, CPython 3.11)

| Case | Result |
| --- | --- |
| clean guard / `--self-test` | `OK (101 pairs)` / `OK (11 ablations)` |
| drop one real enum component | `rc=1`, names the class; restore → clean |
| drop all 18 enum components | `rc=1`, 18 named failures, no traceback |
| neuter the new ablation, run `smoke.sh --profile contracts` | `SMOKE FAIL` (the layer consumes it) |
| restore the ablation | `SMOKE PASS / 667 passed + 5 subtests + 10 env-bound / 0 failed` |
| `main × this head` landing tree | guard plain + `--self-test` + negative control all green |
| 5 in-flight heads (read at landing time) | zero new conflicts; `#193` / `#206` conflicts pre-exist on clean `main` |

Both `compared` counts carry their tree: they move with the snapshot and are
not frozen constants. The floor is the literal, not a number.

## Generated-client enum/constant markers (a third artifact)

The guard above compares **source ↔ snapshot**. `openapi-typescript` is a
*third* export: it emits a JSDoc `@enum {string}` above every published
multi-member enum and `@constant` above every single-member `Literal`. An IDE
shows these tags when a caller hovers the field, so they are client-visible,
but no landed fixed point reads them. The description / title / default /
example digests read *other* JSDoc tags; `_PINNED_ARTIFACTS` is a provenance
blob id a regenerate re-pins in the same reviewed act.

### Decisive ablation (live bytes `77ba9a6b`)

Byte-preserving retype of one `@enum {string}` marker in
`packages/api-client/src/generated/openapi.d.ts`, with both
`_PINNED_ARTIFACTS` blob ids honestly re-pinned:

| Gate | Clean `77ba9a6b` | Marker retyped |
| --- | --- | --- |
| all 12 wired `check_openapi_*` guards | `rc=0` | `rc=0` |
| `smoke.sh --profile contracts` | **SMOKE PASS** | **SMOKE PASS** |
| contracts pytest | 1102 + 41 / 0 failed | 1102 + 41 / 0 failed |

The hover annotation silently disappears and nothing names it. This is the
same "derived expectation cannot freeze a projection" genus as #296/#299,
one artifact further out: the enum baseline is an exact description of the
*snapshot*, not of the generated client.

### What the door pins

- `_GENERATED_MARKER_SEQUENCE_DIGEST` — sha256 over the generated marker rows
  **in document order**, each row `name|tag|occurrence-index`. A sorted
  multiset is blind to a same-count rotation that moves a marker from one
  field to another, so the sequence is the pinned object, not the set.
  There are **136** rows: 100 `@enum {string}`, 36 `@constant`.
- `_EXPECTED_GENERATED_MARKERS` / `_EXPECTED_ENUM_MARKERS` /
  `_EXPECTED_CONSTANT_MARKERS` — exact count doors, so a dropped marker is
  named without relying on the digest alone.
- `generated_marker_rows()` reads only the `components` interface and pairs
  each marker with the declared name that follows its JSDoc block; the
  occurrence index disambiguates the many fields sharing a name such as
  `status` or `mode`.

`failures()` accepts an optional `generated` override, defaulting to the
committed bytes, so self-test plants and second-file regression cases can
inject their own copy. A same-commit re-pin of the literal with both artifacts
stays green; an honest pin is not a whitelist.

### Two-file evidence and wiring

`check_openapi_published_enums.py` carries module-level `test_*` functions
(8 → 14) as the second-file regression: the literal's independence, the
decisive retype, a same-count rotation, the re-pin control, and the guard's
own source plants. That file is now a gating `tests=()` row, so a one-file
edit to `failures()` cannot silence them. This adds one row to `smoke.sh` and
one entry to `PINNED_SUITES`; `REQUIRED_GUARD_CALLS` / `_WIRED_SELF_TESTS`
are unchanged (suites ≠ guard calls), and the teeth case floor is a minimum.
The guard's `--self-test` grows 17 ablations with three named marker plants.
