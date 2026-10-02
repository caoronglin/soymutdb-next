# SoyMutDB Initial Baseline

> **已归档（2026-10-01）**：2026-08 设计波次与旧基线快照。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md；门户布局以 `docs/superpowers/specs/2026-08-14-public-web-layout-alignment-design.md` 为准。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

Date: `2026-09-28`
Status: `initial dual-baseline snapshot`

## 1. Purpose
- Establish a compact starting point for future Aegis alignment checks.
- Record only verified project boundaries and current authority gaps; this snapshot is evidence, not independent product authority.

## 2. Workspace Structure
- `apps/web`, `apps/admin`, and `apps/jbrowse` are the shipped frontend applications.
- `packages/i18n-core` owns shared English/Chinese locale resources.
- `scripts/` owns repository verification gates; `e2e/tests` owns browser tests.
- `docs/dev/` contains architecture, deployment, and domain-contract documentation.

## 3. Current Authority Surfaces
- Repository instructions: `AGENTS.md` and this workspace's baseline governance.
- Biological identity/search/runtime invariants: `docs/dev/database-core-contract.md`.
- React frontend architecture and UI direction: `docs/superpowers/specs/2026-09-27-react-pro-v6-replatform-design.md`.
- Migration status and verification limitations: `docs/dev/react-migration-progress-2026-09-27.md`.
- Current approved portal UI slice: `docs/superpowers/specs/2026-09-28-portal-ui-quality-remediation-design.md`.
- Authority gap: the repository has no root `CONTEXT.md` or `CONTEXT-MAP.md`; no active terminology conflict is known for this UI slice.
- Toolchain note: `AGENTS.md` lists pnpm 11.21.0, but the authoritative `.cnb.yml` and root `package.json` both pin `pnpm@12.5.1`; the guidance row is stale. The global pnpm launcher emitted `[ERROR] unable to open database file`; offline Corepack `pnpm@12.5.1` succeeded, so use `corepack pnpm` for this slice. Do not change toolchain pins.

## 4. Product / Requirement Baseline
### 4.1 Current Truth
- SoyMutDB is a scientific database, not a marketing-first site; stable identifiers, assembly/release context, source, and the external/internal boundary remain important to users.
- The current user approved a staged frontend remediation: `apps/web` first, then `apps/admin`, then `apps/jbrowse`, with separate design/implementation slices.
- The first approved slice localizes app-authored portal UI and fixes confirmed readability/scroll issues without changing route or data behavior.

### 4.2 Non-negotiables
1. Preserve stable IDs, accession values, canonical enums, assembly/release identity, and provenance.
2. Preserve external/internal site-variant isolation and existing route, auth, API, and business behavior.
3. Do not machine-translate live API/CMS free text; mark English source fallback when appropriate.
4. Do not remove intentional scrolling or clipping required by long lists, dialogs, or the embedded genome viewport.

### 4.3 Product Non-goals
- The portal UI slice does not change GoatCounter, ClickHouse, analytics collection, APIs, databases, or Admin/JBrowse route components.
- It does not globally reset typography or redesign unrelated routes.

## 5. Architecture / Runtime Boundary Baseline
### 5.1 Current Truth
- Web, Admin, and JBrowse use the React/Umi runtime; `packages/i18n-core` supplies shared en/zh catalog resources.
- Portal route components own page presentation and consume shared i18n resources; backend APIs remain authoritative for records and workflow state.
- `scripts/check_visible_i18n.py` currently scans Vue SFCs, while `scripts/verify-frontend-artifacts.sh` invokes it as the visible-i18n gate. Active React JSX coverage is missing.

### 5.2 Architecture Non-negotiables
1. Additive locale resources must preserve en/zh parity and must not create new data or runtime owners.
2. Any new React-visible-copy check belongs to the existing frontend verification contract and must add no runtime dependency.
3. Keep deployed site artifacts, service-worker namespaces, and JBrowse integration boundaries unchanged.

### 5.3 Architecture Non-goals
- No API, persistence, release, deployment, package-runtime, or routing architecture changes.

## 6. Ownership / Contract Snapshot
- Portal pages and public/internal site presentation -> `apps/web/src/routes/**`.
- Shared locale definitions -> `packages/i18n-core/src/locales/{en,zh}/common.json`.
- Visible-copy and frontend-artifact gates -> `scripts/check_visible_i18n.py`, `scripts/verify-frontend-artifacts.sh`, and `scripts/smoke.sh`.
- Admin and JBrowse shells -> their respective application owners; they are not modified in the first portal slice.

## 7. Current State and Risks
- The `/compare` source contains English UI copy, small local text styles, and a height-limited nested selector scroll region.
- Other source-audited portal routes contain English literals or incomplete localization; the sequence-extraction screenshot's apparent panel clipping is not yet reproduced at runtime.
- Some audit findings are source-confirmed; viewport-only behavior must be verified before calling it a defect.

## 8. Alignment Use
- Read the Product / Requirement Baseline for UI scope, localization behavior, and data-preservation decisions.
- Read the Architecture / Runtime Boundary Baseline before changing route owners, shared locales, or verification scripts.
- Report any change to IDs, route/auth/API behavior, site-variant visibility, or data ownership as scope drift requiring review.

## 9. Compatibility Boundary
- Keep existing routes, query parameters, API contracts, auth gates, site-variant boundaries, search behavior, comparison selection, chart data, and analysis workflows unchanged.
- Preserve source/canonical biological values; localize only the display layer.
