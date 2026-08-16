"""Deterministic, digest-only catalog baseline contracts.

This module deliberately contains only standard-library data transformations.
It never discovers a database, creates a connection, or writes an artifact.
"""

from __future__ import annotations

import hashlib as rl_hashlib
import json as rl_json
from collections.abc import Mapping as rl_Mapping
from collections.abc import Sequence as rl_Sequence
from typing import Any as rl_Any


RL_RELKIND_MAPPING: dict[str, str] = {
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


RL_REQUIRED_CATALOG_CATEGORIES: tuple[str, ...] = (
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
)


_RL_CATEGORY_CLASS: dict[str, str] = {
    "schemas": "schema",
    "namespaces": "namespace",
    "relations": "relation",
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
    "procs": "proc",
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


_RL_ALLOWED_NONRELATION_KINDS: dict[str, set[str]] = {
    "schemas": {"schema"},
    "namespaces": {"namespace"},
    "columns": {"column"},
    "defaults": {"default"},
    "constraints": {"constraint"},
    "rules": {"rule"},
    "types": {"type", "base", "enum", "range", "composite"},
    "domains": {"domain"},
    "composites": {"composite"},
    "enums": {"enum"},
    "ranges": {"range"},
    "procs": {"function", "procedure", "aggregate", "window"},
    "triggers": {"trigger"},
    "policies": {"policy"},
    "extensions": {"extension"},
    "languages": {"language"},
    "collations": {"collation"},
    "fdw": {"fdw"},
    "servers": {"server"},
    "user_mappings": {"user_mapping"},
    "publications": {"publication"},
    "subscriptions": {"subscription"},
    "large_objects": {"large_object"},
    "event_triggers": {"event_trigger"},
    "text_search": {"text_search"},
    "casts": {"cast"},
    "operators": {"operator"},
    "opclasses": {"opclass"},
    "opfamilies": {"opfamily"},
    "transforms": {"transform"},
    "statistics": {"statistics"},
    "security_labels": {"security_label"},
    "ownership": {"ownership"},
    "acl": {"acl"},
    "tablespace": {"tablespace"},
}

_RL_RELKIND_CATEGORY_ALLOWLIST: dict[str, set[str]] = {
    "indexes": {"i", "I"},
}


_RL_RELATION_CATEGORY_RELKINDS: dict[str, set[str]] = {
    "relations": set(RL_RELKIND_MAPPING),
    "indexes": {"i", "I"},
}


_RL_DIGEST_FIELDS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("fields", ("fields", "rl_fields"), "field_mismatch"),
    ("columns", ("columns", "rl_columns"), "column_mismatch"),
    ("default", ("default", "default_expression", "rl_default"), "default_mismatch"),
    ("indexes", ("indexes", "rl_indexes"), "index_mismatch"),
    ("constraints", ("constraints", "rl_constraints"), "constraint_mismatch"),
    ("rules", ("rules", "rl_rules"), "rule_mismatch"),
    ("types", ("types", "rl_types"), "type_mismatch"),
    ("domains", ("domains", "rl_domains"), "domain_mismatch"),
    ("composites", ("composites", "rl_composites"), "composite_mismatch"),
    ("enums", ("enums", "enum", "rl_enums"), "enum_mismatch"),
    ("extensions", ("extensions", "extension", "rl_extensions"), "extension_mismatch"),
    ("owner", ("owner", "rl_owner"), "owner_mismatch"),
    ("acl", ("acl", "privileges", "rl_acl"), "acl_mismatch"),
    ("tablespace", ("tablespace", "rl_tablespace"), "tablespace_mismatch"),
    ("definition", ("definition", "sql", "rl_definition"), "definition_mismatch"),
)


def _rl_sortable_value(rl_value: rl_Any) -> rl_Any:
    """Recursively make JSON-compatible values and order-independent lists."""

    if isinstance(rl_value, rl_Mapping):
        rl_items = {
            str(rl_key): _rl_sortable_value(rl_item)
            for rl_key, rl_item in rl_value.items()
        }
        return {rl_key: rl_items[rl_key] for rl_key in sorted(rl_items)}
    if isinstance(rl_value, (list, tuple, set, frozenset)):
        rl_items = [_rl_sortable_value(rl_item) for rl_item in rl_value]
        return sorted(
            rl_items,
            key=lambda rl_item: rl_json.dumps(
                rl_item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )
    if rl_value is None or isinstance(rl_value, (str, int, bool)):
        return rl_value
    if isinstance(rl_value, float):
        if rl_value != rl_value or rl_value in (float("inf"), float("-inf")):
            raise ValueError("non_finite_number")
        return rl_value
    raise TypeError("non_json_value")


def rl_canonical_json(rl_value: rl_Any) -> str:
    """Return deterministic canonical JSON with order-independent collections."""

    return rl_json.dumps(
        _rl_sortable_value(rl_value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def rl_sha256_digest(rl_value: rl_Any) -> str:
    """Return only a SHA-256 digest of a canonical JSON value."""

    rl_payload = rl_canonical_json(rl_value).encode("utf-8")
    return "sha256:" + rl_hashlib.sha256(rl_payload).hexdigest()


def rl_classify_relkind(rl_relkind: rl_Any) -> dict[str, rl_Any]:
    """Classify exactly one PostgreSQL relation kind, failing closed."""

    if isinstance(rl_relkind, str) and rl_relkind in RL_RELKIND_MAPPING:
        return {
            "rl_status": "known",
            "rl_blocking": False,
            "rl_object_kind": RL_RELKIND_MAPPING[rl_relkind],
            "rl_reason_codes": [],
        }
    return {
        "rl_status": "BLOCKED",
        "rl_blocking": True,
        "rl_object_kind": "unknown",
        "rl_reason_codes": ["unknown_relkind"],
    }


def _rl_row_shape_reasons(rl_category: str, rl_row: rl_Any) -> list[str]:
    if not isinstance(rl_row, rl_Mapping):
        return ["invalid_row", "invalid_object"]

    rl_reasons: list[str] = []
    rl_row_category_present, rl_row_category = _rl_first(rl_row, "category", "rl_category")
    if not rl_row_category_present or rl_row_category != rl_category:
        rl_reasons.append("category_mismatch")
    _, rl_identity_valid = _rl_identity_digest(rl_row)
    if not rl_identity_valid:
        rl_reasons.append("invalid_identity")
    if rl_category == "relations":
        rl_relkind_present, rl_relkind = _rl_first(rl_row, "relkind", "rl_relkind")
        if (
            not rl_relkind_present
            or not isinstance(rl_relkind, str)
            or rl_relkind not in RL_RELKIND_MAPPING
        ):
            rl_reasons.append("unknown_relkind")
    elif rl_category in _RL_RELKIND_CATEGORY_ALLOWLIST:
        rl_relkind_present, rl_relkind = _rl_first(rl_row, "relkind", "rl_relkind")
        if (
            not rl_relkind_present
            or not isinstance(rl_relkind, str)
            or rl_relkind not in _RL_RELKIND_CATEGORY_ALLOWLIST[rl_category]
        ):
            rl_reasons.append("unknown_relkind")
    elif rl_category in _RL_ALLOWED_NONRELATION_KINDS:
        rl_kind_present, rl_kind = _rl_first(
            rl_row,
            "kind",
            "object_kind",
            "rl_kind",
            "class",
            "object_class",
            "rl_class",
        )
        if (
            not rl_kind_present
            or not isinstance(rl_kind, str)
            or rl_kind not in _RL_ALLOWED_NONRELATION_KINDS[rl_category]
        ):
            rl_reasons.append("unknown_object_class")
    return sorted(set(rl_reasons))


def rl_validate_catalog_contract(rl_catalog: rl_Any) -> dict[str, rl_Any]:
    """Validate the complete category surface without inspecting live state."""

    if not isinstance(rl_catalog, rl_Mapping):
        return {
            "rl_status": "BLOCKED",
            "rl_missing_categories": list(RL_REQUIRED_CATALOG_CATEGORIES),
            "rl_invalid_categories": [],
            "rl_reason_codes": ["catalog_not_mapping", "catalog_contract_incomplete"],
        }

    rl_missing_categories = [
        rl_category
        for rl_category in RL_REQUIRED_CATALOG_CATEGORIES
        if rl_category not in rl_catalog
    ]
    rl_invalid_categories = [
        rl_category
        for rl_category in RL_REQUIRED_CATALOG_CATEGORIES
        if rl_category in rl_catalog
        and not isinstance(rl_catalog[rl_category], (list, tuple))
    ]
    rl_reason_codes: list[str] = []
    if rl_missing_categories:
        rl_reason_codes.extend(["missing_category", "catalog_contract_incomplete"])
    if rl_invalid_categories:
        rl_reason_codes.extend(["category_not_collection", "catalog_contract_incomplete"])
    for rl_category in RL_REQUIRED_CATALOG_CATEGORIES:
        if rl_category not in rl_catalog or not isinstance(rl_catalog[rl_category], (list, tuple)):
            continue
        for rl_row in rl_catalog[rl_category]:
            rl_row_reasons = _rl_row_shape_reasons(rl_category, rl_row)
            if rl_row_reasons:
                if rl_category not in rl_invalid_categories:
                    rl_invalid_categories.append(rl_category)
                rl_reason_codes.extend(rl_row_reasons)
    return {
        "rl_status": "VALID" if not rl_reason_codes else "BLOCKED",
        "rl_missing_categories": rl_missing_categories,
        "rl_invalid_categories": rl_invalid_categories,
        "rl_reason_codes": sorted(set(rl_reason_codes)),
    }


def _rl_first(rl_row: rl_Mapping[str, rl_Any], *rl_keys: str) -> tuple[bool, rl_Any]:
    for rl_key in rl_keys:
        if rl_key in rl_row:
            return True, rl_row[rl_key]
    return False, None


def _rl_digest_field(
    rl_row: rl_Mapping[str, rl_Any],
    rl_field_name: str,
    *rl_keys: str,
) -> str:
    rl_present, rl_value = _rl_first(rl_row, *rl_keys)
    if not rl_present:
        return rl_sha256_digest({"rl_missing_field": rl_field_name})
    if rl_value is None:
        return rl_sha256_digest({"rl_null_field": rl_field_name})
    try:
        return rl_sha256_digest(rl_value)
    except (TypeError, ValueError):
        return rl_sha256_digest({"rl_invalid_field": rl_field_name})


def _rl_identity_digest(rl_row: rl_Mapping[str, rl_Any]) -> tuple[str, bool]:
    rl_schema_present, rl_schema = _rl_first(rl_row, "schema", "namespace", "rl_schema")
    rl_name_present, rl_name = _rl_first(rl_row, "name", "object_name", "rl_name")
    rl_valid = (
        rl_schema_present
        and rl_name_present
        and isinstance(rl_schema, str)
        and isinstance(rl_name, str)
        and bool(rl_schema)
        and bool(rl_name)
    )
    if rl_valid:
        return rl_sha256_digest({"schema": rl_schema, "name": rl_name}), True
    return rl_sha256_digest({"rl_invalid_identity": True}), False


def _rl_relation_kind(rl_row: rl_Mapping[str, rl_Any]) -> tuple[str | None, str, list[str]]:
    rl_present, rl_relkind = _rl_first(rl_row, "relkind", "rl_relkind")
    if not rl_present:
        rl_relkind = None
    rl_result = rl_classify_relkind(rl_relkind)
    if rl_result["rl_status"] == "known":
        return rl_relkind, rl_result["rl_object_kind"], []
    return "unknown", "unknown", list(rl_result["rl_reason_codes"])


def _rl_nonrelation_kind(rl_category: str, rl_row: rl_Mapping[str, rl_Any]) -> tuple[str, list[str]]:
    rl_present, rl_kind = _rl_first(
        rl_row,
        "kind",
        "object_kind",
        "rl_kind",
        "class",
        "object_class",
        "rl_class",
    )
    if rl_category not in RL_REQUIRED_CATALOG_CATEGORIES:
        return "unknown", ["unknown_object_category"]
    if rl_category in _RL_RELKIND_CATEGORY_ALLOWLIST:
        rl_relkind_present, rl_relkind = _rl_first(rl_row, "relkind", "rl_relkind")
        if (
            rl_relkind_present
            and isinstance(rl_relkind, str)
            and rl_relkind in _RL_RELKIND_CATEGORY_ALLOWLIST[rl_category]
        ):
            return rl_relkind, []
        return "unknown", ["unknown_relkind"]
    if rl_category in _RL_ALLOWED_NONRELATION_KINDS and rl_present:
        if isinstance(rl_kind, str) and rl_kind in _RL_ALLOWED_NONRELATION_KINDS[rl_category]:
            return rl_kind, []
        return "unknown", ["unknown_object_class"]
    return "unknown", ["unknown_object_class"]


def _rl_prepare_object(
    rl_category: str,
    rl_row: rl_Any,
) -> tuple[dict[str, rl_Any], list[str], str]:
    rl_reason_codes: list[str] = []
    if not isinstance(rl_row, rl_Mapping):
        rl_reason_codes.extend(["invalid_object", "unexpected_object"])
        rl_row_mapping: rl_Mapping[str, rl_Any] = {}
    else:
        rl_row_mapping = rl_row

    rl_outer_category_known = rl_category in RL_REQUIRED_CATALOG_CATEGORIES
    if not rl_outer_category_known:
        rl_reason_codes.append("unknown_object_category")
    rl_reason_codes.extend(_rl_row_shape_reasons(rl_category, rl_row))

    rl_identity, rl_identity_valid = _rl_identity_digest(rl_row_mapping)
    rl_identity_token_digest = None
    if isinstance(rl_row_mapping, rl_Mapping):
        rl_identity_token_present, rl_identity_token = _rl_first(
            rl_row_mapping,
            "identity",
            "rl_identity",
        )
        if rl_identity_token_present:
            try:
                rl_identity_token_digest = rl_sha256_digest(rl_identity_token)
            except (TypeError, ValueError):
                rl_identity_token_digest = rl_sha256_digest({"rl_invalid_identity_token": True})
    if not rl_identity_valid:
        rl_reason_codes.append("invalid_identity")

    if rl_category == "relations":
        rl_relkind, rl_object_kind, rl_relkind_reasons = _rl_relation_kind(rl_row_mapping)
        rl_reason_codes.extend(rl_relkind_reasons)
        rl_class = "relation"
    else:
        rl_relkind = None
        rl_object_kind, rl_kind_reasons = _rl_nonrelation_kind(rl_category, rl_row_mapping)
        rl_reason_codes.extend(rl_kind_reasons)
        rl_class = _RL_CATEGORY_CLASS.get(rl_category, "unknown")
        if rl_category in _RL_RELKIND_CATEGORY_ALLOWLIST:
            rl_relkind = rl_object_kind
            if rl_relkind in RL_RELKIND_MAPPING:
                rl_object_kind = RL_RELKIND_MAPPING[rl_relkind]

    rl_object = {
        "rl_category": rl_category if rl_outer_category_known else "unknown",
        "rl_class": rl_class,
        "rl_identity_digest": rl_identity,
        "rl_identity_token_digest": rl_identity_token_digest,
        "rl_relkind": rl_relkind,
        "rl_object_kind": rl_object_kind,
        **{
            f"rl_{rl_field_name}_digest": _rl_digest_field(
                rl_row_mapping,
                rl_field_name,
                *rl_keys,
            )
            for rl_field_name, rl_keys, _ in _RL_DIGEST_FIELDS
        },
        "rl_expected_system_baseline": "BLOCKED",
        "rl_reason_codes": sorted(set(rl_reason_codes)),
    }
    return rl_object, sorted(set(rl_reason_codes)), rl_identity


def _rl_reference_value(rl_reference: rl_Mapping[str, rl_Any], *rl_keys: str) -> tuple[bool, rl_Any]:
    for rl_key in rl_keys:
        if rl_key in rl_reference:
            return True, rl_reference[rl_key]
    return False, None


def _rl_reference_signature(
    rl_category: str,
    rl_row: rl_Any,
) -> tuple[dict[str, rl_Any], list[str], str]:
    if isinstance(rl_row, rl_Mapping):
        rl_row_category_present, rl_row_category = _rl_first(
            rl_row,
            "category",
            "rl_category",
        )
        if rl_row_category_present and isinstance(rl_row_category, str):
            rl_category = rl_row_category
    return _rl_prepare_object(rl_category, rl_row)


def _rl_compare_reference_entry(
    rl_observed: dict[str, rl_Any],
    rl_observed_row: rl_Any,
    rl_category: str,
    rl_allowlist: list[rl_Any],
) -> tuple[str, list[str], int | None]:
    rl_matches: list[tuple[int, dict[str, rl_Any], list[str]]] = []
    for rl_index, rl_expected_row in enumerate(rl_allowlist):
        rl_expected_category = rl_category
        if isinstance(rl_expected_row, rl_Mapping):
            rl_expected_category_present, rl_expected_category_value = _rl_first(
                rl_expected_row,
                "category",
                "rl_category",
            )
            if rl_expected_category_present and isinstance(rl_expected_category_value, str):
                rl_expected_category = rl_expected_category_value
        rl_expected, rl_expected_reasons, _ = _rl_reference_signature(
            rl_expected_category,
            rl_expected_row,
        )
        if rl_expected["rl_identity_digest"] == rl_observed["rl_identity_digest"]:
            rl_matches.append((rl_index, rl_expected, rl_expected_reasons))

    if not rl_matches:
        return "BLOCKED", ["unexpected_identity", "unexpected_object"], None

    rl_index, rl_expected, rl_expected_reasons = rl_matches[0]
    rl_reason_codes = list(rl_expected_reasons)
    if rl_expected["rl_category"] != rl_observed["rl_category"]:
        rl_reason_codes.append("category_mismatch")
    if rl_expected["rl_class"] != rl_observed["rl_class"]:
        rl_reason_codes.append("class_mismatch")
    if rl_expected["rl_relkind"] != rl_observed["rl_relkind"]:
        rl_reason_codes.append("relkind_mismatch")
    for rl_field_name, _, rl_reason_code in _RL_DIGEST_FIELDS:
        rl_field_name = f"rl_{rl_field_name}_digest"
        if rl_expected[rl_field_name] != rl_observed[rl_field_name]:
            rl_reason_codes.append(rl_reason_code)

    if rl_reason_codes:
        return "DRIFT", sorted(set(rl_reason_codes)), rl_index
    return "EXPECTED", [], rl_index


def _rl_reference_context(
    rl_reference: rl_Any,
    rl_postgres_version: str | None,
    rl_init_digest: str | None,
) -> tuple[list[rl_Any], list[str], bool]:
    if not isinstance(rl_reference, rl_Mapping):
        return [], ["reference_missing"], False

    rl_reason_codes: list[str] = []
    if rl_postgres_version is None or rl_init_digest is None:
        rl_reason_codes.append("observed_context_missing")
    rl_reference_version_present, rl_reference_version = _rl_reference_value(
        rl_reference,
        "postgres_version",
        "rl_postgres_version",
    )
    rl_reference_init_present, rl_reference_init = _rl_reference_value(
        rl_reference,
        "init_digest",
        "rl_init_digest",
    )
    rl_allowlist_present, rl_allowlist = _rl_reference_value(
        rl_reference,
        "allowlist",
        "objects",
        "rl_allowlist",
    )

    if not rl_reference_version_present:
        rl_reason_codes.append("reference_version_missing")
    elif rl_postgres_version is not None and rl_postgres_version != rl_reference_version:
        rl_reason_codes.append("reference_version_mismatch")

    if not rl_reference_init_present:
        rl_reason_codes.append("reference_init_missing")
    elif rl_init_digest is not None and rl_init_digest != rl_reference_init:
        rl_reason_codes.append("reference_init_mismatch")

    if not rl_allowlist_present or not isinstance(rl_allowlist, list):
        rl_reason_codes.extend(["reference_allowlist_invalid", "malformed_allowlist"])
        rl_allowlist = []
    else:
        rl_identity_digests: list[str] = []
        for rl_expected_row in rl_allowlist:
            if not isinstance(rl_expected_row, rl_Mapping):
                rl_reason_codes.extend(["malformed_allowlist", "invalid_row"])
                continue
            rl_expected_category_present, rl_expected_category = _rl_first(
                rl_expected_row,
                "category",
                "rl_category",
            )
            if not rl_expected_category_present or not isinstance(rl_expected_category, str):
                rl_reason_codes.extend(["malformed_allowlist", "category_mismatch"])
                continue
            rl_expected, rl_expected_reasons, rl_identity = _rl_reference_signature(
                rl_expected_category,
                rl_expected_row,
            )
            rl_reason_codes.extend(rl_expected_reasons)
            if rl_expected_reasons:
                rl_reason_codes.append("malformed_allowlist")
            if not rl_expected["rl_identity_digest"] or rl_identity in rl_identity_digests:
                rl_reason_codes.append("duplicate_reference_identity")
            rl_identity_digests.append(rl_identity)

    return list(rl_allowlist), sorted(set(rl_reason_codes)), not rl_reason_codes


def rl_build_catalog_baseline(
    rl_catalog: rl_Any,
    rl_reference: rl_Any = None,
    *,
    rl_postgres_version: str | None = None,
    rl_init_digest: str | None = None,
    rl_catalog_read_error: rl_Any = None,
) -> dict[str, rl_Any]:
    """Build a static comparison result while keeping live status blocked."""

    rl_validation = rl_validate_catalog_contract(rl_catalog)
    rl_reason_codes = list(rl_validation["rl_reason_codes"])
    if rl_catalog_read_error is not None:
        rl_reason_codes.append("catalog_read_failure")

    rl_reference_allowlist, rl_reference_reasons, rl_reference_ready = _rl_reference_context(
        rl_reference,
        rl_postgres_version,
        rl_init_digest,
    )
    rl_reason_codes.extend(rl_reference_reasons)

    rl_objects: list[dict[str, rl_Any]] = []
    rl_object_records: list[tuple[str, rl_Any, dict[str, rl_Any], list[str]]] = []
    rl_observed_identity_counts: dict[tuple[str, str], int] = {}
    rl_catalog_mapping = rl_catalog if isinstance(rl_catalog, rl_Mapping) else {}
    for rl_category in sorted(
        [
            rl_category
            for rl_category in rl_catalog_mapping
            if isinstance(rl_category, str)
        ]
    ):
        if rl_category not in RL_REQUIRED_CATALOG_CATEGORIES:
            rl_reason_codes.append("unexpected_category")
            continue
        rl_rows = rl_catalog_mapping[rl_category]
        if not isinstance(rl_rows, (list, tuple)):
            continue
        for rl_row in rl_rows:
            rl_object, rl_row_reasons, rl_identity = _rl_prepare_object(rl_category, rl_row)
            rl_objects.append(rl_object)
            rl_object_records.append((rl_category, rl_row, rl_object, rl_row_reasons))
            rl_reason_codes.extend(rl_row_reasons)
            rl_identity_key = (rl_category, rl_identity)
            rl_observed_identity_counts[rl_identity_key] = (
                rl_observed_identity_counts.get(rl_identity_key, 0) + 1
            )

    rl_reason_codes.extend(
        "duplicate_observed_identity"
        for rl_identity_count in rl_observed_identity_counts.values()
        if rl_identity_count > 1
    )

    rl_seen_reference_indexes: set[int] = set()
    # 为什么：allowlist 缺失/格式错时 reference authority 不成立，任何 object 决策
    # 都必须 BLOCKED；但 version/init mismatch 不掩盖 observed DRIFT（仍要比较）。
    rl_allowlist_unusable = (
        "reference_allowlist_invalid" in rl_reason_codes
        or "malformed_allowlist" in rl_reason_codes
        or "duplicate_reference_identity" in rl_reason_codes
        or "invalid_row" in rl_reason_codes
    )
    for rl_category, rl_row, rl_object, rl_row_reasons in rl_object_records:
        if not isinstance(rl_reference, rl_Mapping) or rl_allowlist_unusable:
            rl_object["rl_expected_system_baseline"] = "BLOCKED"
            continue
        rl_expected_status, rl_compare_reasons, rl_reference_index = _rl_compare_reference_entry(
            rl_object,
            rl_row,
            rl_category,
            rl_reference_allowlist,
        )
        rl_object["rl_expected_system_baseline"] = rl_expected_status
        rl_reason_codes.extend(rl_compare_reasons)
        if rl_reference_index is not None:
            rl_seen_reference_indexes.add(rl_reference_index)

    if rl_reference_ready:
        rl_missing_reference_count = len(
            [
                rl_index
                for rl_index in range(len(rl_reference_allowlist))
                if rl_index not in rl_seen_reference_indexes
            ]
        )
        if rl_missing_reference_count:
            rl_reason_codes.append("missing_expected_object")

    try:
        rl_catalog_digest = rl_sha256_digest(rl_catalog)
    except (TypeError, ValueError):
        rl_catalog_digest = rl_sha256_digest({"rl_invalid_catalog": True})
        rl_reason_codes.append("non_json_observation")

    rl_reason_codes = sorted(set(rl_reason_codes))
    rl_blocking_reasons = {
        "catalog_contract_incomplete",
        "catalog_not_mapping",
        "category_not_collection",
        "invalid_row",
        "invalid_object",
        "invalid_identity",
        "unknown_relkind",
        "unknown_object_class",
        "unexpected_category",
        "reference_missing",
        "reference_version_missing",
        "reference_version_mismatch",
        "reference_init_missing",
        "reference_init_mismatch",
        "reference_allowlist_invalid",
        "malformed_allowlist",
        "duplicate_reference_identity",
        "duplicate_observed_identity",
        "observed_context_missing",
        "catalog_read_failure",
        "non_json_observation",
    }
    if not rl_reason_codes:
        rl_comparison_status = "MATCH"
    elif any(rl_reason in rl_blocking_reasons for rl_reason in rl_reason_codes):
        rl_comparison_status = "BLOCKED"
    else:
        rl_comparison_status = "DRIFT"
    return {
        "rl_schema_version": "a0.catalog-baseline.v2",
        "rl_status": "BLOCKED",
        "rl_comparison_status": rl_comparison_status,
        "rl_evidence_status": "BLOCKED",
        "rl_live_status": "BLOCKED",
        "rl_catalog_digest": rl_catalog_digest,
        "rl_validation": rl_validation,
        "rl_reason_codes": rl_reason_codes,
        "rl_object_count": len(rl_objects),
        "rl_objects": sorted(
            rl_objects,
            key=lambda rl_object: (
                str(rl_object["rl_category"]),
                str(rl_object["rl_identity_digest"]),
            ),
        ),
    }


def rl_compare_catalog_to_reference(
    rl_catalog: rl_Any,
    rl_reference: rl_Any = None,
    *,
    rl_postgres_version: str | None = None,
    rl_init_digest: str | None = None,
    rl_catalog_read_error: rl_Any = None,
) -> dict[str, rl_Any]:
    """Compatibility name for callers that describe the operation as compare."""

    return rl_build_catalog_baseline(
        rl_catalog,
        rl_reference,
        rl_postgres_version=rl_postgres_version,
        rl_init_digest=rl_init_digest,
        rl_catalog_read_error=rl_catalog_read_error,
    )


__all__ = [
    "RL_RELKIND_MAPPING",
    "RL_REQUIRED_CATALOG_CATEGORIES",
    "rl_build_catalog_baseline",
    "rl_canonical_json",
    "rl_classify_relkind",
    "rl_compare_catalog_to_reference",
    "rl_sha256_digest",
    "rl_validate_catalog_contract",
]
