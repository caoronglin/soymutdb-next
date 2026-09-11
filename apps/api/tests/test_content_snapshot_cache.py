"""Regression coverage for mutable content-snapshot cache invalidation."""

from __future__ import annotations

import pytest

from app.services import content_snapshot_cache


@pytest.mark.asyncio
async def test_invalidator_evicts_all_snapshot_variants(monkeypatch) -> None:
    prefixes: list[str] = []

    async def fake_delete_prefix(prefix: str) -> int:
        prefixes.append(prefix)
        return 3

    monkeypatch.setattr(content_snapshot_cache, "delete_prefix", fake_delete_prefix)

    await content_snapshot_cache.invalidate_mutable_content_snapshot()

    assert prefixes == ["content:snapshot"]

