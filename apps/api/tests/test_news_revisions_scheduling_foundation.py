"""Offline migration contract for news revision and schedule persistence."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations/versions/0031_news_revisions_scheduling.py"


def test_migration_is_ordered_additive_and_downgrade_is_guarded() -> None:
    assert MIGRATION.is_file()
    spec = importlib.util.spec_from_file_location("news_revision_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)

    assert module.revision == "0031"
    assert module.down_revision == "0030"

    source = MIGRATION.read_text()
    assert "ADD COLUMN IF NOT EXISTS lock_version" in source
    assert "ADD COLUMN IF NOT EXISTS schedule_generation" in source
    assert "news_article_revisions" in source
    assert "news_publication_schedules" in source
    assert "Cannot downgrade migration 0031" in source
