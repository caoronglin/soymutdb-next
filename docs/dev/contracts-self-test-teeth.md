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
- `probe()` runs each wired guard as a real subprocess with `cwd=ROOT` and
  requires `rc == 0` plus a signature match. A gutted self-test, a failing
  self-test and an empty-output self-test are each named.

The guard's own `--self-test` plants a no-op into one guard **in process**
(import + replace `self_test` with a lambda returning 0 + `sys.argv` patch),
asserts a clean control first, then that exactly one guard loses its
signature and no other guard is collateral. Planting the mutation in a
partial temp tree made all 15 probes fail to open, so the case passed
vacuously — the first-hit trap this repo keeps paying for. The control
assertion is what keeps it honest.

`scripts/test_contracts_self_test_teeth.py` (11 cases) is the second file:
it pins the wiring into `smoke.sh`, the `REQUIRED_GUARD_CALLS` floor, status
propagation, the literal (non-derived) nature of the two floors, and each
negative direction under pytest collection. A single-file edit cannot drop
both the behaviour and its own self-test plant.

## Wiring discipline

Adding a wired `--self-test` guard requires **four** edits in the same
change, per #223's set-equality rule:

1. the standalone call in `smoke_contracts()` with `|| rc=$?`;
2. an entry in `REQUIRED_GUARD_CALLS`;
3. an entry in `_WIRED_SELF_TESTS` **and** a signature in `_SIGNATURES`;
4. the doc line below.

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
