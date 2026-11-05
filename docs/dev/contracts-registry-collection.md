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

The line must use `python3`, the exact guard path and `--self-test`, it must
appear **before** the `bash smoke.sh` call -- otherwise the layer would already
have run by the time the gate fires -- and it must be a bare statement, not
merely a substring of one. If that `bash smoke.sh` call disappears or is
renamed, the ordering assertion has no reference point, so the guard fails
closed rather than silently skipping it. Those are separate properties, and a
pin that reads bytes instead of shell semantics has failed on each of them in
turn:

| Shape | What a substring pin sees | What bash does |
| --- | --- | --- |
| `... --self-test` | the invocation | gates the layer |
| `... --self-test \|\| true` | the invocation | discards the status |
| `... --self-test 2>/dev/null` | the invocation | discards the output, keeps the status |
| `... --self-test \| tail -1` | the invocation | reports `tail`'s status |
| `... --self-test  # note` | the invocation | fine, but a stale-looking line |
| `dead() { ...; }` | the invocation | never runs |
| `if false; then ...; fi` | the invocation | never runs |
| `( ... ) &` | the invocation | runs detached, status dropped |

The pin is therefore anchored to the whole line -- an end anchor with no
`re.MULTILINE` alternative, so any trailing operator, redirection, comment or
wrapper stops matching and is reported rather than accepted. Indentation is
read structurally instead of by width: re-indenting the function body moves
every line and is accepted, while a line sitting a level deeper than the
statement before it is inside a compound command and is reported. The mix of
tabs and spaces in this repository is why width alone cannot decide.

`--self-test` carries ten mutations for this shape alone: five trailing
operators, four dead-command wrappers and one duplicate, plus four indentation
variants that must be reported and the uniform re-indent that must stay green.

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

The `--self-test` summary is counted from the result lines it actually emits,
not from a hardcoded `len(cases) + N`: that constant drifts the moment a probe
is added and would report a case count nothing ran. A regression pins reported
== emitted against the committed tree.

Every wiring match starts at the command itself, never at a `#`: a
commented-out line still contains the right text and passes `bash -n`, but
executes nothing. The standalone `${PYTHON_BIN}` guard calls and the
driver-level dispatch are anchored to the start of a line, and
`driver_propagates()` skips comment lines. `--self-test` injects a
commented-out variant for each of the three slots (CI `--self-test` line,
standalone guard call, driver dispatch) and asserts the guard reports it.

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
