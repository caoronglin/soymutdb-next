"""Public visibility for native facts and normalized variant summaries.

Legacy fact surrogates are hashes, not mutant primary keys. Facts use the same
release/name relation as public export; summaries have a real mutant foreign key.
Neither public path gains private access merely because a caller is signed in.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import Table, and_, column, exists, literal, or_, select, table
from sqlalchemy.sql import ColumnElement

from ..models.content import Release, ReleaseStatus
from ..models.variant import MutantLine, VariantSummary
from ..models.variant_facts import variant_facts

# ``releases.status`` is a native enum column (``release_status_enum``). Bind
# the literal with that column's own type: a plain string parameter renders as
# VARCHAR and PostgreSQL refuses ``release_status_enum = character varying``.
_RELEASE_STATUS_TYPE = Release.status.type

# ``variant_facts`` visibility: the fact must belong to a published release and
# either name no mutant line or name one that is public, undeleted and has a
# public id *in the same release*. It is a SQLAlchemy expression, so a caller
# composes it with ``&`` and can never append SQL text of its own; the tables
# are fixed aliases below, never names derived from caller input.
_FACT_RELEASES = table("releases", column("id"), column("status"))
_FACT_MUTANT_LINES = table(
    "mutant_lines",
    column("release_id"),
    column("name"),
    column("is_public"),
    column("is_deleted"),
    column("public_id"),
)


def _published_release(fact):
    return exists(
        select(literal(1)).where(
            _FACT_RELEASES.c.id == fact.c.release_id,
            _FACT_RELEASES.c.status
            == literal(ReleaseStatus.PUBLISHED.value, _RELEASE_STATUS_TYPE),
        )
    )


def _public_mutant_line(fact):
    # EXISTS keeps pages/counts stable even if historical names are not unique.
    return or_(
        fact.c.mutant_line_name == "",
        exists(
            select(literal(1)).where(
                _FACT_MUTANT_LINES.c.release_id == fact.c.release_id,
                _FACT_MUTANT_LINES.c.name == fact.c.mutant_line_name,
                _FACT_MUTANT_LINES.c.is_public.is_(True),
                _FACT_MUTANT_LINES.c.is_deleted.is_(False),
                _FACT_MUTANT_LINES.c.public_id.is_not(None),
            )
        ),
    )


def variant_fact_visibility(
    fact: Table | None = None,
) -> ColumnElement[Any]:
    """Public visibility of ``variant_facts`` rows (expression form).

    ``fact`` is a table construct named in code, never by a caller: callers pass
    the alias they are already selecting from. The default is the ORM table.
    """
    surface = fact if fact is not None else variant_facts
    return and_(_published_release(surface), _public_mutant_line(surface))


PUBLIC_FACT_VISIBILITY = variant_fact_visibility()


def public_mutant_visibility():
    """Public metadata predicates; callers still bind the released context."""
    return and_(
        MutantLine.is_public.is_(True),
        MutantLine.is_deleted.is_(False),
        MutantLine.public_id.is_not(None),
    )


def public_summary_visibility():
    """Equivalent scope for the normalized summary table's real foreign key."""
    released = select(Release.id).where(
        Release.id == VariantSummary.release_id,
        Release.status == ReleaseStatus.PUBLISHED,
    ).correlate(VariantSummary).exists()
    public_mutant = select(MutantLine.id).where(
        MutantLine.id == VariantSummary.mutant_line_id,
        MutantLine.release_id == VariantSummary.release_id,
        public_mutant_visibility(),
    ).correlate(VariantSummary).exists()
    return and_(released, or_(VariantSummary.mutant_line_id.is_(None), public_mutant))
