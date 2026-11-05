# Contracts-layer `--self-test` teeth

## The cell

`scripts/smoke.sh` wires the contracts layer through two mechanisms: a
`local tests=( ... )` array collected by pytest, and standalone
`"${PYTHON_BIN}" scripts/check_*.py ... || rc=$?` calls. Fifteen of those
standalone calls carry `--self-test` and no plain invocation: the guard's
`check()` never runs in this layer. Only its self-test does.

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
  drift at all", and every wired guard has one.
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
  set exactly.
- `EVIDENCE_MEMBERS` is checked, not just declared. Each member's success line
  states a case count (`N mutations`, `N cases`, `N negative cases`,
  `N ablations`), and the same output must carry at least that many
  distinguished per-case lines (`PASS self-test: <case> -> caught`,
  `ok: <plant> -> caught`, `self-test OK   <label>`). `N` cases from zero lines
  is the stub shape. Measured on live main before this row existed: nine of the
  ten members printed a count a `print(<pinned summary>); return 0` stub can
  echo while emitting no evidence, and the whole contracts layer stayed green.
  The floor is one-sided — extra lines stay green — so a legitimate phrasing
  change or a wider plant cannot turn it into a format audit, and a count that
  moves with the ablations still passes because the count is not pinned.
  Membership is listed as literals and audited against the output, not derived
  from the plants: the point is that a guard's evidence is read, not that the
  guard is trusted to be one of the good ones.
- `probe()` runs each wired guard as a real subprocess with `cwd=ROOT` and
  requires `rc == 0` plus a signature match. A gutted self-test, a failing
  self-test and an empty-output self-test are each named.

A signature pins the shape of one printed line, and nothing more. The guard
prints that line from a number it computes itself, so an edit that keeps the
`cases` dict, empties the loop over it, and prints `len(cases)` emits a
well-formed success line that no case produced. Measured on the #256 tree:
`for name, plant in []:` plus the `len(cases)` success line still printed
`(12 negative cases + clean tree)` and this probe stayed green. `_CASE_FLOOR`
closes that: an entry per guard whose self-test must still *reach* its
declared ablations — the mapping must hold at least N entries and some `for`
in the same function must iterate it. Both halves are read from the guard's
source by `ast`, so no printed number can satisfy them. Counts stay a free
variable: shifting the printed N by +5 stays green.

The guard's own `--self-test` plants a no-op into one guard **in process**
(import + replace `self_test` with a lambda returning 0 + `sys.argv` patch),
asserts a clean control first, then that exactly one guard loses its
signature and no other guard is collateral. Planting the mutation in a
partial temp tree made all 17 probes fail to open, so the case passed
vacuously — the first-hit trap this repo keeps paying for. The control
assertion is what keeps it honest.

Its own `--self-test` runs eight cases. The sixth pins the gap one layer below
the signature floor: a body gutted to `print(<pinned signature>); return 0`
still satisfies `_SIGNATURES` — the marker is a string a mutator can write —
so the case asserts **both** that the signature check stays green (or the case
proves nothing) and that the drift probe catches the same body. The seventh
pins the same gap for the half of the floor a drift plant cannot reach: a
drift plant needs a detection entry point to disable, and a per-case guard's
evidence is a print, so the assertion is that `N cases` with zero per-case
lines is rejected while the unlisted thin guard with the same output stays
green. The eighth pins the cell the signature, count and evidence floors all
miss: an entry point gutted so the plain run stops reading the committed tree
keeps every self-test PASS line. Measured on 999a39b3 —
`check_error_code_catalog.self_test` with `problems = []` before each
`check_tree(tree)` kept all twelve `ok: planted ... -> caught` lines and the
whole contracts layer at `SMOKE PASS`. Both limbs are asserted again.

`scripts/test_contracts_self_test_teeth.py` (24 cases) is the second file:
it pins the wiring into `smoke.sh`, the `REQUIRED_GUARD_CALLS` floor, status
propagation, the literal (non-derived) nature of the floors, both plants per
wire, the gut leg's two limbs, the `EVIDENCE_MEMBERS` direction (summary-only
output rejected, unlisted guards not audited, a legitimate count increase
green, an ambiguous count refused), and each negative direction under pytest
collection. A single-file edit cannot drop both the behaviour and its own
self-test plant.

## Wiring discipline

Adding a wired `--self-test` guard requires **four** edits in the same
change (a fifth when it also needs a `_CASE_FLOOR` row), per #223's set-equality rule:

1. the standalone call in `smoke_contracts()` with `|| rc=$?`;
2. an entry in `REQUIRED_GUARD_CALLS`;
3. an entry in `_WIRED_SELF_TESTS`, a signature in `_SIGNATURES`, **and both**
   plants — one in `_DRIFT_PLANTS` (a check to disable) and one in
   `_SELF_TEST_GUTS` (a plain run to gut);
4. the doc line below.

   A pinned self-test that prints a count also needs an entry in `_CASE_FLOOR`;
   one whose summary can be echoed by a stub also belongs in
   `EVIDENCE_MEMBERS`.

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
pinned by the companion suite.
