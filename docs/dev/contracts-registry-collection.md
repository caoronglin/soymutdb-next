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
- every active array row is a **bare path** (no flags/arguments),
  because the array is expanded verbatim into the ``pytest`` argv;
- no array entry is duplicated;
- the pinned standalone guard calls are still present, and no wired call
  sits outside `REQUIRED_GUARD_CALLS`;
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

The **layer call** is pinned the same way. `ci_wiring_errors()` uses the
`bash .../smoke.sh` line as the ordering reference, but a reference is not a
gate: appending `|| true`, `2>/dev/null`, `| tail -1` or a trailing comment
keeps the line present and its position unchanged while `set -e` sees success
even when the layer prints `SMOKE FAIL`. `CI_LAYER_BARE` requires that line to
be a standalone statement too; `--self-test` injects five such neutralisations
and asserts each is reported by name. Without it the only signal was an
`AssertionError` from the self-test's own literal-line lookup -- a crash, not a
named failure.

An independent second door lives in `scripts/test_ci_job_contracts.py`:
`ContractsRegistryWiringTests` reads the committed bytes of both entry points
directly. Deleting the CI-side `--self-test` line used to leave the whole
collected contracts suite green (95 passed), because no assertion in that file
named the guard. Those three checks stay red even if this guard is edited to
lie about itself. The regression suite itself is deliberately **not** added to
`smoke.sh`'s `tests[]`: that array is a shared insertion slot (four live PR
heads collide with a one-line addition there), so the guard's own
`--self-test` and the independent file are the collected coverage instead.

## A tests=() row must be a bare path

``registry()`` matches a row with ``ARRAY_ENTRY``, which ends at ``.py``. A
row such as ``scripts/check_x.py --self-test`` therefore does not match and is
silently skipped -- but it is still a real element of the array, and
``"${PYTHON_BIN}" -m pytest "${tests[@]}" -q`` passes it verbatim to pytest.
pytest rejects the unknown flag with ``unrecognized arguments`` and **exit 4**,
before collecting a single suite: the entire contracts layer is unrunnable,
and the only diagnostic is a bare pytest usage error that names neither the
array nor the row.

This is not hypothetical. PR #175 planted exactly such a row
(``scripts/check_mcp_release_binding.py --self-test``) in ``tests=()``; PR
#184 moved it out to the standalone-guard floor. On the tree between those two
landings, ``smoke.sh --profile contracts`` died at collection and the guard
still reported ``OK (41 gating suites ... wired)`` -- the row was invisible to
the very guard that exists to keep the array honest.

``array_line_errors()`` re-reads the same array slice and full-matches every
active, non-comment row against ``ARRAY_LINE`` (a lone path). ``--self-test``
replays the #175 shape and a pytest-flag variant, asserting each is reported
by name. A clean array stays green; a uniformly re-indented or commented row
is still accepted. The regression file covers the same two directions with
synthetic smoke text.

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

`REQUIRED_GUARD_CALLS` is pinned to exactly the set of standalone calls in
`smoke_contracts()`: `check()` reports both a wired call missing from the set
and a set member no longer wired. This is deliberate. A guard added to the
layer without being pinned here can be dropped later with a green `SMOKE PASS`
-- its only wiring probe may live inside the very call that was dropped, as
with the inline-body guard. `--self-test` plants an unpinned addition and
asserts it is caught, plus a control showing a same-change pin stays green.
Retire a call and remove its pin in the same commit; set-equality fails
closed on drift in either direction.

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

## The next cell: auditing the whole set, not just each row

`#192` made every active `tests=()` row full-match a bare path. That fixed
"the row is wrong". It did **not** fix "a row is gone": `registry()` is an
*extractor*, so deleting a suite lowers both the input and the output. An
equality such as `active_rows == len(registry())` is therefore **redundant**
(the bare-row check already rejects every non-bare active row) and **green on
deletion** (both sides drop together) -- the same co-reversion shape a
consistency check cannot see.

Measured on live `main` with the guard still printing
`OK (46 gating suites, 19 guard calls)` and `SMOKE PASS`:

| Drift | What the layer actually did |
| --- | --- |
| delete a `tests=()` row | `45 gating suites`, `SMOKE PASS`, 8 tests gone |
| `-k "not interval"` on the gating pytest line | `718 passed, 8 deselected`, `SMOKE PASS` |
| delete the whole gating pytest line | `SMOKE PASS`, zero gating suites collected |

Two controls matter. `>/dev/null` on a **standalone** guard call does **not**
drop it: `GUARD_CALL`'s `[^|]*?` tolerates internal redirection and
`|| rc=$?` still propagates the exit status -- diagnostics are swallowed, the
gate is live. And `--ignore=<path>` does **not** deselect an explicitly listed
argv path: pytest still collects that suite. `--ignore` is rejected here only
as a deviation from the reviewed bare form, not because it deselects anything.
The standalone guard calls themselves are already fully pinned on live `main`
(`REQUIRED_GUARD_CALLS` covers all 19, plus an assertion that any newly wired
call must be pinned in the same change), so that half of the original report
is closed.

The fix is two independent pins, reached through `wiring_errors()` so the
synthetic unit-test fixtures keep calling the extraction-only `check()`:

- `PINNED_SUITES`: a literal frozenset of the committed set, compared against
  what was extracted. A fixed point must not be derived from the bytes it
  audits. It is an **allowlist, not a floor**: adding a suite pins it in the
  same change, retiring one removes its entry.

  The distinction is not cosmetic. `REQUIRED_GUARD_CALLS` is a floor because
  `check()` independently fails closed on a wired call it does not name, so an
  addition is caught by the other half. Rows have no such second half:
  `tests=()` is exactly the bytes under audit. Measured on live `main` on
  2026-11-05, three rows had landed after the literal was written -- `#228`'s
  fallback-declaration suite, `#232`'s error-code contract suite and
  `#231`'s operationId floor suite. Deleting any one of them left
  `OK (48 gating suites, 22 guard calls, CI --self-test wired)` with exit
  status 0, while the control row `test_error_code_doc_counts.py` was named.
  A floor protects the set it measured and nothing that arrives later.
- `GATING_PYTEST`: the gating pytest invocation must be exactly one bare
  statement. This is the `CI_LAYER_BARE` shape brought one layer down; pinning
  the reviewed form catches `-k`, `--deselect`, `--ignore`, redirection,
  `|| true` and deletion without enumerating pytest flags.

`--self-test` adds the mutations for these shapes (including an unpinned row);
its summary stays measured from emitted result lines.

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
  name, **and** add it to `PINNED_SUITES` in the same change. The guard
  rejects an unpinned addition; `--self-test` plants one and proves it.
- Adding a standalone guard: add the `|| rc=$?` call **and** its path to
  `REQUIRED_GUARD_CALLS` in the same change. The guard rejects an unpinned
  addition; `--self-test` proves it.
- Retiring a suite: remove the row **and** its `PINNED_SUITES` entry.
- Retiring a called guard: remove the call **and** its pin from
  `REQUIRED_GUARD_CALLS`. A green `SMOKE PASS` after deleting a guard
  file must not be possible.
- Never change the driver's guard call back to `|| rc=$?`; `--self-test`
  fails on that mutation.
