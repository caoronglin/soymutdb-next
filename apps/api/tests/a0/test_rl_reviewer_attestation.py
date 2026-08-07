from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

rl_project_root = Path(__file__).resolve().parents[4]
if str(rl_project_root) not in sys.path:
    sys.path.insert(0, str(rl_project_root))

from tools.a0.rl_reviewer_attestation import (  # noqa: E402
    rl_compute_bundle_digest,
    rl_compute_manifest_digest,
    rl_compute_root_identity_digest,
    rl_compute_trusted_assertion_payload_digest,
    rl_create_reviewer_attestation,
)

rl_SCHEMA_VERSION = "a0.task8.evidence.v1"
rl_SECTION_NAMES = (
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
)


def rl_digest_bytes(rl_payload: bytes) -> str:
    return hashlib.sha256(rl_payload).hexdigest()


def rl_fake_trusted_verifier(rl_request: dict) -> dict:
    # Unit-only fake: this does not prove issuer identity, ACLs, or hostile-writer resistance.
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


def rl_write_artifact(
    rl_artifact_root: Path,
    rl_ref: str,
    rl_kind: str,
    rl_payload: dict,
    *,
    rl_parent_ref: str | None = None,
) -> dict:
    rl_path = rl_artifact_root / rl_ref
    rl_payload_bytes = json.dumps(rl_payload, sort_keys=True).encode("utf-8") + b"\n"
    rl_path.write_bytes(rl_payload_bytes)
    rl_entry = {
        "opaque_ref": rl_ref,
        "kind": rl_kind,
        "schema_version": rl_SCHEMA_VERSION,
        "sha256": rl_digest_bytes(rl_payload_bytes),
        "owner": "rl_a0_evidence_owner",
        "reviewer": "rl_gate_reviewer",
    }
    if rl_parent_ref is not None:
        rl_entry["parent_ref"] = rl_parent_ref
    return rl_entry


def rl_write_manifest(rl_tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    rl_tmp_path.mkdir(parents=True, exist_ok=True)
    rl_producer_root = rl_tmp_path / "producer-root"
    rl_artifact_root = rl_tmp_path / "producer-artifacts"
    rl_review_root = rl_tmp_path / "review-root"
    for rl_root in (rl_producer_root, rl_artifact_root, rl_review_root):
        rl_root.mkdir(parents=True, exist_ok=True)

    rl_artifact_index: list[dict] = []
    rl_source_entry = rl_write_artifact(
        rl_artifact_root,
        "artifact-source-1.json",
        "source_snapshot",
        {"ok": True},
    )
    rl_artifact_index.append(rl_source_entry)
    rl_parent_entry = rl_write_artifact(
        rl_artifact_root,
        "canonical-parent-1.json",
        "generic_task8_evidence",
        {"parent": True},
    )
    rl_artifact_index.append(rl_parent_entry)

    rl_sections: dict[str, dict] = {}
    for rl_section_index, rl_section_name in enumerate(rl_SECTION_NAMES, start=1):
        rl_kind = rl_section_name
        if rl_section_name == "canonical_snapshot_contract":
            rl_kind = "canonical_snapshot_contract"
        if rl_section_name == "semantic_projection_contract":
            rl_kind = "semantic_projection_contract"
        rl_payload = {"section": rl_section_name}
        if rl_section_name == "empty_before_rebuild" or rl_section_name == "empty_before_restore":
            rl_payload = {"empty": True, "section": rl_section_name}
        elif rl_section_name == "list_summary":
            rl_payload = {"valid": True, "section": rl_section_name}
        elif rl_section_name == "restore_semantic_result":
            rl_payload = {"semantic_match": True, "section": rl_section_name}
        elif rl_section_name == "source_stability":
            rl_payload = {"drift_detected": False, "section": rl_section_name}
        rl_ref = f"evidence-{rl_section_index}.json"
        rl_entry = rl_write_artifact(
            rl_artifact_root,
            rl_ref,
            rl_kind,
            rl_payload,
            rl_parent_ref="canonical-parent-1.json"
            if rl_section_name == "canonical_snapshot_contract"
            else None,
        )
        rl_artifact_index.append(rl_entry)
        rl_sections[rl_section_name] = {
            "status": "passed",
            "owner": "rl_a0_evidence_owner",
            "reviewer": "rl_gate_reviewer",
            "evidence_ref": rl_ref,
            "evidence_sha256": rl_entry["sha256"],
            "evidence_kind": rl_entry["kind"],
            "evidence_schema_version": rl_entry["schema_version"],
        }
    rl_sections["empty_before_rebuild"]["empty"] = True
    rl_sections["empty_before_restore"]["empty"] = True
    rl_sections["list_summary"]["valid"] = True
    rl_sections["restore_semantic_result"]["semantic_match"] = True
    rl_sections["source_stability"]["drift_detected"] = False
    rl_sections["restricted_archive_policy"]["cleanup_status"] = "passed"

    rl_action = {
        "action_id": "action-1",
        "action_type": "source_snapshot",
        "run_id": "run-1",
        "role": "rl_a0_producer",
        "preceding_guard_event_id": "guard-1",
        "attestation_event_id": "launcher-1",
        "attestation_kind": "launcher",
        "identity_digest_version": "a0.identity.v2",
        "system_identifier_digest": "1" * 64,
        "endpoint_context_digest": "2" * 64,
        "registry_tuple_digest": "9" * 64,
        "marker_digest": "a" * 64,
        "expiry": "2026-07-22T00:00:00Z",
        "configured_identity_redacted": {"database": "<redacted>", "role": "rl_a0_reader"},
        "redacted_argv_template": ["python", "-m", "rl_source_snapshot", "<opaque>"],
        "exit_code": 0,
        "stdout_sha256": "3" * 64,
        "stderr_sha256": "4" * 64,
        "started_at": "2026-07-21T10:00:00Z",
        "finished_at": "2026-07-21T10:01:00Z",
        "plan_source_sha256": "5" * 64,
        "spec_source_sha256": "6" * 64,
        "tool_source_sha256": "7" * 64,
        "test_source_sha256": "8" * 64,
        "executable_version": "python unit",
        "artifact_refs_and_sha256": [rl_source_entry],
        "owner": "rl_a0_evidence_owner",
        "reviewer": "rl_gate_reviewer",
    }
    rl_event_common = {
        "run_id": "run-1",
        "role": "rl_a0_producer",
        "identity_digest_version": "a0.identity.v2",
        "system_identifier_digest": "1" * 64,
        "endpoint_context_digest": "2" * 64,
        "configured_identity_redacted": rl_action["configured_identity_redacted"],
        "registry_tuple_digest": "9" * 64,
        "marker_digest": "a" * 64,
        "expiry": "2026-07-22T00:00:00Z",
        "redacted_argv_template": rl_action["redacted_argv_template"],
    }
    rl_manifest = {
        "a0_evidence_manifest_version": "a0.gate.v2",
        "run_id": "run-1",
        "producer_root_path": str(rl_producer_root),
        "artifact_root_path": str(rl_artifact_root),
        "producer_root_ref": "rl-producer-root",
        "artifact_root_ref": "rl-artifact-root",
        "project_root_digest": "c" * 64,
        "plan_source_sha256": "5" * 64,
        "spec_source_sha256": "6" * 64,
        "context_contract": rl_sections["context_contract"],
        "profile_contract": rl_sections["profile_contract"],
        "identity_digest_version": "a0.identity.v2",
        "producer_principal": "rl_a0_evidence_owner",
        "reviewer_principal": "rl_gate_reviewer",
        "trusted_assertion_issuer_id": "rl_unit_fake_issuer",
        "database_actions": [rl_action],
        "catalog_baseline": rl_sections["catalog_baseline"],
        "canonical_snapshot_contract": rl_sections["canonical_snapshot_contract"],
        "semantic_projection_contract": rl_sections["semantic_projection_contract"],
        "migration_trajectory": rl_sections["migration_trajectory"],
        "empty_before_rebuild": rl_sections["empty_before_rebuild"],
        "empty_before_restore": rl_sections["empty_before_restore"],
        "source_stability": rl_sections["source_stability"],
        "synthetic_source_policy": rl_sections["synthetic_source_policy"],
        "restricted_archive_policy": rl_sections["restricted_archive_policy"],
        "archive_summary": rl_sections["archive_summary"],
        "list_summary": rl_sections["list_summary"],
        "restore_semantic_result": rl_sections["restore_semantic_result"],
        "legacy_release_classification": rl_sections["legacy_release_classification"],
        "unresolved_queue": {"blocking_count": 0, "items": []},
        "artifact_index": rl_artifact_index,
        "review_attestation_ref": "review-attestation-run-1.json",
        "producer_evidence_completed_at": "2026-07-21T11:00:00Z",
        "guard_events": {"guard-1": {"event_id": "guard-1", "kind": "guard", **rl_event_common}},
        "attestation_events": {
            "launcher-1": {"event_id": "launcher-1", "kind": "launcher", **rl_event_common}
        },
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
    }
    rl_sections["canonical_snapshot_contract"]["evidence_kind"] = "canonical_snapshot_contract"
    rl_sections["semantic_projection_contract"]["evidence_kind"] = "semantic_projection_contract"
    rl_sections["catalog_baseline"]["evidence_kind"] = "catalog_baseline"
    rl_sections["context_contract"]["evidence_kind"] = "context_contract"
    rl_sections["profile_contract"]["evidence_kind"] = "profile_contract"
    rl_manifest["producer_root_identity_digest"] = rl_compute_root_identity_digest(rl_producer_root)
    rl_manifest["artifact_root_identity_digest"] = rl_compute_root_identity_digest(rl_artifact_root)
    rl_manifest["review_root_identity_digest"] = rl_compute_root_identity_digest(rl_review_root)
    rl_manifest_path = rl_tmp_path / "manifest.json"
    rl_manifest_path.write_text(json.dumps(rl_manifest, sort_keys=True), encoding="utf-8")
    return rl_manifest_path, rl_producer_root, rl_artifact_root, rl_review_root


def rl_write_trusted_boundary(rl_review_root: Path) -> Path:
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


def test_rl_manifest_digest_scope_excludes_derived_fields(tmp_path: Path) -> None:
    rl_manifest_path, _, _, _ = rl_write_manifest(tmp_path)
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    rl_first_manifest_digest = rl_compute_manifest_digest(rl_manifest)
    rl_first_bundle_digest = rl_compute_bundle_digest(rl_manifest)
    rl_manifest.update(
        {
            "manifest_digest": "f" * 64,
            "bundle_digest": "e" * 64,
            "review_attestation_ref": "/forbidden/raw/reviewer/path",
            "reviewer_attestation": {"decision": "BLOCKED"},
            "gate_result": {"a1_allowed": True},
        }
    )
    assert rl_compute_manifest_digest(rl_manifest) == rl_first_manifest_digest
    assert rl_compute_bundle_digest(rl_manifest) == rl_first_bundle_digest


def test_rl_in_scope_mutation_changes_frozen_digests(tmp_path: Path) -> None:
    rl_manifest_path, _, _, _ = rl_write_manifest(tmp_path)
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    rl_first_manifest_digest = rl_compute_manifest_digest(rl_manifest)
    rl_first_bundle_digest = rl_compute_bundle_digest(rl_manifest)
    rl_manifest["database_actions"][0]["stdout_sha256"] = "a" * 64
    assert rl_compute_manifest_digest(rl_manifest) != rl_first_manifest_digest
    assert rl_compute_bundle_digest(rl_manifest) != rl_first_bundle_digest


def test_rl_reviewer_attestation_passes_only_with_fake_external_assertion(tmp_path: Path) -> None:
    (
        rl_manifest_path,
        rl_producer_root,
        rl_artifact_root,
        rl_review_root,
    ) = rl_write_manifest(tmp_path)
    rl_write_trusted_boundary(rl_review_root)
    rl_attestation = rl_create_reviewer_attestation(
        rl_manifest_path,
        rl_review_root,
        "run-1",
        rl_fake_trusted_verifier,
        rl_producer_root=rl_producer_root,
        rl_artifact_root=rl_artifact_root,
    )
    assert rl_attestation["decision"] == "PASS"
    assert rl_attestation["blocking_findings"] == []
    assert rl_attestation["trusted_assertion"]["version"] == "a0.trusted-assertion.v1"
    assert rl_attestation["reviewer_identity"] == "rl_gate_reviewer"


def test_rl_reviewer_attestation_blocks_missing_or_failed_verifier(tmp_path: Path) -> None:
    (
        rl_manifest_path,
        rl_producer_root,
        rl_artifact_root,
        rl_review_root,
    ) = rl_write_manifest(tmp_path)
    rl_write_trusted_boundary(rl_review_root)
    rl_missing = rl_create_reviewer_attestation(
        rl_manifest_path,
        rl_review_root,
        "run-1",
        rl_producer_root=rl_producer_root,
        rl_artifact_root=rl_artifact_root,
    )
    assert rl_missing["decision"] == "BLOCKED"
    assert "trusted-boundary-unverified" in rl_missing["blocking_findings"]

    def rl_failed_verifier(_: dict) -> None:
        return None

    rl_failed = rl_create_reviewer_attestation(
        rl_manifest_path,
        rl_review_root / "failed",
        "run-1",
        rl_failed_verifier,
        rl_producer_root=rl_producer_root,
        rl_artifact_root=rl_artifact_root,
    )
    assert rl_failed["decision"] == "BLOCKED"
    assert "trusted-boundary-unverified" in rl_failed["blocking_findings"]


def test_rl_reviewer_attestation_blocks_assertion_manifest_digest_mismatch(
    tmp_path: Path,
) -> None:
    (
        rl_manifest_path,
        rl_producer_root,
        rl_artifact_root,
        rl_review_root,
    ) = rl_write_manifest(tmp_path)
    rl_write_trusted_boundary(rl_review_root)

    def rl_mismatched_verifier(rl_request: dict) -> dict:
        rl_assertion = rl_fake_trusted_verifier(rl_request)
        rl_assertion["manifest_sha256"] = "0" * 64
        rl_assertion["payload_digest"] = rl_compute_trusted_assertion_payload_digest(rl_assertion)
        return rl_assertion

    rl_attestation = rl_create_reviewer_attestation(
        rl_manifest_path,
        rl_review_root,
        "run-1",
        rl_mismatched_verifier,
        rl_producer_root=rl_producer_root,
        rl_artifact_root=rl_artifact_root,
    )

    assert rl_attestation["decision"] == "BLOCKED"
    assert "trusted-assertion-digest-mismatch" in rl_attestation["blocking_findings"]


@pytest.mark.parametrize("rl_bad_ref", ["a\x01.json", "a\n.json", "a\t.json", "archive-list.json"])
def test_rl_reviewer_attestation_rejects_control_or_sensitive_ref(
    tmp_path: Path,
    rl_bad_ref: str,
) -> None:
    rl_manifest_path, _, _, rl_review_root = rl_write_manifest(tmp_path)
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    rl_manifest["review_attestation_ref"] = rl_bad_ref
    rl_manifest_path.write_text(json.dumps(rl_manifest), encoding="utf-8")
    rl_attestation = rl_create_reviewer_attestation(rl_manifest_path, rl_review_root, "run-1")
    assert rl_attestation["decision"] == "BLOCKED"
    assert "attestation-ref" in rl_attestation["blocking_findings"]


def test_rl_reviewer_attestation_rejects_self_hash_scope(tmp_path: Path) -> None:
    rl_manifest_path, _, _, rl_review_root = rl_write_manifest(tmp_path)
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    rl_manifest["digest_scope"] = ["database_actions", "manifest_digest"]
    rl_manifest_path.write_text(json.dumps(rl_manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="self-hash"):
        rl_create_reviewer_attestation(rl_manifest_path, rl_review_root, "run-1")


@pytest.mark.parametrize("rl_overlap", ["equal", "ancestor", "descendant"])
def test_rl_reviewer_attestation_blocks_overlapping_roots(
    tmp_path: Path,
    rl_overlap: str,
) -> None:
    (
        rl_manifest_path,
        rl_producer_root,
        rl_artifact_root,
        rl_review_root,
    ) = rl_write_manifest(tmp_path)
    rl_write_trusted_boundary(rl_review_root)
    if rl_overlap == "equal":
        rl_artifact_root = rl_producer_root
    elif rl_overlap == "ancestor":
        rl_artifact_root = tmp_path
    else:
        rl_artifact_root = rl_producer_root / "nested"
        rl_artifact_root.mkdir()
    rl_attestation = rl_create_reviewer_attestation(
        rl_manifest_path,
        rl_review_root,
        "run-1",
        rl_fake_trusted_verifier,
        rl_producer_root=rl_producer_root,
        rl_artifact_root=rl_artifact_root,
    )
    assert rl_attestation["decision"] == "BLOCKED"
    assert "root-overlap" in rl_attestation["blocking_findings"]


def test_rl_reviewer_attestation_blocks_symlink_review_root(tmp_path: Path) -> None:
    (
        rl_manifest_path,
        rl_producer_root,
        rl_artifact_root,
        rl_review_root,
    ) = rl_write_manifest(tmp_path)
    rl_real_review_root = tmp_path / "real-review-root"
    rl_real_review_root.mkdir()
    rl_symlink_root = tmp_path / "symlink-review-root"
    try:
        rl_symlink_root.symlink_to(rl_real_review_root, target_is_directory=True)
    except OSError:
        pytest.skip("symlink unavailable")
    rl_attestation = rl_create_reviewer_attestation(
        rl_manifest_path,
        rl_symlink_root,
        "run-1",
        rl_fake_trusted_verifier,
        rl_producer_root=rl_producer_root,
        rl_artifact_root=rl_artifact_root,
    )
    assert rl_attestation["decision"] == "BLOCKED"
    assert "root-symlink-or-invalid" in rl_attestation["blocking_findings"]


def test_rl_reviewer_attestation_blocks_missing_semantic_gate_contract_version(
    tmp_path: Path,
) -> None:
    (
        rl_manifest_path,
        rl_producer_root,
        rl_artifact_root,
        rl_review_root,
    ) = rl_write_manifest(tmp_path)
    rl_write_trusted_boundary(rl_review_root)
    rl_manifest = json.loads(rl_manifest_path.read_text(encoding="utf-8"))
    rl_manifest.pop("semantic_gate_contract_version", None)
    rl_manifest_path.write_text(json.dumps(rl_manifest), encoding="utf-8")

    rl_attestation = rl_create_reviewer_attestation(
        rl_manifest_path,
        rl_review_root,
        "run-1",
        rl_fake_trusted_verifier,
        rl_producer_root=rl_producer_root,
        rl_artifact_root=rl_artifact_root,
    )

    assert rl_attestation["decision"] == "BLOCKED"
    assert "semantic-gate-contract-version" in rl_attestation["blocking_findings"]
