"""Regression for the native deployment verifier's fresh-row seeding helper."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SeedRow(Base):
    __tablename__ = "native_export_seed_test"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String)


def load_verifier():
    path = Path(__file__).parent / "dev" / "verify-native-export-chain.py"
    spec = importlib.util.spec_from_file_location("native_export_verifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Session:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = []
        self.flushed = False

    async def execute(self, _statement):
        return SimpleNamespace(scalar_one_or_none=lambda: self.existing)

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        self.flushed = True
        for row in self.added:
            row.id = 42


def test_fresh_row_is_returned_after_flush():
    session = Session()
    result = asyncio.run(load_verifier()._find_or_create(
        session, SeedRow, {"description": "fresh fixture"}, name="chain-assembly",
    ))
    assert session.flushed
    assert result is session.added[0]
    assert result.id == 42
    assert result.name == "chain-assembly"
    assert result.description == "fresh fixture"


def test_existing_row_is_updated_and_returned_without_duplicate():
    existing = SeedRow(id=7, name="chain-assembly", description="old")
    session = Session(existing)
    result = asyncio.run(load_verifier()._find_or_create(
        session, SeedRow, {"description": "updated"}, name="chain-assembly",
    ))
    assert result is existing
    assert result.description == "updated"
    assert result.id == 7
    assert session.flushed
    assert session.added == []
