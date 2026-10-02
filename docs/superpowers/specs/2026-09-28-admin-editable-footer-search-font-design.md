# Admin-Editable Public Footer, Search Workflow, and Typography Design

**Status:** The user approved the scope, direction, and written defaults/bounds. A subsequent direct goal-continuation request authorizes local implementation and synthetic tests under the scoped plan; live Admin writes, deployment, and replacement preview servers remain unauthorized.

**Date:** 2026-09-28

**Parent objective:** Improve the public portal while preserving the database-first workflow, external/internal boundaries, and existing biological/API contracts.

## 1. Context and evidence

The existing approved portal remediation specification covers active React routes, localization, and page-level readability. It explicitly excludes Admin changes and a global font-family change. The user's latest request adds those topics; this document defines that separate, bounded slice.

- The Admin Settings page already has an external/internal footer editor for contact person, phone, email, address, and copyright. It is not bilingual and uses the existing footer settings namespace.
- `GET /site/footer?variant=...` currently returns those five legacy fields. External content is public/cacheable; internal content requires an authenticated viewer and is private/no-store.
- The active React footer renders only legacy copyright and address. It does not render contact fields or navigation. The static navigation found in the old Vue `PortalFooter.vue` is not in the active React import graph. The active React header has the Explore, Tools, Downloads, and Resources groups.
- The active React `/search` route already accepts `types`, `cursor`, `limit`, and `assembly` URL state. Its catalog API returns `by_type`, `ambiguous`, `by_assembly`, `next_cursor`, and `has_more`, but the active page does not expose corresponding controls. Result descriptions/snippets can be truncated to one line.
- The active React entry imports `apps/web/src/index.css`. It currently uses a system CJK stack and a 16px / 1.65 body baseline. The three local HarmonyOS files are not used by that entry and are approximately 4.28 MB (Regular), 4.34 MB (Medium), and 4.40 MB (Bold). The stylesheet deliberately deferred loading these multi-megabyte assets.
- The user selected public contact display; bilingual person/address/copyright values; shared phone/email with localized labels; editable grouped footer navigation seeded from the active React header groups; the database-search workflow slice; and HarmonyOS Regular-only loading for the public React site.

## 2. Goals

1. Let Admins edit the public footer's bilingual contact/copyright content and grouped navigation, and render those saved values on the active public React site.
2. Improve the existing public catalog search workflow with filters and pagination already supported by the API, while making assembly ambiguity explicit.
3. Use the self-hosted HarmonyOS face on the active public React site without requesting the three-weight 12.7 MB family.
4. Preserve API compatibility, existing URL state, public/internal data boundaries, and all biological identity, assembly, release, and provenance contracts.

## 3. Footer design

### 3.1 Admin fields and public rendering

Extend the existing Site Settings footer card. Keep the explicit external/internal variant selector and show an Admin notice that external footer content is public.

Fields maintained per site variant:

- Contact person: `contact_person_en`, `contact_person_zh`.
- Phone and email: shared raw values, `contact_phone_value`, `contact_email_value`; labels come from the current English/Chinese locale, not from stored values.
- Address: `address_en`, `address_zh`.
- Copyright: `copyright_en`, `copyright_zh`.
- Footer navigation: bilingual groups and links, described below.

The active React footer renders contact person, phone, email, address, copyright, and navigation. It uses plain text rendering, localized labels, and responsive wrapping; phone/email become `tel:`/`mailto:` links only after their values pass safe validation. The footer stacks on narrow viewports and uses responsive columns at larger widths. Primary footer text and link targets are at least 14px; secondary metadata is at least 12px. Footer links remain distinct from the active top navigation; editing the footer does not edit the header.

Phone and email may be empty. A non-empty email must pass server-side email validation; a phone `tel:` target is built only from an allowlisted phone format and normalized to an optional leading `+` followed by digits. The visible phone value remains unchanged. Never interpolate an unvalidated value into an `href`.

The new fields take precedence per field and selected language. Existing response fields (`contact_person`, `contact_phone`, `contact_email`, `address`, `copyright`) remain available for old clients. Until a new value is saved, the active footer may fall back to the corresponding legacy value; strip only these recognized leading labels: `联系人:` / `联系人：`, `电话:` / `电话：`, `电子邮件:` / `电子邮件：`, and `地址:` / `地址：`. Do not machine-translate free text. Legacy values are not rewritten automatically.

### 3.2 Editable grouped navigation

The Admin editor provides add, remove, enable/disable, and reorder operations for groups and links. Group titles and link labels have English and Chinese values. Link destinations are either:

- an origin-relative internal path beginning with exactly one `/`, with no scheme, protocol-relative prefix, backslash, or control characters; or
- an absolute HTTPS URL with no embedded username/password.

The API rejects `javascript:`, `data:`, `http:`, protocol-relative, malformed, or overlong destinations. External links render with safe `rel` attributes. Values are plain text; arbitrary HTML is not accepted.

Initial groups are copied from the active React header, skipping its visual separators:

- Explore: `/genes`, `/variants`, `/mutants`, `/browser`, `/sra`, `/compare`, `/analytics`.
- Tools: `/blast`, `/analyses`, `/tools/seqfetch`, `/tools/enrichment`, `/tools/exppattern`, `/tools`.
- Downloads: `/downloads`.
- Resources: `/guide`, `/help`, `/news`, `/publications`, `/seed-request`, `/about`.

Labels start from the existing English/Chinese navigation catalogs. This is an editable starting configuration, not a live binding to the header. The footer may subsequently differ from the header. The old Vue footer link list is not used as the source because it is not active.

The stored setting is a JSON string with `schema_version: 1` and a `groups` array. Each group has a stable slug `id`, bilingual titles, `enabled`, nonnegative integer `order`, and `links`. Each link has a stable slug `id`, bilingual labels, `target` (`internal` or `external`), `href`, `enabled`, and nonnegative integer `order`. Group IDs are unique; link IDs are unique within their group. Reject unknown keys and invalid schema versions. Sort by `order`, using the stable ID as a deterministic tie-breaker. On read-time parse/validation failure, fail closed to the built-in default groups and emit a sanitized diagnostic. The Admin UI edits these fields through a form builder, not a raw JSON editor.

The following initial bounds are proposed for review:

- At most 6 groups and 32 links total.
- Group titles and link labels are at most 80 characters.
- Link destinations are at most 2,048 characters.
- Serialized navigation is at most 32 KiB.
- Stable IDs and explicit order/enabled fields are preserved across edits.

### 3.3 Storage, API, and compatibility

Reuse the existing variant-specific, versioned `system_settings` store; do not add a database table or another authoritative content store. Add a registered `footer_navigation_json` setting under the existing footer base section so the current external/internal variant definitions continue to isolate values. Validate and canonicalize this JSON on the server before persistence.

The Admin editor uses the typed versioned settings client (`adminSettingsApi.get` / `patch`) with expected-version conflict handling and the existing audit history. It sends the navigation as a serialized setting value; the Admin UI is a form builder, not a raw JSON editor.

Extend `FooterContentResponse` and `@soymutdb/api-client` additively with the bilingual values and a structured `navigation` response. Retain the legacy response keys. `GET /site/footer` continues to select the explicit variant; external cache policy and internal authentication/private cache policy remain unchanged. The API defaults provide the initial grouped links when no saved variant-specific value exists.

### 3.4 Privacy and safety

Public contact information is explicitly in scope per user approval. Admin must make the external variant's public visibility obvious. No implementation step changes production settings or uses production values in tests. Before production rollout, an authorized Admin must review the actual external contact values.

Tests use only synthetic names, phone numbers, addresses, email addresses, and link URLs. External/internal isolation, authentication, and cache policy are regression-tested. Unsafe link configurations are rejected server-side even if the Admin client is bypassed.

## 4. Public search workflow design

### 4.1 Scope

Improve the active public catalog search in `/search` when the external-source toggle is off. Do not change the API endpoint or its response contract. Do not change the internal search behavior or the federated external-source response, because those flows do not expose the same type/cursor/assembly controls.

### 4.2 Interactions

- Add localized entity-type filters for the canonical supported values: `gene`, `variant`, `mutant_line`, `phenotype`, and `publication`. Show `by_type` counts where available. An empty selection means all current types, matching today's unfiltered behavior.
- Add an assembly selector populated by the existing assembly endpoint under the current release context. Use the existing `assembly` URL parameter as the selected assembly ID.
- When the API marks an unscoped result set ambiguous, show that state and per-assembly context/counts. Do not silently apply the default assembly. Keep results visibly labeled by assembly and allow the user to select an assembly to narrow the query.
- Add next/previous cursor controls using `next_cursor` and `has_more`. Keep an in-memory cursor stack for previous-page navigation, push the current cursor on Next, and disable Previous when no prior cursor is known (including a deep link loaded directly at a cursor). Keep `q`, `types`, `assembly`, `limit`, and `cursor` synchronized with the URL; changing the query or filters clears the cursor history.
- Wrap result descriptions and federated snippets instead of silently truncating the only visible line.
- Keep the external-source toggle and current result links, IDs, provenance, release labels, and assembly labels intact. Type/assembly/pagination controls are not presented as if they filter federated hits.

### 4.3 Invariants

- Preserve route path `/search` and the existing URL parameter names and types.
- Preserve the current query-key dimensions: site variant, release, assembly, query, filters, cursor, limit, and federated mode.
- External results never expose `internal_id`; internal search remains server-authorized and unchanged.
- Do not silently collapse cross-assembly matches, select the default assembly for ambiguous results, infer v4/v5 equivalence, or alter IDs, aliases, provenance, NCBI source behavior, or release/assembly contracts.

## 5. Typography design

Apply the selected font family only to the active public React site:

- Declare and use `HarmonyOS-Sans-SC-Regular.woff2` in `apps/web/src/index.css` for the public site's body and display family, with the existing system CJK stack as fallback.
- Use `font-display: swap`; load only the Regular file and allow the browser to synthesize heavier weights. Do not preload it. Do not load Medium or Bold.
- Keep the global 16px / 1.65 body baseline and existing hierarchy unless route-level visual evidence justifies a targeted adjustment. Continue the existing minimum readability guidance for route labels and metadata.
- Do not alter Admin, JBrowse, or the retired Vue stylesheet as part of this font slice.

The Regular face is approximately 4.28 MB. Before considering the typography slice verified, measure the same representative mobile/desktop routes before and after under the same network conditions and record the median of at least three runs. Confirm only the Regular asset is requested. Proposed performance gate: LCP regression is no more than 10% from the system-font baseline, CLS remains at or below 0.1, and CLS does not increase by more than 0.02. If the gate fails or measurement is unavailable, do not claim the font change is verified; revisit the font strategy with the user.

## 6. Out of scope

- Editable top navigation, homepage navigation, social-media blocks, legal-link blocks, or arbitrary HTML.
- New database tables, migrations, or an additional authoritative content store.
- Search endpoint, search request/response contract, route, or biological data changes.
- Changes to GoatCounter, ClickHouse collection, analytics dashboards, Admin/JBrowse redesign, or NCBI behavior in this slice.
- Any production Admin write, publish, import, deletion, or data mutation.

## 7. Verification and acceptance

### Footer

- API unit/integration tests cover default navigation, valid grouped edits, limits, malformed JSON, unsafe destinations, and legacy-field compatibility.
- Variant boundary tests prove external responses contain only external footer settings and remain public/cacheable; internal requests require the existing viewer authorization and return private/no-store headers.
- Admin tests cover bilingual input, external/internal switching, add/remove/reorder groups and links, validation, version conflict, and save success using synthetic fixtures.
- Public component tests cover locale selection, labels, phone/email links, legacy fallback, link rendering, and responsive wrapping.
- Validate generated OpenAPI/client types and preserve legacy fields.

### Search

- Route tests cover type filters/counts, assembly selection, ambiguous multi-assembly results without a silent default, cursor next/previous, URL synchronization, reset behavior, and snippet wrapping.
- Confirm catalog search includes all cache-key dimensions and that the external-source and internal-search branches are not accidentally given unsupported controls.

### Typography and artifacts

- Confirm the active React build requests only the Regular font, uses fallback text before swap, and has no font-related clipped controls or horizontal overflow.
- Record before/after LCP and CLS using the same viewport/network conditions; report any material change rather than claiming a pass without measurement.
- Run locale parity, visible-copy checks, focused route tests, and external/internal artifact builds. Screenshot visual acceptance remains pending until a SoyMutDB preview URL is supplied; the DSH GUI URL is not a substitute.

### Environment boundary

No isolated writable Admin test environment, Admin credentials, or SoyMutDB preview URL has been supplied. Code-level tests must use synthetic fixtures/mocks. Do not run Admin writes against production. Manual Admin save-and-public-render E2E and published-route screenshots remain blocked until the user supplies the isolated environment and preview URL.

## 8. Change necessity and architecture review

Code changes are necessary because the Admin already stores footer contact fields but the active React footer hides them, grouped navigation has no active React renderer or settings contract, the search page does not expose API-supported facets/cursors/assembly disambiguation, and the active React stylesheet does not use the selected local font.

This design reuses the existing versioned settings store, variant namespaces, API endpoint, and query contracts. No new database/table or authoritative owner is introduced. No separate ADR is required; the custom JSON validation and public/internal boundary require focused independent review during implementation.

## 9. Implementation boundary

The implementation plan is created only after the user reviews this written specification. Before source edits, record a fresh `TaskStartSnapshot`, preserve all existing dirty/untracked files, do not stage or commit, and use only synthetic data for all Admin write tests. TDD mode is off; verification and regression tests are still required.
