# Admin-Editable Footer, Public Search, and Typography Implementation Plan

Aegis Visibility: This durable plan is warranted because the slice crosses versioned persistence, a public API/variant boundary, shared Admin/Web consumers, and visual/performance checks that require an unavailable preview environment.

## Goal

Implement the user-approved slice in [the design specification](../../superpowers/specs/2026-09-28-admin-editable-footer-search-font-design.md): an editable bilingual footer with grouped navigation, better public catalog search controls, and a Regular-only HarmonyOS font on the active public React site.

## Architecture

- Persistence owner: the existing variant-specific, versioned `system_settings` documents (`footer_external` and `footer_internal`). No new table, migration, or second content store.
- Footer schema/validation owner: one small `apps/api/app/core/footer_content.py` module for the bounded JSON configuration, safe URL/contact validation, and parse/default helpers. The large generic registry remains the registration/wiring owner only.
- Public contract owner: `GET /api/v1/site/footer`, with an additive typed response; legacy fields and authorization/cache behavior remain.
- Admin owner: a focused editor component composed by the existing Settings route; it edits the versioned settings document, not the public API directly.
- Public UI owner: active React `SiteFooter` and `/search` route. The header navigation remains code-owned and independent from footer links.
- Font owner: active public React `apps/web/src/index.css`; no Admin, JBrowse, or legacy Vue font changes.

## Tech stack

FastAPI/Pydantic, versioned SQLAlchemy `SystemSetting` revisions, TypeScript/React, Ant Design, TanStack Query/Router, shared English/Chinese i18n resources, Vitest, pytest, and the existing OpenAPI client generator. No new runtime dependency.

## Baseline and authority references

- Approved feature requirements and acceptance: `docs/superpowers/specs/2026-09-28-admin-editable-footer-search-font-design.md`.
- Existing Web localization/readability boundary: `docs/superpowers/specs/2026-09-28-portal-ui-quality-remediation-design.md` and `docs/aegis/plans/2026-09-28-portal-ui-quality-remediation.md`. This plan is separate and extends neither plan's scope silently.
- Normative biological search/variant contract: `docs/dev/database-core-contract.md`.
- Repo rules and safety: `AGENTS.md`, `docs/aegis/BASELINE-GOVERNANCE.md`, and `docs/aegis/baseline/2026-09-28-initial-baseline.md`.
- Current source owners: `apps/api/app/core/settings_registry.py`, `apps/api/app/services/settings_service.py`, `apps/api/app/api/v1/site.py`, `apps/api/app/schemas/site.py`, `apps/admin/src/routes/settings.tsx`, `apps/web/src/components/site-footer.tsx`, `apps/web/src/routes/search.tsx`, `apps/web/src/index.css`, `packages/api-client/src/site.ts`, and `packages/i18n-core/src/locales/{en,zh}/common.json`.
- No `CONTEXT.md` or `CONTEXT-MAP.md` was found at the repository root. The minimality reference `docs/current/AEGIS_MINIMALITY_REFERENCE.md` is absent; the current settings store, endpoint, and source layout provide direct reuse evidence.

Plan-time snapshot: branch `main`, HEAD `967edbab1`. The worktree already contains edits for the separate approved Web localization slice, including `apps/web/src/routes/search.tsx`, both shared locale files, route tests, and scanner scripts, plus unrelated `.ai-memory/handoff.md` and `e2e/probe-search-input.mjs`. Before source edits, capture a fresh snapshot and review the current diff. Preserve all existing dirty/untracked paths; do not stage or commit.

## Compatibility boundary

- Search continues to use the existing `/search` request/response contract, route parameters, release/assembly context, result IDs, provenance, and external/internal behavior. This slice adds controls only where the current API supports them.
- `GET /site/footer` is additive. Keep the existing single-value response keys and stored keys for compatibility; do not change external cache headers, internal authorization, or `private, no-store` behavior.
- The committed OpenAPI snapshot predates unrelated current API changes; full regeneration also changes existing search/release/identity contracts. This slice merges only the new footer response and navigation schemas into the committed snapshot, regenerates client types from that scoped snapshot, and records the remaining full-snapshot drift separately. Do not propagate unrelated generated API changes or claim global snapshot parity.
- Store the grouped navigation JSON in the existing settings version/audit system. The public endpoint returns parsed typed navigation, never the raw JSON string.
- Keep the external footer and internal footer in separate explicit settings namespaces. Do not derive the site variant from host, cookies, or user-agent.
- Preserve ClickHouse search/component/Web Vitals history and all other telemetry. GoatCounter/AntV work is a separate approved slice, not part of this plan.
- No production setting write, live Admin E2E, publication, import, or deletion is permitted in implementation tests.

## Verification summary

Use synthetic fixtures and mocked API/database tests for local implementation. Run focused API, Admin, Web, API-client, locale, build, and artifact-isolation checks. Build both Web site variants. Record rather than conceal the existing React visible-copy backlog. Published-route screenshots, font LCP/CLS measurement, and Admin save-to-public-render E2E remain `needs-verification` until a SoyMutDB preview URL and an isolated writable Admin test environment are supplied. Never treat `http://127.0.0.1:3080` as the SoyMutDB preview or start a replacement server without explicit approval.

## Change necessity

Code is necessary: Admin already writes a few single-value footer strings, but the active React footer intentionally hides the personal contact values and has no navigation renderer; the public search page does not expose existing type/assembly/cursor capabilities; and the active React stylesheet does not use the selected local font. Documentation or configuration alone cannot implement these behaviors. The minimum code boundary is the existing versioned footer settings owner/API, a focused Admin editor, the active React footer/search components, shared locale keys, and the active React font declarations.

## Requirement Ready Check

- Requirement source: the approved design specification linked above and the current user's goal.
- User scenarios: Admin edits either explicit site variant; a public visitor sees locale-appropriate footer values and navigation; a researcher filters and pages catalog results without losing release/assembly context.
- Acceptance evidence: API/schema tests, settings version/audit tests, Admin and Web component/route tests, OpenAPI/client generation, external/internal builds and boundary checks, locale parity, and later preview-based visual/Admin E2E checks.
- Open blocker questions for code: none. Live Admin writes/screenshots are intentionally deferred until their required environments are provided.
- Decision: `ready` for the approved footer/search/font slice; the broader Admin redesign, JBrowse audit, GoatCounter migration, and AntV dashboards remain separate future slices.

## TDD Route

- Mode: `off`.
- Decision: `skipped`; no strict RED/GREEN choreography.
- Authority: the current Aegis runtime explicitly sets TDD mode to off.
- Test posture: add focused regression and contract tests in the owning test suites; run them after implementation and preserve negative privacy/URL validation cases. Do not weaken, skip, or xfail a required assertion.
- Reason: user-visible/API behavior changes require strong regression checks, but TDD mode is explicitly off.
- Verification: run the narrowest API/Admin/Web/client tests first, then locale/type/lint/build/artifact checks; record exact commands and results.

## Ripple Signal Triage

This slice touches persistence validation, a public response schema, a typed client, Admin settings writes, a cached public renderer, shared locale resources, and search query-state presentation. Canonical flow is Admin editor → versioned settings API/service → `SystemSetting`/revision history → `GET /site/footer` → typed API client → active React footer. Search UI consumes the existing search and assembly APIs. The main risks are variant leakage, unsafe link schemes, loss of legacy values, stale version writes, broken assembly disambiguation, shared-locale conflict, and font-download/layout regression. The plan uses one domain validator, one existing persistence owner, additive response fields, explicit external/internal tests, and sequential locale edits.

## First-principles and Architecture Integrity Review

- First principle: researcher-facing and Admin-visible content must be editable, readable, and safe without weakening the biological search or site-variant contracts.
- Non-negotiables: no production writes; no internal/private content in the external site; no silent assembly default; preserve existing API/cache/auth behavior and telemetry history.
- Assumptions dropped: the old Vue footer is active; editable links require a new table; all three HarmonyOS weights must be downloaded.
- Smallest sufficient path: reuse the existing versioned footer settings and endpoint; validate one bounded JSON field in a focused domain module; add an Admin form component; use current search APIs/URL state; load only Regular.
- Escalation signal: a required migration/new persistence owner, unsupported API semantics, inability to keep site variants isolated, a breaking distributed client requirement, or a failed font performance gate returns to design review.

**Architecture Integrity Lens**

- Invariant: `footer_<variant>` settings remain the sole editable footer source of truth; the API is the only public read boundary.
- Responsibility overlap: the active header has static navigation, while the legacy Vue footer has an inactive static list. The footer's initial groups are a snapshot of the active header, then intentionally maintained independently. Neither header nor legacy Vue becomes a second editable owner.
- Higher-level simplification considered: making the header and footer share one editable menu was rejected because the approved scope makes the footer editable while leaving the header unchanged.
- Old-path retirement: remove the inline legacy footer form from the React Settings route after confirming it has no other consumer; retain generic settings `PUT` for other sections, legacy footer keys/API fields, and the inactive Vue footer outside this scope.
- Verdict: reuse existing persistence/API owner and add a narrowly scoped footer schema/editor owner; no new database, generic JSON framework, or search API.
- ArchitectureReviewRequired: no separate ADR; the contract/persistence boundary requires the focused independent implementation review in Task 5.

## Existence Check — structured footer configuration

- Proposed new surface: bounded bilingual footer navigation JSON plus an Admin group/link editor.
- Existing owner/reuse candidate: versioned `system_settings`/`settings_registry`, `GET /site/footer`, and the existing Settings page; Web already has `SiteFooter` and an explicit header route map.
- Why insufficient: generic scalar strings do not validate nested groups/targets; current React footer hides contacts and has no nav; the current Admin editor has only five single-value inputs.
- Creation proof: grouped editing is user-approved, safe parsing and type-specific validation are required server-side, and no new persistent owner is needed. The new `footer_content.py` module owns only this domain schema/validation; registry additions remain registration/delegation.
- Entropy/retirement: no generic JSON capability or table is added. The header remains independent; legacy API fields are retained under the compatibility exception below.
- Minimality reference: `docs/current/AEGIS_MINIMALITY_REFERENCE.md` is absent. Current code proves the existing versioned store, route, and Settings UI are the narrow reuse path.
- Decision: `reuse-existing` persistence/API plus `add-with-proof` for the bounded schema helper and focused editor component.

## Complexity Budget and Plan-Time Complexity Check

**Complexity Budget**

- Artifact classes: source, tests, OpenAPI/client contract, plan, and durable checkpoint.
- Current pressure: `apps/admin/src/routes/settings.tsx` is 1,200 lines; `apps/api/app/core/settings_registry.py` is 2,371 lines; `apps/web/src/index.css` is 1,037 lines; `apps/api/tests/test_admin_settings.py` is 912 lines. `apps/web/src/routes/search.tsx` and shared locale catalogs already have uncommitted work from the separate approved UI plan.
- Projected pressure: within budget if the form/schema are extracted into focused modules and existing large owners receive only bounded wiring. No generic JSON infrastructure, new table, runtime dependency, or unrelated refactor.
- Governance: extract the Admin footer editor to `apps/admin/src/components/SettingsFooterEditor.tsx`; put the navigation/contact validator and defaults in `apps/api/app/core/footer_content.py`; keep API registry and route edits declarative; add separate focused tests instead of growing the 912-line settings test file.

**Plan-Time Complexity Check**

- `settings.tsx`: remove its footer-specific state/load/form block and compose one component; do not append the grouped editor to this 1,200-line route.
- `settings_registry.py`: only register the new keys and delegate the domain-specific checks; no large schema/URL logic in this 2,371-line file.
- `index.css`: add one face and update the existing font variables only; no typography redesign or duplicated font stack.
- `search.tsx`: edit the existing route in place because the current component already owns query/URL behavior; first inspect and preserve its dirty localization changes.
- Recommendation: extract the cohesive Admin and API footer helpers; keep narrow Web route/CSS edits; proceed inline and sequentially.

## Implementation Tasks

Tasks are sequential because the Admin and Web editors share locale catalogs, the API/client schema must be generated before consumer typing, and the current worktree already has edits in `search.tsx` and the shared locale files.

### Task 0 — Capture implementation start state

1. Record a full `TaskStartSnapshot`: repository root, branch/HEAD, upstream divergence, staged/unstaged/untracked paths, active merge/rebase/cherry-pick state, `git worktree list --porcelain`, toolchain versions, and available test/preview environments before source changes.
2. Re-read the complete diff for `apps/web/src/routes/search.tsx` and both locale catalogs. Preserve the existing approved localization/readability changes; do not reset, overwrite, stage, or commit any current dirty/untracked work.
3. Record that the code-level API tests use mock DB sessions/synthetic values. Stop before any live Admin write or replacement server.
4. If the task now requires changing the search API, database, biological IDs, variant policy, or production values, return to design/user review.

### Task 1 — Add the bounded footer content schema and additive API response

Files to change/add:

```text
apps/api/app/core/footer_content.py                 (new schema/default/validation owner)
apps/api/app/core/settings_registry.py              (register keys and delegate validation)
apps/api/app/schemas/site.py                        (typed footer response fields)
apps/api/app/api/v1/site.py                         (parse config, preserve variant/cache/auth)
apps/api/tests/test_footer_content.py               (new focused validator tests)
apps/api/tests/test_site_footer.py                  (new route/variant/cache tests)
apps/api/tests/test_settings_registry.py            (registered values/validation)
packages/api-client/openapi.json                    (generated contract snapshot)
packages/api-client/src/generated/openapi.d.ts      (generated; never hand edit)
packages/api-client/src/site.ts                     (typed SiteFooter client)
```

1. Register bilingual contact person, address, and copyright values; shared phone/email values; and `navigation_json` in the footer base section so existing variant expansion creates isolated external/internal keys. Keep current legacy keys and defaults intact.
2. Implement schema version 1 validation/canonicalization for the bounded group/link JSON: at most 6 groups and 32 links total; bilingual group titles/link labels up to 80 characters; destinations up to 2,048 characters; serialized JSON up to 32 KiB. Require stable slug IDs, unique group IDs and per-group link IDs, nonnegative integer order, boolean enabled, reject unknown fields, and sort by order then stable ID. Internal paths must begin with exactly one `/` and contain no scheme, protocol-relative prefix, backslash, or control characters; external destinations must be absolute HTTPS URLs without credentials. Validate non-empty optional email values and allow a `tel:` target only for an allowlisted phone format, normalized to optional `+` plus digits; never alter the visible phone value.
3. Seed the built-in groups from the exact active-header path/locale catalog mapping in the approved design. Serve a structured `navigation` list and new bilingual values from `/site/footer`; never expose the stored JSON string. Preserve all old response keys and cache/auth headers. Use the built-in default groups for missing or invalid stored navigation, sort by order then ID, omit disabled groups/links, and log only a sanitized diagnostic for invalid reads.
4. Keep versioned settings writes/audits and optimistic concurrency. No migration or live data rewrite.
5. Add negative tests for malformed JSON, extra fields, invalid schema version, excessive counts/lengths, `javascript:`, `data:`, `http:`, `//host`, userinfo, and unsafe phone/email values. Test public external cache headers, anonymous internal 401, authorized viewer internal `private, no-store`, and external/internal values never crossing.
6. Export current OpenAPI, merge only `FooterContentResponse`, `FooterNavigationGroup`, and `FooterNavigationLink` into the pre-existing contract snapshot, then regenerate the client types from that scoped snapshot through Corepack. Never hand-edit generated TypeScript or propagate unrelated search/release/identity drift.

Checks: API focused pytest + Ruff; scoped OpenAPI/client generation; `scripts/contract_visibility.py` against the preserved contract snapshot; API-client typecheck. Record full-source snapshot parity as pre-existing drift, not a pass.

### Task 2 — Extract and implement the Admin footer editor

Files to change/add:

```text
apps/admin/src/routes/settings.tsx                 (remove old inline footer owner; compose component)
apps/admin/src/components/SettingsFooterEditor.tsx  (new focused editor)
apps/admin/src/components/SettingsFooterEditor.test.tsx (new UI tests)
packages/i18n-core/src/locales/en/common.json       (Admin labels/help/validation)
packages/i18n-core/src/locales/zh/common.json       (matching Chinese keys)
```

1. Replace the old inline five-field footer card/state/GET/PUT block with the extracted editor, preserving Settings card visibility and the explicit external/internal selector.
2. Load `footer_external`/`footer_internal` through `adminSettingsApi.get`; save with `adminSettingsApi.patch` and the expected version. Reuse the existing `admin-settings-schema` query to obtain the registered `navigation_json` default because the versioned document returns stored values only. On a stale version, show a conflict/reload message and do not silently overwrite newer content. Keep `handleSave`/legacy `PUT` for other settings sections.
3. Provide labeled bilingual inputs for contact person, address, copyright, and shared phone/email. Show existing legacy values in a clearly marked read-only fallback panel; do not prefill or machine-translate them into new language fields. New fields start from their stored values or registered defaults, and remain absent until explicitly edited.
4. Add a bilingual group/link form builder: add/remove/enable/reorder groups and links; edit bilingual titles/labels, destination kind, and destination. Show an explicit public-visibility notice for the external variant. Do not expose a raw JSON text editor.
5. Client validation mirrors the contract for fast feedback; the API remains authoritative. Patch only touched new keys (or the changed navigation JSON) so saving navigation cannot silently migrate legacy text; retain legacy values untouched.
6. Test variant switching, initial defaults/legacy draft, add/remove/reorder, bilingual edits, invalid targets, save payload/version, stale conflicts, and no save on rejected input with mocked APIs/synthetic data.

Checks: focused Admin Vitest, Admin typecheck/lint/build, and locale parity.

### Task 3 — Render the public footer and apply Regular-only typography

Files to change/add:

```text
apps/web/src/components/site-footer.tsx
apps/web/src/components/FooterNavigation.tsx          (new focused grouped-link renderer)
apps/web/src/components/site-footer.test.tsx         (new component tests)
apps/web/src/index.css                                (Regular face and current font variables only)
packages/i18n-core/src/locales/en/common.json        (footer labels)
packages/i18n-core/src/locales/zh/common.json        (matching footer labels)
```

1. Use `getSiteFooter(SITE_VARIANT)`; select bilingual values using the active language, localize labels, and prefer new values per field/language. If a new value is absent, fall back to its corresponding legacy value after removing only the recognized leading labels; if the request fails, use translated local fallbacks and omit unsafe contact links. Never machine-translate.
2. Render contact, navigation groups, address, and copyright responsively; keep primary text/links at least 14px and secondary metadata at least 12px. Use plain text and safe `mailto:` values; build a `tel:` target only from an allowlisted phone format normalized to optional `+` plus digits, without changing visible text. Use router links/origin-relative internal paths and HTTPS-only external anchors with safe `rel` attributes. Omit disabled groups/links, use translated fallback values if the request fails, and preserve public/internal query-key variant isolation.
3. Add `@font-face` for the existing `HarmonyOS-Sans-SC-Regular.woff2` only, set `font-display: swap`, system fallback, and synthesized weight behavior. Do not preload and do not request Medium/Bold. Leave the 16px/1.65 baseline and unrelated route styles unchanged.
4. Test locale switching, new and legacy values, request-failure fallbacks, disabled-link omission, invalid link suppression, phone/email href safety, variant-aware fetching, grouped link rendering, minimum text sizing, and no raw HTML interpretation.

Checks: focused Web Vitest, Web typecheck/lint, locale parity, and both external/internal site builds. Visual and Core Web Vitals measurements require the approved SoyMutDB preview; do not substitute the DSH GUI.

### Task 4 — Expose the existing catalog search controls

Files to change/test:

```text
apps/web/src/routes/search.tsx
apps/web/src/routes/search.test.tsx
packages/i18n-core/src/locales/en/common.json
packages/i18n-core/src/locales/zh/common.json
```

1. Merge on top of the existing dirty route/localization diff after Task 0 review. Keep the current query functions, canonical result types, route path, `q/types/cursor/limit/assembly/external` URL contract, release pin, and query cache dimensions.
2. Add localized type filters and counts using the existing `types` and `by_type` fields. Add an assembly selector using `getAssemblies` with the current release/variant context. When `ambiguous` is true, show per-assembly labels/counts and never silently choose `is_default`.
3. Add next/previous pagination using `next_cursor`/`has_more` and an in-memory cursor stack. An empty type selection means all current types. Sync `q`, `types`, `assembly`, `limit`, and `cursor` to the URL; changing query/type/assembly clears cursor history. A deep link at a cursor has no invented previous cursor.
4. Wrap descriptions/snippets without hiding the remaining text. Render these controls only for the public local catalog flow; do not imply they filter federated hits, and do not change internal-search behavior.
5. Extend route tests for type/count state, ambiguous results, assembly selection, URL changes, next/previous and reset behavior, long snippets, and preservation of release/ID/provenance labels.

Checks: focused route Vitest, Web typecheck/lint, and no-new-finding review for the changed JSX. The full React visible-copy scanner currently has unrelated backlog; do not claim its global gate is clean unless it actually passes.

### Task 5 — Cross-surface verification and independent review

1. Run the focused API, API-client, Admin, and Web tests and record exact counts.
2. Run locale parity, the React and Vue scanner self-tests, `git diff --check`, focused ESLint/TypeScript checks, API Ruff, and OpenAPI contract validation.
3. Build both Web variants and Admin; run the existing external/internal artifact-isolation check. Verify the footer response is additive and generated clients match OpenAPI.
4. Review the changed files against this plan, especially: no legacy response/key deletion, no unsafe navigation, no public/internal leakage, no API search contract change, no production setting write, no unrequested source or package additions.
5. Request an independent code review for the API/variant/settings boundary and the Admin/Web flow. Resolve any Critical/Important findings before declaring the code slice verified.
6. If a real SoyMutDB preview and isolated Admin test environment are later supplied, capture representative mobile/desktop screenshots, confirm only the Regular font is requested, and measure before/after LCP/CLS under identical network/viewport conditions. Use the median of at least three runs per route/viewport; pass only if LCP regression is at most 10%, CLS is at most 0.1, and CLS increase is at most 0.02. Exercise Admin save → public render with synthetic data. Otherwise record these checks as pending and keep the parent goal active.

## Verification commands

Use the repository-pinned Corepack pnpm rather than changing toolchain pins. The current repo guidance and historical plan record a mismatch between `AGENTS.md` pnpm 11.21.0 and the root/CI pin; follow the verified root/CI pin and do not edit version declarations. The focused Ruff command scopes out only the pre-existing `UP037` quoted return annotation in `app/schemas/site.py`; that unrelated baseline line is not changed.

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_footer_content.py tests/test_site_footer.py \
  tests/test_settings_registry.py tests/test_admin_settings.py -q
cd apps/api && .venv/bin/ruff check \
  --per-file-ignores 'app/schemas/site.py:UP037' \
  app/core/footer_content.py app/core/settings_registry.py \
  app/schemas/site.py app/api/v1/site.py \
  tests/test_footer_content.py tests/test_site_footer.py tests/test_settings_registry.py
PYTHONPATH=. apps/api/.venv/bin/python apps/api/scripts/export_openapi.py \
  --output /tmp/soymutdb-openapi-current.json
# Merge only FooterContentResponse, FooterNavigationGroup, and FooterNavigationLink
# from the temp export into the committed snapshot; preserve unrelated contracts.
python3 - <<'PY'
import json
import subprocess
from pathlib import Path
source = json.loads(Path("/tmp/soymutdb-openapi-current.json").read_text())
baseline = json.loads(subprocess.run(
    ["git", "show", "HEAD:packages/api-client/openapi.json"],
    check=True, capture_output=True, text=True,
).stdout)
for name in ("FooterContentResponse", "FooterNavigationGroup", "FooterNavigationLink"):
    baseline["components"]["schemas"][name] = source["components"]["schemas"][name]
baseline["components"]["schemas"] = dict(sorted(baseline["components"]["schemas"].items()))
Path("packages/api-client/openapi.json").write_text(json.dumps(baseline, indent=2))
PY
corepack pnpm --filter @soymutdb/api-client exec openapi-typescript \
  "$PWD/packages/api-client/openapi.json" \
  -o "$PWD/packages/api-client/src/generated/openapi.d.ts"
python3 scripts/contract_visibility.py \
  --schema packages/api-client/openapi.json \
  --client-root packages/api-client/src \
  --baseline packages/api-client/contract-visibility-baseline.json
corepack pnpm --filter @soymutdb/api-client typecheck
corepack pnpm --filter @soymutdb/admin exec vitest run src/components/SettingsFooterEditor.test.tsx
corepack pnpm --filter @soymutdb/admin typecheck
corepack pnpm --filter @soymutdb/admin lint
corepack pnpm --filter @soymutdb/admin build
corepack pnpm --filter @soymutdb/web exec vitest run \
  src/components/site-footer.test.tsx src/routes/search.test.tsx
corepack pnpm --filter @soymutdb/web typecheck
corepack pnpm --filter @soymutdb/web lint
corepack pnpm --filter @soymutdb/web build
node scripts/check_visible_i18n_react.mjs --self-test
python3 scripts/check_visible_i18n.py --self-test
bash scripts/verify-frontend-artifacts.sh
python3 -m unittest scripts.test_site_artifact_isolation -v
git diff --check
```

On this host, `corepack pnpm --version` resolves 12.5.1, while the unqualified global launcher at `~/.local/share/pnpm/bin/pnpm` fails with `unable to open database file`; both API-client shell wrappers invoke that unqualified launcher. Do not change toolchain pins or global package-manager state. Use the scoped export/merge/generation procedure above. A full-source `check:contract` remains blocked by pre-existing unrelated snapshot drift (including search/release/identity contracts); do not absorb that drift into this footer slice.

## Compatibility, rollback, and Anti-Entropy Declaration

- Internal code retirement: delete the old inline footer state/load/form from `settings.tsx` once references confirm it is only used by that card. Preserve the generic Settings `PUT` compatibility API because other settings or clients may still use it; the new footer editor alone moves to versioned `get`/`patch`.
- External API compatibility exception: retain the five legacy footer response keys and setting values. The active React footer prefers new bilingual values and uses a bounded read fallback to legacy values. Do not remove legacy fields, rewrite stored values, or add a background migration in this slice.
- Retirement trigger for legacy footer fields/fallback: a future user-approved contract version/deprecation task must first inventory distributed consumers, migrate/review existing values for both variants, and prove the legacy fallback is no longer needed. Unknown public consumers are not evidence that removal is safe.
- Retain the old Vue footer source outside this active React slice; it is not used as the new configuration source. The active React footer navigation is owned by the versioned footer setting, independent of the code-owned header.
- No database migration means application rollback is code-only. If an Admin later writes new settings in a live deployment, rollback must leave those values/revision history untouched; never delete settings as part of code rollback.

## Acceptance mapping

- Bilingual contact/copyright and grouped editable navigation → Tasks 1–3; API, Admin, and public component tests.
- Public/internal variant isolation and URL safety → Tasks 1–3 and negative API/UI assertions.
- Type filters, ambiguous assembly presentation, cursor pagination, wrapped snippets → Task 4 route tests; database-core contract remains unchanged.
- HarmonyOS Regular-only behavior and fallback → Task 3 build/network check; performance acceptance remains pending until same-origin preview metrics exist.
- No production writes, no schema migration, no search API change, no lost telemetry history → Tasks 0/1/5 diff and boundary review.

## Execution Readiness View

- Intent Lock: implement only the approved footer/search/font slice.
- Scope Fence: `apps/api`, `packages/api-client`, `apps/admin`, active `apps/web`, and required shared locale/test owners; not JBrowse, GoatCounter, or AntV.
- Baseline Lock: new approved design supersedes the older Web-only exclusions only for this slice; existing search localization changes are preserved.
- Approved Behavior: editable per-variant footer; public API is additive; public catalog filters/pagination use existing contracts; Regular-only public font.
- Owner/Contract Constraints: one existing settings store, explicit site variants, API as public projection, immutable search/ID/assembly semantics.
- Compatibility Boundary: keep legacy footer API/settings; keep generic settings PUT; no telemetry/history changes.
- Retirement Boundary: remove only the duplicate inline footer UI; retain the legacy external contract until a future confirmed deprecation.
- Task Batches: snapshot → backend/schema/client → Admin → public footer/font → search UI → verification/review.
- Test Obligations: synthetic settings only; API security/cache, form conflicts, route state, locale parity, dual builds, artifact isolation, and code review.
- Review Gates: independent API boundary review; no visual/performance/Admin E2E claim without the named preview and isolated environment.
- Drift/Rewind Rules: stop and return to design if a migration/new authority, search endpoint change, variant relaxation, internal-ID exposure, production write, or new dependency becomes necessary. Revert only this slice's source files; keep any later settings/revision data intact.
- Evidence Required Before Completion: exact test/build output, generated OpenAPI/client diff, reviewed source diff, and either screenshots/LCP/CLS/Admin E2E or an explicit `needs-verification` record.
- Advisory Boundary: this plan is execution guidance, not a GateDecision, PolicySnapshot, or completion authority.

## Plan Pressure Test

- Owner/contract/retirement: passes; existing versioned settings and site endpoint remain canonical; additive contract is explicit; only the old inline UI is retired.
- Architecture integrity/higher-level path: passes; one domain schema and one persistence owner are simpler than tables, HTML, or a generic JSON framework; header editing remains out of scope.
- Verification scope: passes for code-level tests/builds; live visual/metrics/E2E are explicitly externalized until authorized environments exist.
- Task executability: passes; tasks are ordered by schema/client and shared-locale dependencies, with exact owners and checks.
- Pressure result: `proceed`.

## Execution Route

- Decision: `inline`.
- Evidence: the API contract, Admin and Web consumers, shared locale files, and pre-existing dirty search route require sequential integration; parallel writing would risk stale shared state.
- Fallback: reconsider delegation only if a later independently scoped slice has disjoint owners and a clear verification boundary.
- User confirmation required: no for code/tests using mocks and synthetic data; yes before any live Admin write, new preview server, or claim of published-route verification.
