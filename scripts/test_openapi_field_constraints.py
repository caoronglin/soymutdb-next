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
from collections import Counter
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


def _resolve(document: dict, path: str):
    """Walk a ``rows()`` path. ``properties`` / ``$defs`` nest by name, not ``/``.

    Component schema names carry dots (``Glycine.max``), so the path is split on
    ``/`` only after the schema name, per the walker's own convention.
    """
    node = document["components"]["schemas"]
    for part in path.strip("/").split("/"):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def _rotate_distinct(document: dict, key: str) -> str:
    """Rotate three distinct values of one keyword; leave the multiset intact.

    Reassigning a value to *another row carrying a different value* keeps every
    count door green: the by-key histogram is unchanged and so is the row count.
    Only a positional fixed point sees it. Count doors alone would not.
    """
    buckets: dict[str, list[tuple[str, object]]] = {}
    for path, row_key, value in guard.rows(document):
        if row_key == key:
            buckets.setdefault(json.dumps(value, sort_keys=True), []).append(
                (path, value)
            )
    distinct = [bucket[0] for bucket in buckets.values() if bucket][:3]
    assert len(distinct) == 3, f"need three distinct {key!r} values"
    (path_a, value_a), (path_b, value_b), (path_c, value_c) = distinct
    _resolve(document, path_a)[key] = value_b
    _resolve(document, path_b)[key] = value_c
    _resolve(document, path_c)[key] = value_a


def test_a_same_count_value_rotation_is_rejected() -> None:
    """Every value moves to another row, every count door still holds."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    before = guard.rows(document)
    _rotate_distinct(document, "default")
    after = guard.rows(document)
    assert len(after) == len(before)
    def histogram(rows_: list[tuple[str, str, object]]) -> Counter[str]:
        return Counter(key for _, key, _ in rows_)

    assert histogram(after) == histogram(before)
    assert after != before
    found = guard.failures(snapshot=json.dumps(document, indent=2))
    assert any("drifted" in problem for problem in found), found


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


# ---------------------------------------------------------------------------
# Door 5 -- the published ``examples`` projection.
# ---------------------------------------------------------------------------


def _example_doc(change) -> str:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    change(document)
    return json.dumps(document, indent=2)


def _generated() -> str:
    return guard._GENERATED.read_text(encoding="utf-8")


def test_committed_examples_match_the_independent_literal() -> None:
    """The literal is recomputable from committed bytes but not derived by it."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    rows_ = guard.example_rows(document)
    assert len(rows_) == guard._EXPECTED_EXAMPLES == 7
    assert guard._example_digest(rows_) == guard._EXAMPLE_DIGEST
    # The digest is a module-level literal, not a call folded into failures().
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assigned = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_EXAMPLE_DIGEST"
            for target in node.targets
        )
    ]
    assert len(assigned) == 1
    assert ast.literal_eval(assigned[0].value) == guard._EXAMPLE_DIGEST


def test_examples_digest_is_separate_from_the_constraint_digest() -> None:
    """A drift here must say 'examples', not 'field constraints'."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    assert "examples" not in guard._KEYS
    assert guard._FIELD_CONSTRAINT_DIGEST != guard._EXAMPLE_DIGEST
    # Non-duplication: the constraint digest is unchanged by this door.
    assert guard._digest(guard.rows(document)) == guard._FIELD_CONSTRAINT_DIGEST


def test_coordinated_examples_co_revert_is_caught_only_by_the_digest() -> None:
    """The decisive drift: all 7 values rewritten in BOTH halves."""

    def change(doc: dict) -> None:
        for name in ("LoginRequest", "UserCreate"):
            for prop in doc["components"]["schemas"][name]["properties"].values():
                if isinstance(prop, dict) and isinstance(prop.get("examples"), list):
                    prop["examples"] = [v + "X" for v in prop["examples"]]

    gen = _generated()
    for value in ("researcher@univ.edu", "S3cureP@ss!", "Jane Doe", "viewer"):
        gen = gen.replace("@example " + value, "@example " + value + "X")
    found = guard.failures(snapshot=_example_doc(change), generated=gen)
    assert len(found) == 1, found
    assert "_EXAMPLE_DIGEST" in found[0], found
    assert "count" not in found[0].lower(), found


def test_same_count_example_swap_is_caught_only_by_the_digest() -> None:
    """A permutation must not be dismissed as a count check in disguise."""

    def change(doc: dict) -> None:
        props = doc["components"]["schemas"]["LoginRequest"]["properties"]
        props["username"]["examples"], props["password"]["examples"] = (
            props["password"]["examples"],
            props["username"]["examples"],
        )

    found = guard.failures(snapshot=_example_doc(change))
    assert len(found) == 1, found
    assert "_EXAMPLE_DIGEST" in found[0], found
    assert "count" not in found[0].lower(), found


def test_a_dropped_snapshot_example_names_the_count_door() -> None:
    def change(doc: dict) -> None:
        doc["components"]["schemas"]["LoginRequest"]["properties"]["username"].pop(
            "examples"
        )

    found = guard.failures(snapshot=_example_doc(change))
    assert any("_EXPECTED_EXAMPLES pins 7" in problem for problem in found), found


def test_a_dropped_generated_tag_names_only_the_generated_count_door() -> None:
    gen = _generated().replace(
        "             * @example researcher@univ.edu\n", "", 1
    )
    found = guard.failures(
        snapshot=json.dumps(json.loads(guard.SNAPSHOT.read_text()), indent=2),
        generated=gen,
    )
    assert len(found) == 1, found
    assert "_EXPECTED_GENERATED_EXAMPLES pins 7" in found[0], found
    assert "_EXAMPLE_DIGEST" not in found[0], found


def test_the_description_decoy_is_not_counted_as_an_example() -> None:
    """``user@example.com`` lives in a @description block, not an @example tag."""
    gen = _generated()
    # The decoy line carries the substring but no strict JSDoc marker.
    decoy = next(line for line in gen.splitlines() if "user@example.com" in line)
    assert "@example" in decoy
    assert guard._GENERATED_EXAMPLE.search(decoy) is None
    assert len(guard.generated_examples(gen)) == 7
    # A naive substring scan counts 8; the strict marker must not inherit it.
    assert sum("@example" in line for line in gen.splitlines()) == 8
    assert not guard.failures()


def test_examples_repin_in_the_same_commit_stays_green() -> None:
    """A reviewed regenerate re-pins the example literal with the artifact."""

    def change(doc: dict) -> None:
        for name in ("LoginRequest", "UserCreate"):
            for prop in doc["components"]["schemas"][name]["properties"].values():
                if isinstance(prop, dict) and isinstance(prop.get("examples"), list):
                    prop["examples"] = [v + "X" for v in prop["examples"]]

    snapshot = _example_doc(change)
    gen = _generated()
    for value in ("researcher@univ.edu", "S3cureP@ss!", "Jane Doe", "viewer"):
        gen = gen.replace("@example " + value, "@example " + value + "X")
    new_digest = guard._example_digest(guard.example_rows(json.loads(snapshot)))
    assert new_digest != guard._EXAMPLE_DIGEST
    assert not guard.failures(
        snapshot=snapshot, generated=gen, example_digest=new_digest
    )


def test_door_five_self_test_plants_are_registered() -> None:
    """From a second file: the ablations exist and the clean control is green."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    assert "example_cases" in source
    for name in (
        "coordinated examples co-revert",
        "same-count example swap",
        "one-sided example dropped",
        "one-sided example added",
        "one-sided generated tag dropped",
        "forged generated tag invented",
    ):
        assert name in source, name


def test_zero_new_wiring_for_door_five() -> None:
    """The hot files #272/#273/#281 crashed into are deliberately untouched."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    assert "_EXAMPLE_DIGEST" in source
    # No new guard file: door 5 lives in an already-registered guard.
    assert not (ROOT / "scripts" / "check_openapi_published_examples.py").exists()


def _generated_defaults() -> str:
    return (
        ROOT / "packages" / "api-client" / "src" / "generated" / "openapi.d.ts"
    ).read_text(encoding="utf-8")


def test_the_generated_default_tag_pin_is_an_independent_literal() -> None:
    """The tag digest is a source literal, not derived from the artifact."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assigned = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_DEFAULT_TAG_DIGEST"
            for target in node.targets
        )
    ]
    assert len(assigned) == 1
    value = ast.literal_eval(assigned[0].value)
    assert isinstance(value, str) and len(value) == 64
    assert value == guard._default_tag_digest(
        guard.default_tag_rows(_generated_defaults())
    )


def test_the_committed_generated_tags_match_the_pinned_literal() -> None:
    """The clean committed generated half is the pinned projection."""
    rows_ = guard.default_tag_rows(_generated_defaults())
    assert len(rows_) == guard._EXPECTED_DEFAULT_TAGS
    assert guard._default_tag_digest(rows_) == guard._DEFAULT_TAG_DIGEST
    assert not guard.failures(generated=_generated_defaults())


def test_a_dropped_generated_default_tag_is_rejected() -> None:
    """The exact gap: delete one @default tag, snapshot untouched."""
    lines = _generated_defaults().splitlines(keepends=True)
    for index, line in enumerate(lines):
        if "@default" in line and line.lstrip().startswith("* @"):
            del lines[index]
            break
    else:
        raise AssertionError("no @default tag found to drop")
    found = guard.failures(generated="".join(lines))
    assert any("tag count is" in problem for problem in found), found
    assert any("generated default tags drifted" in problem for problem in found), found


def test_a_same_count_tag_relocation_is_caught_only_by_the_digest() -> None:
    """Move a tag between two fields; every count door must stay silent."""
    generated = _generated_defaults()
    moved = generated.replace(
        "            /** @default custom */\n"
        '            category: components["schemas"]["WidgetCategoryEnum"];',
        "            /** Template Path */\n"
        '            category: components["schemas"]["WidgetCategoryEnum"];',
        1,
    )
    moved = moved.replace(
        "            /** Template Path */\n            template_path: string;",
        "            /** @default custom */\n            template_path: string;",
        1,
    )
    assert moved != generated
    assert len(guard.default_tag_rows(moved)) == guard._EXPECTED_DEFAULT_TAGS
    found = guard.failures(generated=moved)
    # Only Door 6's digest fires: no snapshot door, no example door, no count.
    assert len(found) == 1, found
    assert "generated default tags drifted" in found[0], found


def test_the_generated_tag_pin_does_not_duplicate_the_example_floor() -> None:
    """@default and @example are two different published JSDoc projections."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    assert "default_tag_rows(generated)" in source
    assert "generated_examples(generated)" in source
    tags = guard.default_tag_rows(_generated_defaults())
    examples = guard.generated_examples(_generated_defaults())
    assert tags and examples and tags != examples


def test_a_repin_of_the_tag_digest_alone_stays_green() -> None:
    """A reviewed regenerate re-pins both halves in the same commit."""
    lines = _generated_defaults().splitlines(keepends=True)
    for index, line in enumerate(lines):
        if "@default" in line and line.lstrip().startswith("* @"):
            del lines[index]
            break
    edited = "".join(lines)
    new_digest = guard._default_tag_digest(guard.default_tag_rows(edited))
    assert new_digest != guard._DEFAULT_TAG_DIGEST
    assert not guard.failures(
        generated=edited,
        tag_digest=new_digest,
        expected_tags=guard._EXPECTED_DEFAULT_TAGS - 1,
    )


# ---------------------------------------------------------------------------
# Door 8 -- the generated half's @example values, not just their cardinality.
# ---------------------------------------------------------------------------


def test_a_one_sided_generated_value_rewrite_is_named_only_by_door_eight() -> None:
    """The residual: rewrite one @example value, keep all 7 tags."""
    gen = _generated().replace("@example Jane Doe", "@example John Roe", 1)
    assert len(guard.generated_examples(gen)) == guard._EXPECTED_GENERATED_EXAMPLES
    found = guard.failures(
        snapshot=json.dumps(json.loads(guard.SNAPSHOT.read_text()), indent=2),
        generated=gen,
    )
    assert len(found) == 1, found
    assert "generated @example values disagree" in found[0], found
    assert "_EXAMPLE_DIGEST" not in found[0], found
    assert "tag count" not in found[0].lower(), found


def test_a_same_count_generated_value_permutation_is_named() -> None:
    """Two distinct values swapped between tags: cardinality cannot see it."""
    gen = (
        _generated()
        .replace("@example Jane Doe", "@example __SWAP__", 1)
        .replace("@example viewer", "@example Jane Doe", 1)
        .replace("@example __SWAP__", "@example viewer", 1)
    )
    assert sorted(guard.generated_examples(gen)) == sorted(
        guard.generated_examples(_generated())
    )
    found = guard.failures(
        snapshot=json.dumps(json.loads(guard.SNAPSHOT.read_text()), indent=2),
        generated=gen,
    )
    assert len(found) == 1, found
    assert "generated @example values disagree" in found[0], found


def test_the_snapshot_side_drift_is_named_only_by_door_five() -> None:
    """Door 8 stands down when the snapshot digest drifts: full resolution."""

    def change(doc: dict) -> None:
        for name in ("LoginRequest", "UserCreate"):
            for prop in doc["components"]["schemas"][name]["properties"].values():
                if isinstance(prop, dict) and isinstance(prop.get("examples"), list):
                    prop["examples"] = [v + "X" for v in prop["examples"]]

    found = guard.failures(snapshot=_example_doc(change))
    assert len(found) == 1, found
    assert "_EXAMPLE_DIGEST" in found[0], found
    assert "@example values disagree" not in found[0], found


def test_door_eight_self_test_plants_are_registered() -> None:
    """From a second file: the two new ablations exist and are consumed."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    for name in (
        "one-sided generated example value rewritten",
        "same-count generated example value permutation",
    ):
        assert name in source, name
    assert "generated @example values disagree" in source


def test_door_eight_keeps_a_reviewed_repin_green() -> None:
    """A reviewed regenerate moves the digest AND both halves' values."""

    def change(doc: dict) -> None:
        for name in ("LoginRequest", "UserCreate"):
            for prop in doc["components"]["schemas"][name]["properties"].values():
                if isinstance(prop, dict) and isinstance(prop.get("examples"), list):
                    prop["examples"] = [v + "X" for v in prop["examples"]]

    snapshot = _example_doc(change)
    gen = _generated()
    for value in ("researcher@univ.edu", "S3cureP@ss!", "Jane Doe", "viewer"):
        gen = gen.replace("@example " + value, "@example " + value + "X")
    new_digest = guard._example_digest(guard.example_rows(json.loads(snapshot)))
    assert not guard.failures(
        snapshot=snapshot, generated=gen, example_digest=new_digest
    )


def test_door_eight_adds_no_new_wiring() -> None:
    """Zero smoke.sh / registry / teeth churn, exactly like door 5, 6 and 7."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    assert "generated @example values disagree" in source
    assert not (ROOT / "scripts" / "check_openapi_published_examples.py").exists()
    import subprocess

    for relative in (
        "scripts/smoke.sh",
        "scripts/check_contracts_registry_collection.py",
        "scripts/check_contracts_self_test_teeth.py",
    ):
        ours = (ROOT / relative).read_bytes()
        main = subprocess.check_output(
            ["git", "show", f"origin/main:{relative}"], cwd=ROOT
        )
        assert ours == main, relative
