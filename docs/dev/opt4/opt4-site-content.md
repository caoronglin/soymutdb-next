# OPT4 · Vue portal consumes editable site content

Status: done (unit + typecheck + lint + i18n guard + build + Playwright verified).
Owner files: `apps/web/src/lib/site-content.{ts,test.ts}`,
`apps/web/src/views/HomeView.vue` + `.test.ts`,
`apps/web/src/components/PortalHeader.vue` + `.test.ts`.

## Problem

The admin console can edit `content.*` copy and the React portal reads it through
`apps/web/src/lib/site-content.tsx` + `useSiteContent()`. The Vue portal had no
equivalent, so an operator edit never reached the live Vue artifact.

## Design: override-only, variant-keyed

`useSiteContent(variant?)` is a thin reader over
`getSiteContent(site.siteVariant, { onlyOverrides: true })`.

`onlyOverrides: true` is mandatory, not an optimisation. Without it the API
fills every registered key with its **English** registered default; since the
Vue portal renders locale-aware `t(...)` strings, a Chinese page would flip to
English the moment the query resolved. With stored-only rows every call site
reads `override ?? t(...)`:

- an unedited deployment renders byte-identically to today in both locales;
- an operator edit wins in both locales.

Isolation and failure behaviour:

- query key is `["site", "content", <variant>]`, so external and internal never
  share a cache entry (`packages/query-keys` does not own this key; it is local
  to the composable like `lib/branding.ts`);
- `staleTime: 5 * 60_000`, `retry: false`;
- a rejected read (offline, or anonymous internal visitor hitting a 401) leaves
  `data` undefined and `get` returns the caller fallback — no throw, no blocked
  render;
- `get(key, fallback)` returns `overrides[key] ?? fallback`, and `""` when the
  fallback is omitted (React parity: never `undefined`).

## Wiring map (35 registered keys)

| Backend key | Vue location | i18n fallback |
| --- | --- | --- |
| `hero.eyebrow` | `HomeView` hero eyebrow | `home.heroEyebrow` |
| `hero.title` | `HomeView` hero `<h1>` | `home.heroTitle` |
| `hero.subtitle` | `HomeView` hero subtitle | `home.heroSubtitle` |
| `hero.searchPlaceholder` | `HomeView` `#home-search` placeholder | `home.searchPlaceholder` |
| `tool.gene.label` | `HomeView` `task-gene-search` title | `home.toolGeneLabel` |
| `tool.gene.desc` | `HomeView` `task-gene-search` description | `home.toolGeneDescription` |
| `tool.location.label` | `HomeView` `task-location-search` title | `home.toolLocationLabel` |
| `tool.location.desc` | `HomeView` `task-location-search` description | `home.toolLocationDescription` |
| `tool.gbrowse.label` | `HomeView` `task-jbrowse` title | `home.toolGbrowseLabel` |
| `tool.gbrowse.desc` | `HomeView` `task-jbrowse` description | `home.toolGbrowseDescription` |
| `tool.primer.label` | `HomeView` `task-primer` title | `home.toolPrimerLabel` |
| `tool.primer.desc` | `HomeView` `task-primer` description | `home.toolPrimerDescription` |
| `tool.blast.label` | `HomeView` `task-blast` title | `home.toolBlastLabel` |
| `tool.blast.desc` | `HomeView` `task-blast` description | `home.toolBlastDescription` |
| `nav.home` | `PortalHeader` brand `aria-label` | `nav.home` |
| `nav.search` | `PortalHeader` search label + submit | `nav.search` |
| `nav.explore` | `PortalHeader` desktop + mobile group | `nav.explore` |
| `nav.resources` | `PortalHeader` desktop + mobile group | `nav.resources` |
| `nav.tools` | `PortalHeader` desktop + mobile group | `nav.tools` |
| `nav.downloads` | `PortalHeader` desktop + mobile direct link | `nav.downloads` |
| `nav.genes` | `PortalHeader` Explore menu (desktop + mobile) | `nav.genes` |
| `nav.variants` | Explore menu | `nav.variants` |
| `nav.browser` | Explore menu | `nav.browser` |
| `nav.sra` | Explore menu | `nav.sra` |
| `nav.compare` | Explore menu | `nav.compare` |
| `nav.analytics` | Explore menu | `nav.analytics` |
| `nav.blast` | Tools menu | `nav.blast` |
| `nav.analyses` | Tools menu | `nav.analyses` |
| `nav.allTools` | Tools menu | `nav.allTools` |
| `nav.guide` | Resources menu | `nav.guide` |
| `nav.help` | Resources menu | `nav.help` |
| `nav.news` | Resources menu | `nav.news` |
| `nav.publications` | Resources menu | `nav.publications` |
| `nav.seedRequest` | Resources menu | `nav.seedRequest` |
| `nav.about` | Resources menu | `nav.about` |

Not wired on purpose (kept `t(...)`):

- `nav.mutantLines` and the `tools.*.title` page titles are not in
  `settings_registry.py`, so `PortalHeader` only routes registered nav keys
  through `get` (`EDITABLE_NAV_KEYS`).
- The hero carousel slides 2/3 have no registered key; the first slide reuses
  `home.heroTitle` and was deliberately left `t(...)` (React parity).
- `hero.image` / `tool.*.image` are not rendered this round (no image markup).

## Unwired registry keys (next round, 96)

Only keys present in `apps/api/app/core/settings_registry.py` that are still
unconsumed. `hero.image` and the five `tool.*.image` need markup (not text).

- `hero.image`
- `tool.{gene,location,gbrowse,blast,primer}.image`
- `search.genes.title|subtitle|colAssembly|colChromosome|colPosition|colMutation|colGeneId|colGbrowse`
- `search.location.title|subtitle|colAssembly|colChromosome|colPosition|colMutation|colGeneId|colGbrowse|assembly|chromosome|start|end|submit`
- `search.genes.assembly|assemblyPlaceholder|geneIdHint|geneIdPlaceholder`
- `blast.searchType|database|databasePlaceholder|input|inputSequence|sequencePlaceholder|submit|eValue|maxHits|hitSequenceId|hitGeneId|hitCoverage|hitEValue`
- `help.gettingStarted|documentation|contact|faq|faq1.q|faq1.a|faq2.q|faq2.a|faq3.q|faq3.a|faq4.q|faq4.a|faq5.q|faq5.a|faq6.q|faq6.a`
- `ui.searchButton|submit|loading|errorRetry|noResults`
- `common.loading|retry|submit|clear|reset|empty|error|viewAll`
- `genes.title|subtitle|colGeneId|colChromosome|colBiotype|colVariantCount|colSymbol|colPosition`
- `variants.title|subtitle|colVariantId|colChromosome|colPosition|colRefAlt|colVariantType|colImpact|colGeneSymbol`
- `guide.title|subtitle`
- `downloads.title|subtitle`
- `nav.latestNews`, `nav.contact` (registered; `nav.latestNews` is used by
  HomeView headings, `nav.contact` by the footer)

No new i18n keys were needed.

## Verification

All commands run from the repo root with the pinned pnpm/XDG env.

| Command | Exit | Result |
| --- | --- | --- |
| `pnpm --filter @soymutdb/web exec vitest run src/lib/site-content.test.ts src/views/HomeView.test.ts src/components/PortalHeader.test.ts` | 0 | 3 files / 27 tests passed |
| `pnpm --filter @soymutdb/web test` | 0 | 51 files / 263 tests passed (was 50 / 251) |
| `pnpm --filter @soymutdb/web typecheck` | 0 | clean |
| `pnpm --filter @soymutdb/web lint` | 0 | clean |
| `python3 scripts/check_visible_i18n.py` | 0 | `visible i18n OK (5 tracked string(s) in 1 file(s))` |
| `VITE_API_BASE_URL=http://localhost:8010 VITE_JBROWSE_BASE_URL=http://localhost:5175 pnpm --filter @soymutdb/web build` | 0 | built; 27 external documents enumerated |

New regression coverage:

- composable: fallback with no override, override wins, omitted fallback → `""`,
  failure degrades without throwing, external/internal query keys differ,
  `onlyOverrides: true` is always sent;
- HomeView: empty map keeps today's zh copy (and is provably not the English
  registered default), `{"hero.title":"OVERRIDE"}` wins under **both** en and zh,
  `hero.searchPlaceholder` override;
- PortalHeader: `nav.explore` override renders, unregistered `nav.mutantLines`
  stays i18n-only, all pre-existing nav/branding/gating assertions stay green.

### Headless-browser assertions

`NODE_PATH=e2e/node_modules PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright" node <script>`
against dev server `http://localhost:5173`, locale `zh-CN`, with
`page.route('**/api/v1/site/content**', ...)` and the auth endpoints stubbed
(anonymous dev otherwise hard-redirects to `/login`):

- stub `{}` → hero `<h1>` stays `探索多物种突变的未知疆域`, not the English
  default; request was
  `http://localhost:5173/api/v1/site/content?variant=external&only_overrides=true`;
  switching language then yields the English i18n string (proves localization
  still works);
- stub `{"hero.title":"运营标题"}` → hero shows `运营标题`, still on `/`;
- same stub + click `[data-testid=language-switch]` → still `运营标题` under `en`;
- stub `{"nav.explore":"探索OVERRIDE"}` → `nav-group-explore` shows the override.

Script kept at `.validation/tmp/site-content-verify.cjs` (untracked scratch).

## Not done / follow-ups

- No image rendering (`hero.image`, `tool.*.image`).
- Only HomeView + PortalHeader consume content this round; every other view
  still renders `t(...)` only.
- The dev stack needs `auth/refresh` + `auth/me` stubbed for a future E2E spec;
  a committed `e2e/tests/site-content.spec.ts` was out of scope.
