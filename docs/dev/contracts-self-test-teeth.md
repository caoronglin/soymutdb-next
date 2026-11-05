# Contracts-layer `--self-test` teeth

## The cell

`scripts/smoke.sh` wires the contracts layer through two mechanisms: a
`local tests=( ... )` array collected by pytest, and standalone
`"${PYTHON_BIN}" scripts/check_*.py ... || rc=$?` calls. Twenty of those
standalone calls carry `--self-test`; this guard's own call is the twenty-first.
For most of them that is the only invocation in the layer, so `check()` never
runs here — only their self-test does. Three also have a plain call elsewhere
in `smoke_contracts()`: that plain run is the only call that reads the
committed tree. `BOTH_CALLS` pins that set — deleting a plain run otherwise
keeps every gate and the whole layer green while the guard never inspects the
real source. Do not "remove the duplicate call" without removing its
`BOTH_CALLS` row in the same reviewed change.

`check_contracts_registry_collection.py` pins that every call **exists** and
is listed in `REQUIRED_GUARD_CALLS`. It does not read the body the call
reaches. Measured on live `ae0f8ac0`: replacing
`check_app_shell_assets.self_test` with `return 0` left the whole layer at

```
SMOKE PASS / 741 passed + 5 subtests + 10 env-bound / 0 failed
```

The call was present, pinned and green while the guard had lost every
assertion it owned. This is one level below the "registered but not
collectible" cell: registered, collectible, invoked — and vacuous.

## What is pinned

`scripts/check_contracts_self_test_teeth.py`:

- `_WIRED_SELF_TESTS` — a hand-written literal floor of the guards wired via
  `--self-test`. Adding a wire without pinning it fails closed; dropping a
  wire is reported by name. A fixed point must not be derived from the bytes
  it audits.
- `_SIGNATURES` — one regex per guard matching the **shape of the evidence**
  the self-test prints (`OK (N checks)`, `N mutations`, `self-test passed`,
  `N cases, 0 failures`). Counts are deliberately not pinned: a legitimate new
  ablation changes `OK (11 checks)` to `OK (12 checks)` and must stay green.
  A no-op `return 0` prints nothing and matches none of them.
- `_DRIFT_PLANTS` — a source edit that disables one *check* the guard owns.
  `drift_probe()` applies it to the real tree, runs the wired `--self-test`,
  and requires a non-zero exit. This answers "does the guard still detect
  drift at all", and every wired guard has one. `_plant()` returns
  `rc=None` when the plant itself failed (unreadable source, missing anchor,
  no-op replacement, failed subprocess); `drift_errors()` reports that as an
  unrun probe instead of reading a bare non-zero `rc` as "caught". Without
  that distinction an edit that deletes a plant's own anchor immunises itself
  against the very probe meant to catch it. The companion suite pins both
  limbs from a second file.
- `_SELF_TEST_GUTS` — a second plant, at the entry point instead of at a
  check: stop the plain run reading the committed tree. This is the shape no
  output-based floor can see. A guard whose self-test plants its own mutations
  in memory or on temp copies prints every `ok: <plant> -> caught` line
  whether or not the plain run reads anything, so the signature, the declared
  count and the per-case evidence all survive. `gut_probe()` requires the
  wired `--self-test` to stay green *and* the plain run to report the
  untouched tree as clean; only the second half is a signal, and a guard whose
  plain run still fails means the plant proved nothing. Every wired guard has
  one, and `drift_floor_errors()` fails closed unless both sets cover the wire
  set exactly. `gut_anchor_errors()` additionally pins the source shape: each
  registered anchor must sit inside `main()`, never `self_test()`. An anchor in
  `self_test()` never reaches the plain run, and `gut_probe()` reads only exit
  codes, so `plain_rc == 0` cannot tell "the guard survived" from "the plant
  never ran" — the empty leg would stay green. The pin is structural, so a new
  wire carrying the same bug is named at registration instead of shipped.
- `EVIDENCE_MEMBERS` is checked, not just declared. Each member's success line
  states a case count (`N mutations`, `N cases`, `N negative cases`,
  `N ablations`), and the same output must carry at least that many
  distinguished per-case lines (`PASS self-test: <case> -> caught`,
  `ok: <plant> -> caught`, `self-test OK   <label>`). `N` cases from zero lines
  is the stub shape. Measured on live main before this row existed: nine of the
  ten members printed a count a `print(<pinned summary>); return 0` stub can
  echo while emitting no evidence, and the whole contracts layer stayed green.
  The floor is one-sided — extra lines stay green — so a legitimate phrasing
  change or a wider plant cannot turn it into a format audit, and a declared
  count that moves with the ablations still passes. But the *emitted* evidence
  is also held to the reviewed `_CASE_FLOOR` literal: a guard whose success line
  prints a loop counter (e.g. `{results}`) lets an edited loop shrink the
  declared count and the per-case lines together, so `emitted < declared`
  never fires. Measured on `c3e88a49`: slicing
  `check_openapi_operation_id_floor.py`'s loop to 8 of 11 rows printed
  `8 cases` with 8 PASS lines, all source-AST floors stayed green, and the
  whole layer reported `OK (20 wired guards probed)`. The literal floor names
  it.
  Membership is listed as literals and audited against the output, not derived
  from the plants: the point is that a guard's evidence is read, not that the
  guard is trusted to be one of the good ones.
  **A member is not exempted because its evidence is unfakeable; it is exempted
  because it emits more than one line.** `_SIGNATURES` still matches one line
  of that output, so a gut reduced to `print(<closing line>); return 0` would
  satisfy it — of the thirteen, one prints `ok: planted 'x' -> caught`, the
  others print `PASS self-test: ...` variants. What makes them load-bearing is
  `_CASE_FLOOR` below, not the shape of their output.
- `probe()` runs each wired guard as a real subprocess with `cwd=ROOT` and
  requires `rc == 0` plus a signature match. A gutted self-test, a failing
  self-test and an empty-output self-test are each named.

A signature pins the shape of one printed line, and nothing more. The guard
prints that line from a number it computes itself, so an edit that keeps the
`cases` dict, empties the loop over it, and prints `len(cases)` emits a
well-formed success line that no case produced. Measured on the #256 tree:
`for name, plant in []:` plus the `len(cases)` success line still printed
`(12 negative cases + clean tree)` and this probe stayed green.

The two plants have the same one-sided shape: they disable one check or one
entry point, not a *case*. Deleting the decisive `cases.append((...))` block
from `check_openapi_operation_id_floor.py` leaves its self-test at
`10 cases, 0 failure(s)` while every plant, signature, evidence line and
count check here stays green — the tuple `(path, anchor, replacement, why)`
cannot assert "this anchor is still the only one". (A marker-preserving gut of
`check_app_shell_assets.py` is caught *specifically because* that guard has a
plant; the per-case-evidence guards are not covered by that claim.)

`_CASE_FLOOR` closes both: one reviewed row per `EVIDENCE_MEMBERS` guard,
reading the case rows from the guard's **source** (`dict`/`list`/`tuple`
literals, `cases.append(...)`, `cases[key] = ...`, or a module-level literal
such as `CLAIMS`) and requiring some `for` in the same function to name that
container. A deleted case then names itself. `evidence_floor_errors()` fails
closed if an audited guard has no row, so adding one is a reviewed edit.
Both halves are read by `ast`, so no printed number can satisfy them. Counts
stay a free variable: shifting the printed N by +5 stays green.

The guard's own `--self-test` plants a no-op into one guard **in process**
(import + replace `self_test` with a lambda returning 0 + `sys.argv` patch),
asserts a clean control first, then that exactly one guard loses its
signature and no other guard is collateral. Planting the mutation in a
partial temp tree made all probes fail to open, so the case passed
vacuously — the first-hit trap this repo keeps paying for. The control
assertion is what keeps it honest.

Its own `--self-test` plants one case per gap. Ordinals are deliberately not
used here: an ordinal in prose goes stale exactly like a cardinal in a comment,
and a new case inserted in the middle used to leave "the sixth" describing the
wrong gap. The signature-floor case pins a body gutted to
`print(<pinned signature>); return 0` — the marker is a string a mutator can
write — by asserting **both** that the signature check stays green (or the
case proves nothing) and that the drift probe catches the same body. The
per-case-evidence case covers the half a drift plant cannot reach: `N cases`
with zero per-case lines is rejected while an unlisted thin guard with the
same output stays green. The entry-point case pins the cell the signature,
count and evidence floors all miss: a plain run gutted to stop reading the
committed tree keeps every self-test PASS line. Measured on 999a39b3 —
`check_error_code_catalog.self_test` with `problems = []` before each
`check_tree(tree)` kept all twelve `ok: planted ... -> caught` lines and the
whole contracts layer at `SMOKE PASS`. Both limbs are asserted again.
The loop-counter-forgery case pins the reviewed floor: a coherent short run
passes the one-sided `emitted < declared` check (or the case proves nothing)
and is named by the floor. Both limbs are asserted again.

The both-calls case deletes a pinned plain run and asserts the floor names it.
The final case closes one turn of the same genus: dropping a `BOTH_CALLS` row
**and** that guard's plain run in one edit leaves every membership rule silent
(no row is left to complain about), so `BOTH_CALLS_SIZE` is asserted as a
reviewed cardinality. Both limbs are asserted: membership is blind to the
coordinated edit, and the counted floor is what names it.

`scripts/test_contracts_self_test_teeth.py` is the second file:
it pins the wiring into `smoke.sh`, the `REQUIRED_GUARD_CALLS` floor, status
propagation, the literal (non-derived) nature of the floors, both plants per
wire, the gut leg's two limbs, the `EVIDENCE_MEMBERS` direction (summary-only
output rejected, unlisted guards not audited, a legitimate count increase
green, an ambiguous count refused), and each negative direction under pytest
collection. A single-file edit cannot drop both the behaviour and its own
self-test plant.

## Wiring discipline

Adding a wired `--self-test` guard requires **four** edits in the same
change (a fifth, mandatory for every `EVIDENCE_MEMBERS` guard, is its
`_CASE_FLOOR` row), per #223's set-equality rule:

1. the standalone call in `smoke_contracts()` with `|| rc=$?`;
2. an entry in `REQUIRED_GUARD_CALLS`;
3. an entry in `_WIRED_SELF_TESTS`, a signature in `_SIGNATURES`, **and both**
   plants — one in `_DRIFT_PLANTS` (a check to disable) and one in
   `_SELF_TEST_GUTS` (a plain run to gut);
4. the doc line below.

   A guard audited for per-case evidence belongs in `EVIDENCE_MEMBERS` **and**
   gets a `_CASE_FLOOR` row (guard, source file, function, case container,
   minimum declared rows).

A guard that must also read the committed tree needs a **second** plain call in
`smoke_contracts()` and a matching row in `BOTH_CALLS`. The registry floor pins
a guard's path, not how many times it is invoked: deleting the plain run keeps
its path pinned, keeps the `--self-test` green and keeps `SMOKE PASS`. Do not
"remove the duplicate call" without removing its `BOTH_CALLS` row in the same
reviewed change -- that row is the only net under the plain half. Membership
alone is data, not mechanism: the same one-commit edit can drop the row and the
call together, so `BOTH_CALLS_SIZE` pins the reviewed cardinality next to the
literal and fails closed when the floor shrinks.

The companion suite is a normal `tests=()` row; `PINNED_SUITES` is a floor,
not an allowlist, so adding a suite needs no edit there (see
`docs/dev/contracts-registry-collection.md`).

## Running

```bash
python3 scripts/check_contracts_self_test_teeth.py
python3 scripts/check_contracts_self_test_teeth.py --self-test
python3 -m pytest scripts/test_contracts_self_test_teeth.py -q
bash scripts/smoke.sh --profile contracts
```

## Boundary

The probe re-runs the wired self-tests once per plant (~9 s of the layer). It
is a teeth check, not a second copy of their assertions: the guards remain the sole owners of what
each mutation means. A guard that legitimately changes its success line must
update its signature here in the same commit; that is the reviewed action,
pinned by the companion suite. A registered plant whose anchor drifts away
from the committed source no longer proves anything; the probe says so by name
instead of silently counting a failed plant as a detection.
