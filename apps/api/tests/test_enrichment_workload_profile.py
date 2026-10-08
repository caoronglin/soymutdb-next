"""Replay integer semantics and parity gates must agree with production ORA."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from scipy.stats import hypergeom

from app.services.enrichment_service import compute_enrichment

from .test_gene_annotation_cli import CONTENTS, cli, cli_scope  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "enrichment_profiler_under_test", ROOT / "scripts/profile_enrichment_workload.py"
)
assert _spec is not None and _spec.loader is not None
profile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(profile)


def test_export_excludes_unknown_genes_from_draw_size_and_preserves_term_identity():
    mapping = {"G1": {"T1", "T2"}, "G2": {"T1"}, "G3": {"T2"}}
    genes = ["G1", "UNKNOWN", "G1", "ANOTHER_UNKNOWN"]
    exported = profile.build_case_export(mapping, genes, p_threshold=1)
    assert exported["input_genes"] == 3
    assert exported["annotated_input_genes"] == 1
    assert exported["cases"] == [[3, 2, 1, 1], [3, 2, 1, 1]]
    assert exported["term_ids"] == ["T1", "T2"]
    assert exported["request_genes"] == ["G1", "UNKNOWN", "ANOTHER_UNKNOWN"]
    result = compute_enrichment(genes, mapping, {}, ontology="go", p_threshold=1)
    observed = {term.id: term.p_value for term in result.terms}
    for term_id, (N, K, n, k) in zip(exported["term_ids"], exported["cases"], strict=True):
        assert observed[term_id] == pytest.approx(hypergeom.sf(k - 1, N, K, n))
    assert profile.build_case_export(mapping, genes, p_threshold=1) == exported


def test_export_with_no_annotated_input_contains_no_cases():
    exported = profile.build_case_export({"G1": {"T"}}, ["MISSING"], p_threshold=0.05)
    assert exported["annotated_input_genes"] == 0
    assert exported["cases"] == []


@pytest.mark.parametrize("option", ["--repeats", "--concurrency", "--input-genes", "--max-terms"])
def test_invalid_measurement_budget_is_rejected(option):
    with pytest.raises(SystemExit) as exc:
        profile.main(["--synthetic", option, "0"])
    assert exc.value.code == 2


@pytest.mark.parametrize("threshold", ["nan", "inf", "-0.1", "1.1"])
def test_invalid_threshold_is_rejected(threshold):
    with pytest.raises(SystemExit) as exc:
        profile.main(["--synthetic", "--p-threshold", threshold])
    assert exc.value.code == 2


def test_profile_modes_are_exclusive():
    with pytest.raises(SystemExit) as exc:
        profile.main(["--synthetic", "--real"])
    assert exc.value.code == 2


@pytest.mark.integration
@pytest.mark.parametrize("drift", [False, True])
async def test_database_replay_verifies_production_calculation(
    cli_scope, monkeypatch, drift,  # noqa: F811 — imported pytest fixture
):
    import io

    import sqlalchemy.ext.asyncio

    args, factory = cli_scope
    imported = await cli._run(args, io.BytesIO(CONTENTS), hashlib.sha256(CONTENTS).hexdigest())
    scope = {
        "assembly_id": args.assembly_id, "release_id": args.release_id,
        "annotation_set_id": imported["annotation_set_id"],
    }
    monkeypatch.setattr(
        sqlalchemy.ext.asyncio, "create_async_engine",
        lambda *a, **kw: SimpleNamespace(dispose=AsyncMock()),
    )
    monkeypatch.setattr(sqlalchemy.ext.asyncio, "async_sessionmaker", lambda *a, **kw: factory)
    monkeypatch.setattr(profile, "discover_scopes", AsyncMock(return_value=([scope], {})))
    if drift:
        original = profile.run_enrichment

        async def wrong_calculation(*a, **kw):
            result = await original(*a, **kw)
            return result.model_copy(update={"input_genes": result.input_genes + 1})

        monkeypatch.setattr(profile, "run_enrichment", wrong_calculation)
    request = argparse.Namespace(
        database_url="postgresql+asyncpg://redacted/test", ontology="go",
        input_genes=1, repeats=2, concurrency=1, seed=123, p_threshold=1, max_terms=20,
    )
    if drift:
        with pytest.raises(RuntimeError, match="differs from the production result"):
            await profile.run_real(request)
    else:
        report = await profile.run_real(request)
        assert report["workload_kind"] == "database_replay"
        assert report["production_calculation_parity"] is True
        assert report["case_export"]["cases"] == [[1, 1, 1, 1]]
        assert report["result_shape"]["returned_terms"] == 1
        assert "calculation-only" in report["single_request"]["measurement_path"]
