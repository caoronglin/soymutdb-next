from __future__ import annotations

import hashlib
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

from tools.a0.rl_reviewer_attestation import (  # noqa: E402
    rl_compute_bundle_digest,
    rl_compute_manifest_digest,
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
    from fixtures.rl_v2_fixture import rl_fake_trusted_verifier as _v2

    return _v2(rl_request)


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
    from fixtures.rl_v2_fixture import build_manifest

    rl_manifest_path, rl_artifact_root, _ = build_manifest(rl_tmp_path)
    rl_producer_root = rl_tmp_path / "producer-root"
    rl_review_root = rl_tmp_path / "review-root"
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
    assert rl_attestation["trusted_assertion"]["version"] == "a0.trusted-assertion.v2"
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
    assert "trusted-assertion-manifest_sha256-mismatch" in rl_attestation["blocking_findings"]


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
    rl_attestation = rl_create_reviewer_attestation(rl_manifest_path, rl_review_root, "run-1")
    assert rl_attestation["decision"] == "BLOCKED"
    assert "self-hash-scope" in rl_attestation["blocking_findings"]


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
