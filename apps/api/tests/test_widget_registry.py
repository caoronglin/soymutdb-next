"""Unit tests for the widget data-source registry."""

from __future__ import annotations

import importlib
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.core.exceptions import ValidationError
from app.widgets.data_sources.registry import WIDGET_DATA_SOURCE_REGISTRY
from app.widgets.router import _load_data_source


def _widget(source: str) -> Any:
    return cast(Any, SimpleNamespace(name="test_widget", data_source=source))


@pytest.mark.asyncio
async def test_registered_data_source_runs_through_registry(monkeypatch) -> None:
    calls: list[tuple[dict, object]] = []

    async def fake_handler(params, db):
        calls.append((params, db))
        return {
            "run": {"Run": params["run"]},
            "run_accession": params["run"],
            "fetch_error": None,
            "is_fallback": True,
        }

    original = WIDGET_DATA_SOURCE_REGISTRY["sra_run"]
    monkeypatch.setitem(
        WIDGET_DATA_SOURCE_REGISTRY,
        "sra_run",
        replace(original, handler=fake_handler),
    )

    db: Any = object()
    context = await _load_data_source(
        _widget("sra_run"),
        {"run": "SRR30334525"},
        db,
    )

    assert context["run_accession"] == "SRR30334525"
    assert calls == [({"run": "SRR30334525"}, db)]


@pytest.mark.asyncio
async def test_unknown_data_source_is_rejected_without_import(monkeypatch) -> None:
    def fail_import(*_args, **_kwargs):
        raise AssertionError("database value must never reach importlib")

    monkeypatch.setattr(importlib, "import_module", fail_import)

    with pytest.raises(ValidationError) as raised:
        await _load_data_source(
            _widget("os.system"),
            {},
            cast(Any, None),
        )

    assert "not registered" in str(raised.value).lower()


@pytest.mark.asyncio
async def test_registered_data_source_validates_parameters(monkeypatch) -> None:
    async def fake_handler(_params, _db):
        return {"ok": True}

    original = WIDGET_DATA_SOURCE_REGISTRY["sra_run"]
    monkeypatch.setitem(
        WIDGET_DATA_SOURCE_REGISTRY,
        "sra_run",
        replace(original, handler=fake_handler),
    )

    with pytest.raises(ValidationError) as raised:
        await _load_data_source(_widget("sra_run"), {"run": ""}, cast(Any, None))

    assert raised.value.error_code == "validation_error"
