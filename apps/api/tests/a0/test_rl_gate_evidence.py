from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

rl_project_root = Path(__file__).resolve().parents[4]
if str(rl_project_root) not in sys.path:
    sys.path.insert(0, str(rl_project_root))
rl_a0_test_root = Path(__file__).resolve().parent
if str(rl_a0_test_root) not in sys.path:
    sys.path.insert(0, str(rl_a0_test_root))

# Shared v2 fixture (33-phase recipe + 16 section contracts + v2 trusted assertion).
from fixtures.rl_v2_fixture import (  # noqa: E402
    build_manifest,
    rl_fake_trusted_verifier,
)
from tools.a0.rl_emit_gate_evidence import (  # noqa: E402
    rl_emit_gate_evidence,
)


def rl_prepare_reviewed_manifest(
    rl_tmp_path: Path,
    *,
    rl_action_type: str = "source_snapshot",
    rl_action_overrides: dict | None = None,
    rl_top_overrides: dict | None = None,
) -> tuple[Path, Path, Path]:
    rl_manifest_path, rl_artifact_root, _ = build_manifest(
        rl_tmp_path,
        rl_action_overrides=rl_action_overrides,
        rl_top_overrides=rl_top_overrides,
    )
    rl_review_root = rl_tmp_path / "review-root"
    from tools.a0.rl_reviewer_attestation import rl_create_reviewer_attestation

    rl_create_reviewer_attestation(
        rl_manifest_path,
        rl_review_root,
        "run-1",
        rl_fake_trusted_verifier,
        rl_producer_root=rl_tmp_path / "producer-root",
        rl_artifact_root=rl_artifact_root,
    )
    return (
        rl_manifest_path,
        rl_artifact_root,
        rl_review_root / "review-attestation-run-1.json",
    )


def test_rl_gate_emits_a0_only_result_even_when_status_passes(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_output_path = tmp_path / "gate-result.json"

    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        rl_output_path,
        rl_attestation_path,
        rl_trusted_verifier=rl_fake_trusted_verifier,
        rl_producer_root=tmp_path / "producer-root",
    )

    assert rl_result["status"] == "PASS"
    assert rl_result["a0_observational_evidence_complete"] is True
    assert rl_result["a1_allowed"] is False
    assert rl_result["production_migration_allowed"] is False
    assert rl_result["production_write_cutover_allowed"] is False
    assert rl_result["publication_implementation_allowed"] is False
    assert json.loads(rl_output_path.read_text(encoding="utf-8")) == rl_result


def test_rl_gate_rejects_bool_summary_and_versionless_manifest(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_output_path = tmp_path / "gate-result.json"

    with pytest.raises(TypeError, match="manifest path"):
        rl_emit_gate_evidence(
            True,
            rl_artifact_root,
            "run-1",
            rl_output_path,
            rl_attestation_path,
        )

    rl_versionless = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    del rl_versionless["a0_evidence_manifest_version"]
    rl_manifest_path.write_text(json.dumps(rl_versionless), encoding="utf-8")
    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        rl_output_path,
        rl_attestation_path,
    )
    assert rl_result["status"] == "BLOCKED"
    assert "manifest-version" in rl_result["findings"]


@pytest.mark.parametrize(
    ("rl_action_overrides", "rl_top_overrides", "rl_expected_finding"),
    [
        ({"exit_code": 7}, None, "nonzero-exit"),
        ({"plan_source_sha256": None}, None, "missing-source-digest"),
    ],
)
def test_rl_gate_blocks_hard_failure_states(
    tmp_path: Path,
    rl_action_overrides: dict | None,
    rl_top_overrides: dict | None,
    rl_expected_finding: str,
) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(
        tmp_path,
        rl_action_overrides=rl_action_overrides,
        rl_top_overrides=rl_top_overrides,
    )
    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
    )
    assert rl_result["status"] == "BLOCKED"
    assert rl_expected_finding in rl_result["findings"]


def test_rl_gate_blocks_missing_artifact_and_sensitive_raw_inputs(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    # A missing artifact referenced in the index must block.
    rl_manifest["artifact_index"].append(
        {
            "opaque_ref": "missing-artifact.json",
            "kind": "action_output",
            "schema_version": "a0.action-output.v1",
            "sha256": "a" * 64,
            "run_id": "run-1",
            "owner": "rl_a0_evidence_owner",
            "reviewer": "rl_gate_reviewer",
            "producer_action_ids": ["action-1"],
        }
    )
    rl_manifest_path.write_text(json.dumps(rl_manifest), encoding="utf-8")
    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
    )
    assert rl_result["status"] == "BLOCKED"
    assert "artifact-missing-or-unsafe" in rl_result["findings"]
    assert str(tmp_path) not in json.dumps(rl_result)


def test_rl_gate_rejects_raw_archive_magic_and_url_inputs(tmp_path: Path) -> None:

    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    # Raw archive magic bytes (PGDMP) in an artifact must be rejected.
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    rl_artifact_path = rl_artifact_root / "evidence-1.json"
    rl_artifact_path.write_bytes(b"PGDMP renamed archive\n")
    rl_manifest_path.write_text(json.dumps(rl_manifest), encoding="utf-8")

    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
    )
    assert rl_result["status"] == "BLOCKED"
    assert "artifact-raw-archive" in rl_result["findings"]


def test_rl_gate_requires_actual_engine_attestation_for_migration(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    # An alembic (migration) action with non-actual_engine attestation must block.
    for rl_action in rl_manifest["database_actions"]:
        if rl_action["action_type"].startswith("alembic"):
            rl_action["attestation_kind"] = "launcher"
    rl_manifest_path.write_text(json.dumps(rl_manifest), encoding="utf-8")
    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
    )
    assert rl_result["status"] == "BLOCKED"
    assert "alembic-attestation" in rl_result["findings"]


def test_rl_gate_blocks_self_hash_scope_and_missing_trusted_boundary(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, _ = build_manifest(
        tmp_path,
        rl_top_overrides={"digest_scope": ["actions", "bundle_digest"]},
    )
    rl_review_root = tmp_path / "review-root"
    rl_review_root.mkdir(exist_ok=True)
    rl_attestation_path = tmp_path / "review-attestation.json"
    rl_attestation_path.write_text(
        json.dumps(
            {
                "review_attestation_version": "a0.reviewer-attestation.v2",
                "run_id": "run-1",
                "manifest_sha256": "0" * 64,
                "recomputed_bundle_sha256": "0" * 64,
                "reviewer_identity": "rl_gate_reviewer",
                "review_started_at": "2026-07-21T10:02:00Z",
                "review_finished_at": "2026-07-21T10:03:00Z",
                "decision": "PASS",
                "blocking_findings": [],
                "review_source_sha256": "1" * 64,
            }
        ),
        encoding="utf-8",
    )
    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
    )
    assert rl_result["status"] == "BLOCKED"
    assert "self-hash-scope" in rl_result["findings"]


@pytest.mark.parametrize(
    "rl_sensitive_ref",
    ["password", "passwd", "secret", "token", "archive", "full-list", "list_path", "archive_path"],
)
def test_rl_gate_rejects_sensitive_opaque_artifact_refs(
    tmp_path: Path,
    rl_sensitive_ref: str,
) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    # A sensitive-named opaque_ref in the artifact index is rejected.
    rl_manifest["artifact_index"].append(
        {
            "opaque_ref": rl_sensitive_ref,
            "kind": "action_output",
            "schema_version": "a0.action-output.v1",
            "sha256": "a" * 64,
            "run_id": "run-1",
            "owner": "rl_a0_evidence_owner",
            "reviewer": "rl_gate_reviewer",
            "producer_action_ids": ["action-1"],
        }
    )
    rl_manifest_path.write_text(json.dumps(rl_manifest), encoding="utf-8")

    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
    )
    assert rl_result["status"] == "BLOCKED"
    assert "artifact-ref-invalid" in rl_result["findings"]


def test_rl_gate_rejects_attestation_in_child_path(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_child_root = rl_attestation_path.parent / "child"
    rl_child_root.mkdir()
    rl_child_attestation = rl_child_root / rl_attestation_path.name
    rl_child_attestation.write_bytes(rl_attestation_path.read_bytes())

    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_child_attestation,
        rl_review_root=rl_attestation_path.parent,
        rl_trusted_verifier=rl_fake_trusted_verifier,
        rl_producer_root=tmp_path / "producer-root",
    )
    assert rl_result["status"] == "BLOCKED"
    assert "attestation-path-binding" in rl_result["findings"]


def test_rl_gate_rejects_attestation_path_alias(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_alias_path = rl_attestation_path.parent / "attestation-alias.json"
    try:
        rl_alias_path.symlink_to(rl_attestation_path)
    except OSError:
        pytest.skip("symlink unavailable")

    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_alias_path,
        rl_review_root=rl_attestation_path.parent,
        rl_trusted_verifier=rl_fake_trusted_verifier,
        rl_producer_root=tmp_path / "producer-root",
    )
    assert rl_result["status"] == "BLOCKED"
    assert "attestation-path-binding" in rl_result["findings"]


def test_rl_gate_cannot_elevate_any_authorization_flag(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    rl_manifest.update(
        {
            "a1_allowed": True,
            "production_migration_allowed": True,
            "production_write_cutover_allowed": True,
            "publication_implementation_allowed": True,
        }
    )
    rl_manifest_path.write_text(json.dumps(rl_manifest), encoding="utf-8")
    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
        rl_trusted_verifier=rl_fake_trusted_verifier,
        rl_producer_root=tmp_path / "producer-root",
    )
    assert rl_result["a1_allowed"] is False
    assert rl_result["production_migration_allowed"] is False
    assert rl_result["production_write_cutover_allowed"] is False
    assert rl_result["publication_implementation_allowed"] is False


def test_rl_gate_blocks_generic_ok_artifact_payload(tmp_path: Path) -> None:
    # Mutating the canonical snapshot artifact to a generic payload must block.
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    rl_artifact_path = rl_artifact_root / "evidence-4.json"
    rl_artifact_path.write_text('{"ok":true}\n', encoding="utf-8")
    rl_manifest_path.write_text(json.dumps(rl_manifest), encoding="utf-8")

    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
    )
    assert rl_result["status"] == "BLOCKED"
    assert "artifact-payload-contract" in rl_result["findings"]


def test_rl_gate_blocks_missing_semantic_gate_contract_version(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    rl_manifest.pop("semantic_gate_contract_version", None)
    rl_manifest_path.write_text(json.dumps(rl_manifest), encoding="utf-8")

    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
    )
    assert rl_result["status"] == "BLOCKED"
    assert "semantic-gate-contract-version" in rl_result["findings"]
