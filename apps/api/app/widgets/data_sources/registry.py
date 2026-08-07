"""Explicit registry for widget data sources.

Database values are stable registry identifiers only. A registry entry keeps
the executable handler, input schema, timeout, and output schema together so
database content can never select an arbitrary Python import path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .sra import sra_run_context

WidgetDataSourceHandler = Callable[
    [dict[str, Any], Any], Awaitable[dict[str, Any]]
]


class SraRunParams(BaseModel):
    """Validated parameters accepted by the SRA run data source."""

    run: str = Field(default="SRR30334525", min_length=1, max_length=64)

    @field_validator("run")
    @classmethod
    def normalize_run(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("run must not be empty")
        return value


class SraRunContext(BaseModel):
    """Return contract for the SRA run data source."""

    model_config = ConfigDict(extra="allow")

    run: dict[str, Any]
    run_accession: str
    fetch_error: str | None = None
    is_fallback: bool = True


@dataclass(frozen=True)
class WidgetDataSourceSpec:
    """Executable and validation contract for one registry identifier."""

    identifier: str
    handler: WidgetDataSourceHandler
    params_schema: type[BaseModel]
    timeout_seconds: float
    return_schema: type[BaseModel]


WIDGET_DATA_SOURCE_REGISTRY: dict[str, WidgetDataSourceSpec] = {
    "sra_run": WidgetDataSourceSpec(
        identifier="sra_run",
        handler=sra_run_context,
        params_schema=SraRunParams,
        timeout_seconds=15.0,
        return_schema=SraRunContext,
    ),
}


def get_widget_data_source(identifier: str) -> WidgetDataSourceSpec | None:
    """Return a registered data source by its stable identifier."""
    return WIDGET_DATA_SOURCE_REGISTRY.get(identifier.strip())


__all__ = [
    "SraRunContext",
    "SraRunParams",
    "WIDGET_DATA_SOURCE_REGISTRY",
    "WidgetDataSourceSpec",
    "get_widget_data_source",
]
