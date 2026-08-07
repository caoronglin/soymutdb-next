from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

rl_project_root = Path(__file__).resolve().parents[4]
if str(rl_project_root) not in sys.path:
    sys.path.insert(0, str(rl_project_root))

from tools.a0.rl_emit_gate_evidence import (  # noqa: E402
    rl_emit_gate_evidence,
)
from tools.a0.rl_reviewer_attestation import (  # noqa: E402
    rl_compute_root_identity_digest,
    rl_compute_trusted_assertion_payload_digest,
    rl_create_reviewer_attestation,
)


def rl_fake_trusted_verifier(rl_request: dict) -> dict:
    rl_assertion = {
        "version": "a0.trusted-assertion.v1",
        "assertion_ref": "external-assertion-1",
        "issuer_id": "rl_unit_fake_issuer",
        "run_id": rl_request["run_id"],
        "producer_principal": rl_request["producer_principal"],
        "reviewer_principal": rl_request["reviewer_principal"],
        "root_identity_digests": rl_request["root_identity_digests"],
        "manifest_sha256": rl_request["manifest_sha256"],
        "bundle_sha256": rl_request["bundle_sha256"],
        "producer_writable": False,
        "access_control_verified": True,
        "issued_at": "2026-07-21T08:00:00Z",
        "expires_at": "2026-07-22T08:00:00Z",
        "nonce": "unit-nonce-1",
    }
    rl_assertion["payload_digest"] = rl_compute_trusted_assertion_payload_digest(rl_assertion)
    return rl_assertion


def rl_sha256_file(rl_file_path: Path) -> str:
    return hashlib.sha256(rl_file_path.read_bytes()).hexdigest()


def rl_build_manifest(
    rl_tmp_path: Path,
    *,
    rl_action_type: str = "source_snapshot",
    rl_action_overrides: dict | None = None,
    rl_top_overrides: dict | None = None,
) -> tuple[Path, Path, dict]:
    rl_tmp_path.mkdir(parents=True, exist_ok=True)
    rl_artifact_root = rl_tmp_path / "producer-artifacts"
    rl_artifact_root.mkdir(parents=True)
    (rl_tmp_path / "producer-root").mkdir(parents=True, exist_ok=True)
    (rl_tmp_path / "review-root").mkdir(parents=True, exist_ok=True)
    rl_artifact_path = rl_artifact_root / "artifact-source-1.json"
    rl_artifact_path.write_bytes(b'{"ok":true}\n')
    rl_artifact_sha256 = rl_sha256_file(rl_artifact_path)
    rl_attestation_kind = "actual_engine" if (
        "alembic" in rl_action_type or "migration" in rl_action_type
    ) else "launcher"
    rl_action = {
        "action_id": "action-1",
        "action_type": rl_action_type,
        "run_id": "run-1",
        "role": "rl_a0_producer",
        "preceding_guard_event_id": "guard-1",
        "attestation_event_id": "attestation-1",
        "attestation_kind": rl_attestation_kind,
        "identity_digest_version": "a0.identity.v2",
        "system_identifier_digest": "1" * 64,
        "endpoint_context_digest": "2" * 64,
        "registry_tuple_digest": "9" * 64,
        "marker_digest": "a" * 64,
        "expiry": "2026-07-22T00:00:00Z",
        "configured_identity_redacted": {
            "database": "<redacted>",
            "role": "rl_a0_reader",
        },
        "redacted_argv_template": [
            "python",
            "-m",
            "rl_a0_child",
            "--run-id",
            "<opaque>",
        ],
        "exit_code": 0,
        "stdout_sha256": "3" * 64,
        "stderr_sha256": "4" * 64,
        "started_at": "2026-07-21T10:00:00Z",
        "finished_at": "2026-07-21T10:01:00Z",
        "plan_source_sha256": "5" * 64,
        "spec_source_sha256": "6" * 64,
        "tool_source_sha256": "7" * 64,
        "test_source_sha256": "8" * 64,
        "executable_version": "python 3.14.0",
        "artifact_refs_and_sha256": [
            {
                "opaque_ref": rl_artifact_path.name,
                "sha256": rl_artifact_sha256,
                "owner": "rl_a0_evidence_owner",
                "reviewer": "rl_gate_reviewer",
            }
        ],
        "owner": "rl_a0_evidence_owner",
        "reviewer": "rl_gate_reviewer",
    }
    if rl_action_overrides:
        rl_action.update(rl_action_overrides)
    rl_guard_event = {
        "event_id": "guard-1",
        "kind": "guard",
        "run_id": "run-1",
        "role": "rl_a0_producer",
        "identity_digest_version": "a0.identity.v2",
        "system_identifier_digest": "1" * 64,
        "endpoint_context_digest": "2" * 64,
        "configured_identity_redacted": rl_action["configured_identity_redacted"],
        "registry_tuple_digest": rl_action.get("registry_tuple_digest"),
        "marker_digest": rl_action.get("marker_digest"),
        "expiry": rl_action.get("expiry"),
        "redacted_argv_template": rl_action["redacted_argv_template"],
    }
    rl_attestation_event = dict(rl_guard_event)
    rl_attestation_event.update(
        {
            "event_id": "attestation-1",
            "kind": rl_attestation_kind,
        }
    )
    rl_status_section = {
        "status": "passed",
        "owner": "rl_a0_evidence_owner",
        "reviewer": "rl_gate_reviewer",
        "evidence_ref": "evidence-summary-1",
        "evidence_sha256": "b" * 64,
    }
    rl_manifest = {
        "a0_evidence_manifest_version": "a0.gate.v2",
        "run_id": "run-1",
        "producer_root_ref": "rl-producer-root",
        "artifact_root_ref": "rl-artifact-root",
        "producer_root_path": str(rl_tmp_path / "producer-root"),
        "artifact_root_path": str(rl_artifact_root),
        "project_root_digest": "c" * 64,
        "plan_source_sha256": "5" * 64,
        "spec_source_sha256": "6" * 64,
        "identity_digest_version": "a0.identity.v2",
        "producer_principal": "rl_a0_evidence_owner",
        "reviewer_principal": "rl_gate_reviewer",
        "trusted_assertion_issuer_id": "rl_unit_fake_issuer",
        "artifact_index": [],
        "database_actions": [rl_action],
        "context_contract": dict(rl_status_section),
        "profile_contract": dict(rl_status_section),
        "catalog_baseline": dict(rl_status_section),
        "canonical_snapshot_contract": dict(rl_status_section),
        "semantic_projection_contract": dict(rl_status_section),
        "migration_trajectory": dict(rl_status_section),
        "empty_before_rebuild": {**rl_status_section, "empty": True},
        "empty_before_restore": {**rl_status_section, "empty": True},
        "source_stability": {**rl_status_section, "drift_detected": False},
        "synthetic_source_policy": dict(rl_status_section),
        "restricted_archive_policy": {**rl_status_section, "cleanup_status": "passed"},
        "archive_summary": dict(rl_status_section),
        "list_summary": {**rl_status_section, "valid": True},
        "restore_semantic_result": {**rl_status_section, "semantic_match": True},
        "legacy_release_classification": dict(rl_status_section),
        "unresolved_queue": {"blocking_count": 0, "items": []},
        "review_attestation_ref": "review-attestation-run-1.json",
        "trusted_boundary": {
            "trusted_boundary_version": "a0.trusted-boundary.v1",
            "boundary_ref": "rl-boundary-1",
            "control_metadata_ref": "rl-control-1",
            "producer_root_ref": "rl-producer-root",
            "review_root_ref": "rl-review-root",
            "reviewer_controlled": True,
            "producer_writable": False,
            "access_control_verified": True,
            "owner": "rl_gate_reviewer",
        },
        "producer_evidence_completed_at": "2026-07-21T11:00:00Z",
        "guard_events": {"guard-1": rl_guard_event},
        "attestation_events": {"attestation-1": rl_attestation_event},
    }
    rl_source_entry = {
        "opaque_ref": rl_artifact_path.name,
        "kind": "source_snapshot",
        "schema_version": "a0.task8.evidence.v1",
        "sha256": rl_artifact_sha256,
        "owner": "rl_a0_evidence_owner",
        "reviewer": "rl_gate_reviewer",
    }
    rl_manifest["artifact_index"] = [rl_source_entry]
    for rl_section_name in (
        "context_contract",
        "profile_contract",
        "catalog_baseline",
        "canonical_snapshot_contract",
        "semantic_projection_contract",
        "migration_trajectory",
        "empty_before_rebuild",
        "empty_before_restore",
        "source_stability",
        "synthetic_source_policy",
        "restricted_archive_policy",
        "archive_summary",
        "list_summary",
        "restore_semantic_result",
        "legacy_release_classification",
    ):
        rl_manifest[rl_section_name].update(
            {
                "evidence_ref": rl_artifact_path.name,
                "evidence_sha256": rl_artifact_sha256,
                "evidence_kind": "source_snapshot",
                "evidence_schema_version": "a0.task8.evidence.v1",
            }
        )
    rl_manifest["producer_root_identity_digest"] = rl_compute_root_identity_digest(
        rl_tmp_path / "producer-root"
    )
    rl_manifest["artifact_root_identity_digest"] = rl_compute_root_identity_digest(rl_artifact_root)
    rl_manifest["review_root_identity_digest"] = rl_compute_root_identity_digest(
        rl_tmp_path / "review-root"
    )
    if rl_top_overrides:
        rl_manifest.update(rl_top_overrides)
    rl_manifest_path = rl_tmp_path / "manifest.json"
    rl_manifest_path.write_text(json.dumps(rl_manifest), encoding="utf-8")
    return rl_manifest_path, rl_artifact_root, rl_manifest


def rl_write_boundary(rl_tmp_path: Path) -> Path:
    rl_review_root = rl_tmp_path / "review-root"
    rl_review_root.mkdir(parents=True, exist_ok=True)
    (rl_review_root / "rl_trusted_boundary.json").write_text(
        json.dumps(
            {
                "trusted_boundary_version": "a0.trusted-boundary.v1",
                "boundary_ref": "rl-boundary-1",
                "control_metadata_ref": "rl-control-1",
                "producer_root_ref": "rl-producer-root",
                "review_root_ref": "rl-review-root",
                "reviewer_controlled": True,
                "producer_writable": False,
                "access_control_verified": True,
                "owner": "rl_gate_reviewer",
            }
        ),
        encoding="utf-8",
    )
    return rl_review_root


def rl_prepare_reviewed_manifest(
    rl_tmp_path: Path,
    *,
    rl_action_type: str = "source_snapshot",
    rl_action_overrides: dict | None = None,
    rl_top_overrides: dict | None = None,
) -> tuple[Path, Path, Path]:
    rl_manifest_path, rl_artifact_root, _ = rl_build_manifest(
        rl_tmp_path,
        rl_action_type=rl_action_type,
        rl_action_overrides=rl_action_overrides,
        rl_top_overrides=rl_top_overrides,
    )
    rl_review_root = rl_write_boundary(rl_tmp_path)
    rl_create_reviewer_attestation(
        rl_manifest_path,
        rl_review_root,
        "run-1",
        rl_fake_trusted_verifier,
        rl_producer_root=rl_tmp_path / "producer-root",
        rl_artifact_root=rl_artifact_root,
    )
    return rl_manifest_path, rl_artifact_root, rl_review_root / "review-attestation-run-1.json"


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
    assert any("version" in rl_finding for rl_finding in rl_result["findings"])


@pytest.mark.parametrize(
    ("rl_action_overrides", "rl_top_overrides", "rl_expected_finding"),
    [
        ({"exit_code": 7}, None, "nonzero-exit"),
        ({"plan_source_sha256": None}, None, "missing-source-digest"),
        (
            None,
            {"list_summary": {"status": "invalid", "valid": False}},
            "list-invalid",
        ),
        (
            None,
            {"empty_before_restore": {"status": "failed"}},
            "restore-empty-failure",
        ),
        (
            None,
            {"semantic_projection_contract": {"status": "failed"}},
            "semantic-failure",
        ),
        (
            None,
            {"restricted_archive_policy": {"status": "passed", "cleanup_status": "failed"}},
            "cleanup-failure",
        ),
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
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(
        tmp_path,
        rl_action_overrides={
            "artifact_refs_and_sha256": [
                {
                    "opaque_ref": "missing-artifact.json",
                    "sha256": "a" * 64,
                    "owner": "rl_a0_evidence_owner",
                    "reviewer": "rl_gate_reviewer",
                }
            ],
            "redacted_argv_template": ["python", "--password=plain-secret"],
        },
    )
    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
    )

    assert rl_result["status"] == "BLOCKED"
    assert "missing-artifact" in rl_result["findings"]
    assert "sensitive-input" in rl_result["findings"]
    assert str(tmp_path) not in json.dumps(rl_result)


def test_rl_gate_rejects_raw_archive_list_path_and_url_inputs(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(
        tmp_path,
        rl_action_overrides={
            "redacted_argv_template": [
                "python",
                "--archive-ref",
                "/restricted/raw-backup.dump",
                "--list-ref",
                "https://example.invalid/raw-list.txt",
            ]
        },
    )
    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
    )

    assert rl_result["status"] == "BLOCKED"
    assert "unsafe-path" in rl_result["findings"]
    assert "sensitive-input" in rl_result["findings"]


def test_rl_gate_requires_actual_engine_attestation_for_migration(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(
        tmp_path,
        rl_action_type="alembic_upgrade",
        rl_action_overrides={"attestation_kind": "launcher"},
    )
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
    rl_manifest_path, rl_artifact_root, _ = rl_build_manifest(
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
    assert "trusted-boundary" in rl_result["findings"]


@pytest.mark.parametrize(
    "rl_sensitive_ref",
    [
        "password",
        "passwd",
        "secret",
        "token",
        "archive",
        "full-list",
        "list_path",
        "archive_path",
    ],
)
def test_rl_gate_rejects_sensitive_opaque_artifact_refs(
    tmp_path: Path,
    rl_sensitive_ref: str,
) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_artifact_path = rl_artifact_root / rl_sensitive_ref
    rl_artifact_path.write_bytes(b"safe summary\n")
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    rl_manifest["database_actions"][0]["artifact_refs_and_sha256"] = [
        {
            "opaque_ref": rl_sensitive_ref,
            "sha256": rl_sha256_file(rl_artifact_path),
            "owner": "rl_a0_evidence_owner",
            "reviewer": "rl_gate_reviewer",
        }
    ]
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


def test_rl_gate_defaults_blocked_when_local_boundary_metadata_is_self_written(
    tmp_path: Path,
) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)

    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
    )

    assert rl_result["status"] == "BLOCKED"
    assert "trusted-boundary-unverified" in rl_result["findings"]


def test_rl_gate_blocks_expired_external_assertion(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)

    def rl_expired_verifier(rl_request: dict) -> dict:
        rl_assertion = rl_fake_trusted_verifier(rl_request)
        rl_assertion["issued_at"] = "2019-01-01T00:00:00Z"
        rl_assertion["expires_at"] = "2020-01-01T00:00:00Z"
        rl_assertion["payload_digest"] = rl_compute_trusted_assertion_payload_digest(rl_assertion)
        return rl_assertion

    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
        rl_trusted_verifier=rl_expired_verifier,
        rl_producer_root=tmp_path / "producer-root",
    )

    assert rl_result["status"] == "BLOCKED"
    assert "trusted-assertion-expired" in rl_result["findings"]


def test_rl_gate_blocks_attestation_assertion_ref_mismatch(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_attestation = json.loads(rl_attestation_path.read_text(encoding="utf-8"))
    rl_attestation["trusted_assertion_ref"] = "other-external-assertion"
    rl_attestation_path.write_text(json.dumps(rl_attestation), encoding="utf-8")

    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
        rl_trusted_verifier=rl_fake_trusted_verifier,
        rl_producer_root=tmp_path / "producer-root",
    )

    assert rl_result["status"] == "BLOCKED"
    assert "attestation-assertion-ref" in rl_result["findings"]


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


@pytest.mark.parametrize(
    ("rl_field", "rl_value", "rl_expected"),
    [
        ("kind", "unknown-kind", "artifact-kind"),
        ("schema_version", "unknown-schema", "artifact-schema"),
        ("sha256", "0" * 64, "artifact-digest"),
        ("owner", "other-owner", "section-artifact-owner"),
        ("reviewer", "other-reviewer", "section-artifact-reviewer"),
    ],
)
def test_rl_gate_blocks_section_or_index_binding_mismatch(
    tmp_path: Path,
    rl_field: str,
    rl_value: str,
    rl_expected: str,
) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    rl_manifest["artifact_index"][0][rl_field] = rl_value
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

    assert rl_result["status"] == "BLOCKED"
    assert rl_expected in rl_result["findings"]


def test_rl_gate_blocks_artifact_content_mutation_after_attestation(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_artifact_path = rl_artifact_root / "artifact-source-1.json"
    rl_artifact_path.write_bytes(b'{"mutated":true}\n')

    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
        rl_trusted_verifier=rl_fake_trusted_verifier,
        rl_producer_root=tmp_path / "producer-root",
    )

    assert rl_result["status"] == "BLOCKED"
    assert "artifact-digest" in rl_result["findings"]


@pytest.mark.parametrize(
    ("rl_action_overrides", "rl_expected"),
    [
        ({"action_type": "unregistered_action"}, "action-unknown"),
        ({"attestation_kind": "not_applicable"}, "not-applicable-for-database-action"),
        ({"attestation_event_id": "missing-event"}, "event-unresolved"),
        ({"role": "other-role"}, "event-mismatch"),
    ],
)
def test_rl_gate_blocks_database_action_contract_failures(
    tmp_path: Path,
    rl_action_overrides: dict,
    rl_expected: str,
) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(
        tmp_path,
        rl_action_overrides=rl_action_overrides,
    )
    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
        rl_trusted_verifier=rl_fake_trusted_verifier,
        rl_producer_root=tmp_path / "producer-root",
    )

    assert rl_result["status"] == "BLOCKED"
    assert rl_expected in rl_result["findings"]


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


def test_rl_gate_blocks_symlinked_artifact_file(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_real_file = tmp_path / "real-summary.json"
    rl_real_file.write_bytes(b'{"safe":true}\n')
    rl_artifact_path = rl_artifact_root / "artifact-source-1.json"
    rl_artifact_path.unlink()
    try:
        rl_artifact_path.symlink_to(rl_real_file)
    except OSError:
        pytest.skip("symlink unavailable")

    rl_result = rl_emit_gate_evidence(
        rl_manifest_path,
        rl_artifact_root,
        "run-1",
        tmp_path / "gate-result.json",
        rl_attestation_path,
        rl_trusted_verifier=rl_fake_trusted_verifier,
        rl_producer_root=tmp_path / "producer-root",
    )

    assert rl_result["status"] == "BLOCKED"
    assert "artifact-missing-or-unsafe" in rl_result["findings"]


def test_rl_gate_blocks_renamed_archive_magic_and_full_list_payload(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_artifact_path = rl_artifact_root / "artifact-source-1.json"
    rl_artifact_path.write_bytes(b"PGDMP renamed archive\n")
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    rl_manifest["artifact_index"][0]["sha256"] = rl_sha256_file(rl_artifact_path)
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
    assert rl_result["status"] == "BLOCKED"
    assert "artifact-raw-archive" in rl_result["findings"]


def test_rl_gate_blocks_action_after_completion_and_duplicate_event_ids(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    rl_manifest["database_actions"][0]["finished_at"] = "2026-07-21T12:00:00Z"
    rl_manifest["attestation_events"]["guard-1"] = rl_manifest["guard_events"]["guard-1"]
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
    assert rl_result["status"] == "BLOCKED"
    assert "timestamp-order" in rl_result["findings"]
    assert "event-duplicate-or-invalid" in rl_result["findings"]


def test_rl_gate_blocks_section_time_ordering_failure(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    rl_manifest["context_contract"].update(
        {
            "started_at": "2026-07-21T12:00:00Z",
            "finished_at": "2026-07-21T12:01:00Z",
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
    assert rl_result["status"] == "BLOCKED"
    assert "section-time-order" in rl_result["findings"]


def test_rl_gate_blocks_snapshot_self_digest_without_parent_binding(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_artifact_path = rl_artifact_root / "artifact-source-1.json"
    rl_artifact_path.write_text('{"artifact_sha256":"self"}\n', encoding="utf-8")
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    rl_manifest["artifact_index"][0].update(
        {
            "kind": "canonical_snapshot",
            "sha256": rl_sha256_file(rl_artifact_path),
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
    assert rl_result["status"] == "BLOCKED"
    assert "snapshot-self-digest" in rl_result["findings"]
    assert "snapshot-parent-binding" in rl_result["findings"]


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
        rl_trusted_verifier=rl_fake_trusted_verifier,
        rl_producer_root=tmp_path / "producer-root",
    )

    assert rl_result["status"] == "BLOCKED"
    assert "semantic-gate-contract-version" in rl_result["findings"]


def test_rl_gate_blocks_generic_ok_artifact_payload(tmp_path: Path) -> None:
    rl_manifest_path, rl_artifact_root, rl_attestation_path = rl_prepare_reviewed_manifest(tmp_path)
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    rl_artifact_path = rl_artifact_root / "artifact-source-1.json"
    rl_artifact_path.write_text('{"ok":true}\n', encoding="utf-8")
    rl_manifest["artifact_index"][0]["sha256"] = rl_sha256_file(rl_artifact_path)
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

    assert rl_result["status"] == "BLOCKED"
    assert "artifact-payload-contract" in rl_result["findings"]
