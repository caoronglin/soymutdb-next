#!/usr/bin/env python3
"""Guard the cross-assembly exclusion at the release-wide variant counts.

``variant_summaries.assembly_id`` and ``gene_id`` have no database-level
consistency constraint (issue #86), so a v5 summary can point at a v4 gene.
The gene page excludes such a row by construction -- it compares the summary's
``assembly_id`` to the gene's own -- but the release-wide ``variant_type``
aggregate never joined ``genes`` and counted it. The site-wide total moved to
``variant_facts`` (which carries its own denormalized ``assembly_id``), so the
release-wide aggregate was the remaining read point.

Two things have to stay true together, and a reversion of either one is
invisible to the API tests that need PostgreSQL to run:

- ``variant_visibility.summary_assembly_consistency()`` exists, correlates to
  the row it filters (not to a fixed id), and treats a gene-less summary as
  consistent;
- ``stats._variant_type_counts_from_pg`` applies it, and applies it as a
  ``FILTER`` -- filtering the scan would change which rows the statement
  touches, which is not the contract.

This is a source guard, not a runtime proof. It parses the sources with ``ast``
so a comment mentioning the predicate cannot satisfy it. ``--self-test``
plants both regressions and requires the guard to catch them.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VISIBILITY = ROOT / "apps/api/app/services/variant_visibility.py"
DEFAULT_STATS = ROOT / "apps/api/app/api/v1/stats.py"

CONSISTENCY_FN = "summary_assembly_consistency"
AGGREGATE_FN = "_variant_type_counts_from_pg"


def _function_span(tree: ast.AST, name: str) -> tuple[int, int] | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node.lineno, node.end_lineno or node.lineno
    return None


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def check_visibility(path: Path) -> list[str]:
    """The predicate must exist and correlate to the filtered row."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    span = _function_span(tree, CONSISTENCY_FN)
    if span is None:
        return [f"{path}: {CONSISTENCY_FN}() is missing"]
    start, end = span
    body = "\n".join(_lines(path)[start - 1 : end])

    problems: list[str] = []
    # Correlate to the row, not to a literal id.
    for needle in (
        "gene_pk == VariantSummary.gene_id",
        "assembly_id == VariantSummary.assembly_id",
    ):
        if needle not in body:
            problems.append(f"{path}: {CONSISTENCY_FN}() lost its correlation ({needle})")
    # A gene-less summary is consistent by definition, not excluded.
    if "VariantSummary.gene_id.is_(None)" not in body:
        problems.append(f"{path}: {CONSISTENCY_FN}() no longer treats a gene-less summary as consistent")
    # It must be a real expression, not a constant.
    if "exists(" not in body:
        problems.append(f"{path}: {CONSISTENCY_FN}() no longer builds an EXISTS")
    return problems


def check_aggregate(path: Path) -> list[str]:
    """The aggregate must count with the predicate, and count with FILTER."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    span = _function_span(tree, AGGREGATE_FN)
    if span is None:
        return [f"{path}: {AGGREGATE_FN}() is missing"]
    start, end = span
    body = "\n".join(_lines(path)[start - 1 : end])

    problems: list[str] = []
    tree_body = _function_node(tree, AGGREGATE_FN)
    calls = _call_names(tree_body)
    # The predicate has to be *called*, not merely mentioned in a comment.
    if CONSISTENCY_FN not in calls:
        problems.append(f"{path}: {AGGREGATE_FN}() no longer calls {CONSISTENCY_FN}()")
    # And it has to be called through ``.filter(...)`` on the aggregate, which
    # is what makes it a FILTER clause instead of narrowing the scan.
    if not _calls_within(tree_body, attribute="filter", callee=CONSISTENCY_FN):
        problems.append(
            f"{path}: {AGGREGATE_FN}() no longer counts with "
            f"func.count().filter({CONSISTENCY_FN}())"
        )
    return problems


def _function_node(tree: ast.AST, name: str) -> ast.AST | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _call_names(node: ast.AST | None) -> set[str]:
    names: set[str] = set()
    if node is None:
        return names
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if isinstance(sub.func, ast.Name):
                names.add(sub.func.id)
            elif isinstance(sub.func, ast.Attribute):
                names.add(sub.func.attr)
    return names


def _calls_within(node: ast.AST | None, *, attribute: str, callee: str) -> bool:
    """Is ``callee`` an argument of a ``.<attribute>(...)`` call?"""
    if node is None:
        return False
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if not isinstance(func, ast.Attribute) or func.attr != attribute:
            continue
        for arg in sub.args:
            if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                if arg.func.id == callee:
                    return True
    return False


def run(visibility: Path, stats: Path) -> list[str]:
    return check_visibility(visibility) + check_aggregate(stats)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visibility", type=Path, default=DEFAULT_VISIBILITY)
    parser.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    problems = run(args.visibility, args.stats)
    if problems:
        print(f"variant summary assembly consistency: {len(problems)} problem(s)")
        for problem in problems:
            print(f"  - {problem}")
        print("FAIL")
        return 1
    print("variant summary assembly consistency: OK (predicate correlates, aggregate filters)")
    return 0


def self_test() -> int:
    import tempfile

    good_visibility = '''
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
    good_stats = '''
async def _variant_type_counts_from_pg(db, release_id=None):
    stmt = select(
        VariantSummary.variant_type,
        func.count().filter(summary_assembly_consistency()),
    )
    return stmt
'''
    cases = [
        ("clean control", good_visibility, good_stats, False),
        (
            "predicate dropped entirely",
            good_visibility.replace("def summary_assembly_consistency", "def something_else"),
            good_stats,
            True,
        ),
        (
            "correlation to a fixed id",
            good_visibility.replace(
                "gene_alias.c.assembly_id == VariantSummary.assembly_id",
                "gene_alias.c.assembly_id == 5",
            ),
            good_stats,
            True,
        ),
        (
            "gene-less summaries no longer consistent",
            good_visibility.replace(
                "VariantSummary.gene_id.is_(None),", "VariantSummary.gene_id.is_not(None),"
            ),
            good_stats,
            True,
        ),
        (
            "aggregate stops using the predicate",
            good_visibility,
            good_stats.replace(".filter(summary_assembly_consistency())", ""),
            True,
        ),
        (
            "aggregate filters the scan instead",
            good_visibility,
            good_stats.replace(
                "func.count().filter(summary_assembly_consistency())", "func.count()"
            ).replace(
                "stmt = select(", "stmt = select("
            ).replace(
                "    )\n    return stmt",
                "    ).where(summary_assembly_consistency())\n    return stmt",
            ),
            True,
        ),
    ]

    failures = 0
    for name, visibility, stats, should_fail in cases:
        with tempfile.TemporaryDirectory() as tmp:
            vis = Path(tmp) / "variant_visibility.py"
            sta = Path(tmp) / "stats.py"
            vis.write_text(visibility, encoding="utf-8")
            sta.write_text(stats, encoding="utf-8")
            problems = run(vis, sta)
        caught = bool(problems)
        if caught != should_fail:
            failures += 1
            print(f"  FAIL: {name} -> caught={caught}, expected {should_fail}")
        else:
            print(f"  ok: {name} -> {'caught' if caught else 'clean'}")

    if failures:
        print(f"SELF-TEST FAIL: {failures} case(s) behaved unexpectedly")
        return 1
    print(f"SELF-TEST PASS: {len(cases)} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
