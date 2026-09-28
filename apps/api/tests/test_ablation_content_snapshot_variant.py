"""Content-snapshot variant isolation and sanitization (service level).

Two public-boundary defects motivated these guards:

1. ``GET /content/snapshot`` declared a ``variant`` parameter but the internal
   builder call dropped it, so an internal build received the *external*
   ``about.*`` namespace — the two site artifacts shared bytes.
2. ``about.content_en`` / ``content_zh`` and published static-page bodies were
   emitted verbatim, unlike ``/site/about`` which sanitizes on read. Any legacy
   write that bypassed the CMS sanitizer became an unsanitized public HTML
   source for SSG.

Both are unit-level here (no PostgreSQL needed): the service is driven with a
minimal fake session that records the statement and returns canned rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.site_variant import SiteVariant
from app.services.content_snapshot_service import ContentSnapshotService

_SCRIPTED = '<p>body</p><script>alert(1)</script><a href="javascript:alert(2)">x</a>'


class _ScalarRows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarRows:
        return self

    def all(self) -> list[Any]:
        return self._rows


class _FakeSession:
    """Returns the rows it holds, whatever the statement asks for.

    The assertions are about which *values* the service chose, so the fake does
    not filter. ``statements`` is kept so a test can assert the settings lookup
    is a single round trip.
    """

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _ScalarRows:
        self.statements.append(statement)
        return _ScalarRows(self._rows)


def _setting(key: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(key=key, value=value)


def _service() -> ContentSnapshotService:
    return ContentSnapshotService()


# ---------------------------------------------------------------------------
# 1. Variant namespace isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_about_prefers_the_variant_namespace_over_legacy():
    """Ablation: dropping the `variant` argument collapses both variants."""
    db = _FakeSession(
        [
            _setting("about.title_en", "Legacy Title"),
            _setting("about_internal.title_en", "Internal Title"),
            _setting("about_external.title_en", "External Title"),
        ]
    )
    service = _service()

    internal = await service._load_about(db, variant=SiteVariant.INTERNAL)  # noqa: SLF001
    external = await service._load_about(db, variant=SiteVariant.EXTERNAL)  # noqa: SLF001

    assert internal["title_en"] == "Internal Title"
    assert external["title_en"] == "External Title"
    assert internal["title_en"] != external["title_en"]


@pytest.mark.asyncio
async def test_about_falls_back_to_legacy_only_when_the_variant_key_is_absent():
    """Migration compatibility: an unsaved variant revision still renders."""
    db = _FakeSession([_setting("about.title_en", "Legacy Title")])

    internal = await _service()._load_about(db, variant=SiteVariant.INTERNAL)  # noqa: SLF001

    assert internal["title_en"] == "Legacy Title"
    # Selected + legacy keys are fetched together, not per key.
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_about_returns_none_for_keys_absent_from_both_namespaces():
    db = _FakeSession([_setting("about_external.title_en", "Only Title")])

    values = await _service()._load_about(db, variant=SiteVariant.EXTERNAL)  # noqa: SLF001

    assert values["title_en"] == "Only Title"
    assert values["content_en"] is None


# ---------------------------------------------------------------------------
# 2. Sanitization on read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rich_about_values_are_sanitized_on_read():
    """A `<script>`/`javascript:` that bypassed the CMS sanitizer is stripped."""
    db = _FakeSession([_setting("about_external.content_en", _SCRIPTED)])

    values = await _service()._load_about(db, variant=SiteVariant.EXTERNAL)  # noqa: SLF001

    content = values["content_en"]
    assert content is not None
    assert "<script>" not in content
    assert "javascript:" not in content
    assert "body" in content


@pytest.mark.asyncio
async def test_non_rich_about_values_are_not_html_processed():
    """Plain fields keep their text; sanitizing them would be lossy."""
    db = _FakeSession([_setting("about_external.summary_en", "a & b < c")])

    values = await _service()._load_about(db, variant=SiteVariant.EXTERNAL)  # noqa: SLF001

    assert values["summary_en"] == "a & b < c"


@pytest.mark.asyncio
async def test_static_page_bodies_are_sanitized_on_read():
    page = SimpleNamespace(
        id="7",
        slug="guide",
        title_en="Guide",
        title_zh=None,
        content_en=_SCRIPTED,
        content_zh=None,
        status="published",
        category=None,
        summary=None,
        sort_order=0,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    pages = await _service()._load_static_pages(_FakeSession([page]))  # noqa: SLF001

    assert len(pages) == 1
    content = str(pages[0]["content_en"])
    assert "<script>" not in content
    assert "javascript:" not in content
    assert "body" in content
