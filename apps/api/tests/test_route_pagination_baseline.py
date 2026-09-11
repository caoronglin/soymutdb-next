"""A-19 guard for the reviewed pagination contract baseline only."""

from __future__ import annotations

from app.core.route_inventory import inventory_paginated_routes
from app.main import create_app


# This is intentionally not a repository-wide demand for pagination. It
# freezes the small set of collection routes that were reviewed for A-19 and
# already expose a bounded pagination interface. Extend it only as routes are
# explicitly reviewed and adopted into the migration baseline.
PAGINATION_BASELINE = {
    ("/api/v1/admin/imports", ("GET",)): ("page", "page_size"),
    ("/api/v1/admin/media", ("GET",)): ("page", "page_size"),
    ("/api/v1/admin/news", ("GET",)): ("page", "page_size"),
    ("/api/v1/admin/page-builder/pages", ("GET",)): ("page", "page_size"),
    ("/api/v1/admin/publication", ("GET",)): ("page", "page_size"),
    ("/api/v1/admin/publications", ("GET",)): ("page", "page_size"),
    ("/api/v1/homologs/search", ("GET",)): ("cursor", "page", "page_size"),
    ("/api/v1/search", ("GET",)): ("cursor", "limit"),
    ("/api/v1/variants", ("GET",)): ("cursor", "limit"),
}


def test_a19_pagination_baseline_is_complete_and_exact() -> None:
    observed = {
        (item.path, item.methods): item.query_parameters
        for item in inventory_paginated_routes(create_app().routes)
        if (item.path, item.methods) in PAGINATION_BASELINE
    }
    assert observed == PAGINATION_BASELINE


def test_pagination_inventory_ignores_unscoped_legacy_routes() -> None:
    """The guard inventories declarations; it does not infer missing migration work."""
    inventory = inventory_paginated_routes(create_app().routes)
    assert all(item.query_parameters for item in inventory)
    assert any(item.path == "/api/v1/mutants" for item in inventory)
    assert ("/api/v1/mutants", ("GET",)) not in PAGINATION_BASELINE
