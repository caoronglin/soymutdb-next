# Configurable Table Views and the Species Instance Registry

Status: implemented (backend + portal + admin), PostgreSQL-verified.
Migration: `0039_table_views_and_species_instances`.

This document describes how a portal table's columns are decided, who can change
them, and how one admin console manages more than one deployed species database.

## Why the columns are configuration

A SoyMutDB deployment shows a *lot* of tabular data, and the column order, the
labels, and which optional columns exist are operational decisions, not code
decisions. Hard-coding them makes every re-ordering a frontend release and makes
it impossible for two deployments of the same commit to show different layouts.

The portal therefore asks the API for its column set:

```
GET /api/v1/table-views/{kind}?species=...&variant=external|internal
```

`kind` is one of `mutation_sites`, `variants`, `genes`, `mutant_lines`.

The response is a vocabulary, never biological data:

```json
{
  "kind": "mutation_sites",
  "species": "Glycine max",
  "site_variant": "external",
  "release_id": 7,
  "template_id": 12,
  "template_name": "mutation sites (with homologs)",
  "is_builtin_default": false,
  "columns": [
    {"key": "mutant_line_name", "label_zh": "株系", "label_en": "Mutant line", "visible": true},
    {"key": "confidence",       "label_zh": "可信度", "label_en": "Confidence", "visible": true}
  ],
  "actions": {"jbrowse": true, "genome_preview": true}
}
```

### Built-in default (mutation sites)

The default column order is the product requirement, and it deliberately does
**not** include the cross-assembly homolog columns:

1. `mutant_line_name` — 株系
2. `mutation_system` — 突变体系（株系母+位置）, derived as `<line>·<position>`
   when the payload has no precomputed label
3. `chromosome` — 染色体号
4. `position` — 位点
5. `confidence` — 可信度（`H`/`M`/`L` rendered as 高/中/低）
6. `gene_id` — 基因号
7. `feature` — 特征
8. `available` — 可获得（`true`/`false` rendered as `Y`/`N`）

The homolog columns (`W82_V2`, `W82_V4`, `DN53_V1`, …) are opt-in. Rendering
them by default would show an empty cell for a deployment that never imported
those crosswalk rows, and an empty cell reads as "no observation" instead of
"this deployment does not have this column". An operator adds them explicitly,
per species.

A homolog column is keyed `homolog:<species-or-version>`, e.g.
`homolog:W82_V2`. It matches an entry of the row's `homologs` array whose
`species` equals that suffix, and renders `—` when there is none. A missing value
is never coerced to `0` or to an empty string.

## Resolution order

`GET /table-views/{kind}` resolves, most specific first:

1. a template with `species`, `site_variant` **and** `release_id` equal to the
   request's release;
2. a template with the same `species` + `site_variant` and `release_id IS NULL`
   (the deployment-wide layout), the `is_default` row winning when several
   exist;
3. the built-in default.

Without a release context (no pinned release, no active release) only
deployment-wide templates are eligible — a release-pinned layout is never served
to a request that has no release identity.

## Site variant boundary

The site variant is an explicit request parameter. It is never inferred from a
header, host, cookie or user agent.

* `variant=external` — anonymous read allowed.
* `variant=internal` — **requires authentication**. The internal artifact is a
  separate security boundary; an anonymous caller must not be able to enumerate
  what an internal deployment shows.

Templates are never shared across variants, so an internal-only column can never
leak into the external artifact.

## Managing templates (admin)

`apps/admin` → `/table-views`:

* pick the table kind, species, and site variant;
* reorder columns, toggle visibility, add or remove columns (the homolog family
  is offered explicitly);
* enable/disable the trailing `JBrowse 2` and gene-preview actions;
* optionally pin the template to a release;
* save it as a named template and promote it to the default.

Promotion is exclusive: exactly one default exists per
`(kind, species, site_variant, release scope)`, enforced both in the service and
by a partial unique index on `coalesce(release_id, 0)`.

Admin endpoints (administrator role required, all mutations audited):

```
GET    /api/v1/admin/table-views?kind=&species=
POST   /api/v1/admin/table-views
PUT    /api/v1/admin/table-views/{id}
DELETE /api/v1/admin/table-views/{id}
```

## Species instance registry (multi-server, one console)

`species_instances` registers each deployed species database:

| column | meaning |
| --- | --- |
| `code` | stable short code (`soy`, `maize`) |
| `name`, `species` | operator-facing names |
| `api_base_url` | the instance's API origin |
| `jbrowse_base_url`, `portal_base_url` | its browser/portal origins |
| `is_enabled` | administrative switch |
| `is_local` | **exactly one** row is local (partial unique index) |

The registry exists so one admin console can address several servers. It is a
*registry*, not a merge: each instance keeps its own PostgreSQL, its own
releases, and its own table templates. Nothing in this feature reads across
instances, and no biological record is copied between them.

Admin endpoints:

```
GET    /api/v1/admin/species-instances
POST   /api/v1/admin/species-instances
PUT    /api/v1/admin/species-instances/{id}
DELETE /api/v1/admin/species-instances/{id}
```

### What the registry does not do yet

Pointing the console at a *remote* instance requires a decision this change does
not make for you: either each instance grants the console's browser origin CORS
and API access (simplest, keeps per-instance auth), or the local API proxies
administrative calls to the peer (keeps one credential set, needs a
trusted-network assumption). `is_local` + `api_base_url` are recorded so either
direction can be implemented without a data migration.

## Portal rendering

`apps/web-vue/src/components/ConfigurableTable.vue` renders whatever the
template says, in that order, and nothing else:

* columns with `visible: false` are not rendered;
* values are rendered as text, never as HTML;
* `homolog:*` columns resolve from the row's homolog list;
* `confidence` is localised (`H/M/L` → 高/中/低);
* booleans render `Y`/`N`;
* the trailing JBrowse / gene-preview buttons follow the template's `actions`.

## Tests

* `apps/api/tests/test_table_views.py` — resolution order, site-variant
  isolation, built-in default (including "homolog columns are opt-in"), default
  exclusivity, update semantics, one-local-instance invariant.
* `apps/api/tests/test_migrations.py::test_0039_...` — the migration's tables,
  constraints and the `coalesce(release_id, 0)` index, plus the downgrade.
* `apps/web-vue/src/components/ConfigurableTable.test.ts` — column order,
  derived `mutation_system`, homolog rendering and its `—` fallback, hidden
  columns, optional actions, API resolution.

Run them with the local PostgreSQL fixture environment documented in
`docs/dev/mamba-validation-environment.md`:

```bash
cd apps/api
export SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55433/soymutdb_testfixtures'
.venv/bin/python -m pytest tests/test_table_views.py tests/test_migrations.py -q
```
