"""受控 fixture 驱动的 legacy release evidence classifier tests。"""

from __future__ import annotations

import copy
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

rl_root_path = Path(__file__).resolve().parents[4]
if str(rl_root_path) not in sys.path:
    sys.path.insert(0, str(rl_root_path))

rl_fixture_path = Path(__file__).parent / "fixtures" / "rl_legacy_release_cases.json"
rl_sha256_pattern = re.compile(r"^sha256:[0-9a-fA-F]{64}$")
rl_evidence_identity_fields = {
    "content_revision": "content_revision_id",
    "frozen_build_input": "build_input_id",
    "immutable_manifest": "manifest_id",
    "publication_approval": "approval_id",
    "deployment": "deployment_id",
}
rl_linkage_digest_fields = (
    "content_revision_digest",
    "frozen_build_input_digest",
    "immutable_manifest_digest",
    "publication_approval_digest",
    "deployment_digest",
)


def rl_load_cases() -> list[dict]:
    with rl_fixture_path.open(encoding="utf-8") as rl_fixture_file:
        rl_payload = json.load(rl_fixture_file)
    return rl_payload["cases"]


def rl_get_module():
    try:
        return importlib.import_module("tools.a0.rl_classify_legacy_releases")
    except ImportError as rl_error:
        pytest.fail(f"classifier 缺失，红灯原因应为缺少实现: {rl_error}", pytrace=False)


def rl_get_case(rl_case_id: str) -> dict:
    for rl_case in rl_load_cases():
        if rl_case["case_id"] == rl_case_id:
            return rl_case
    raise AssertionError(f"fixture case not found: {rl_case_id}")


def rl_complete_input() -> dict:
    return copy.deepcopy(rl_get_case("complete-evidence-release")["input"])


def rl_result_for_case(rl_case_id: str) -> dict:
    return rl_get_module().rl_classify_release(rl_get_case(rl_case_id)["input"])


def test_rl_classifier_covers_all_controlled_fixture_cases():
    rl_module = rl_get_module()
    rl_cases = rl_load_cases()
    rl_inputs = [rl_case["input"] for rl_case in rl_cases]

    rl_results = rl_module.rl_classify_legacy_releases(rl_inputs)

    assert {rl_result["legacy_release_id"] for rl_result in rl_results} == {
        rl_case["input"]["legacy_id"] for rl_case in rl_cases
    }
    assert len(rl_results) == len(rl_cases)
    for rl_result, rl_case in zip(rl_results, rl_cases):
        assert rl_result["legacy_release_id"] == rl_case["input"]["legacy_id"]
        assert rl_result["version"] == rl_case["input"]["legacy_version"]
        assert rl_result["dataset_default"] == "DatasetRelease"
        assert rl_result["classification"] in {"DatasetRelease", "PublicationRelease"}
        assert isinstance(rl_result["owner"], str)
        assert isinstance(rl_result["reviewer"], str)
        assert rl_result["unresolved_codes"] == sorted(rl_result["unresolved_codes"])


def test_rl_complete_evidence_is_classified_and_matches_pure_output_schema():
    rl_module = rl_get_module()
    rl_result = rl_result_for_case("complete-evidence-release")
    rl_required_keys = {
        "legacy_release_id",
        "version",
        "dataset_default",
        "content_revision_evidence",
        "frozen_build_input",
        "final_manifest",
        "publication_approval",
        "deployment_attempt",
        "classification",
        "unresolved_codes",
        "evidence_digest",
        "owner",
        "reviewer",
        "unresolved_records",
    }

    assert rl_required_keys <= rl_result.keys()
    assert rl_result["dataset_default"] == "DatasetRelease"
    assert rl_result["classification"] == "PublicationRelease"
    assert rl_result["blocking"] is False
    assert rl_result["unresolved_codes"] == []
    assert rl_result["unresolved_records"] == []
    assert rl_sha256_pattern.fullmatch(rl_result["evidence_digest"])
    assert rl_result["owner"] == "data-owner"
    assert rl_result["reviewer"] == "release-reviewer"

    for rl_evidence_key in (
        "content_revision_evidence",
        "frozen_build_input",
        "final_manifest",
        "publication_approval",
        "deployment_attempt",
    ):
        assert isinstance(rl_result[rl_evidence_key], dict)
        assert rl_sha256_pattern.fullmatch(rl_result[rl_evidence_key]["digest"])
        assert rl_result[rl_evidence_key]["ref"]
        assert rl_result[rl_evidence_key]["identity"]

    assert rl_result["evidence_refs"] == [
        rl_result["content_revision_evidence"],
        rl_result["frozen_build_input"],
        rl_result["final_manifest"],
        rl_result["publication_approval"],
        rl_result["deployment_attempt"],
    ]
    assert rl_module.rl_build_unresolved_records(rl_result) == []


def test_rl_incomplete_public_release_remains_dataset_release_and_blocking():
    rl_result = rl_result_for_case("typical-incomplete-public-release")

    assert rl_result["publication_mapping"] is None
    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert {
        "rl_missing_deployment_evidence",
        "rl_missing_digest_linkage",
        "rl_missing_frozen_build_input",
        "rl_missing_immutable_manifest",
        "rl_missing_publication_approval",
    }.issubset(rl_result["unresolved_codes"])
    assert rl_result["source_relation_ref"] == "relations/legacy-incomplete.json"
    assert rl_sha256_pattern.fullmatch(rl_result["evidence_digest"])

    rl_content_ref = next(
        rl_ref for rl_ref in rl_result["evidence_refs"] if rl_ref["kind"] == "content_revision"
    )
    assert rl_content_ref["ref"] == "evidence/incomplete/content-revision.json"
    assert "digest" not in rl_content_ref
    assert len(rl_content_ref["canonical_json_sha256"]) == 64


@pytest.mark.parametrize(
    ("rl_metadata_field", "rl_metadata_value"),
    [
        ("is_public", False),
        ("is_public", True),
        ("published_at", "2099-01-01T00:00:00Z"),
        ("approved_by", "independent-publication-reviewer"),
        ("page_accessible", True),
    ],
)
def test_rl_public_metadata_mutations_cannot_promote_incomplete_release(
    rl_metadata_field: str, rl_metadata_value: Any
):
    rl_input = copy.deepcopy(rl_get_case("typical-incomplete-public-release")["input"])
    rl_baseline = rl_result_for_case("typical-incomplete-public-release")
    rl_input[rl_metadata_field] = rl_metadata_value

    rl_result = rl_get_module().rl_classify_release(rl_input)

    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert rl_result["unresolved_codes"] == rl_baseline["unresolved_codes"]


@pytest.mark.parametrize(
    ("rl_kind", "rl_field"),
    [
        (rl_kind, rl_field)
        for rl_kind, rl_identity_field in rl_evidence_identity_fields.items()
        for rl_field in ("ref", rl_identity_field, "digest")
    ],
)
def test_rl_missing_each_evidence_field_blocks(rl_kind: str, rl_field: str):
    rl_input = rl_complete_input()
    rl_input["evidence"][rl_kind].pop(rl_field)

    rl_result = rl_get_module().rl_classify_release(rl_input)

    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert f"rl_missing_{rl_kind}_{rl_field.removesuffix('_id')}" in rl_result["unresolved_codes"]


@pytest.mark.parametrize("rl_kind", tuple(rl_evidence_identity_fields))
def test_rl_wrong_evidence_item_type_blocks(rl_kind: str):
    rl_input = rl_complete_input()
    rl_input["evidence"][rl_kind] = ["not-a-mapping"]

    rl_result = rl_get_module().rl_classify_release(rl_input)

    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert f"rl_invalid_{rl_kind}_type" in rl_result["unresolved_codes"]


@pytest.mark.parametrize(
    ("rl_kind", "rl_field"),
    [
        (rl_kind, rl_field)
        for rl_kind, rl_identity_field in rl_evidence_identity_fields.items()
        for rl_field in ("ref", rl_identity_field, "digest")
    ],
)
def test_rl_empty_each_evidence_field_blocks(rl_kind: str, rl_field: str):
    rl_input = rl_complete_input()
    rl_input["evidence"][rl_kind][rl_field] = ""

    rl_result = rl_get_module().rl_classify_release(rl_input)

    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert f"rl_missing_{rl_kind}_{rl_field.removesuffix('_id')}" in rl_result["unresolved_codes"]


@pytest.mark.parametrize("rl_kind", tuple(rl_evidence_identity_fields))
def test_rl_invalid_evidence_digest_format_blocks(rl_kind: str):
    rl_input = rl_complete_input()
    rl_input["evidence"][rl_kind]["digest"] = "sha256:not-a-sha256-digest"

    rl_result = rl_get_module().rl_classify_release(rl_input)

    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert f"rl_invalid_{rl_kind}_digest" in rl_result["unresolved_codes"]


@pytest.mark.parametrize(
    "rl_approval_role",
    [None, "", 42, "release-reviewer"],
)
def test_rl_publication_approval_requires_independent_approver_role(rl_approval_role: Any):
    rl_input = rl_complete_input()
    if rl_approval_role is None:
        rl_input["evidence"]["publication_approval"].pop("approver_role")
    else:
        rl_input["evidence"]["publication_approval"]["approver_role"] = rl_approval_role

    rl_result = rl_get_module().rl_classify_release(rl_input)

    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert any(
        rl_code
        in {
            "rl_missing_publication_approval_approver_role",
            "rl_invalid_publication_approval_approver_role",
            "rl_non_independent_publication_approval_role",
        }
        for rl_code in rl_result["unresolved_codes"]
    )


@pytest.mark.parametrize("rl_deployment_outcome", [None, "", 42, "failed"])
def test_rl_deployment_requires_explicit_success_or_active_outcome(rl_deployment_outcome: Any):
    rl_input = rl_complete_input()
    if rl_deployment_outcome is None:
        rl_input["evidence"]["deployment"].pop("outcome")
    else:
        rl_input["evidence"]["deployment"]["outcome"] = rl_deployment_outcome

    rl_result = rl_get_module().rl_classify_release(rl_input)

    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert any(
        rl_code in {"rl_missing_deployment_outcome", "rl_invalid_deployment_outcome"}
        for rl_code in rl_result["unresolved_codes"]
    )


def test_rl_missing_source_relation_blocks_even_complete_evidence():
    rl_result = rl_result_for_case("missing-source-relation")

    assert rl_result["publication_mapping"] is None
    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert rl_result["unresolved_codes"] == ["rl_missing_source_relation"]
    assert rl_result["source_relation_ref"] is None
    assert len(rl_result["evidence_refs"]) == 5


@pytest.mark.parametrize("rl_linkage_field", ("version", "ref", "legacy_id", "legacy_version"))
def test_rl_missing_linkage_metadata_field_blocks(rl_linkage_field: str):
    rl_input = rl_complete_input()
    rl_input["evidence"]["digest_linkage"].pop(rl_linkage_field)

    rl_result = rl_get_module().rl_classify_release(rl_input)

    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert f"rl_missing_digest_linkage_{rl_linkage_field}" in rl_result["unresolved_codes"]


@pytest.mark.parametrize("rl_linkage_field", rl_linkage_digest_fields)
def test_rl_missing_each_linkage_digest_field_blocks(rl_linkage_field: str):
    rl_input = rl_complete_input()
    rl_input["evidence"]["digest_linkage"].pop(rl_linkage_field)

    rl_result = rl_get_module().rl_classify_release(rl_input)

    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert f"rl_missing_digest_linkage_{rl_linkage_field}" in rl_result["unresolved_codes"]


@pytest.mark.parametrize(
    ("rl_linkage_field", "rl_wrong_value", "rl_expected_code"),
    [
        ("version", "2099.99", "rl_digest_linkage_version_mismatch"),
        ("legacy_id", "legacy-other", "rl_digest_linkage_legacy_id_mismatch"),
        ("legacy_version", "2099.99", "rl_digest_linkage_legacy_version_mismatch"),
        ("ref", "evidence/other/digest-linkage.json", "rl_digest_linkage_ref_mismatch"),
    ],
)
def test_rl_linkage_identity_version_and_ref_mismatch_block(
    rl_linkage_field: str, rl_wrong_value: str, rl_expected_code: str
):
    rl_input = rl_complete_input()
    rl_input["evidence"]["digest_linkage"][rl_linkage_field] = rl_wrong_value

    rl_result = rl_get_module().rl_classify_release(rl_input)

    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert rl_expected_code in rl_result["unresolved_codes"]


def test_rl_extra_unknown_linkage_digest_field_blocks():
    rl_input = rl_complete_input()
    rl_input["evidence"]["digest_linkage"]["unknown_digest"] = "sha256:" + "f" * 64

    rl_result = rl_get_module().rl_classify_release(rl_input)

    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert "rl_unknown_digest_linkage_field" in rl_result["unresolved_codes"]


def test_rl_wrong_linkage_type_blocks():
    rl_input = rl_complete_input()
    rl_input["evidence"]["digest_linkage"] = "not-a-mapping"

    rl_result = rl_get_module().rl_classify_release(rl_input)

    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert "rl_invalid_digest_linkage_type" in rl_result["unresolved_codes"]


@pytest.mark.parametrize("rl_linkage_field", rl_linkage_digest_fields)
def test_rl_invalid_linkage_digest_format_blocks(rl_linkage_field: str):
    rl_input = rl_complete_input()
    rl_input["evidence"]["digest_linkage"][rl_linkage_field] = "sha256:invalid"

    rl_result = rl_get_module().rl_classify_release(rl_input)

    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert f"rl_invalid_digest_linkage_{rl_linkage_field}" in rl_result["unresolved_codes"]


@pytest.mark.parametrize("rl_linkage_field", rl_linkage_digest_fields)
def test_rl_each_linkage_digest_mismatch_blocks(rl_linkage_field: str):
    rl_input = rl_complete_input()
    rl_input["evidence"]["digest_linkage"][rl_linkage_field] = "sha256:" + "f" * 64

    rl_result = rl_get_module().rl_classify_release(rl_input)

    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert "rl_digest_mismatch" in rl_result["unresolved_codes"]


def test_rl_digest_mismatch_fixture_blocks_complete_evidence():
    rl_result = rl_result_for_case("digest-mismatch")

    assert rl_result["publication_mapping"] is None
    assert rl_result["classification"] == "DatasetRelease"
    assert rl_result["blocking"] is True
    assert rl_result["unresolved_codes"] == ["rl_digest_mismatch"]


def test_rl_unresolved_records_are_one_json_ready_record_per_code():
    rl_module = rl_get_module()
    rl_result = rl_result_for_case("typical-incomplete-public-release")
    rl_before = copy.deepcopy(rl_result)

    rl_records = rl_module.rl_build_unresolved_records(rl_result)

    assert rl_result == rl_before
    assert [rl_record["code"] for rl_record in rl_records] == rl_result["unresolved_codes"]
    for rl_record in rl_records:
        assert set(rl_record) == {
            "code",
            "legacy_release_id",
            "source",
            "blocking",
            "reason",
            "evidence_digest",
            "owner",
            "reviewer",
        }
        assert rl_record["legacy_release_id"] == rl_result["legacy_release_id"]
        assert rl_record["source"] == rl_result["source_relation_ref"]
        assert rl_record["blocking"] is True
        assert rl_record["reason"]
        assert rl_sha256_pattern.fullmatch(rl_record["evidence_digest"])


def test_rl_classifier_does_not_mutate_input_and_is_deterministic():
    rl_module = rl_get_module()
    rl_cases = rl_load_cases()
    rl_inputs = [rl_case["input"] for rl_case in rl_cases]
    rl_before = copy.deepcopy(rl_inputs)

    rl_first = rl_module.rl_classify_legacy_releases(rl_inputs)
    rl_second = rl_module.rl_classify_legacy_releases(rl_inputs)

    assert rl_inputs == rl_before
    assert rl_first == rl_second
    assert json.dumps(rl_first, ensure_ascii=False, sort_keys=True) == json.dumps(
        rl_second, ensure_ascii=False, sort_keys=True
    )

    rl_reversed = rl_module.rl_classify_legacy_releases(list(reversed(rl_inputs)))
    assert [rl_result["legacy_release_id"] for rl_result in rl_reversed] == [
        rl_input["legacy_id"] for rl_input in reversed(rl_inputs)
    ]


def test_rl_module_has_fixture_only_boundary_without_positional_cli():
    rl_module_source = Path(rl_get_module().__file__).read_text(encoding="utf-8")

    assert 'if __name__ == "__main__"' not in rl_module_source
