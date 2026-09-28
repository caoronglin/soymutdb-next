"""OPT-04: the external ``public_id IS NOT NULL`` predicate is redundant defence.

cache-site.md I1: the external mutant-line search carries both
``public_id IS NOT NULL`` and ``public_id ILIKE pattern``.  ``ILIKE`` evaluates
to NULL (never true) on a NULL column, so the explicit predicate can never
change which rows match; it is kept as defence in depth so a future change to
the matching expression cannot silently leak rows with no public identity.

This test pins the redundancy on a PostgreSQL fixture whose NULL-``public_id``
row is eligible on *every other* axis, then executes the service's own compiled
statement with and without the predicate and asserts identical results.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql

from app.core.site_variant import SiteVariant
from app.models.content import Release, ReleaseStatus
from app.models.variant import MutantLine
from app.services.search_service import SearchService

_PREDICATE = "mutant_lines.public_id IS NOT NULL"


class _EmptyRows:
    def all(self) -> list[Any]:
        return []


class _CapturingDb:
    """Capture the statement the real service builds without touching a DB."""

    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _EmptyRows()


async def _captured_external_sql(release_id: int) -> str:
    db = _CapturingDb()
    await SearchService()._search_mutant_lines(
        db,
        "SMOPT04",
        "%SMOPT04%",
        10,
        release_id=release_id,
        site_variant=SiteVariant.EXTERNAL,
    )
    return str(
        db.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def _executable(sql: str) -> str:
    """Make ``literal_binds`` output runnable as raw SQL.

    ``literal_binds`` renders the ILIKE escape character as ``'\\\\'`` (two
    backslashes), which PostgreSQL rejects; the real bound query passes a
    single-character escape.
    """
    return sql.replace("ESCAPE '\\\\'", "ESCAPE '\\'")


@pytest.mark.asyncio
async def test_dropping_the_public_id_predicate_keeps_results(db_session):
    release = Release(
        version="opt04-release",
        name="opt04 release",
        status=ReleaseStatus.PUBLISHED,
    )
    db_session.add(release)
    await db_session.flush()

    db_session.add_all(
        [
            MutantLine(
                public_id="SMOPT04001",
                name="opt04 public line",
                release_id=release.id,
                is_public=True,
                is_deleted=False,
            ),
            MutantLine(
                public_id=None,
                name="SMOPT04 null line",
                release_id=release.id,
                is_public=True,
                is_deleted=False,
            ),
        ]
    )
    await db_session.flush()

    # The NULL row is a meaningful probe: it satisfies every other eligibility
    # axis, so only the public-identity match can exclude it.
    probe = (
        await db_session.execute(
            select(MutantLine).where(MutantLine.name == "SMOPT04 null line")
        )
    ).scalar_one()
    assert probe.public_id is None
    assert probe.is_public is True
    assert probe.is_deleted is False
    assert probe.release_id == release.id

    sql = await _captured_external_sql(release.id)
    assert _PREDICATE in sql
    without_predicate_sql = re.sub(rf"\s+AND\s+{re.escape(_PREDICATE)}", "", sql)
    assert without_predicate_sql != sql

    with_predicate = (await db_session.execute(text(_executable(sql)))).all()
    without_predicate = (
        await db_session.execute(text(_executable(without_predicate_sql)))
    ).all()

    # Dropping the predicate is a behavioural no-op ...
    assert with_predicate == without_predicate
    # ... because the ILIKE term already excludes the NULL row.
    returned_names = {row[1] for row in with_predicate}
    assert "opt04 public line" in returned_names
    assert "SMOPT04 null line" not in returned_names


@pytest.mark.asyncio
async def test_predicate_becomes_load_bearing_under_a_null_tolerant_match(db_session):
    """Control: the guard is defence in depth, not dead weight.

    If the matching term ever becomes NULL-tolerant (here ``coalesce``), the
    explicit predicate is the only thing excluding a row with no public
    identity -- which is exactly why removing it must be a conscious choice.
    """
    release = Release(
        version="opt04-control-release",
        name="opt04 control release",
        status=ReleaseStatus.PUBLISHED,
    )
    db_session.add(release)
    await db_session.flush()
    db_session.add_all(
        [
            MutantLine(
                public_id="SMOPT04002",
                name="opt04 control public line",
                release_id=release.id,
                is_public=True,
                is_deleted=False,
            ),
            MutantLine(
                public_id=None,
                name="SMOPT04 control null line",
                release_id=release.id,
                is_public=True,
                is_deleted=False,
            ),
        ]
    )
    await db_session.flush()

    sql = await _captured_external_sql(release.id)
    tolerant = sql.replace(
        "mutant_lines.public_id ILIKE",
        "coalesce(mutant_lines.public_id, mutant_lines.name) ILIKE",
    )
    assert tolerant != sql
    tolerant_without = re.sub(rf"\s+AND\s+{re.escape(_PREDICATE)}", "", tolerant)
    assert tolerant_without != tolerant

    guarded = {
        row[1]
        for row in (await db_session.execute(text(_executable(tolerant)))).all()
    }
    unguarded = {
        row[1]
        for row in (await db_session.execute(text(_executable(tolerant_without)))).all()
    }

    assert "SMOPT04 control null line" in unguarded
    assert "SMOPT04 control null line" not in guarded
