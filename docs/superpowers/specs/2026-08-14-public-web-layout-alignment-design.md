# Public Web Builder And Layout Alignment Design

Date: 2026-08-14
Status: Approved
Revised: 2026-09-29 — search tool pages separated from the portal search page, home database-entrypoint strip removed, reference details for Gene ID / Physical Location / BLAST recorded, and the remaining wireframe differences listed inline as open items.
Reference: `ui-r/网页-查询V2.pdf`

## Goal

Align the public React application with the seven-page reference layout and make the public site fully configurable through the Admin application, while preserving the existing brand system, accessibility behavior, responsive support, internationalization, dark mode, and production routes.

The reference is treated as a functional wireframe. Purple annotations, placeholder labels, spelling mistakes, and raw wireframe colors are implementation notes rather than user-facing content.

## Decisions

- Use the existing JBrowse 2 integration everywhere. Replace remaining GBrowse route names, labels, comments, and action text in the public UI with JBrowse 2 terminology.
- Preserve the current visual design system rather than copying the wireframe's cyan, green, red, and purple colors.
- Use targeted alignment instead of rewriting the public application or first introducing a broad component abstraction.
- Follow the reference module order and proportions on desktop, then adapt the same hierarchy for tablet and mobile.
- Search submissions open shareable, parameterized result views in a new browser tab, as required by the reference.
- Except for JBrowse 2 and BLAST, public pages are assembled in Admin from a fixed allowlist of safe components. Administrators can configure page structure, component visibility and order, form fields, table columns, labels, content, and approved interactions.
- Admin configuration never accepts executable JavaScript, arbitrary templates, or unsanitized HTML.
- Module data is uploaded through schema-specific TSV templates, validated, imported into release-scoped database records, and retained with the original source object for traceability.
- A successful upload means the complete upload, validation, import, static build, smoke-test, and publication pipeline succeeded. A transfer alone is never reported as a published success.
- Each publication selects one configured target: local/Nginx, GitHub Pages, or Cloudflare Pages.

## Information Architecture

The primary navigation order is fixed to:

1. Home
2. Search
3. Tools
4. Latest News
5. Contact

The reference confirms this order as 主页 / 收录 / 工具 / 最新动态 / 联系我们. As of 2026-09-29 the shipped portal header instead renders 浏览 / 工具 / 下载 / 资源 with a 最新动态 child link, so it does not yet match the approved order. That is an open implementation deviation, not an approved change to this section.

The public home page contains, in order:

1. A desktop 2:3 content grid with up to five latest-news links on the left and a three-to-six-image featured carousel on the right.
2. Five direct task entries in this order: Gene ID, Physical Location, JBrowse 2, BLAST, Primer Design.
3. The existing sanitized, CMS-managed home content block supporting text, images, video, and links.

The current hero search and statistics strip are removed because they are outside the approved reference structure. Their underlying APIs remain unchanged.

The home database-entrypoint strip — the `SOYMUTDB DATABASE` eyebrow, the `SoyMutDB 数据库` heading, the `查询数据库` link, and the 突变系 / 基因 / 变异 cards — is not part of the approved structure above. It was removed from the public React home page on 2026-09-29 to align the implementation with this section. The three destinations stay reachable through the primary navigation, the five task entries, and the resource navigation; no API, route, or i18n catalog entry was deleted.

### Search tool pages

Every search tool is a standalone page, never a section of the portal search page.

- Routes: `/search/genes` (Gene ID), `/search/location` (Physical Location), `/search/gbrowse` (JBrowse 2), `/search/blast` (BLAST), `/search/primer` (Primer Design).
- A tool page renders its own heading, its own query form and its own result table. It SHALL NOT render the portal hero, the global search box, the federated-source toggle or the aggregated portal result list — those belong to `/search` alone.
- `/search` keeps the hero, the global search box and the aggregated result list.

This is a route-architecture rule, not a styling preference. `/search` is a parent route that renders `<Outlet />`; until 2026-09-29 it also rendered the portal hero for every child, which pushed each tool's own heading and form below a full screen of unrelated portal content. The fix renders the portal block only when the path is `/search` itself.

The reference marks a secondary directory on tool pages in this order: 基因 ID / 物理位置 / JBrowse / BLAST.

## Search Flows

### Gene ID

The form contains a default API-provided genome assembly, a gene ID input, and a search action. Submission opens a parameterized `/search/genes` URL in a new tab. The result view keeps the form visible and renders these columns in reference order:

1. Genome assembly
2. Chromosome
3. Position
4. Mutation feature
5. Gene ID
6. JBrowse 2 action

Gene IDs link to gene details. The JBrowse 2 action opens a locus-specific browser view in a new tab.

Form details confirmed by the reference:

- The assembly control is a dropdown showing the default assembly with an explicit default marker; options can grow as more assemblies are released.
- The gene ID field carries a placeholder example drawn from the currently selected assembly, so the accepted identifier shape is visible before typing.
- The submit action is the only trigger; results appear in a new tab rather than replacing the page.

Open difference: the reference draws a single-line gene ID field with one example, while the current implementation accepts multiple gene IDs, one per line, and says so in a helper line. The multi-ID form is a superset of the reference behaviour and is not yet reconciled with the wireframe.

### Physical Location

The form contains an assembly, chromosome, start position, and end position. Submission opens a parameterized `/search/location` URL in a new tab. The result table follows the same six-column order as Gene ID search and links each row to JBrowse 2.

Open difference: the reference draws one combined input — `染色体号:起始点位-终止点位` (for example `Gm01:1-2000`) — while the current implementation provides four controls: an assembly dropdown, a chromosome dropdown populated from the API for the selected assembly, and separate start/end inputs. The four-control form matches the "assembly, chromosome, start position, and end position" contract in this section and keeps the chromosome list authoritative instead of parsing free text; reconciling it with the single-box wireframe is a pending decision.

### JBrowse 2

The current transfer page remains responsible for selecting an assembly and opening the existing browser route. Public route labels and content use JBrowse 2 consistently. Existing links may remain compatible internally if renaming a path would create unnecessary route churn.

### BLAST

The search entry opens the complete BLAST form rather than an intermediate explanation card. The form contains BLAST type (`blastn` or `blastp`), reference sequence type, assembly, FASTA input, and submit action. Results expose genome assembly, query sequence ID, coverage, E-value, gene ID, and JBrowse 2 actions. Gene IDs cross-link to parameterized Gene ID search results.

Form details confirmed by the reference:

- BLAST type is a dropdown limited to `blastn` and `blastp`; no other program is offered.
- The reference sequence type is the assembly version.
- The sequence input accepts FASTA format.
- Each result row carries two independent actions: the gene ID opens Gene ID search for that identifier, and the JBrowse action opens the genome browser in a new page. Both are per row, not per result set.

### Primer Design

The existing primer workflow remains available as the fifth task. Its current region and pasted-sequence modes are retained because the reference names the entry but does not specify its inner layout.

## Responsive Layout

- At 1024 px and above, preserve the home page 2:3 news/carousel proportion and horizontal task-entry row.
- From 768 px to 1023 px, allow forms and task entries to wrap while preserving reading order.
- Below 768 px, stack home modules and form controls in one column, retain the existing mobile navigation, and wrap result tables in horizontal overflow containers.
- Existing focus indicators, keyboard navigation, reduced-motion behavior, dark mode, and English/Chinese switching remain supported.

## Data And State

- Genome assemblies and their default value continue to come from the existing API.
- Query parameters are the source of truth for result views so searches are shareable and reload-safe.
- Result queries only run after validated parameters are available.
- Existing API clients and response types remain unchanged unless a verified reference field is unavailable.
- CMS home content remains sanitized with the existing DOMPurify pipeline.

## Admin Page Builder

The builder uses versioned page definitions rather than editable source code. A page definition contains route metadata, translated labels, SEO fields, responsive section layout, and an ordered component tree. Components are selected from a server-owned registry with validated configuration schemas.

The initial component allowlist contains:

- Site navigation and footer navigation
- Latest-news list and featured-media carousel
- Sanitized rich-text and media content
- Tool-entry navigation
- Assembly selector
- Gene ID and physical-location query forms
- Configurable data table and approved row actions
- Button, link, notice, divider, tabs, and responsive column layout
- JBrowse 2 launcher and BLAST launcher as dedicated components

The builder supports draft editing and preview, but the approved workflow automatically publishes after a TSV-backed change completes the full pipeline. Page definitions and data releases are immutable once published; later edits create a new version.

## TSV Import Contract

Each module type owns an explicit, downloadable TSV schema with required headers, optional headers, scalar types, null rules, unique keys, reference checks, maximum sizes, and example rows. Free-form column inference is not allowed.

The import pipeline is:

1. Upload the source object and verify checksum, size, encoding, delimiter, and header schema.
2. Create an idempotent import task and release-scoped staging data in one transactional workflow.
3. Parse and validate every row, retaining row-level diagnostics without exposing partial data publicly.
4. Bulk-load valid data into staging tables and run referential and count checks.
5. Mark the dataset ready only after all required validation evidence is stored.
6. Trigger a static publication request through a correctly named transactional outbox event.

The current CSV adapters that only count rows are not reused as evidence of import success. They must be replaced by real database writers before the new module type can be enabled.

## Static Build And Publication

The builder reads an explicit page-definition version and data release, then generates a complete static tree in a new immutable directory. It never overwrites the active tree file by file.

Each artifact manifest records the release ID, page-definition version, source checksums, generated file hashes, build time, and application version. The generated site is validated for schema conformance, unsafe markup, broken internal links, required routes, hydration, and selected end-to-end flows.

Only after every check passes does a publication adapter update its target:

- `local`: publish a version directory and atomically switch the Nginx/current pointer.
- `github_pages`: dispatch a workflow for the immutable artifact, create a complete Pages commit, and update the branch ref only after verification.
- `cloudflare_pages`: upload the immutable artifact as a deployment and promote the verified deployment to production.

The Admin environment stores one default target and allows an administrator to select a different configured target for a publication. Credentials and target settings remain server-side environment or secret-manager configuration; page definitions and TSV files cannot supply them.

Publication records store target type, target project, release ID, artifact digest, remote deployment or commit ID, status, validation evidence, and rollback pointer. Platform propagation is eventually consistent; "automatic publication" means the pipeline starts immediately and switches only after platform confirmation.

## Failure Isolation And Rollback

- Concurrent publications for the same target are serialized by a publication lease and monotonic publication ID.
- A stale job that finishes late cannot replace a newer requested publication.
- Import, generation, smoke, or remote-deployment failure leaves the current public pointer unchanged.
- Rollback selects a previously verified immutable artifact and uses the same publication adapter to restore its pointer or deployment.
- Static pages embed their release ID. Hydrated dynamic API requests include that release ID so a static page cannot silently query a different active dataset.

## Required Foundation Repairs

Implementation begins by fixing verified blockers in the existing system:

- Replace placeholder CSV/TSV adapters with real, idempotent database imports.
- Add required Celery task names and payload contracts to import and release outbox events.
- Make import state transitions persist to PostgreSQL rather than only logging.
- Align Admin Widget categories, permissions, list response shape, and health fields with the API schemas.
- Correct broken Admin content/publication endpoints before building new management screens.
- Make snapshots, API caches, and public queries release-aware.
- Escape generated URL and attribute values and enforce route, protocol, and host allowlists.

## Validation And Errors

- Empty Gene ID and FASTA values are rejected before submission.
- Physical ranges require a selected assembly and chromosome, `start >= 1`, and `end >= start`.
- BLAST validates supported type and FASTA structure before creating the result request.
- Assembly-loading failures disable dependent actions and provide retry feedback.
- Loading, empty, and request-error states are explicit and do not render sample data as real results.
- New-tab links use `noopener` or `noreferrer` as appropriate.

## Verification

Targeted tests cover:

- Primary navigation order and translated labels.
- Home module order, five-news limit, carousel placement, five task entries, and CMS content fallback.
- Desktop and mobile layout behavior.
- Default assembly selection and form validation.
- New-tab result URLs and query-parameter restoration.
- Gene and location result column order.
- BLAST-to-gene and all JBrowse 2 deep links.
- Loading, empty, failure, and retry states.
- TSV schema, delimiter, type, uniqueness, size, and row-diagnostic validation.
- Idempotent import retries and proof that failed imports expose no partial data.
- Outbox dispatch, publication serialization, stale-job rejection, and rollback.
- Builder component-schema validation and rejection of arbitrary HTML or JavaScript.
- Equivalent artifact manifests and smoke checks for local, GitHub Pages, and Cloudflare Pages adapters.

Verification runs include public-web unit tests, type checking, linting, production build, and focused Playwright coverage for the approved user flows. Existing unrelated baseline failures must be reported separately rather than hidden or weakened.

## Scope Boundaries

- No replacement of JBrowse 2 or BLAST execution infrastructure.
- No recreation of purple design annotations or placeholder copy.
- No arbitrary HTML, JavaScript, Jinja template, or third-party plugin upload through the page builder.
- No simultaneous multi-target publication in one publication job; an administrator selects one target.
- No guarantee of transactional visibility across third-party global CDNs. Each adapter provides atomic pointer/deployment switching within the capabilities of its platform.
- No redesign of MCP or unrelated analysis workflows.
- No speculative Primer Design redesign beyond fitting it into the approved navigation and responsive shell.
