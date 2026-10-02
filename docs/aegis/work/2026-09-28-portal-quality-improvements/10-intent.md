# Portal quality and feature improvements - Intent

## TaskIntentDraft

- Requested outcome: Complete the user-approved, phased improvements to the SoyMutDB public portal and its Admin experience.
- Goal: Audit and improve localization, typography, clipping, Admin UX, footer editing, portal functionality, analytics collection and visualization across apps/web, apps/admin, and apps/jbrowse, with no production writes.
- Success evidence:
- Every implementation slice has an approved spec and plan, focused tests/builds pass, published routes receive desktop/mobile screenshot review, isolated Admin workflows pass on synthetic data, and existing ClickHouse telemetry/history is preserved while GoatCounter and AntV are verified.
- Stop condition: Stop on scope drift or any required production write. Keep the goal active with needs-verification when isolated Admin environment or SoyMutDB preview is unavailable; ask the user before any live Admin write or starting a replacement server.
- Non-goals:
- No production writes, no silent data/telemetry deletion, no desktop runtime in this monorepo, and no implementation outside a separately approved slice.
- Scope: Phased work across apps/web, apps/admin, apps/jbrowse, relevant API/client contracts, self-hosted GoatCounter, preserved ClickHouse search/component/Web Vitals history, and AntV dashboards; each phase requires user-approved scope.
- Change kinds:
- cross-cutting-feature
- Risk hints:
- Public/internal security boundary, runtime settings/API compatibility, search assembly/release invariants, telemetry retention, and Admin write workflows; synthetic test data only.

## BaselineReadSetHint

- AGENTS.md
- docs/dev/database-core-contract.md
- docs/aegis/BASELINE-GOVERNANCE.md
- docs/superpowers/specs/2026-09-28-portal-ui-quality-remediation-design.md
- docs/aegis/plans/2026-09-28-portal-ui-quality-remediation.md
- docs/superpowers/specs/2026-09-28-admin-editable-footer-search-font-design.md

## BaselineUsageDraft

- Required baseline refs:
- AGENTS.md
- docs/dev/database-core-contract.md
- docs/aegis/BASELINE-GOVERNANCE.md
- docs/aegis/baseline/2026-09-28-initial-baseline.md
- docs/superpowers/specs/2026-09-28-portal-ui-quality-remediation-design.md
- docs/aegis/plans/2026-09-28-portal-ui-quality-remediation.md
- docs/superpowers/specs/2026-09-28-admin-editable-footer-search-font-design.md
- Delivered context refs:
- none
- Acknowledged before plan:
- AGENTS.md
- docs/dev/database-core-contract.md
- docs/aegis/BASELINE-GOVERNANCE.md
- docs/aegis/baseline/2026-09-28-initial-baseline.md
- docs/superpowers/specs/2026-09-28-portal-ui-quality-remediation-design.md
- docs/aegis/plans/2026-09-28-portal-ui-quality-remediation.md
- docs/superpowers/specs/2026-09-28-admin-editable-footer-search-font-design.md
- Cited in plan:
- AGENTS.md
- docs/dev/database-core-contract.md
- docs/aegis/BASELINE-GOVERNANCE.md
- docs/aegis/baseline/2026-09-28-initial-baseline.md
- docs/superpowers/specs/2026-09-28-portal-ui-quality-remediation-design.md
- docs/aegis/plans/2026-09-28-portal-ui-quality-remediation.md
- docs/superpowers/specs/2026-09-28-admin-editable-footer-search-font-design.md
- Missing refs:
- none
- Advisory decision: continue

## ImpactStatementDraft

- Compatibility boundary: Footer response and old setting keys remain compatible; ClickHouse search/component/Web Vitals collection and historical records remain while GoatCounter replaces only public pageview analytics; existing routes and API contracts are additive unless separately approved.
- Affected layers:
- apps/web
- apps/admin
- apps/jbrowse
- apps/api
- packages/api-client
- packages/i18n-core
- telemetry
- deployment
- Owners:
- Each application/API owns its route, settings, and telemetry boundary; the approved footer API remains under apps/api, versioned settings remain the persistence owner, and the current goal is the coordination parent.
- Invariants:
- Preserve explicit external/internal isolation, stable IDs and release/assembly/provenance contracts, existing ClickHouse history, and no-production-write policy.
- Non-goals:
- No production writes, no silent data/telemetry deletion, no desktop runtime in this monorepo, and no implementation outside a separately approved slice.

These records are Method Pack drafts / hints, not authoritative runtime decisions.
