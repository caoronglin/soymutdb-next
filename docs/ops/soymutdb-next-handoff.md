# SoyMutDB Next — delegation and NPC pipeline contract

How work on the "下一代优化" programme (Issue #1) is split between agents, and
what the repository pipeline needs to look like for that split to function.
It is written down because the pipeline previously looked wired up and was not.

## 1. The defect this fixes

The `$` → `issue.comment@npc` body was:

```yaml
script: echo "Handled by the .cnb.yml npc pipeline"
```

That is the failure shape worth remembering: the build goes **green**, the
mention looks acknowledged, and no agent ever reads the thread. Nothing
downstream noticed, because a placeholder that exits 0 is indistinguishable
from a task that succeeded. Every delegation in this repository therefore
silently became "please do it yourself".

Three related faults, each of which on its own would have kept `@` mentions from
working:

1. **No `npc:go` job.** Only that task can reply, write branch code and open a
   PR on the mentioner's behalf.
2. **Only `issue.comment@npc` was declared.** NPC config merges *per event*, so
   a missing `pull_request.comment@npc` falls back to the platform default and
   the two entry points drift silently.
3. **An `npc:go` block had been dropped into `main` → `pull_request`.** That
   event is the verification gate; the block carried no `name`, so it did not
   sit beside `verify`, it replaced it. See the commit history for
   `fix(ci): drop the npc:go block that pre-empted the pull_request gate`.

## 2. What the configuration now guarantees

- `$/issue.comment@npc` and `$/pull_request.comment@npc` both start a named
  `npc` pipeline whose body is `type: npc:go`.
- Prompts are **not** passed in `.cnb.yml`. For `@` mentions the platform
  injects the role prompt from `.cnb/settings.yml` and ignores `options`, so
  writing them in both places creates a second source of truth that silently
  does nothing. For non-mention triggers (`api_trigger`, `push`, `crontab`)
  `options.userPrompt` is required and `role` alone is rejected — that path
  belongs to whoever wires it, with its prompt alongside it.
- `.cnb/settings.yml` declares `npc.roles`; names match the `@repo(role)`
  mention exactly (case-sensitive, no globbing).
- `scripts/test_ci_job_contracts.py` enforces all of it:
  `test_npc_events_run_the_npc_task_instead_of_a_placeholder` fails when an NPC
  event body stops being `npc:go` or when either event goes missing, and
  `test_npc_events_resolve_a_role_declared_in_settings` fails when `npc.roles`
  is empty. The role requirement is deliberately skipped for `@npc` events,
  because there the role comes from the mention and `options.role` can never
  take effect.

## 3. Role split

| Role | Scope | Allowed to touch |
| --- | --- | --- |
| `CodeBuddy` (system) | orchestration, frontend, evidence | `apps/web/`, `docs/`, pipeline config |
| 代码审查员 | PR review; facts only | nothing — comments only |
| 功能开发 | backend / data pipelines | `apps/worker/`, `apps/api/app/api/v1/blast.py`, `apps/api/app/services/blast_service.py`, `packages/api-client/src/blast.ts` |

The two BLAST entry points (`apps/web/src/routes/blast.tsx`,
`apps/web/src/routes/search/blast.tsx`) have exactly **one** owner at a time.
That is what keeps parallel agents from double-writing the same file; it is the
reason frontend work is excluded from 功能开发's scope rather than a comment on
who is better at it.

## 4. Programme state — current facts, not a roadmap

Delivered or in review:

- PR #3 — worker `except` syntax repair, engine-scoped program vocabulary
  (`ENGINE_PROGRAMS`). **Merge authority for the worker side**; merged.
- PR #4 — dual-entry query parity and result downloads on the frontend. Its
  worker changes yield to #3.

Still open on Phase 1 (NCBI BLAST+). Each of these was verified absent in the
working tree, not assumed:

- `makeblastdb` lifecycle inside Celery. `apps/worker/src/soymutdb_worker/blast_index.py`
  is a solid operator-only CLI (`build` / `verify`, atomic rename, checksums)
  with **no task calling it**; `tasks/blast.py` only reads pre-placed indexes.
- Catalog build state machine and immutable index publication.
- Protein-hit → transcript/gene coordinate resolution before any genome-browser
  link. Amino-acid coordinates are never genomic coordinates.
- Cancellation / retry / download-expiry coverage on the NCBI path.

Nothing above should be described as complete until it has a test that runs, and
the PR states which commands were executed and which were not.
