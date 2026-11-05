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
from ..models.genomic import Gene
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


def summary_assembly_consistency():
    """Is this summary's ``gene_id`` in the summary's own assembly?

    ``variant_summaries`` has no database-level constraint tying ``gene_id`` to
    ``assembly_id`` (see issue #86), so a cross-assembly row -- a v4 gene on a
    v5 summary -- is insertable. The gene page filters it out by construction
    (it compares ``assembly_id`` to the gene's own). The site-wide total reads
    ``variant_facts``, which carries its own denormalized ``assembly_id``, so
    this gap is specific to the release-wide ``variant_type`` aggregate.

    Use it as a ``count(...) FILTER (WHERE ...)`` rather than a ``WHERE`` clause
    at those read points: the number must stop counting these rows without
    changing which rows the statement scans. Callers that need a predicate can
    use it directly; negating it finds the rows an import must reject.
    """
    gene_alias = Gene.__table__.alias("summary_assembly_gene")
    return or_(
        VariantSummary.gene_id.is_(None),
        exists(
            select(literal(1))
            .select_from(gene_alias)
            .where(
                gene_alias.c.gene_pk == VariantSummary.gene_id,
                gene_alias.c.assembly_id == VariantSummary.assembly_id,
            )
        ),
    )
