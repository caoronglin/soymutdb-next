# NCBI BLAST+ runtime repair: importable runner and engine-scoped programs

TaskStartSnapshot: base `bc6bf2a` (`feat(blast): execute NCBI BLAST+ alongside DIAMOND`, PR #38); branch `fix/blast-ncbi-runtime`; started 2026-11-03.

Change Necessity: the NCBI execution PR landed two defects that made the
headline P0 feature unreachable in production. Neither is a design question;
both are straight failures, and the existing suite could not see either one.

## Defect 1 — the runner module does not parse

`apps/worker/src/soymutdb_worker/ncbi_blast.py:266` and
`tasks/blast.py:421,426` carried Python-2 style `except A, B:` clauses.
`ncbi_blast.py` therefore raised `SyntaxError` on import, so every
`engine: ncbi_blast` job failed before touching an index:

```
E   File ".../ncbi_blast.py", line 266
E     except OSError, UnicodeError:
E            ^^^^^^^^^^^^^^^^^^^^^
E   SyntaxError: multiple exception types must be parenthesized
```

`tasks/blast.py` survived only because those two clauses sit in
`_set_subprocess_limits`, reached at `subprocess.run` time — the DIAMOND path
was already broken there and no test exercised it.

Fixed by parenthesising both.

## Defect 2 — the worker whitelisted `blastp` for every engine

`ALLOWED_PROGRAMS = frozenset({"blastp"})` was consulted for both engines, so
`blastn`, `blastx`, `tblastn` and `tblastx` were refused even though
`run_blast` routes them to `ncbi_blast.run_search` and the API schema
(`BlastSubmitProgram`) advertises all five. Only protein→protein search worked.

Fixed by making the program vocabulary engine-scoped (`ENGINE_PROGRAMS`), with
`validate_program(program, engine="diamond")`. DIAMOND stays protein-only;
NCBI BLAST+ runs all five. `run_blast_command` (DIAMOND) and `run_blast` now
pass the engine that will actually execute.

## Test-harness corrections

- `tests/test_ncbi_blast_real.py` spawned `makeblastdb` with the ambient
  environment. Without `BLAST_USAGE_REPORT=false` each NCBI binary spends ~31 s
  attempting usage reporting on a network-isolated host, so the whole real-binary
  suite timed out at its 20 s limit. The worker's own `_env` already sets this;
  the fixture now pins the same contract.
- `tests/test_lazy_task_registration.py` built a child `PYTHONPATH` without
  `packages/import-protocol/src`, so the subprocess failed to import
  `soymutdb_import_protocol` regardless of the change under test.

## Verification

Real NCBI BLAST+ 2.17.0 binaries (`ncbi-blast-2.17.0+-x64-linux`), synthetic
CC0 fixtures, no mocked search:

```
tests/test_ncbi_blast_real.py                6 passed   (blastn/blastp/blastx/tblastn/tblastx + reverse-strand + no-hit)
tests/test_blast_index_real.py               2 passed   (makeblastdb + blastdbcmd, nucl + prot)
tests/test_blast_engine_programs.py         12 passed   (new: engine×program matrix, source parses, runner imports)
apps/worker/tests (full)                   754 passed, 70 skipped
apps/api/tests -k blast                    250 passed, 28 skipped
```

`ruff check` clean on every touched file.

## Honest limitations

- The API suite has 30 pre-existing failures in this sandbox, all the same
  cause: `orjson` publishes no CPython 3.15 wheel and cannot build without Rust.
  Unrelated to this change; `0` non-orjson failures.
- This repair does not add the asynchronous `makeblastdb` publication workflow,
  the protein-hit→gene coordinate resolution, or the five-program UI wiring.
  Those remain open in `docs/implementation/roadmap.md` Phase 1.
- Anonymous (`/blast/public/*`) and account (`/blast/jobs`) submission paths are
  both untouched and both still route through the same service, outbox and
  worker; this change is engine-side only.
