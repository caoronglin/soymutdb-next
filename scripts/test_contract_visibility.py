"""Tests for the stage-1 handwritten API contract visibility checker."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_new_client_route_drift_fails_against_openapi(tmp_path: Path) -> None:
    schema = {"paths": {"/api/v1/genes": {"get": {}}}}
    schema_path = tmp_path / "openapi.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    client_path = tmp_path / "genes.ts"
    client_path.write_text(
        'return http.get("/genes/assemblies");\n', encoding="utf-8"
    )

    from contract_visibility import check_contract_visibility

    report = check_contract_visibility(
        schema_path=schema_path,
        client_paths=[client_path],
        baseline_path=tmp_path / "baseline.json",
    )

    assert report["status"] == "FAIL"
    assert report["new_drift"] == ["GET /genes/assemblies"]


def test_known_route_drift_is_debt_but_does_not_fail(tmp_path: Path) -> None:
    schema = {"paths": {"/api/v1/genes": {"get": {}}}}
    schema_path = tmp_path / "openapi.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    client_path = tmp_path / "genes.ts"
    client_path.write_text('return http.get("/genes/assemblies");\n', encoding="utf-8")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"GET /genes/assemblies": "legacy handwritten client route"}),
        encoding="utf-8",
    )

    from contract_visibility import check_contract_visibility

    report = check_contract_visibility(
        schema_path=schema_path,
        client_paths=[client_path],
        baseline_path=baseline_path,
    )

    assert report["status"] == "PASS"
    assert report["baseline_debt"] == ["GET /genes/assemblies"]


def test_template_parameter_matches_openapi_parameter(tmp_path: Path) -> None:
    schema = {
        "paths": {
            "/api/v1/genes/assemblies/{assembly_id}/chromosomes": {"get": {}}
        }
    }
    schema_path = tmp_path / "openapi.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    client_path = tmp_path / "genes.ts"
    client_path.write_text(
        'return http.get(`/genes/assemblies/${assembly_id}/chromosomes`);\n',
        encoding="utf-8",
    )

    from contract_visibility import check_contract_visibility

    report = check_contract_visibility(
        schema_path=schema_path,
        client_paths=[client_path],
        baseline_path=tmp_path / "baseline.json",
    )

    assert report["status"] == "PASS"
    assert report["new_drift"] == []
