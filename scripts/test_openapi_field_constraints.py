"""Regression coverage for ``scripts/check_openapi_field_constraints.py``.

The guard pins the 1712 published field-level values (815 constraints + 897
``default`` values) to a hand-written literal. These cases prove each failure
direction on real
committed bytes, that the literal is independent of the artifact it audits,
and that the wiring cannot quietly rot. Collected by the contracts layer's
``tests=()`` array; stdlib-only, no Python 3.15 needed.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_openapi_field_constraints as guard

SMOKE = (ROOT / "scripts" / "smoke.sh").read_text(encoding="utf-8")
REGISTRY = (ROOT / "scripts" / "check_contracts_registry_collection.py").read_text(
    encoding="utf-8"
)
TEETH = (ROOT / "scripts" / "check_contracts_self_test_teeth.py").read_text(
    encoding="utf-8"
)

_INPUT_OBJECTS = "AnalysesSubmitRequest"


def _mutate(change) -> str:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    node = document["components"]["schemas"][_INPUT_OBJECTS]["properties"][
        "input_objects"
    ]
    change(node)
    return json.dumps(document, indent=2)


def test_committed_tree_passes() -> None:
    found = guard.failures()
    assert not found, found


def test_coordinated_maxitems_retype_is_rejected() -> None:
    """The decisive drift: one value retyped, no other half to disagree."""

    def change(node: dict) -> None:
        assert node["maxItems"] == 100
        node["maxItems"] = 999

    found = guard.failures(snapshot=_mutate(change))
    assert any("drifted" in problem for problem in found), found


def test_one_sided_constraint_dropped_is_rejected() -> None:
    found = guard.failures(snapshot=_mutate(lambda node: node.pop("minItems")))
    assert any("count is" in problem for problem in found), found


def test_one_sided_constraint_added_is_rejected() -> None:
    found = guard.failures(snapshot=_mutate(lambda node: node.update(pattern="^x$")))
    assert any("count is" in problem for problem in found), found


def test_constraint_keyword_renamed_is_rejected() -> None:
    def change(node: dict) -> None:
        node["maxLength"] = node.pop("maxItems")

    found = guard.failures(snapshot=_mutate(change))
    assert any("by keyword changed" in problem for problem in found), found


def test_same_count_permutation_is_rejected() -> None:
    """Two same-key values swapped: every count door holds, the digest moves."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    schemas = document["components"]["schemas"]
    first = schemas["AnalysesUploadRequest"]["properties"]["filename"]
    second = schemas["UserCreate"]["properties"]["full_name"]
    assert first["maxLength"] == 255 == second["maxLength"]
    first["maxLength"], second["maxLength"] = 64, 255
    # Swap a second pair to keep the by-key value multiset unchanged.
    third = schemas["AlleleFreqRequest"]["properties"]["gene_id"]["anyOf"][0]
    fourth = schemas["AlleleFreqRequest"]["properties"]["chromosome"]["anyOf"][0]
    assert third["maxLength"] == 64 == fourth["maxLength"]
    third["maxLength"], fourth["maxLength"] = 255, 64
    found = guard.failures(snapshot=json.dumps(document, indent=2))
    assert any("drifted" in problem for problem in found), found


def test_coordinated_default_retype_is_rejected() -> None:
    """The decisive shape: a default retyped in both halves + re-pinned blobs.

    Only the independent literal sees it: the generated ``@default`` line
    moves with the snapshot, and the provenance blob ids are a reviewed
    re-pin. Without ``default`` in ``_KEYS`` every wired guard stayed green.
    """

    def change(document: dict) -> None:
        node = document["components"]["schemas"]["AdminDashboardStats"][
            "properties"
        ]["totalUsers"]
        assert node["default"] == 0
        node["default"] = 999999

    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    change(document)
    found = guard.failures(snapshot=json.dumps(document, indent=2))
    assert any("drifted" in problem for problem in found), found


def test_default_values_are_pinned_by_the_literal() -> None:
    """``default`` is in the pinned vocabulary, not a decorative keyword."""
    assert "default" in guard._KEYS
    assert guard._EXPECTED_BY_KEY["default"] == 897
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    defaults = [(path, key, value) for path, key, value in guard.rows(document)
                if key == "default"]
    assert len(defaults) == 897


def test_the_default_named_property_is_a_schema_not_a_keyword() -> None:
    """``SettingFieldSchema.properties.default`` is a field, not a row.

    A flat-key walk would count the map entry itself as a ``default`` value;
    the marker-based walker counts only keyword values on real schema nodes,
    so the two properties literally named ``default`` are not phantom rows.
    """
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    rows_ = guard.rows(document)
    assert len(rows_) == guard._EXPECTED_CONSTRAINT_ROWS
    offenders = [
        (path, key) for path, key, _ in rows_
        if path.endswith("/properties/default") and key == "default"
    ]
    assert not offenders, offenders


def test_a_default_only_drift_moves_the_digest() -> None:
    """A same-count default swap is invisible to every count door."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    props = document["components"]["schemas"]["BlastDatabaseResponse"]["properties"]
    first, second = props["engine"], props["build_status"]
    assert first["default"] != second["default"]
    first["default"], second["default"] = second["default"], first["default"]
    found = guard.failures(snapshot=json.dumps(document, indent=2))
    assert any("drifted" in problem for problem in found), found

def test_the_digest_is_an_independent_literal() -> None:
    """Re-deriving the digest from the artifact would make the pin vacuous."""
    source = (ROOT / "scripts" / "check_openapi_field_constraints.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    assigned = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_FIELD_CONSTRAINT_DIGEST"
            for target in node.targets
        )
    ]
    assert len(assigned) == 1
    value = ast.literal_eval(assigned[0].value)
    assert isinstance(value, str) and len(value) == 64
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    assert value == guard._digest(guard.rows(document))


def test_the_count_doors_are_load_bearing() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    found = guard.failures(
        snapshot=json.dumps(document, indent=2),
        expected_rows=guard._EXPECTED_CONSTRAINT_ROWS + 1,
    )
    assert any("count is" in problem for problem in found), found


def test_keyword_named_properties_are_not_constraints() -> None:
    """A field called ``format``/``minimum`` is not a JSON Schema keyword."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    rows_ = guard.rows(document)
    assert len(rows_) == guard._EXPECTED_CONSTRAINT_ROWS
    offenders = [
        (path, key)
        for path, key, _ in rows_
        if path.endswith("/properties/format") and key == "format"
        or path.endswith("/properties/minimum") and key == "minimum"
        or path.endswith("/properties/pattern") and key == "pattern"
    ]
    assert not offenders, offenders


def test_a_repin_in_the_same_commit_stays_green() -> None:
    """A reviewed regenerate re-pins the literal with the artifact, once."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    document["components"]["schemas"][_INPUT_OBJECTS]["properties"][
        "input_objects"
    ]["maxItems"] = 999
    snapshot = json.dumps(document, indent=2)
    new_digest = guard._digest(guard.rows(json.loads(snapshot)))
    assert new_digest != guard._FIELD_CONSTRAINT_DIGEST
    assert not guard.failures(snapshot=snapshot, digest=new_digest)


def test_the_wiring_is_pinned_in_all_three_places() -> None:
    assert f"scripts/{guard.SELF}" in SMOKE
    assert f"scripts/{guard.SELF}" in REGISTRY
    assert "scripts/test_openapi_field_constraints.py" in SMOKE
    assert "scripts/test_openapi_field_constraints.py" in REGISTRY
    assert f"scripts/{guard.SELF}" in TEETH
