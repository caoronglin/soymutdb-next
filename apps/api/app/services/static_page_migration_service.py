"""Safe idempotent legacy StaticPage migration."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.content import StaticPage
from ..models.page_builder import PageDefinition, PageDefinitionStatus, PageDefinitionVersion
from ..page_builder.registry import validate_definition, validate_route

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StaticPageMigrationItem:
    static_page_id: int
    slug: str
    route: str
    outcome: str
    error_code: str | None = None
    message: str | None = None


@dataclass
class StaticPageMigrationReport:
    dry_run: bool
    items: list[StaticPageMigrationItem] = field(default_factory=list)

    @property
    def created(self) -> int:
        return sum(item.outcome == "created" for item in self.items)

    @property
    def skipped(self) -> int:
        return sum(item.outcome == "skipped" for item in self.items)

    @property
    def invalid(self) -> int:
        return sum(item.outcome == "invalid" for item in self.items)


def route_for_static_page(page: StaticPage) -> str:
    """Map legacy public SSG content to its future Page Builder route."""
    return validate_route(f"/pages/{page.slug}")


def convert_to_definition(page: StaticPage) -> dict[str, object]:
    """Return a validated v2 draft definition without changing the source page."""
    children = [{"type": "rich_text", "props": {"content": page.content_en}}]
    # RichTextConfig currently has one content field, so retain Chinese as a
    # separate node rather than silently discarding it.
    if page.content_zh:
        children.append({"type": "rich_text", "props": {"content": page.content_zh}})
    return validate_definition(
        {
            "schema_version": 2,
            "title_key": f"page.{page.slug}.title",
            "root": {"type": "columns", "props": {"columns": 1}, "children": children},
            "data_sources": [],
            "theme_id": "scientific-light",
            "layouts": {"desktop": {}, "tablet": {}, "mobile": {}},
        }
    )


async def migrate_static_pages(
    db: AsyncSession, *, dry_run: bool = True, slugs: Iterable[str] | None = None,
) -> StaticPageMigrationReport:
    """Create draft definitions only; keep every legacy record unchanged.

    Target route existence makes retries idempotent. Dry runs validate and
    report every item without adding rows or committing a transaction.
    """
    selected = set(slugs) if slugs is not None else None
    statement = select(StaticPage).order_by(StaticPage.id.asc())
    if selected is not None:
        statement = statement.where(StaticPage.slug.in_(selected))
    pages = list((await db.execute(statement)).scalars().all())
    report = StaticPageMigrationReport(dry_run=dry_run)

    for page in pages:
        fallback_route = f"/pages/{page.slug}"
        try:
            route = route_for_static_page(page)
            definition = convert_to_definition(page)
        except Exception:
            logger.exception("StaticPage migration preview failed for page_id=%s", page.id)
            report.items.append(
                StaticPageMigrationItem(
                    page.id,
                    page.slug,
                    fallback_route,
                    "invalid",
                    "invalid_static_page",
                    "The legacy page cannot be converted to a Page Builder draft.",
                )
            )
            continue

        existing = await db.scalar(select(PageDefinition.id).where(PageDefinition.route == route))
        if existing is not None:
            report.items.append(
                StaticPageMigrationItem(
                    page.id,
                    page.slug,
                    route,
                    "skipped",
                    "target_route_exists",
                    "A Page Builder page already exists for this route.",
                )
            )
            continue

        if not dry_run:
            definition_page = PageDefinition(route=route, title_key=f"page.{page.slug}.title")
            db.add(definition_page)
            await db.flush()
            db.add(
                PageDefinitionVersion(
                    page_id=definition_page.id,
                    version=1,
                    status=PageDefinitionStatus.DRAFT,
                    definition=definition,
                    edited_by=page.author_id,
                    edit_comment=f"Migrated from StaticPage:{page.id}",
                )
            )
        report.items.append(StaticPageMigrationItem(page.id, page.slug, route, "created"))

    if not dry_run and report.created:
        await db.commit()
    return report
