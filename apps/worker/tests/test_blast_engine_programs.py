"""Engine-scoped program vocabularies and importability of the BLAST runner.

Two failure modes are pinned here because both were live at once and each one
silently disabled part of the P0 feature:

1. ``ncbi_blast.py`` carried Python-2 ``except A, B:`` clauses, so the module
   could not be imported at all — every NCBI BLAST+ job died before running.
2. The worker whitelisted ``blastp`` for *all* engines, so blastn/blastx/
   tblastn/tblastx were refused even though the task routes them to the NCBI
   runner and the API advertises them.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from soymutdb_worker.tasks import blast

#: Every module under the worker package must at least parse; an unparseable
#: module is a broken deployment, not a lint nit.
WORKER_SRC = Path(__file__).resolve().parents[1] / "src" / "soymutdb_worker"


@pytest.mark.parametrize("program", ["blastn", "blastp", "blastx", "tblastn", "tblastx"])
def test_ncbi_engine_accepts_all_five_programs(program):
    assert blast.validate_program(program, "ncbi_blast") == program


@pytest.mark.parametrize("program", ["blastn", "blastx", "tblastn", "tblastx"])
def test_diamond_engine_rejects_nucleotide_programs(program):
    """DIAMOND has no nucleotide search: the runner must refuse, not guess."""
    with pytest.raises(ValueError, match="Unsupported program"):
        blast.validate_program(program, "diamond")


def test_engine_program_sets_are_explicit():
    assert blast.ENGINE_PROGRAMS["diamond"] == frozenset({"blastp"})
    assert blast.ENGINE_PROGRAMS["ncbi_blast"] == frozenset(
        {"blastn", "blastp", "blastx", "tblastn", "tblastx"}
    )
    # Default engine is DIAMOND, so the historical one-arg call stays protein-only.
    with pytest.raises(ValueError, match="Unsupported program"):
        blast.validate_program("blastn")


def test_python_sources_parse_without_python2_syntax():
    broken = []
    for path in sorted(WORKER_SRC.rglob("*.py")):
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - failure path
            broken.append(f"{path.relative_to(WORKER_SRC)}:{exc.lineno}: {exc.msg}")
    assert broken == []


def test_ncbi_runner_imports():
    """Regression: the module must be importable, not merely present."""
    from soymutdb_worker import ncbi_blast

    assert ncbi_blast.PROGRAM_DATABASE_TYPES["blastn"] == "nucl"
    assert ncbi_blast.PROGRAM_DATABASE_TYPES["blastp"] == "prot"
