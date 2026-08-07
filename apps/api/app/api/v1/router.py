"""Aggregated v1 router – mounts every endpoint module.

This is the single entry point imported by ``app.main``.  It ensures that
all modular routers are registered (no placeholder routes).
"""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    admin,
    admin_content,
    admin_imports,
    admin_settings,
    admin_static,
    analyses,
    analytics,
    auth,
    blast,
    content,
    expression,
    genes,
    health,
    homolog,
    mutants,
    releases,
    search,
    seeds,
    sra,
    stats,
    tools_exppattern,
    tracks,
    variants,
    tools_seqfetch,
    tools_enrichment,
)
from ...widgets.router import router as widgets_router

api_router = APIRouter()

# Mount every endpoint module.
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(genes.router)
api_router.include_router(variants.router)
api_router.include_router(tools_seqfetch.router)
api_router.include_router(search.router)
api_router.include_router(stats.router)
api_router.include_router(blast.router)
api_router.include_router(analyses.router)
api_router.include_router(tracks.router)
api_router.include_router(releases.router)
api_router.include_router(mutants.router)
api_router.include_router(seeds.router)
api_router.include_router(content.router)
api_router.include_router(admin.router)
api_router.include_router(admin_content.router)
api_router.include_router(admin_imports.router)
api_router.include_router(admin_settings.router)
api_router.include_router(admin_static.router)
api_router.include_router(expression.router)
api_router.include_router(homolog.router)
api_router.include_router(analytics.router)
api_router.include_router(sra.router)
api_router.include_router(tools_enrichment.router)
api_router.include_router(tools_exppattern.router)
api_router.include_router(widgets_router)

__all__ = ["api_router"]
