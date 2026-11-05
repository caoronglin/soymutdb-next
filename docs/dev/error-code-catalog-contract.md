# Error-code catalog contract

`packages/api-client/error-codes.json` is a generated, published artifact
(listed in `package.json` `files`). Its source of truth is the
`SoyMutDBError` hierarchy in `apps/api/app/core/exceptions.py`:
`error_code_catalog()` walks every subclass, takes its `error_code` attribute
and its class docstring, and `export_contract.py --error-codes` writes the
result. The same catalog is embedded in `openapi.json` as `x-error-codes`
(`main.py` injects it into the schema).

## The gap this guard closes

`check-contract.sh` re-exports `openapi.json` and diffs the generated
TypeScript client, but it never regenerates or compares `error-codes.json`.
Consequences before this guard:

- Adding a domain exception without running `generate:api-client` ships a
  catalog that omits the new code; the OpenAPI `x-error-codes` would disagree,
  but only if the snapshot was also re-exported -- and the standalone file is
  never checked at all.
- A hand edit to `error-codes.json` (or a stale-base co-revert of source +
  catalog + snapshot together) passes every existing gate: the snapshot diff
  compares the reverted backend with the reverted document.
- The catalog is consumed by frontend error mapping; a wrong `code` string or
  description changes client-visible behavior with no contract signal.

## What is checked

`scripts/check_error_code_catalog.py` reads only committed bytes (stdlib
`ast` / `json`, no API import, no 3.15 interpreter, no pydantic, no PG):

1. `error-codes.json` equals the catalog derived from the exception hierarchy.
   Descriptions are compared too -- they are derived with `inspect.cleandoc`,
   matching how Python stores `__doc__`, so multi-line docstrings (e.g. #103's
   `StatisticsInvariantError`) reproduce exactly.
2. `openapi.json` `x-error-codes` equals the same derived catalog.
3. Every code is a lowercase `snake_case` token; the catalog is non-empty.
4. Both wirings exist: `generate-api-client.sh` still passes `--error-codes`,
   and `check-contract.sh` still invokes the guard. Dropping either is a loud
   failure rather than a silent gap.

It is wired into `packages/api-client/scripts/check-contract.sh` (run on the
`$API_PYTHON` venv interpreter the gate already provisions), which both CNB
and GitHub reach through `verify-frontend-artifacts.sh` (`check:contract`).
`scripts/test_error_code_catalog_contract.py` is the regression suite: 12
pytest cases including synthetic drift trees and `--self-test` (9 planted
negative cases). Removing the loop/call, or weakening any single assertion,
turns a case red.

The suite is deliberately **not** registered in `smoke.sh`: that file's
`smoke_contracts()` test list is a shared hotspot (7+ in-flight PRs insert at
the same location), and the guard is already a hard gate via `check-contract.sh`.
A later phase can register it once those PRs land, without a conflict.

## Reproducing

```bash
python3 scripts/check_error_code_catalog.py              # live tree
python3 scripts/check_error_code_catalog.py --self-test  # planted drift
python3 -m pytest scripts/test_error_code_catalog_contract.py -q
```

Regenerate the artifacts (requires the API 3.15 venv + pnpm):

```bash
pnpm --filter @soymutdb/api-client generate:api-client
```
