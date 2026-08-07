# SoyMutDB Next - Architecture Design

## 1. Widget System Architecture

### Database Models
- `widgets` table: id, name (unique), category, template_path, data_source, params_schema (JSONB), cache_ttl, admin_config (JSONB), permissions, is_active, created_at, updated_at
- `page_layouts` table: id, page_name (unique), widget_order (JSONB array of widget names/ids), created_at, updated_at
- Migration: new Alembic migration 0004

### Backend Structure (apps/api/app/widgets/)
- `__init__.py`
- `registry.py` - Widget registry, lazy loading
- `models.py` - SQLAlchemy Widget, PageLayout models
- `schemas.py` - Pydantic schemas for Widget config, layout
- `renderer.py` - Jinja2 rendering engine with bleach sanitization
- `cache.py` - Redis cache layer for rendered fragments
- `router.py` - FastAPI routes: /layout/{page}, /widget/{name}
- `loader.py` - Data source loaders (static, api, postgres, external, dynamic)
- `base.py` - Base widget class
- `health.py` - Widget health metrics (latency, cache hit rate, errors)
- `templates/` - Jinja2 templates for built-in widgets
  - `hero.html.j2`
  - `stats.html.j2`
  - `search_bar.html.j2`
  - `variant_table.html.j2`
  - `gene_detail.html.j2`
  - `chromosome_view.html.j2`
  - `external_result.html.j2`
  - `error.html.j2`

### API Endpoints
- `GET /api/v1/layout/{page}` -> JSON list of widget descriptors for SSG/admin
- `GET /api/v1/widget/{name}?params=...` -> text/html (sanitized fragment)
- `POST /api/v1/admin/widgets` -> create widget (admin)
- `PUT /api/v1/admin/widgets/{name}` -> update widget (admin)
- `DELETE /api/v1/admin/widgets/{name}` -> delete widget (admin)
- `GET /api/v1/admin/widgets` -> list all widgets (admin)
- `GET /api/v1/admin/layout/{page}` -> get layout (admin)
- `PUT /api/v1/admin/layout/{page}` -> update layout ordering (admin)
- `POST /api/v1/admin/widgets/{name}/preview` -> preview with test params (admin)
- `GET /api/v1/admin/widgets/health` -> health metrics (admin)

### Sanitization Pipeline
1. Jinja2 autoescape=True for all templates
2. bleach.clean() on rendered output with allowed tags/attributes
3. Allowed tags: div, span, p, a, h1-h6, ul, ol, li, table, thead, tbody, tr, th, td, img, br, strong, em, code, pre, section, article, header, footer, small, button, input, form, label, select, option, svg, path, g, circle, rect (safe subset)
4. Allowed attributes: href, src, alt, title, class, id, data-*, type, name, value, placeholder, colspan, rowspan, selected, disabled, checked, viewBox, fill, d, cx, cy, r, x, y, width, height
5. CSS allowed only via class attributes, no inline style by default

### Cache Strategy
- Cache key: `widget:{name}:{sha256(params_json)}`
- L1: in-process LRU (template cache)
- L2: Redis with configurable TTL per widget
- Cache stampede protection: Redis lock per key
- Prewarm: SSG build hits all public page layouts
- Admin can invalidate cache per widget

---

## 2. Search System Architecture

### Backend Structure (apps/api/app/search/)
- `__init__.py`
- `router.py` - FastAPI route returning text/html
- `aggregator.py` - Parallel source aggregation with circuit breaker
- `sanitizer.py` - Bleach sanitization for search results
- `cache.py` - Search result cache
- `adapters/` - Per-source adapters
  - `base.py` - Base adapter class with timeout/rate-limit/retry
  - `ncbi.py` - NCBI E-utilities (esearch/esummary)
  - `uniprot.py` - UniProt REST API
  - `ensembl.py` - Ensembl REST API
  - `embl_ebi.py` - EMBL-EBI Search API
- `templates/`
  - `search_results.html.j2` - Main results container
  - `source_group.html.j2` - Per-source results group
  - `result_item.html.j2` - Individual result item
  - `source_error.html.j2` - Degraded source error
  - `empty.html.j2` - No results
- `models.py` - Circuit breaker state tracking

### Circuit Breaker
- States: CLOSED (normal), OPEN (failing, skip), HALF_OPEN (testing)
- Config: failure_threshold=5, recovery_timeout=30s, half_open_max=1
- Per-source state stored in Redis with TTL

### HTML Fragment Response
- Returns `text/html; charset=utf-8`
- Structure: div with data-source attributes, per-source sections
- Includes source status badges (available/degraded/unavailable)
- All external data sanitized through bleach before template rendering

### Cache
- Key: `search:{query_hash}:{sources_hash}`
- TTL: 5 minutes (configurable per source)
- External source responses cached individually too

---

## 3. Frontend SSG Architecture

### Build Scripts (apps/web/scripts/)
- `ssg-build.ts` - Main SSG builder
  1. Fetch /api/v1/layout/{page} for index, about, browse, search
  2. Fetch /api/v1/widget/{name} for each widget in layout (static/cacheable)
  3. Assemble complete HTML from base template + widget fragments
  4. Write to dist/{page}.html
- `generate-samples.ts` - Sample page generator
  1. Fetch variant list from API
  2. For each variant, render sample detail page
  3. Write to dist/samples/{id}.html
- `gzip-compress.ts` - Post-build gzip pre-compression
  1. Find all .html, .css, .js in dist/
  2. Create .gz files alongside originals

### Widget Loader (apps/web/src/lib/widget-loader.ts)
- fetchWidgetFragment(name, params): Promise<string>
- Fetches from /api/v1/widget/{name} with Accept: text/html
- Sanitizes with DOMPurify before returning
- Uses Trusted Types policy if available
- Caches in memory (Map)

### Dynamic Insertion
- Widget containers: `<div data-widget="{name}" data-widget-params='{...}'>`
- widget-loader.ts finds all containers on page load
- Fetches dynamic widgets (data_source=dynamic/external)
- Inserts sanitized HTML with animation (GSAP fade in)
- Respects reduced-motion preference

### SSG Base Template
- Wraps widget fragments with proper HTML document
- Includes CSS, fonts, i18n data, theme init script
- Widget placeholders replaced at build time for static widgets
- Dynamic widgets leave placeholder for runtime fetch

### Pages
- / (index.html) - Hero + Stats + Browse preview + Search bar
- /about.html - About SoyMutDB
- /browse.html - Data browser with filter widgets
- /search.html - Search page with dynamic results area
- /samples/{id}.html - Individual variant pages
- /guide.html - User guide
- /downloads.html - Downloads page
- /publications.html - Publications
- /help.html - Help/FAQ

---

## 4. Admin Panel Extensions

### New Routes (apps/admin/src/routes/)
- `widgets.tsx` - Widget Manager (list, create, edit, delete)
- `widgets/$name.tsx` - Widget detail editor
- `layout.tsx` - Layout Editor (drag-and-drop per page)
- `widget-preview.tsx` - Widget preview sandbox
- `widget-health.tsx` - Widget health dashboard (latency, cache, errors)

### Key Components
- WidgetForm: edit name, category, template, params_schema, cache_ttl, etc.
- LayoutEditor: drag-and-drop reorder, add/remove widgets per page
- WidgetPreview: render widget with test params (iframe sandbox)
- HealthChart: latency percentiles, cache hit rate, error rates over time

### Security
- Dev server binds to 127.0.0.1 only
- All admin API endpoints require JWT auth
- Nginx /admin/ location has allowlist for private networks

---

## 5. Analytics System

### Track Pixel Endpoint
- `GET /api/v1/track.gif` - 1x1 transparent GIF response
- Query params: event type, page, widget, referrer, data
- Async: writes to ClickHouse via background task (Celery)
- Does not block response
- Respects DNT header

### ClickHouse Schema
- `events` table: timestamp, session_id, event_type, page, path, widget_name, search_query, source, referrer, user_agent, ip_hash, duration_ms
- Materialized views for: pageviews per hour, popular samples, search queries, widget usage

### Admin Dashboard
- Visits over time (line chart)
- Top pages (bar chart)
- Search query frequency
- Widget health (latency, error rate, cache hit)
- External source availability

---

## 6. Nginx / Infrastructure Updates

### Nginx Changes
- Add `gzip_static on;` for static file locations
- Add `/admin/` location with allowlist (127.0.0.1, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- Add `/samples/` static file serving
- Add `/track.gif` proxy to API (no cache, no rate limit)
- Update CSP to allow inline styles for widget rendering
- Add immutable cache headers for hashed assets

### Admin Binding
- Vite dev: --host 127.0.0.1 (already --host 0.0.0.0, need to change)
- Production nginx: allowlist enforced

### Docker Updates
- Add bleach, jinja2 to API dependencies (Jinja2 likely already present via FastAPI/Starlette)
- Add DOMPurify to web/admin dependencies
- Ensure worker has all needed deps for cache warmup tasks

---

## 7. Dependencies to Add

### Backend (apps/api/pyproject.toml)
- `jinja2>=3.1.0` (templating - check if already transitive)
- `bleach>=6.0.0` (HTML sanitization)

### Frontend (apps/web/package.json)
- `dompurify>=3.2.0` (client-side HTML sanitization)
- `@types/dompurify` (dev)
- `sortablejs` (for admin layout drag/drop - admin only)

### Admin (apps/admin/package.json)
- `dompurify>=3.2.0`
- `@types/dompurify` (dev)
- `@dnd-kit/core` (drag and drop for layout editor)
- `@dnd-kit/sortable`
- `@dnd-kit/utilities`
