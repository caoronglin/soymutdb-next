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
- `_DRIFT_PLANTS` — the guards whose signature a one-line gut **can** fake
  (those that print a single summary line) also get a drift plant: a source
  edit that disables the guard's detection entry point. `drift_probe()`
  applies the plant to the real tree, runs the wired `--self-test`, and
  requires a non-zero exit. A gutted body that reproduces the pinned marker
  (`print("... self-test passed"); return 0`) stays green on the signature
  check and goes red here. Guards that print per-case evidence
  (`ok: planted 'x' -> caught`) cannot be faked by a summary line and are
  listed in `_EVIDENCE_PER_CASE` instead. Every wired guard must be in exactly
  one of the two sets or `drift_floor_errors()` fails closed.
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

Its own `--self-test` runs six cases. The sixth pins the gap one layer below
the signature floor: a body gutted to `print(<pinned signature>); return 0`
still satisfies `_SIGNATURES` — the marker is a string a mutator can write —
so the case asserts **both** that the signature check stays green (or the case
proves nothing) and that the drift probe catches the same body.

`scripts/test_contracts_self_test_teeth.py` (14 cases) is the second file:
it pins the wiring into `smoke.sh`, the `REQUIRED_GUARD_CALLS` floor, status
propagation, the literal (non-derived) nature of the two floors, and each
negative direction under pytest collection. A single-file edit cannot drop
both the behaviour and its own self-test plant.

## Wiring discipline

Adding a wired `--self-test` guard requires **four** edits in the same
change (a fifth when it also needs a `_CASE_FLOOR` row), per #223's set-equality rule:

1. the standalone call in `smoke_contracts()` with `|| rc=$?`;
2. an entry in `REQUIRED_GUARD_CALLS`;
3. an entry in `_WIRED_SELF_TESTS` **and** a signature in `_SIGNATURES`;
   a guard that prints only a summary line also needs an entry in
   `_DRIFT_PLANTS`; one that prints per-case evidence goes in
   `_EVIDENCE_PER_CASE`;
4. the doc line below.

   A pinned self-test that prints a count also needs an entry in `_CASE_FLOOR`.

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

The probe re-runs the wired self-tests (~4 s). It is a teeth check, not a
second copy of their assertions: the guards remain the sole owners of what
each mutation means. A guard that legitimately changes its success line must
update its signature here in the same commit; that is the reviewed action,
pinned by the companion suite.
