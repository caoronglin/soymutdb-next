# Public Portal UI Localization and Layout Remediation Design

**Status:** Design and written specification approved by the user; committed as `967edba`.

**Date:** 2026-09-28
**Parent objective:** Remediate confirmed UI localization/readability issues across all three frontends in separate app-specific phases. This specification covers only the first `apps/web` phase.

## 1. Context and root cause

The supplied screenshots identify the portal's `/compare` page and the sequence-extraction page. A read-only source audit also found similar user-visible issues elsewhere in the portal, Admin, and JBrowse.

The strongest systemic cause is that the currently shipped frontends use React/Umi, while `scripts/check_visible_i18n.py` only scans `.vue` files. It therefore does not see hardcoded JSX copy in the active route components. Locale-key parity checks ensure that `en` and `zh` catalogs have matching shapes, but do not establish that rendered route copy uses those keys.

On `/compare`, English literals are rendered even though the route calls `useTranslation()`; the hook result is discarded. The selector is constrained to `70vh` and uses a nested scrolling region, making the list look folded. Several labels and metadata use 10–12px styles. The global portal body baseline itself is 16px with a 1.65 line height, so remediation should be page-specific rather than a global font reset.

Other confirmed portal surfaces include hardcoded copy on `/search` and `/sra`, English fragments on `/analytics` and `/analyses/*`, an English browser missing-context state, and news detail fallback to English when Chinese content is absent. The SRA curated list remains reachable through intentional scrolling; the sequence-extraction page already uses translations, but its screenshot suggests that the result panel may be clipped at the shown viewport and requires runtime confirmation.

## 2. Scope

### In scope

- Active shipped React/Umi routes in `apps/web` only.
- Confirmed user-visible localization and readability issues in:
  - `/compare`
  - `/search`
  - `/sra`
  - `/analytics`
  - `/analyses`, `/analyses/fastp`, and `/analyses/scanpy`
  - `/browser` missing-context state
  - `/news/$slug` when Chinese article fields are absent
- Recheck `/tools/seqfetch` at the screenshot viewport and the existing responsive breakpoints; change its layout only if clipping/overflow is reproduced.
- Add regression protection for visible React/JSX copy and route language behavior.

### Out of scope

- Admin/JBrowse route and component changes; those apps remain in the parent objective and receive their own designs and implementation phases. The shared `packages/i18n-core` catalogs may receive only the keys required by this portal phase; unrelated Admin/JBrowse copy is not changed here.
- Retired Vue routes and source files that are not in the shipped React import graph.
- API, database, analytics collection, GoatCounter, authentication, authorization, route paths, query parameters, site-variant boundaries, and business behavior.
- Machine translation of live API/CMS free-text or changes to canonical biological data.

## 3. Design

### 3.1 Localization behavior

- All app-authored page labels, headings, helper text, buttons, loading/empty/error states, and accessibility text on the in-scope routes use the existing `@soymutdb/i18n` / `packages/i18n-core` English and Chinese catalogs.
- Add missing keys to both catalogs and preserve their key parity. English mode continues to show English; Chinese mode shows Chinese for app-authored interface copy.
- In `/compare`, project-authored curated-example descriptions and display labels may have localized presentation strings. Keep record IDs, gene symbols/IDs, accessions, species/cultivar names, assembly/release identifiers, and raw API enum values unchanged. Controlled enum display captions may be localized, while their canonical values remain intact for data and logic.
- For live article/API free-text that has no Chinese translation, do not machine-translate or alter its source. When `/news/$slug` falls back to English in Chinese mode, display a localized notice that the English original is being shown.

### 3.2 Layout and readability

- `/compare` becomes a full-width responsive selection-card grid followed by the selected-record summary and comparison table/chart. All curated choices remain visible in normal document flow; remove the nested `70vh` scroll constraint. Retain the current selection limit, selected-state behavior, URL synchronization, comparison contents, and chart behavior.
- Make primary labels and descriptions comfortably readable (normally at least 14px); secondary metadata may remain smaller but should not fall below 12px without a specific data-density reason. Use existing spacing/design tokens rather than changing global typography.
- `/search`: localize interface and state copy; allow important result descriptions/snippets to wrap or provide an explicit reveal affordance instead of silently hiding them on one line. Keep IDs, source names, and technical result values canonical.
- `/sra`: localize interface copy, improve sidebar row/action readability, and add a count or visible scroll cue for the curated-run list. Keep the list scrollable if its runtime length warrants it; scrolling is not treated as data loss.
- `/analytics` and `/analyses/*`: localize banners, chart descriptions, actions, empty/error states, and visible instructions without changing chart data or job workflows.
- `/browser`: localize the missing-context state while preserving the requirement for explicit assembly and published release context.
- `/tools/seqfetch`: first reproduce the screenshot's apparent right-panel clipping at 375, 768, 1024, 1241, and 1440 CSS-pixel widths. Fix only the responsive grid/min-width issue if confirmed; its current translation behavior is retained.

### 3.3 Regression protection

- Add a conservative React-visible-copy guard for active portal TSX/JSX. It should inspect rendered JSX text and user-visible static attributes (for example `placeholder`, `title`, `aria-label`, and `alt`), while excluding code-only strings and allowlisted canonical technical vocabulary. The existing Vue scanner remains valid for legacy source but is not treated as coverage for React.
- Add or extend route/component tests to verify representative in-scope pages in `zh` and `en`, including that fixed routes do not render raw translation keys or app-authored English in Chinese mode.
- Add responsive checks for `/compare`, `/search`, `/sra`, and `/tools/seqfetch`; confirm no document-level horizontal overflow, no clipped controls, all compare choices are reachable, and only intentionally long lists use their own scroll region.

## 4. Invariants

- Preserve external/internal site-variant separation and all public/internal identifier boundaries.
- Preserve API requests/responses, route paths, deep links, search parameters, selection behavior, authentication, job submission, chart data, and release/assembly context.
- Do not translate scientific identifiers or change biological records to make labels appear localized.
- Do not remove intentional viewport clipping from the embedded JBrowse genome visualization or intentional scrolling from genuinely long lists/dialogs.
- Do not modify unrelated pages merely because they use a compact metadata style; changes must correspond to a reproduced or source-confirmed usability issue.

## 5. Acceptance criteria

1. In both supported languages, the in-scope app-authored UI copy is localized; there are no raw missing-key strings on the covered routes.
2. The React visible-copy guard covers shipped `apps/web` TSX/JSX and prevents new unreviewed hardcoded prose from entering active portal pages.
3. `/compare` displays all curated choices in normal page flow without a nested capped selector, retains selection/URL behavior, and remains usable at 375, 768, 1024, 1241, and 1440px.
4. Search descriptions are not silently truncated without a user-visible way to read them; the SRA list remains reachable and communicates when it scrolls.
5. `/tools/seqfetch` is visually checked at the same breakpoints; any layout change is made only if its apparent clipping is reproduced.
6. Route/auth/API/data/site-variant contracts remain unchanged.
7. `apps/web` tests, lint, typecheck, and build pass; locale-key parity and the new visible-copy guard pass. Exact commands and outcomes will be recorded in the implementation handoff.

## 6. Rollout and verification limits

This is a design for a single app-specific slice. After the user reviews and approves this written specification, an implementation plan will be prepared. Runtime screenshots/tests are required for responsive claims; source inspection alone is not sufficient to mark the sequence-extraction panel or other viewport-only behavior fixed. The Admin and JBrowse phases will be specified separately before their implementation.
