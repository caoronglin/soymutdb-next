"""Tests for the shared AnalysisJobPayload schema (analyses queue)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from soymutdb_jobs.schemas import AnalysisJobPayload


def _make_payload(**overrides) -> AnalysisJobPayload:
    values = {
        "job_id": uuid.uuid4(),
        "analysis_type": "fastp",
        "input_objects": ["uploads/run-1/sample_R1.fastq.gz"],
        "params": {"threads": 4},
        "idempotency_key": "analysis:fastp:job-1",
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return AnalysisJobPayload(**values)


def test_defaults() -> None:
    p = _make_payload()
    assert p.max_attempts == 1
    assert p.params == {"threads": 4}
    assert p.input_objects == ["uploads/run-1/sample_R1.fastq.gz"]


def test_scanpy_analysis_type_accepted() -> None:
    p = _make_payload(
        analysis_type="scanpy",
        input_objects=["uploads/run-1/matrix.h5ad"],
        params={"min_genes": 200, "n_top_genes": 1000},
    )
    assert p.analysis_type == "scanpy"
    assert p.params == {"min_genes": 200, "n_top_genes": 1000}


def test_rejects_unknown_analysis_type() -> None:
    with pytest.raises(ValidationError):
        _make_payload(analysis_type="rnaseq")


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _make_payload(surprise="field")


def test_input_objects_must_be_strings() -> None:
    with pytest.raises(ValidationError):
        _make_payload(input_objects=["ok.fastq", 123])


def test_max_attempts_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _make_payload(max_attempts=0)


def test_serializes_to_plain_json() -> None:
    p = _make_payload()
    data = p.model_dump(mode="json")
    assert isinstance(data["job_id"], str)
    assert isinstance(data["created_at"], str)
    assert data["analysis_type"] == "fastp"
    assert data["input_objects"] == ["uploads/run-1/sample_R1.fastq.gz"]
    # Round-trip through JSON keeps every field.
    assert AnalysisJobPayload.model_validate(data) == p


def test_roundtrip_preserves_idempotency_key() -> None:
    key = "analysis:scanpy:job-7"
    p = _make_payload(idempotency_key=key)
    assert AnalysisJobPayload.model_validate(p.model_dump(mode="json")).idempotency_key == key
