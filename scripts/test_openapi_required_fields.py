"""Regression coverage for ``scripts/check_openapi_required_fields.py``.

The guard pins 1076 published ``required`` declarations to a hand-written
literal and checks the generated client's optional markers against them.
These cases prove each failure direction on real committed bytes, that the
digest is independent of the artifact it audits, that the generated half
cannot be edited alone, and that the wiring cannot quietly rot. Collected by
the contracts layer's ``tests=()`` array; stdlib-only, no Python 3.15 needed.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_openapi_required_fields as guard

SMOKE = (ROOT / "scripts" / "smoke.sh").read_text(encoding="utf-8")
REGISTRY = (ROOT / "scripts" / "check_contracts_registry_collection.py").read_text(
    encoding="utf-8"
)
TEETH = (ROOT / "scripts" / "check_contracts_self_test_teeth.py").read_text(
    encoding="utf-8"
)

_TARGET = "AdminPluginResponse"
_SNAPSHOT = guard.SNAPSHOT.read_text(encoding="utf-8")
_GENERATED = guard.GENERATED.read_text(encoding="utf-8")


def _mutate(change) -> str:
    document = json.loads(_SNAPSHOT)
    change(document["components"]["schemas"])
    return json.dumps(document, indent=2)


def test_committed_tree_passes() -> None:
    found = guard.failures(snapshot=_SNAPSHOT, generated=_GENERATED)
    assert not found, found


def test_coordinated_required_drop_is_rejected() -> None:
    """The decisive drift: both halves move together, blob ids re-pinned."""

    def change(schemas: dict) -> None:
        assert schemas[_TARGET]["required"] == ["key", "status"]
        schemas[_TARGET]["required"] = ["status"]

    snapshot = _mutate(change)
    generated = _GENERATED.replace(
        "        AdminPluginResponse: {\n            /** Key */\n            key: string;",
        "        AdminPluginResponse: {\n            /** Key */\n            key?: string;",
        1,
    )
    assert generated != _GENERATED
    found = guard.failures(snapshot=snapshot, generated=generated)
    assert any("drifted" in problem for problem in found), found


def test_one_sided_snapshot_drop_is_rejected() -> None:
    def change(schemas: dict) -> None:
        schemas[_TARGET]["required"] = ["status"]

    found = guard.failures(snapshot=_mutate(change), generated=_GENERATED)
    assert any("drifted" in problem for problem in found), found


def test_one_sided_client_optional_flip_is_rejected() -> None:
    """The generated half is checked against the pinned rows, not the snapshot."""
    generated = _GENERATED.replace(
        "        AdminPluginResponse: {\n            /** Key */\n            key: string;",
        "        AdminPluginResponse: {\n            /** Key */\n            key?: string;",
        1,
    )
    assert generated != _GENERATED
    found = guard.failures(snapshot=_SNAPSHOT, generated=generated)
    assert any("renders required field" in problem for problem in found), found


def test_one_sided_required_add_is_rejected() -> None:
    def change(schemas: dict) -> None:
        schemas[_TARGET]["required"].append("manifest")

    found = guard.failures(snapshot=_mutate(change), generated=_GENERATED)
    assert any("count is" in problem for problem in found), found


def test_nested_defs_required_drop_is_rejected() -> None:
    """The seven nested $defs copies are part of the pinned surface."""

    def change(schemas: dict) -> None:
        detail = schemas["ErrorResponse"]["$defs"]["ErrorDetail"]
        assert detail["required"] == ["code", "message"]
        detail["required"] = ["code"]

    found = guard.failures(snapshot=_mutate(change), generated=_GENERATED)
    assert any("drifted" in problem for problem in found), found


def test_same_count_permutation_is_rejected() -> None:
    """Move one required field between two schemas: counts hold, digest moves."""

    def change(schemas: dict) -> None:
        a = schemas["AdminPluginResponse"]["required"]
        b = schemas["AdminPluginsResponse"]["required"]
        assert a == ["key", "status"] and b == ["plugins"]
        a[0], b[0] = b[0], a[0]

    found = guard.failures(snapshot=_mutate(change), generated=_GENERATED)
    assert any("drifted" in problem for problem in found), found


def test_the_digest_is_an_independent_literal() -> None:
    """Re-deriving the digest from the artifact would make the pin vacuous."""
    source = (ROOT / "scripts" / "check_openapi_required_fields.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    assigned = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_REQUIRED_FIELD_DIGEST"
            for target in node.targets
        )
    ]
    assert len(assigned) == 1
    value = ast.literal_eval(assigned[0].value)
    assert isinstance(value, str) and len(value) == 64
    document = json.loads(_SNAPSHOT)
    assert value == guard._digest(guard.rows(document))


def test_the_count_doors_are_load_bearing() -> None:
    found = guard.failures(
        snapshot=_SNAPSHOT,
        generated=_GENERATED,
        expected_rows=guard._EXPECTED_REQUIRED_ROWS + 1,
    )
    assert any("count is" in problem for problem in found), found
    found = guard.failures(
        snapshot=_SNAPSHOT,
        generated=_GENERATED,
        expected_schemas=guard._EXPECTED_SCHEMAS + 1,
    )
    assert any("span" in problem for problem in found), found


def test_a_repin_in_the_same_commit_stays_green() -> None:
    """A reviewed regenerate re-pins the literal with the artifact, once."""

    def change(schemas: dict) -> None:
        schemas[_TARGET]["required"] = ["status"]

    snapshot = _mutate(change)
    new_digest = guard._digest(guard.rows(json.loads(snapshot)))
    assert new_digest != guard._REQUIRED_FIELD_DIGEST
    found = guard.failures(
        snapshot=snapshot,
        generated=_GENERATED,
        digest=new_digest,
        expected_rows=guard._EXPECTED_REQUIRED_ROWS - 1,
    )
    assert not found, found


def test_the_wiring_is_pinned_in_all_three_places() -> None:
    assert f"scripts/{guard.SELF}" in SMOKE
    assert f"scripts/{guard.SELF}" in REGISTRY
    assert "scripts/test_openapi_required_fields.py" in SMOKE
    assert "scripts/test_openapi_required_fields.py" in REGISTRY
    assert f"scripts/{guard.SELF}" in TEETH


# --- the tuple/map surface (Doors 4 and 5) ---------------------------------

_TUPLE_TARGET = "SequenceAlignResponse"
_TUPLE_FIELD = "query_range"
_TUPLE_BLOCK = (
    "            query_range: [\n"
    "                number,\n"
    "                number\n"
    "            ];"
)


def _retype_client_tuple() -> str:
    old_tail = "                number\n            ];"
    new_tail = "                string\n            ];"
    replaced = _GENERATED.replace(_TUPLE_BLOCK, _TUPLE_BLOCK.replace(
        old_tail, new_tail
    ), 1)
    assert replaced != _GENERATED
    return replaced


def test_the_tuple_keywords_have_their_own_literal() -> None:
    """Not folded into the required digest: the two surfaces stay separable."""
    assert guard._VALUE_DIGEST != guard._REQUIRED_FIELD_DIGEST
    assert guard._EXPECTED_VALUE_ROWS == len(
        guard.value_rows(json.loads(_SNAPSHOT))
    )
    assert sum(guard._EXPECTED_VALUE_BY_KEYWORD.values()) == (
        guard._EXPECTED_VALUE_ROWS
    )


def test_a_coordinated_tuple_retype_is_rejected() -> None:
    """Both halves move together; only the independent literal sees it."""

    def change(schemas: dict) -> None:
        slots = schemas[_TUPLE_TARGET]["properties"][_TUPLE_FIELD]["prefixItems"]
        assert slots == [{"type": "integer"}, {"type": "integer"}]
        slots[1] = {"type": "string"}

    found = guard.failures(
        snapshot=_mutate(change), generated=_retype_client_tuple()
    )
    assert any("_VALUE_DIGEST" in problem for problem in found), found


def test_the_digest_alone_catches_it_and_the_agreement_door_is_silent() -> None:
    """A positive control: with the digest re-pinned, Door 5 must still be quiet.

    Without this, Door 5 could be catching the coordinated case by accident and
    the digest would look load-bearing when it is not (or the reverse).
    """

    def change(schemas: dict) -> None:
        schemas[_TUPLE_TARGET]["properties"][_TUPLE_FIELD]["prefixItems"][1] = {
            "type": "string"
        }

    snapshot = _mutate(change)
    new_digest = guard._value_digest(
        guard.value_rows(json.loads(snapshot))
    )
    assert new_digest != guard._VALUE_DIGEST
    found = guard.failures(
        snapshot=snapshot,
        generated=_retype_client_tuple(),
        value_digest=new_digest,
    )
    assert not found, found


def test_a_client_only_tuple_retype_is_named_with_both_shapes() -> None:
    found = guard.failures(
        snapshot=_SNAPSHOT, generated=_retype_client_tuple()
    )
    assert any(
        f"{_TUPLE_TARGET}.{_TUPLE_FIELD}" in problem and "string" in problem
        for problem in found
    ), found


def test_a_client_tuple_replaced_by_an_array_is_rejected() -> None:
    """Arity alone is not the contract; losing the tuple shape is a break."""
    found = guard.failures(
        snapshot=_SNAPSHOT,
        generated=_GENERATED.replace(
            _TUPLE_BLOCK, "            query_range: number[];", 1
        ),
    )
    assert any("positional tuple" in problem for problem in found), found


def test_an_unmodelled_slot_never_compares_equal() -> None:
    """A future slot type must fail loudly, not pass by being unknown."""
    assert guard._ts_slot({"type": "integer"}) == "number"
    assert guard._ts_slot({"anyOf": [{"type": "number"}, {"type": "null"}]}) == (
        "number | null"
    )
    assert guard._ts_slot({"type": "object"}).startswith("UNMODELLED(")


def test_the_map_bounds_are_pinned() -> None:
    def change(schemas: dict) -> None:
        schemas["ImportCommitRequest"]["properties"]["config"][
            "maxProperties"
        ] = 33

    found = guard.failures(snapshot=_mutate(change), generated=_GENERATED)
    assert any("_VALUE_DIGEST" in problem for problem in found), found


def test_a_same_count_map_bound_rotation_is_rejected() -> None:
    """Every count and the row set are unchanged; only the digest moves."""

    def change(schemas: dict) -> None:
        a = schemas["ImportCommitRequest"]["properties"]["config"]
        b = schemas["SettingsPatchRequest"]["properties"]["values"]
        a["maxProperties"], b["minProperties"] = 1, 32

    found = guard.failures(snapshot=_mutate(change), generated=_GENERATED)
    assert any("_VALUE_DIGEST" in problem for problem in found), found


def test_the_discriminator_is_pinned() -> None:
    def change(schemas: dict) -> None:
        del schemas["SequenceMatchRequest"]["properties"]["target"][
            "discriminator"
        ]

    found = guard.failures(snapshot=_mutate(change), generated=_GENERATED)
    assert any("_VALUE_DIGEST" in problem for problem in found), found


def test_the_guard_source_still_carries_both_plants() -> None:
    """A second file asserts the source plant, so a single-file edit cannot
    remove the self-test case and stay green."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    assert "_VALUE_DIGEST = (" in source
    assert "_VALUE_KEYWORDS: tuple[str, ...] = (" in source
    assert "coordinated tuple slot retype (both halves)" in source
    assert "one-sided client tuple slot retype" in source


# --- the component-to-component $ref wiring (Doors 6, 7 and 8) -------------

_REF_OWNER = "AdminDashboardSeries"
_A_LINE = (
    '            import_throughput?: components["schemas"]'
    '["ImportThroughputPoint"][];'
)
_B_LINE = (
    '            query_latency?: components["schemas"]'
    '["QueryLatencyPoint"][];'
)


def _swap_snapshot(schemas: dict) -> None:
    series = schemas[_REF_OWNER]["properties"]
    assert series["import_throughput"]["items"]["$ref"].endswith(
        "ImportThroughputPoint"
    )
    assert series["query_latency"]["items"]["$ref"].endswith(
        "QueryLatencyPoint"
    )
    series["import_throughput"]["items"]["$ref"] = (
        "#/components/schemas/QueryLatencyPoint"
    )
    series["query_latency"]["items"]["$ref"] = (
        "#/components/schemas/ImportThroughputPoint"
    )


def _swap_client() -> str:
    swapped = _GENERATED.replace(
        _A_LINE,
        _A_LINE.replace("ImportThroughputPoint", "QueryLatencyPoint"),
        1,
    ).replace(
        _B_LINE,
        _B_LINE.replace("QueryLatencyPoint", "ImportThroughputPoint"),
        1,
    )
    assert swapped != _GENERATED
    return swapped


def test_the_two_ref_literals_are_independent() -> None:
    assert guard._SCHEMA_REF_DIGEST != guard._REQUIRED_FIELD_DIGEST
    assert guard._SCHEMA_REF_DIGEST != guard._VALUE_DIGEST
    assert guard._CLIENT_SCHEMA_REF_DIGEST != guard._SCHEMA_REF_DIGEST
    document = json.loads(_SNAPSHOT)
    assert guard._EXPECTED_SCHEMA_REF_ROWS == len(
        guard.schema_ref_rows(document)
    )
    assert guard._EXPECTED_CLIENT_SCHEMA_REF_ROWS == len(
        guard.client_schema_ref_rows(_GENERATED)
    )
    rows_ = guard.schema_ref_rows(document)
    assert guard._EXPECTED_SCHEMA_REF_OWNERS == len({r[0] for r in rows_})
    assert guard._EXPECTED_SCHEMA_REF_TARGETS == len({r[2] for r in rows_})


def test_a_coordinated_ref_swap_is_rejected() -> None:
    """The decisive drift: both halves agree, every landed guard stays green."""
    found = guard.failures(
        snapshot=_mutate(_swap_snapshot), generated=_swap_client()
    )
    assert any("_SCHEMA_REF_DIGEST" in problem for problem in found), found
    assert any("_CLIENT_SCHEMA_REF_DIGEST" in problem for problem in found), found


def test_a_one_sided_snapshot_swap_is_named() -> None:
    found = guard.failures(
        snapshot=_mutate(_swap_snapshot), generated=_GENERATED
    )
    assert any("target disagrees" in problem for problem in found), found


def test_a_one_sided_client_swap_is_named() -> None:
    found = guard.failures(
        snapshot=_SNAPSHOT, generated=_swap_client()
    )
    assert any("target disagrees" in problem for problem in found), found


def test_repinning_only_one_ref_digest_stays_red() -> None:
    """Two independent fixed points: a single-side re-pin is never green."""
    snapshot = _mutate(_swap_snapshot)
    swapped = _swap_client()
    document = json.loads(snapshot)
    snap_digest = guard._schema_ref_digest(guard.schema_ref_rows(document))
    cli_digest = guard._client_schema_ref_digest(
        guard.client_schema_ref_rows(swapped)
    )
    assert snap_digest != guard._SCHEMA_REF_DIGEST
    assert cli_digest != guard._CLIENT_SCHEMA_REF_DIGEST

    only_snapshot = guard.failures(
        snapshot=snapshot,
        generated=swapped,
        schema_ref_digest=snap_digest,
    )
    assert any("_CLIENT_SCHEMA_REF_DIGEST" in p for p in only_snapshot), (
        only_snapshot
    )
    only_client = guard.failures(
        snapshot=snapshot,
        generated=swapped,
        client_ref_digest=cli_digest,
    )
    assert any("_SCHEMA_REF_DIGEST" in p for p in only_client), only_client
    both = guard.failures(
        snapshot=snapshot,
        generated=swapped,
        schema_ref_digest=snap_digest,
        client_ref_digest=cli_digest,
    )
    assert not both, both


def test_a_same_count_ref_rotation_is_rejected() -> None:
    """Move one ref to an already-referenced target: counts unchanged."""

    def change(schemas: dict) -> None:
        series = schemas[_REF_OWNER]["properties"]
        series["storage_growth"]["items"]["$ref"] = (
            "#/components/schemas/ImportThroughputPoint"
        )

    found = guard.failures(snapshot=_mutate(change), generated=_GENERATED)
    assert any("_SCHEMA_REF_DIGEST" in problem for problem in found), found


def test_the_ref_digests_are_independent_literals() -> None:
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for name in ("_SCHEMA_REF_DIGEST", "_CLIENT_SCHEMA_REF_DIGEST"):
        assigned = [
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets
            )
        ]
        assert len(assigned) == 1, name
        value = ast.literal_eval(assigned[0].value)
        assert isinstance(value, str) and len(value) == 64, name
    assert guard._SCHEMA_REF_DIGEST == guard._schema_ref_digest(
        guard.schema_ref_rows(json.loads(_SNAPSHOT))
    )
    assert guard._CLIENT_SCHEMA_REF_DIGEST == guard._client_schema_ref_digest(
        guard.client_schema_ref_rows(_GENERATED)
    )


def test_the_ref_count_doors_are_load_bearing() -> None:
    found = guard.failures(
        snapshot=_SNAPSHOT,
        generated=_GENERATED,
        expected_ref_rows=guard._EXPECTED_SCHEMA_REF_ROWS + 1,
    )
    assert any("row count is" in p for p in found), found
    found = guard.failures(
        snapshot=_SNAPSHOT,
        generated=_GENERATED,
        expected_client_ref_rows=guard._EXPECTED_CLIENT_SCHEMA_REF_ROWS + 1,
    )
    assert any("row count is" in p for p in found), found


def test_the_guard_source_carries_the_ref_plants() -> None:
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    assert "_SCHEMA_REF_DIGEST = (" in source
    assert "_CLIENT_SCHEMA_REF_DIGEST = (" in source
    assert "coordinated schema $ref swap (both halves)" in source
    assert "only the snapshot digest re-pinned stays red" in source
