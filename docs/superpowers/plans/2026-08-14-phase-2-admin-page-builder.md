# Safe Admin Page Builder Implementation Plan

> **已归档（2026-10-01）**：已被现行计划取代的历史实施计划。继任：`docs/aegis/plans/` 与 `docs/aegis/INDEX.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let administrators build every public page except BLAST and JBrowse 2 from versioned, schema-validated, safe components.

**Architecture:** Store immutable PageDefinition versions containing an ordered component tree. Validate every node against a server-owned component registry; Admin edits drafts and previews the same renderer contract used by SSG, while publication always references an immutable version.

**Tech Stack:** FastAPI, SQLAlchemy, JSON Schema/Pydantic, React 19, Ant Design, TanStack Query, Vitest.

---

## File Structure

- Create `apps/api/app/models/page_builder.py` and migration `0016_page_builder.py`.
- Create `apps/api/app/page_builder/registry.py`, `schemas.py`, and `service.py`.
- Create `apps/api/app/api/v1/admin_page_builder.py` and `apps/api/app/api/v1/page_definitions.py`.
- Create `packages/shared/src/page-builder.ts` for generated/shared DTOs.
- Create `apps/admin/src/lib/page-builder-api.ts`.
- Create `apps/admin/src/routes/page-builder/index.tsx`, `$pageId.tsx`, and components under `apps/admin/src/components/page-builder/`.
- Modify `apps/admin/src/lib/widget-api.ts` and API widget schemas/routes to reconcile existing contract mismatches first.
- Test `apps/api/tests/test_page_builder_registry.py`, `test_admin_page_builder.py`, `test_page_definition_public.py`, and Admin component tests.

### Task 1: Reconcile Existing Widget Contracts

- [ ] Add failing API-client contract tests for widget categories, permissions, list response `{items,total}`, and health fields.
- [ ] Make `apps/admin/src/lib/widget-api.ts` use exactly the enum values defined by `apps/api/app/widgets/schemas.py`.
- [ ] Make the API return the documented paginated shape or update both callers and OpenAPI to one shape; do not keep dual undocumented shapes.
- [ ] Fix the broken Admin content/publication calls by pointing the UI to existing `/admin/content/pages` and adding explicit Admin publication CRUD endpoints.
- [ ] Run `pnpm --filter @soymutdb/admin typecheck` and `apps/api/.venv/bin/python -m pytest apps/api/tests/test_widget_registry.py apps/api/tests/test_openapi_contract.py -q`.

Expected: existing Widget and content screens use one verified contract before the builder depends on them.

### Task 2: Add Versioned Page Definitions

- [ ] Write model tests proving published versions are immutable and a new edit creates a draft version.
- [ ] Add these core records:

```python
class PageDefinition(Base):
    __tablename__ = "page_definitions"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    route: Mapped[str] = mapped_column(String(160), unique=True)
    title_key: Mapped[str] = mapped_column(String(160))

class PageDefinitionVersion(Base):
    __tablename__ = "page_definition_versions"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    page_id: Mapped[UUID] = mapped_column(ForeignKey("page_definitions.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("page_id", "version"),)
```

- [ ] Validate routes with `^/[a-z0-9][a-z0-9/_-]*$`; reserve `/blast`, `/browser`, `/admin`, and `/api` from generic definitions.
- [ ] Run migration and `test_admin_page_builder.py`.

### Task 3: Implement The Safe Component Registry

- [ ] Add failing tests that reject unknown component types, unknown props, `javascript:` URLs, inline event handlers, raw scripts, and arbitrary template names.
- [ ] Define a discriminated union with initial types: `navigation`, `news_list`, `media_carousel`, `rich_text`, `tool_entries`, `assembly_select`, `gene_search_form`, `location_search_form`, `data_table`, `button`, `link`, `notice`, `divider`, `tabs`, `columns`, `jbrowse_launcher`, `blast_launcher`.
- [ ] Each registry entry exposes `config_model`, `allowed_children`, `data_binding_model`, and `renderer_key`; there is no admin-provided renderer or template path.
- [ ] Sanitize rich text through the existing server sanitizer and validate links against `http`, `https`, and internal-route allowlists.
- [ ] Run `apps/api/.venv/bin/python -m pytest apps/api/tests/test_page_builder_registry.py apps/api/tests/test_sanitize.py -q`.

### Task 4: Add Draft, Preview, Version, And Publish APIs

- [ ] Test Admin-only create/update, optimistic revision conflict (409), preview, version listing, and immutable published reads.
- [ ] Implement:

```text
GET    /api/v1/admin/page-builder/pages
POST   /api/v1/admin/page-builder/pages
GET    /api/v1/admin/page-builder/pages/{id}
PUT    /api/v1/admin/page-builder/pages/{id}/draft
POST   /api/v1/admin/page-builder/pages/{id}/preview
POST   /api/v1/admin/page-builder/pages/{id}/publish-request
GET    /api/v1/page-definitions/{route:path}?version=<uuid>
```

- [ ] `publish-request` validates the definition and emits a named `static_publish_requested` outbox event; it does not directly mutate public files.
- [ ] Audit every mutation with old/new version IDs.
- [ ] Run API tests and OpenAPI contract generation.

### Task 5: Build The Admin Editor

- [ ] Add Admin route tests for loading, validation errors, version conflict, preview, and save.
- [ ] Implement a three-pane editor: component palette, ordered page tree, schema-driven properties panel. Use existing dnd-kit patterns from `apps/admin/src/routes/layout.tsx`.
- [ ] The property editor renders only registry-declared controls: text, translated text, boolean, number, select, safe link, module binding, and approved action.
- [ ] Add a preview iframe/token endpoint that uses the same definition DTO as SSG; never inject editable scripts into the Admin origin.
- [ ] Add schema-template download and TSV upload controls that call Phase 1 APIs and display row-level diagnostics.
- [ ] Run `pnpm --filter @soymutdb/admin test -- --run` and `pnpm --filter @soymutdb/admin typecheck`.

### Task 6: Add Navigation And Query Configuration

- [ ] Seed the five approved navigation entries and reference pages through a migration or idempotent seed command.
- [ ] Allow labels, order, visibility, target, form fields, table columns, and approved row actions to be configured while preserving required validation semantics.
- [ ] Reject configurations that remove required Gene ID/location inputs or map an action to an unapproved route.
- [ ] Add tests demonstrating that JBrowse 2 and BLAST use dedicated launcher components rather than arbitrary generic page implementations.

### Task 7: Phase Verification

- [ ] Run: `apps/api/.venv/bin/python -m pytest apps/api/tests/test_page_builder_registry.py apps/api/tests/test_admin_page_builder.py apps/api/tests/test_page_definition_public.py apps/api/tests/test_widget_registry.py -q`
- [ ] Run: `pnpm --filter @soymutdb/admin lint`
- [ ] Run: `pnpm --filter @soymutdb/admin typecheck`
- [ ] Run: `pnpm --filter @soymutdb/admin test -- --run`

Expected: an administrator can create and preview the seven reference pages from safe components; attempts to inject HTML scripts, JS URLs, or arbitrary renderer names are rejected.
