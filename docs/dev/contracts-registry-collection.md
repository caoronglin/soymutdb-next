# Contracts-layer registry / collection contract

## What is pinned

`scripts/smoke.sh` wires the contracts layer through two independent
mechanisms, both inside `smoke_contracts()`:

1. `local tests=( ... )` — a literal array of paths handed to
   `"${PYTHON_BIN}" -m pytest "${tests[@]}" -q`.
2. A floor of standalone guards invoked as
   `"${PYTHON_BIN}" scripts/check_*.py ... || rc=$?`.

`scripts/check_contracts_registry_collection.py` reads both from the
committed `smoke.sh` bytes and asserts:

- every array entry exists, parses, and defines at least one collectible test;
- no array entry is duplicated;
- the known floor of standalone guard calls is still present;
- every called guard still exists on disk;
- the driver-level invocation registers its failure in `FAILED`, so a failing
  guard cannot print `SMOKE PASS` (see below).

## Why

A registered path that pytest collects **zero** tests from is silently
ignored. The layer still prints `SMOKE PASS` with an unchanged collected
count, so a hand-merge that keeps a bogus entry, a rename that turns a suite
into a non-test module, or a stale path looks exactly like a healthy gate.
This is the same "registered but not collected" shape seen in hardcoded
counts, `Ran 0 tests, OK`, and the interval-visibility guard's two wiring
slots — where the `tests[]` entry conflicts visibly but the standalone call
can be dropped without any conflict marker.

Demonstrated on the tree that would actually land (`main + #150`): adding a
registry entry whose module defines no `test_*` leaves
`SMOKE PASS / 427 passed / 0 failed`. The guard reports it by name.

## The driver must not swallow the guard

`smoke.sh` sets `set -uo pipefail` and decides its exit status from the
`FAILED` array, not from a top-level `rc`. A driver-level call ending in
`|| rc=$?` therefore prints the guard's diagnostics but still exits 0 with
`SMOKE PASS` -- the exact silent no-op this guard exists to prevent. The
driver registers the failure in `FAILED` instead, and the guard's
`--self-test` includes a mutation that restores `|| rc=$?` and asserts it is
caught.

## The CI entry point and its ordering

`ci-job-steps.sh`'s `smoke_contracts_run()` invokes the guard with
`--self-test` before running `bash smoke.sh --profile contracts`. That line is
a third wiring slot: a `keep one side` hand-merge of the add/add conflict in
this function can drop it while the local `smoke.sh` dispatch stays intact --
and a validator that reads only `smoke.sh` cannot see it. The guard therefore
reads `ci-job-steps.sh` too and requires the invocation inside that function
body.

Indentation inside a bash function is noise, so the match is not anchored to
the start of a line: a deeper space indent or a tab still runs in bash and is
accepted. But the line must use `python3`, the exact guard path, and
`--self-test`, and it must appear **before** the `bash smoke.sh` call --
otherwise the layer would already have run by the time the gate fires. Moving
it below that call is a silent inversion, and `--self-test` asserts it is
caught.

## Boundary

The guard is a **static** proxy, not a pytest subprocess. It recognises
module-level `def test_*` and `unittest.TestCase` methods via `ast`. pytest's
real discovery also handles fixtures, parametrization, dynamic collection
hooks and `pytest_collect_file`; a suite relying on those would need a
different assertion. It deliberately does not enumerate every
`scripts/test_*.py` on disk: 16 such files are owned by other gates
(frontend, bio-core, backend) and are intentionally absent from this array.
One-to-one *set equality* would therefore be wrong; the pinned direction is
"everything registered must really collect something".

`REQUIRED_GUARD_CALLS` is a floor, not an allowlist: adding a new guard call
needs no edit here (verified by `--self-test`), removing one fails. The list
must be updated only when a guard call is intentionally retired from this
layer.

## Running

```bash
python3 scripts/check_contracts_registry_collection.py --self-test
python3 scripts/check_contracts_registry_collection.py
python3 -m pytest scripts/test_contracts_registry_collection.py -q
```

No Python 3.15, wheel, database, Rust toolchain or workspace install needed.
The guard is invoked by `smoke.sh --profile contracts` (local runs) and by
`ci-job-steps.sh`'s `smoke_contracts_run()` (the CI Contract suites stage,
with `--self-test`), so it gates both entry points before any suite is
collected. The guard deliberately does **not** add its regression file to
`tests=()`: that array is a shared merge slot with many in-flight PRs, and the
guard's `--self-test` already provides the mutation coverage. The pytest file
is kept for direct runs and editor integration.

## Changing the layer

- Adding a suite: put the path in `tests=()`, keep at least one `test_*`
  name. No edit to this guard.
- Adding a standalone guard: add the `|| rc=$?` call. No edit to this guard.
- Retiring a suite or a called guard: remove the entry/call **and** update
  `REQUIRED_GUARD_CALLS` if it was in the floor. A green `SMOKE PASS` after
  deleting a guard file must not be possible.
- Never change the driver's guard call back to `|| rc=$?`; `--self-test`
  fails on that mutation.
