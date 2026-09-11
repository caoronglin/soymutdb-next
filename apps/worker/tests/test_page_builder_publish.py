"""Tests for durable Page Builder version publication."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from soymutdb_worker.tasks import page_builder_publish


@contextmanager
def _session_context(session):
    yield session


def _run_with_status(monkeypatch, status: str, *, rowcount: int = 1):
    session = MagicMock()
    selected = MagicMock()
    selected.scalar_one_or_none.return_value = status
    updated = MagicMock()
    updated.rowcount = rowcount
    session.execute.side_effect = [selected, updated]
    monkeypatch.setattr(
        page_builder_publish,
        "get_db",
        lambda: _session_context(session),
    )
    page_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    result = page_builder_publish.publish_definition.run(
        page_id=page_id,
        version_id=version_id,
    )
    return result, session


def test_requested_version_is_published(monkeypatch) -> None:
    result, session = _run_with_status(monkeypatch, "requested")

    assert result["status"] == "published"
    assert result["changed"] is True
    assert session.execute.call_count == 2


def test_redelivery_of_published_version_is_noop(monkeypatch) -> None:
    session = MagicMock()
    selected = MagicMock()
    selected.scalar_one_or_none.return_value = "published"
    session.execute.return_value = selected
    monkeypatch.setattr(
        page_builder_publish,
        "get_db",
        lambda: _session_context(session),
    )

    result = page_builder_publish.publish_definition.run(
        page_id=str(uuid.uuid4()),
        version_id=str(uuid.uuid4()),
    )

    assert result["status"] == "published"
    assert result["changed"] is False
    assert session.execute.call_count == 1


@pytest.mark.parametrize("status", ["draft", "preview"])
def test_invalid_lifecycle_state_is_rejected(monkeypatch, status: str) -> None:
    with pytest.raises(ValueError, match="expected requested"):
        _run_with_status(monkeypatch, status)
