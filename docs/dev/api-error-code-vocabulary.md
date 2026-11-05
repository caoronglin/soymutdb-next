# Published API error-code vocabulary

## What is frozen

`packages/api-client/error-codes.golden.json` is a hand-written lock of the
public `error.code` values the API can emit, with their client-facing
descriptions. It covers the twelve codes derived from the `SoyMutDBError`
hierarchy in `apps/api/app/core/exceptions.py`.

The lock is **not** an input or output of any generator.
`generate-api-client.sh` writes exactly three artifacts from
`app.main:app` / `error_code_catalog()`:

- `packages/api-client/openapi.json` (including the `x-error-codes` extension)
- `packages/api-client/error-codes.json`
- `packages/api-client/src/generated/openapi.d.ts`

The lock is a fourth file, outside that set.

## Why a lock is needed

Every other check on the published catalog is a **consistency** check:

| Gate | What it proves | What it cannot see |
| --- | --- | --- |
| `check-contract.sh` | a fresh export equals the committed snapshot | both were reverted together |
| `check_error_code_catalog.py` (#136) | artifacts equal the catalog re-derived from the source AST | source and artifacts moved together |
| `check_error_code_contract.py` (#152) | artifacts equal the executed source functions (three status codes pinned) | a rename of any other code, with all artifacts regenerated |
| `test_openapi_behavior_contracts.py` (#166) | `x-error-codes` exists and is published by `error_code_catalog()` | the *contents* of the catalog |

So renaming `settings_version_conflict` in `exceptions.py` and re-running
`generate:api-client` leaves all of them green while a published, client-visible
code value silently changes. `error.code` is a value clients branch on; it is a
public contract, not a derived echo of the implementation.

This is the same blind spot `packages/bio-core/errors.golden.json` closes for
the Rust kernel error codes (PR #162), one layer up. The two locks are
independent: kernel codes are `UPPER_SNAKE` values in `errors.rs`, API domain
codes are `lower_snake` values in `exceptions.py`.

## The guard

`scripts/check_api_error_code_vocabulary.py` reads committed bytes only — no
API import, no Python 3.15 venv, no wheel, no database. It asserts:

- the lock is valid, non-empty, lowercase-snake keys with string descriptions;
- neither generator mentions the lock file, so it cannot become a derived
  artifact without a failing gate;
- `error-codes.json` and `openapi.json`'s `x-error-codes` match the lock exactly:
  no missing codes, no extra codes, no changed descriptions;
- every `error_code` literal declared in the exception hierarchy is frozen, and
  every frozen code is still declared.

`--self-test` plants seven independent defects (coordinated rename, dropped
code, changed description, lock turned into a generated artifact, invented
source code, empty lock, duplicate key) and proves each is caught.

`packages/api-client/python_tests/test_api_error_code_vocabulary.py` provides
seven `unittest` regressions, including the killing mutation: a rename applied
to the source **and** both published artifacts still fails, because the lock is
not one of them.

## Wiring

`packages/api-client/scripts/check-contract.sh` runs the guard and the
regression suite at the end of the frontend contract gate, on both CNB and the
GitHub mirror (the job bodies are shared scripts). The guard is also runnable
standalone from a developer machine:

```bash
python3 scripts/check_api_error_code_vocabulary.py
python3 scripts/check_api_error_code_vocabulary.py --self-test
python3 -m unittest discover -s packages/api-client/python_tests -p 'test_*.py'
```

## Change process

Adding, removing, or renaming a public error code is a **breaking contract
change**. Do not edit the lock to make a green build. Instead:

1. Ship the runtime change with a migration note naming the old and new codes,
   the affected clients, and the redirect/alias policy.
2. Update `error-codes.golden.json` in a **separate, reviewed commit** in the
   same PR, with the reason in the commit message.
3. Regenerate the two JSON artifacts and the TypeScript client.
4. Confirm the guard's `--self-test` and the regression suite pass.

A lock that is auto-updated by the generator is not a lock. Keep it hand-written.

Ref: #1
