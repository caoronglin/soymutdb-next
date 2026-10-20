# ADR-0015: dnd-kit sortable 10 upgrade; remaining held upgrades are blocked upstream

Status: accepted (2026-10-18)
Context: ADR-0010's remaining held rows were dnd-kit, jbrowse major,
TypeScript 7 and redis-py 8. This ADR records the one that could be taken and
the concrete, verified reasons the other three cannot be taken safely yet.

## Taken: `@dnd-kit/sortable` 8 → 10

`@dnd-kit/core` 6.3.1 and `@dnd-kit/utilities` 3.2.2 are already the latest
releases; only `@dnd-kit/sortable` was behind (8.0.0 → 10.0.0). Its peer range
(`@dnd-kit/core ^6.3.0`) is satisfied. The sole consumer is the admin
featured-news reorder modal, which uses the standard
`DndContext`/`SortableContext`/`useSortable`/`arrayMove`/`verticalListSortingStrategy`
API. Verified: admin `tsc --noEmit`, `eslint`, and 23 files / 172 tests pass.

### Adjacent dev-tooling refresh: jsdom 29.1.1 → 30.1.3

The Vitest DOM environment for `apps/web`, `apps/admin` and `packages/charts`
moves to jsdom 30.1.3 in the same change (it is dev-only and participates in
every component test). Verified by the three suites (web 44 files / 373 tests,
admin 23 / 172, charts 5 / 84).

## Blocked: redis-py 6.4 → 8

Celery's transport library Kombu is the owner of the redis-py bound. The latest
stable Kombu (5.6.2, used by Celery 5.6.3) declares
`redis>=4.5.2,<6.5`; the workspace is already at the ceiling (redis-py 6.4.0).
Upgrading to redis-py 8 would require a non-default Kombu (main/beta) or
bypassing the constraint, and redis-py 8 also switches the default wire
protocol to RESP3 (response-shape changes that need a deliberate review — the
platform cache and fail-closed rate limiter depend on connection/retry
semantics). Decision: hold until a Kombu stable release raises the bound;
then take redis-py 8 with an explicit RESP2/RESP3 decision.

## Blocked: TypeScript 5.9 → 7.0

TypeScript 7 (native compiler) is the npm `latest` tag, but the lint toolchain
is the binding constraint: the latest `@typescript-eslint/parser` (8.71.2)
declares `typescript >=4.8.4 <6.1.0`, so neither TS 7 nor the TS 6 beta is
accepted by the parser used by the repo's flat ESLint config. `@umijs/max`
4.7.24's own toolchain is also pinned to the 5.9 line. Decision: hold until
typescript-eslint ships TS 7 support and a Umi release validates against it;
the migration then needs its own branch with all workspaces type-checked before
any runtime change.

## Deferred: `@jbrowse/react-linear-genome-view` major

The jbrowse app is a separate build/deploy boundary, and its production build
cannot run inside the DSH sandbox (esbuild/process quota). The upgrade must be
validated by the CI artifact lane (`verify-frontend-artifacts` +
`startup-acceptance`), not by a local dependency bump. Decision: defer to a CI
change with the artifact gates as acceptance.

Consequences: after this ADR the hold list contains only four rows with named
owners/constraints (Kombu, typescript-eslint/Umi upstreams, CI jbrowse lane),
so the next dependency PR has a clear trigger condition. Rollback for the
taken change is the single `@dnd-kit/sortable` pin plus the lockfile.
