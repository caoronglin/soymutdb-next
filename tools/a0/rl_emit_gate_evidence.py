from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .rl_reviewer_attestation import (
    rl_ACTION_RECIPE_VERSION,
    rl_ATTESTATION_VERSION,
    rl_build_trusted_assertion_request,
    rl_compute_bundle_digest,
    rl_compute_manifest_digest,
    rl_compute_review_source_digest,
    rl_GATE_RESULT_VERSION,
    rl_is_opaque_ref,
    rl_load_json,
    rl_manifest_scope,
    rl_normalize_manifest,
    rl_parse_timestamp,
    rl_root_identity_bindings,
    rl_safe_canonical_directory,
    rl_safe_regular_file,
    rl_SEMANTIC_GATE_CONTRACT_VERSION,
    rl_TrustedAssertionVerifier,
    rl_validate_manifest_contract,
    rl_verify_trusted_assertion,
)


def rl_finding(rl_findings: list[str], rl_code: str) -> None:
    if rl_code not in rl_findings:
        rl_findings.append(rl_code)


def rl_attestation_path_is_safe(
    rl_attestation_path: Path,
    rl_review_root: Path,
    rl_expected_ref: Any,
    rl_findings: list[str],
) -> bytes | None:
    if not isinstance(rl_expected_ref, str) or not rl_is_opaque_ref(rl_expected_ref):
        rl_finding(rl_findings, "attestation-ref")
        return None
    from .rl_reviewer_attestation import rl_attestation_path_is_exact

    if not rl_attestation_path_is_exact(
        rl_attestation_path, rl_review_root, rl_expected_ref
    ):
        rl_finding(rl_findings, "attestation-path-binding")
        return None
    rl_file = rl_safe_regular_file(rl_review_root, rl_expected_ref)
    if rl_file is None:
        rl_finding(rl_findings, "missing-attestation")
        return None
    return rl_file[1]


def rl_validate_attestation(
    rl_manifest: Mapping[str, Any],
    rl_attestation_path: Path,
    rl_review_root: Path,
    rl_run_id: str,
    rl_root_identity_digests: Mapping[str, str] | None,
    rl_trusted_verifier: rl_TrustedAssertionVerifier | Any | None,
    rl_findings: list[str],
) -> None:
    rl_attestation_bytes = rl_attestation_path_is_safe(
        rl_attestation_path,
        rl_review_root,
        rl_manifest.get("review_attestation_ref"),
        rl_findings,
    )
    if rl_attestation_bytes is None:
        return
    try:
        rl_attestation = json.loads(rl_attestation_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        rl_finding(rl_findings, "attestation-invalid")
        return
    if not isinstance(rl_attestation, Mapping):
        rl_finding(rl_findings, "attestation-invalid")
        return
    if rl_attestation.get("review_attestation_version") != rl_ATTESTATION_VERSION:
        rl_finding(rl_findings, "attestation-version")
    if (
        rl_attestation.get("semantic_gate_contract_version")
        != rl_SEMANTIC_GATE_CONTRACT_VERSION
    ):
        rl_finding(rl_findings, "semantic-gate-contract-version")
    if rl_attestation.get("run_id") != rl_run_id:
        rl_finding(rl_findings, "attestation-run-id")
    if rl_attestation.get("decision") != "PASS":
        rl_finding(rl_findings, "attestation-decision")
    if rl_attestation.get("blocking_findings") != []:
        rl_finding(rl_findings, "attestation-findings")
    if rl_attestation.get("review_attestation_ref") != rl_manifest.get(
        "review_attestation_ref"
    ):
        rl_finding(rl_findings, "attestation-ref-mismatch")
    try:
        rl_manifest_sha256 = rl_compute_manifest_digest(rl_manifest)
        rl_bundle_sha256 = rl_compute_bundle_digest(
            rl_manifest, Path(str(rl_manifest.get("artifact_root_path")))
        )
    except (ValueError, TypeError):
        rl_finding(rl_findings, "attestation-digest")
        return
    if rl_attestation.get("manifest_sha256") != rl_manifest_sha256:
        rl_finding(rl_findings, "attestation-manifest-digest")
    if rl_attestation.get("recomputed_bundle_sha256") != rl_bundle_sha256:
        rl_finding(rl_findings, "attestation-bundle-digest")
    rl_completion = rl_parse_timestamp(
        rl_manifest.get("producer_evidence_completed_at")
    )
    rl_attestation_completion = rl_parse_timestamp(
        rl_attestation.get("producer_evidence_completed_at")
    )
    rl_review_started = rl_parse_timestamp(rl_attestation.get("review_started_at"))
    rl_review_finished = rl_parse_timestamp(rl_attestation.get("review_finished_at"))
    if (
        rl_completion is None
        or rl_attestation_completion != rl_completion
        or rl_review_started is None
        or rl_review_finished is None
        or not (rl_completion <= rl_review_started <= rl_review_finished)
    ):
        rl_finding(rl_findings, "attestation-time")
    if rl_root_identity_digests is None:
        rl_finding(rl_findings, "root-binding")
        return
    rl_request = rl_build_trusted_assertion_request(
        rl_manifest,
        rl_run_id,
        rl_root_identity_digests,
        rl_manifest_sha256,
        rl_bundle_sha256,
    )
    rl_verified_assertion, rl_assertion_findings = rl_verify_trusted_assertion(
        rl_trusted_verifier, rl_request
    )
    for rl_assertion_finding in rl_assertion_findings:
        rl_finding(rl_findings, rl_assertion_finding)
    if rl_verified_assertion is None:
        return
    if rl_attestation.get("trusted_assertion") != rl_verified_assertion:
        rl_finding(rl_findings, "attestation-assertion-mismatch")
    if rl_attestation.get("reviewer_identity") != rl_verified_assertion.get(
        "reviewer_principal"
    ):
        rl_finding(rl_findings, "reviewer-identity")
    rl_expected_review_source = rl_compute_review_source_digest(
        rl_manifest_sha256,
        rl_bundle_sha256,
        str(rl_verified_assertion.get("reviewer_principal")),
        str(rl_manifest.get("producer_evidence_completed_at")),
        rl_trusted_boundary=rl_manifest.get("trusted_boundary")
        if isinstance(rl_manifest.get("trusted_boundary"), Mapping)
        else None,
        rl_root_identity_digests=rl_root_identity_digests,
        rl_assertion_payload_digest=str(rl_verified_assertion.get("payload_digest")),
        rl_review_attestation_ref=str(rl_manifest.get("review_attestation_ref")),
        rl_review_started_at=str(rl_attestation.get("review_started_at")),
        rl_review_finished_at=str(rl_attestation.get("review_finished_at")),
        rl_decision=str(rl_attestation.get("decision")),
        rl_blocking_findings=list(rl_attestation.get("blocking_findings", [])),
    )
    if rl_attestation.get("review_source_sha256") != rl_expected_review_source:
        rl_finding(rl_findings, "review-source-digest")


def rl_emit_gate_evidence(
    rl_manifest_path: Path,
    rl_artifact_root: Path,
    rl_run_id: str,
    rl_output_path: Path,
    rl_attestation_path: Path,
    rl_review_root: Path | None = None,
    rl_trusted_verifier: rl_TrustedAssertionVerifier | Any | None = None,
    rl_producer_root: Path | None = None,
) -> dict[str, Any]:
    rl_findings: list[str] = []
    rl_manifest: dict[str, Any] = {}
    if isinstance(rl_manifest_path, bool) or not isinstance(rl_manifest_path, Path):
        raise TypeError("manifest path required")
    if not isinstance(rl_artifact_root, Path) or not isinstance(rl_output_path, Path):
        raise TypeError("path arguments required")
    if not isinstance(rl_attestation_path, Path):
        raise TypeError("attestation path required")
    rl_review_root = rl_review_root or rl_attestation_path.parent
    try:
        rl_manifest = rl_normalize_manifest(rl_load_json(rl_manifest_path))
        if rl_producer_root is None and isinstance(
            rl_manifest.get("producer_root_path"), str
        ):
            rl_producer_root = Path(rl_manifest["producer_root_path"])
        if rl_safe_canonical_directory(rl_artifact_root) is None:
            rl_finding(rl_findings, "artifact-root")
        if rl_safe_canonical_directory(rl_review_root) is None:
            rl_finding(rl_findings, "review-root")
        try:
            rl_manifest_scope(rl_manifest)
        except (ValueError, TypeError):
            rl_finding(rl_findings, "self-hash-scope")
        rl_root_digests = rl_root_identity_bindings(
            rl_manifest,
            rl_producer_root,
            rl_artifact_root,
            rl_review_root,
            rl_findings,
        )
        rl_validate_manifest_contract(
            rl_manifest,
            rl_run_id,
            rl_artifact_root,
            rl_findings,
        )
        if rl_root_digests is None:
            rl_finding(rl_findings, "trusted-boundary")
        else:
            try:
                rl_manifest_sha256 = rl_compute_manifest_digest(rl_manifest)
                rl_bundle_sha256 = rl_compute_bundle_digest(
                    rl_manifest, rl_artifact_root
                )
                rl_request = rl_build_trusted_assertion_request(
                    rl_manifest,
                    rl_run_id,
                    rl_root_digests,
                    rl_manifest_sha256,
                    rl_bundle_sha256,
                )
                _, rl_assertion_findings = rl_verify_trusted_assertion(
                    rl_trusted_verifier, rl_request
                )
                for rl_assertion_finding in rl_assertion_findings:
                    rl_finding(rl_findings, rl_assertion_finding)
            except (ValueError, TypeError):
                rl_finding(rl_findings, "trusted-boundary-unverified")
        rl_validate_attestation(
            rl_manifest,
            rl_attestation_path,
            rl_review_root,
            rl_run_id,
            rl_root_digests,
            rl_trusted_verifier,
            rl_findings,
        )
        try:
            rl_manifest_sha256 = rl_compute_manifest_digest(rl_manifest)
            rl_bundle_sha256 = rl_compute_bundle_digest(rl_manifest, rl_artifact_root)
        except (ValueError, TypeError):
            rl_manifest_sha256 = None
            rl_bundle_sha256 = None
            rl_finding(rl_findings, "self-hash-scope")
    except Exception:
        rl_manifest_sha256 = None
        rl_bundle_sha256 = None
        rl_finding(rl_findings, "gate-contract-error")
    rl_result = {
        "a0_gate_result_version": rl_GATE_RESULT_VERSION,
        "semantic_gate_contract_version": rl_SEMANTIC_GATE_CONTRACT_VERSION,
        "action_recipe_version": rl_ACTION_RECIPE_VERSION,
        "run_id": rl_run_id,
        "manifest_sha256": rl_manifest_sha256,
        "bundle_sha256": rl_bundle_sha256,
        "status": "PASS" if not rl_findings else "BLOCKED",
        "findings": list(dict.fromkeys(rl_findings)),
        "a0_observational_evidence_complete": not bool(rl_findings),
        "a1_allowed": False,
        "production_migration_allowed": False,
        "production_write_cutover_allowed": False,
        "publication_implementation_allowed": False,
    }
    try:
        rl_output_path.parent.mkdir(parents=True, exist_ok=True)
        rl_output_path.write_bytes(
            json.dumps(rl_result, ensure_ascii=False, sort_keys=True, indent=2).encode(
                "utf-8"
            )
            + b"\n"
        )
    except Exception:
        rl_result["status"] = "BLOCKED"
        rl_finding(rl_result["findings"], "gate-result-write")
    return rl_result


def rl_main() -> int:
    import argparse

    rl_parser = argparse.ArgumentParser(
        description="Emit an observational A0 gate result"
    )
    rl_parser.add_argument("--manifest-ref", required=True)
    rl_parser.add_argument("--artifact-root-ref", required=True)
    rl_parser.add_argument("--attestation-ref", required=True)
    rl_parser.add_argument("--review-root-ref", required=True)
    rl_parser.add_argument("--run-id", required=True)
    rl_parser.add_argument("--output-ref", required=True)
    rl_args = rl_parser.parse_args()
    rl_result = rl_emit_gate_evidence(
        Path(rl_args.manifest_ref),
        Path(rl_args.artifact_root_ref),
        rl_args.run_id,
        Path(rl_args.output_ref),
        Path(rl_args.attestation_ref),
        Path(rl_args.review_root_ref),
    )
    print(json.dumps(rl_result, ensure_ascii=False, sort_keys=True))
    return 0 if rl_result.get("status") == "PASS" else 1


__all__ = ["rl_emit_gate_evidence", "rl_main"]
