"""Pure-data schema reconciliation contracts with a permanently blocked live state."""

from __future__ import annotations

import hashlib as rl_hashlib
import json as rl_json
import re as rl_re
from collections.abc import Mapping as rl_Mapping
from typing import Any as rl_Any

RL_SCHEMA_REGIONS: tuple[str, ...] = (
    "alembic",
    "orm",
    "deployed",
    "catalog_baseline",
    "semantic",
)


# 为什么：region/fact 传入的 reason code 只接受 canonical snake_case 词表；
# 其它 raw 字面量（URL、SQL 片段、带连字符/空格的串）一律 wipe，不回显。
_RL_CANONICAL_REASON_RE = rl_re.compile(r"^[a-z][a-z0-9_]*$")


_RL_KNOWN_RELKINDS: set[str] = {
    "r",
    "i",
    "S",
    "t",
    "v",
    "m",
    "c",
    "f",
    "p",
    "I",
}


# 为什么：object kind 是 catalog 类别的单数对象形态；未识别的 kind 一律
# canonical 为 "unknown"，避免 raw 字面量（如 "untrusted-kind"）回显。
_RL_KNOWN_OBJECT_KINDS: set[str] = {
    "schema",
    "namespace",
    "relation",
    "table",
    "view",
    "matview",
    "sequence",
    "column",
    "default",
    "index",
    "constraint",
    "rule",
    "type",
    "domain",
    "composite",
    "enum",
    "range",
    "proc",
    "function",
    "procedure",
    "trigger",
    "policy",
    "extension",
    "language",
    "collation",
    "fdw",
    "server",
    "user_mapping",
    "publication",
    "subscription",
    "large_object",
    "event_trigger",
    "text_search",
    "cast",
    "operator",
    "opclass",
    "opfamily",
    "transform",
    "statistic",
    "security_label",
    "owner",
    "acl",
    "tablespace",
}


_RL_REQUIRED_CATALOG_CATEGORIES: set[str] = {
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


# 为什么：relkind 只在表/索引类 catalog 对象上有意义；schema/column/type/
# extension 等「已知非关系」对象无 relkind 概念，缺失 relkind 不应记为
# unknown_relkind。关系类（relations/indexes）与「未知类别」对象仍 fail-closed。
_RL_NON_RELKIND_CATEGORIES: set[str] = _RL_REQUIRED_CATALOG_CATEGORIES - {
    "relations",
    "indexes",
}


_RL_FACT_DIGEST_FIELDS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("fields", ("fields", "rl_fields_digest"), "field_drift"),
    ("columns", ("columns", "rl_columns_digest"), "column_drift"),
    (
        "defaults",
        ("defaults", "default", "default_expression", "rl_default_digest"),
        "default_drift",
    ),
    ("indexes", ("indexes", "rl_indexes_digest"), "index_drift"),
    ("constraints", ("constraints", "rl_constraints_digest"), "constraint_drift"),
    ("rules", ("rules", "rl_rules_digest"), "rule_drift"),
    ("types", ("types", "rl_types_digest"), "type_drift"),
    ("domains", ("domains", "rl_domains_digest"), "domain_drift"),
    ("composites", ("composites", "rl_composites_digest"), "composite_drift"),
    ("enums", ("enum", "enums", "rl_enums_digest", "rl_enum_digest"), "enum_drift"),
    (
        "extensions",
        ("extension", "extensions", "rl_extensions_digest", "rl_extension_digest"),
        "extension_drift",
    ),
    ("owner", ("owner", "rl_owner_digest"), "owner_drift"),
    ("acl", ("acl", "privileges", "rl_acl_digest"), "acl_drift"),
    ("tablespace", ("tablespace", "rl_tablespace_digest"), "tablespace_drift"),
    ("definition", ("definition", "sql", "rl_definition_digest"), "definition_drift"),
)


def _rl_canonical_json(rl_value: rl_Any) -> str:
    if isinstance(rl_value, rl_Mapping):
        rl_value = {
            str(rl_key): rl_value[rl_key]
            for rl_key in sorted(rl_value, key=lambda rl_key: str(rl_key))
        }
        return rl_json.dumps(
            {
                rl_key: _rl_canonical_value(rl_item)
                for rl_key, rl_item in rl_value.items()
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    return rl_json.dumps(
        _rl_canonical_value(rl_value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _rl_canonical_value(rl_value: rl_Any) -> rl_Any:
    if isinstance(rl_value, rl_Mapping):
        return {
            str(rl_key): _rl_canonical_value(rl_item)
            for rl_key, rl_item in sorted(
                rl_value.items(), key=lambda rl_pair: str(rl_pair[0])
            )
        }
    if isinstance(rl_value, (list, tuple, set, frozenset)):
        rl_items = [_rl_canonical_value(rl_item) for rl_item in rl_value]
        return sorted(
            rl_items,
            key=lambda rl_item: rl_json.dumps(
                rl_item,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ),
        )
    if isinstance(rl_value, (str, int, bool)) or rl_value is None:
        return rl_value
    if (
        isinstance(rl_value, float)
        and rl_value == rl_value
        and rl_value
        not in (
            float("inf"),
            float("-inf"),
        )
    ):
        return rl_value
    raise TypeError("non_json_value")


def _rl_digest(rl_value: rl_Any) -> str:
    try:
        rl_payload = _rl_canonical_json(rl_value).encode("utf-8")
    except (TypeError, ValueError):
        rl_payload = b'{"rl_invalid":true}'
    return "sha256:" + rl_hashlib.sha256(rl_payload).hexdigest()


def _rl_reason_codes_from_region(rl_region: rl_Any) -> list[str]:
    if not isinstance(rl_region, rl_Mapping):
        return []
    rl_reasons = rl_region.get("rl_reason_codes", rl_region.get("reason_codes", []))
    if not isinstance(rl_reasons, (list, tuple, set, frozenset)):
        return ["invalid_region_reason_codes"]
    rl_canonical: list[str] = []
    for rl_reason in rl_reasons:
        if not isinstance(rl_reason, str) or not rl_reason:
            continue
        # 为什么：只保留 canonical snake_case 词表 code，raw 字面量不回显。
        if _RL_CANONICAL_REASON_RE.fullmatch(rl_reason):
            rl_canonical.append(rl_reason)
    return rl_canonical


def _rl_catalog_object_to_fact(rl_object: rl_Any) -> dict[str, rl_Any] | None:
    if not isinstance(rl_object, rl_Mapping):
        return None
    rl_category = rl_object.get("rl_category", rl_object.get("category"))
    rl_identity_digest = rl_object.get("rl_identity_digest")
    if not isinstance(rl_identity_digest, str) or not rl_identity_digest.startswith(
        "sha256:"
    ):
        rl_schema = rl_object.get("schema", rl_object.get("namespace"))
        rl_name = rl_object.get("name", rl_object.get("object_name"))
        if (
            isinstance(rl_schema, str)
            and isinstance(rl_name, str)
            and bool(rl_schema)
            and bool(rl_name)
        ):
            rl_identity_digest = _rl_digest({"schema": rl_schema, "name": rl_name})
        else:
            rl_identity_digest = None
    rl_identity_token_digest = rl_object.get("rl_identity_token_digest")
    if not isinstance(rl_identity_token_digest, str):
        rl_identity_token = rl_object.get("identity", rl_object.get("rl_identity"))
        if rl_identity_token is not None:
            rl_identity_token_digest = _rl_digest(rl_identity_token)
    if (
        not isinstance(rl_category, str)
        or rl_category not in _RL_REQUIRED_CATALOG_CATEGORIES
    ):
        return {
            "category": "unknown",
            "relkind": "unknown",
            "rl_identity_digest": rl_identity_digest,
            "rl_name_digest": rl_identity_digest,
            "rl_identity_token_digest": rl_identity_token_digest,
            "rl_reason_codes": list(rl_object.get("rl_reason_codes", []))
            if isinstance(
                rl_object.get("rl_reason_codes", []), (list, tuple, set, frozenset)
            )
            else ["invalid_object"],
        }
    rl_fact: dict[str, rl_Any] = {
        "category": rl_category,
        "relkind": rl_object.get("rl_relkind", rl_object.get("relkind", "unknown")),
        "rl_identity_digest": rl_identity_digest,
        "rl_name_digest": rl_identity_digest,
        "rl_identity_token_digest": rl_identity_token_digest,
        "kind": rl_object.get("rl_object_kind", rl_object.get("kind", "unknown")),
        "class": rl_object.get("rl_class", rl_object.get("class", "unknown")),
    }
    for rl_field_name, _, _ in _RL_FACT_DIGEST_FIELDS:
        rl_digest_key = f"rl_{rl_field_name}_digest"
        if rl_digest_key in rl_object:
            rl_fact[rl_digest_key] = rl_object[rl_digest_key]
        elif rl_field_name == "defaults" and "rl_default_digest" in rl_object:
            rl_fact[rl_digest_key] = rl_object["rl_default_digest"]
        elif rl_field_name == "defaults" and "default_digest" in rl_object:
            rl_fact[rl_digest_key] = rl_object["default_digest"]
    rl_object_reasons = rl_object.get("rl_reason_codes", [])
    if isinstance(rl_object_reasons, (list, tuple, set, frozenset)):
        rl_fact["rl_reason_codes"] = [
            rl_reason
            for rl_reason in rl_object_reasons
            if isinstance(rl_reason, str) and rl_reason
        ]
    return rl_fact


def _rl_baseline_facts(rl_region: rl_Any) -> tuple[list[rl_Any], list[str]]:
    if not isinstance(rl_region, rl_Mapping):
        return [], []
    rl_objects = rl_region.get("rl_objects", [])
    if not isinstance(rl_objects, (list, tuple)):
        return [], ["invalid_baseline_objects"]
    rl_facts: list[rl_Any] = []
    rl_reasons: list[str] = []
    for rl_object in rl_objects:
        rl_fact = _rl_catalog_object_to_fact(rl_object)
        if rl_fact is None:
            rl_reasons.extend(["invalid_object", "unexpected_object"])
        else:
            rl_facts.append(rl_fact)
            rl_object_reasons = rl_fact.get("rl_reason_codes", [])
            if isinstance(rl_object_reasons, (list, tuple, set, frozenset)):
                rl_reasons.extend(
                    rl_reason
                    for rl_reason in rl_object_reasons
                    if isinstance(rl_reason, str) and rl_reason
                )
            if rl_fact.get("category") == "unknown":
                rl_reasons.append("unknown_object_category")
            if rl_fact.get("relkind") == "unknown":
                rl_reasons.append("unknown_relkind")
    rl_region_reasons = _rl_reason_codes_from_region(rl_region)
    rl_reasons.extend(rl_region_reasons)
    return rl_facts, sorted(set(rl_reasons))


def _rl_region_facts(
    rl_region_name: str, rl_region: rl_Any
) -> tuple[str, list[rl_Any], list[str]]:
    if rl_region_name == "catalog_baseline":
        if rl_region is None:
            return "BLOCKED", [], ["catalog_baseline_unavailable"]
        if not isinstance(rl_region, rl_Mapping):
            return "BLOCKED", [], ["catalog_baseline_unavailable", "invalid_region"]
        rl_facts, rl_reasons = _rl_baseline_facts(rl_region)
        if rl_region.get("rl_status") == "BLOCKED":
            rl_reasons.append("catalog_baseline_unavailable")
        rl_comparison_status = rl_region.get("rl_comparison_status")
        if rl_comparison_status not in ("MATCH", "DRIFT", "BLOCKED"):
            rl_comparison_status = rl_region.get("rl_status")
        if rl_comparison_status not in ("MATCH", "DRIFT", "BLOCKED"):
            rl_comparison_status = "BLOCKED" if rl_reasons else "MATCH"
        return rl_comparison_status, rl_facts, sorted(set(rl_reasons))
    if rl_region_name == "deployed" and rl_region is None:
        return "BLOCKED", [], ["deployed_unavailable"]
    if rl_region is None:
        return "BLOCKED", [], ["region_unavailable"]
    if isinstance(rl_region, (list, tuple)):
        if rl_region_name == "deployed":
            return "BLOCKED", [], ["deployed_unavailable"]
        return "AVAILABLE", list(rl_region), []
    if not isinstance(rl_region, rl_Mapping):
        return "BLOCKED", [], ["invalid_region"]

    rl_status = rl_region.get("rl_status", rl_region.get("status"))
    rl_facts = rl_region.get("rl_facts", rl_region.get("facts", []))
    rl_reasons = _rl_reason_codes_from_region(rl_region)
    if not isinstance(rl_facts, (list, tuple)):
        rl_facts = []
        rl_reasons.append("invalid_region_facts")
    if rl_region_name == "deployed" and rl_status != "AVAILABLE":
        rl_reasons.append("deployed_unavailable")
        return "BLOCKED", [], sorted(set(rl_reasons))
    if rl_status == "BLOCKED":
        return "BLOCKED", [], sorted(set(rl_reasons or ["region_blocked"]))
    if rl_status not in (None, "AVAILABLE"):
        rl_reasons.append("invalid_region_status")
    return (
        "AVAILABLE" if not rl_reasons else "BLOCKED",
        list(rl_facts),
        sorted(set(rl_reasons)),
    )


def _rl_fact_identity(rl_fact: rl_Any) -> tuple[str, bool, str, str | None]:
    if not isinstance(rl_fact, rl_Mapping):
        rl_invalid_digest = _rl_digest({"rl_invalid_fact": True})
        return rl_invalid_digest, False, rl_invalid_digest, None
    rl_identity_digest = rl_fact.get("rl_identity_digest")
    rl_schema = rl_fact.get("schema", rl_fact.get("namespace"))
    rl_name = rl_fact.get("name", rl_fact.get("object_name"))
    rl_existing_token_digest = rl_fact.get("rl_identity_token_digest")
    if (
        not isinstance(rl_schema, str)
        or not isinstance(rl_name, str)
        or not bool(rl_schema)
        or not bool(rl_name)
    ):
        if isinstance(rl_identity_digest, str) and rl_identity_digest.startswith(
            "sha256:"
        ):
            rl_name_digest = rl_fact.get("rl_name_digest", rl_identity_digest)
            if not isinstance(rl_name_digest, str) or not rl_name_digest.startswith(
                "sha256:"
            ):
                rl_name_digest = rl_identity_digest
            if isinstance(
                rl_existing_token_digest, str
            ) and not rl_existing_token_digest.startswith("sha256:"):
                rl_existing_token_digest = _rl_digest(rl_existing_token_digest)
            return rl_identity_digest, True, rl_name_digest, rl_existing_token_digest
    if not (
        isinstance(rl_schema, str)
        and isinstance(rl_name, str)
        and bool(rl_schema)
        and bool(rl_name)
    ):
        rl_invalid_digest = _rl_digest({"rl_invalid_identity": True})
        return rl_invalid_digest, False, rl_invalid_digest, None
    rl_name_digest = _rl_digest({"schema": rl_schema, "name": rl_name})
    if not isinstance(rl_identity_digest, str) or not rl_identity_digest.startswith(
        "sha256:"
    ):
        rl_identity_digest = rl_name_digest
    rl_explicit_identity = rl_fact.get("identity", rl_fact.get("rl_identity"))
    if rl_explicit_identity is None:
        rl_identity_token_digest = None
    else:
        rl_identity_token_digest = _rl_digest(rl_explicit_identity)
    return rl_identity_digest, True, rl_name_digest, rl_identity_token_digest


def _rl_digest_from_fact(
    rl_fact: rl_Mapping[str, rl_Any],
    rl_digest_key: str,
    rl_aliases: tuple[str, ...],
) -> str:
    rl_existing_digest = rl_fact.get(rl_digest_key)
    if isinstance(rl_existing_digest, str) and rl_existing_digest.startswith("sha256:"):
        return rl_existing_digest
    for rl_alias in rl_aliases:
        if rl_alias in rl_fact:
            return _rl_digest(rl_fact[rl_alias])
    return _rl_digest({"rl_missing": rl_digest_key})


def _rl_fact_signature(rl_fact: rl_Any) -> dict[str, rl_Any]:
    if not isinstance(rl_fact, rl_Mapping):
        rl_invalid_digest = _rl_digest({"rl_invalid_fact": True})
        rl_signature: dict[str, rl_Any] = {
            "rl_identity_digest": rl_invalid_digest,
            "rl_name_digest": rl_invalid_digest,
            "rl_category": "unknown",
            "rl_class": "unknown",
            "rl_object_kind": "unknown",
            "rl_relkind": "unknown",
            "rl_identity_token_digest": None,
            "rl_valid_identity": False,
        }
        for rl_field_name, _, _ in _RL_FACT_DIGEST_FIELDS:
            rl_signature[f"rl_{rl_field_name}_digest"] = _rl_digest(
                {"rl_missing": rl_field_name}
            )
        return rl_signature
    rl_identity_digest, rl_valid_identity, rl_name_digest, rl_identity_token_digest = (
        _rl_fact_identity(rl_fact)
    )
    rl_category = rl_fact.get("category", rl_fact.get("rl_category", "relations"))
    # 为什么：catalog 类别必须在已知词汇表内；未识别类别 canonical 为 "unknown"，
    # 不保留 raw 字面量（防止回显 + 触发 unknown_object_category finding）。
    if (
        not isinstance(rl_category, str)
        or rl_category not in _RL_REQUIRED_CATALOG_CATEGORIES
    ):
        rl_category = "unknown"
    rl_relkind = rl_fact.get("relkind", rl_fact.get("rl_relkind", "unknown"))
    if not isinstance(rl_relkind, str) or rl_relkind not in _RL_KNOWN_RELKINDS:
        rl_relkind = "unknown"
    rl_class = rl_fact.get("class", rl_fact.get("rl_class", rl_category))
    if not isinstance(rl_class, str) or not rl_class:
        rl_class = "unknown"
    rl_object_kind = rl_fact.get(
        "kind", rl_fact.get("object_kind", rl_fact.get("rl_object_kind", "unknown"))
    )
    if (
        not isinstance(rl_object_kind, str)
        or rl_object_kind not in _RL_KNOWN_OBJECT_KINDS
    ):
        rl_object_kind = "unknown"
    rl_signature = {
        "rl_identity_digest": rl_identity_digest,
        "rl_name_digest": rl_name_digest,
        "rl_category": rl_category,
        "rl_class": rl_class,
        "rl_object_kind": rl_object_kind,
        "rl_relkind": rl_relkind,
        "rl_identity_token_digest": rl_identity_token_digest,
        "rl_valid_identity": rl_valid_identity,
    }
    for rl_field_name, rl_aliases, _ in _RL_FACT_DIGEST_FIELDS:
        rl_signature[f"rl_{rl_field_name}_digest"] = _rl_digest_from_fact(
            rl_fact,
            f"rl_{rl_field_name}_digest",
            rl_aliases,
        )
    return rl_signature


def _rl_pair_reason_codes(
    rl_left: dict[str, rl_Any],
    rl_right: dict[str, rl_Any],
) -> list[str]:
    rl_reasons: list[str] = []
    if rl_left["rl_category"] != rl_right["rl_category"]:
        rl_reasons.append(
            "unknown_object_category"
            if "unknown"
            in (
                rl_left["rl_category"],
                rl_right["rl_category"],
            )
            else "category_drift"
        )
    if rl_left["rl_class"] != rl_right["rl_class"]:
        rl_reasons.append(
            "unknown_object_class"
            if "unknown"
            in (
                rl_left["rl_class"],
                rl_right["rl_class"],
            )
            else "class_drift"
        )
    if rl_left["rl_object_kind"] != rl_right["rl_object_kind"]:
        rl_reasons.append(
            "unknown_object_class"
            if "unknown"
            in (
                rl_left["rl_object_kind"],
                rl_right["rl_object_kind"],
            )
            else "object_kind_drift"
        )
    if (
        rl_left["rl_relkind"] == "unknown"
        and rl_left["rl_category"] not in _RL_NON_RELKIND_CATEGORIES
    ) or (
        rl_right["rl_relkind"] == "unknown"
        and rl_right["rl_category"] not in _RL_NON_RELKIND_CATEGORIES
    ):
        rl_reasons.append("unknown_relkind")
    elif rl_left["rl_relkind"] != rl_right["rl_relkind"]:
        rl_reasons.append("relkind_drift")
    if (
        rl_left["rl_name_digest"] == rl_right["rl_name_digest"]
        and rl_left["rl_identity_token_digest"] is not None
        and rl_right["rl_identity_token_digest"] is not None
        and rl_left["rl_identity_token_digest"] != rl_right["rl_identity_token_digest"]
    ):
        rl_reasons.append("same_name_identity_mismatch")
    for rl_field_name, _, rl_reason_code in _RL_FACT_DIGEST_FIELDS:
        rl_digest_key = f"rl_{rl_field_name}_digest"
        if rl_left[rl_digest_key] != rl_right[rl_digest_key]:
            rl_reasons.append(rl_reason_code)
    return sorted(set(rl_reasons))


def _rl_region_output(
    rl_region_name: str, rl_status: str, rl_facts: list[rl_Any], rl_reasons: list[str]
) -> dict[str, rl_Any]:
    return {
        "rl_source": rl_region_name,
        "rl_status": rl_status,
        "rl_fact_count": len(rl_facts),
        "rl_facts": rl_facts,
        "rl_reason_codes": sorted(set(rl_reasons)),
    }


def rl_reconcile_schema(rl_input: rl_Any) -> dict[str, rl_Any]:
    """Reconcile independent static regions without promoting one to another."""

    if not isinstance(rl_input, rl_Mapping):
        rl_input_mapping: rl_Mapping[str, rl_Any] = {}
        rl_global_reasons = ["invalid_input"]
    else:
        rl_input_mapping = rl_input
        rl_global_reasons = []

    rl_regions: dict[str, dict[str, rl_Any]] = {}
    rl_all_facts: dict[str, list[dict[str, rl_Any]]] = {}
    for rl_region_name in RL_SCHEMA_REGIONS:
        rl_region_value = rl_input_mapping.get(rl_region_name)
        rl_status, rl_facts, rl_reasons = _rl_region_facts(
            rl_region_name, rl_region_value
        )
        if rl_region_name == "deployed" and rl_region_value is None:
            rl_reasons.append("deployed_unavailable")
        rl_regions[rl_region_name] = _rl_region_output(
            rl_region_name,
            rl_status,
            [],
            rl_reasons,
        )
        rl_all_facts[rl_region_name] = [
            _rl_fact_signature(rl_fact) for rl_fact in rl_facts
        ]
        for rl_fact in rl_all_facts[rl_region_name]:
            if rl_fact["rl_category"] == "unknown":
                rl_reasons.append("unknown_object_category")
            if (
                rl_fact["rl_relkind"] == "unknown"
                and rl_fact["rl_category"] not in _RL_NON_RELKIND_CATEGORIES
            ):
                rl_reasons.append("unknown_relkind")
            if (
                rl_fact["rl_class"] == "unknown"
                or rl_fact["rl_object_kind"] == "unknown"
            ):
                rl_reasons.append("unknown_object_class")
        rl_reasons = sorted(set(rl_reasons))
        rl_regions[rl_region_name]["rl_status"] = (
            "BLOCKED"
            if rl_reasons and rl_status == "AVAILABLE"
            else rl_regions[rl_region_name]["rl_status"]
        )
        rl_regions[rl_region_name]["rl_reason_codes"] = rl_reasons
        rl_regions[rl_region_name]["rl_facts"] = rl_all_facts[rl_region_name]
        rl_global_reasons.extend(rl_reasons)

    if rl_regions["deployed"]["rl_status"] != "AVAILABLE":
        rl_global_reasons.append("deployed_unavailable")

    rl_keyed: dict[str, dict[str, list[dict[str, rl_Any]]]] = {}
    for rl_region_name, rl_facts in rl_all_facts.items():
        for rl_fact in rl_facts:
            rl_identity = rl_fact["rl_identity_digest"]
            rl_keyed.setdefault(rl_identity, {}).setdefault(rl_region_name, []).append(
                rl_fact
            )

    for rl_identity, rl_by_region in rl_keyed.items():
        rl_has_orm = bool(rl_by_region.get("orm"))
        rl_has_migration = bool(rl_by_region.get("alembic"))
        rl_has_deployed = bool(rl_by_region.get("deployed"))
        if rl_has_orm and not rl_has_deployed:
            rl_global_reasons.append("orm_only")
        if rl_has_migration and not rl_has_deployed:
            rl_global_reasons.append("migration_only")
        if rl_has_deployed and not rl_has_orm and not rl_has_migration:
            rl_global_reasons.append("deployed_only")
        if (rl_has_orm or rl_has_migration) and not rl_has_deployed:
            rl_global_reasons.append("unresolved_static_only")

        rl_reference_facts = []
        for rl_region_name in ("alembic", "orm", "deployed"):
            rl_reference_facts.extend(rl_by_region.get(rl_region_name, []))
        if rl_reference_facts:
            rl_first = rl_reference_facts[0]
            for rl_other in rl_reference_facts[1:]:
                rl_global_reasons.extend(_rl_pair_reason_codes(rl_first, rl_other))

        rl_same_name_candidates: list[dict[str, rl_Any]] = []
        for rl_other_identity, rl_other_by_region in rl_keyed.items():
            if rl_other_identity == rl_identity:
                continue
            for rl_other_facts in rl_other_by_region.values():
                rl_same_name_candidates.extend(rl_other_facts)
        for rl_candidate in rl_same_name_candidates:
            if (
                rl_reference_facts
                and rl_candidate["rl_name_digest"]
                == rl_reference_facts[0]["rl_name_digest"]
                and rl_candidate["rl_identity_token_digest"] is not None
                and rl_reference_facts[0]["rl_identity_token_digest"] is not None
                and rl_candidate["rl_identity_token_digest"]
                != rl_reference_facts[0]["rl_identity_token_digest"]
            ):
                rl_global_reasons.append("same_name_identity_mismatch")

    rl_baseline_input = rl_input_mapping.get("catalog_baseline")
    if isinstance(rl_baseline_input, rl_Mapping):
        rl_baseline_reasons = rl_regions["catalog_baseline"]["rl_reason_codes"]
        rl_global_reasons.extend(rl_baseline_reasons)
        if rl_baseline_input.get("rl_status") == "BLOCKED":
            if not rl_baseline_reasons or any(
                "mismatch" in rl_reason
                or "failure" in rl_reason
                or "missing" in rl_reason
                for rl_reason in rl_baseline_reasons
            ):
                rl_global_reasons.append("baseline_mismatch")

    rl_global_reasons = sorted(set(rl_global_reasons))
    return {
        "rl_schema_version": "a0.schema-reconciliation.v1",
        "rl_status": "BLOCKED",
        "rl_comparison_status": (
            "DRIFT"
            if any(
                rl_reason.endswith("_drift")
                or rl_reason.endswith("_mismatch")
                or rl_reason
                in {
                    "unexpected_object",
                    "unexpected_identity",
                    "missing_expected_object",
                }
                for rl_reason in rl_global_reasons
            )
            else "BLOCKED"
        ),
        "rl_evidence_status": "BLOCKED",
        "rl_live_status": "BLOCKED",
        "rl_regions": rl_regions,
        "rl_columns": rl_regions,
        "rl_reason_codes": rl_global_reasons,
        "rl_region_digests": {
            rl_region_name: _rl_digest(rl_all_facts[rl_region_name])
            for rl_region_name in RL_SCHEMA_REGIONS
        },
    }


__all__ = ["RL_SCHEMA_REGIONS", "rl_reconcile_schema"]
