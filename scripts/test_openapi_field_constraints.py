"""Regression coverage for ``scripts/check_openapi_field_constraints.py``.

The guard pins the 1790 published field-level values (865 constraints + 925
``default`` values) plus the published ``examples`` arrays and both generated
JSDoc projections to hand-written literals. These cases prove each failure
direction on real committed bytes, that each literal is independent of the
artifact it audits, and that the wiring cannot quietly rot. Collected by the
contracts layer's ``tests=()`` array; stdlib-only, no Python 3.15 needed.
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
    assert guard._EXPECTED_BY_KEY["default"] == 925
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    defaults = [(path, key, value) for path, key, value in guard.rows(document)
                if key == "default"]
    assert len(defaults) == 925


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
    new_value_digest = guard._generated_example_value_digest(
        guard.generated_example_rows(gen)
    )
    assert new_digest != guard._EXAMPLE_DIGEST
    assert not guard.failures(
        snapshot=snapshot,
        generated=gen,
        example_digest=new_digest,
        generated_example_value_digest=new_value_digest,
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
    # Door 6 names the relocated field; Door 7 sees the same move as a changed
    # (component, field, value) row. Both count doors and every snapshot door
    # stay silent -- that is the load-bearing part of this plant.
    assert len(found) == 2, found
    assert any("generated default tags drifted" in f for f in found), found
    assert any("generated default tag values drifted" in f for f in found), found
    assert not any("tag count is" in f for f in found), found


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
    new_value_digest = guard._default_tag_value_digest(
        guard.default_tag_values(edited)
    )
    assert new_digest != guard._DEFAULT_TAG_DIGEST
    assert new_value_digest != guard._DEFAULT_TAG_VALUE_DIGEST
    # A legitimate reviewed regenerate re-pins both halves' literals in the
    # same commit: dropping a tag changes the location rows and the value rows.
    assert not guard.failures(
        generated=edited,
        tag_digest=new_digest,
        tag_value_digest=new_value_digest,
        expected_tags=guard._EXPECTED_DEFAULT_TAGS - 1,
    )


# --- Door 7: the value written in each generated @default tag --------------


def test_generated_default_values_match_the_independent_literal() -> None:
    """924 named (component, field, value) rows; one bare tag is positional."""
    gen = _generated_defaults()
    rows_ = guard.default_tag_values(gen)
    assert len(rows_) == guard._EXPECTED_DEFAULT_TAGS == 924
    assert all(name and field for name, field, _ in rows_)
    assert guard._default_tag_value_digest(rows_) == guard._DEFAULT_TAG_VALUE_DIGEST
    bare = [(c, f) for c, f, v in rows_ if v == ""]
    assert bare == [("BlastHit", "subject_title")], bare


def test_the_generated_default_value_pin_is_an_independent_literal() -> None:
    """Re-deriving the value digest from the client would make it vacuous."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    assigned = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "_DEFAULT_TAG_VALUE_DIGEST"
            for t in node.targets
        )
    ]
    assert len(assigned) == 1
    value = ast.literal_eval(assigned[0].value)
    assert isinstance(value, str) and len(value) == 64
    assert value == guard._default_tag_value_digest(
        guard.default_tag_values(_generated_defaults())
    )
    # Separate literal from #297's location digest: a retyped value must not
    # be able to agree with the presence/location pin.
    assert value != guard._DEFAULT_TAG_DIGEST


def test_a_retyped_generated_default_value_with_blob_repin_is_rejected() -> None:
    """The decisive co-revert: one tag value retyped, generated_blob re-pinned.

    #297's Door 6 pins (component, field) presence, so it stays green: the
    location digest is unchanged and the count door holds. The snapshot's 925
    default rows are untouched too. Only Door 7 has to see it.
    """
    gen = _generated_defaults()
    needle = "             * @default 10000\n"
    assert gen.count(needle) == 1
    drifted = gen.replace(needle, "             * @default 9999\n", 1)
    found = guard.failures(generated=drifted)
    assert len(found) == 1, found
    assert "generated default tag values drifted" in found[0], found
    # Door 6 and every snapshot-side door are silent.
    assert guard._default_tag_digest(
        guard.default_tag_rows(drifted)
    ) == guard._DEFAULT_TAG_DIGEST


def test_a_same_count_generated_value_rotation_hits_only_door_seven() -> None:
    """Two distinct tag values swapped: location rows and count unchanged."""
    gen = _generated_defaults()
    a = "             * @default SNP\n"
    b = "             * @default genome\n"
    assert gen.count(a) == gen.count(b) == 1
    rotated = gen.replace(a, "@@A@@", 1).replace(b, a, 1).replace("@@A@@", b, 1)
    found = guard.failures(generated=rotated)
    assert len(found) == 1, found
    assert "generated default tag values drifted" in found[0], found
    assert guard._default_tag_digest(
        guard.default_tag_rows(rotated)
    ) == guard._DEFAULT_TAG_DIGEST
    assert len(guard.default_tag_rows(rotated)) == guard._EXPECTED_DEFAULT_TAGS


def test_filling_the_bare_generated_default_value_is_rejected() -> None:
    """The one empty-string default must stay a bare @default tag."""
    gen = _generated_defaults()
    bare = "             * @default\n"
    assert gen.count(bare) == 1
    filled = gen.replace(bare, "             * @default filled\n", 1)
    found = guard.failures(generated=filled)
    assert any("generated default tag values drifted" in f for f in found), found


def test_a_repin_of_the_value_digest_alone_stays_green() -> None:
    """A reviewed regenerate re-pins Door 7's literal with the client, once."""
    gen = _generated_defaults()
    drifted = gen.replace(
        "             * @default 10000\n", "             * @default 9999\n", 1
    )
    new_digest = guard._default_tag_value_digest(
        guard.default_tag_values(drifted)
    )
    assert new_digest != guard._DEFAULT_TAG_VALUE_DIGEST
    assert not guard.failures(
        generated=drifted,
        tag_value_digest=new_digest,
    )


def test_door_seven_self_test_plants_are_registered() -> None:
    """The guard's own self-test must plant a value retype, not just a drop."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    assert "generated @default value retyped" in source
    assert "same-count generated @default value rotation" in source
    assert "default_value_cases" in source


def test_zero_new_wiring_for_door_seven() -> None:
    """Door 7 lives in an already-registered guard; no smoke/registry/teeth edit."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    assert "def default_tag_values(" in source
    assert "_DEFAULT_TAG_VALUE_DIGEST" in source
# ---------------------------------------------------------------------------
# Door 8 -- the generated half's @example values, not just their cardinality.
# ---------------------------------------------------------------------------


def test_a_one_sided_generated_value_rewrite_is_named_only_by_door_eight() -> None:
    """The residual: rewrite one @example value, keep all 7 tags.

    Door 11 names the field; door 8 stands down so the drift is reported once.
    """
    gen = _generated().replace("@example Jane Doe", "@example John Roe", 1)
    assert len(guard.generated_examples(gen)) == guard._EXPECTED_GENERATED_EXAMPLES
    found = guard.failures(
        snapshot=json.dumps(json.loads(guard.SNAPSHOT.read_text()), indent=2),
        generated=gen,
    )
    assert len(found) == 1, found
    assert "generated @example values disagree" in found[0], found
    assert "UserCreate.full_name" in found[0], found
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
    assert len(found) == 2, found
    assert all("generated @example values disagree" in f for f in found), found
    assert "UserCreate.full_name" in found[0], found
    assert "UserCreate.role_name" in found[1], found


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
    new_value_digest = guard._generated_example_value_digest(
        guard.generated_example_rows(gen)
    )
    assert not guard.failures(
        snapshot=snapshot,
        generated=gen,
        example_digest=new_digest,
        generated_example_value_digest=new_value_digest,
    )


def test_door_eight_adds_no_new_wiring() -> None:
    """Zero smoke.sh / registry / teeth churn, exactly like door 5, 6 and 7."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    assert "generated @example values disagree" in source
    assert not (ROOT / "scripts" / "check_openapi_published_examples.py").exists()
    # A fresh single-branch CI checkout has no ``origin/main`` ref to diff
    # against: shelling out to ``git show origin/main:...`` produces one false
    # failure there for the wrong reason. Assert instead that the three hot
    # wiring files carry none of this door's identities -- no new guard call,
    # no new suite row, no new teeth signature. Same load-bearing claim, no
    # git dependency.
    for relative in (
        "scripts/smoke.sh",
        "scripts/check_contracts_registry_collection.py",
        "scripts/check_contracts_self_test_teeth.py",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "example_value_cases" not in text, relative
        assert "door_eight" not in text, relative
        assert "check_openapi_published_examples" not in text, relative


_AP_TARGET = "AdminSiteBrandResponse"


def _ap_co_revert() -> tuple[str, str]:
    """Flip one published ``false`` to ``true`` in both halves."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    node = document["components"]["schemas"][_AP_TARGET]
    assert node["additionalProperties"] is False
    node["additionalProperties"] = True
    generated = _generated()
    start = generated.find(f"        {_AP_TARGET}: {{")
    end = generated.find("\n        };", start)
    block = generated[start:end]
    assert "[key: string]" not in block
    drifted = (
        generated[:start]
        + block
        + "\n            [key: string]: unknown;"
        + generated[end:]
    )
    return json.dumps(document, indent=2), drifted


def test_additional_properties_digests_are_independent_literals() -> None:
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    assigned = {
        target.id
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert "_ADDITIONAL_PROPERTIES_DIGEST" in assigned
    assert "_CLIENT_ADDITIONAL_PROPERTIES_DIGEST" in assigned
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    rows = guard.additional_property_rows(document)
    assert guard._additional_properties_digest(rows) == guard._ADDITIONAL_PROPERTIES_DIGEST
    assert len(rows) == guard._EXPECTED_ADDITIONAL_PROPERTIES
    client = guard.client_additional_properties(_generated())
    assert (
        guard._client_additional_properties_digest(client)
        == guard._CLIENT_ADDITIONAL_PROPERTIES_DIGEST
    )
    assert len(client) == guard._EXPECTED_CLIENT_ADDITIONAL_PROPERTIES


def test_coordinated_additional_properties_co_revert_is_rejected() -> None:
    """Both halves agree; only the independent literals see the drift."""
    snapshot, generated = _ap_co_revert()
    found = guard.failures(snapshot=snapshot, generated=generated)
    assert any("additionalProperties drifted" in f for f in found), found
    assert any("index signatures drifted" in f for f in found), found


def test_same_commit_additional_properties_re_pin_stays_green() -> None:
    """A reviewed regenerate re-pins both literals with both artifacts."""
    snapshot, generated = _ap_co_revert()
    fresh = guard.failures(
        snapshot=snapshot,
        generated=generated,
        additional_digest=guard._additional_properties_digest(
            guard.additional_property_rows(json.loads(snapshot))
        ),
        client_additional_digest=guard._client_additional_properties_digest(
            guard.client_additional_properties(generated)
        ),
        expected_client_additional=len(
            guard.client_additional_properties(generated)
        ),
    )
    assert not fresh, fresh


def test_additional_properties_count_doors_are_load_bearing() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    del document["components"]["schemas"][_AP_TARGET]["additionalProperties"]
    found = guard.failures(snapshot=json.dumps(document, indent=2))
    assert any("row count is" in f for f in found), found


def test_generated_index_signature_door_is_load_bearing() -> None:
    """Dropping one client line alone must be named, not just counted."""
    generated = _generated()
    line = "            [key: string]: string;\n"
    assert generated.count(line) >= 1
    found = guard.failures(generated=generated.replace(line, "", 1))
    assert any("index signatures drifted" in f for f in found), found


def test_additional_properties_digest_doors_are_not_self_agreeing() -> None:
    """A single-file ``actual = pinned`` edit must fail the decisive case."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    gutted = source.replace(
        "    actual_additional = _additional_properties_digest(additional_rows_)",
        "    actual_additional = pinned_additional",
        1,
    ).replace(
        "    actual_client_additional = _client_additional_properties_digest(\n"
        "        client_additional_\n    )",
        "    actual_client_additional = pinned_client_additional",
        1,
    )
    assert gutted != source
    namespace: dict = {
        "__name__": "gutted_guard",
        "__file__": str(ROOT / "scripts" / guard.SELF),
    }
    exec(compile(gutted, str(ROOT / "scripts" / guard.SELF), "exec"), namespace)  # noqa: S102
    snapshot, generated = _ap_co_revert()
    found = namespace["failures"](
        snapshot=snapshot,
        generated=generated,
        expected_additional=len(
            namespace["additional_property_rows"](json.loads(snapshot))
        ),
        expected_client_additional=len(
            namespace["client_additional_properties"](generated)
        ),
    )
    assert not any("drifted" in f for f in found), found


def test_additional_properties_self_test_cases_are_registered() -> None:
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    assert "coordinated additionalProperties false->true" in source
    assert "same-commit re-pin stays green" in source


# ---------------------------------------------------------------------------
# Door 11 -- the field each generated @example tag is printed under.
# ---------------------------------------------------------------------------

_LOGIN_USERNAME_BLOCK = """            /**
             * Username
             * @description Email address or username
             * @default null
             * @example researcher@univ.edu
             */
            username: string | null;
            /**
             * Email
             * @description Email address (alternative to ``username``)
             * @default null
             * @example researcher@univ.edu
             */"""

_LOGIN_RELOCATED_BLOCK = """            /**
             * Username
             * @description Email address or username
             * @default null
             */
            username: string | null;
            /**
             * Email
             * @description Email address (alternative to ``username``)
             * @default null
             * @example researcher@univ.edu
             * @example researcher@univ.edu
             */"""


def _relocated() -> str:
    gen = _generated()
    assert gen.count(_LOGIN_USERNAME_BLOCK) == 1
    return gen.replace(_LOGIN_USERNAME_BLOCK, _LOGIN_RELOCATED_BLOCK, 1)


def test_a_tag_relocated_between_two_fields_is_named() -> None:
    """The flat door 8 sequence survives a same-value tag relocation."""
    gen = _relocated()
    assert guard.generated_examples(gen) == guard.generated_examples(_generated())
    found = guard.failures(
        snapshot=json.dumps(json.loads(guard.SNAPSHOT.read_text()), indent=2),
        generated=gen,
    )
    assert len(found) == 2, found
    assert any("LoginRequest.username" in f for f in found), found
    assert any("LoginRequest.email" in f for f in found), found


def test_door_eleven_off_leaves_the_relocation_silent() -> None:
    """Without door 11, live main's flat comparison cannot see the drift."""
    found = guard.failures(
        snapshot=json.dumps(json.loads(guard.SNAPSHOT.read_text()), indent=2),
        generated=_relocated(),
        pin_example_fields=False,
    )
    assert not found, found


def test_the_example_tag_reader_uses_finditer() -> None:
    """Two @example tags in one doc block are two published values, not one."""
    gen = _generated().replace(
        "             * @example Jane Doe\n",
        "             * @example Jane Doe\n             * @example Jane Doe\n",
        1,
    )
    rows = [
        row
        for row in guard.generated_example_rows(gen)
        if row[:2] == ("UserCreate", "full_name")
    ]
    assert len(rows) == 2, rows


def test_a_stray_tag_is_resolved_by_the_count_door_alone() -> None:
    """Cardinality drift is door 5's; door 11 stands down, no double report."""
    gen = _generated().replace(
        "             * @example Jane Doe\n",
        "             * @example Jane Doe\n             * @example Jane Doe\n",
        1,
    )
    found = guard.failures(
        snapshot=json.dumps(json.loads(guard.SNAPSHOT.read_text()), indent=2),
        generated=gen,
    )
    assert len(found) == 1, found
    assert "tag count is 8" in found[0], found


def test_door_eleven_stands_down_on_a_snapshot_drift() -> None:
    """A snapshot-side rewrite stays door 5's alone, never counted twice."""

    def change(doc: dict) -> None:
        doc["components"]["schemas"]["UserCreate"]["properties"]["full_name"][
            "examples"
        ] = ["John Roe"]

    found = guard.failures(snapshot=_example_doc(change))
    assert len(found) == 1, found
    assert "_EXAMPLE_DIGEST" in found[0], found


def test_door_eleven_adds_no_new_wiring() -> None:
    """One guard, one ledger: no new guard file or wiring row."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    assert "def generated_example_rows(" in source
    assert "def example_projection(" in source
    assert not (ROOT / "scripts" / "check_openapi_example_fields.py").exists()
    for text in (SMOKE, REGISTRY, TEETH):
        assert "example_field_cases" not in text
        assert "check_openapi_example_fields" not in text


def test_door_eleven_self_test_plants_are_registered() -> None:
    """From a second file: the ablation exists and is consumed."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    assert "one @example tag relocated between two fields" in source
    assert "pin_example_fields=False" in source


# ---------------------------------------------------------------------------
# Door 12 -- an independent literal for the 7 generated @example values.
# ---------------------------------------------------------------------------


def _both_halves_example_rewrite() -> tuple[str, str, str]:
    """A regenerate shape: one published value moved in BOTH halves.

    The snapshot digest is honestly re-pinned to the derived value, as a
    reviewed regenerate requires. Both artifacts now publish ``John Roe``;
    every two-artifact door agrees with itself.
    """

    def change(doc: dict) -> None:
        doc["components"]["schemas"]["UserCreate"]["properties"]["full_name"][
            "examples"
        ] = ["John Roe"]

    snapshot = _example_doc(change)
    generated = _generated().replace("@example Jane Doe", "@example John Roe", 1)
    assert generated != _generated()
    new_digest = guard._example_digest(guard.example_rows(json.loads(snapshot)))
    assert new_digest != guard._EXAMPLE_DIGEST
    return snapshot, generated, new_digest


def test_the_generated_example_value_pin_is_an_independent_literal() -> None:
    """The new digest is a module-level literal, not derived from artifacts."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assigned = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "_GENERATED_EXAMPLE_VALUE_DIGEST"
            for target in node.targets
        )
    ]
    assert len(assigned) == 1
    assert ast.literal_eval(assigned[0].value) == guard._GENERATED_EXAMPLE_VALUE_DIGEST
    assert guard._GENERATED_EXAMPLE_VALUE_DIGEST != guard._EXAMPLE_DIGEST
    assert guard._GENERATED_EXAMPLE_VALUE_DIGEST != guard._DEFAULT_TAG_VALUE_DIGEST


def test_committed_generated_example_values_match_the_pinned_literal() -> None:
    rows = guard.generated_example_rows(_generated())
    assert len(rows) == guard._EXPECTED_GENERATED_EXAMPLE_VALUE_ROWS
    assert guard._generated_example_value_digest(rows) == (
        guard._GENERATED_EXAMPLE_VALUE_DIGEST
    )


def test_a_coordinated_both_halves_example_rewrite_is_rejected() -> None:
    """The R2 residual: both halves move together, digest honestly re-pinned.

    Doors 8 / 11 read the snapshot as their reference, so they agree with the
    regenerate; the count doors and the re-pinned snapshot digest stay silent.
    Only the independent generated-value literal can name it.
    """
    snapshot, generated, new_digest = _both_halves_example_rewrite()
    found = guard.failures(
        snapshot=snapshot, generated=generated, example_digest=new_digest
    )
    assert len(found) == 1, found
    assert "_GENERATED_EXAMPLE_VALUE_DIGEST" in found[0], found
    assert "published examples drifted" not in found[0], found
    assert "tag count is" not in found[0], found


def test_re_pinning_only_the_snapshot_digest_is_no_longer_enough() -> None:
    """The topology's old 'one deliberate act' now needs a second one."""
    snapshot, generated, new_digest = _both_halves_example_rewrite()
    assert guard.failures(
        snapshot=snapshot, generated=generated, example_digest=new_digest
    )


def test_a_reviewed_both_halves_re_pin_stays_green() -> None:
    """Re-pin BOTH literals in the same commit: not a dead witness."""
    snapshot, generated, new_digest = _both_halves_example_rewrite()
    new_value_digest = guard._generated_example_value_digest(
        guard.generated_example_rows(generated)
    )
    assert new_value_digest != guard._GENERATED_EXAMPLE_VALUE_DIGEST
    assert not guard.failures(
        snapshot=snapshot,
        generated=generated,
        example_digest=new_digest,
        generated_example_value_digest=new_value_digest,
    )


def test_door_twelve_does_not_double_report_a_one_sided_rewrite() -> None:
    """A one-sided generated rewrite stays door 11's named-field failure."""
    generated = _generated().replace("@example Jane Doe", "@example John Roe", 1)
    found = guard.failures(
        snapshot=json.dumps(json.loads(guard.SNAPSHOT.read_text()), indent=2),
        generated=generated,
    )
    assert len(found) == 1, found
    assert "UserCreate.full_name" in found[0], found
    assert "_GENERATED_EXAMPLE_VALUE_DIGEST" not in found[0], found


def test_door_twelve_does_not_double_report_a_tag_relocation() -> None:
    """A same-value relocation stays door 11's two named fields."""
    found = guard.failures(
        snapshot=json.dumps(json.loads(guard.SNAPSHOT.read_text()), indent=2),
        generated=_relocated(),
    )
    assert len(found) == 2, found
    assert all("_GENERATED_EXAMPLE_VALUE_DIGEST" not in f for f in found), found


def test_door_twelve_stands_down_on_a_snapshot_drift() -> None:
    """A snapshot-side rewrite is door 5's alone, never counted twice."""

    def change(doc: dict) -> None:
        doc["components"]["schemas"]["UserCreate"]["properties"]["full_name"][
            "examples"
        ] = ["John Roe"]

    found = guard.failures(snapshot=_example_doc(change))
    assert len(found) == 1, found
    assert "_EXAMPLE_DIGEST" in found[0], found


def test_door_twelve_adds_no_new_wiring() -> None:
    """One guard, one ledger: no new guard file or wiring row."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    assert "def _generated_example_value_digest(" in source
    assert "_GENERATED_EXAMPLE_VALUE_DIGEST" in source
    for text in (SMOKE, REGISTRY, TEETH):
        assert "independent_value_cases" not in text, text
        assert "GENERATED_EXAMPLE_VALUE_DIGEST" not in text, text


def test_door_twelve_self_test_plants_are_registered() -> None:
    """From a second file: the decisive ablation and both controls exist."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    assert "coordinated both-halves example rewrite" in source
    assert "reviewed example-value re-pin stays green" in source
    assert "re-pinning only the snapshot digest does not agree" in source


def test_door_twelve_digest_is_load_bearing() -> None:
    """A single-file ``actual = pinned`` edit must fail the decisive case."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    gutted = source.replace(
        "    actual_generated_example_values = _generated_example_value_digest(\n"
        "        printed_example_rows\n"
        "    )",
        "    actual_generated_example_values = pinned_generated_example_digest",
        1,
    )
    assert gutted != source
    namespace: dict = {
        "__name__": "gutted_guard",
        "__file__": str(ROOT / "scripts" / guard.SELF),
    }
    exec(compile(gutted, str(ROOT / "scripts" / guard.SELF), "exec"), namespace)  # noqa: S102
    snapshot, generated, new_digest = _both_halves_example_rewrite()
    found = namespace["failures"](
        snapshot=snapshot, generated=generated, example_digest=new_digest
    )
    assert not any("_GENERATED_EXAMPLE_VALUE_DIGEST" in f for f in found), found


def _concurrent_decoy() -> tuple[str, str, str]:
    """A coordinated both-halves rewrite with a one-sided decoy alongside it.

    The coordinated half moves ``UserCreate.full_name`` to ``John Roe`` in the
    snapshot and in ``openapi.d.ts`` with ``_EXAMPLE_DIGEST`` honestly
    re-pinned -- the shape door 12 exists to name. The decoy swaps
    ``LoginRequest.username``'s tag in the generated half only, so the two
    halves already disagree when door 12 asks.
    """
    snapshot, generated, new_digest = _both_halves_example_rewrite()
    assert generated.count(_LOGIN_DECOY_BLOCK) == 1
    decoy = generated.replace(_LOGIN_DECOY_BLOCK, _LOGIN_DECOY_BLOCK_DECOYED, 1)
    assert decoy != generated
    return snapshot, decoy, new_digest


_LOGIN_DECOY_BLOCK = _LOGIN_USERNAME_BLOCK
_LOGIN_DECOY_BLOCK_DECOYED = _LOGIN_USERNAME_BLOCK.replace(
    "             * @example researcher@univ.edu\n"
    "             */\n"
    "            username",
    "             * @example decoy@univ.edu\n"
    "             */\n"
    "            username",
    1,
)
assert _LOGIN_DECOY_BLOCK_DECOYED != _LOGIN_DECOY_BLOCK


def test_a_concurrent_decoy_defers_door_twelve_onto_door_eleven() -> None:
    """The measured concurrent shape: the decoy is named, door 12 stands down.

    Door 12 is single-cause. One coordinated both-halves rewrite *plus* one
    one-sided ``LoginRequest.username`` decoy yields exactly one failure, and
    it is door 11's named field -- not the independent literal. Both halves of
    the coordinated move are present and the snapshot digest is re-pinned, so
    a door that fired concurrently would be naming a value the verified tree
    cannot yet resolve.
    """
    snapshot, generated, new_digest = _concurrent_decoy()
    found = guard.failures(
        snapshot=snapshot, generated=generated, example_digest=new_digest
    )
    assert len(found) == 1, found
    assert "LoginRequest.username" in found[0], found
    assert "_GENERATED_EXAMPLE_VALUE_DIGEST" not in found[0], found
    # The coordinated value really is present in the generated half: door 12
    # is silent on a drift it could see, not on an absent one.
    assert guard._generated_example_value_digest(
        guard.generated_example_rows(generated)
    ) != guard._GENERATED_EXAMPLE_VALUE_DIGEST


def test_resolving_the_decoy_re_arms_door_twelve() -> None:
    """Deferred, not permanent: drop the decoy and the literal fires again."""
    _, _, new_digest = _concurrent_decoy()
    clean_snapshot, clean_generated, _ = _both_halves_example_rewrite()
    armed = guard.failures(
        snapshot=clean_snapshot,
        generated=clean_generated,
        example_digest=new_digest,
    )
    assert len(armed) == 1, armed
    assert "_GENERATED_EXAMPLE_VALUE_DIGEST" in armed[0], armed
    assert "LoginRequest.username" not in armed[0], armed
    # And reverting the coordinated rewrite ships nothing at all.
    assert not guard.failures()


def test_door_eleven_keeps_the_snapshot_reference_door_twelve_gates_on() -> None:
    """The precedence, read from the source: replacement, not addition.

    Door 11 still compares the snapshot projection to the printed rows; door
    12 derives its literal from those same printed rows and gates on the
    *absence* of door 11's drift. That conjunction is why a coordinated
    both-halves move leaves door 11 silent and is never pre-empted.
    """
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    tree = ast.parse(source)
    by_name = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    compared = [
        node
        for node in ast.walk(by_name["failures"])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "example_field_drift"
    ]
    rendered = sorted(ast.unparse(call) for call in compared)
    assert rendered == [
        "example_field_drift(example_projection(document), printed_example_rows)",
        "example_field_drift(example_projection(document), printed_example_rows)",
    ], rendered
    # One call is door 11's own comparison, the other is door 12's gate; the
    # gate is negated, the door is not.
    gate = guard_source_gate(tree, by_name["failures"])
    assert gate is not None, "door 12 no longer gates on example_field_drift(...)"
    # The literal derives from the printed rows, not from the snapshot half.
    assert (
        "actual_generated_example_values = _generated_example_value_digest(\n"
        "        printed_example_rows\n"
        "    )"
    ) in source


def guard_source_gate(
    tree: ast.Module, function: ast.FunctionDef
) -> ast.UnaryOp | None:
    """The ``not example_field_drift(...)`` operand inside an ``and`` chain."""
    for node in ast.walk(function):
        if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.And):
            continue
        for operand in node.values:
            if not isinstance(operand, ast.UnaryOp):
                continue
            if not isinstance(operand.op, ast.Not):
                continue
            call = operand.operand
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "example_field_drift"
            ):
                inner = ast.unparse(call)
                if inner == (
                    "example_field_drift("
                    "example_projection(document), printed_example_rows)"
                ):
                    return operand
    return None


def test_the_guard_docstring_names_the_measured_behaviour() -> None:
    """The prose cannot quietly drift back to an unconditional claim."""
    doc = guard.__doc__ or ""
    assert isinstance(doc, str) and doc
    assert "when that\n  rewrite is the only cause" in doc, doc[:400]
    for phrase in (
        "deferred, not permanent",
        "Resolve the\n  concurrent drift",
        "Door 12 stands down whenever",
        "three-clause\n  conjunction",
        "*any* concurrent drift",
        "the count door",
    ):
        assert phrase in doc, phrase
    # The old door-11-specific overstatement must be gone.
    assert "A concurrent one-sided drift" not in doc
    # The old unconditional claim must be gone.
    assert "It closes the coordinated both-halves\n  cell" not in doc
    # And the precedence is stated: replacement of the generated-half
    # reference, not an addition beside door 11's snapshot reference.
    assert "*replaces*" in doc
    assert "door 11 keeps reading the snapshot" in doc
    # Words are not the claim: an inverted sentence keeps both and still passes.
    # Bind both measured shapes from #363, not just the vocabulary.
    assert "precedence" in doc
    assert "firing" in doc
    assert "cannot make door 12 fire on an in-region ghost" in doc
    assert "it takes narrowing\n  it and the door-11 clause together" in doc
    assert "named first by the\n  count door, not by door 11" in doc


# ---------------------------------------------------------------------------
# Door 12 -- the stand-down is a three-clause conjunction, not one clause.
# ---------------------------------------------------------------------------

_MARK_READ_IDS_BLOCK = """            /**
             * Ids
             * @default null
             */
            ids: string[] | null;"""
_MARK_READ_IDS_DECOYED = """            /**
             * Ids
             * @default null
             * @example decoy_ghost
             */
            ids: string[] | null;"""


def _generated_side_decoy_rewrite() -> tuple[str, str, str, str]:
    """Coordinated both-halves rewrite PLUS one generated-side decoy.

    ``UserCreate.full_name`` moves to ``John Roe`` in both halves with
    ``_EXAMPLE_DIGEST`` honestly re-derived; a stray ``* @example `` tag is
    then printed under ``MarkReadRequest.ids``, a field whose snapshot
    publishes no examples at all. The count door owns the ghost (``8 != 7``),
    door 11 stands down on the cardinality drift, and door 12 must defer --
    it is a conjunction of three stand-downs, not just door 11's field drift.
    """
    snapshot, generated, new_digest = _both_halves_example_rewrite()
    assert generated.count(_MARK_READ_IDS_BLOCK) == 1
    decoy = generated.replace(_MARK_READ_IDS_BLOCK, _MARK_READ_IDS_DECOYED, 1)
    assert decoy != generated
    return snapshot, generated, decoy, new_digest


def test_door_twelve_defers_to_a_generated_side_decoy() -> None:
    """The count door, not door 11, owns a stray tag; door 12 stays silent."""
    snapshot, generated, decoy, new_digest = _generated_side_decoy_rewrite()
    assert len(guard.generated_examples(decoy)) == (
        guard._EXPECTED_GENERATED_EXAMPLES + 1
    )
    resolved = guard.failures(
        snapshot=snapshot, generated=generated, example_digest=new_digest
    )
    assert len(resolved) == 1, resolved
    assert "_GENERATED_EXAMPLE_VALUE_DIGEST" in resolved[0], resolved
    found = guard.failures(
        snapshot=snapshot, generated=decoy, example_digest=new_digest
    )
    assert len(found) == 1, found
    assert "tag count is" in found[0], found
    assert all("_GENERATED_EXAMPLE_VALUE_DIGEST" not in f for f in found), found
    assert all("generated @example tags" not in f for f in found), found


def test_the_generated_side_decoy_owns_the_count_door_not_door_eleven() -> None:
    """A strict marker outside the schemas region is also count-door only."""
    snapshot, generated, _decoy, new_digest = _generated_side_decoy_rewrite()
    stray = generated + "\n/**\n * @example stray_outside_region\n */\n"
    assert len(guard.generated_example_rows(stray)) == (
        guard._EXPECTED_GENERATED_EXAMPLE_VALUE_ROWS
    )
    found = guard.failures(
        snapshot=snapshot, generated=stray, example_digest=new_digest
    )
    assert len(found) == 1, found
    assert "tag count is" in found[0], found
    assert all("_GENERATED_EXAMPLE_VALUE_DIGEST" not in f for f in found), found


def test_resolving_the_generated_side_decoy_re_arms_door_twelve() -> None:
    """Deferred, not permanent: remove the ghost and the value is named."""
    snapshot, generated, decoy, new_digest = _generated_side_decoy_rewrite()
    assert not any(
        "_GENERATED_EXAMPLE_VALUE_DIGEST" in f
        for f in guard.failures(
            snapshot=snapshot, generated=decoy, example_digest=new_digest
        )
    )
    found = guard.failures(
        snapshot=snapshot, generated=generated, example_digest=new_digest
    )
    assert len(found) == 1, found
    assert "_GENERATED_EXAMPLE_VALUE_DIGEST" in found[0], found
    assert guard.failures() == []


def test_door_twelve_defers_to_the_snapshot_digest_clause() -> None:
    """Door 5 is a stand-down too: no honest re-pin, no door 12."""
    snapshot, generated, _decoy, _new_digest = _generated_side_decoy_rewrite()
    found = guard.failures(snapshot=snapshot, generated=generated)
    assert len(found) == 1, found
    assert "_EXAMPLE_DIGEST" in found[0], found
    assert all("_GENERATED_EXAMPLE_VALUE_DIGEST" not in f for f in found), found


def test_door_twelve_defers_to_the_door_eleven_clause() -> None:
    """Door 11 is the third stand-down: a one-sided rewrite stays its own."""
    generated = _generated().replace("@example Jane Doe", "@example John Roe", 1)
    found = guard.failures(
        snapshot=json.dumps(json.loads(guard.SNAPSHOT.read_text()), indent=2),
        generated=generated,
    )
    assert len(found) == 1, found
    assert "UserCreate.full_name" in found[0], found
    assert all("_GENERATED_EXAMPLE_VALUE_DIGEST" not in f for f in found), found


def test_the_stand_down_conjunction_has_three_clauses() -> None:
    """From a second file: narrowing the conjunction to one clause is red."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    tree = ast.parse(source)
    gates = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "example_value_drift"
            for target in node.targets
        )
    ]
    assert len(gates) == 1
    gate = gates[0]
    assert isinstance(gate, ast.BoolOp) and isinstance(gate.op, ast.And)
    clauses = [ast.unparse(value) for value in gate.values]
    assert clauses[:3] == [
        "actual_example_digest == pinned_example_digest",
        "len(gen_examples) == pinned_generated",
        "not example_field_drift(example_projection(document), printed_example_rows)",
    ], clauses
    assert len(clauses) == 4, clauses


def test_narrowing_the_conjunction_double_reports_a_drift() -> None:
    """Each stand-down is load-bearing, exposed by a distinct shape."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    coordinated, generated, _decoy, new_digest = _generated_side_decoy_rewrite()
    clean_snapshot = json.dumps(json.loads(guard.SNAPSHOT.read_text()), indent=2)
    one_sided = _generated().replace("@example Jane Doe", "@example John Roe", 1)
    stray = generated + "\n/**\n * @example stray_outside_region\n */\n"
    # Removing a clause must make its own owning shape double-report.
    cases = (
        (
            "        actual_example_digest == pinned_example_digest\n        and ",
            "        ",
            dict(snapshot=coordinated, generated=generated),
        ),
        (
            "        and len(gen_examples) == pinned_generated\n",
            "",
            dict(
                snapshot=coordinated,
                generated=stray,
                example_digest=new_digest,
            ),
        ),
        (
            "        and not example_field_drift(\n"
            "            example_projection(document), printed_example_rows\n"
            "        )\n",
            "",
            dict(snapshot=clean_snapshot, generated=one_sided),
        ),
    )
    for removed, replacement, shape in cases:
        narrowed = source.replace(removed, replacement, 1)
        assert narrowed != source
        namespace: dict = {
            "__name__": "narrowed_guard",
            "__file__": str(ROOT / "scripts" / guard.SELF),
        }
        exec(  # noqa: S102
            compile(narrowed, str(ROOT / "scripts" / guard.SELF), "exec"),
            namespace,
        )
        intact = guard.failures(**shape)
        assert not any(
            "_GENERATED_EXAMPLE_VALUE_DIGEST" in f for f in intact
        ), (removed, intact)
        found = namespace["failures"](**shape)
        assert any("_GENERATED_EXAMPLE_VALUE_DIGEST" in f for f in found), (
            removed,
            found,
        )

def _narrow(source: str, *removals: str) -> dict:
    """Compile the guard with one or more conjunction clauses removed."""
    narrowed = source
    for removed in removals:
        assert removed in narrowed, removed
        narrowed = narrowed.replace(removed, "", 1)
    assert narrowed != source
    namespace: dict = {
        "__name__": "narrowed_guard",
        "__file__": str(ROOT / "scripts" / guard.SELF),
    }
    exec(  # noqa: S102
        compile(narrowed, str(ROOT / "scripts" / guard.SELF), "exec"),
        namespace,
    )
    return namespace


_COUNT_CLAUSE = "        and len(gen_examples) == pinned_generated\n"
_FIELD_CLAUSE = (
    "        and not example_field_drift(\n"
    "            example_projection(document), printed_example_rows\n"
    "        )\n"
)


def test_an_in_region_ghost_keeps_the_count_clause_precedence_only() -> None:
    """The receipt's shape: narrowing the count clause cannot re-arm door 12.

    A ghost printed under ``MarkReadRequest.ids`` sits inside the schemas
    region, so it mutates both ``generated_example_rows`` (the value digest)
    and ``example_field_drift``. With the other three clauses intact, removing
    the count clause changes which failure is named first but cannot make
    door 12 fire; it takes removing the count *and* the field-drift clause.
    """
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    snapshot, _clean, ghost, new_digest = _generated_side_decoy_rewrite()
    shape = dict(snapshot=snapshot, generated=ghost, example_digest=new_digest)
    intact = guard.failures(**shape)
    assert len(intact) == 1, intact
    assert "tag count is" in intact[0], intact
    assert not any("_GENERATED_EXAMPLE_VALUE_DIGEST" in f for f in intact)

    count_only = _narrow(source, _COUNT_CLAUSE)["failures"](**shape)
    assert not any("_GENERATED_EXAMPLE_VALUE_DIGEST" in f for f in count_only), (
        count_only
    )
    both = _narrow(source, _COUNT_CLAUSE, _FIELD_CLAUSE)["failures"](**shape)
    assert any("_GENERATED_EXAMPLE_VALUE_DIGEST" in f for f in both), both
    assert len(both) > len(intact), both


def test_an_out_of_region_ghost_keeps_the_count_clause_load_bearing() -> None:
    """The checked-in shape: a marker outside the schemas region has teeth.

    That stray tag bumps ``generated_examples`` but never reaches
    ``generated_example_rows``, so the value digest still disagrees while the
    field drift is empty. Narrowing the count clause alone double-reports.
    This is why the count clause is precedence, not decoration.
    """
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    coordinated, generated, _ghost, new_digest = (
        _generated_side_decoy_rewrite()
    )
    stray = generated + "\n/**\n * @example stray_outside_region\n */\n"
    shape = dict(
        snapshot=coordinated, generated=stray, example_digest=new_digest
    )
    intact = guard.failures(**shape)
    assert len(intact) == 1, intact
    assert "tag count is" in intact[0], intact
    narrowed = _narrow(source, _COUNT_CLAUSE)["failures"](**shape)
    assert any("_GENERATED_EXAMPLE_VALUE_DIGEST" in f for f in narrowed), (
        narrowed
    )
    assert len(narrowed) > len(intact), narrowed
