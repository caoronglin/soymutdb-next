"""Seed the initial Page Builder definitions (idempotent).

Creates seven published reference-page definitions and the fixed five-entry
primary navigation (Home / Search / Tools / Latest News / Contact), matching
the approved public-web IA.  BLAST and JBrowse 2 are *not* seeded here — they
are dedicated launchers served by their own code, so their routes stay
reserved from generic definitions.

Run from the repository root::

    python -m apps.api.app.scripts.seed_page_builder

Idempotent: existing routes are skipped (their definitions are never
overwritten), missing routes are created with a published version 1.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from ..core.database import close_db, get_session_factory
from ..models.page_builder import (
    PageDefinition,
    PageDefinitionStatus,
    PageDefinitionVersion,
)
from ..page_builder.registry import validate_definition

logger = logging.getLogger("seed_page_builder")

NAV_ITEMS = [
    {"label": "Home", "route": "/"},
    {"label": "Search", "route": "/search"},
    {"label": "Tools", "route": "/tools"},
    {"label": "Latest News", "route": "/latest-news"},
    {"label": "Contact", "route": "/contact"},
]

# route -> (title_key, root component tree)
SEED_PAGES: list[tuple[str, str, dict]] = [
    (
        "/",
        "nav.home",
        {
            "root": {
                "type": "columns",
                "props": {"columns": 1},
                "children": [
                    {
                        "type": "navigation",
                        "props": {
                            "title": "Site Navigation",
                            "items": [
                                {"label": i["label"], "route": i["route"]}
                                for i in NAV_ITEMS
                            ],
                        },
                    },
                    {
                        "type": "tool_entries",
                        "props": {
                            "entries": [
                                "Gene ID",
                                "Physical Location",
                                "JBrowse 2",
                                "BLAST",
                                "Primer Design",
                            ]
                        },
                    },
                    {
                        "type": "news_list",
                        "props": {"limit": 5},
                    },
                    {
                        "type": "rich_text",
                        "props": {"content": "<p>SoyMutDB home content</p>"},
                    },
                ],
            }
        },
    ),
    (
        "/search",
        "nav.search",
        {
            "root": {
                "type": "columns",
                "props": {"columns": 1},
                "children": [
                    {
                        "type": "assembly_select",
                        "props": {"default_assembly": "Glycine max"},
                    },
                    {
                        "type": "gene_search_form",
                        "props": {"title": "Gene ID Search"},
                    },
                    {
                        "type": "location_search_form",
                        "props": {"title": "Physical Location Search"},
                    },
                ],
            }
        },
    ),
    (
        "/tools",
        "nav.tools",
        {
            "root": {
                "type": "columns",
                "props": {"columns": 1},
                "children": [
                    {
                        "type": "tool_entries",
                        "props": {
                            "entries": [
                                "Gene ID",
                                "Physical Location",
                                "JBrowse 2",
                                "BLAST",
                                "Primer Design",
                            ]
                        },
                    },
                    {
                        "type": "jbrowse_launcher",
                        "props": {"assembly": "Glycine max"},
                    },
                    {
                        "type": "blast_launcher",
                        "props": {"program": "blastn"},
                    },
                ],
            }
        },
    ),
    (
        "/latest-news",
        "nav.latest_news",
        {
            "root": {
                "type": "columns",
                "props": {"columns": 1},
                "children": [
                    {
                        "type": "news_list",
                        "props": {"limit": 10},
                    },
                ],
            }
        },
    ),
    (
        "/contact",
        "nav.contact",
        {
            "root": {
                "type": "columns",
                "props": {"columns": 1},
                "children": [
                    {
                        "type": "rich_text",
                        "props": {"content": "<p>Contact SoyMutDB</p>"},
                    },
                    {
                        "type": "link",
                        "props": {"label": "Email", "href": "mailto:"},
                    },
                ],
            }
        },
    ),
    (
        "/search/genes",
        "nav.search_genes",
        {
            "root": {
                "type": "columns",
                "props": {"columns": 1},
                "children": [
                    {
                        "type": "gene_search_form",
                        "props": {"title": "Gene ID Results"},
                    },
                    {
                        "type": "data_table",
                        "props": {
                            "columns": [
                                "Assembly",
                                "Chromosome",
                                "Position",
                                "Mutation Feature",
                                "Gene ID",
                                "JBrowse 2",
                            ]
                        },
                    },
                ],
            }
        },
    ),
    (
        "/search/location",
        "nav.search_location",
        {
            "root": {
                "type": "columns",
                "props": {"columns": 1},
                "children": [
                    {
                        "type": "location_search_form",
                        "props": {"title": "Physical Location Results"},
                    },
                    {
                        "type": "data_table",
                        "props": {
                            "columns": [
                                "Assembly",
                                "Chromosome",
                                "Position",
                                "Mutation Feature",
                                "Gene ID",
                                "JBrowse 2",
                            ]
                        },
                    },
                ],
            }
        },
    ),
]


async def seed() -> dict[str, int]:
    """Seed pages and navigation.  Returns ``{"created": N, "skipped": M}``."""
    factory = get_session_factory()
    created = 0
    skipped = 0

    async with factory() as db:
        for route, title_key, definition in SEED_PAGES:
            existing = await db.scalar(
                select(PageDefinition).where(PageDefinition.route == route)
            )
            if existing is not None:
                skipped += 1
                continue

            # Validate + clean through the registry before persisting.
            cleaned = validate_definition({**definition, "title_key": title_key})

            page = PageDefinition(route=route, title_key=title_key)
            db.add(page)
            await db.flush()

            version = PageDefinitionVersion(
                page_id=page.id,
                version=1,
                status=PageDefinitionStatus.PUBLISHED,
                definition=cleaned,
                edited_by=None,
                edit_comment="seeded initial definition",
                published_at=datetime.now(UTC),
            )
            db.add(version)
            created += 1

        await db.commit()
        logger.info("seed_page_builder created=%d skipped=%d", created, skipped)
        return {"created": created, "skipped": skipped}


async def _main() -> None:
    result = await seed()
    print(f"[seed_page_builder] created={result['created']} skipped={result['skipped']}")
    await close_db()


def main() -> None:
    """Console-script entry point."""
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(_main())


if __name__ == "__main__":
    main()
