"""Pure fixture/dict classifier and report-record core for legacy releases.

本模块只消费受控 fixture/dict，生成纯 classification/unresolved records；不访问 DB、
不写 DB、不读写 docs/JSONL。真实 guarded profile reader 与 docs/JSONL writer 属于后续
A0 live integration，由外部 profile/provisioner 条件控制，不能由本 task 假装实现。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

rl_sha256_pattern = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
rl_evidence_kinds = (
    "content_revision",
    "frozen_build_input",
    "immutable_manifest",
    "publication_approval",
    "deployment",
)
rl_evidence_identity_fields = {
    "content_revision": "content_revision_id",
    "frozen_build_input": "build_input_id",
    "immutable_manifest": "manifest_id",
    "publication_approval": "approval_id",
    "deployment": "deployment_id",
}
rl_linkage_metadata_fields = ("version", "ref", "legacy_id", "legacy_version")
rl_linkage_digest_fields = (
    "content_revision_digest",
    "frozen_build_input_digest",
    "immutable_manifest_digest",
    "publication_approval_digest",
    "deployment_digest",
)
rl_linkage_allowed_fields = frozenset(
    (*rl_linkage_metadata_fields, *rl_linkage_digest_fields)
)


def rl_classify_legacy_releases(
    rl_releases: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Classify supplied fixture rows without mutation or external side effects."""

    return [rl_classify_release(rl_release) for rl_release in rl_releases]


def rl_classify_release(rl_release: Mapping[str, Any]) -> dict[str, Any]:
    """Return deterministic pure-core mapping; default remains ``DatasetRelease``."""

    rl_unresolved_codes: set[str] = set()
    rl_evidence = rl_release.get("evidence")
    if not isinstance(rl_evidence, Mapping):
        rl_evidence = {}
        rl_unresolved_codes.add("rl_invalid_evidence_type")

    rl_evidence_refs: list[dict[str, Any]] = []
    for rl_kind in rl_evidence_kinds:
        rl_item = rl_evidence.get(rl_kind)
        if not isinstance(rl_item, Mapping):
            rl_unresolved_codes.add(
                "rl_missing_deployment_evidence"
                if rl_kind == "deployment"
                else f"rl_missing_{rl_kind}"
            )
            if rl_item is not None:
                rl_unresolved_codes.add(f"rl_invalid_{rl_kind}_type")
            continue

        rl_item_codes = rl_validate_evidence_item(rl_kind, rl_item)
        rl_unresolved_codes.update(rl_item_codes)
        rl_evidence_refs.append(rl_build_evidence_ref(rl_kind, rl_item))

    if not rl_release.get("source_relation_ref"):
        # 保守规则：没有 legacy→source 关系，完整 evidence 也不能升级 publication。
        rl_unresolved_codes.add("rl_missing_source_relation")

    rl_digest_linkage = rl_evidence.get("digest_linkage")
    rl_unresolved_codes.update(
        rl_validate_digest_linkage(
            rl_release=rl_release,
            rl_evidence=rl_evidence,
            rl_digest_linkage=rl_digest_linkage,
        )
    )

    rl_evidence_digest = rl_evidence_digest_for(rl_release, rl_evidence_refs)
    rl_can_publish = not rl_unresolved_codes
    rl_classification = "PublicationRelease" if rl_can_publish else "DatasetRelease"
    rl_owner = rl_release.get("owner_role", "")
    rl_reviewer = rl_release.get("reviewer_role", "")
    rl_result: dict[str, Any] = {
        "legacy_release_id": rl_release.get("legacy_id"),
        "version": rl_release.get("legacy_version"),
        "dataset_default": "DatasetRelease",
        "content_revision_evidence": rl_find_evidence_ref(
            rl_evidence_refs, "content_revision"
        ),
        "frozen_build_input": rl_find_evidence_ref(
            rl_evidence_refs, "frozen_build_input"
        ),
        "final_manifest": rl_find_evidence_ref(rl_evidence_refs, "immutable_manifest"),
        "publication_approval": rl_find_evidence_ref(
            rl_evidence_refs, "publication_approval"
        ),
        "deployment_attempt": rl_find_evidence_ref(rl_evidence_refs, "deployment"),
        "classification": rl_classification,
        "unresolved_codes": sorted(rl_unresolved_codes),
        "evidence_digest": rl_evidence_digest,
        "owner": rl_owner,
        "reviewer": rl_reviewer,
        "unresolved_records": [],
        # Compatibility fields retained for the prior Task 6 consumer shape.
        "legacy_id": rl_release.get("legacy_id"),
        "legacy_version": rl_release.get("legacy_version"),
        "default_mapping": "DatasetRelease",
        "publication_mapping": "PublicationRelease" if rl_can_publish else None,
        "blocking": not rl_can_publish,
        "source_relation_ref": rl_release.get("source_relation_ref"),
        "evidence_refs": rl_evidence_refs,
        "owner_role": rl_owner,
        "reviewer_role": rl_reviewer,
    }
    rl_result["unresolved_records"] = rl_build_unresolved_records(rl_result)
    return rl_result


def rl_validate_evidence_item(rl_kind: str, rl_item: Mapping[str, Any]) -> set[str]:
    rl_codes: set[str] = set()
    rl_identity_field = rl_evidence_identity_fields[rl_kind]
    for rl_field in ("ref", rl_identity_field, "digest"):
        rl_value = rl_item.get(rl_field)
        if not isinstance(rl_value, str) or not rl_value.strip():
            # 保守规则：字段为空或类型不符时，不能从其他 metadata 猜出 evidence identity。
            rl_codes.add(f"rl_missing_{rl_kind}_{rl_field.removesuffix('_id')}")
    rl_digest = rl_item.get("digest")
    if (
        isinstance(rl_digest, str)
        and rl_digest
        and not rl_sha256_pattern.fullmatch(rl_digest)
    ):
        rl_codes.add(f"rl_invalid_{rl_kind}_digest")

    if rl_kind == "publication_approval":
        rl_approver_role = rl_item.get("approver_role")
        if not isinstance(rl_approver_role, str) or not rl_approver_role.strip():
            rl_codes.add("rl_missing_publication_approval_approver_role")
        elif "independent" not in rl_approver_role.lower():
            # 保守规则：普通 admin/reviewer 身份不等价于独立 publication approval。
            rl_codes.add("rl_non_independent_publication_approval_role")

    if rl_kind == "deployment":
        rl_outcome = rl_item.get("outcome")
        if not isinstance(rl_outcome, str) or not rl_outcome.strip():
            rl_codes.add("rl_missing_deployment_outcome")
        elif rl_outcome.lower() not in {"success", "active"}:
            # 保守规则：page accessible/is_public 不证明 deployment 成功或 active。
            rl_codes.add("rl_invalid_deployment_outcome")
    return rl_codes


def rl_validate_digest_linkage(
    rl_release: Mapping[str, Any],
    rl_evidence: Mapping[str, Any],
    rl_digest_linkage: Any,
) -> set[str]:
    rl_codes: set[str] = set()
    if not isinstance(rl_digest_linkage, Mapping):
        rl_codes.add("rl_missing_digest_linkage")
        if rl_digest_linkage is not None:
            rl_codes.add("rl_invalid_digest_linkage_type")
        return rl_codes

    for rl_field in rl_linkage_metadata_fields:
        rl_value = rl_digest_linkage.get(rl_field)
        if not isinstance(rl_value, str) or not rl_value.strip():
            rl_codes.add(f"rl_missing_digest_linkage_{rl_field}")
    for rl_field in rl_linkage_digest_fields:
        rl_value = rl_digest_linkage.get(rl_field)
        if not isinstance(rl_value, str) or not rl_value.strip():
            rl_codes.add(f"rl_missing_digest_linkage_{rl_field}")
        elif not rl_sha256_pattern.fullmatch(rl_value):
            rl_codes.add(f"rl_invalid_digest_linkage_{rl_field}")
    for rl_field in set(rl_digest_linkage) - rl_linkage_allowed_fields:
        rl_codes.add("rl_unknown_digest_linkage_field")

    if rl_digest_linkage.get("legacy_id") != rl_release.get("legacy_id"):
        rl_codes.add("rl_digest_linkage_legacy_id_mismatch")
    if rl_digest_linkage.get("legacy_version") != rl_release.get("legacy_version"):
        rl_codes.add("rl_digest_linkage_legacy_version_mismatch")
    rl_expected_ref = rl_digest_linkage.get("ref")
    if rl_expected_ref and rl_expected_ref != rl_expected_linkage_ref(rl_evidence):
        rl_codes.add("rl_digest_linkage_ref_mismatch")

    for rl_kind in rl_evidence_kinds:
        rl_item = rl_evidence.get(rl_kind)
        rl_digest_field = f"{rl_kind}_digest"
        if not isinstance(rl_item, Mapping):
            continue
        rl_item_digest = rl_item.get("digest")
        rl_linked_digest = rl_digest_linkage.get(rl_digest_field)
        if (
            isinstance(rl_item_digest, str)
            and rl_sha256_pattern.fullmatch(rl_item_digest)
            and isinstance(rl_linked_digest, str)
            and rl_sha256_pattern.fullmatch(rl_linked_digest)
            and rl_item_digest != rl_linked_digest
        ):
            # 保守规则：linkage 与 evidence digest 不一致时，不尝试选择一方作为真值。
            rl_codes.add("rl_digest_mismatch")
    if rl_digest_linkage.get("version") != "1":
        rl_codes.add("rl_digest_linkage_version_mismatch")
    return rl_codes


def rl_expected_linkage_ref(rl_evidence: Mapping[str, Any]) -> str | None:
    for rl_kind in rl_evidence_kinds:
        rl_item = rl_evidence.get(rl_kind)
        if isinstance(rl_item, Mapping) and rl_item.get("ref"):
            rl_ref = str(rl_item["ref"])
            if "/" in rl_ref:
                return f"{rl_ref.rsplit('/', 1)[0]}/digest-linkage.json"
    return None


def rl_build_evidence_ref(rl_kind: str, rl_item: Mapping[str, Any]) -> dict[str, Any]:
    rl_ref: dict[str, Any] = {
        "kind": rl_kind,
        "ref": rl_item.get("ref"),
        "identity": rl_item.get(rl_evidence_identity_fields[rl_kind]),
        "digest": rl_item.get("digest"),
    }
    if not rl_ref["digest"]:
        rl_ref.pop("digest")
        rl_ref["canonical_json_sha256"] = rl_canonical_json_sha256(rl_item)
    return rl_ref


def rl_find_evidence_ref(
    rl_evidence_refs: list[dict[str, Any]], rl_kind: str
) -> dict[str, Any] | None:
    return next(
        (rl_ref for rl_ref in rl_evidence_refs if rl_ref["kind"] == rl_kind), None
    )


def rl_canonical_json_sha256(rl_value: Mapping[str, Any]) -> str:
    rl_canonical_json = json.dumps(
        rl_value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(rl_canonical_json).hexdigest()


def rl_evidence_digest_for(
    rl_release: Mapping[str, Any], rl_evidence_refs: list[dict[str, Any]]
) -> str:
    rl_digest_input = {
        "legacy_id": rl_release.get("legacy_id"),
        "legacy_version": rl_release.get("legacy_version"),
        "source_relation_ref": rl_release.get("source_relation_ref"),
        "evidence_refs": rl_evidence_refs,
    }
    return f"sha256:{rl_canonical_json_sha256(rl_digest_input)}"


def rl_build_unresolved_records(rl_result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build JSON-ready unresolved records without writing JSONL."""

    rl_reason_map = {
        "rl_missing_source_relation": "legacy release lacks a source relation",
        "rl_digest_mismatch": "evidence digest linkage does not match evidence",
    }
    return [
        {
            "code": rl_code,
            "legacy_release_id": rl_result.get("legacy_release_id"),
            "source": rl_result.get("source_relation_ref"),
            "blocking": True,
            "reason": rl_reason_map.get(
                rl_code, f"evidence requirement unresolved: {rl_code}"
            ),
            "evidence_digest": rl_result.get("evidence_digest"),
            "owner": rl_result.get("owner", ""),
            "reviewer": rl_result.get("reviewer", ""),
        }
        for rl_code in rl_result.get("unresolved_codes", [])
    ]


def rl_load_json_and_classify(rl_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Classify controlled JSON in memory; this is not a profile/DB/report writer CLI."""

    rl_releases = rl_payload.get("releases", rl_payload.get("cases", []))
    return rl_classify_legacy_releases(
        rl_case.get("input", rl_case) if isinstance(rl_case, Mapping) else rl_case
        for rl_case in rl_releases
    )
