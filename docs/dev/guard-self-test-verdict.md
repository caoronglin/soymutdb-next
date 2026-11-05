# A guard's `--self-test` verdict must reach its exit status

## The cell

`scripts/check_contracts_self_test_teeth.py` proves every wired guard still
*plants* mutations: it applies a source drift, runs the guard's `--self-test`,
and requires the run to detect it. Its gut probe goes further and requires the
same `--self-test` to stay **green** while a check is disabled, then reads the
plain run for the signal.

Both legs assume the guard's status is connected to its output.
`scripts/check_guard_self_test_verdict.py` covers the case where it is not:
the plants run, the `FAIL: … was not caught` lines are printed, and a
later assignment throws the verdict away before the exit status is
computed. The gate is dead while its stdout looks honest, and
every plant in the teeth guard stays green because the guard *does* detect
them — it just does not report it.

## The shipped instance

`scripts/check_openapi_published_enums.py` carried exactly that shape. The
marker self-test plants three door ablations and then ran

```python
    result = 0
    for label, mutate in cases:
```

after the marker loop. With all three marker doors gutted, `--self-test`
printed

```
FAIL: a generated @enum marker is retyped was not caught
FAIL: a generated @constant marker is retyped was not caught
FAIL: a same-count marker relocation between two doc blocks was not caught
OK (17 ablations)
```

and exited **0**. That file's own second-file suite could not see it: the suite
calls `failures()` directly, and `--self-test` is the only caller that assigns
the status.

## What the guard reads

For each `--self-test` call wired in `smoke_contracts()`, the guard resolves the
function that computes the status — `_self_test` / `self_test` /
`run_self_test` / `_run_all`, in the guard or in the module it delegates to
(`from scripts.<module> import self_test`, `import test_<x> as suite`) — and
requires that no verdict name is assigned a pass value *after* a verdict has
already been written.

- **Reported**: a pass reset that lands after a `FAIL`/failure write. Every
  plant caught before that line is printed and thrown away.
- **Accepted**: one initialiser at the top; a second initialiser before every
  plant; a counter that merely shares a prefix (`results = 0`,
  `failures_seen += 1`); an expression status (`return 0 if not failures else 1`);
  `problems = [] if x else problems`, which filters rather than resets.
- **Fails closed**: a wired `--self-test` whose status function cannot be
  located. "Wired but unreadable" is not proof that the verdict is load-bearing.

The reading is structural, on committed bytes. No guard is imported, no venv,
no Docker, no network.

## Evidence

Measured on the two record heads of that fix, detached worktrees, CPython 3.11:

| tree | guard on committed bytes |
| --- | --- |
| `90fb79bf` (bug shipped) | 1 finding: `_self_test() assigns 'result' a pass value at line 1219` |
| `bbfcb6b2` (bug fixed) | clean |
| `bbfcb6b2` + the bug re-planted | 1 finding, same line shape |

Live-tree drift plant, applied to a *different* wired guard
(`check_openapi_field_constraints.py`) so the check is not tuned to one file:

| tree | guard's own `--self-test` | this guard |
| --- | --- | --- |
| clean | `self-test: 27 cases, 0 failure(s)`, rc=0 | OK (21 wired self-tests) |
| `failures_count = 0` inserted after its loops | rc=**0**, still green | **rc=1**, names the line |

False positives over all 21 wired guards on live main: **0**.

## Wiring

- `scripts/smoke.sh` → `smoke_contracts()`, `--self-test` call, before pytest.
- `scripts/check_contracts_registry_collection.py` → `REQUIRED_GUARD_CALLS`.
- `scripts/check_contracts_self_test_teeth.py` → `_WIRED_SELF_TESTS`,
  `_SIGNATURES`, `_DRIFT_PLANTS`, `_SELF_TEST_GUTS`. The teeth guard fails
  closed on a wired `--self-test` that is not pinned there, so this guard is
  probed by the same machinery as every other one.
- `scripts/test_guard_self_test_verdict.py` → gating `tests=()` row and
  `PINNED_SUITES`; 13 cases, including one that mutates a real wired guard on
  disk, runs the guard as a subprocess, and reads the exit code.

## Suite counts

| suite | before | after |
| --- | --- | --- |
| gating `tests=()` rows | 61 | 62 |
| pinned guard calls | 32 | 33 |
| `smoke.sh --profile contracts` | 1103 passed (live main) | 1116 + 41 subtests + 10 bound |
