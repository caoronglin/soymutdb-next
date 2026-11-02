"""Public visibility for native facts and normalized variant summaries.

Legacy fact surrogates are hashes, not mutant primary keys. Facts use the same
release/name relation as public export; summaries have a real mutant foreign key.
Neither public path gains private access merely because a caller is signed in.
"""
from __future__ import annotations

from sqlalchemy import and_, or_, select

from ..models.content import Release, ReleaseStatus
from ..models.variant import MutantLine, VariantSummary

# Only fixed SQL identifiers appear here. No caller-provided identifiers/values.
# EXISTS keeps pages/counts stable even if historical names are not unique.
PUBLIC_FACT_VISIBILITY = """(
    EXISTS (SELECT 1 FROM releases public_release
            WHERE public_release.id = variant_facts.release_id
              AND public_release.status = 'published')
    AND (variant_facts.mutant_line_name = '' OR EXISTS (
        SELECT 1 FROM mutant_lines public_mutant
        WHERE public_mutant.release_id = variant_facts.release_id
          AND public_mutant.name = variant_facts.mutant_line_name
          AND public_mutant.is_public = true
          AND public_mutant.is_deleted = false
          AND public_mutant.public_id IS NOT NULL
    ))
)"""


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
