"""纯数据 A0 schema reconciliation contract tests。"""

from __future__ import annotations

import ast as rl_ast
import inspect as rl_inspect
import json as rl_json

import pytest

from tools.a0 import rl_reconcile_schema as rl_module
from tools.a0.rl_reconcile_schema import rl_reconcile_schema


def rl_fact(
    rl_schema: str,
    rl_name: str,
    *,
    rl_kind: object = "table",
    rl_fields: object = None,
    rl_constraints: object = None,
    rl_enum: object = None,
    rl_extension: object = None,
    rl_identity: object = None,
    rl_category: object = "relations",
    rl_relkind: object = "r",
    **rl_aliases: object,
) -> dict[str, object]:
    rl_row: dict[str, object] = {
        "schema": rl_schema,
        "name": rl_name,
        "kind": rl_kind,
        "category": rl_category,
    }
    if rl_relkind is not None:
        rl_row["relkind"] = rl_relkind
    if rl_fields is not None:
        rl_row["fields"] = rl_fields
    if rl_constraints is not None:
        rl_row["constraints"] = rl_constraints
    if rl_enum is not None:
        rl_row["enum"] = rl_enum
    if rl_extension is not None:
        rl_row["extension"] = rl_extension
    for rl_alias, rl_value in rl_aliases.items():
        rl_row[rl_alias] = rl_value
    if rl_identity is not None:
        rl_row["identity"] = rl_identity
    return rl_row


def rl_catalog_object(
    rl_schema: str,
    rl_name: str,
    *,
    rl_category: str = "relations",
    rl_relkind: str = "r",
    **rl_fields: object,
) -> dict[str, object]:
    rl_object: dict[str, object] = {
        "schema": rl_schema,
        "name": rl_name,
        "category": rl_category,
        "relkind": rl_relkind,
    }
    rl_object.update(rl_fields)
    return rl_object


def rl_catalog_baseline(
    *rl_objects: dict[str, object],
    rl_status: str = "MATCH",
    rl_comparison_status: str | None = None,
    rl_reason_codes: list[str] | None = None,
) -> dict[str, object]:
    return {
        "rl_schema_version": "a0.catalog-baseline.v2",
        "rl_status": rl_status,
        "rl_comparison_status": rl_comparison_status or rl_status,
        "rl_evidence_status": "BLOCKED",
        "rl_live_status": "BLOCKED",
        "rl_objects": list(rl_objects),
        "rl_reason_codes": list(rl_reason_codes or []),
    }


def test_reconciliation_keeps_the_five_input_regions_separate() -> None:
    rl_input = {
        "alembic": [rl_fact("public", "orders", rl_fields={"id": "integer"})],
        "orm": [rl_fact("public", "orders", rl_fields={"id": "integer"})],
        "deployed": None,
        "catalog_baseline": rl_catalog_baseline(rl_catalog_object("public", "orders")),
        "semantic": {"search": {"rl_relation": "orders"}},
    }

    rl_result = rl_reconcile_schema(rl_input)
    assert rl_result["rl_status"] == "BLOCKED"
    assert set(rl_result["rl_regions"]) == {
        "alembic",
        "orm",
        "deployed",
        "catalog_baseline",
        "semantic",
    }
    assert set(rl_result["rl_columns"]) == {
        "alembic",
        "orm",
        "deployed",
        "catalog_baseline",
        "semantic",
    }
    for rl_region_name, rl_region in rl_result["rl_regions"].items():
        assert rl_region["rl_source"] == rl_region_name
        assert "rl_facts" in rl_region
    assert "search" not in rl_json.dumps(rl_result)
    assert "orders" not in rl_json.dumps(rl_result)


def test_deployed_is_unavailable_by_default_and_static_facts_never_become_deployed() -> None:
    rl_result = rl_reconcile_schema(
        {
            "alembic": [rl_fact("public", "migration_only")],
            "orm": [rl_fact("public", "orm_only")],
            "semantic": [{"name": "semantic_only"}],
        }
    )

    assert rl_result["rl_regions"]["deployed"]["rl_status"] == "BLOCKED"
    assert rl_result["rl_regions"]["deployed"]["rl_facts"] == []
    assert "deployed_unavailable" in rl_result["rl_reason_codes"]
    assert "migration_only" in rl_result["rl_reason_codes"]
    assert "orm_only" in rl_result["rl_reason_codes"]
    assert "unresolved_static_only" in rl_result["rl_reason_codes"]


def test_explicit_deployed_facts_are_not_augmented_by_orm_or_alembic() -> None:
    rl_deployed_fact = rl_fact("public", "deployed_only")
    rl_result = rl_reconcile_schema(
        {
            "alembic": [rl_fact("public", "migration_only")],
            "orm": [rl_fact("public", "orm_only")],
            "deployed": {
                "rl_status": "AVAILABLE",
                "rl_facts": [rl_deployed_fact],
            },
        }
    )

    assert rl_result["rl_regions"]["deployed"]["rl_status"] == "AVAILABLE"
    assert len(rl_result["rl_regions"]["deployed"]["rl_facts"]) == 1
    assert "deployed_only" in rl_result["rl_reason_codes"]
    assert "migration_only" in rl_result["rl_reason_codes"]
    assert "orm_only" in rl_result["rl_reason_codes"]


def test_static_only_inputs_are_blocking_and_do_not_claim_a_live_snapshot() -> None:
    rl_result = rl_reconcile_schema(
        {
            "alembic": [rl_fact("public", "orders")],
            "orm": [rl_fact("public", "orders")],
            "catalog_baseline": rl_catalog_baseline(
                rl_catalog_object("public", "orders")
            ),
        }
    )
    rl_serialized = rl_json.dumps(rl_result, ensure_ascii=False, sort_keys=True)
    assert rl_result["rl_status"] == "BLOCKED"
    assert rl_result["rl_comparison_status"] == "BLOCKED"
    assert rl_result["rl_evidence_status"] == "BLOCKED"
    assert rl_result["rl_live_status"] == "BLOCKED"
    assert rl_result["rl_regions"]["catalog_baseline"]["rl_status"] == "MATCH"
    assert "deployed_unavailable" in rl_result["rl_reason_codes"]
    assert "snapshot" not in rl_serialized.lower()
    assert "schema_signature" not in rl_serialized.lower()
    assert "live_ready" not in rl_serialized.lower()
    assert "pass" not in rl_serialized.lower()


@pytest.mark.parametrize(
    ("rl_field", "rl_reason"),
    (
        ("fields", "field_drift"),
        ("columns", "column_drift"),
        ("default", "default_drift"),
        ("indexes", "index_drift"),
        ("constraints", "constraint_drift"),
        ("rules", "rule_drift"),
        ("types", "type_drift"),
        ("domains", "domain_drift"),
        ("composites", "composite_drift"),
        ("enum", "enum_drift"),
        ("extension", "extension_drift"),
        ("owner", "owner_drift"),
        ("acl", "acl_drift"),
        ("tablespace", "tablespace_drift"),
        ("definition", "definition_drift"),
    ),
)
def test_available_deployed_facts_report_drift_by_stable_reason_code(
    rl_field: str, rl_reason: str
) -> None:
    rl_alembic_fact = rl_fact(
        "public",
        "orders",
        **{rl_field: {"expected": "one"}},
    )
    rl_orm_fact = rl_fact(
        "public",
        "orders",
        **{rl_field: {"expected": "one"}},
    )
    rl_deployed_fact = rl_fact(
        "public",
        "orders",
        **{rl_field: {"observed": "two"}},
    )
    rl_result = rl_reconcile_schema(
        {
            "alembic": [rl_alembic_fact],
            "orm": [rl_orm_fact],
            "deployed": {"rl_status": "AVAILABLE", "rl_facts": [rl_deployed_fact]},
        }
    )
    assert rl_result["rl_status"] == "BLOCKED"
    assert rl_reason in rl_result["rl_reason_codes"]


def test_same_name_identity_mismatch_is_not_tunneled_into_a_match() -> None:
    rl_result = rl_reconcile_schema(
        {
            "orm": [rl_fact("public", "orders", rl_identity="orm-id")],
            "deployed": {
                "rl_status": "AVAILABLE",
                "rl_facts": [rl_fact("public", "orders", rl_identity="deployed-id")],
            },
        }
    )
    assert rl_result["rl_status"] == "BLOCKED"
    assert "same_name_identity_mismatch" in rl_result["rl_reason_codes"]


def test_unknown_category_relkind_catalog_failure_and_baseline_mismatch_block() -> None:
    rl_result = rl_reconcile_schema(
        {
            "deployed": {
                "rl_status": "AVAILABLE",
                "rl_facts": [
                    rl_fact(
                        "public",
                        "mystery",
                        rl_category="mystery_category",
                        rl_relkind="X",
                    )
                ],
            },
            "catalog_baseline": rl_catalog_baseline(
                rl_catalog_object(
                    "public",
                    "mystery",
                    rl_category="mystery_category",
                    rl_relkind="X",
                ),
                rl_status="BLOCKED",
                rl_comparison_status="DRIFT",
                rl_reason_codes=[
                    "catalog_read_failure",
                    "baseline_mismatch",
                ],
            ),
        }
    )
    assert rl_result["rl_status"] == "BLOCKED"
    for rl_reason in (
        "unknown_object_category",
        "unknown_relkind",
        "catalog_read_failure",
        "baseline_mismatch",
    ):
        assert rl_reason in rl_result["rl_reason_codes"]


def test_catalog_baseline_object_level_reasons_propagate_to_region_and_global_output() -> None:
    rl_result = rl_reconcile_schema(
        {
            "catalog_baseline": rl_catalog_baseline(
                rl_catalog_object(
                    "public",
                    "orders",
                    rl_reason_codes=["owner_mismatch", "unexpected_object"],
                ),
                rl_status="BLOCKED",
                rl_comparison_status="DRIFT",
            )
        }
    )

    assert "owner_mismatch" in rl_result["rl_reason_codes"]
    assert "unexpected_object" in rl_result["rl_reason_codes"]
    assert "owner_mismatch" in rl_result["rl_regions"]["catalog_baseline"]["rl_reason_codes"]


def test_baseline_unavailable_reason_does_not_hide_object_level_drift() -> None:
    rl_result = rl_reconcile_schema(
        {
            "catalog_baseline": rl_catalog_baseline(
                rl_catalog_object(
                    "public",
                    "orders",
                    rl_reason_codes=["owner_mismatch", "unknown_relkind"],
                ),
                rl_status="BLOCKED",
                rl_comparison_status="BLOCKED",
                rl_reason_codes=["catalog_read_failure", "reference_missing"],
            ),
            "deployed": None,
        }
    )

    for rl_reason in (
        "catalog_read_failure",
        "reference_missing",
        "owner_mismatch",
        "unknown_relkind",
        "catalog_baseline_unavailable",
        "deployed_unavailable",
    ):
        assert rl_reason in rl_result["rl_reason_codes"]


def test_all_postgresql_relkinds_are_case_sensitive_in_reconciliation() -> None:
    for rl_relkind in ("r", "i", "S", "t", "v", "m", "c", "f", "p", "I"):
        rl_result = rl_reconcile_schema(
            {
                "deployed": {
                    "rl_status": "AVAILABLE",
                    "rl_facts": [rl_fact("public", "object", rl_relkind=rl_relkind)],
                }
            }
        )
        assert "unknown_relkind" not in rl_result["rl_reason_codes"]

    for rl_relkind in (None, "", "s", "x", "rr", 1):
        rl_row = rl_fact("public", "object", rl_relkind=None)
        if rl_relkind is not None:
            rl_row["relkind"] = rl_relkind
        rl_result = rl_reconcile_schema(
            {
                "deployed": {"rl_status": "AVAILABLE", "rl_facts": [rl_row]},
            }
        )
        assert "unknown_relkind" in rl_result["rl_reason_codes"]


def test_reconciliation_module_is_stdlib_only_and_has_no_action_surface() -> None:
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


def test_reconciler_consumes_producer_comparison_status_without_promoting_top_level_blocked() -> None:
    for rl_comparison_status in ("MATCH", "DRIFT", "BLOCKED"):
        rl_result = rl_reconcile_schema(
            {
                "catalog_baseline": rl_catalog_baseline(
                    rl_catalog_object("public", "orders"),
                    rl_status="BLOCKED",
                    rl_comparison_status=rl_comparison_status,
                )
            }
        )
        assert rl_result["rl_status"] == "BLOCKED"
        assert rl_result["rl_evidence_status"] == "BLOCKED"
        assert rl_result["rl_live_status"] == "BLOCKED"
        assert rl_result["rl_regions"]["catalog_baseline"]["rl_status"] == rl_comparison_status

    rl_missing = rl_reconcile_schema(
        {
            "catalog_baseline": {
                "rl_schema_version": "a0.catalog-baseline.v2",
                "rl_status": "BLOCKED",
                "rl_evidence_status": "BLOCKED",
                "rl_live_status": "BLOCKED",
                "rl_objects": [],
            }
        }
    )
    assert rl_missing["rl_regions"]["catalog_baseline"]["rl_status"] == "BLOCKED"
    assert rl_missing["rl_comparison_status"] == "BLOCKED"


def test_nonrelation_relkind_is_not_applicable_but_relation_and_index_require_mapping() -> None:
    for rl_category in ("schemas", "columns", "types", "extensions"):
        rl_result = rl_reconcile_schema(
            {
                "deployed": {
                    "rl_status": "AVAILABLE",
                    "rl_facts": [
                        rl_fact(
                            "public",
                            f"{rl_category}_object",
                            rl_category=rl_category,
                            rl_relkind=None,
                            rl_kind=rl_category[:-1] if rl_category != "types" else "type",
                        )
                    ],
                }
            }
        )
        assert "unknown_relkind" not in rl_result["rl_reason_codes"]

    for rl_category in ("relations", "indexes"):
        rl_result = rl_reconcile_schema(
            {
                "deployed": {
                    "rl_status": "AVAILABLE",
                    "rl_facts": [
                        rl_fact(
                            "public",
                            f"{rl_category}_object",
                            rl_category=rl_category,
                            rl_relkind=None,
                        )
                    ],
                }
            }
        )
        assert "unknown_relkind" in rl_result["rl_reason_codes"]


def test_identity_digest_binds_category_parent_and_overload_discriminators_without_leakage() -> None:
    rl_result = rl_reconcile_schema(
        {
            "orm": [
                rl_fact(
                    "public",
                    "same_name",
                    rl_category="columns",
                    rl_relkind=None,
                    rl_kind="column",
                    parent="parent_a",
                    ordinal=1,
                    signature="credential-shaped:rl_secret",
                ),
                rl_fact(
                    "public",
                    "same_name",
                    rl_category="columns",
                    rl_relkind=None,
                    rl_kind="column",
                    parent="parent_b",
                    ordinal=1,
                    signature="credential-shaped:rl_secret",
                ),
                rl_fact(
                    "public",
                    "run",
                    rl_category="procs",
                    rl_relkind=None,
                    rl_kind="function",
                    arguments=["integer"],
                ),
                rl_fact(
                    "public",
                    "run",
                    rl_category="procs",
                    rl_relkind=None,
                    rl_kind="function",
                    arguments=["text"],
                ),
            ]
        }
    )
    rl_serialized = rl_json.dumps(rl_result, ensure_ascii=False, sort_keys=True)
    assert "same_name_identity_mismatch" not in rl_result["rl_reason_codes"]
    assert "parent_a" not in rl_serialized
    assert "parent_b" not in rl_serialized
    assert "credential-shaped:rl_secret" not in rl_serialized
    assert "integer" not in rl_serialized
    assert "text" not in rl_serialized


def test_invalid_reason_category_kind_and_digest_are_canonicalized_without_echo() -> None:
    rl_result = rl_reconcile_schema(
        {
            "deployed": {
                "rl_status": "AVAILABLE",
                "rl_reason_codes": ["raw-schema-name", "postgres://user:password@host/db"],
                "rl_facts": [
                    rl_fact(
                        "public",
                        "orders",
                        category="untrusted-category",
                        kind="untrusted-kind",
                        relkind="x",
                        rl_identity_digest="sha256:short",
                        reason_codes=["SELECT secret FROM credentials"],
                    )
                ],
            }
        }
    )
    rl_serialized = rl_json.dumps(rl_result, ensure_ascii=False, sort_keys=True)
    for rl_secret in (
        "raw-schema-name",
        "postgres://user:password@host/db",
        "untrusted-category",
        "untrusted-kind",
        "SELECT secret FROM credentials",
        "public",
        "orders",
    ):
        assert rl_secret not in rl_serialized
    assert "unknown_object_category" in rl_result["rl_reason_codes"]
    assert "unknown_relkind" in rl_result["rl_reason_codes"]
    assert "unknown_object_class" in rl_result["rl_reason_codes"]
