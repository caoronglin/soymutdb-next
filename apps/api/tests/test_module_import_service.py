"""Regression coverage for module TSV import publication boundaries."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.data_publishing import DataSet, ImportStatus
from app.models.module_data import ModuleDataRow
from app.models.outbox import OutboxEvent
from app.services.module_import_service import import_rows


@pytest.mark.asyncio
async def test_ready_module_data_does_not_implicitly_request_static_publication(
    db_session,
) -> None:
    """A publication target is required and must be selected explicitly."""
    dataset = await import_rows(
        db_session,
        module_key="genes",
        release_id=1,
        checksum="a" * 64,
        rows=[
            {
                "gene_id": "Gm01g00001",
                "chromosome": "1",
                "start": 1,
                "end": 2,
            }
        ],
    )

    assert dataset.status == ImportStatus.READY.value
    assert (
        await db_session.scalars(
            select(ModuleDataRow).where(ModuleDataRow.release_id == 1)
        )
    ).all()
    assert (
        await db_session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == str(dataset.id),
                OutboxEvent.event_type == "static_publish_requested",
            )
        )
    ).all() == []

    persisted = await db_session.get(DataSet, dataset.id)
    assert persisted is not None
    assert persisted.manifest["module_key"] == "genes"
