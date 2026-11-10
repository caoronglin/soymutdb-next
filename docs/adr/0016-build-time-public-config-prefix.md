# ADR-0016: Build-time public config uses the `SOYMUTDB_*` prefix

Status: Accepted

Date: 2026-11-09

## Context

The portal and admin were originally built with Vite, so every build-time
public value was named `VITE_*`. Both apps now build with Umi Max, but those
names survived because the build scripts and deployment dashboards already used
them. In practice this leaked Vite-era terminology into operator-facing
configuration: the admin analytics settings page instructed operators to create
`VITE_CLOUDFLARE_ANALYTICS_TOKEN`, even though no Vite build reads it anymore.

The prefix is only a naming convention, not a runtime mechanism. Build-time
public values are still injected into static artifacts and are not secrets.

## Decision

- New build-time public configuration uses the `SOYMUTDB_*` prefix. The first
  migrated variable is `SOYMUTDB_CLOUDFLARE_ANALYTICS_TOKEN`.
- Existing `VITE_*` names remain readable as legacy aliases so deployed
  Cloudflare Pages projects do not silently lose behaviour. The canonical name
  wins when both are set.
- Operator-facing surfaces (admin pages, UI copy) document only the canonical
  `SOYMUTDB_*` name. Legacy names are recorded in deployment documentation.
- Renaming a variable is a coordinated change across the build config, the CSP
  builder (`apps/web/scripts/csp.ts`), the Turbo environment allowlist, deploy
  documentation, and the hosting project's environment variables.
- The remaining `VITE_*` variables are not renamed wholesale in this decision.
  Each one moves when its owning surface is touched, with the same
  canonical-plus-alias pattern.

## Consequences

- New deployments create `SOYMUTDB_*` variables; existing `VITE_*` values keep
  working until their owners migrate.
- The analytics beacon keeps working during migration because both readers
  (`apps/web/config/config.ts` and `apps/web/scripts/csp.ts`) accept either
  name.
- A future cleanup can drop the legacy aliases after deployment dashboards no
  longer set them. That removal must be announced in release notes because it
  changes external configuration, not repository code.