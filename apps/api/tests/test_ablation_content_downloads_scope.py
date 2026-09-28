"""Ablation guards for the public content downloads boundary.

The review found ``DownloadFile`` reads were entirely unscoped:

* ``GET /content/downloads`` selected **every** row, and ``download_files.
  release_id`` is nullable — so draft-release and release-unbound files were
  listed publicly;
* ``GET /content/downloads/{id}/url`` looked the row up by primary key alone,
  so any id (including a draft's) could be signed;
* a presign failure fell back to returning the raw ``s3://bucket/key`` path,
  which the client cannot fetch, and a non-S3 location was returned verbatim
  regardless of scheme.

Unit-level guards (no PostgreSQL): the route coroutines are driven with a fake
session that records the compiled SQL.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import Response

from app.api.v1 import content as content_routes
from app.core.exceptions import NotFoundError, ServiceUnavailableError, ValidationError
from app.services.release_context import ReleaseContext

_RELEASE_ID = 7


def _context(release_id: int = _RELEASE_ID) -> ReleaseContext:
    return ReleaseContext(release_id=release_id, assembly_id=3, assembly="Wm82.a4.v1")


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def scalars(self) -> _Rows:
        return self

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows[0] if self._rows else 0


class _RecordingDb:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.statements: list[Any] = []
        self._rows = list(rows or [])

    async def execute(self, statement: Any) -> _Rows:
        self.statements.append(statement)
        return _Rows(self._rows)

    async def scalar(self, statement: Any):
        self.statements.append(statement)
        return 0

    def sql(self, index: int = -1) -> str:
        return str(self.statements[index])


def _download(
    *,
    file_id: int = 1,
    file_url: str = "https://files.example/x.vcf.gz",
    release_id: int | None = _RELEASE_ID,
):
    from app.models.content import DownloadFile

    row = DownloadFile(
        id=file_id,
        name="variants.vcf.gz",
        file_url=file_url,
        file_size=1024,
        category="variants",
        release_id=release_id,
        download_count=0,
    )
    row.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    row.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    return row


# ---------------------------------------------------------------------------
# 1. Listing is bound to the published release.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_list_filters_on_the_resolved_release():
    """Ablation: dropping the predicate re-exposes draft/unbound files."""
    db = _RecordingDb([_download()])

    await content_routes.list_downloads(
        db=db, release_context=_context(), category=None
    )

    sql = db.sql(0)
    assert "download_files.release_id" in sql, sql
    bound = set(db.statements[0].compile().params.values())
    assert _RELEASE_ID in bound, bound


@pytest.mark.asyncio
async def test_download_list_keeps_the_category_filter():
    db = _RecordingDb([_download()])

    await content_routes.list_downloads(
        db=db, release_context=_context(), category="variants"
    )

    sql = db.sql(0)
    assert "download_files.release_id" in sql, sql
    assert "download_files.category" in sql, sql


# ---------------------------------------------------------------------------
# 2. The URL endpoint is a release-scoped lookup, not a bare primary key.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_url_lookup_is_release_scoped():
    db = _RecordingDb([_download()])

    await content_routes.get_download_url(
        file_id=1, response=Response(), db=db, release_context=_context()
    )

    sql = db.sql(0)
    assert "download_files.id" in sql, sql
    assert "download_files.release_id" in sql, sql


@pytest.mark.asyncio
async def test_a_file_outside_the_release_is_not_found():
    """The fake returns no row, which is what the release predicate produces."""
    db = _RecordingDb([])

    with pytest.raises(NotFoundError):
        await content_routes.get_download_url(
            file_id=99, response=Response(), db=db, release_context=_context()
        )


# ---------------------------------------------------------------------------
# 3. The returned URL is a safe, fetchable target and is never cached.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_https_location_is_returned_and_marked_private():
    db = _RecordingDb([_download(file_url="https://files.example/x.vcf.gz")])
    response = Response()

    signed = await content_routes.get_download_url(
        file_id=1, response=response, db=db, release_context=_context()
    )

    assert signed.url == "https://files.example/x.vcf.gz"
    # A download link is a capability: no shared or browser cache may keep it.
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Vary"] == "Authorization"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hostile",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "ftp://files.example/x",
    ],
)
async def test_unsupported_schemes_are_refused(hostile: str):
    db = _RecordingDb([_download(file_url=hostile)])

    with pytest.raises(ValidationError):
        await content_routes.get_download_url(
            file_id=1, response=Response(), db=db, release_context=_context()
        )


@pytest.mark.asyncio
async def test_presign_failure_fails_closed_instead_of_leaking_the_raw_path(
    monkeypatch,
):
    """Ablation: the fallback used to return ``s3://bucket/key`` verbatim."""
    db = _RecordingDb([_download(file_url="s3://bucket/key.vcf.gz")])

    def _boom(*args: Any, **kwargs: Any):
        raise RuntimeError("no credentials")

    monkeypatch.setattr(content_routes, "generate_presigned_url", _boom)

    with pytest.raises(ServiceUnavailableError):
        await content_routes.get_download_url(
            file_id=1, response=Response(), db=db, release_context=_context()
        )


@pytest.mark.asyncio
async def test_successful_presign_is_returned(monkeypatch):
    db = _RecordingDb([_download(file_url="s3://bucket/key.vcf.gz")])
    monkeypatch.setattr(
        content_routes,
        "generate_presigned_url",
        lambda url, expires_in=3600: "https://s3.example/signed?token=abc",
    )

    signed = await content_routes.get_download_url(
        file_id=1, response=Response(), db=db, release_context=_context()
    )

    assert signed.url.startswith("https://s3.example/signed")
