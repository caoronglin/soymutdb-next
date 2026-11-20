"""Regression tests for the cross-assembly variant-count guard.

The guard exists because a cross-assembly ``variant_summaries`` row (a v5
summary pointing at a v4 gene) is insertable and the release-wide aggregate
counted it. The only behavioural test needed PostgreSQL, so nothing in a clean
checkout would have caught the exclusion being dropped. Each case here plants
one regression against a synthetic tree and requires the guard to fail.
"""
from pathlib import Path

from scripts import check_variant_summary_assembly_consistency as guard

GOOD_VISIBILITY = '''
def summary_assembly_consistency():
    gene_alias = Gene.__table__.alias("summary_assembly_gene")
    return or_(
        VariantSummary.gene_id.is_(None),
        exists(
            select(literal(1)).select_from(gene_alias).where(
                gene_alias.c.gene_pk == VariantSummary.gene_id,
                gene_alias.c.assembly_id == VariantSummary.assembly_id,
            )
        ),
    )
'''

GOOD_STATS = '''
async def _variant_type_counts_from_pg(db, release_id=None):
    stmt = select(
        VariantSummary.variant_type,
        func.count().filter(summary_assembly_consistency()),
    ).where(public_summary_visibility())
    return stmt
'''


def _tree(tmp_path: Path, visibility: str, stats: str) -> tuple[Path, Path]:
    vis = tmp_path / "variant_visibility.py"
    sta = tmp_path / "stats.py"
    vis.write_text(visibility, encoding="utf-8")
    sta.write_text(stats, encoding="utf-8")
    return vis, sta


def test_current_contract_is_accepted(tmp_path):
    vis, sta = _tree(tmp_path, GOOD_VISIBILITY, GOOD_STATS)
    assert guard.run(vis, sta) == []


def test_missing_predicate_is_rejected(tmp_path):
    vis, sta = _tree(
        tmp_path,
        GOOD_VISIBILITY.replace("def summary_assembly_consistency", "def renamed"),
        GOOD_STATS,
    )
    problems = guard.run(vis, sta)
    assert any("is missing" in p for p in problems), problems


def test_correlation_pinned_to_a_fixed_assembly_is_rejected(tmp_path):
    """A literal id would exclude real rows instead of cross-assembly ones."""
    vis, sta = _tree(
        tmp_path,
        GOOD_VISIBILITY.replace(
            "gene_alias.c.assembly_id == VariantSummary.assembly_id",
            "gene_alias.c.assembly_id == 5",
        ),
        GOOD_STATS,
    )
    problems = guard.run(vis, sta)
    assert any("lost its correlation" in p for p in problems), problems


def test_gene_less_summaries_must_stay_consistent(tmp_path):
    """``gene_id IS NULL`` is a gene-less summary, not a mismatch."""
    vis, sta = _tree(
        tmp_path,
        GOOD_VISIBILITY.replace(
            "VariantSummary.gene_id.is_(None),", "VariantSummary.gene_id.is_not(None),"
        ),
        GOOD_STATS,
    )
    problems = guard.run(vis, sta)
    assert any("gene-less" in p for p in problems), problems


def test_aggregate_dropping_the_predicate_is_rejected(tmp_path):
    vis, sta = _tree(
        tmp_path, GOOD_VISIBILITY, GOOD_STATS.replace(".filter(summary_assembly_consistency())", "")
    )
    problems = guard.run(vis, sta)
    assert any("no longer calls" in p for p in problems), problems


def test_filters_the_scan_instead_of_counting_is_rejected(tmp_path):
    """FILTER keeps the scanned rows; a WHERE narrows them. Only FILTER is the contract."""
    stats = GOOD_STATS.replace(
        "func.count().filter(summary_assembly_consistency()),", "func.count(),"
    ).replace(
        ".where(public_summary_visibility())",
        ".where(public_summary_visibility(), summary_assembly_consistency())",
    )
    vis, sta = _tree(tmp_path, GOOD_VISIBILITY, stats)
    problems = guard.run(vis, sta)
    assert any("counts with" in p for p in problems), problems


def test_a_comment_cannot_satisfy_the_filter_requirement(tmp_path):
    """The regression this guard is for must not be reverted by editing a comment."""
    stats = (
        "# func.count().filter(summary_assembly_consistency())  <- as it should be\n"
        + GOOD_STATS.replace(
            "func.count().filter(summary_assembly_consistency()),", "func.count(),"
        )
    )
    vis, sta = _tree(tmp_path, GOOD_VISIBILITY, stats)
    problems = guard.run(vis, sta)
    assert any("counts with" in p for p in problems), problems
