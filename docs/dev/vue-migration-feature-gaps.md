# Vue migration — React-to-Vue feature-parity gap analysis

Status: evidence-based audit of the current tree (HEAD `79c273bca`).

This document maps every React route/feature that existed immediately before the
Vue cutover (and the earlier React admin baseline) to the current Vue route or to
an explicit gap. It also reconciles `docs/dev/vue-migration-recovery-status.md`
section 4 and `docs/dev/project-status.md` against the current tree.

Every row carries file evidence. Anything that cannot be resolved from the tree is
marked **待复核** with the exact command that would confirm it. No row is based on
inference.

## 1. Method and evidence commands

Current Vue route tables (authoritative):

- `apps/web/src/router/routes.ts` (pure metadata table) and
  `apps/web/src/router/index.ts` (component binding, `PORTAL_ROUTES`).
- `apps/admin/src/router/index.ts` (`ADMIN_ROUTES`: functional routes,
  redirects, and `LegacyUnavailableView` placeholders).
- Views: `apps/web/src/views/*.vue`, `apps/admin/src/views/*.vue`.
- Route-depth tests: `apps/admin/src/router/legacy-routes.test.ts`,
  `apps/web/src/router/feature-gating.test.ts`.

React baselines (last pre-Vue state):

| Purpose | Commit | What it is |
| --- | --- | --- |
| Web React baseline | `d3904c210` | Parent of `25c32e499` ("cut the portal over to Vue"); last React web tree. |
| Web Vue cutover | `25c32e499` | `git show -s --format=%P 25c32e499` -> `d3904c210`. |
| Admin React baseline | `2004c25c6` | Direct parent of `53a65a90d` (admin/charts Vue cutover). Message is `fix(shared): give the shared package a tsconfig…`, **not** "Phase 4/5" (correction to the task brief). |
| Admin Vue cutover | `53a65a90d` | Deletes `apps/admin/src/App.tsx` (384 lines) and adds `App.vue`. |
| Earlier React admin baseline | `4d970bfba` | "initial baseline"; 18 admin routes, later reduced in `cab115493` (2026-08-13). |

Commands used (reproducible):

```bash
# Current Vue route inventory
grep -c 'path: "' apps/web/src/router/routes.ts        # 35
grep -cE 'name: ' apps/admin/src/router/index.ts       # 17 name literals (incl. not-found and one duplicate login)

# React web route table (generated route tree)
git show d3904c210:apps/web/src/routeTree.gen.ts
git ls-tree -r --name-only d3904c210 -- apps/web/src/routes

# React admin route table
git show 2004c25c6:apps/admin/src/App.tsx
git show 4d970bfba:apps/admin/src/App.tsx

# ADRs
cat docs/adr/0008-no-vue-antd-pilot-route.md
cat docs/adr/0009-retire-page-builder-and-widgets.md
```

## 2. Baseline counts

| Tree | Count | Evidence |
| --- | --- | --- |
| React web routes @ `d3904c210` | 36 | 36 route files under `apps/web/src/routes` (excluding `__root.tsx` and the non-route helper `tools/api.ts`). |
| Vue web routes (current) | 35 | `grep -c 'path: "' apps/web/src/router/routes.ts` -> 35. |
| React admin routes @ `2004c25c6` | 34 | `git show 2004c25c6:apps/admin/src/App.tsx` -> 34 `path:` definitions. |
| Vue admin functional routes (current) | 19 | `apps/admin/src/router/index.ts` named non-redirect component routes excluding `not-found`; plus 11 redirects, 1 documented-unavailable route (`/resource-catalog`) and 7 ADR-0009 `LegacyUnavailableView` routes. |
| Earlier React admin routes @ `4d970bfba` | 18 | `git show 4d970bfba:apps/admin/src/App.tsx` -> 18 `path:` definitions. |

Correction: `docs/wiki/applications.md` says "公共站 34 条路由" and "管理端 14 条路由";
the current tables are **35** web routes and **19** admin functional routes.

## 3. apps/web — React `d3904c210` -> current Vue

All Vue views below live in `apps/web/src/views/`. "implemented" means the route
exists in `apps/web/src/router/routes.ts` and is bound in
`apps/web/src/router/index.ts` (`COMPONENTS`).

| React feature/route | React evidence (file@commit) | Vue status | Vue file | gap/action |
| --- | --- | --- | --- | --- |
| Home / | `apps/web/src/routes/index.tsx@d3904c210` | implemented | `HomeView.vue` | none; news loading/error/empty covered by `HomeView.test.ts` |
| About /about | `apps/web/src/routes/about.tsx@d3904c210` | implemented | `AboutView.vue` | none |
| AntD pilot /antd-pilot | `apps/web/src/routes/_antd-pilot.tsx@d3904c210` | intentionally retired w/ ADR | — (no route) | ADR-0008; see §6 |
| Analytics /analytics | `apps/web/src/routes/analytics.tsx@d3904c210` | implemented | `AnalyticsView.vue` | none |
| BLAST /blast | `apps/web/src/routes/blast.tsx@d3904c210` | implemented | `BlastView.vue` | none |
| Browser /browser | `apps/web/src/routes/browser.tsx@d3904c210` | implemented | `BrowserView.vue` | none |
| Compare /compare | `apps/web/src/routes/compare.tsx@d3904c210` | implemented | `CompareView.vue` | none |
| Downloads /downloads | `apps/web/src/routes/downloads.tsx@d3904c210` | implemented | `DownloadsView.vue` | none |
| Guide /guide | `apps/web/src/routes/guide.tsx@d3904c210` | implemented | `GuideView.vue` | none |
| Help /help | `apps/web/src/routes/help.tsx@d3904c210` | implemented | `HelpView.vue` | none |
| Login /login | `apps/web/src/routes/login.tsx@d3904c210` | implemented | `LoginView.vue` | none; `safeRedirect` in `apps/web/src/lib/redirect.ts` |
| Publications /publications | `apps/web/src/routes/publications.tsx@d3904c210` | implemented | `PublicationsView.vue` | none |
| Search /search | `apps/web/src/routes/search.tsx@d3904c210` | implemented | `SearchView.vue` | none |
| Gene ID search /search/genes | `apps/web/src/routes/search/genes.tsx@d3904c210` | implemented | `SearchGenesView.vue` | assembly id/ambiguity handled by `apps/web/src/lib/assembly-selection.ts` |
| Location search /search/location | `apps/web/src/routes/search/location.tsx@d3904c210` | implemented | `SearchLocationView.vue` | none |
| GBrowse /search/gbrowse | `apps/web/src/routes/search/gbrowse.tsx@d3904c210` | implemented | `GbrowseView.vue` | feature-gated via `apps/web/src/router/feature-gating.ts` |
| Primer /search/primer | `apps/web/src/routes/search/primer.tsx@d3904c210` | implemented | `PrimerView.vue` | none |
| BLAST search /search/blast | `apps/web/src/routes/search/blast.tsx@d3904c210` | implemented | `BlastView.vue` | shares the `blast` component key |
| Tools search /search/tools | `apps/web/src/routes/search/tools.tsx@d3904c210` | implemented | `SearchToolsView.vue` | none |
| Seed request /seed-request | `apps/web/src/routes/seed-request.tsx@d3904c210` | implemented | `SeedRequestView.vue` | none |
| SRA /sra | `apps/web/src/routes/sra.tsx@d3904c210` | implemented | `SraView.vue` | none |
| Genes list /genes | `apps/web/src/routes/genes/index.tsx@d3904c210` | implemented | `GenesListView.vue` | none |
| Gene detail /genes/$geneId | `apps/web/src/routes/genes/$geneId.tsx@d3904c210` | implemented | `GeneView.vue` | none |
| Mutants list /mutants | `apps/web/src/routes/mutants/index.tsx@d3904c210` | implemented | `MutantsListView.vue` | none |
| Mutant detail /mutants/$id | `apps/web/src/routes/mutants/$id.tsx@d3904c210` | implemented | `MutantDetailView.vue` | param renamed `$id` -> `:publicId` (`routes.ts`), consistent with public-id contract |
| News list /news | `apps/web/src/routes/news/index.tsx@d3904c210` | implemented | `NewsListView.vue` | none |
| News detail /news/$slug | `apps/web/src/routes/news/$slug.tsx@d3904c210` | implemented | `NewsDetailView.vue` | none |
| Variants /variants | `apps/web/src/routes/variants/index.tsx@d3904c210` | implemented | `VariantsView.vue` | none |
| Analyses /analyses | `apps/web/src/routes/analyses/index.tsx@d3904c210` | implemented | `AnalysesView.vue` | none |
| fastp /analyses/fastp | `apps/web/src/routes/analyses/fastp.tsx@d3904c210` | implemented | `AnalysesFastpView.vue` | none |
| scanpy /analyses/scanpy | `apps/web/src/routes/analyses/scanpy.tsx@d3904c210` | implemented | `AnalysesScanpyView.vue` | none |
| Analysis job /analyses/$jobId | `apps/web/src/routes/analyses/$jobId.tsx@d3904c210` | implemented | `AnalysesJobView.vue` | none |
| Tools index /tools | `apps/web/src/routes/tools/index.tsx@d3904c210` | implemented | `ToolsView.vue` | none |
| Sequence fetch /tools/seqfetch | `apps/web/src/routes/tools/seqfetch.tsx@d3904c210` | implemented | `SeqFetchView.vue` | none |
| Enrichment /tools/enrichment | `apps/web/src/routes/tools/enrichment.tsx@d3904c210` | implemented | `EnrichmentView.vue` | none |
| Expression pattern /tools/exppattern | `apps/web/src/routes/tools/exppattern.tsx@d3904c210` | implemented | `ExpPatternView.vue` | none |
| Feature: page-definition-driven home composition | `apps/web/src/routes/__tests__/home-page-definition-binding.test.tsx@d3904c210` (mocks `apps/web/src/page-builder/loader`) | intentionally retired w/ ADR | — (Vue `HomeView.vue` renders fixed sections) | ADR-0009; see §6 |

Web tally: 35 implemented, 0 missing, 2 intentionally retired (ADR-0008 / ADR-0009),
0 待复核.

## 4. apps/admin — React `2004c25c6` -> current Vue

All Vue views below live in `apps/admin/src/views/`. The React route table is
`apps/admin/src/App.tsx@2004c25c6` (34 routes). Redirect and placeholder targets
are in `apps/admin/src/router/index.ts`.

| React feature/route | React evidence (file@commit) | Vue status | Vue file | gap/action |
| --- | --- | --- | --- | --- |
| Login /login | `apps/admin/src/routes/login.tsx@2004c25c6` | implemented | `LoginView.vue` | none |
| Dashboard / | `apps/admin/src/routes/index.tsx@2004c25c6` | implemented | `DashboardView.vue` | wiki notes React had extra metrics; current page has "关键指标" |
| Resource catalog /resource-catalog | `apps/admin/src/routes/resource-catalog.tsx@2004c25c6` | documented unavailable | `LegacyUnavailableView.vue` | no backing API exists: the React page was a static link grid and there is no resource-catalog endpoint. `router/index.ts` renders the explicit unavailable page with a `reasonKey`/`statusKey` and a link to `/imports`, so no catalog data is fabricated |
| Imports list /imports | `apps/admin/src/routes/imports.tsx@2004c25c6` | implemented | `ImportsView.vue` | none |
| Import create /imports/new | `apps/admin/src/routes/imports/new.tsx@2004c25c6` | implemented | `ImportCreateView.vue` | restored; **corrects** `wiki/applications.md` line 53 and §6.5 which still list it as not restored; locked by `legacy-routes.test.ts` ("P1-06") |
| Import task detail /imports/$taskId | `apps/admin/src/routes/imports/task-detail.tsx@2004c25c6` | implemented | `ImportDetailView.vue` | restored; same correction; progress enhancement remains "计划中" per wiki |
| Content management /content | `apps/admin/src/routes/content.tsx@2004c25c6` | implemented | `StaticPagesView.vue` | static-page list + create/edit + publish/unpublish/delete backed by `adminContentApi` (`packages/api-client/src/admin-content.ts`); `router/index.ts` `/content`; resolves the 待复核 — the pages tab is restored, not retired |
| Content pages /content/pages | `apps/admin/src/App.tsx@2004c25c6` mounts `PageBuilderIndexPage` (`apps/admin/src/routes/page-builder/index.tsx@2004c25c6`) | implemented (reinterpreted) | `StaticPagesView.vue` | ADR-0009 keeps the page builder retired; `/content/pages` is repurposed as the static-page editor (same view as `/content`) and `/content/pages/:pageId` redirects to `/content?edit=<id>`. No page-builder editor is restored; see §6 |
| Content legacy migration /content/legacy | `apps/admin/src/routes/content.tsx@2004c25c6` (`isLegacyRoute` + `StaticPageMigrationReport`) | implemented (read-only) | `ContentLegacyMigrationView.vue` | calls the real `POST /admin/content/pages/migrate-to-page-builder/dry-run` (`apps/api/app/api/v1/admin_content.py`, `dry_run` only); page builder stays retired per ADR-0009, so the report is a diagnostic and writes nothing |
| Media /media | `apps/admin/src/routes/media.tsx@2004c25c6` | implemented | `MediaView.vue` | none |
| News list /news | `apps/admin/src/routes/news/index.tsx@2004c25c6` | implemented | `NewsAdminView.vue` | none |
| News new /news/new | `apps/admin/src/routes/news/new.tsx@2004c25c6` | implemented (redirect) | `NewsAdminView.vue` | `router/index.ts:52` -> `/news?new=1` |
| News trash /news/trash | `apps/admin/src/routes/news/trash.tsx@2004c25c6` | implemented (redirect) | `NewsAdminView.vue` | `router/index.ts:53` -> `/news?status=archived` |
| News edit /news/$id | `apps/admin/src/routes/news/$id.tsx@2004c25c6` | implemented (redirect) | `NewsAdminView.vue` | `router/index.ts:54` -> `/news?edit=<id>` |
| Audit /audit | `apps/admin/src/routes/audit.tsx@2004c25c6` | implemented | `AuditView.vue` | none |
| Settings overview /settings | `apps/admin/src/routes/settings/index.tsx@2004c25c6` | implemented | `SettingsView.vue` | supports `?section=` (used by the security/appearance/integrations/localization/advanced redirects); a requested-but-unregistered section renders a documented unavailable state instead of the first section |
| Settings legacy form /settings/legacy | `apps/admin/src/routes/settings.tsx@2004c25c6` | implemented (redirect) | `SettingsView.vue` | `router/index.ts` -> `/settings`; the schema-driven overview exposes every registered section, which is the monolithic form's replacement |
| Settings site /settings/site | `apps/admin/src/routes/settings/site.tsx@2004c25c6` | implemented (redirect) | `SiteBrandSettingsView.vue` | `router/index.ts:50` -> `/settings/brand` |
| Settings appearance /settings/appearance | `apps/admin/src/routes/settings/appearance.tsx@2004c25c6` | implemented (redirect) | `SettingsView.vue` | `router/index.ts` -> `/settings?section=general` (`general` carries `defaultTheme`/`primaryColor`, verified against `apps/api/app/core/settings_registry.py`); an unregistered `?section` renders a documented unavailable state |
| Settings integrations /settings/integrations | `apps/admin/src/routes/settings/integrations.tsx@2004c25c6` | implemented (redirect) | `SettingsView.vue` | `router/index.ts` -> `/settings?section=cdn` (`cdn` section, verified against `settings_registry.py`) |
| Settings security /settings/security | `apps/admin/src/routes/settings/security.tsx@2004c25c6` | implemented (redirect) | `SettingsView.vue` | `router/index.ts:51` -> `/settings?section=security` |
| Settings localization /settings/localization | `apps/admin/src/routes/settings/localization.tsx@2004c25c6` | implemented (redirect) | `SettingsView.vue` | `router/index.ts` -> `/settings?section=general` (`defaultLanguage`); site-variant content remains in the overview |
| Settings advanced /settings/advanced | `apps/admin/src/routes/settings/advanced.tsx@2004c25c6` | implemented (redirect) | `SettingsView.vue` | `router/index.ts` -> `/settings?section=data`; the other advanced sections (`email`, `file_preview`) stay reachable in the overview nav |
| Features /features | `apps/admin/src/routes/features.tsx@2004c25c6` | implemented | `FeaturesView.vue` | none |
| Analytics settings /analytics-settings | `apps/admin/src/routes/analytics-settings.tsx@2004c25c6` | implemented | `AnalyticsSettingsView.vue` | real summary from `GET /admin/analytics/summary` via `packages/api-client/src/admin-analytics.ts`; the Cloudflare beacon remains documented build-time configuration and the page never shows placeholder numbers |
| Widgets /widgets | `apps/admin/src/routes/widgets.tsx@2004c25c6` | intentionally retired w/ ADR | `LegacyUnavailableView.vue` (`router/index.ts`, ADR-0009) | ADR-0009; see §6 |
| Widget editor /widgets/$name | `apps/admin/src/routes/widgets/$name.tsx@2004c25c6` | intentionally retired w/ ADR | `LegacyUnavailableView.vue` (`router/index.ts`, ADR-0009) | ADR-0009; see §6 |
| Layout editor /layout | `apps/admin/src/routes/layout.tsx@2004c25c6` | intentionally retired w/ ADR | `LegacyUnavailableView.vue` (`router/index.ts`, ADR-0009) | ADR-0009; see §6 |
| Widget preview /widget-preview | `apps/admin/src/routes/widget-preview.tsx@2004c25c6` | intentionally retired w/ ADR | `LegacyUnavailableView.vue` (`router/index.ts`, ADR-0009) | ADR-0009; see §6 |
| Widget health /widget-health | `apps/admin/src/routes/widget-health.tsx@2004c25c6` | intentionally retired w/ ADR | `LegacyUnavailableView.vue` (`router/index.ts`, ADR-0009) | ADR-0009; see §6 |
| Page builder /page-builder | `apps/admin/src/routes/page-builder/index.tsx@2004c25c6` | intentionally retired w/ ADR | `LegacyUnavailableView.vue` (`router/index.ts`, ADR-0009) | ADR-0009; see §6 |
| Page builder edit /page-builder/$pageId | `apps/admin/src/routes/page-builder/$pageId.tsx@2004c25c6` | intentionally retired w/ ADR | `LegacyUnavailableView.vue` (`router/index.ts`, ADR-0009) | ADR-0009; see §6 |
| Publications /publications | `apps/admin/src/routes/publications.tsx@2004c25c6` | implemented | `PublicationsAdminView.vue` | none |
| Table views /table-views | `apps/admin/src/routes/table-views.tsx@2004c25c6` | implemented (renamed) | `TableTemplatesView.vue` | Vue path is `/table-templates` (`router/index.ts:36`); no `/table-views` alias -> **待复核** old link reachability: `grep -n 'table-views' apps/admin/src/router/index.ts` |

Admin tally: 26 implemented (including the read-only migration preview and the
`/content/pages` reinterpretation), 1 documented unavailable (`/resource-catalog`,
no backing API), 7 intentionally retired (ADR-0009), 0 missing, 0 待复核.

## 5. Earlier React admin baseline `4d970bfba` — routes removed before the Vue cutover

These routes existed at the initial baseline and were **deleted in `cab115493`**
(2026-08-13, "complete data publishing and search upgrade"), i.e. before the Vue
cutover. They are not part of the `2004c25c6` React baseline, so they are listed
separately. Their disposition is not documented in any ADR -> **待复核**.

| React feature/route | React evidence (file@commit) | Vue status | Vue file | gap/action |
| --- | --- | --- | --- | --- |
| Users admin /users | `apps/admin/src/routes/users.tsx@4d970bfba` | 待复核 | — | Removed in `cab115493`. Confirm no replacement: `git log --all --oneline --diff-filter=AD -- apps/admin/src/routes/users.tsx` |
| Assemblies admin /assemblies | `apps/admin/src/routes/assemblies.tsx@4d970bfba` | 待复核 | — | Removed in `cab115493`. Confirm: `grep -rn 'assemblies' apps/admin/src/router` |
| Variants admin /variants | `apps/admin/src/routes/variants.tsx@4d970bfba` | 待复核 | — | Removed in `cab115493`. Confirm: `grep -rn 'variants' apps/admin/src/router` |
| Tracks admin /tracks | `apps/admin/src/routes/tracks.tsx@4d970bfba` | 待复核 | — | Removed in `cab115493`. Confirm: `grep -rn 'tracks' apps/admin/src/router apps/admin/src/views` |
| BLAST admin /blast | `apps/admin/src/routes/blast.tsx@4d970bfba` | 待复核 | — | Removed in `cab115493`; public `/blast` is not an admin surface. Confirm: `git log -S 'blast' --oneline -- apps/admin/src` |
| Seeds admin /seeds | `apps/admin/src/routes/seeds.tsx@4d970bfba` | 待复核 | — | Removed in `cab115493`. Confirm: `grep -rn 'seed' apps/admin/src/router` |
| Releases admin /releases | `apps/admin/src/routes/releases.tsx@4d970bfba` | implemented | `ReleasesView.vue` | Removed in `cab115493`, reintroduced in the Vue console (`router/index.ts:32`) |

Earlier-baseline tally: 1 implemented, 0 missing, 0 retired, 6 待复核.

## 6. Intentionally retired (ADR call-outs)

### ADR-0008 — /antd-pilot

- ADR: `docs/adr/0008-no-vue-antd-pilot-route.md` (status: accepted).
- React evidence: `apps/web/src/routes/_antd-pilot.tsx@d3904c210`; enumerated
  as `/antd-pilot` in `apps/web/src/routeTree.gen.ts@d3904c210`.
- Current Vue: no `/antd-pilot` in `apps/web/src/router/routes.ts`.
- ADR rationale: design-system contract lives in `packages/ui-vue/src/index.ts`
  + `packages/ui-vue/src/facade.test.ts`; tokens in
  `packages/ui-vue/src/design-tokens.ts`; history in
  `docs/ops/antd6-design-system.md`.

### ADR-0009 — page builder and widget system

- ADR: `docs/adr/0009-retire-page-builder-and-widgets.md` (status: accepted).
- React evidence (all `@2004c25c6`): `apps/admin/src/routes/page-builder/index.tsx`,
  `apps/admin/src/routes/page-builder/$pageId.tsx`,
  `apps/admin/src/routes/widgets.tsx`, `apps/admin/src/routes/widgets/$name.tsx`,
  `apps/admin/src/routes/layout.tsx`, `apps/admin/src/routes/widget-preview.tsx`,
  `apps/admin/src/routes/widget-health.tsx`; `/content/pages` mounted the page
  builder via `apps/admin/src/App.tsx`.
- Current Vue: the seven page-builder/widget paths resolve to
  `LegacyUnavailableView.vue` (`apps/admin/src/router/index.ts`). `/content/pages`
  is no longer inside the retirement boundary: it is repurposed as the
  static-page editor (`StaticPagesView.vue`) while the page builder itself stays
  retired.
- ADR boundary: `page_definitions` / widget tables and endpoints remain until a
  separate audited migration; the ADR does **not** authorise deleting them.

## 7. Vue-only routes (no React `2004c25c6` equivalent)

Recorded for completeness; these are additions, not gaps.

| Vue route | Vue file | Evidence |
| --- | --- | --- |
| /instances | `SpeciesInstancesView.vue` | `apps/admin/src/router/index.ts:42`; `SpeciesInstancesView.test.ts` |
| /settings/brand | `SiteBrandSettingsView.vue` | `apps/admin/src/router/index.ts:44`; target of the `/settings/site` redirect |

(`/releases` is listed in §5 as a reintroduction, `/table-templates` as a rename.)

## 8. Reconciliation: recovery-status section 4 and project-status.md

`docs/dev/vue-migration-recovery-status.md` says "第 6 节记录的行目取代第 4 节对应行";
the table below checks both against the current tree.

| Doc claim (source) | Current-tree evidence | Reconciliation |
| --- | --- | --- |
| §4: "P0 React->Vue 功能矩阵（admin 约 34->11 路由）— 未开始" | `apps/web/src/router/routes.ts` (35), `apps/admin/src/router/index.ts` (15 functional), `docs/wiki/applications.md` matrix | Superseded by §6.5/§7: matrix exists. Remaining gaps = 9 missing admin routes (§4) + 6 earlier-baseline 待复核 (§5). |
| §4: "P0 部署态 CSS/CSP/缓存/子路径浏览器验证 — 待复核" | §3.1/§10.3 static smoke only; no deployed-service test artefact in tree | Still **待复核**; needs a live deployment (`bash scripts/smoke.sh --profile runtime` + browser probe). |
| §4: "P0 assembly 选择与深链 — 待复核" | `apps/web/src/lib/assembly-selection.ts`; §6.1; `project-status.md` "后端 label 规范化计划中" | Code parity done; backend `assembly_id` normalization still planned. |
| §4: "P0 中英文逐页文案扫描 — 部分" | §8: budget `6 串 / 1 文件`; `scripts/visible-i18n-baseline.json` | Resolved to budget (whitelisted data values only). |
| §4: "P1 首页新闻状态机 — 待复核" | §7.2; `apps/web/src/views/HomeView.test.ts`; `featuredNewsQueryOptions` envelope validation | Resolved (E2E 29 passed / 2 skipped, §7.1). |
| §4: "P1 登录独立布局、子路径回跳 — 部分" | `LoginView.vue` + `apps/web/src/lib/redirect.ts` (+ `redirect.test.ts`) | Implemented. |
| §4: "P1 管理端 favicon、dashboard/导入/新闻 — 待复核" | §6.3 favicon + `scripts/check_app_shell_assets.py`; `ImportsView.vue`, `ImportCreateView.vue`, `ImportDetailView.vue` | favicon/imports resolved; news preview/trash still "计划中" per `docs/wiki/applications.md`. |
| §4: "P1 静态预览/部署 API base 与 CORS — 待复核" | no artefact in tree | Still **待复核**. |
| §4: "D 多实例远端写操作 — 按设计关闭" | `apps/admin/src/lib/instance-connector.ts` (`RemoteAdministrationDisabledError`) | Closed by design (unchanged). |
| §4: "E 默认 API 端口 8010 — 未开始" | §6.4 (39 files updated); `project-status.md` "默认 API 端口 8010" | Resolved. |
| §4: "F docs/wiki 与目录清理 — 未开始" | `docs/wiki/{README,architecture,applications,api-and-ports,deployment-and-ops,multi-instance}.md` | Resolved. |
| §4: "C 构建期品牌写入静态 HTML/manifest — 未开始" | `project-status.md` "构建期静态写入**计划中**" | Still planned. |
| `project-status.md`: "公共站 34 条路由全部实现" | `grep -c 'path: "' apps/web/src/router/routes.ts` -> 35 | Count is stale; behaviour parity holds (35/35 implemented). |
| `project-status.md`: "管理端 14 条路由" | `apps/admin/src/router/index.ts` -> 19 functional named routes | Count is stale; update to 19. |
| `project-status.md`: "Page Builder/内容页/Widgets/导入向导详情为计划中" | router: widgets/page-builder/layout -> `LegacyUnavailableView`; ADR-0009; `/content` and `/content/pages` -> `StaticPagesView`; imports create/detail implemented | Page builder/widgets/layout are **intentionally retired** (ADR-0009), not "planned". Content pages are now implemented as static-page management (`StaticPagesView.vue` + `packages/api-client/src/admin-content.ts`). Import wizard detail is implemented (`ImportDetailView.vue`), contradicting the doc. |
| `docs/wiki/applications.md` line 53-54: `/imports/new`, `/imports/:taskId` listed under "尚未恢复" | `apps/admin/src/router/index.ts:34-35`; `legacy-routes.test.ts` "restores the import create and detail deep links (P1-06)" | Doc error: both are restored; update the wiki list. |
| `docs/wiki/applications.md` line 6/26: web 34 / admin 14 routes | routes.ts 35; admin router 19 functional | Doc counts stale; the admin count lags by five. |

## 9. Tally

| Status | Count |
| --- | --- |
| implemented | 62 |
| documented unavailable (no API) | 1 |
| missing | 0 |
| intentionally retired w/ ADR | 9 |
| 待复核 | 6 |
| **total rows** | **78** |

Breakdown: web = 35 implemented + 2 retired (37 rows); admin `2004c25c6` =
26 implemented + 1 documented-unavailable + 7 retired (34 rows); earlier admin
`4d970bfba` = 1 implemented + 6 待复核 (7 rows).

## 10. 待复核 register (exact confirming commands)

Resolved since the audit (see §4): `/content`, `/content/pages`,
`/content/legacy`, `/analytics-settings` and the settings sub-pages are
implemented; `/resource-catalog` is an explicit documented-unavailable page. The
two former `/content` rows are removed from this register.

| Item | Command |
| --- | --- |
| `/table-views` -> `/table-templates` old deep-link reachability | `grep -n 'table-views' apps/admin/src/router/index.ts` |
| Earlier-baseline `/users` disposition | `git log --all --oneline --diff-filter=AD -- apps/admin/src/routes/users.tsx` |
| Earlier-baseline `/assemblies` disposition | `grep -rn 'assemblies' apps/admin/src/router apps/admin/src/views` |
| Earlier-baseline `/variants` disposition | `grep -rn 'variants' apps/admin/src/router` |
| Earlier-baseline `/tracks` disposition | `grep -rn 'tracks' apps/admin/src/router apps/admin/src/views` |
| Earlier-baseline `/blast` disposition | `git log -S 'blast' --oneline -- apps/admin/src` |
| Earlier-baseline `/seeds` disposition | `grep -rn 'seed' apps/admin/src/router` |
| §4 deployment-state CSS/CSP/subpath verification | `bash scripts/smoke.sh --profile runtime` plus a browser probe of the deployed origins |
| §4 static preview/deploy API base and CORS | inspect the deployed nginx/proxy config and re-run `scripts/verify-pages-artifact.sh` |
| Build-time brand into static HTML/manifest | `grep -rn 'brand' scripts/generate-static-routes.ts apps/web/index.html` |
| Backend `assembly_id` normalization | `grep -rn 'assembly_id' apps/api/src` and `docs/dev/database-core-contract.md` |
