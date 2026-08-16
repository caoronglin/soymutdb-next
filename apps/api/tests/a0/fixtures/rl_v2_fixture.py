"""Shared v2 manifest/artifact/assertion builder for A0 gate tests.

Produces a *complete and valid* ``a0.gate.v2`` manifest (33-phase recipe, 16
fully-populated section contracts, v2 trusted-assertion) so the gate reaches
the business-layer findings the tests assert, instead of being short-circuited
by top-level contract codes.

Test-only: the fake trusted-assertion verifier never proves issuer identity,
ACLs, or hostile-writer resistance.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from tools.a0 import rl_reviewer_attestation as rl_att

rl_IDENTITY_VERSION = "a0.identity.v2"
rl_PRODUCER = "rl_a0_evidence_owner"
rl_REVIEWER = "rl_gate_reviewer"
rl_ISSUER = "rl_unit_fake_issuer"
rl_RECIPE_ID = rl_att.rl_RECIPE_ID
rl_ACTION_RECIPE_VERSION = rl_att.rl_ACTION_RECIPE_VERSION
rl_SEMANTIC_GATE_CONTRACT_VERSION = rl_att.rl_SEMANTIC_GATE_CONTRACT_VERSION


def rl_sha256_hex(rl_value: Any) -> str:
    if isinstance(rl_value, bytes):
        rl_bytes = rl_value
    elif isinstance(rl_value, str):
        rl_bytes = rl_value.encode("utf-8")
    else:
        rl_bytes = json.dumps(rl_value, sort_keys=True).encode("utf-8")
    return hashlib.sha256(rl_bytes).hexdigest()


def rl_distinct(rl_counter: int) -> str:
    """Deterministic distinct 64-hex digest."""
    return rl_sha256_hex(f"rl-distinct-{rl_counter}")


# ---------------------------------------------------------------------------
# trusted-assertion v2 verifier (fake)
# ---------------------------------------------------------------------------

def rl_trusted_assertion_required() -> tuple[str, ...]:
    return (
        "version",
        "semantic_gate_contract_version",
        "action_recipe_version",
        "assertion_id",
        "assertion_ref",
        "issuer_id",
        "subject",
        "audience",
        "run_id",
        "manifest_sha256",
        "bundle_sha256",
        "review_attestation_ref",
        "producer_principal",
        "reviewer_principal",
        "root_identity_digests",
        "root_claims",
        "source_claims",
        "ci_identity",
        "producer_writable",
        "reviewer_controlled",
        "access_control_verified",
        "issued_at",
        "expires_at",
        "nonce",
        "replay_guard",
        "payload_digest",
    )


def rl_fake_trusted_verifier(rl_request: dict) -> dict:
    """Fake v2 verifier mirroring every request field (never real proof)."""
    rl_assertion: dict[str, Any] = {
        "version": rl_att.rl_TRUSTED_ASSERTION_VERSION,
        "semantic_gate_contract_version": rl_request["semantic_gate_contract_version"],
        "action_recipe_version": rl_request["action_recipe_version"],
        "assertion_id": "external-assertion-1",
        "assertion_ref": "external-assertion-1",
        "issuer_id": rl_request["expected_issuer_id"],
        "subject": rl_request["reviewer_principal"],
        "audience": rl_request["audience"],
        "run_id": rl_request["run_id"],
        "manifest_sha256": rl_request["manifest_sha256"],
        "bundle_sha256": rl_request["bundle_sha256"],
        "review_attestation_ref": rl_request["review_attestation_ref"],
        "producer_principal": rl_request["producer_principal"],
        "reviewer_principal": rl_request["reviewer_principal"],
        "root_identity_digests": deepcopy(rl_request["root_identity_digests"]),
        "root_claims": deepcopy(rl_request.get("root_claims")),
        "source_claims": deepcopy(rl_request.get("source_claims")),
        "ci_identity": deepcopy(rl_request.get("ci_identity")),
        "producer_writable": False,
        "reviewer_controlled": True,
        "access_control_verified": True,
        "issued_at": "2020-01-01T08:00:00Z",
        "expires_at": "2099-01-01T08:00:00Z",
        "nonce": "unit-nonce-1",
        "replay_guard": {"kind": "unit", "id": "rg-1"},
    }
    rl_assertion["payload_digest"] = rl_att.rl_compute_trusted_assertion_payload_digest(rl_assertion)
    return rl_assertion


# ---------------------------------------------------------------------------
# section contracts
# ---------------------------------------------------------------------------

rl_SECTION_REQUIRED: dict[str, tuple[str, ...]] = {
    "context_contract": ("project_root_digest", "runtime_facts_ref", "runtime_facts_digest", "cwd_digest", "absolute_paths", "fresh_process", "in_process_settings_switch"),
    "profile_contract": ("registry_digest", "profile_only", "sanitized_env", "shell_false", "interactive_password", "mode_0700", "mode_0600"),
    "catalog_baseline": ("same_version_init_ref", "same_version_init_digest", "reference_digest", "server_digest", "category_digests", "unknown_count", "read_failures", "match"),
    "canonical_snapshot_contract": ("canonical_version", "structural_policy_digest", "count_independent", "raw_rows", "self_digest_forbidden", "parent_sidecar_required", "sidecar_ref", "sidecar_sha256"),
    "semantic_projection_contract": ("semantic_version", "policy_digest", "stable_key_digest", "exclusion_digest", "positive_table_count", "content_digests_only", "raw_rows", "sequence_state", "unknown_fields"),
    "migration_trajectory": ("initial_revision", "downgrade_revision", "final_revision", "edge_count", "edges", "nonempty_edges", "strict_ancestor", "downgrade_rehearsal", "seed_semantic", "revision_snapshot_refs", "revision_snapshot_digests"),
    "empty_before_rebuild": ("identity_digest", "empty", "user_object_count", "snapshot_ref", "snapshot_sha256", "catalog_baseline_match", "guard_event_ids", "action_ids"),
    "empty_before_restore": ("identity_digest", "empty", "user_object_count", "snapshot_ref", "snapshot_sha256", "catalog_baseline_match", "guard_event_ids", "action_ids"),
    "source_stability": ("pre_binding_digest", "post_binding_digest", "structural_match", "semantic_match", "sequence_match", "drift_detected"),
    "synthetic_source_policy": ("classification", "approval_digest", "policy_digest", "seed_digest", "raw_sensitive"),
    "restricted_archive_policy": ("root_identity_digest", "acl_claim_digest", "mode_0700", "mode_0600", "opaque_only", "raw_ordinary", "retention_outcome", "cleanup_status"),
    "archive_summary": ("archive_ref", "archive_sha256", "item_count", "opaque_only", "raw_archive", "unknown_count", "failures"),
    "list_summary": ("list_ref", "list_sha256", "item_count", "opaque_only", "raw_full_list", "unknown_count", "failures"),
    "restore_semantic_result": ("structural_match", "content_match", "count_match", "sequence_match", "extensions_match", "enums_match", "revision_match", "mismatches"),
    "legacy_release_classification": ("classifier", "input_digest", "dataset_count", "release_count", "records_ref", "records_sha256", "unresolved_count", "items"),
}

rl_SECTION_KIND: dict[str, str] = {
    "context_contract": "context_contract",
    "profile_contract": "profile_contract",
    "catalog_baseline": "catalog_baseline",
    "canonical_snapshot_contract": "canonical_snapshot",
    "semantic_projection_contract": "semantic_projection",
    "migration_trajectory": "migration_trajectory",
    "empty_before_rebuild": "empty_proof_rebuild",
    "empty_before_restore": "empty_proof_restore",
    "source_stability": "source_stability",
    "synthetic_source_policy": "synthetic_source_policy",
    "restricted_archive_policy": "restricted_archive",
    "archive_summary": "archive_summary",
    "list_summary": "list_summary",
    "restore_semantic_result": "restore_semantic_result",
    "legacy_release_classification": "legacy_release_classification",
}

_SHA_FIELDS = {
    "project_root_digest", "runtime_facts_digest", "cwd_digest", "registry_digest",
    "same_version_init_digest", "reference_digest", "server_digest",
    "structural_policy_digest", "policy_digest", "stable_key_digest",
    "exclusion_digest", "identity_digest", "snapshot_sha256", "pre_binding_digest",
    "post_binding_digest", "approval_digest", "seed_digest", "root_identity_digest",
    "acl_claim_digest", "archive_sha256", "list_sha256", "input_digest",
    "records_sha256", "sidecar_sha256",
}
_TRUE_FIELDS = {
    "absolute_paths", "fresh_process", "profile_only", "sanitized_env",
    "shell_false", "mode_0700", "mode_0600", "count_independent",
    "self_digest_forbidden", "parent_sidecar_required", "content_digests_only",
    "sequence_state", "nonempty_edges", "strict_ancestor", "downgrade_rehearsal",
    "seed_semantic", "empty", "catalog_baseline_match", "structural_match",
    "semantic_match", "sequence_match", "opaque_only", "content_match",
    "count_match", "extensions_match", "enums_match", "revision_match", "match",
}
_FALSE_FIELDS = {
    "raw_rows", "in_process_settings_switch", "interactive_password",
    "raw_ordinary", "drift_detected", "raw_archive", "raw_full_list", "raw_sensitive",
}
_LIST_FIELDS = {"read_failures", "unknown_fields", "mismatches", "failures", "items"}
_REF_FIELDS = {
    "runtime_facts_ref", "same_version_init_ref", "snapshot_ref", "sidecar_ref",
    "archive_ref", "list_ref", "records_ref",
}


def rl_section_values(rl_section: str, rl_counter: int) -> dict[str, Any]:
    rl_values: dict[str, Any] = {}
    rl_step = rl_counter * 1000
    for rl_idx, rl_field in enumerate(rl_SECTION_REQUIRED[rl_section]):
        if rl_field in _SHA_FIELDS:
            rl_values[rl_field] = rl_distinct(rl_step + rl_idx)
        elif rl_field in _TRUE_FIELDS:
            rl_values[rl_field] = True
        elif rl_field in _FALSE_FIELDS:
            rl_values[rl_field] = False
        elif rl_field in _LIST_FIELDS:
            rl_values[rl_field] = []
        elif rl_field in _REF_FIELDS:
            rl_values[rl_field] = f"ref{rl_step + rl_idx}"
        elif rl_field == "category_digests":
            rl_values[rl_field] = {
                rl_cat: rl_distinct(rl_step + 50 + rl_j)
                for rl_j, rl_cat in enumerate(sorted(rl_att.rl_CATALOG_CATEGORIES))
            }
        elif rl_field == "edges":
            rl_values[rl_field] = [
                {
                    "forward_action_id": "action-1",
                    "downgrade_action_id": "action-1",
                    "reupgrade_action_id": "action-1",
                }
            ]
            rl_values["edge_count"] = 1
        elif rl_field == "revision_snapshot_refs":
            rl_values[rl_field] = ["ref-snap-1"]
        elif rl_field == "revision_snapshot_digests":
            rl_values[rl_field] = [rl_distinct(rl_step + 7)]
        elif rl_field == "guard_event_ids":
            rl_values[rl_field] = [f"guard-{rl_step}"]
        elif rl_field == "action_ids":
            rl_values[rl_field] = [f"action-{rl_step}"]
        elif rl_field in ("dataset_count", "release_count", "positive_table_count", "item_count"):
            rl_values[rl_field] = 1 if rl_field in ("dataset_count", "positive_table_count") else 0
        elif rl_field in ("unknown_count", "unresolved_count", "user_object_count"):
            rl_values[rl_field] = 0
        elif rl_field == "classification":
            rl_values[rl_field] = "synthetic-non-sensitive"
        elif rl_field in ("cleanup_status", "retention_outcome"):
            rl_values[rl_field] = "passed"
        elif rl_field in ("canonical_version", "semantic_version", "initial_revision", "downgrade_revision", "final_revision", "classifier"):
            rl_values[rl_field] = "a0-fixture-v1"
        else:
            rl_values[rl_field] = True
    return rl_values


# ---------------------------------------------------------------------------
# action / event / manifest builder
# ---------------------------------------------------------------------------

rl_COMMON_PAYLOAD_FIELDS = {
    "semantic_gate_contract_version",
    "section_name",
    "artifact_kind",
    "schema_version",
    "run_id",
    "owner",
    "reviewer",
    "status",
    "producer_action_ids",
}


def rl_action_type_for_phase(rl_phase: str) -> str:
    rl_types = rl_att.rl_PHASE_ACTION_TYPES[rl_phase]
    # pick a non-alembic type first (simple), alembic only for M02/M04/M06/M07/M09
    if "alembic_upgrade" in rl_types:
        return "alembic_upgrade"
    if "alembic_downgrade" in rl_types:
        return "alembic_downgrade"
    if "migration_reupgrade" in rl_types:
        return "migration_reupgrade"
    return sorted(rl_types)[0]


def rl_primary_kind_for_phase(rl_phase: str) -> str | None:
    rl_section = rl_att.rl_PHASE_PRIMARY_SECTIONS.get(rl_phase)
    if rl_section is None:
        return None
    if rl_section == "action_output":
        return rl_att.rl_ACTION_OUTPUT_KIND
    return rl_att.rl_SECTION_CONTRACTS[rl_section]["kind"]


def build_manifest(
    rl_tmp_path: Path,
    *,
    rl_action_overrides: dict | None = None,
    rl_top_overrides: dict | None = None,
    rl_mutate: dict | None = None,
) -> tuple[Path, Path, dict]:
    """Build a complete valid v2 manifest; returns (manifest_path, artifact_root, manifest)."""
    rl_tmp_path.mkdir(parents=True, exist_ok=True)
    rl_producer_root = rl_tmp_path / "producer-root"
    rl_artifact_root = rl_tmp_path / "producer-artifacts"
    rl_review_root = rl_tmp_path / "review-root"
    for rl_root in (rl_producer_root, rl_artifact_root, rl_review_root):
        rl_root.mkdir(parents=True, exist_ok=True)

    rl_run_id = "run-1"
    rl_artifact_index: list[dict] = []
    rl_sections: dict[str, dict] = {}

    # Write the 16 section artifact files + build manifest section objects.
    for rl_order, rl_section in enumerate(rl_att.rl_STATUS_FIELDS, start=1):
        rl_kind = rl_SECTION_KIND[rl_section]
        rl_schema = rl_att.rl_SECTION_CONTRACTS[rl_section]["schema"]
        rl_values = rl_section_values(rl_section, rl_order)
        rl_payload: dict[str, Any] = {
            "semantic_gate_contract_version": rl_SEMANTIC_GATE_CONTRACT_VERSION,
            "section_name": rl_section,
            "artifact_kind": rl_kind,
            "schema_version": rl_schema,
            "run_id": rl_run_id,
            "owner": rl_PRODUCER,
            "reviewer": rl_REVIEWER,
            "status": "passed",
            "producer_action_ids": ["action-1"],
        }
        rl_payload.update(rl_values)
        rl_ref = f"evidence-{rl_order}.json"
        rl_bytes = json.dumps(rl_payload, sort_keys=True).encode("utf-8") + b"\n"
        (rl_artifact_root / rl_ref).write_bytes(rl_bytes)
        rl_entry = {
            "opaque_ref": rl_ref,
            "kind": rl_kind,
            "schema_version": rl_schema,
            "sha256": rl_sha256_hex(rl_bytes),
            "run_id": rl_run_id,
            "owner": rl_PRODUCER,
            "reviewer": rl_REVIEWER,
            "producer_action_ids": ["action-1"],
        }
        rl_artifact_index.append(rl_entry)
        # section object mirrors the semantic fields + points to the artifact
        rl_section_obj: dict[str, Any] = {
            "status": "passed",
            "owner": rl_PRODUCER,
            "reviewer": rl_REVIEWER,
            "evidence_ref": rl_ref,
            "evidence_sha256": rl_entry["sha256"],
            "evidence_kind": rl_kind,
            "evidence_schema_version": rl_schema,
        }
        rl_section_obj.update(rl_values)
        rl_sections[rl_section] = rl_section_obj

    # --- canonical snapshot sidecar (one-way digest, solution a) ---
    # Write the sidecar file first (child_ref only, no child_sha256), so its
    # digest is independent of the snapshot's byte content.
    rl_snap_ref = "evidence-4.json"  # canonical_snapshot_contract section
    rl_sidecar_ref = "snapshot-sidecar-1.json"
    rl_sidecar_payload: dict[str, Any] = {
        "child_ref": rl_snap_ref,
        "child_kind": "canonical_snapshot",
        "child_schema_version": "a0.canonical-snapshot.v1",
        "run_id": rl_run_id,
        "owner": rl_PRODUCER,
        "reviewer": rl_REVIEWER,
        "producer_action_id": "action-1",
    }
    rl_sidecar_bytes = json.dumps(rl_sidecar_payload, sort_keys=True).encode("utf-8") + b"\n"
    (rl_artifact_root / rl_sidecar_ref).write_bytes(rl_sidecar_bytes)
    rl_sidecar_sha = rl_sha256_hex(rl_sidecar_bytes)

    # Patch the canonical_snapshot_contract section payload with the real sidecar digest,
    # then re-write its file and recompute its own digest.
    rl_canon = rl_sections["canonical_snapshot_contract"]
    rl_canon["sidecar_ref"] = rl_sidecar_ref
    rl_canon["sidecar_sha256"] = rl_sidecar_sha
    # Rebuild the snapshot artifact payload from common fields + semantic fields
    # (NOT from the section object, which carries evidence_* metadata).
    rl_meta = {"status", "owner", "reviewer", "evidence_ref", "evidence_sha256", "evidence_kind", "evidence_schema_version"}
    rl_snap_semantic = {k: v for k, v in rl_canon.items() if k not in rl_meta}
    rl_snap_payload: dict[str, Any] = {
        "semantic_gate_contract_version": rl_SEMANTIC_GATE_CONTRACT_VERSION,
        "section_name": "canonical_snapshot_contract",
        "artifact_kind": "canonical_snapshot",
        "schema_version": "a0.canonical-snapshot.v1",
        "run_id": rl_run_id,
        "owner": rl_PRODUCER,
        "reviewer": rl_REVIEWER,
        "status": "passed",
        "producer_action_ids": ["action-1"],
    }
    rl_snap_payload.update(rl_snap_semantic)
    rl_snap_bytes = json.dumps(rl_snap_payload, sort_keys=True).encode("utf-8") + b"\n"
    (rl_artifact_root / rl_snap_ref).write_bytes(rl_snap_bytes)
    rl_snap_sha = rl_sha256_hex(rl_snap_bytes)

    # Update the canonical snapshot index entry (new sha) + section evidence_sha256.
    for rl_entry in rl_artifact_index:
        if rl_entry["opaque_ref"] == rl_snap_ref:
            rl_entry["sha256"] = rl_snap_sha
    rl_canon["evidence_sha256"] = rl_snap_sha

    # Add the sidecar index entry (child_sha256 lives in the index, not in file bytes).
    rl_artifact_index.append({
        "opaque_ref": rl_sidecar_ref,
        "kind": rl_att.rl_SIDECAR_KIND,
        "schema_version": rl_att.rl_SIDECAR_SCHEMA,
        "sha256": rl_sidecar_sha,
        "run_id": rl_run_id,
        "owner": rl_PRODUCER,
        "reviewer": rl_REVIEWER,
        "producer_action_ids": ["action-1"],
        "child_sha256": rl_snap_sha,
    })

    # --- action_output artifact (generic per-action output) ---
    rl_action_output_ref = "action-output-1.json"
    rl_action_output_payload = {"status": "passed"}
    rl_ao_bytes = json.dumps(rl_action_output_payload, sort_keys=True).encode("utf-8") + b"\n"
    (rl_artifact_root / rl_action_output_ref).write_bytes(rl_ao_bytes)
    rl_action_output_entry = {
        "opaque_ref": rl_action_output_ref,
        "kind": rl_att.rl_ACTION_OUTPUT_KIND,
        "schema_version": rl_att.rl_ACTION_OUTPUT_SCHEMA,
        "sha256": rl_sha256_hex(rl_ao_bytes),
        "run_id": rl_run_id,
        "owner": rl_PRODUCER,
        "reviewer": rl_REVIEWER,
        "producer_action_ids": ["action-1"],
    }
    rl_artifact_index.append(rl_action_output_entry)

    # Actions (33 phases) + events.
    rl_actions: list[dict] = []
    rl_guard_events: dict[str, dict] = {}
    rl_attestation_events: dict[str, dict] = {}
    rl_action_ids: list[str] = []

    for rl_seq, rl_phase in enumerate(rl_att.rl_REQUIRED_PHASES, start=1):
        rl_action_id = f"action-{rl_seq}"
        rl_action_ids.append(rl_action_id)
        rl_type = rl_action_type_for_phase(rl_phase)
        rl_kind = rl_primary_kind_for_phase(rl_phase)
        rl_attestation_kind = "actual_engine" if rl_type.startswith("alembic") else "launcher"
        rl_action: dict[str, Any] = {
            "action_id": rl_action_id,
            "action_type": rl_type,
            "phase_id": rl_phase,
            "sequence_no": rl_seq,
            "recipe_id": rl_RECIPE_ID,
            "action_recipe_version": rl_ACTION_RECIPE_VERSION,
            "run_id": rl_run_id,
            "role": "rl_a0_producer",
            "preceding_guard_event_id": f"guard-{rl_seq}",
            "attestation_event_id": f"attest-{rl_seq}",
            "attestation_kind": rl_attestation_kind,
            "identity_digest_version": rl_IDENTITY_VERSION,
            "system_identifier_digest": rl_distinct(100 + rl_seq),
            "endpoint_context_digest": rl_distinct(200 + rl_seq),
            "registry_tuple_digest": rl_distinct(300 + rl_seq),
            "marker_digest": rl_distinct(400 + rl_seq),
            "expiry": "2026-07-22T00:00:00Z",
            "configured_identity_redacted": {"database": "<redacted>", "role": "rl_a0_reader"},
            "redacted_argv_template": ["python", "-m", "rl_action", "<opaque>"],
            "exit_code": 0,
            "stdout_sha256": rl_distinct(500 + rl_seq),
            "stderr_sha256": rl_distinct(600 + rl_seq),
            "started_at": "2026-07-21T10:00:00Z",
            "finished_at": "2026-07-21T10:01:00Z",
            "plan_source_sha256": "5" * 64,
            "spec_source_sha256": "6" * 64,
            "tool_source_sha256": "7" * 64,
            "test_source_sha256": "8" * 64,
            "executable_version": "python 3.14.0",
            "artifact_refs_and_sha256": [],
            "required_primary_output_kind": rl_kind,
            "owner": rl_PRODUCER,
            "reviewer": rl_REVIEWER,
        }
        rl_action["planned_binding_digest"] = rl_distinct(700 + rl_seq)
        rl_action["completed_binding_digest"] = rl_distinct(800 + rl_seq)

        # bind the section artifacts as inputs; primary output for primary phases
        for rl_order2, rl_section in enumerate(rl_att.rl_STATUS_FIELDS, start=1):
            rl_section_kind = rl_SECTION_KIND[rl_section]
            rl_ref = f"evidence-{rl_order2}.json"
            rl_entry = next(e for e in rl_artifact_index if e["opaque_ref"] == rl_ref)
            rl_direction = "output" if rl_kind == rl_section_kind else "input"
            rl_action["artifact_refs_and_sha256"].append({
                "opaque_ref": rl_ref,
                "sha256": rl_entry["sha256"],
                "kind": rl_section_kind,
                "schema_version": rl_entry["schema_version"],
                "owner": rl_PRODUCER,
                "reviewer": rl_REVIEWER,
                "direction": rl_direction,
                "binding_role": f"role-{rl_section}",
            })
        # bind the generic action_output artifact as the primary output when required
        if rl_kind == rl_att.rl_ACTION_OUTPUT_KIND:
            rl_action["artifact_refs_and_sha256"].append({
                "opaque_ref": rl_action_output_ref,
                "sha256": rl_action_output_entry["sha256"],
                "kind": rl_att.rl_ACTION_OUTPUT_KIND,
                "schema_version": rl_att.rl_ACTION_OUTPUT_SCHEMA,
                "owner": rl_PRODUCER,
                "reviewer": rl_REVIEWER,
                "direction": "output",
                "binding_role": "role-action-output",
            })
        # compute action binding digest
        rl_action["action_binding_digest"] = rl_att.rl_compute_action_binding_digest(rl_action)

        # events (unique guard + attestation)
        rl_common_event: dict[str, Any] = {
            "event_id": "",
            "kind": "",
            "action_id": rl_action_id,
            "recipe_id": rl_RECIPE_ID,
            "phase_id": rl_phase,
            "sequence_no": rl_seq,
            "planned_binding_digest": rl_action["planned_binding_digest"],
            "completed_binding_digest": rl_action["completed_binding_digest"],
            "started_at": "2026-07-21T10:00:00Z",
            "completed_at": "2026-07-21T10:01:00Z",
            "output_tuples": [],
        }
        rl_guard = dict(rl_common_event)
        rl_guard["event_id"] = f"guard-{rl_seq}"
        rl_guard["kind"] = "guard"
        rl_attest = dict(rl_common_event)
        rl_attest["event_id"] = f"attest-{rl_seq}"
        rl_attest["kind"] = "attestation"
        rl_guard_events[f"guard-{rl_seq}"] = rl_guard
        rl_attestation_events[f"attest-{rl_seq}"] = rl_attest
        rl_actions.append(rl_action)

    rl_manifest: dict[str, Any] = {
        "a0_evidence_manifest_version": "a0.gate.v2",
        "semantic_gate_contract_version": rl_SEMANTIC_GATE_CONTRACT_VERSION,
        "action_recipe_version": rl_ACTION_RECIPE_VERSION,
        "recipe_id": rl_RECIPE_ID,
        "run_id": rl_run_id,
        "producer_root_ref": "rl-producer-root",
        "artifact_root_ref": "rl-artifact-root",
        "review_root_ref": "rl-review-root",
        "producer_root_path": str(rl_producer_root),
        "artifact_root_path": str(rl_artifact_root),
        "project_root_digest": "c" * 64,
        "plan_source_sha256": "5" * 64,
        "spec_source_sha256": "6" * 64,
        "review_tool_source_sha256": "7" * 64,
        "gate_tool_source_sha256": "8" * 64,
        "ci_identity": {"provider": "unit", "workflow": "rl-fixture"},
        "identity_digest_version": rl_IDENTITY_VERSION,
        "producer_principal": rl_PRODUCER,
        "reviewer_principal": rl_REVIEWER,
        "trusted_assertion_issuer_id": rl_ISSUER,
        "artifact_index": rl_artifact_index,
        "database_actions": rl_actions,
        "guard_events": rl_guard_events,
        "attestation_events": rl_attestation_events,
        "unresolved_queue": {"blocking_count": 0, "items": []},
        "review_attestation_ref": "review-attestation-run-1.json",
        "producer_evidence_completed_at": "2026-07-21T11:00:00Z",
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
    for rl_section in rl_att.rl_STATUS_FIELDS:
        rl_manifest[rl_section] = rl_sections[rl_section]

    rl_manifest["producer_root_identity_digest"] = rl_att.rl_compute_root_identity_digest(rl_producer_root)
    rl_manifest["artifact_root_identity_digest"] = rl_att.rl_compute_root_identity_digest(rl_artifact_root)
    rl_manifest["review_root_identity_digest"] = rl_att.rl_compute_root_identity_digest(rl_review_root)

    if rl_action_overrides:
        # apply to the first action (the tests mutate the primary action)
        rl_manifest["database_actions"][0].update(rl_action_overrides)
        # recompute binding digest after mutation
        rl_manifest["database_actions"][0]["action_binding_digest"] = rl_att.rl_compute_action_binding_digest(rl_manifest["database_actions"][0])
    if rl_top_overrides:
        rl_manifest.update(rl_top_overrides)

    rl_manifest_path = rl_tmp_path / "manifest.json"
    rl_manifest_path.write_text(json.dumps(rl_manifest, sort_keys=True), encoding="utf-8")
    return rl_manifest_path, rl_artifact_root, rl_manifest
