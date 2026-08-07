"""纯数据 A0 catalog baseline contract tests。

这些测试只允许使用内存中的 dict/list fixture。它们不代表真实 PostgreSQL
inventory，也不生成 live evidence。
"""

from __future__ import annotations

import ast as rl_ast
import hashlib as rl_hashlib
import inspect as rl_inspect
import json as rl_json
from pathlib import Path as rl_Path

import pytest

from tools.a0 import rl_catalog_baseline as rl_module
from tools.a0.rl_catalog_baseline import (
    RL_RELKIND_MAPPING,
    RL_REQUIRED_CATALOG_CATEGORIES,
    rl_build_catalog_baseline,
    rl_canonical_json,
    rl_classify_relkind,
    rl_sha256_digest,
    rl_validate_catalog_contract,
)


rl_EXPECTED_REQUIRED_CATEGORIES = {
    "schemas",
    "namespaces",
    "relations",
    "columns",
    "defaults",
    "indexes",
    "constraints",
    "rules",
    "types",
    "domains",
    "composites",
    "enums",
    "ranges",
    "procs",
    "triggers",
    "policies",
    "extensions",
    "languages",
    "collations",
    "fdw",
    "servers",
    "user_mappings",
    "publications",
    "subscriptions",
    "large_objects",
    "event_triggers",
    "text_search",
    "casts",
    "operators",
    "opclasses",
    "opfamilies",
    "transforms",
    "statistics",
    "security_labels",
    "ownership",
    "acl",
    "tablespace",
}


def rl_complete_catalog(*rl_objects: object) -> dict[str, object]:
    """Build a complete static fixture without consulting production metadata."""

    rl_catalog: dict[str, object] = {
        rl_category: [] for rl_category in RL_REQUIRED_CATALOG_CATEGORIES
    }
    rl_catalog["relations"] = list(rl_objects)
    return rl_catalog


def rl_orders_object(**rl_overrides: object) -> dict[str, object]:
    rl_object: dict[str, object] = {
        "schema": "public",
        "name": "orders",
        "category": "relations",
        "relkind": "r",
        "owner": "owner-a",
        "acl": ["owner-a=arwdDxt/owner-a"],
        "tablespace": "pg_default",
        "definition": (
            "CREATE TABLE public.orders (id integer DEFAULT "
            "rl_sensitive_default_20260730_8f1c)"
        ),
        "default": "rl_sensitive_default_20260730_8f1c",
    }
    rl_object.update(rl_overrides)
    return rl_object


def rl_reference_for_orders(**rl_overrides: object) -> dict[str, object]:
    rl_expected = rl_orders_object(**rl_overrides)
    return {
        "postgres_version": "16.4",
        "init_digest": "sha256:init-a0",
        "allowlist": [rl_expected],
    }


def test_all_postgresql_relkinds_are_explicit_and_case_sensitive() -> None:
    assert RL_RELKIND_MAPPING == {
        "r": "ordinary_table",
        "i": "index",
        "S": "sequence",
        "t": "toast",
        "v": "view",
        "m": "materialized_view",
        "c": "composite_type",
        "f": "foreign_table",
        "p": "partitioned_table",
        "I": "partitioned_index",
    }

    for rl_relkind, rl_object_kind in RL_RELKIND_MAPPING.items():
        rl_result = rl_classify_relkind(rl_relkind)
        assert rl_result["rl_status"] == "known"
        assert rl_result["rl_object_kind"] == rl_object_kind
        assert rl_result["rl_blocking"] is False

    for rl_relkind in (None, "", "s", "X", "rr", 1):
        rl_result = rl_classify_relkind(rl_relkind)
        assert rl_result["rl_status"] == "BLOCKED"
        assert rl_result["rl_blocking"] is True
        assert rl_result["rl_object_kind"] == "unknown"
        assert "unknown_relkind" in rl_result["rl_reason_codes"]


def test_catalog_normalization_and_digest_ignore_input_sorting() -> None:
    rl_left = {
        "relations": [
            {"name": "b", "schema": "public"},
            {"name": "a", "schema": "public"},
        ],
        "nested": {"items": [{"z": 2}, {"z": 1}]},
    }
    rl_right = {
        "nested": {"items": [{"z": 1}, {"z": 2}]},
        "relations": [
            {"schema": "public", "name": "a"},
            {"schema": "public", "name": "b"},
        ],
    }

    assert rl_canonical_json(rl_left) == rl_canonical_json(rl_right)
    assert rl_sha256_digest(rl_left) == rl_sha256_digest(rl_right)
    assert rl_sha256_digest(rl_left).startswith("sha256:")

    rl_expected_bytes = rl_canonical_json(rl_left).encode("utf-8")
    assert rl_sha256_digest(rl_left) == "sha256:" + rl_hashlib.sha256(rl_expected_bytes).hexdigest()


def test_required_category_contract_is_explicit_and_not_an_empty_table_shortcut() -> None:
    assert rl_EXPECTED_REQUIRED_CATEGORIES <= set(RL_REQUIRED_CATALOG_CATEGORIES)

    rl_complete = rl_complete_catalog()
    rl_valid = rl_validate_catalog_contract(rl_complete)
    assert rl_valid["rl_status"] == "VALID"
    assert rl_valid["rl_missing_categories"] == []

    rl_missing = dict(rl_complete)
    del rl_missing["extensions"]
    rl_missing_result = rl_validate_catalog_contract(rl_missing)
    assert rl_missing_result["rl_status"] == "BLOCKED"
    assert "extensions" in rl_missing_result["rl_missing_categories"]

    rl_empty_shortcut = {"relations": []}
    rl_empty_result = rl_validate_catalog_contract(rl_empty_shortcut)
    assert rl_empty_result["rl_status"] == "BLOCKED"
    assert set(rl_empty_result["rl_missing_categories"]) >= rl_EXPECTED_REQUIRED_CATEGORIES - {"relations"}


def test_baseline_objects_are_digest_only_and_static_match_stays_blocked() -> None:
    rl_secret_values = (
        (
            "CREATE TABLE public.orders (id integer DEFAULT "
            "rl_sensitive_default_20260730_8f1c)"
        ),
        "owner-a=arwdDxt/owner-a",
        "rl_sensitive_default_20260730_8f1c",
        "/var/lib/postgresql/16/main/rl_sensitive_catalog_20260730_8f1c",
        "https://db.example.invalid/catalog/rl_sensitive_20260730_8f1c",
        "postgres://a0:rl_sensitive_password_20260730@db.example.invalid/main",
    )
    rl_catalog = rl_complete_catalog(rl_orders_object())
    rl_result = rl_build_catalog_baseline(
        rl_catalog,
        rl_reference_for_orders(),
        rl_postgres_version="16.4",
        rl_init_digest="sha256:init-a0",
    )
    rl_serialized = rl_json.dumps(rl_result, ensure_ascii=False, sort_keys=True)

    assert rl_result["rl_comparison_status"] == "MATCH"
    assert rl_result["rl_status"] == "BLOCKED"
    assert rl_result["rl_evidence_status"] == "BLOCKED"
    assert rl_result["rl_live_status"] == "BLOCKED"
    assert rl_result["rl_objects"]
    rl_object = rl_result["rl_objects"][0]
    for rl_field in (
        "rl_class",
        "rl_identity_digest",
        "rl_relkind",
        "rl_object_kind",
        "rl_owner_digest",
        "rl_acl_digest",
        "rl_tablespace_digest",
        "rl_definition_digest",
        "rl_expected_system_baseline",
    ):
        assert rl_field in rl_object
    assert "orders" not in rl_serialized
    assert "public" not in rl_serialized
    for rl_secret in rl_secret_values:
        assert rl_secret not in rl_serialized


def test_catalog_summary_uses_v2_and_keeps_fixture_comparison_separate_from_live_state() -> None:
    rl_result = rl_build_catalog_baseline(
        rl_complete_catalog(rl_orders_object()),
        rl_reference_for_orders(),
        rl_postgres_version="16.4",
        rl_init_digest="sha256:init-a0",
    )

    assert rl_result["rl_schema_version"] == "a0.catalog-baseline.v2"
    assert rl_result["rl_comparison_status"] == "MATCH"
    assert rl_result["rl_evidence_status"] == "BLOCKED"
    assert rl_result["rl_live_status"] == "BLOCKED"
    assert rl_result["rl_status"] == "BLOCKED"


def test_valid_fixture_field_drift_is_drift_not_a_live_or_evidence_pass() -> None:
    rl_result = rl_build_catalog_baseline(
        rl_complete_catalog(rl_orders_object(owner="owner-b")),
        rl_reference_for_orders(),
        rl_postgres_version="16.4",
        rl_init_digest="sha256:init-a0",
    )

    assert rl_result["rl_comparison_status"] == "DRIFT"
    assert "owner_mismatch" in rl_result["rl_reason_codes"]
    assert rl_result["rl_evidence_status"] == "BLOCKED"
    assert rl_result["rl_live_status"] == "BLOCKED"


def test_each_catalog_row_requires_a_matching_category_and_valid_identity() -> None:
    rl_catalog = rl_complete_catalog(
        "not-a-catalog-row",
        {"schema": "public", "name": "orders", "relkind": "r"},
        {"schema": "", "name": "missing_schema", "category": "relations", "relkind": "r"},
    )

    rl_validation = rl_validate_catalog_contract(rl_catalog)

    assert rl_validation["rl_status"] == "BLOCKED"
    assert "relations" in rl_validation["rl_invalid_categories"]
    assert "invalid_row" in rl_validation["rl_reason_codes"]
    assert "invalid_identity" in rl_validation["rl_reason_codes"]


def test_unknown_nonrelation_class_is_fail_closed_at_row_validation() -> None:
    rl_catalog = rl_complete_catalog()
    rl_catalog["extensions"] = [
        {"schema": "public", "name": "postgis", "category": "extensions", "kind": "mystery"}
    ]

    rl_validation = rl_validate_catalog_contract(rl_catalog)

    assert rl_validation["rl_status"] == "BLOCKED"
    assert "unknown_object_class" in rl_validation["rl_reason_codes"]


@pytest.mark.parametrize(
    ("rl_field", "rl_reason"),
    (
        ("definition", "definition_mismatch"),
        ("default", "default_mismatch"),
        ("fields", "field_mismatch"),
        ("columns", "column_mismatch"),
        ("indexes", "index_mismatch"),
        ("constraints", "constraint_mismatch"),
        ("rules", "rule_mismatch"),
        ("types", "type_mismatch"),
        ("domains", "domain_mismatch"),
        ("composites", "composite_mismatch"),
        ("enums", "enum_mismatch"),
        ("extensions", "extension_mismatch"),
    ),
)
def test_catalog_comparison_covers_digest_fields_without_returning_values(
    rl_field: str, rl_reason: str
) -> None:
    rl_result = rl_build_catalog_baseline(
        rl_complete_catalog(rl_orders_object(**{rl_field: {"observed": "two"}})),
        rl_reference_for_orders(),
        rl_postgres_version="16.4",
        rl_init_digest="sha256:init-a0",
    )

    assert rl_result["rl_comparison_status"] == "DRIFT"
    assert rl_reason in rl_result["rl_reason_codes"]
    rl_serialized = rl_json.dumps(rl_result, ensure_ascii=False, sort_keys=True)
    assert "observed" not in rl_serialized
    assert "two" not in rl_serialized


def test_catalog_reference_rejects_duplicate_reference_identity() -> None:
    rl_reference = {
        "postgres_version": "16.4",
        "init_digest": "sha256:init-a0",
        "allowlist": [rl_orders_object(), rl_orders_object()],
    }
    rl_result = rl_build_catalog_baseline(
        rl_complete_catalog(rl_orders_object()),
        rl_reference,
        rl_postgres_version="16.4",
        rl_init_digest="sha256:init-a0",
    )

    assert rl_result["rl_comparison_status"] == "BLOCKED"
    assert "duplicate_reference_identity" in rl_result["rl_reason_codes"]


def test_catalog_reference_reports_missing_expected_object_independently() -> None:
    rl_extra_expected = rl_orders_object(name="expected_but_not_observed")
    rl_result = rl_build_catalog_baseline(
        rl_complete_catalog(rl_orders_object()),
        {
            "postgres_version": "16.4",
            "init_digest": "sha256:init-a0",
            "allowlist": [rl_orders_object(), rl_extra_expected],
        },
        rl_postgres_version="16.4",
        rl_init_digest="sha256:init-a0",
    )

    assert rl_result["rl_comparison_status"] == "DRIFT"
    assert "missing_expected_object" in rl_result["rl_reason_codes"]
    assert "duplicate_reference_identity" not in rl_result["rl_reason_codes"]


def test_catalog_unavailable_context_does_not_hide_observed_drift() -> None:
    rl_result = rl_build_catalog_baseline(
        rl_complete_catalog(rl_orders_object(owner="owner-b")),
        rl_reference_for_orders(),
        rl_postgres_version="15.0",
        rl_init_digest="sha256:init-a0",
        rl_catalog_read_error="catalog read failed: secret",
    )

    assert rl_result["rl_comparison_status"] == "BLOCKED"
    assert "reference_version_mismatch" in rl_result["rl_reason_codes"]
    assert "catalog_read_failure" in rl_result["rl_reason_codes"]
    assert "owner_mismatch" in rl_result["rl_reason_codes"]


def test_system_baseline_decision_never_comes_from_name_pg_prefix_or_schema() -> None:
    rl_variants = (
        rl_orders_object(name="orders"),
        rl_orders_object(name="pg_orders"),
        rl_orders_object(schema="pg_catalog", name="pg_orders"),
        rl_orders_object(schema="other_schema", name="orders"),
    )

    for rl_object in rl_variants:
        rl_result = rl_build_catalog_baseline(
            rl_complete_catalog(rl_object),
            rl_reference=None,
        )
        assert rl_result["rl_status"] == "BLOCKED"
        assert rl_result["rl_objects"][0]["rl_expected_system_baseline"] == "BLOCKED"
        assert "reference_missing" in rl_result["rl_reason_codes"]


@pytest.mark.parametrize(
    ("rl_reference", "rl_kwargs", "rl_reason"),
    (
        (None, {}, "reference_missing"),
        (
            rl_reference_for_orders(),
            {"rl_postgres_version": "15.0", "rl_init_digest": "sha256:init-a0"},
            "reference_version_mismatch",
        ),
        (
            rl_reference_for_orders(),
            {"rl_postgres_version": "16.4", "rl_init_digest": "sha256:init-other"},
            "reference_init_mismatch",
        ),
        (
            rl_reference_for_orders(),
            {
                "rl_postgres_version": "16.4",
                "rl_init_digest": "sha256:init-a0",
                "rl_catalog_read_error": "raw catalog error: password=secret",
            },
            "catalog_read_failure",
        ),
    ),
)
def test_reference_and_catalog_read_failures_are_stable_blocking(
    rl_reference: dict[str, object] | None,
    rl_kwargs: dict[str, object],
    rl_reason: str,
) -> None:
    rl_result = rl_build_catalog_baseline(
        rl_complete_catalog(rl_orders_object()),
        rl_reference,
        **rl_kwargs,
    )
    assert rl_result["rl_status"] == "BLOCKED"
    assert rl_reason in rl_result["rl_reason_codes"]
    assert "raw catalog error" not in rl_json.dumps(rl_result)
    assert "secret" not in rl_json.dumps(rl_result)


@pytest.mark.parametrize(
    ("rl_mutation", "rl_reason"),
    (
        (lambda rl_object: {**rl_object, "name": "unexpected"}, "unexpected_identity"),
        (lambda rl_object: {**rl_object, "owner": "owner-b"}, "owner_mismatch"),
        (lambda rl_object: {**rl_object, "acl": ["public=r/owner-b"]}, "acl_mismatch"),
        (lambda rl_object: {**rl_object, "tablespace": "other_space"}, "tablespace_mismatch"),
        (lambda rl_object: {**rl_object, "relkind": "v"}, "relkind_mismatch"),
        (lambda rl_object: {**rl_object, "category": "unknown_category"}, "category_mismatch"),
    ),
)
def test_unexpected_identity_owner_acl_tablespace_class_or_relkind_blocks(
    rl_mutation, rl_reason: str
) -> None:
    rl_result = rl_build_catalog_baseline(
        rl_complete_catalog(rl_mutation(rl_orders_object())),
        rl_reference_for_orders(),
        rl_postgres_version="16.4",
        rl_init_digest="sha256:init-a0",
    )
    assert rl_result["rl_status"] == "BLOCKED"
    assert rl_reason in rl_result["rl_reason_codes"]


@pytest.mark.parametrize(
    ("rl_category", "rl_object"),
    (
        ("relations", {"schema": "public", "name": "v", "relkind": "v"}),
        ("relations", {"schema": "public", "name": "seq", "relkind": "S"}),
        ("procs", {"schema": "public", "name": "fn", "kind": "function"}),
        ("domains", {"schema": "public", "name": "domain_x", "kind": "domain"}),
        ("extensions", {"schema": "public", "name": "extra_extension", "kind": "extension"}),
    ),
)
def test_view_sequence_function_domain_and_extra_extension_are_not_implicitly_system(
    rl_category: str, rl_object: dict[str, object]
) -> None:
    rl_catalog = rl_complete_catalog(rl_orders_object())
    rl_catalog[rl_category] = [rl_object]
    rl_result = rl_build_catalog_baseline(
        rl_catalog,
        rl_reference_for_orders(),
        rl_postgres_version="16.4",
        rl_init_digest="sha256:init-a0",
    )
    assert rl_result["rl_status"] == "BLOCKED"
    assert any(
        rl_reason in rl_result["rl_reason_codes"]
        for rl_reason in (
            "unexpected_identity",
            "unexpected_object",
            "unknown_object_class",
            "category_mismatch",
        )
    )


def test_every_nonrelation_category_requires_an_explicit_allowed_kind() -> None:
    rl_category_kinds = {
        "schemas": "schema",
        "namespaces": "namespace",
        "columns": "column",
        "defaults": "default",
        "indexes": "index",
        "constraints": "constraint",
        "rules": "rule",
        "types": "type",
        "domains": "domain",
        "composites": "composite",
        "enums": "enum",
        "ranges": "range",
        "procs": "function",
        "triggers": "trigger",
        "policies": "policy",
        "extensions": "extension",
        "languages": "language",
        "collations": "collation",
        "fdw": "fdw",
        "servers": "server",
        "user_mappings": "user_mapping",
        "publications": "publication",
        "subscriptions": "subscription",
        "large_objects": "large_object",
        "event_triggers": "event_trigger",
        "text_search": "text_search",
        "casts": "cast",
        "operators": "operator",
        "opclasses": "opclass",
        "opfamilies": "opfamily",
        "transforms": "transform",
        "statistics": "statistics",
        "security_labels": "security_label",
        "ownership": "ownership",
        "acl": "acl",
        "tablespace": "tablespace",
    }
    assert set(rl_category_kinds) == set(RL_REQUIRED_CATALOG_CATEGORIES) - {"relations"}

    for rl_category, rl_kind in rl_category_kinds.items():
        rl_catalog = rl_complete_catalog()
        rl_valid_row = {
            "schema": "public",
            "name": f"{rl_category}_object",
            "category": rl_category,
            "kind": rl_kind,
        }
        if rl_category == "indexes":
            rl_valid_row["relkind"] = "i"
        rl_catalog[rl_category] = [rl_valid_row]
        assert rl_validate_catalog_contract(rl_catalog)["rl_status"] == "VALID"

        rl_invalid_row = {
            "schema": "public",
            "name": f"{rl_category}_object",
            "category": rl_category,
        }
        if rl_category == "indexes":
            rl_invalid_row["relkind"] = "r"
        rl_catalog[rl_category] = [rl_invalid_row]
        rl_invalid = rl_validate_catalog_contract(rl_catalog)
        assert rl_invalid["rl_status"] == "BLOCKED"
        assert any(
            rl_reason in rl_invalid["rl_reason_codes"]
            for rl_reason in ("unknown_object_class", "unknown_relkind")
        )


def test_duplicate_observed_identity_is_blocked_without_exposing_identity_values() -> None:
    rl_result = rl_build_catalog_baseline(
        rl_complete_catalog(rl_orders_object(), rl_orders_object()),
        rl_reference_for_orders(),
        rl_postgres_version="16.4",
        rl_init_digest="sha256:init-a0",
    )

    assert rl_result["rl_comparison_status"] == "BLOCKED"
    assert "duplicate_observed_identity" in rl_result["rl_reason_codes"]
    rl_serialized = rl_json.dumps(rl_result, ensure_ascii=False, sort_keys=True)
    assert "public" not in rl_serialized
    assert "orders" not in rl_serialized


def test_missing_observed_reference_context_blocks_comparison() -> None:
    rl_result = rl_build_catalog_baseline(
        rl_complete_catalog(rl_orders_object()),
        rl_reference_for_orders(),
    )

    assert rl_result["rl_comparison_status"] == "BLOCKED"
    assert "observed_context_missing" in rl_result["rl_reason_codes"]


def test_catalog_baseline_module_is_stdlib_only_and_has_no_action_surface() -> None:
    rl_source = rl_inspect.getsource(rl_module)
    rl_tree = rl_ast.parse(rl_source)
    rl_forbidden_modules = {
        "sqlalchemy",
        "alembic",
        "asyncpg",
        "socket",
        "subprocess",
        "requests",
        "urllib",
        "dotenv",
    }
    for rl_node in rl_ast.walk(rl_tree):
        if isinstance(rl_node, rl_ast.Import):
            assert all(
                rl_alias.name.split(".", 1)[0] not in rl_forbidden_modules
                for rl_alias in rl_node.names
            )
        elif isinstance(rl_node, rl_ast.ImportFrom):
            assert (rl_node.module or "").split(".", 1)[0] not in rl_forbidden_modules
        elif isinstance(rl_node, rl_ast.Call) and isinstance(rl_node.func, rl_ast.Name):
            assert rl_node.func.id not in {"open", "eval", "exec", "compile", "__import__"}
    assert not any(
        isinstance(rl_node, rl_ast.If)
        and isinstance(rl_node.test, rl_ast.Compare)
        and any(
            isinstance(rl_comparator, rl_ast.Constant)
            and rl_comparator.value == "__main__"
            for rl_comparator in rl_node.test.comparators
        )
        for rl_node in rl_tree.body
    )
    assert any(isinstance(rl_node, rl_ast.FunctionDef) for rl_node in rl_tree.body)


def test_reference_authority_blocks_every_object_decision_until_context_is_valid() -> None:
    rl_contexts = (
        {"postgres_version": "16.4", "init_digest": "sha256:init-a0"},
        {"postgres_version": "15.0", "init_digest": "sha256:init-a0"},
        {"postgres_version": "16.4", "init_digest": "sha256:init-other"},
        {
            "postgres_version": "16.4",
            "init_digest": "sha256:init-a0",
            "allowlist": "malformed",
        },
        {
            "postgres_version": "16.4",
            "init_digest": "sha256:init-a0",
            "allowlist": [rl_orders_object(), rl_orders_object()],
        },
    )
    for rl_reference in rl_contexts:
        rl_result = rl_build_catalog_baseline(
            rl_complete_catalog(rl_orders_object()),
            rl_reference,
            rl_postgres_version="16.4",
            rl_init_digest="sha256:init-a0",
        )
        assert rl_result["rl_comparison_status"] == "BLOCKED"
        assert rl_result["rl_objects"][0]["rl_expected_system_baseline"] == "BLOCKED"
        assert all(
            rl_object["rl_expected_system_baseline"] == "BLOCKED"
            for rl_object in rl_result["rl_objects"]
        )


def test_catalog_identity_digest_is_category_aware_and_caller_digests_are_strict() -> None:
    rl_catalog = rl_complete_catalog(
        rl_orders_object(
            category="relations",
            rl_identity_digest="sha256:short",
        )
    )
    rl_result = rl_build_catalog_baseline(
        rl_catalog,
        {
            "postgres_version": "16.4",
            "init_digest": "sha256:init-a0",
            "allowlist": [
                rl_orders_object(
                    category="relations",
                    rl_identity_digest="sha256:short",
                )
            ],
        },
        rl_postgres_version="16.4",
        rl_init_digest="sha256:init-a0",
    )
    rl_object = rl_result["rl_objects"][0]
    assert rl_object["rl_identity_digest"].startswith("sha256:")
    assert len(rl_object["rl_identity_digest"]) == len("sha256:") + 64
    assert rl_object["rl_identity_digest"] != "sha256:short"
    assert "public" not in rl_json.dumps(rl_result)
    assert "orders" not in rl_json.dumps(rl_result)
