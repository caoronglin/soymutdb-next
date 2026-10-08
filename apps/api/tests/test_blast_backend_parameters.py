"""The worker only accepts DIAMOND's vocabulary, so the API must not emit
NCBI-BLAST keys — an unknown flag aborts the search, not the submission."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.blast import BlastParameters, BlastSubmitProgram
from app.services.blast_service import _worker_parameters


def test_defaults_map_to_nothing():
    """DIAMOND has its own masking defaults; sending NCBI keys would abort."""
    assert _worker_parameters(BlastParameters()) == {}
    assert _worker_parameters(BlastParameters(), BlastSubmitProgram.BLASTP) == {}


@pytest.mark.parametrize(
    "field,value",
    [("word_size", 11), ("dust", True), ("dust", False), ("soft_masking", True)],
)
def test_retired_blast_parameters_are_rejected_at_the_schema(field, value):
    with pytest.raises(ValidationError, match="retired NCBI BLAST option"):
        BlastParameters(**{field: value})


def test_retired_parameters_default_to_absent():
    params = BlastParameters()
    assert params.word_size is None
    assert params.dust is None
    assert params.soft_masking is None


def test_supported_parameters_still_translate():
    assert _worker_parameters(
        BlastParameters(gap_open=11, gap_extend=1, matrix="BLOSUM45")
    ) == {"gapopen": 11, "gapextend": 1, "matrix": "BLOSUM45"}
