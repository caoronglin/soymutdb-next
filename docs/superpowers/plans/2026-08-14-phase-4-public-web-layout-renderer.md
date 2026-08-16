# Public Web Layout And Builder Renderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the approved seven-page public layout from safe PageDefinitions while preserving the existing visual system and specialized JBrowse 2 and BLAST behavior.

**Architecture:** Add a typed public component renderer that maps registry keys to existing React components. Seed the approved layout as the default definition, then refactor existing routes to consume URL-backed query state and builder configuration without moving scientific query logic into editable content.

**Tech Stack:** React 19, Vite, TanStack Router/Query, Ant Design, i18next, Vitest, Playwright.

---

## File Structure

- Create `apps/web/src/page-builder/registry.tsx`, `renderer.tsx`, `types.ts`, and component adapters.
- Create `apps/web/src/page-builder/__tests__/renderer.test.tsx`.
- Modify `apps/web/src/components/site-header.tsx`.
- Rewrite the composition in `apps/web/src/routes/index.tsx` while reusing `NewsCarousel` and sanitized content APIs.
- Modify `apps/web/src/routes/search/genes.tsx`, `location.tsx`, `blast.tsx`, `gbrowse.tsx`, and `primer.tsx`.
- Modify `apps/web/src/routes/blast.tsx` only where needed to accept direct entry and result cross-links.
- Modify i18n resources under `packages/i18n` to replace GBrowse labels with JBrowse 2.
- Add route/component tests and extend `tests/e2e/homepage.spec.ts`, `search.spec.ts`, `genes.spec.ts`, and `accessibility.spec.ts`.

### Task 1: Add The Safe Public Renderer

- [ ] Add a failing renderer test for a columns node containing news and carousel nodes.
- [ ] Implement an exhaustive `COMPONENT_RENDERERS` map keyed by the shared discriminated union. Unknown keys render an error boundary in development and are rejected before production builds.
- [ ] Component adapters receive only validated props and approved data bindings; no `dangerouslySetInnerHTML` except the existing DOMPurify-controlled rich-text adapter.
- [ ] Add tests that script-like props and unknown actions cannot reach DOM rendering.
- [ ] Run `pnpm --filter @soymutdb/web test -- --run src/page-builder/__tests__/renderer.test.tsx`.

### Task 2: Drive Primary Navigation From The Definition

- [ ] Add a `SiteHeader` test asserting order Home, Search, Tools, Latest News, Contact and mobile parity.
- [ ] Replace hard-coded `NAV_ITEMS` with validated navigation data from the page-definition snapshot, retaining an immutable five-item fallback for API/offline failure.
- [ ] Preserve active state, keyboard focus, mobile drawer, language switch, theme, animation control, and command palette.
- [ ] Update translation keys and change all public `Gbrowse`/`GBrowse` labels to `JBrowse 2`; internal compatibility route names may remain.

### Task 3: Recompose The Home Page

- [ ] Add tests for exact section order and limits: news list first column (maximum five), carousel second column (three to six items), five tools, then sanitized CMS content.
- [ ] Remove `HomeHero` and `HomeStatsBar` from the rendered home composition without deleting reusable API clients.
- [ ] Build a responsive `grid-cols-1 lg:grid-cols-[2fr_3fr]` top section; stack on mobile.
- [ ] Render tool entries in this order: Gene ID, Physical Location, JBrowse 2, BLAST, Primer Design.
- [ ] Preserve loading, empty, error/retry, dark theme, reduced motion, and translated content.
- [ ] Run home unit tests and `tests/e2e/homepage.spec.ts`.

### Task 4: Make Gene Search URL-Backed And Shareable

- [ ] Extend route search validation to include `q`, `assembly`, and `run`.
- [ ] Add tests showing an initial parameterized URL restores form state and runs once, while form submit calls `window.open(router.buildLocation(...).href, "_blank", "noopener")`.
- [ ] Reorder table columns to Assembly, Chromosome, Position, Mutation Feature, Gene ID, JBrowse 2.
- [ ] Keep Gene ID detail links and generate JBrowse 2 links with the existing base-aware helper rather than root-relative strings.
- [ ] Wrap the table for horizontal scrolling below 768 px and preserve accessible region labels.

### Task 5: Make Location Search URL-Backed And Shareable

- [ ] Validate `assembly`, `chromosome`, `start`, `end`, and `run` in route search params.
- [ ] Add form tests for missing fields, `start < 1`, and `end < start`.
- [ ] Submit to a new parameterized tab and restore/rerun from URL.
- [ ] Use the same approved result column order and JBrowse 2 action semantics as Gene search.
- [ ] Run focused tests and Playwright search flow.

### Task 6: Route BLAST Directly To The Full Form

- [ ] Change the builder/default tool entry from `/search/blast` to `/blast`; keep `/search/blast` as a compatibility redirect.
- [ ] Verify the full form contains type (`blastn`/`blastp`), reference type, assembly, FASTA input, and submit.
- [ ] Add client-side FASTA validation before request submission without replacing backend validation.
- [ ] Ensure results expose assembly, query ID, coverage, E-value, Gene ID search action, and JBrowse 2 action. Cross-links open parameterized tabs with `noopener`.
- [ ] Run existing blast validation/result tests and browser smoke.

### Task 7: Keep JBrowse 2 And Primer Specialized

- [ ] Rename the public JBrowse transfer component and labels while keeping the existing route if changing it would break links.
- [ ] Use `import.meta.env.BASE_URL`/deployment helper for browser links so GitHub Pages and Cloudflare subpaths work.
- [ ] Keep Primer's region/paste modes and replace its GBrowse action label/link with JBrowse 2.
- [ ] Add tests for base paths and new-tab security attributes.

### Task 8: Connect Builder Definitions And Static Fallback

- [ ] Load the release-pinned PageDefinition from SSG bootstrap data; hydrate without refetch when the embedded version matches.
- [ ] If dynamic refresh fails, retain the validated embedded definition rather than reverting to an unrelated latest version.
- [ ] Seed the approved PDF layout as the initial published definition so a new installation has the required pages before any Admin edits.
- [ ] Add a build-time test proving every published component key has a registered renderer.

### Task 9: Responsive, Accessibility, And Visual Verification

- [ ] Extend Playwright at desktop 1440x900, tablet 900x900, and mobile 390x844.
- [ ] Assert mobile single-column order, visible focus, keyboard-operable navigation/forms, table horizontal overflow, no clipped controls, and no horizontal page overflow.
- [ ] Run accessibility scans for home, Gene search, location search, BLAST, and JBrowse launcher.
- [ ] Capture screenshots and compare layout hierarchy against `ui-r/网页-查询V2.pdf`; preserve the repository's visual system instead of copying wireframe colors.

### Task 10: Phase Verification

- [ ] Run: `pnpm --filter @soymutdb/web test -- --run`
- [ ] Run: `pnpm --filter @soymutdb/web typecheck`
- [ ] Run: `pnpm --filter @soymutdb/web lint`
- [ ] Run: `pnpm --filter @soymutdb/web build`
- [ ] Run: `pnpm exec playwright test --config tests/e2e/playwright.config.ts tests/e2e/homepage.spec.ts tests/e2e/search.spec.ts tests/e2e/genes.spec.ts tests/e2e/accessibility.spec.ts`

Expected: the public site follows the approved layout and flows on desktop/mobile, is fully driven by safe definitions except specialized JBrowse 2/BLAST behavior, and builds correctly for root and subpath deployments.
