"""Aggregated v1 router – mounts every endpoint module.

This is the single entry point imported by ``app.main``.  It ensures that
all modular routers are registered (no placeholder routes).
"""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    admin,
    admin_content,
    admin_features,
    admin_imports,
    admin_media,
    admin_modules,
    admin_news,
    admin_page_builder,
    admin_plugins,
    admin_publication,
    admin_publications,
    admin_settings,
    admin_static,
    admin_table_views,
    admin_uploads,
    analyses,
    analytics,
    assemblies,
    auth,
    blast,
    capabilities,
    comparative,
    content,
    export_query,
    expression,
    genes,
    gwas,
    health,
    homolog,
    import_studio,
    jobs,
    mutants,
    news,
    notifications,
    ontology,
    page_definitions,
    popgen,
    preview_test_data,
    releases,
    search,
    seed_requests,
    seeds,
    site,
    sra,
    stats,
    table_views,
    tools_enrichment,
    tools_exppattern,
    tools_intervals,
    tools_seqfetch,
    tools_sequence,
    tracks,
    variants,
)

# NOTE: this import must stay AFTER the ``from . import (...)`` block:
# ``widgets.models`` imports ``app.models.base``, and importing it first
# would trigger the ``app.models`` package init while ``widgets.models`` is
# still partially initialized (circular import).
from ...widgets.router import router as widgets_router  # isort: skip

api_router = APIRouter()

# Mount every endpoint module.
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(genes.router)
api_router.include_router(assemblies.router)
api_router.include_router(gwas.router)
api_router.include_router(jobs.router)
api_router.include_router(popgen.router)
api_router.include_router(preview_test_data.router)
api_router.include_router(variants.router)
api_router.include_router(tools_seqfetch.router)
api_router.include_router(tools_sequence.router)
api_router.include_router(tools_intervals.router)
api_router.include_router(search.router)
api_router.include_router(stats.router)
api_router.include_router(blast.router)
api_router.include_router(analyses.router)
api_router.include_router(tracks.router)
api_router.include_router(releases.router)
api_router.include_router(mutants.router)
api_router.include_router(table_views.router)
api_router.include_router(seeds.router)
api_router.include_router(seed_requests.router)
api_router.include_router(content.router)
api_router.include_router(export_query.router)
api_router.include_router(news.router)
api_router.include_router(notifications.router)
api_router.include_router(ontology.router)
api_router.include_router(page_definitions.router)
api_router.include_router(admin.router)
api_router.include_router(admin_features.router)
api_router.include_router(admin_content.router)
api_router.include_router(admin_media.router)
api_router.include_router(admin_news.router)
api_router.include_router(admin_page_builder.router)
api_router.include_router(admin_plugins.router)
api_router.include_router(admin_publication.router)
api_router.include_router(admin_publications.router)
api_router.include_router(admin_imports.router)
api_router.include_router(import_studio.router)
api_router.include_router(admin_modules.router)
api_router.include_router(admin_settings.router)
api_router.include_router(admin_static.router)
api_router.include_router(admin_table_views.router)
api_router.include_router(admin_table_views.species_router)
api_router.include_router(admin_uploads.router)
api_router.include_router(expression.router)
api_router.include_router(homolog.router)
api_router.include_router(comparative.router)
api_router.include_router(analytics.router)
api_router.include_router(site.router)
api_router.include_router(capabilities.router)
api_router.include_router(sra.router)
api_router.include_router(tools_enrichment.router)
api_router.include_router(tools_exppattern.router)
api_router.include_router(widgets_router)

__all__ = ["api_router"]
