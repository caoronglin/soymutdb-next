from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol


rl_MANIFEST_VERSION = "a0.gate.v2"
rl_ATTESTATION_VERSION = "a0.reviewer-attestation.v2"
rl_GATE_RESULT_VERSION = "a0.gate-result.v2"
rl_SEMANTIC_GATE_CONTRACT_VERSION = "a0.semantic-gate.v1"
rl_ACTION_RECIPE_VERSION = "a0.action-recipe.v1"
rl_RECIPE_ID = "a0.task8.semantic-recipe.v1"
rl_TRUSTED_ASSERTION_VERSION = "a0.trusted-assertion.v2"
rl_TRUSTED_ASSERTION_AUDIENCE = "a0-task8-semantic-gate"
rl_TRUSTED_ASSERTION_REQUEST_VERSION = "a0.trusted-assertion-request.v2"
rl_TRUSTED_BOUNDARY_VERSION = "a0.trusted-boundary.v1"
rl_SHA256_LENGTH = 64
rl_OPAQUE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
rl_RAW_LIST_RE = re.compile(r"^\s*\d+;\s*\d+\s+\S+", re.MULTILINE)
rl_SENSITIVE_REF_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "archive",
    "full-list",
    "list_path",
    "archive_path",
)
rl_SELF_DIGEST_KEYS = frozenset(
    {"artifact_sha256", "file_sha256", "self_digest", "self_sha256"}
)
rl_SCOPE_DECLARATION_FIELDS = (
    "digest_scope",
    "manifest_digest_scope",
    "bundle_digest_scope",
    "canonical_digest_scope",
)
rl_DERIVED_MANIFEST_FIELDS = frozenset(
    {
        "manifest_digest",
        "bundle_digest",
        "reviewer_attestation_sha256",
        "reviewer_attestation",
        "review_attestation_sha256",
        "review_attestation_digest",
        "recomputed_bundle_sha256",
        "gate_result",
        "gate_result_digest",
        "gate_result_ref",
        "gate_result_sha256",
        "gate_status",
        "gate_decision",
        "a0_gate_status",
        "a0_gate_result_version",
        "a0_observational_evidence_complete",
        "a1_allowed",
        "production_migration_allowed",
        "production_write_cutover_allowed",
        "publication_implementation_allowed",
        "findings",
        "status",
    }
)
rl_ROOT_IDENTITY_FIELDS = (
    "producer_root_identity_digest",
    "artifact_root_identity_digest",
    "review_root_identity_digest",
)
rl_STATUS_FIELDS = (
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
rl_C_PHASES = tuple(f"C{rl_index:02d}" for rl_index in range(1, 8))
rl_M_PHASES = tuple(f"M{rl_index:02d}" for rl_index in range(1, 12))
rl_R_PHASES = tuple(f"R{rl_index:02d}" for rl_index in range(1, 16))
rl_REQUIRED_PHASES = rl_C_PHASES + rl_M_PHASES + rl_R_PHASES
rl_PHASE_ACTION_TYPES = {
    "C01": {"context_validation"},
    "C02": {"profile_validation"},
    "C03": {"catalog_validation"},
    "C04": {"canonical_contract_validation"},
    "C05": {"semantic_contract_validation"},
    "C06": {"synthetic_source_validation"},
    "C07": {"legacy_classify"},
    "M01": {"migration_snapshot"},
    "M02": {"migration_forward", "alembic_upgrade"},
    "M03": {"migration_snapshot"},
    "M04": {"migration_forward", "alembic_upgrade"},
    "M05": {"migration_snapshot"},
    "M06": {"migration_forward", "alembic_upgrade"},
    "M07": {"migration_downgrade", "alembic_downgrade"},
    "M08": {"migration_snapshot"},
    "M09": {"migration_reupgrade", "alembic_upgrade"},
    "M10": {"migration_snapshot"},
    "M11": {"migration_finalize"},
    "R01": {"source_guard"},
    "R02": {"source_snapshot"},
    "R03": {"dump"},
    "R04": {"dump_list"},
    "R05": {"source_stability"},
    "R06": {"empty_before_rebuild"},
    "R07": {"direct_restore"},
    "R08": {"restored_snapshot"},
    "R09": {"semantic_compare"},
    "R10": {"retention_cleanup"},
    "R11": {"source_stability_post"},
    "R12": {"restore_semantic_compare"},
    "R13": {"archive_summary"},
    "R14": {"list_summary"},
    "R15": {"legacy_release_classification"},
}
rl_PHASE_PRIMARY_SECTIONS = {
    "C01": "context_contract",
    "C02": "profile_contract",
    "C03": "catalog_baseline",
    "C04": "canonical_snapshot_contract",
    "C05": "semantic_projection_contract",
    "C06": "synthetic_source_policy",
    "C07": "legacy_release_classification",
    "M01": "migration_trajectory",
    "R01": "source_stability",
    "R02": "action_output",
    "R03": "restricted_archive_policy",
    "R04": "list_summary",
    "R06": "empty_before_rebuild",
    "R07": "empty_before_restore",
    "R09": "restore_semantic_result",
}
rl_COMMON_PAYLOAD_FIELDS = frozenset(
    {
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
)
rl_CATALOG_CATEGORIES = (
    "schemas",
    "relations",
    "columns",
    "constraints",
    "indexes",
    "sequences",
    "enums",
    "extensions",
    "functions",
    "triggers",
    "policies",
    "privileges_acl",
    "owners",
    "tablespaces",
    "publications",
    "subscriptions",
    "fdw",
)
rl_SECTION_CONTRACTS: dict[str, dict[str, Any]] = {
    "context_contract": {
        "kind": "context_contract",
        "schema": "a0.context-contract.v1",
        "required": (
            "project_root_digest",
            "runtime_facts_ref",
            "runtime_facts_digest",
            "cwd_digest",
            "absolute_paths",
            "fresh_process",
            "in_process_settings_switch",
        ),
    },
    "profile_contract": {
        "kind": "profile_contract",
        "schema": "a0.profile-contract.v1",
        "required": (
            "registry_digest",
            "profile_only",
            "sanitized_env",
            "shell_false",
            "interactive_password",
            "mode_0700",
            "mode_0600",
        ),
    },
    "catalog_baseline": {
        "kind": "catalog_baseline",
        "schema": "a0.catalog-baseline.v1",
        "required": (
            "same_version_init_ref",
            "same_version_init_digest",
            "reference_digest",
            "server_digest",
            "category_digests",
            "unknown_count",
            "read_failures",
            "match",
        ),
    },
    "canonical_snapshot_contract": {
        "kind": "canonical_snapshot",
        "schema": "a0.canonical-snapshot.v1",
        "required": (
            "canonical_version",
            "structural_policy_digest",
            "count_independent",
            "raw_rows",
            "self_digest_forbidden",
            "parent_sidecar_required",
            "sidecar_ref",
            "sidecar_sha256",
        ),
    },
    "semantic_projection_contract": {
        "kind": "semantic_projection",
        "schema": "a0.semantic-projection.v1",
        "required": (
            "semantic_version",
            "policy_digest",
            "stable_key_digest",
            "exclusion_digest",
            "positive_table_count",
            "content_digests_only",
            "raw_rows",
            "sequence_state",
            "unknown_fields",
        ),
    },
    "migration_trajectory": {
        "kind": "migration_trajectory",
        "schema": "a0.migration-trajectory.v1",
        "required": (
            "initial_revision",
            "downgrade_revision",
            "final_revision",
            "edge_count",
            "edges",
            "nonempty_edges",
            "strict_ancestor",
            "downgrade_rehearsal",
            "seed_semantic",
            "revision_snapshot_refs",
            "revision_snapshot_digests",
        ),
    },
    "empty_before_rebuild": {
        "kind": "empty_proof_rebuild",
        "schema": "a0.empty-proof-rebuild.v1",
        "required": (
            "identity_digest",
            "empty",
            "user_object_count",
            "snapshot_ref",
            "snapshot_sha256",
            "catalog_baseline_match",
            "guard_event_ids",
            "action_ids",
        ),
    },
    "empty_before_restore": {
        "kind": "empty_proof_restore",
        "schema": "a0.empty-proof-restore.v1",
        "required": (
            "identity_digest",
            "empty",
            "user_object_count",
            "snapshot_ref",
            "snapshot_sha256",
            "catalog_baseline_match",
            "guard_event_ids",
            "action_ids",
        ),
    },
    "source_stability": {
        "kind": "source_stability",
        "schema": "a0.source-stability.v1",
        "required": (
            "pre_binding_digest",
            "post_binding_digest",
            "structural_match",
            "semantic_match",
            "sequence_match",
            "drift_detected",
        ),
    },
    "synthetic_source_policy": {
        "kind": "synthetic_source_policy",
        "schema": "a0.synthetic-source-policy.v1",
        "required": (
            "classification",
            "approval_digest",
            "policy_digest",
            "seed_digest",
            "raw_sensitive",
        ),
    },
    "restricted_archive_policy": {
        "kind": "restricted_archive",
        "schema": "a0.restricted-archive.v1",
        "required": (
            "root_identity_digest",
            "acl_claim_digest",
            "mode_0700",
            "mode_0600",
            "opaque_only",
            "raw_ordinary",
            "retention_outcome",
            "cleanup_status",
        ),
    },
    "archive_summary": {
        "kind": "archive_summary",
        "schema": "a0.archive-summary.v1",
        "required": (
            "archive_ref",
            "archive_sha256",
            "item_count",
            "opaque_only",
            "raw_archive",
            "unknown_count",
            "failures",
        ),
    },
    "list_summary": {
        "kind": "list_summary",
        "schema": "a0.list-summary.v1",
        "required": (
            "list_ref",
            "list_sha256",
            "item_count",
            "opaque_only",
            "raw_full_list",
            "unknown_count",
            "failures",
        ),
    },
    "restore_semantic_result": {
        "kind": "restore_semantic_result",
        "schema": "a0.restore-semantic.v1",
        "required": (
            "structural_match",
            "content_match",
            "count_match",
            "sequence_match",
            "extensions_match",
            "enums_match",
            "revision_match",
            "mismatches",
        ),
    },
    "legacy_release_classification": {
        "kind": "legacy_release_classification",
        "schema": "a0.legacy-classification.v1",
        "required": (
            "classifier",
            "input_digest",
            "dataset_count",
            "release_count",
            "records_ref",
            "records_sha256",
            "unresolved_count",
            "items",
        ),
    },
}
rl_SIDECAR_KIND = "canonical_snapshot_sidecar"
rl_SIDECAR_SCHEMA = "a0.snapshot-sidecar.v1"
rl_ACTION_OUTPUT_KIND = "action_output"
rl_ACTION_OUTPUT_SCHEMA = "a0.action-output.v1"
rl_REQUIRED_MANIFEST_FIELDS = (
    "project_root_digest",
    "plan_source_sha256",
    "spec_source_sha256",
    "review_tool_source_sha256",
    "gate_tool_source_sha256",
    "ci_identity",
    "context_contract",
    "profile_contract",
    "identity_digest_version",
    "producer_principal",
    "reviewer_principal",
    "trusted_assertion_issuer_id",
    "producer_root_ref",
    "artifact_root_ref",
    "review_root_ref",
    "producer_root_path",
    "artifact_root_path",
    "producer_root_identity_digest",
    "artifact_root_identity_digest",
    "review_root_identity_digest",
    "artifact_index",
    "database_actions",
    "guard_events",
    "attestation_events",
    "recipe_id",
    "semantic_gate_contract_version",
    "action_recipe_version",
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
    "unresolved_queue",
    "review_attestation_ref",
    "trusted_boundary",
    "producer_evidence_completed_at",
)


class rl_ManifestScopeError(ValueError):
    pass


class rl_TrustedAssertionVerifier(Protocol):
    """External provisioner contract; local JSON is never authoritative."""

    def __call__(self, rl_request: Mapping[str, Any]) -> Mapping[str, Any] | None:
        ...


def rl_canonical_json(rl_value: Any) -> bytes:
    return json.dumps(
        rl_value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def rl_sha256(rl_value: Any) -> str:
    return hashlib.sha256(rl_canonical_json(rl_value)).hexdigest()


def rl_is_sha256(rl_value: Any) -> bool:
    return (
        isinstance(rl_value, str)
        and len(rl_value) == rl_SHA256_LENGTH
        and all(rl_character in "0123456789abcdef" for rl_character in rl_value)
    )


def rl_is_opaque_ref(rl_ref: Any) -> bool:
    if not isinstance(rl_ref, str) or not rl_OPAQUE_REF_RE.fullmatch(rl_ref):
        return False
    if rl_ref in {".", ".."}:
        return False
    return not any(
        rl_marker in rl_ref.lower() for rl_marker in rl_SENSITIVE_REF_MARKERS
    )


def rl_parse_timestamp(rl_value: Any) -> datetime | None:
    if not isinstance(rl_value, str) or not rl_value:
        return None
    try:
        rl_timestamp = datetime.fromisoformat(rl_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if rl_timestamp.tzinfo is None:
        return None
    return rl_timestamp.astimezone(timezone.utc)


def rl_normalize_manifest(rl_manifest: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(rl_manifest, Mapping):
        raise ValueError("manifest must be an object")
    rl_normalized = deepcopy(dict(rl_manifest))
    rl_aliases = {
        "runtime_context": "context_contract",
        "profile_policy": "profile_contract",
        "canonical_snapshot_policy": "canonical_snapshot_contract",
        "semantic_projection_policy": "semantic_projection_contract",
        "archive_policy": "restricted_archive_policy",
        "restore_empty_proof": "empty_before_restore",
        "legacy_evidence": "legacy_release_classification",
    }
    for rl_legacy_field, rl_canonical_field in rl_aliases.items():
        if rl_legacy_field not in rl_normalized:
            continue
        if (
            rl_canonical_field in rl_normalized
            and rl_normalized[rl_canonical_field] != rl_normalized[rl_legacy_field]
        ):
            raise ValueError(f"conflicting manifest alias: {rl_legacy_field}")
        rl_normalized.setdefault(
            rl_canonical_field, deepcopy(rl_normalized[rl_legacy_field])
        )
        del rl_normalized[rl_legacy_field]
    rl_legacy_ref = rl_normalized.get("reviewer_attestation_ref")
    rl_canonical_ref = rl_normalized.get("review_attestation_ref")
    if rl_legacy_ref is not None:
        if not rl_is_opaque_ref(rl_legacy_ref):
            raise ValueError("legacy attestation ref is not opaque")
        if rl_canonical_ref is not None and rl_canonical_ref != rl_legacy_ref:
            raise ValueError("conflicting attestation refs")
        rl_normalized["review_attestation_ref"] = rl_legacy_ref
        del rl_normalized["reviewer_attestation_ref"]
    if "actions" in rl_normalized:
        if (
            "database_actions" in rl_normalized
            and rl_normalized["actions"] != rl_normalized["database_actions"]
        ):
            raise ValueError("conflicting action indexes")
        rl_normalized.setdefault(
            "database_actions", deepcopy(rl_normalized["actions"])
        )
        del rl_normalized["actions"]
    return rl_normalized


def rl_normalize_review_attestation_ref(rl_manifest: Mapping[str, Any]) -> str:
    rl_ref = rl_normalize_manifest(rl_manifest).get("review_attestation_ref")
    if not rl_is_opaque_ref(rl_ref):
        raise ValueError("review_attestation_ref must be opaque")
    return str(rl_ref)


def rl_manifest_scope(rl_manifest: Mapping[str, Any]) -> dict[str, Any]:
    if any(rl_field in rl_manifest for rl_field in rl_SCOPE_DECLARATION_FIELDS):
        raise rl_ManifestScopeError("producer-defined digest scope is forbidden")
    rl_normalized = rl_normalize_manifest(rl_manifest)
    return {
        rl_key: deepcopy(rl_value)
        for rl_key, rl_value in rl_normalized.items()
        if rl_key not in rl_DERIVED_MANIFEST_FIELDS
    }


def rl_compute_manifest_digest(rl_manifest: Mapping[str, Any]) -> str:
    return rl_sha256(rl_manifest_scope(rl_manifest))


def rl_safe_canonical_directory(rl_root: Path) -> Path | None:
    if not isinstance(rl_root, Path):
        return None
    try:
        if rl_root.is_symlink():
            return None
        for rl_parent in (rl_root, *rl_root.parents):
            if rl_parent.is_symlink():
                return None
        rl_resolved_root = rl_root.resolve(strict=True)
        rl_stat = os.stat(rl_resolved_root, follow_symlinks=False)
        if not stat.S_ISDIR(rl_stat.st_mode):
            return None
        return rl_resolved_root
    except (OSError, RuntimeError, ValueError):
        return None


def rl_safe_regular_file(rl_root: Path, rl_ref: str) -> tuple[Path, bytes] | None:
    rl_resolved_root = rl_safe_canonical_directory(rl_root)
    if rl_resolved_root is None or not rl_is_opaque_ref(rl_ref):
        return None
    rl_candidate = rl_resolved_root / rl_ref
    try:
        if rl_candidate.is_symlink():
            return None
        rl_resolved_candidate = rl_candidate.resolve(strict=True)
        if rl_resolved_candidate.parent != rl_resolved_root:
            return None
        rl_stat = os.stat(rl_candidate, follow_symlinks=False)
        if not stat.S_ISREG(rl_stat.st_mode) or rl_stat.st_nlink != 1:
            return None
        rl_fd = os.open(rl_candidate, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(rl_fd, "rb") as rl_stream:
            return rl_resolved_candidate, rl_stream.read()
    except (OSError, RuntimeError, ValueError):
        return None


def rl_prepare_safe_directory(rl_root: Path) -> Path | None:
    if rl_root.exists() or rl_root.is_symlink():
        return rl_safe_canonical_directory(rl_root)
    rl_parent = rl_safe_canonical_directory(rl_root.parent)
    if rl_parent is None:
        return None
    try:
        rl_root.mkdir()
    except OSError:
        return None
    return rl_safe_canonical_directory(rl_root)


def rl_compute_root_identity_digest(rl_root: Path) -> str | None:
    rl_resolved_root = rl_safe_canonical_directory(rl_root)
    if rl_resolved_root is None:
        return None
    try:
        rl_stat = os.stat(rl_resolved_root, follow_symlinks=False)
    except OSError:
        return None
    return rl_sha256(
        {
            "canonical_path": str(rl_resolved_root),
            "st_dev": rl_stat.st_dev,
            "st_ino": rl_stat.st_ino,
        }
    )


def rl_roots_are_disjoint(rl_roots: Mapping[str, Path]) -> bool:
    rl_canonical_roots: dict[str, Path] = {}
    for rl_name, rl_root in rl_roots.items():
        rl_canonical = rl_safe_canonical_directory(rl_root)
        if rl_canonical is None:
            return False
        rl_canonical_roots[rl_name] = rl_canonical
    rl_names = list(rl_canonical_roots)
    for rl_index, rl_left_name in enumerate(rl_names):
        for rl_right_name in rl_names[rl_index + 1 :]:
            rl_left = rl_canonical_roots[rl_left_name]
            rl_right = rl_canonical_roots[rl_right_name]
            if rl_left == rl_right:
                return False
            try:
                rl_left.relative_to(rl_right)
                return False
            except ValueError:
                pass
            try:
                rl_right.relative_to(rl_left)
                return False
            except ValueError:
                pass
    return True


def rl_root_identity_bindings(
    rl_manifest: Mapping[str, Any],
    rl_producer_root: Path | None,
    rl_artifact_root: Path | None,
    rl_review_root: Path,
    rl_findings: list[str],
) -> dict[str, str] | None:
    if rl_producer_root is None or rl_artifact_root is None:
        rl_findings.append("root-binding")
        return None
    rl_roots = {
        "producer": rl_producer_root,
        "artifact": rl_artifact_root,
        "review": rl_review_root,
    }
    if not rl_roots_are_disjoint(rl_roots):
        rl_findings.append("root-overlap")
        rl_findings.append("root-overlap-or-unsafe")
        return None
    rl_digests: dict[str, str] = {}
    for rl_name, rl_root in rl_roots.items():
        rl_digest = rl_compute_root_identity_digest(rl_root)
        if rl_digest is None:
            rl_findings.append("root-binding")
            return None
        rl_digests[rl_name] = rl_digest
    for rl_name, rl_field in zip(
        ("producer", "artifact", "review"), rl_ROOT_IDENTITY_FIELDS
    ):
        if rl_manifest.get(rl_field) != rl_digests[rl_name]:
            rl_findings.append("root-identity-mismatch")
    return rl_digests


def rl_boundary_projection(rl_boundary: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(rl_boundary, Mapping):
        return {}
    return {
        rl_field: rl_boundary.get(rl_field)
        for rl_field in (
            "trusted_boundary_version",
            "boundary_ref",
            "control_metadata_ref",
            "producer_root_ref",
            "review_root_ref",
            "reviewer_controlled",
            "producer_writable",
            "access_control_verified",
            "owner",
        )
    }


def rl_is_valid_trusted_boundary(rl_boundary: Any) -> bool:
    return (
        isinstance(rl_boundary, Mapping)
        and rl_boundary.get("trusted_boundary_version") == rl_TRUSTED_BOUNDARY_VERSION
        and rl_boundary.get("reviewer_controlled") is True
        and rl_boundary.get("producer_writable") is False
        and rl_boundary.get("access_control_verified") is True
        and isinstance(rl_boundary.get("owner"), str)
        and bool(rl_boundary.get("owner"))
        and all(
            rl_is_opaque_ref(rl_boundary.get(rl_field))
            for rl_field in (
                "boundary_ref",
                "control_metadata_ref",
                "producer_root_ref",
                "review_root_ref",
            )
        )
        and rl_boundary.get("producer_root_ref") != rl_boundary.get("review_root_ref")
    )


def rl_load_json(rl_json_path: Path) -> dict[str, Any]:
    rl_payload = json.loads(rl_json_path.read_text(encoding="utf-8"))
    if not isinstance(rl_payload, dict):
        raise ValueError("JSON root must be an object")
    return rl_payload


def rl_load_trusted_boundary(rl_review_root: Path) -> dict[str, Any] | None:
    rl_file = rl_safe_regular_file(rl_review_root, "rl_trusted_boundary.json")
    if rl_file is None:
        return None
    try:
        rl_boundary = json.loads(rl_file[1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return dict(rl_boundary) if isinstance(rl_boundary, Mapping) else None


def rl_compute_trusted_assertion_payload_digest(
    rl_assertion: Mapping[str, Any],
) -> str:
    return rl_sha256(
        {
            rl_key: rl_value
            for rl_key, rl_value in rl_assertion.items()
            if rl_key != "payload_digest"
        }
    )


def rl_compute_action_binding_digest(rl_action: Mapping[str, Any]) -> str:
    return rl_sha256(
        {
            rl_key: rl_value
            for rl_key, rl_value in rl_action.items()
            if rl_key not in {"action_binding_digest", "completed_binding_digest"}
        }
    )


def rl_compute_bundle_digest(
    rl_manifest: Mapping[str, Any],
    rl_artifact_root: Path | None = None,
) -> str:
    rl_scope = rl_manifest_scope(rl_manifest)
    rl_index = rl_scope.get("artifact_index")
    if not isinstance(rl_index, list):
        raise ValueError("artifact_index must be a list")
    rl_tuples: list[dict[str, Any]] = []
    for rl_entry in rl_index:
        if not isinstance(rl_entry, Mapping):
            raise ValueError("artifact index entry must be an object")
        rl_ref = rl_entry.get("opaque_ref")
        if not rl_is_opaque_ref(rl_ref) or not rl_is_sha256(rl_entry.get("sha256")):
            raise ValueError("invalid artifact index digest")
        if rl_artifact_root is not None:
            rl_file = rl_safe_regular_file(rl_artifact_root, str(rl_ref))
            if rl_file is None:
                raise ValueError("artifact missing or unsafe")
            if hashlib.sha256(rl_file[1]).hexdigest() != rl_entry.get("sha256"):
                raise ValueError("artifact digest mismatch")
        rl_tuples.append(
            {
                rl_key: deepcopy(rl_entry.get(rl_key))
                for rl_key in (
                    "opaque_ref",
                    "sha256",
                    "kind",
                    "schema_version",
                    "run_id",
                    "owner",
                    "reviewer",
                    "producer_action_ids",
                )
            }
        )
    rl_tuples.sort(key=lambda rl_entry: str(rl_entry.get("opaque_ref")))
    return rl_sha256(
        {"normalized_manifest": rl_scope, "artifact_index_tuples": rl_tuples}
    )


def rl_compute_review_source_digest(
    rl_manifest_sha256: str,
    rl_bundle_sha256: str,
    rl_reviewer_identity: str,
    rl_producer_evidence_completed_at: str,
    rl_trusted_boundary: Mapping[str, Any] | None = None,
    rl_root_identity_digests: Mapping[str, str] | None = None,
    rl_assertion_payload_digest: str | None = None,
    rl_review_attestation_ref: str = "",
    rl_review_started_at: str = "",
    rl_review_finished_at: str = "",
    rl_decision: str = "PASS",
    rl_blocking_findings: list[str] | None = None,
) -> str:
    return rl_sha256(
        {
            "semantic_gate_contract_version": rl_SEMANTIC_GATE_CONTRACT_VERSION,
            "manifest_sha256": rl_manifest_sha256,
            "bundle_sha256": rl_bundle_sha256,
            "review_attestation_ref": rl_review_attestation_ref,
            "reviewer_identity": rl_reviewer_identity,
            "producer_evidence_completed_at": rl_producer_evidence_completed_at,
            "review_started_at": rl_review_started_at,
            "review_finished_at": rl_review_finished_at,
            "root_identity_digests": dict(rl_root_identity_digests or {}),
            "trusted_boundary": dict(rl_trusted_boundary or {}),
            "assertion_payload_digest": rl_assertion_payload_digest,
            "decision": rl_decision,
            "blocking_findings": list(rl_blocking_findings or []),
        }
    )


def rl_build_trusted_assertion_request(
    rl_manifest: Mapping[str, Any],
    rl_run_id: str,
    rl_root_identity_digests: Mapping[str, str],
    rl_manifest_sha256: str,
    rl_bundle_sha256: str,
) -> dict[str, Any]:
    rl_actions = rl_manifest.get("database_actions")
    rl_source_actions: list[dict[str, Any]] = []
    if isinstance(rl_actions, list):
        for rl_action in rl_actions:
            if isinstance(rl_action, Mapping):
                rl_source_actions.append(
                    {
                        "action_id": rl_action.get("action_id"),
                        "tool_source_sha256": rl_action.get("tool_source_sha256"),
                        "test_source_sha256": rl_action.get("test_source_sha256"),
                        "executable_version": rl_action.get("executable_version"),
                    }
                )
    return {
        "version": rl_TRUSTED_ASSERTION_REQUEST_VERSION,
        "audience": rl_TRUSTED_ASSERTION_AUDIENCE,
        "semantic_gate_contract_version": rl_SEMANTIC_GATE_CONTRACT_VERSION,
        "action_recipe_version": rl_ACTION_RECIPE_VERSION,
        "run_id": rl_run_id,
        "manifest_sha256": rl_manifest_sha256,
        "bundle_sha256": rl_bundle_sha256,
        "review_attestation_ref": rl_manifest.get("review_attestation_ref"),
        "producer_principal": rl_manifest.get("producer_principal"),
        "reviewer_principal": rl_manifest.get("reviewer_principal"),
        "expected_issuer_id": rl_manifest.get("trusted_assertion_issuer_id"),
        "root_identity_digests": dict(rl_root_identity_digests),
        "root_claims": deepcopy(rl_manifest.get("trusted_boundary")),
        "source_claims": {
            "project_root_digest": rl_manifest.get("project_root_digest"),
            "plan_source_sha256": rl_manifest.get("plan_source_sha256"),
            "spec_source_sha256": rl_manifest.get("spec_source_sha256"),
            "review_tool_source_sha256": rl_manifest.get(
                "review_tool_source_sha256"
            ),
            "gate_tool_source_sha256": rl_manifest.get("gate_tool_source_sha256"),
            "actions": rl_source_actions,
        },
        "ci_identity": deepcopy(rl_manifest.get("ci_identity")),
    }


def rl_verify_trusted_assertion(
    rl_trusted_verifier: rl_TrustedAssertionVerifier | Any | None,
    rl_request: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    if rl_trusted_verifier is None:
        return None, ["trusted-boundary-unverified"]
    try:
        rl_verifier_object = rl_trusted_verifier
        rl_result = (
            getattr(rl_verifier_object, "verify")(rl_request)
            if hasattr(rl_trusted_verifier, "verify")
            else rl_trusted_verifier(rl_request)
        )
    except Exception:
        return None, ["trusted-boundary-unverified"]
    if not isinstance(rl_result, Mapping):
        return None, ["trusted-assertion-invalid"]
    rl_assertion = dict(rl_result)
    rl_findings: list[str] = []
    rl_required = (
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
    if any(rl_assertion.get(rl_key) in (None, "") for rl_key in rl_required):
        rl_findings.append("trusted-assertion-invalid")
    if rl_assertion.get("version") != rl_TRUSTED_ASSERTION_VERSION:
        rl_findings.append("trusted-assertion-version")
    if rl_assertion.get("semantic_gate_contract_version") != rl_request.get(
        "semantic_gate_contract_version"
    ):
        rl_findings.append("trusted-assertion-semantic-version")
    if rl_assertion.get("action_recipe_version") != rl_request.get(
        "action_recipe_version"
    ):
        rl_findings.append("trusted-assertion-recipe-version")
    if rl_assertion.get("audience") != rl_request.get("audience"):
        rl_findings.append("trusted-assertion-audience")
    for rl_key in (
        "run_id",
        "manifest_sha256",
        "bundle_sha256",
        "review_attestation_ref",
        "producer_principal",
        "reviewer_principal",
        "root_identity_digests",
        "source_claims",
        "ci_identity",
        "root_claims",
    ):
        if rl_assertion.get(rl_key) != rl_request.get(rl_key):
            rl_findings.append(f"trusted-assertion-{rl_key}-mismatch")
    if rl_assertion.get("issuer_id") != rl_request.get("expected_issuer_id"):
        rl_findings.append("trusted-assertion-issuer-mismatch")
    if rl_assertion.get("subject") != rl_request.get("reviewer_principal"):
        rl_findings.append("trusted-assertion-subject")
    if rl_assertion.get("producer_writable") is not False:
        rl_findings.append("trusted-assertion-producer-writable")
    if rl_assertion.get("reviewer_controlled") is not True:
        rl_findings.append("trusted-assertion-reviewer-control")
    if rl_assertion.get("access_control_verified") is not True:
        rl_findings.append("trusted-assertion-acl")
    if rl_assertion.get("producer_principal") == rl_assertion.get(
        "reviewer_principal"
    ):
        rl_findings.append("trusted-assertion-principal")
    if not rl_is_opaque_ref(rl_assertion.get("assertion_id")) or not rl_is_opaque_ref(
        rl_assertion.get("assertion_ref")
    ):
        rl_findings.append("trusted-assertion-ref")
    if not isinstance(rl_assertion.get("root_claims"), Mapping):
        rl_findings.append("trusted-assertion-root-claims")
    elif rl_assertion.get("root_claims") != rl_request.get("root_claims"):
        rl_findings.append("trusted-assertion-root-claims-mismatch")
    if not isinstance(rl_assertion.get("source_claims"), Mapping):
        rl_findings.append("trusted-assertion-source-claims")
    if not isinstance(rl_assertion.get("ci_identity"), Mapping):
        rl_findings.append("trusted-assertion-ci-identity")
    if not isinstance(rl_assertion.get("replay_guard"), Mapping):
        rl_findings.append("trusted-assertion-replay")
    rl_issued_at = rl_parse_timestamp(rl_assertion.get("issued_at"))
    rl_expires_at = rl_parse_timestamp(rl_assertion.get("expires_at"))
    rl_now = datetime.now(timezone.utc)
    if rl_issued_at is None or rl_expires_at is None or rl_expires_at <= rl_issued_at:
        rl_findings.append("trusted-assertion-time")
    elif rl_issued_at > rl_now:
        rl_findings.append("trusted-assertion-future")
    elif rl_expires_at <= rl_now:
        rl_findings.append("trusted-assertion-expired")
    if rl_assertion.get("payload_digest") != rl_compute_trusted_assertion_payload_digest(
        rl_assertion
    ):
        rl_findings.append("trusted-assertion-payload-digest")
    return rl_assertion, list(dict.fromkeys(rl_findings))


def rl_recursive_keys(rl_value: Any) -> set[str]:
    if isinstance(rl_value, Mapping):
        return {str(rl_key) for rl_key in rl_value} | {
            rl_key for rl_child in rl_value.values() for rl_key in rl_recursive_keys(rl_child)
        }
    if isinstance(rl_value, list):
        return {rl_key for rl_child in rl_value for rl_key in rl_recursive_keys(rl_child)}
    return set()


def rl_validate_semantic_payload(
    rl_section_name: str,
    rl_payload: Any,
    rl_manifest: Mapping[str, Any],
    rl_action_ids: set[str],
    rl_findings: list[str],
) -> None:
    rl_contract = rl_SECTION_CONTRACTS.get(rl_section_name)
    if not isinstance(rl_payload, Mapping) or rl_contract is None:
        rl_findings.append("artifact-payload-contract")
        return
    rl_required = set(rl_contract["required"])
    if set(rl_payload) != rl_COMMON_PAYLOAD_FIELDS | rl_required:
        rl_findings.append("artifact-payload-contract")
    if rl_payload.get("semantic_gate_contract_version") != rl_SEMANTIC_GATE_CONTRACT_VERSION:
        rl_findings.append("semantic-gate-contract-version")
    if rl_payload.get("section_name") != rl_section_name:
        rl_findings.append("artifact-section-mismatch")
    if rl_payload.get("artifact_kind") != rl_contract["kind"]:
        rl_findings.append("artifact-kind")
    if rl_payload.get("schema_version") != rl_contract["schema"]:
        rl_findings.append("artifact-schema")
    if rl_payload.get("run_id") != rl_manifest.get("run_id"):
        rl_findings.append("artifact-run-id")
    if rl_payload.get("owner") != rl_manifest.get("producer_principal"):
        rl_findings.append("artifact-owner")
    if rl_payload.get("reviewer") != rl_manifest.get("reviewer_principal"):
        rl_findings.append("artifact-reviewer")
    if rl_payload.get("status") != "passed":
        rl_findings.append("artifact-status")
    rl_action_ids_value = rl_payload.get("producer_action_ids")
    if (
        not isinstance(rl_action_ids_value, list)
        or not rl_action_ids_value
        or len(set(rl_action_ids_value)) != len(rl_action_ids_value)
        or not all(
            isinstance(rl_action_id, str) and rl_action_id in rl_action_ids
            for rl_action_id in rl_action_ids_value
        )
    ):
        rl_findings.append("artifact-action-binding")
    if rl_recursive_keys(rl_payload) & rl_SELF_DIGEST_KEYS:
        rl_findings.append("snapshot-self-digest")
    for rl_required_field in rl_required:
        # 为什么：空 list/dict 是合法的空集合（read_failures/failures/mismatches/
        # items/unknown_fields 等语义检查明确要求 == []），只有缺字段(None)或
        # 空串才是真正的 missing。
        if rl_payload.get(rl_required_field) in (None, ""):
            rl_findings.append("artifact-payload-contract")
    for rl_field in (
        "project_root_digest",
        "runtime_facts_digest",
        "cwd_digest",
        "registry_digest",
        "same_version_init_digest",
        "reference_digest",
        "server_digest",
        "structural_policy_digest",
        "policy_digest",
        "stable_key_digest",
        "exclusion_digest",
        "identity_digest",
        "snapshot_sha256",
        "pre_binding_digest",
        "post_binding_digest",
        "approval_digest",
        "seed_digest",
        "root_identity_digest",
        "acl_claim_digest",
        "archive_sha256",
        "list_sha256",
        "input_digest",
        "records_sha256",
        "sidecar_sha256",
    ):
        if rl_field in rl_payload and not rl_is_sha256(rl_payload.get(rl_field)):
            rl_findings.append("artifact-payload-digest")
    for rl_field in ("runtime_facts_ref", "same_version_init_ref", "snapshot_ref", "archive_ref", "list_ref", "records_ref", "sidecar_ref"):
        if rl_field in rl_payload and not rl_is_opaque_ref(rl_payload.get(rl_field)):
            rl_findings.append("artifact-payload-ref")
    if rl_section_name == "context_contract" and not (
        rl_payload.get("absolute_paths") is True
        and rl_payload.get("fresh_process") is True
        and rl_payload.get("in_process_settings_switch") is False
    ):
        rl_findings.append("context-semantic-failure")
    if rl_section_name == "profile_contract" and not (
        rl_payload.get("profile_only") is True
        and rl_payload.get("sanitized_env") is True
        and rl_payload.get("shell_false") is True
        and rl_payload.get("interactive_password") is False
        and rl_payload.get("mode_0700") is True
        and rl_payload.get("mode_0600") is True
    ):
        rl_findings.append("profile-semantic-failure")
    if rl_section_name == "catalog_baseline":
        rl_category_digests = rl_payload.get("category_digests")
        if (
            not isinstance(rl_category_digests, Mapping)
            or set(rl_category_digests) != set(rl_CATALOG_CATEGORIES)
            or any(
                not rl_is_sha256(rl_value)
                for rl_value in rl_category_digests.values()
            )
            or rl_payload.get("unknown_count") != 0
            or rl_payload.get("read_failures") != []
            or rl_payload.get("match") is not True
        ):
            rl_findings.append("catalog-semantic-failure")
    if rl_section_name == "canonical_snapshot_contract" and not (
        rl_payload.get("count_independent") is True
        and rl_payload.get("raw_rows") is False
        and rl_payload.get("self_digest_forbidden") is True
        and rl_payload.get("parent_sidecar_required") is True
    ):
        rl_findings.append("canonical-semantic-failure")
    rl_positive_table_count = rl_payload.get("positive_table_count")
    if rl_section_name == "semantic_projection_contract" and not (
        isinstance(rl_positive_table_count, int)
        and rl_positive_table_count > 0
        and rl_payload.get("content_digests_only") is True
        and rl_payload.get("raw_rows") is False
        and rl_payload.get("sequence_state") is True
        and rl_payload.get("unknown_fields") == []
    ):
        rl_findings.append("semantic-projection-failure")
    if rl_section_name == "migration_trajectory":
        rl_edges = rl_payload.get("edges")
        if not (
            rl_payload.get("nonempty_edges") is True
            and rl_payload.get("strict_ancestor") is True
            and rl_payload.get("downgrade_rehearsal") is True
            and rl_payload.get("seed_semantic") is True
            and isinstance(rl_edges, list)
            and bool(rl_edges)
            and len(rl_edges) == rl_payload.get("edge_count")
        ):
            rl_findings.append("migration-semantic-failure")
    if rl_section_name in {"empty_before_rebuild", "empty_before_restore"} and not (
        rl_payload.get("empty") is True
        and rl_payload.get("user_object_count") == 0
        and rl_payload.get("catalog_baseline_match") is True
    ):
        rl_findings.append("empty-proof-failure")
    if rl_section_name == "source_stability" and not (
        rl_payload.get("structural_match") is True
        and rl_payload.get("semantic_match") is True
        and rl_payload.get("sequence_match") is True
        and rl_payload.get("drift_detected") is False
    ):
        rl_findings.append("source-drift")
    if rl_section_name == "synthetic_source_policy" and not (
        rl_payload.get("classification") == "synthetic-non-sensitive"
        and rl_payload.get("raw_sensitive") is False
    ):
        rl_findings.append("synthetic-source-failure")
    if rl_section_name == "restricted_archive_policy" and not (
        rl_payload.get("mode_0700") is True
        and rl_payload.get("mode_0600") is True
        and rl_payload.get("opaque_only") is True
        and rl_payload.get("raw_ordinary") is False
        and rl_payload.get("cleanup_status") == "passed"
    ):
        rl_findings.append("restricted-archive-failure")
    rl_item_count = rl_payload.get("item_count")
    if rl_section_name in {"archive_summary", "list_summary"} and not (
        isinstance(rl_item_count, int)
        and rl_item_count >= 0
        and rl_payload.get("opaque_only") is True
        and rl_payload.get("unknown_count") == 0
        and rl_payload.get("failures") == []
        and rl_payload.get("raw_archive", False) is False
        and rl_payload.get("raw_full_list", False) is False
    ):
        rl_findings.append("archive-list-safety-failure")
    if rl_section_name == "restore_semantic_result" and not (
        all(
            rl_payload.get(rl_field) is True
            for rl_field in (
                "structural_match",
                "content_match",
                "count_match",
                "sequence_match",
                "extensions_match",
                "enums_match",
                "revision_match",
            )
        )
        and rl_payload.get("mismatches") == []
    ):
        rl_findings.append("restore-semantic-failure")
    if rl_section_name == "legacy_release_classification" and not (
        rl_payload.get("unresolved_count") == 0
        and rl_payload.get("items") == []
    ):
        rl_findings.append("legacy-classification-failure")


def rl_validate_artifact_index(
    rl_manifest: Mapping[str, Any],
    rl_artifact_root: Path | None,
    rl_action_ids: set[str],
    rl_findings: list[str],
) -> dict[str, dict[str, Any]]:
    rl_index = rl_manifest.get("artifact_index")
    if not isinstance(rl_index, list) or not rl_index or rl_artifact_root is None:
        rl_findings.append("artifact-index-invalid")
        return {}
    rl_entries: dict[str, dict[str, Any]] = {}
    for rl_raw_entry in rl_index:
        if not isinstance(rl_raw_entry, Mapping):
            rl_findings.append("artifact-index-invalid")
            continue
        rl_entry = dict(rl_raw_entry)
        rl_ref = rl_entry.get("opaque_ref")
        if not rl_is_opaque_ref(rl_ref) or rl_ref in rl_entries:
            rl_findings.append("artifact-ref-invalid")
            continue
        rl_kind = rl_entry.get("kind")
        rl_schema = rl_entry.get("schema_version")
        rl_primary_kinds = {rl_contract["kind"] for rl_contract in rl_SECTION_CONTRACTS.values()}
        if rl_kind not in rl_primary_kinds | {rl_SIDECAR_KIND, rl_ACTION_OUTPUT_KIND}:
            rl_findings.append("artifact-kind")
        if rl_kind in rl_primary_kinds:
            rl_contract = next(
                rl_contract
                for rl_contract in rl_SECTION_CONTRACTS.values()
                if rl_contract["kind"] == rl_kind
            )
            if rl_schema != rl_contract["schema"]:
                rl_findings.append("artifact-schema")
        elif rl_kind == rl_SIDECAR_KIND and rl_schema != rl_SIDECAR_SCHEMA:
            rl_findings.append("artifact-schema")
        elif rl_kind == rl_ACTION_OUTPUT_KIND and rl_schema != rl_ACTION_OUTPUT_SCHEMA:
            rl_findings.append("artifact-schema")
        if not rl_is_sha256(rl_entry.get("sha256")):
            rl_findings.append("artifact-digest")
        if rl_entry.get("run_id") != rl_manifest.get("run_id"):
            rl_findings.append("artifact-run-id")
        if rl_entry.get("owner") != rl_manifest.get("producer_principal"):
            rl_findings.append("artifact-owner")
        if rl_entry.get("reviewer") != rl_manifest.get("reviewer_principal"):
            rl_findings.append("artifact-reviewer")
        rl_producer_ids = rl_entry.get("producer_action_ids")
        if (
            not isinstance(rl_producer_ids, list)
            or not rl_producer_ids
            or len(set(rl_producer_ids)) != len(rl_producer_ids)
            or not all(
                isinstance(rl_action_id, str) and rl_action_id in rl_action_ids
                for rl_action_id in rl_producer_ids
            )
        ):
            rl_findings.append("artifact-action-binding")
        rl_file = rl_safe_regular_file(rl_artifact_root, str(rl_ref))
        if rl_file is None:
            rl_findings.append("artifact-missing-or-unsafe")
            continue
        rl_bytes = rl_file[1]
        if hashlib.sha256(rl_bytes).hexdigest() != rl_entry.get("sha256"):
            rl_findings.append("artifact-digest")
        if rl_bytes.startswith(b"PGDMP"):
            rl_findings.append("artifact-raw-archive")
        try:
            rl_payload = json.loads(rl_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            rl_findings.append("artifact-content-invalid")
            rl_entries[str(rl_ref)] = rl_entry
            continue
        if not isinstance(rl_payload, Mapping):
            rl_findings.append("artifact-content-invalid")
        elif rl_RAW_LIST_RE.search(rl_bytes.decode("utf-8")):
            rl_findings.append("artifact-raw-list")
        if rl_kind in rl_primary_kinds:
            rl_section_name = next(
                rl_name
                for rl_name, rl_contract in rl_SECTION_CONTRACTS.items()
                if rl_contract["kind"] == rl_kind
            )
            rl_validate_semantic_payload(
                rl_section_name,
                rl_payload,
                rl_manifest,
                rl_action_ids,
                rl_findings,
            )
        elif rl_kind == rl_SIDECAR_KIND:
            rl_validate_sidecar_payload(rl_payload, rl_manifest, rl_findings)
        elif rl_kind == rl_ACTION_OUTPUT_KIND:
            if not isinstance(rl_payload, Mapping) or rl_payload.get("status") != "passed":
                rl_findings.append("artifact-payload-contract")
        rl_entries[str(rl_ref)] = rl_entry
    rl_validate_canonical_sidecars(rl_entries, rl_artifact_root, rl_manifest, rl_findings)
    return rl_entries


def rl_validate_sidecar_payload(
    rl_payload: Any,
    rl_manifest: Mapping[str, Any],
    rl_findings: list[str],
) -> None:
    # 为什么（单向摘要 (a)）：child_sha256 不进 sidecar 文件字节，改由 sidecar 的
    # index entry 携带，避免 canonical-snapshot↔sidecar 互认证摘要形成哈希不动点
    # 循环（snapshot.sidecar_sha256 依赖 sidecar 字节，sidecar.child_sha256 依赖
    # snapshot 字节）。sidecar payload 只单向引用 child_ref。
    rl_required = {
        "child_ref",
        "child_kind",
        "child_schema_version",
        "run_id",
        "owner",
        "reviewer",
        "producer_action_id",
    }
    if not isinstance(rl_payload, Mapping) or set(rl_payload) != rl_required:
        rl_findings.append("sidecar-payload-contract")
        return
    if rl_payload.get("semantic_gate_contract_version") is not None:
        rl_findings.append("sidecar-payload-contract")
    if not rl_is_opaque_ref(rl_payload.get("child_ref")):
        rl_findings.append("sidecar-child-ref")
    if rl_payload.get("run_id") != rl_manifest.get("run_id"):
        rl_findings.append("sidecar-run-id")
    if rl_payload.get("owner") != rl_manifest.get("producer_principal"):
        rl_findings.append("sidecar-owner")
    if rl_payload.get("reviewer") != rl_manifest.get("reviewer_principal"):
        rl_findings.append("sidecar-reviewer")


def rl_validate_canonical_sidecars(
    rl_entries: Mapping[str, Mapping[str, Any]],
    rl_artifact_root: Path,
    rl_manifest: Mapping[str, Any],
    rl_findings: list[str],
) -> None:
    rl_canonical_entries = [
        (rl_ref, rl_entry)
        for rl_ref, rl_entry in rl_entries.items()
        if rl_entry.get("kind") == "canonical_snapshot"
    ]
    rl_sidecar_entries = [
        (rl_ref, rl_entry)
        for rl_ref, rl_entry in rl_entries.items()
        if rl_entry.get("kind") == rl_SIDECAR_KIND
    ]
    if len(rl_canonical_entries) != 1 or len(rl_sidecar_entries) != 1:
        rl_findings.append("canonical-sidecar-cardinality")
        return
    rl_snapshot_ref, rl_snapshot_entry = rl_canonical_entries[0]
    rl_sidecar_ref, rl_sidecar_entry = rl_sidecar_entries[0]
    rl_snapshot_file = rl_safe_regular_file(rl_artifact_root, rl_snapshot_ref)
    rl_sidecar_file = rl_safe_regular_file(rl_artifact_root, rl_sidecar_ref)
    if rl_snapshot_file is None or rl_sidecar_file is None:
        rl_findings.append("canonical-sidecar-missing")
        return
    try:
        rl_snapshot_payload = json.loads(rl_snapshot_file[1].decode("utf-8"))
        rl_sidecar_payload = json.loads(rl_sidecar_file[1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        rl_findings.append("canonical-sidecar-invalid")
        return
    if not isinstance(rl_snapshot_payload, Mapping) or not isinstance(
        rl_sidecar_payload, Mapping
    ):
        rl_findings.append("canonical-sidecar-invalid")
        return
    if rl_snapshot_payload.get("sidecar_ref") != rl_sidecar_ref:
        rl_findings.append("canonical-sidecar-binding")
    if rl_snapshot_payload.get("sidecar_sha256") != rl_sidecar_entry.get("sha256"):
        rl_findings.append("canonical-sidecar-digest")
    if rl_sidecar_payload.get("child_ref") != rl_snapshot_ref:
        rl_findings.append("canonical-sidecar-binding")
    # 为什么（单向摘要 (a)）：child_sha256 由 sidecar 的 index entry 提供，不进文件字节。
    if rl_sidecar_entry.get("child_sha256") != rl_snapshot_entry.get("sha256"):
        rl_findings.append("canonical-sidecar-digest")
    if rl_sidecar_payload.get("child_kind") != "canonical_snapshot":
        rl_findings.append("canonical-sidecar-kind")
    if rl_sidecar_payload.get("child_schema_version") != "a0.canonical-snapshot.v1":
        rl_findings.append("canonical-sidecar-schema")
    if rl_sidecar_entry.get("parent_ref") is not None or rl_sidecar_entry.get("sidecar_ref") is not None:
        rl_findings.append("canonical-sidecar-cycle")


def rl_event_index(
    rl_manifest: Mapping[str, Any],
    rl_findings: list[str],
) -> dict[str, dict[str, Any]]:
    rl_events: dict[str, dict[str, Any]] = {}
    for rl_collection_name in ("guard_events", "attestation_events"):
        rl_collection = rl_manifest.get(rl_collection_name)
        if not isinstance(rl_collection, Mapping):
            rl_findings.append(f"invalid-events:{rl_collection_name}")
            continue
        for rl_key, rl_value in rl_collection.items():
            if not isinstance(rl_value, Mapping) or not isinstance(rl_key, str):
                rl_findings.append("event-invalid")
                continue
            rl_event = dict(rl_value)
            rl_event_id = rl_event.get("event_id", rl_key)
            if (
                not isinstance(rl_event_id, str)
                or not rl_event_id
                or rl_event_id != rl_key
                or rl_event_id in rl_events
            ):
                rl_findings.append("event-duplicate")
                continue
            rl_events[rl_event_id] = rl_event
    return rl_events


def rl_validate_event(
    rl_event: Mapping[str, Any],
    rl_action: Mapping[str, Any],
    rl_event_role: str,
    rl_findings: list[str],
) -> None:
    rl_event_required = (
        "event_id",
        "kind",
        "action_id",
        "recipe_id",
        "phase_id",
        "sequence_no",
        "planned_binding_digest",
        "completed_binding_digest",
        "started_at",
        "completed_at",
        "output_tuples",
    )
    if any(rl_event.get(rl_field) in (None, "") for rl_field in rl_event_required):
        rl_findings.append("event-contract")
    if rl_event.get("action_id") != rl_action.get("action_id"):
        rl_findings.append("event-action-mismatch")
    for rl_field in ("recipe_id", "phase_id", "sequence_no", "planned_binding_digest", "completed_binding_digest"):
        if rl_event.get(rl_field) != rl_action.get(rl_field):
            rl_findings.append("event-binding-mismatch")
    if rl_event.get("kind") != rl_event_role:
        rl_findings.append("event-kind-mismatch")
    rl_started = rl_parse_timestamp(rl_event.get("started_at"))
    rl_completed = rl_parse_timestamp(rl_event.get("completed_at"))
    if rl_started is None or rl_completed is None or rl_completed < rl_started:
        rl_findings.append("event-time")
    if not isinstance(rl_event.get("output_tuples"), list):
        rl_findings.append("event-output-tuples")


def rl_validate_action_graph(
    rl_manifest: Mapping[str, Any],
    rl_run_id: str,
    rl_artifact_entries: Mapping[str, Mapping[str, Any]],
    rl_findings: list[str],
) -> set[str]:
    rl_actions = rl_manifest.get("database_actions")
    if not isinstance(rl_actions, list) or len(rl_actions) != len(rl_REQUIRED_PHASES):
        rl_findings.append("recipe-phase-count")
        return set()
    rl_action_ids: set[str] = set()
    rl_event_ids: set[str] = set()
    rl_event_map = rl_event_index(rl_manifest, rl_findings)
    rl_completion = rl_parse_timestamp(rl_manifest.get("producer_evidence_completed_at"))
    rl_outputs: dict[str, str] = {}
    rl_phase_to_action: dict[str, Mapping[str, Any]] = {}
    for rl_index, rl_raw_action in enumerate(rl_actions, start=1):
        if not isinstance(rl_raw_action, Mapping):
            rl_findings.append("action-invalid")
            continue
        rl_action = dict(rl_raw_action)
        rl_action_id = rl_action.get("action_id")
        if not isinstance(rl_action_id, str) or not rl_action_id or rl_action_id in rl_action_ids:
            rl_findings.append("action-duplicate")
        else:
            rl_action_ids.add(rl_action_id)
        rl_phase_id = rl_action.get("phase_id")
        if rl_phase_id not in rl_REQUIRED_PHASES or rl_phase_id in rl_phase_to_action:
            rl_findings.append("recipe-phase-invalid")
        else:
            rl_phase_to_action[str(rl_phase_id)] = rl_action
        if rl_action.get("sequence_no") != rl_index:
            rl_findings.append("recipe-sequence")
        if rl_action.get("recipe_id") != rl_RECIPE_ID:
            rl_findings.append("recipe-id")
        if rl_action.get("action_recipe_version") != rl_ACTION_RECIPE_VERSION:
            rl_findings.append("action-recipe-version")
        if rl_action.get("run_id") != rl_run_id:
            rl_findings.append("run-id-mismatch")
        if rl_action.get("action_type") not in rl_PHASE_ACTION_TYPES.get(str(rl_phase_id), set()):
            rl_findings.append("recipe-action-type")
        if rl_action.get("attestation_kind") == "not_applicable":
            rl_findings.append("not-applicable-for-database-action")
        if (
            str(rl_action.get("action_type", "")).startswith("alembic")
            or str(rl_action.get("phase_id", "")).startswith("M")
            and rl_action.get("action_type") in {"migration_forward", "migration_downgrade", "migration_reupgrade"}
        ) and rl_action.get("attestation_kind") != "actual_engine":
            rl_findings.append("alembic-attestation")
        rl_required_fields = (
            "role",
            "preceding_guard_event_id",
            "attestation_event_id",
            "identity_digest_version",
            "system_identifier_digest",
            "endpoint_context_digest",
            "configured_identity_redacted",
            "redacted_argv_template",
            "exit_code",
            "stdout_sha256",
            "stderr_sha256",
            "started_at",
            "finished_at",
            "plan_source_sha256",
            "spec_source_sha256",
            "tool_source_sha256",
            "test_source_sha256",
            "registry_tuple_digest",
            "marker_digest",
            "expiry",
            "executable_version",
            "artifact_refs_and_sha256",
            "action_binding_digest",
            "required_primary_output_kind",
            "owner",
            "reviewer",
        )
        rl_action_missing = False
        for rl_field in rl_required_fields:
            rl_value = rl_action.get(rl_field)
            # 为什么：required_primary_output_kind 可以为 None（非 primary phase
            # 无必需 primary output），其余字段缺失/空值才是 action-contract。
            if rl_field == "required_primary_output_kind":
                continue
            if rl_value in (None, "", [], {}):
                rl_action_missing = True
        if rl_action_missing:
            rl_findings.append("action-contract")
        for rl_digest_field in (
            "system_identifier_digest",
            "endpoint_context_digest",
            "stdout_sha256",
            "stderr_sha256",
            "plan_source_sha256",
            "spec_source_sha256",
            "tool_source_sha256",
            "test_source_sha256",
            "registry_tuple_digest",
            "marker_digest",
        ):
            if not rl_is_sha256(rl_action.get(rl_digest_field)):
                rl_findings.append("missing-source-digest")
        if rl_action.get("plan_source_sha256") != rl_manifest.get("plan_source_sha256") or rl_action.get("spec_source_sha256") != rl_manifest.get("spec_source_sha256"):
            rl_findings.append("action-plan-spec-mismatch")
        if rl_action.get("exit_code") != 0:
            rl_findings.append("nonzero-exit")
        rl_started = rl_parse_timestamp(rl_action.get("started_at"))
        rl_finished = rl_parse_timestamp(rl_action.get("finished_at"))
        rl_expiry = rl_parse_timestamp(rl_action.get("expiry"))
        if rl_started is None or rl_finished is None or rl_expiry is None:
            rl_findings.append("timestamp-invalid")
        elif rl_finished < rl_started or (rl_completion is not None and rl_finished > rl_completion) or rl_expiry < rl_finished:
            rl_findings.append("timestamp-order")
        if rl_action.get("identity_digest_version") != rl_manifest.get("identity_digest_version"):
            rl_findings.append("identity-digest-version")
        if rl_compute_action_binding_digest(rl_action) != rl_action.get("action_binding_digest"):
            rl_findings.append("action-binding-digest")
        for rl_event_field, rl_role in (("preceding_guard_event_id", "guard"), ("attestation_event_id", "attestation")):
            rl_event_id = rl_action.get(rl_event_field)
            if not isinstance(rl_event_id, str) or rl_event_id in rl_event_ids or rl_event_id not in rl_event_map:
                rl_findings.append("event-reuse-or-unresolved")
                continue
            rl_event_ids.add(rl_event_id)
            rl_validate_event(rl_event_map[rl_event_id], rl_action, rl_role, rl_findings)
        rl_action_artifacts = rl_action.get("artifact_refs_and_sha256")
        if not isinstance(rl_action_artifacts, list) or not rl_action_artifacts:
            rl_findings.append("action-artifacts")
        else:
            for rl_artifact_ref in rl_action_artifacts:
                if not isinstance(rl_artifact_ref, Mapping):
                    rl_findings.append("action-artifacts")
                    continue
                rl_ref = rl_artifact_ref.get("opaque_ref")
                rl_entry = rl_artifact_entries.get(rl_ref) if isinstance(rl_ref, str) else None
                if rl_entry is None:
                    rl_findings.append("action-artifact-unresolved")
                    continue
                for rl_field in ("sha256", "kind", "schema_version", "owner", "reviewer"):
                    if rl_artifact_ref.get(rl_field) != rl_entry.get(rl_field):
                        rl_findings.append("action-artifact-mismatch")
                if rl_artifact_ref.get("direction") not in {"input", "output"} or not isinstance(rl_artifact_ref.get("binding_role"), str):
                    rl_findings.append("action-artifact-typing")
                if rl_artifact_ref.get("direction") == "output":
                    if rl_ref in rl_outputs and rl_outputs[rl_ref] != rl_action_id:
                        rl_findings.append("artifact-multiple-producers")
                    rl_outputs[str(rl_ref)] = str(rl_action_id)
        rl_required_kind = rl_action.get("required_primary_output_kind")
        if rl_required_kind is not None and not any(
            isinstance(rl_artifact_ref, Mapping)
            and rl_artifact_ref.get("direction") == "output"
            and rl_artifact_ref.get("kind") == rl_required_kind
            for rl_artifact_ref in rl_action.get("artifact_refs_and_sha256", [])
        ):
            rl_findings.append("required-primary-output")
    if set(rl_phase_to_action) != set(rl_REQUIRED_PHASES):
        rl_findings.append("recipe-phases-missing-or-extra")
    for rl_phase_id, rl_section_name in rl_PHASE_PRIMARY_SECTIONS.items():
        rl_action = rl_phase_to_action.get(rl_phase_id)
        if rl_action is None:
            rl_findings.append("primary-action-missing")
            continue
        # 为什么：R02 的 primary output 是 action_output（非 section contract），
        # 其 kind 固定为 rl_ACTION_OUTPUT_KIND，不在 rl_SECTION_CONTRACTS 内。
        if rl_section_name == "action_output":
            rl_expected_kind: str | None = rl_ACTION_OUTPUT_KIND
        else:
            rl_expected_kind = rl_SECTION_CONTRACTS[rl_section_name]["kind"]
        if rl_action.get("required_primary_output_kind") != rl_expected_kind:
            rl_findings.append("primary-output-kind")
    rl_migration = rl_manifest.get("migration_trajectory")
    if isinstance(rl_migration, Mapping):
        rl_edges = rl_migration.get("edges")
        if not isinstance(rl_edges, list) or len(rl_edges) != rl_migration.get("edge_count") or not rl_edges:
            rl_findings.append("migration-edge-contract")
        else:
            for rl_edge in rl_edges:
                if not isinstance(rl_edge, Mapping) or not all(
                    isinstance(rl_edge.get(rl_key), str)
                    for rl_key in ("forward_action_id", "downgrade_action_id", "reupgrade_action_id")
                ):
                    rl_findings.append("migration-edge-contract")
    return rl_action_ids


def rl_validate_section_evidence(
    rl_manifest: Mapping[str, Any],
    rl_artifact_entries: Mapping[str, Mapping[str, Any]],
    rl_action_ids: set[str],
    rl_findings: list[str],
) -> None:
    rl_seen_refs: set[str] = set()
    for rl_section_name in rl_STATUS_FIELDS:
        rl_section = rl_manifest.get(rl_section_name)
        if not isinstance(rl_section, Mapping):
            rl_findings.append(f"invalid-status:{rl_section_name}")
            continue
        rl_ref = rl_section.get("evidence_ref")
        if not rl_is_opaque_ref(rl_ref) or rl_ref in rl_seen_refs:
            rl_findings.append("primary-evidence-ref-reuse")
        if isinstance(rl_ref, str):
            rl_seen_refs.add(rl_ref)
        rl_entry = rl_artifact_entries.get(rl_ref) if isinstance(rl_ref, str) else None
        if rl_entry is None:
            rl_findings.append("section-artifact-missing")
            continue
        rl_contract = rl_SECTION_CONTRACTS[rl_section_name]
        if rl_section.get("evidence_sha256") != rl_entry.get("sha256") or rl_section.get("evidence_kind") != rl_contract["kind"] or rl_section.get("evidence_schema_version") != rl_contract["schema"]:
            rl_findings.append("section-artifact-mismatch")
        if rl_entry.get("kind") != rl_contract["kind"] or rl_entry.get("schema_version") != rl_contract["schema"]:
            rl_findings.append("section-index-contract")
        if rl_entry.get("owner") != rl_manifest.get("producer_principal") or rl_section.get("owner") != rl_manifest.get("producer_principal"):
            rl_findings.append("section-owner")
        if rl_entry.get("reviewer") != rl_manifest.get("reviewer_principal") or rl_section.get("reviewer") != rl_manifest.get("reviewer_principal"):
            rl_findings.append("section-reviewer")
        if rl_manifest.get("producer_principal") == rl_manifest.get("reviewer_principal"):
            rl_findings.append("principal-distinctness")
        rl_mirror_fields = {
            rl_key: rl_value
            for rl_key, rl_value in rl_section.items()
            if rl_key not in {"status", "owner", "reviewer", "evidence_ref", "evidence_sha256", "evidence_kind", "evidence_schema_version"}
        }
        if rl_mirror_fields:
            rl_file = rl_safe_regular_file(Path(rl_manifest["artifact_root_path"]), str(rl_ref))
            if rl_file is None:
                rl_findings.append("section-artifact-missing")
            else:
                try:
                    rl_payload = json.loads(rl_file[1].decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    rl_payload = {}
                if not isinstance(rl_payload, Mapping) or any(rl_payload.get(rl_key) != rl_value for rl_key, rl_value in rl_mirror_fields.items()):
                    rl_findings.append("section-payload-mirror-mismatch")


def rl_validate_manifest_contract(
    rl_manifest: Mapping[str, Any],
    rl_run_id: str,
    rl_artifact_root: Path | None,
    rl_findings: list[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(rl_manifest, Mapping):
        rl_findings.append("manifest-invalid")
        return {}
    if rl_manifest.get("a0_evidence_manifest_version") != rl_MANIFEST_VERSION:
        rl_findings.append("manifest-version")
    if rl_manifest.get("run_id") != rl_run_id:
        rl_findings.append("run-id-mismatch")
    if rl_manifest.get("semantic_gate_contract_version") != rl_SEMANTIC_GATE_CONTRACT_VERSION:
        rl_findings.append("semantic-gate-contract-version")
    if rl_manifest.get("action_recipe_version") != rl_ACTION_RECIPE_VERSION:
        rl_findings.append("action-recipe-version")
    if rl_manifest.get("recipe_id") != rl_RECIPE_ID:
        rl_findings.append("recipe-id")
    for rl_field in rl_REQUIRED_MANIFEST_FIELDS:
        if rl_manifest.get(rl_field) in (None, "", [], {}):
            rl_findings.append(f"missing-top-level:{rl_field}")
    for rl_field in rl_ROOT_IDENTITY_FIELDS + (
        "project_root_digest",
        "plan_source_sha256",
        "spec_source_sha256",
        "review_tool_source_sha256",
        "gate_tool_source_sha256",
    ):
        if not rl_is_sha256(rl_manifest.get(rl_field)):
            rl_findings.append(f"invalid-top-level:{rl_field}")
    if not isinstance(rl_manifest.get("ci_identity"), Mapping):
        rl_findings.append("ci-identity")
    if not isinstance(rl_manifest.get("trusted_boundary"), Mapping):
        rl_findings.append("trusted-boundary")
    rl_action_ids = {
        str(rl_action.get("action_id"))
        for rl_action in rl_manifest.get("database_actions", [])
        if isinstance(rl_action, Mapping) and isinstance(rl_action.get("action_id"), str)
    }
    rl_entries = rl_validate_artifact_index(rl_manifest, rl_artifact_root, rl_action_ids, rl_findings)
    rl_validate_section_evidence(rl_manifest, rl_entries, rl_action_ids, rl_findings)
    rl_validate_action_graph(rl_manifest, rl_run_id, rl_entries, rl_findings)
    rl_unresolved = rl_manifest.get("unresolved_queue")
    if not isinstance(rl_unresolved, Mapping) or rl_unresolved.get("blocking_count") != 0:
        rl_findings.append("unresolved-blocking")
    return rl_entries


def rl_attestation_path_is_exact(
    rl_attestation_path: Path,
    rl_review_root: Path,
    rl_expected_ref: str,
) -> bool:
    if not rl_is_opaque_ref(rl_expected_ref):
        return False
    rl_resolved_root = rl_safe_canonical_directory(rl_review_root)
    if rl_resolved_root is None or rl_attestation_path.is_symlink():
        return False
    try:
        rl_expected_path = rl_resolved_root / rl_expected_ref
        if rl_attestation_path.absolute() != rl_expected_path.absolute():
            return False
        rl_stat = os.stat(rl_expected_path, follow_symlinks=False)
        return stat.S_ISREG(rl_stat.st_mode) and rl_stat.st_nlink == 1
    except (OSError, ValueError):
        return False


def rl_attestation_path_is_under_root(
    rl_attestation_path: Path,
    rl_review_root: Path,
) -> bool:
    return rl_attestation_path_is_exact(
        rl_attestation_path, rl_review_root, rl_attestation_path.name
    )


def rl_attestation_result(
    rl_run_id: str,
    rl_findings: list[str],
    **rl_fields: Any,
) -> dict[str, Any]:
    rl_unique_findings = list(dict.fromkeys(rl_findings))
    rl_result: dict[str, Any] = {
        "review_attestation_version": rl_ATTESTATION_VERSION,
        "semantic_gate_contract_version": rl_SEMANTIC_GATE_CONTRACT_VERSION,
        "run_id": rl_run_id,
        "decision": "PASS" if not rl_unique_findings else "BLOCKED",
        "blocking_findings": rl_unique_findings,
    }
    rl_result.update(rl_fields)
    return rl_result


def rl_write_json_exclusive(
    rl_target_path: Path,
    rl_payload: Mapping[str, Any],
) -> bool:
    try:
        rl_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        rl_fd = os.open(rl_target_path, rl_flags, 0o600)
        with os.fdopen(rl_fd, "wb") as rl_stream:
            rl_stream.write(rl_canonical_json(dict(rl_payload)) + b"\n")
        return True
    except OSError:
        return False


def rl_create_reviewer_attestation(
    rl_manifest_path: Path,
    rl_review_root: Path,
    rl_run_id: str,
    rl_trusted_verifier: rl_TrustedAssertionVerifier | Any | None = None,
    *,
    rl_producer_root: Path | None = None,
    rl_artifact_root: Path | None = None,
) -> dict[str, Any]:
    rl_findings: list[str] = []
    rl_manifest: dict[str, Any] = {}
    rl_expected_ref = "review-attestation-blocked.json"
    try:
        if not isinstance(rl_manifest_path, Path) or not isinstance(rl_review_root, Path):
            raise ValueError("path arguments required")
        rl_manifest = rl_normalize_manifest(rl_load_json(rl_manifest_path))
        rl_expected_ref = str(rl_manifest.get("review_attestation_ref", rl_expected_ref))
        if not rl_is_opaque_ref(rl_expected_ref):
            rl_findings.append("attestation-ref")
            rl_expected_ref = "review-attestation-blocked.json"
        if rl_artifact_root is None and isinstance(rl_manifest.get("artifact_root_path"), str):
            rl_artifact_root = Path(rl_manifest["artifact_root_path"])
        if rl_producer_root is None and isinstance(rl_manifest.get("producer_root_path"), str):
            rl_producer_root = Path(rl_manifest["producer_root_path"])
        try:
            rl_manifest_sha256 = rl_compute_manifest_digest(rl_manifest)
            rl_bundle_sha256 = rl_compute_bundle_digest(rl_manifest, rl_artifact_root)
        except (ValueError, TypeError, rl_ManifestScopeError):
            rl_manifest_sha256 = None
            rl_bundle_sha256 = None
            rl_findings.append("self-hash-scope")
        rl_validate_manifest_contract(rl_manifest, rl_run_id, rl_artifact_root, rl_findings)
        rl_root_digests = rl_root_identity_bindings(
            rl_manifest,
            rl_producer_root,
            rl_artifact_root,
            rl_review_root,
            rl_findings,
        )
        rl_assertion: dict[str, Any] | None = None
        if rl_root_digests is None or rl_manifest_sha256 is None or rl_bundle_sha256 is None:
            rl_findings.append("trusted-boundary-unverified")
        else:
            rl_request = rl_build_trusted_assertion_request(
                rl_manifest,
                rl_run_id,
                rl_root_digests,
                rl_manifest_sha256,
                rl_bundle_sha256,
            )
            rl_assertion, rl_assertion_findings = rl_verify_trusted_assertion(
                rl_trusted_verifier, rl_request
            )
            rl_findings.extend(rl_assertion_findings)
        rl_completion_raw = rl_manifest.get("producer_evidence_completed_at")
        rl_completion = rl_parse_timestamp(rl_completion_raw)
        rl_review_now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if rl_completion is None:
            rl_findings.append("producer-completion")
        rl_attestation_fields: dict[str, Any] = {
            "review_attestation_ref": rl_expected_ref,
            "manifest_sha256": rl_manifest_sha256,
            "recomputed_bundle_sha256": rl_bundle_sha256,
            "producer_evidence_completed_at": rl_completion_raw,
            "review_started_at": rl_review_now,
            "review_finished_at": rl_review_now,
        }
        if rl_assertion is not None and rl_root_digests is not None:
            rl_attestation_fields.update(
                {
                    "reviewer_identity": rl_assertion.get("reviewer_principal"),
                    "trusted_assertion": rl_assertion,
                    "trusted_assertion_ref": rl_assertion.get("assertion_ref"),
                    "trusted_assertion_payload_digest": rl_assertion.get("payload_digest"),
                    "trusted_boundary_reference": {
                        "root_identity_digests": rl_root_digests,
                        "assertion_ref": rl_assertion.get("assertion_ref"),
                    },
                }
            )
            rl_attestation_fields["review_source_sha256"] = rl_compute_review_source_digest(
                str(rl_manifest_sha256),
                str(rl_bundle_sha256),
                str(rl_assertion.get("reviewer_principal")),
                str(rl_completion_raw),
                rl_trusted_boundary=rl_manifest.get("trusted_boundary") if isinstance(rl_manifest.get("trusted_boundary"), Mapping) else None,
                rl_root_identity_digests=rl_root_digests,
                rl_assertion_payload_digest=str(rl_assertion.get("payload_digest")),
                rl_review_attestation_ref=rl_expected_ref,
                rl_review_started_at=rl_review_now,
                rl_review_finished_at=rl_review_now,
            )
        rl_attestation = rl_attestation_result(rl_run_id, rl_findings, **rl_attestation_fields)
    except Exception:
        rl_attestation = rl_attestation_result(
            rl_run_id,
            list(rl_findings) + ["reviewer-contract-error"],
            review_attestation_ref=rl_expected_ref,
        )
    try:
        rl_review_root_canonical = rl_prepare_safe_directory(rl_review_root)
        if rl_review_root_canonical is None:
            rl_attestation["decision"] = "BLOCKED"
            rl_attestation.setdefault("blocking_findings", []).append("root-symlink-or-invalid")
        else:
            rl_target_path = rl_review_root_canonical / rl_expected_ref
            if not rl_write_json_exclusive(rl_target_path, rl_attestation):
                rl_attestation["decision"] = "BLOCKED"
                rl_attestation.setdefault("blocking_findings", []).append("attestation-exists-or-unsafe")
            rl_attestation["blocking_findings"] = list(
                dict.fromkeys(rl_attestation.get("blocking_findings", []))
            )
    except Exception:
        rl_attestation["decision"] = "BLOCKED"
        rl_attestation.setdefault("blocking_findings", []).append("attestation-write")
    return rl_attestation


def rl_main() -> int:
    import argparse

    rl_parser = argparse.ArgumentParser(description="Write an independent A0 reviewer attestation")
    rl_parser.add_argument("--manifest-ref", required=True)
    rl_parser.add_argument("--review-root-ref", required=True)
    rl_parser.add_argument("--run-id", required=True)
    rl_args = rl_parser.parse_args()
    rl_attestation = rl_create_reviewer_attestation(
        Path(rl_args.manifest_ref), Path(rl_args.review_root_ref), rl_args.run_id
    )
    print(json.dumps(rl_attestation, ensure_ascii=False, sort_keys=True))
    return 0 if rl_attestation.get("decision") == "PASS" else 1


__all__ = [
    "rl_ACTION_RECIPE_VERSION",
    "rl_MANIFEST_VERSION",
    "rl_RECIPE_ID",
    "rl_SEMANTIC_GATE_CONTRACT_VERSION",
    "rl_STATUS_FIELDS",
    "rl_TrustedAssertionVerifier",
    "rl_attestation_path_is_exact",
    "rl_attestation_path_is_under_root",
    "rl_boundary_projection",
    "rl_build_trusted_assertion_request",
    "rl_compute_action_binding_digest",
    "rl_compute_bundle_digest",
    "rl_compute_manifest_digest",
    "rl_compute_review_source_digest",
    "rl_compute_root_identity_digest",
    "rl_compute_trusted_assertion_payload_digest",
    "rl_create_reviewer_attestation",
    "rl_is_opaque_ref",
    "rl_is_sha256",
    "rl_is_valid_trusted_boundary",
    "rl_load_json",
    "rl_load_trusted_boundary",
    "rl_manifest_scope",
    "rl_normalize_manifest",
    "rl_normalize_review_attestation_ref",
    "rl_parse_timestamp",
    "rl_root_identity_bindings",
    "rl_roots_are_disjoint",
    "rl_safe_canonical_directory",
    "rl_safe_regular_file",
    "rl_sha256",
    "rl_validate_artifact_index",
    "rl_validate_manifest_contract",
    "rl_verify_trusted_assertion",
]


if __name__ == "__main__":
    raise SystemExit(rl_main())
