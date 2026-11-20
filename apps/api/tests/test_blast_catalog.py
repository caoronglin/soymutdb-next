"""Catalog preparation may expose safe metadata, never dispatch future indexes."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.models.blast import BlastDatabase
from app.schemas.blast import BlastDatabaseResponse, BlastSubmitRequest
from app.services.blast_service import BlastService
from app.services.release_context import ReleaseContext


def catalog(**overrides):
    values = dict(
        id=1, name="protein", db_type="prot", assembly_id=1, is_active=True,
        engine="diamond", build_status="ready", is_default=False,
        file_path="/private/index/protein", created_at=datetime.now(UTC),
    )
    values.update(overrides)
    return BlastDatabase(**values)


def session(row):
    result = SimpleNamespace(
        scalar_one_or_none=lambda: row,
        scalars=lambda: SimpleNamespace(all=lambda: [row], first=lambda: row),
    )
    return SimpleNamespace(execute=AsyncMock(return_value=result), add=AsyncMock())


CONTEXT = ReleaseContext(release_id=1, assembly_id=1, assembly="Wm82")


@pytest.mark.parametrize("field,value", [
    ("engine", "ncbi_blast"), ("build_status", "building"),
    ("build_status", "failed"), ("build_status", "pending"),
    ("db_type", "nucl"), ("is_active", False),
])
@pytest.mark.parametrize("selector", ["id", "name", "both", "default"])
async def test_unexecutable_catalog_never_creates_job_or_outbox(
    field, value, selector, monkeypatch,
):
    from app.services import blast_service

    monkeypatch.setattr(blast_service.settings, "blast_default_db", "protein")
    row = catalog(**{field: value})
    db = session(row)
    # Fallback assembly query must find no eligible assembly; explicit catalog
    # lookups still return the incompatible row to exercise the service guard.
    original_execute = db.execute

    async def execute(statement):
        if "blast_databases" not in str(statement):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: None))
        return await original_execute(statement)

    db.execute = AsyncMock(side_effect=execute)
    selectors = {"id": {"database_id": 1}, "name": {"database": "protein"},
                 "both": {"database_id": 1, "database": "protein"}, "default": {}}
    request = BlastSubmitRequest(
        engine="diamond", query_sequence="MKVLAAGIVGLNLGGK", **selectors[selector]
    )
    with pytest.raises(NotFoundError):
        await BlastService().submit_job(db, None, request, release_context=CONTEXT)
    db.add.assert_not_called()
    discovered = await BlastService().list_databases(db, release_context=CONTEXT)
    if field == "engine":
        assert len(discovered) == 1  # Both ready engines/types are discoverable.
    else:
        assert discovered == []


async def test_public_catalog_is_an_explicit_metadata_allowlist():
    row = catalog(
        sequence_type="protein", annotation_version="a4.v1", source_url="https://soybase.org/data",
        sequence_count=56000, total_length=22000000, fasta_sha256="a" * 64,
        index_version="diamond-2.1", license="CC-BY-4.0",
        provenance={"index_prefix": "/private/index", "credential": "never-public"},
    )
    response = (await BlastService().list_databases(session(row), release_context=CONTEXT))[0]
    body = response.model_dump(mode="json")
    assert body["engine"] == "diamond"
    assert body["sequence_type"] == "protein"
    assert body["annotation_version"] == "a4.v1"
    assert body["source_url"] == "https://soybase.org/data"
    assert body["sequence_count"] == 56000
    assert body["fasta_sha256"] == "a" * 64
    assert "provenance" not in body
    assert "file_path" not in body
    assert "/private" not in str(body)
    assert "never-public" not in str(body)


@pytest.mark.parametrize("url", [
    "https://public.example/download?token=secret",
    "https://public.example/download#private/path",
    "/private/input.fa", "file:///private/input.fa", "s3://private/input.fa",
    "https://user:password@soybase.org/data", "https://127.0.0.1/data",
    "http://localhost/data", "https://10.0.0.1/data", "https://index.internal/path",
    "https://[::1]/data", "https://soybase.org:invalid/data", "https://soybase.org\n/path",
])
def test_stored_private_source_url_is_omitted(url):
    response = BlastDatabaseResponse(
        id=1, name="protein", db_type="prot", assembly_id=1,
        is_active=True, created_at=datetime.now(UTC), source_url=url,
    )
    assert response.source_url is None


async def test_published_ncbi_index_is_discoverable():
    """A worker-published catalog row must survive response validation.

    Regression: the database query selects ``published``/``ready`` rows, but
    BlastDatabaseResponse's build_status Literal used to omit ``published``,
    so GET /blast/databases raised a 500 on every newly built NCBI index.
    """
    row = catalog(engine="ncbi_blast", build_status="published")
    discovered = await BlastService().list_databases(session(row), release_context=CONTEXT)
    assert [item.build_status for item in discovered] == ["published"]
