# OPT5-B · Help / Guide / SearchGenes / SearchLocation content wiring

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

Status: done (targeted vitest + full web suite + typecheck + lint + i18n guard +
production build all green).
Owner files: `apps/web/src/views/HelpView.vue` + `HelpView.test.ts`,
`GuideView.vue` + `GuideView.test.ts`,
`SearchGenesView.vue` + `SearchGenesView.test.ts`,
`SearchLocationView.vue` + `SearchLocationView.test.ts`,
this note.

## Problem

The admin console can edit `content.*` copy; the portal reader
`useSiteContent()` (OPT4) already resolves `override ?? t(fallback)`. The nav /
home keys were wired last round; the remaining React-consumed *registered* keys
on these four pages were still hard-coded `t(...)`, so an operator edit never
reached them.

## Design

Every call site is `get("<registered content key>", t("<i18n key>"))` — the
localized `t(...)` fallback is always preserved, and an unedited deployment
renders the same catalog strings as before. No change to
`lib/site-content.ts`, no new parameters, no new i18n keys.

## Wiring map

### HelpView.vue

| Backend key | Location | i18n fallback |
| --- | --- | --- |
| `help.faq` | FAQ `<h2>` | `t("help.faq")` |
| `help.faq{i}.q` | FAQ question, i = loop index + 1 | `t("help.q{i}.q")` |
| `help.faq{i}.a` | FAQ answer, i = loop index + 1 | `t("help.q{i}.a")` |
| `help.contact` | contact `<h2>` | `t("help.contact")` |
| `help.documentation` | documentation `<h2>` | `t("help.documentation")` |
| `help.gettingStarted` | getting-started `<h2>` | `t("help.gettingStarted")` |

**Index shift:** the catalog names the questions `help.q1`..`help.q6` while the
backend keys are `help.faq1.q`..`help.faq6.q`. `FAQ` keeps the catalog names and
the loop derives the backend key from the 1-based index — exactly React's
`get("help.faq" + (i + 1) + ".q", faq.q)`. The FAQ list was extended from 5 to 6
entries to match React; the FAQ `data-testid` numbering is unchanged in shape
(`help-question-0..5`).

A documentation section was added: React's docs card had no Vue counterpart, so
`help.documentation` had no element to render into. Its body reuses the existing
`docs.subtitle` catalog string (no hard-coded copy, so the visible-i18n gate
stays at 0 hits for this file).

### GuideView.vue

| Backend key | Location | i18n fallback |
| --- | --- | --- |
| `help.documentation` | page eyebrow | `t("help.documentation")` |
| `nav.guide` | page `<h1>` | `t("nav.guide")` |

The `<h1>` used to be `page?.title_en ?? t("docs.gettingStarted")`. With the API
page absent on the dev deployment the h1 rendered "Getting Started" even though
the route is `/guide`; it now renders `nav.guide` ("Guide"), matching the task's
"页面标题" mapping.

### SearchGenesView.vue

| Backend key | Location | i18n fallback |
| --- | --- | --- |
| `search.genes.title` | `<h1>` | `t("search.genes.title")` |
| `search.genes.subtitle` | subtitle `<p>` | `t("search.genes.subtitle")` |
| `search.genes.assembly` | assembly field label | `t("search.genes.assembly")` |
| `search.genes.assemblyPlaceholder` | assembly `<select>` placeholder option | `t("search.genes.assemblyPlaceholder")` |
| `search.genes.geneIdPlaceholder` | gene input `placeholder` | `t("search.genes.geneIdPlaceholder")` |
| `search.genes.geneIdHint` | hint `<p id="search-genes-hint">` | `t("search.genes.geneIdHint")` |
| `ui.searchButton` | submit button | `t("search.genes.submit")` |
| `ui.noResults` | empty-result `<p>` | `t("search.genes.noResults")` |
| `ui.errorRetry` | error `<p>` | `t("search.genes.resultsRetry")` |
| `search.genes.colAssembly` | template column `assembly_name` header | `t("search.genes.colAssembly")` |
| `search.genes.colChromosome` | template column `chromosome` header | `t("search.genes.colChromosome")` |
| `search.genes.colPosition` | template column `position` header | `t("search.genes.colPosition")` |
| `search.genes.colMutation` | template column `variant_count` header | `t("search.genes.colMutation")` |
| `search.genes.colGeneId` | template column `gene_id` header | `t("search.genes.colGeneId")` |
| `search.genes.colGbrowse` | template column `jbrowse` header | `t("search.genes.colGbrowse")` |

### SearchLocationView.vue

| Backend key | Location | i18n fallback |
| --- | --- | --- |
| `search.location.title` | `<h1>` | `t("search.location.title")` |
| `search.location.subtitle` | subtitle `<p>` | `t("search.location.subtitle")` |
| `search.location.assembly` | assembly label | `t("search.location.assembly")` |
| `search.location.chromosome` | chromosome label | `t("search.location.chromosome")` |
| `search.location.start` | start label **+ `aria-label`** | `t("search.location.start")` |
| `search.location.end` | end label **+ `aria-label`** | `t("search.location.end")` |
| `search.location.submit` | submit button | `t("search.location.submit")` |
| `ui.noResults` | empty-result `<p>` | `t("search.location.noResults")` |
| `ui.errorRetry` | error `<p>` | `t("search.location.resultsRetry")` |
| `search.genes.colAssembly` | template column `assembly_name` header | `t("search.location.colAssembly")` |
| `search.genes.colChromosome` | template column `chromosome` header | `t("search.location.colChromosome")` |
| `search.genes.colPosition` | template column `position` header | `t("search.location.colPosition")` |
| `search.genes.colMutation` | template columns `impact` / `variant_type` header | `t("search.location.colMutation")` |
| `search.genes.colGeneId` | template column `gene_id` header | `t("search.location.colGeneId")` |
| `search.genes.colGbrowse` | template column `jbrowse` header | `t("search.location.colGbrowse")` |

The six `search.genes.col*` keys are deliberately reused on this page with
`search.location.col*` fallbacks — that is exactly what React did, so one
operator edit retitles the column on both search pages.

**Column headers:** the API owns the column set (`ConfigurableTable` is out of
scope), so each view remaps the template columns' `label_en` through the content
key map before passing them to the table. English output is unchanged; a Chinese
page now shows the localized catalogue label instead of the English template
label.

## Skipped (genuinely unregistered in `settings_registry.py`)

| Key | Reason |
| --- | --- |
| `search.genes.geneId` | React called `get(...)` but the key is not registered → the server never returns it; kept `t(...)` |
| `search.location.assemblyPlaceholder` | not registered; the Vue assembly `<select>` has no placeholder slot |
| `search.location.formatHint` | not registered; used twice (`formatHint` line + idle message) |

Re-checked with a case-insensitive extraction: the 47 camelCase keys that were
previously mis-classified as "unregistered" (`blast.searchType`, `ui.noResults`,
`search.genes.colAssembly`, …) are registered and are wired here.

## Known gaps in the catalog (no `packages/**` change allowed)

| Key | Effect |
| --- | --- |
| `help.q6.q` / `help.q6.a` | the 6th FAQ falls back to the raw key `help.q6.q` / `help.q6.a`; the `help.faq6.*` override still wins |
| `search.genes.resultsRetry` | `ui.errorRetry` fallback resolves to the raw key on the gene error line |
| `search.location.resultsRetry` | same on the location error line |

`search.genes.colGbrowse` / `search.location.colGbrowse` are mapped, but the
JBrowse action column header is hard-coded (`JBrowse 2`) inside
`ConfigurableTable.vue`; the key only renders for a template that itself exposes
a `jbrowse` column. Fixing that needs a change to the shared component.

## Verification

All commands from the repo root with the pinned pnpm/XDG env.

| Command | Exit | Result |
| --- | --- | --- |
| `pnpm --filter @soymutdb/web exec vitest run src/views/HelpView.test.ts src/views/SearchGenesView.test.ts src/views/SearchLocationView.test.ts src/views/GuideView.test.ts` | 0 | 4 files / 22 tests passed |
| `pnpm --filter @soymutdb/web test` | 0 | 55 files / 304 tests passed (was 52 / 272) |
| `pnpm --filter @soymutdb/web typecheck` | 0 | clean |
| `pnpm --filter @soymutdb/web lint` | 0 | clean |
| `python3 scripts/check_visible_i18n.py` | 0 | `visible i18n OK` |
| `VITE_API_BASE_URL=… VITE_JBROWSE_BASE_URL=… pnpm --filter @soymutdb/web build` | 0 | 27 static documents emitted |

New tests: HelpView (6 FAQ mapping via `help.q{i}`, overrides for FAQ1 /
contact / faq / documentation / gettingStarted), GuideView (eyebrow + title
fallback, title override), SearchGenes (fallback title/assembly/placeholder,
title override, column retitle, error override), SearchLocation (fallback
title/aria, title + aria + empty + error overrides, column retitle). No existing
assertion was deleted or weakened and no test was skipped.
