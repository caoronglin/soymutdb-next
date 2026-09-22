"""Phase 1 / P1-2: disabled import types fail closed at the API boundary.

Regression lock: the 7 classic scientific import types default OFF
(``core.features``) and must be rejected with a clear ``ValidationError``
(HTTP 422) BEFORE any Celery dispatch, so a user action never creates a
worker ``fail-closed`` task.  See ADR-0005 and
``docs/ops/phase-0-fact-baseline-2026-09-20.md`` (D5).
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin_imports import _require_import_type_enabled
from app.core.exceptions import ValidationError

# The seven classic scientific import types whose durable writers are not yet
# closed (core/features.py defaults them to False).
DISABLED_TYPES = [
    "fasta",
    "gff3",
    "vcf",
    "blast_db",
    "seed_data",
    "expression_csv",
    "homolog_csv",
]

# The one import type with a working persistence writer, enabled by default.
ENABLED_TYPES = ["module_tsv"]


@pytest.mark.parametrize("import_type", DISABLED_TYPES)
async def test_disabled_import_type_rejected_before_dispatch(
    db_session: AsyncSession, import_type: str
) -> None:
    """A disabled type raises up front (-> 422), never a queued fail-closed task."""
    with pytest.raises(ValidationError):
        await _require_import_type_enabled(db_session, import_type)


@pytest.mark.parametrize("import_type", ENABLED_TYPES)
async def test_enabled_import_type_passes_gate(
    db_session: AsyncSession, import_type: str
) -> None:
    """An enabled type is not blocked by the capability gate."""
    await _require_import_type_enabled(db_session, import_type)


async def test_unknown_import_type_rejected(db_session: AsyncSession) -> None:
    """An unmapped import type is rejected, not silently accepted."""
    with pytest.raises(ValidationError):
        await _require_import_type_enabled(db_session, "not_a_real_type")
