# Public Portal UI Quality Remediation Implementation Plan

## Goal and parent

Implement the approved first slice from [the portal UI design specification](../../superpowers/specs/2026-09-28-portal-ui-quality-remediation-design.md). This slice repairs the confirmed localization/readability issues in the active `apps/web` React/Umi portal. The parent objective still covers Admin and JBrowse, but each receives a separate design and plan after this slice.

## Change necessity

Code changes are necessary: adding keys alone cannot change hardcoded JSX, and changing the capped `/compare` selector requires a route layout change. A source guard is also necessary because the current visible-copy gate scans Vue files, not the React files that ship.

## Scope fence

- Change only active portal presentation, shared locale entries needed by this slice, and its existing verification owners.
- Preserve route paths, query parameters, selection state/URL sync, search and analysis workflows, APIs, auth, site variants, chart data, and biological values.
- Do not modify Admin/JBrowse route components, backend/data stores, GoatCounter, analytics collection, or retired Vue source.
- Do not globally reset typography. Do not alter `seqfetch` layout unless the screenshot's apparent clipping is reproduced.
- Leave the pre-existing dirty `.ai-memory/handoff.md` and untracked `e2e/probe-search-input.mjs` untouched and unstaged.

## Baseline and readiness

- TaskStartSnapshot at plan time: branch `main`, HEAD `967edbab`; the approved design is committed, no application source has changed. Before the first implementation edit, capture a fresh `git status --short` and confirm the two unrelated pre-existing paths above remain unchanged.
- Active runtime is React/Umi. The old visible-copy script enumerates only `*.vue`; the canonical frontend verification script already invokes it. Locale parity checks catalog shape, not JSX call sites.
- Canonical owners: portal routes in `apps/web/src/routes/**`; locale resources in `packages/i18n-core/src/locales/{en,zh}/common.json`; visible-copy/artifact verification in `scripts/`.
- `apps/web/src/lib/i18n.ts` also contains existing app-local `EXTRA_RESOURCES`. This plan follows the approved design's shared-catalog owner for new keys; preserve existing extras and do not duplicate newly added keys across both sources.
- Readiness: approved scope and acceptance are unambiguous. Source-confirmed issues may be fixed; screenshot-only clipping must be reproduced before changing layout.
- Toolchain discrepancy: `AGENTS.md` says pnpm 11.21.0, but authoritative `.cnb.yml` and root `package.json` both specify `pnpm@12.5.1`; treat the `AGENTS.md` row as stale. The global pnpm launcher emitted `[ERROR] unable to open database file`; `COREPACK_ENABLE_NETWORK=0 corepack pnpm@12.5.1 --version` succeeded. Use `corepack pnpm` for this slice; do not change pins.
- No root `CONTEXT.md` was found. No semantic terminology change is in scope.
- Implementation-start snapshot: `main` at `967edbab1`, upstream `cnb/main` has 0 commits ahead / local branch is 255 commits ahead; no staged or unmerged paths and no active merge/rebase/cherry-pick. Existing validation worktrees, including two marked prunable, are left untouched. The worktree contains the two pre-existing unrelated paths plus this task's new uncommitted Aegis docs; no app source has been modified.

## TDD Route

- Mode: `off`.
- Decision: `skipped` (no strict RED/GREEN choreography).
- Authority: current runtime context explicitly sets Aegis TDD mode to off; the user approved behavior and regression acceptance, not strict test-first TDD.
- Test posture: for each confirmed bug, add a minimal failing regression where the existing harness supports it, then apply one focused fix and verify; this follows systematic debugging without imposing strict RED/GREEN refactor choreography.
- Reason: this is a user-visible repair with source/screenshot evidence; the approved plan requires route, copy-guard, locale, and responsive verification while the runtime explicitly disables strict TDD.

## Existence Check — React visible-copy guard

- Proposed surface: active React/JSX visible-copy scan.
- Existing owner / reuse candidate: `scripts/check_visible_i18n.py` plus its canonical invocation in `scripts/verify-frontend-artifacts.sh`.
- Why current coverage is insufficient: the Python checker scans `.vue` SFCs and its text extraction is Vue-template-specific; there is no JSX scan in the repository.
- Creation proof: current active portal components are `.tsx`; the approved audit found hardcoded visible English there. Root TypeScript is already a development dependency, so a TypeScript-AST companion needs no runtime dependency.
- Entropy / retirement: add one small source-only checker (not a runtime package), reuse the existing baseline JSON and frontend gate, and retain the Vue scanner only while legacy Vue files remain. No new public contract or runtime owner is created.
- Minimality reference: `docs/current/AEGIS_MINIMALITY_REFERENCE.md` is absent from both the target checkout and installed Aegis pack (confirmed by path search). Direct source evidence establishes the gap; use the existing frontend gate and TypeScript dependency rather than adding a separate package or a second baseline owner.
- Decision: `add-with-proof`, bounded to the existing visible-i18n verification contract.

## Complexity and architecture review

**Complexity Budget**
- Artifact classes: source, test/verification, plan.
- Target owners: a small TypeScript-AST check, existing frontend gate/baseline, the affected portal route files, and two shared locale catalogs.
- Current pressure: multiple route files share the same locale resources; the existing scanner has no React support.
- Projected pressure: within budget; no runtime package, API, schema, or design-system migration is added.
- Governance: keep the checker source-only and conservative, add a self-test fixture, localize only audited route UI, and avoid unrelated refactors.

**Plan-Time Complexity Check**
- Edit intent: local fixes plus one focused development-time guard; no overloaded owner receives a new runtime responsibility.
- Better boundary: a small TSX scanner beside the existing Vue scanner is clearer than forcing TypeScript parsing into the Python Vue-template parser.
- Recommendation: add the scanner as a companion but invoke it from the existing frontend gate and share the existing visible-copy baseline.

**ArchitectureReviewRequired:** no separate ADR/architecture review. The React checker is development-only and stays under the existing frontend-verification contract; route/API/runtime owners do not change. Request a focused independent code review after implementation because the checker and shared locale resources affect multiple packages.

## Implementation tasks

Tasks are sequential and inline. They touch shared locale/baseline files and the same frontend gate, so parallel write delegation would create conflicts without reducing elapsed time.

### Task 0 — Capture implementation start state

1. Record `git status --short`, HEAD, active pnpm version, and current test availability.
2. Confirm only the known `.ai-memory/handoff.md` modification and `e2e/probe-search-input.mjs` untracked file are outside this slice; do not stage or modify them.
3. Stop if any new source change conflicts with the approved design or if the worktree shows unexpected route/data changes; re-read the current diff before proceeding.

### Task 1 — Add React visible-copy coverage to the existing gate

Files to add/change:

```text
scripts/visible-i18n-allowlist.json                   (new shared config)
scripts/check_visible_i18n.py                         (existing)
scripts/check_visible_i18n_react.mjs                  (new)
scripts/visible-i18n-baseline.json                   (existing)
scripts/verify-frontend-artifacts.sh                 (existing)
scripts/smoke.sh                                     (existing)
```

1. Move the existing technical/canonical-value allowlist into one JSON config consumed by both the Vue and React scanners; preserve the Vue scanner's current classification behavior.
2. Implement a conservative TypeScript-AST scan of JSX text and visible static attributes under `apps/web/src`; skip code-only strings and translation-key arguments, use the shared allowlist, and count/fail against the existing baseline.
3. Keep baseline entries in the single JSON file by file extension: each scanner's `--update-baseline` must preserve the other scanner's entries. Add `--self-test` fixtures for JSX text, visible static attributes, translation calls, canonical identifiers, and cross-extension baseline preservation.
4. Invoke the React self-test and scan from the existing frontend verification path; invoke its self-test from the contracts smoke layer. Do not add workflow-local logic.
5. Triage every hit under the active portal route tree as UI copy, canonical technical vocabulary, or record/source data. Fix all confirmed app-authored UI copy in this portal slice, not only the initially listed routes; use non-zero baseline entries only for explicitly documented canonical/data values. Fixed route UI counts must reach zero.
6. Verify the old Vue self-test and baseline behavior are unchanged.

Checks: `node scripts/check_visible_i18n_react.mjs --self-test`, `node scripts/check_visible_i18n_react.mjs`, `python3 scripts/check_visible_i18n.py --self-test`, `python3 scripts/check_visible_i18n.py`, and `bash scripts/smoke.sh --profile contracts`.

### Task 2 — Localize and uncap `/compare`

Files to change/test:

```text
apps/web/src/routes/compare.tsx
apps/web/src/lib/compare-data.ts
packages/i18n-core/src/locales/en/common.json
packages/i18n-core/src/locales/zh/common.json
apps/web/src/routes/compare.test.tsx                 (new if existing route harness supports it)
```

1. Route all app-authored headings, controls, field labels, helper/error/empty copy, chart captions, and accessibility text through bilingual keys.
2. Move project-authored curated phenotype descriptions from the English-only `CompareVariant.phenotype` display field into bilingual locale keys keyed by the existing immutable variant ID; remove that field after confirming it has no other consumers. Preserve record IDs, genes, accession-like values, species/cultivar names, raw enum values, and comparison behavior.
3. Replace the capped nested selector with the approved full-width responsive card grid in normal document flow. Keep selection limit, selected states, URL synchronization, cards, comparison table, and chart behavior.
4. Make primary content readable and preserve compact canonical metadata where useful.
5. Test all curated choices are reachable, selection behavior is unchanged, and both locales render the correct labels without raw keys.

### Task 3 — Repair confirmed portal localization/readability issues

Files in the audited surface:

```text
apps/web/src/routes/search.tsx
apps/web/src/routes/sra.tsx
apps/web/src/routes/analytics.tsx
apps/web/src/routes/analyses/index.tsx
apps/web/src/routes/analyses/fastp.tsx
apps/web/src/routes/analyses/scanpy.tsx
apps/web/src/routes/browser.tsx
apps/web/src/routes/news/$slug.tsx
packages/i18n-core/src/locales/en/common.json
packages/i18n-core/src/locales/zh/common.json
```

1. Localize app-authored visible copy, empty/loading/error states, buttons, helper text, titles, and accessibility labels in both languages.
2. `/search`: make important result descriptions readable by wrapping or explicit reveal; keep identifiers, search-source names, and record data canonical.
3. `/sra`: increase primary row/action readability; add a count/scroll cue while retaining a scroll region only for a genuinely long list.
4. `/analytics` and `/analyses/*`: localize descriptions, demo notice, retry/error/empty states without changing charts, API requests, or job workflows.
5. `/browser`: localize only the missing-context state; preserve explicit assembly/release requirements and embedded viewer ownership.
6. `/news/$slug`: when Chinese article text is unavailable and English is displayed, add a localized notice; do not machine-translate content.
7. Add focused React tests for representative Chinese/English rendering and update the guard baseline so fixed route files have no user-facing untranslated hits.

### Task 4 — Verify sequence-extraction layout before touching it

1. Check whether an existing portal preview/browser target is available. The DSH GUI at port 3080 is not a substitute for this application's preview.
2. Test the screenshot viewport plus 375, 768, 1024, and 1440 CSS-pixel widths. If the result panel remains within the viewport, make no layout change. If clipping is reproduced, fix only the responsible grid/min-width rule and add a regression check.
3. Do not start a replacement local server without user approval. If no suitable preview exists and runtime screenshots are necessary, ask before starting one.

### Task 5 — Final verification and review

Run, as available:

```bash
node scripts/check_visible_i18n_react.mjs --self-test
node scripts/check_visible_i18n_react.mjs
python3 scripts/check_visible_i18n.py --self-test
python3 scripts/check_visible_i18n.py
corepack pnpm --filter @soymutdb/i18n-core check:locale-keys --self-test
corepack pnpm --filter @soymutdb/i18n-core check:locale-keys
corepack pnpm --filter @soymutdb/i18n-core test
corepack pnpm --filter @soymutdb/web test
corepack pnpm --filter @soymutdb/web lint
corepack pnpm --filter @soymutdb/web typecheck
corepack pnpm --filter @soymutdb/web build
```

- Run responsive browser checks only against a confirmed portal preview; if unavailable, report that verification as pending and ask before starting a server.
- Run `git diff --check`, review the complete diff for boundary changes, and run the focused independent code review.
- Do not claim visual acceptance from source inspection or a build alone.

## Acceptance mapping

- Bilingual visible-copy and no raw-key checks -> Tasks 1–3 and locale/route tests.
- Full-flow `/compare` choices and preserved selection/URL behavior -> Task 2 and responsive checks.
- Readable/wrappable search and intentionally scrollable SRA list -> Task 3.
- Conditional `seqfetch` layout correction -> Task 4 only if reproduced.
- No route/API/auth/data/site-variant changes -> diff review and portal build.
- Admin/JBrowse and GoatCounter remain separate parent-goal slices.

## Compatibility, rollback, and retirement

- All production changes are presentation/resource changes; existing APIs, routes, state behavior, and site-variant boundaries remain unchanged.
- Roll back a UI subtask by reverting only its route/catalog/test changes. Roll back the guard by removing its gate invocation and companion scanner while retaining the existing Vue check; no persistent data migration is involved.
- Keep the existing Vue scanner active for retained legacy Vue files. Do not retire it in this portal slice.

**Anti-Entropy Declaration — curated phenotype display copy**
- Deletion class: `code-retirement`.
- Old path: the English-only `CompareVariant.phenotype` field in the local curated comparison dataset.
- Invalid responsibility: storing app-authored display prose as a single-locale data value.
- New canonical owner: shared `compare.curated.phenotypes.<variant-id>` en/zh locale entries.
- Preserved behavior: exact variant IDs and all biological/canonical fields, selection, comparison rows, and chart calculations.
- Retired behavior: rendering the English-only description directly from the data object.
- External boundary: no. Persistent/source-of-truth data risk: none; this is a local static UI dataset.
- User confirmation required: no; the approved design explicitly localizes these project-authored descriptions.
- Retirement decision: `delete-first`; remove the field only after confirming the route is its only consumer, then verify there are no remaining references.

## Parent-requested follow-on QA (separate from this web slice)

After the approved UI remediation slices for Web, Admin, and JBrowse are complete:

- Enumerate every active/published route from each app's route manifest and capture at least desktop and mobile screenshots per route. Triage each screenshot for localization, density, clipping, horizontal overflow, and broken empty/error states; fix confirmed findings through the owning app's approved slice and re-capture.
- Exercise all active Admin functions, including authenticated CRUD/content flows, news upload/preview/publish, media upload where used, database package upload/import, validation, release/publish, audit visibility, and safe cleanup. Record outcomes per workflow; do not infer passing from a successful page load.
- All write workflows must use an isolated local/test environment, dedicated test account, and synthetic fixture data. Never upload, publish, import, or delete against production. If no isolated environment exists, stop and ask for the target environment and authorization before creating services or performing writes. Do not request secrets in chat; use the approved environment's secret mechanism.
- This follow-on spans Admin/JBrowse and data-import workflow contracts, so create separate app/QA specs and plans before implementation; it is not silently folded into the current `apps/web` plan.

## Execution readiness and drift rules

- Intent lock: repair confirmed English, density, and nested-scroll defects across the active portal.
- Scope fence: `apps/web` only, plus shared locale keys and the existing frontend verification contract.
- Baseline lock: use the approved design and current source/route evidence; do not infer viewport bugs from code alone.
- Approved behavior: bilingual UI, readable content, expanded comparison choices, canonical scientific data preserved.
- Compatibility/retirement: routes, API/auth/data/site variants unchanged; keep the Vue checker until its source owner is retired.
- Review gates: focused code review after Tasks 1–4; user visual review if a preview is available.
- Drift / rewind: stop if a fix needs an API/data change, introduces a new runtime dependency, alters internal/public identity handling, or requires redesigning an out-of-scope route. Return to the design/user before expanding.
- Evidence required: exact commands and results, source diff, and responsive screenshots or an explicit `needs-verification` note.
- State carrier: inline checkpoint via the active goal/todo list; no per-slice work record.

## Execution route

- Decision: `inline`.
- Evidence: route tasks share the same locale catalogs, visible-copy baseline, and portal verification gate; sequential integration is safer than parallel ownership.
- Fallback: if a distinct independent task emerges, reconsider only after checking its write scope and dependency boundary.
- User confirmation required: no for code within this approved slice; yes before starting any new local preview server when no existing target is available.
