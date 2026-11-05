"""Regression coverage for ``scripts/check_openapi_schema_descriptions.py``.

The guard pins 257 published component-schema ``description`` strings and 2327
``title`` strings to hand-written literals and checks the generated client's
JSDoc lines against them. These cases prove each failure direction on real
committed bytes: the decisive byte-preserving co-revert of both halves (with
provenance blob ids re-pinned) still fails via the digests, a one-sided client
edit is named, each digest is independent of the artifact it audits, the count
doors are load-bearing, and the generated half cannot be silently dropped.

Collected by the contracts layer's ``tests=()`` array; stdlib-only, no Python
3.15 needed. Plants are built from the *current* committed value, so a tree
that already drifted is reported by ``test_committed_tree_passes`` rather than
by a brittle assertion inside a fixture.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_openapi_schema_descriptions as guard

_SNAPSHOT = guard.SNAPSHOT.read_text(encoding="utf-8")
_GENERATED = guard.GENERATED.read_text(encoding="utf-8")

_TARGET_SCHEMA = "EnrichmentGseaResponse"
_TARGET_FIELD = "mode"


def _committed_value() -> str:
    document = json.loads(_SNAPSHOT)
    return document["components"]["schemas"][_TARGET_SCHEMA]["properties"][
        _TARGET_FIELD
    ]["description"]


def _drifted_value() -> str:
    return _committed_value() + " (planted drift)"


def _snapshot_with(change) -> str:
    """Byte-preserving single-string rewrite, not a re-serialize."""
    document = json.loads(_SNAPSHOT)
    target = document["components"]["schemas"][_TARGET_SCHEMA]["properties"][
        _TARGET_FIELD
    ]
    before = target["description"]
    change(target)
    after = target["description"]
    needle = f'"description": "{before}"'
    anchor = f'"{_TARGET_SCHEMA}": {{'
    start = _SNAPSHOT.index(anchor)
    segment = _SNAPSHOT[start : start + 4000]
    assert needle in segment
    rewritten = segment.replace(needle, f'"description": "{after}"', 1)
    return _SNAPSHOT[:start] + rewritten + _SNAPSHOT[start + 4000 :]


def _generated_with(value: str) -> str:
    return _GENERATED.replace(
        f"* @description {_committed_value()}\n", f"* @description {value}\n"
    )


def test_committed_tree_passes() -> None:
    assert guard.failures(snapshot=_SNAPSHOT, generated=_GENERATED) == []


def test_decisive_co_revert_is_rejected() -> None:
    """Both halves move together; only the independent digest can see it."""
    snapshot = _snapshot_with(
        lambda node: node.__setitem__("description", _drifted_value())
    )
    generated = _generated_with(_drifted_value())
    assert snapshot != _SNAPSHOT and generated != _GENERATED
    found = guard.failures(snapshot=snapshot, generated=generated)
    assert any("_SCHEMA_DESCRIPTION_DIGEST" in f for f in found), found
    # The generated half is compared with the *pinned* literal, not with the
    # drifted snapshot: a co-revert of both halves cannot pass by agreement.
    assert any("@description lines disagree" in f for f in found), found


def test_one_sided_client_rewrite_is_rejected() -> None:
    generated = _generated_with(_drifted_value())
    found = guard.failures(snapshot=_SNAPSHOT, generated=generated)
    assert any("@description lines disagree" in f for f in found), found


def test_one_sided_snapshot_rewrite_is_rejected() -> None:
    snapshot = _snapshot_with(
        lambda node: node.__setitem__("description", _drifted_value())
    )
    found = guard.failures(snapshot=snapshot, generated=_GENERATED)
    assert any("_SCHEMA_DESCRIPTION_DIGEST" in f for f in found), found
    assert any("@description lines disagree" in f for f in found), found


def test_digest_is_an_independent_literal() -> None:
    """The committed literal must be the real fixed point, not a re-pin."""
    assert guard._SCHEMA_DESCRIPTION_DIGEST == guard._digest(
        guard.rows(json.loads(_SNAPSHOT))
    )
    snapshot = _snapshot_with(
        lambda node: node.__setitem__("description", _drifted_value())
    )
    drifted_digest = guard._digest(guard.rows(json.loads(snapshot)))
    assert drifted_digest != guard._SCHEMA_DESCRIPTION_DIGEST
    # Passing the drifted digest is the re-pin escape hatch; the generated
    # half, pinned to the committed literal, still names the drift.
    found = guard.failures(snapshot=snapshot, digest=drifted_digest)
    assert any("@description lines disagree" in f for f in found), found


def test_count_doors_are_load_bearing() -> None:
    """Dropping one description but re-pinning the digest still names the count."""
    document = json.loads(_SNAPSHOT)
    node = document["components"]["schemas"][_TARGET_SCHEMA]["properties"][
        _TARGET_FIELD
    ]
    del node["description"]
    snapshot = json.dumps(document, indent=2, ensure_ascii=False)
    digest = guard._digest(guard.rows(document))
    found = guard.failures(snapshot=snapshot, digest=digest)
    assert any("_EXPECTED_ROWS pins" in f for f in found), found


def test_same_count_rotation_is_rejected() -> None:
    """Three distinct values rotated leave every count door green."""
    document = json.loads(_SNAPSHOT)
    picked: list[dict] = []
    seen: set[str] = set()
    for schema in document["components"]["schemas"].values():
        for node in (schema.get("properties") or {}).values():
            value = node.get("description")
            if (
                isinstance(value, str)
                and "\n" not in value
                and value not in seen
            ):
                seen.add(value)
                picked.append(node)
            if len(picked) == 3:
                break
        if len(picked) == 3:
            break
    assert len(picked) == 3
    values = [node["description"] for node in picked]
    for index, node in enumerate(picked):
        node["description"] = values[(index + 1) % 3]
    rotated = guard.rows(document)
    assert len(rotated) == guard._EXPECTED_ROWS
    assert Counter(v for _, v in rotated) == Counter(
        v for _, v in guard.rows(json.loads(_SNAPSHOT))
    )
    snapshot = json.dumps(document, indent=2, ensure_ascii=False)
    found = guard.failures(snapshot=snapshot, generated=_GENERATED)
    assert any("_SCHEMA_DESCRIPTION_DIGEST" in f for f in found), found


def test_generated_half_is_pinned_to_the_literal() -> None:
    """The client check compares against pinned rows, not the drifted snapshot."""
    drifted = _snapshot_with(
        lambda node: node.__setitem__("description", _drifted_value())
    )
    generated = _generated_with(_drifted_value())
    assert guard.failures(snapshot=drifted, generated=generated)
    found = guard.failures(
        snapshot=drifted,
        generated=generated,
        digest=guard._digest(guard.rows(json.loads(drifted))),
    )
    assert any("@description lines disagree" in f for f in found), found


def test_synthetic_client_line_is_reviewed() -> None:
    """Exactly one generator-synthesized description is allowed."""
    lines = guard.client_descriptions(_GENERATED)
    assert lines.count(guard._SYNTHETIC_CLIENT_DESCRIPTION) == 1


_TITLE_SCHEMA = "AdminDashboardStats"
_TITLE_FIELD = "totalUsers"


def _committed_title() -> str:
    document = json.loads(_SNAPSHOT)
    return document["components"]["schemas"][_TITLE_SCHEMA]["properties"][
        _TITLE_FIELD
    ]["title"]


def _drifted_title() -> str:
    return _committed_title() + " (planted drift)"


def _snapshot_with_title(value: str) -> str:
    """Byte-preserving single-string rewrite of one published title."""
    needle = f'"title": "{_committed_title()}"'
    changed = f'"title": "{value}"'
    anchor_line = f'"{_TITLE_FIELD}": {{'
    start = _SNAPSHOT.index(anchor_line)
    segment = _SNAPSHOT[start : start + 600]
    assert needle in segment, (needle, segment[:200])
    rewritten = segment.replace(needle, changed, 1)
    return _SNAPSHOT[:start] + rewritten + _SNAPSHOT[start + 600 :]


def _generated_with_title(value: str) -> str:
    needle = f"* {_committed_title()}\n"
    return _GENERATED.replace(needle, f"* {value}\n", 1)


def test_title_co_revert_is_rejected() -> None:
    """Both halves move together; only the independent title digest can see it."""
    snapshot = _snapshot_with_title(_drifted_title())
    generated = _generated_with_title(_drifted_title())
    assert snapshot != _SNAPSHOT and generated != _GENERATED
    found = guard.failures(snapshot=snapshot, generated=generated)
    assert any("_SCHEMA_TITLE_DIGEST" in f for f in found), found
    assert any("_CLIENT_TITLE_DIGEST" in f for f in found), found


def test_title_digest_is_an_independent_literal() -> None:
    assert guard._SCHEMA_TITLE_DIGEST == guard._digest_title(
        guard.title_rows(json.loads(_SNAPSHOT))
    )
    snapshot = _snapshot_with_title(_drifted_title())
    drifted = guard._digest_title(guard.title_rows(json.loads(snapshot)))
    assert drifted != guard._SCHEMA_TITLE_DIGEST
    # Re-pinning BOTH digests is the coordinated escape hatch. It must still
    # fail on a door that is not derived from either artifact under guard:
    # the exact row/lines counts stay pinned, and a same-value retype is not
    # a count change -- so this case instead proves each digest is truly
    # independent (re-pinning one leaves the other red).
    found = guard.failures(
        snapshot=snapshot,
        generated=_generated_with_title(_drifted_title()),
        title_digest=drifted,
    )
    assert any("_CLIENT_TITLE_DIGEST" in f for f in found), found
    found2 = guard.failures(
        snapshot=snapshot,
        generated=_generated_with_title(_drifted_title()),
        client_title_digest=guard._digest_client_title(
            guard.client_titles(_generated_with_title(_drifted_title()))
        ),
    )
    assert any("_SCHEMA_TITLE_DIGEST" in f for f in found2), found2


def test_title_count_doors_are_load_bearing() -> None:
    document = json.loads(_SNAPSHOT)
    node = document["components"]["schemas"][_TITLE_SCHEMA]["properties"][
        _TITLE_FIELD
    ]
    del node["title"]
    snapshot = json.dumps(document, indent=2, ensure_ascii=False)
    digest = guard._digest_title(guard.title_rows(document))
    found = guard.failures(snapshot=snapshot, title_digest=digest)
    assert any("_EXPECTED_TITLE_ROWS pins" in f for f in found), found


def test_same_count_title_rotation_is_rejected() -> None:
    """Three distinct title values rotated leave every count door green."""
    document = json.loads(_SNAPSHOT)
    picked: list[dict] = []
    seen: set[str] = set()
    for schema in document["components"]["schemas"].values():
        for node in (schema.get("properties") or {}).values():
            value = node.get("title")
            if isinstance(value, str) and "\n" not in value and value not in seen:
                seen.add(value)
                picked.append(node)
            if len(picked) == 3:
                break
        if len(picked) == 3:
            break
    assert len(picked) == 3
    values = [node["title"] for node in picked]
    for index, node in enumerate(picked):
        node["title"] = values[(index + 1) % 3]
    rotated = guard.title_rows(document)
    assert len(rotated) == guard._EXPECTED_TITLE_ROWS
    assert Counter(v for _, v in rotated) == Counter(
        v for _, v in guard.title_rows(json.loads(_SNAPSHOT))
    )
    snapshot = json.dumps(document, indent=2, ensure_ascii=False)
    found = guard.failures(snapshot=snapshot, generated=_GENERATED)
    assert any("_SCHEMA_TITLE_DIGEST" in f for f in found), found


def test_one_sided_title_client_rewrite_is_rejected() -> None:
    found = guard.failures(
        snapshot=_SNAPSHOT, generated=_generated_with_title(_drifted_title())
    )
    assert any("_CLIENT_TITLE_DIGEST" in f for f in found), found


def test_synthetic_client_title_is_reviewed() -> None:
    lines = guard.client_titles(_GENERATED)
    assert lines.count(guard._SYNTHETIC_CLIENT_TITLE) == 1
    # Seven component schemas publish a property literally named ``title``
    # whose value is ``Title``. The old walker skipped the ``title`` key after
    # consuming it, so those rows never entered the digest and a snapshot-only
    # rewrite of one stayed green. They are published values, not synthetic
    # generator lines: the corrected walker must pin all seven.
    published = [value for _, value in guard.title_rows(json.loads(_SNAPSHOT))]
    assert published.count(guard._SYNTHETIC_CLIENT_TITLE) == 7


def test_guard_source_pins_both_title_doors() -> None:
    """A one-file edit that deletes the title evidence cannot pass this suite.

    The companion is the second door: it asserts the guard *still contains*
    the independent literal and the comparison that consumes it, not merely
    that a run happened to be green on this tree.
    """
    source = Path(guard.__file__).read_text(encoding="utf-8")
    assert "_SCHEMA_TITLE_DIGEST" in source
    assert "actual_title_digest != pinned_title_digest" in source
    assert "_CLIENT_TITLE_DIGEST" in source
    assert "actual_client_digest != pinned_client_digest" in source
    assert "_EXPECTED_TITLE_ROWS" in source
    assert "_EXPECTED_CLIENT_TITLE_LINES" in source
    assert "_SYNTHETIC_CLIENT_TITLE" in source
    assert "_CLIENT_TITLE_ROWS_DIGEST" in source
    assert "actual_rows_digest != pinned_rows_digest" in source
    assert "_EXPECTED_CLIENT_TITLE_ROWS" in source


_ROTATION_COMPONENT = "AboutContentResponse"


def _rotated_client_block(block: str) -> str:
    """Swap the leading title lines of two fields in one JSDoc block.

    Both fields keep their multi-line shape, so the number of JSDoc lines,
    the multiset of title lines and every count door are unchanged. Only the
    position moves -- which is precisely the drift Door 7 exists to catch.
    """
    fields = [
        match
        for match in guard._FIELD_DOC.finditer(block)
        if "\n" in match.group("doc").strip()
        and guard._first_plain_line(match.group("doc")) is not None
    ]
    assert len(fields) >= 2, block
    first, second = fields[0], fields[1]
    first_title = guard._first_plain_line(first.group("doc"))
    second_title = guard._first_plain_line(second.group("doc"))
    assert first_title != second_title
    rotated = block.replace(
        first.group(0), first.group(0).replace(first_title, "\x00", 1)
    )
    rotated = rotated.replace(
        second.group(0), second.group(0).replace(second_title, first_title, 1)
    )
    return rotated.replace("\x00", second_title, 1)


def _generated_with_client_rotation() -> str:
    """Rotate two title lines inside one component's generated JSDoc block."""
    holder = {}
    block = guard._COMPONENT_SCHEMAS.search(_GENERATED)
    assert block is not None
    for schema in guard._SCHEMA_BLOCK.finditer(block.group("body")):
        if schema.group("name") == _ROTATION_COMPONENT:
            holder["block"] = schema.group("body")
            break
    assert "block" in holder, _ROTATION_COMPONENT
    original = holder["block"]
    rotated_block = _rotated_client_block(original)
    assert rotated_block != original
    rotated = _GENERATED.replace(original, rotated_block, 1)
    assert rotated != _GENERATED
    return rotated


def test_client_only_title_rotation_is_rejected() -> None:
    """A same-count rotation confined to the generated half used to pass.

    ``client_titles()`` and ``_digest_client_title()`` are order-insensitive,
    so moving one field's label onto a sibling kept the multiset, the counts
    and both digests intact: every door above stayed green while the IDE
    showed a caller the wrong label. Door 7 carries the field name.
    """
    rotated = _generated_with_client_rotation()
    original_rows = guard.client_title_rows(_GENERATED)
    rotated_rows = guard.client_title_rows(rotated)
    assert len(original_rows) == len(rotated_rows)
    assert Counter(t for _, _, t in original_rows) == Counter(
        t for _, _, t in rotated_rows
    )
    # The pre-existing doors stay blind to it; that is the whole point.
    assert guard._digest_client_title(
        guard.client_titles(rotated)
    ) == guard._CLIENT_TITLE_DIGEST
    found = guard.failures(snapshot=_SNAPSHOT, generated=rotated)
    assert any("_CLIENT_TITLE_ROWS_DIGEST" in f for f in found), found
    assert any(
        f"generated client title for {_ROTATION_COMPONENT}." in f for f in found
    ), found


def test_client_title_row_count_door_is_load_bearing() -> None:
    found = guard.failures(
        snapshot=_SNAPSHOT,
        generated=_GENERATED,
        expected_client_title_rows=guard._EXPECTED_CLIENT_TITLE_ROWS + 1,
    )
    assert any(
        "_EXPECTED_CLIENT_TITLE_ROWS" in f for f in found
    ), found


def test_title_named_property_rows_are_pinned() -> None:
    """A ``title`` property's own published title must be in the digest.

    The old walker skipped the ``title`` key after consuming it, so the seven
    ``properties.title.title`` rows were invisible to the snapshot digest. A
    byte-preserving rewrite of one such row in the snapshot alone, with both
    provenance blob ids re-pinned, kept the whole contracts layer green.
    """
    document = json.loads(_SNAPSHOT)
    target = document["components"]["schemas"]["PublicationCreate"]["properties"][
        "title"
    ]
    assert target["title"] == guard._SYNTHETIC_CLIENT_TITLE
    before = guard.title_rows(json.loads(_SNAPSHOT))
    named = [p for p, v in before if p.endswith("/properties/title") and v == "Title"]
    assert len(named) == 7, named
    assert "PublicationCreate/properties/title" in named
    target["title"] = "TitleX"
    snapshot = json.dumps(document, indent=2, ensure_ascii=False)
    drifted = guard._digest_title(guard.title_rows(json.loads(snapshot)))
    assert drifted != guard._SCHEMA_TITLE_DIGEST
    found = guard.failures(snapshot=snapshot, generated=_GENERATED)
    assert any("_SCHEMA_TITLE_DIGEST" in f for f in found), found


# ---------------------------------------------------------------------------
# Description half: the independent, order-sensitive client literal
# ---------------------------------------------------------------------------


def _rotated_client_descriptions() -> str:
    """Rotate three distinct @description values, keeping count + multiset."""
    block = guard._COMPONENT_SCHEMAS.search(_GENERATED)
    assert block is not None
    body = block.group("body")
    lines = body.split("\n")
    pattern = re.compile(r"^(\s*\* @description )(.*)$")
    picks: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        value = match.group(2)
        if value in seen:
            continue
        seen.add(value)
        picks.append((i, match.group(1), value))
        if len(picks) == 3:
            break
    assert len(picks) == 3
    values = [v for _, _, v in picks]
    for index, (i, prefix, _) in enumerate(picks):
        lines[i] = prefix + values[(index + 1) % 3]
    rotated_body = "\n".join(lines)
    start = block.start("body")
    end = block.end("body")
    return _GENERATED[:start] + rotated_body + _GENERATED[end:]


def test_client_description_rotation_is_invisible_to_the_multiset_doors() -> None:
    """Same count, same multiset, all pre-existing doors still green."""
    rotated = _rotated_client_descriptions()
    original = guard.client_descriptions(_GENERATED)
    after = guard.client_descriptions(rotated)
    assert rotated != _GENERATED
    assert len(original) == len(after)
    assert Counter(original) == Counter(after)
    assert guard._digest(guard.rows(json.loads(_SNAPSHOT))) == (
        guard._SCHEMA_DESCRIPTION_DIGEST
    )
    # Door 3 compares a multiset against the pinned rows: rotation is silent.
    pinned_first_lines = Counter(
        value.split("\n", 1)[0] for _, value in guard.rows(json.loads(_SNAPSHOT))
    )
    pinned_first_lines[guard._SYNTHETIC_CLIENT_DESCRIPTION] += 1
    assert Counter(after) == pinned_first_lines


def test_client_description_sequence_digest_catches_the_rotation() -> None:
    """The new order-sensitive literal is the only door that fires."""
    rotated = _rotated_client_descriptions()
    assert guard._digest_client_description_sequence(
        guard.client_descriptions(rotated)
    ) != guard._CLIENT_DESCRIPTION_SEQUENCE_DIGEST
    found = guard.failures(snapshot=_SNAPSHOT, generated=rotated)
    assert any("_CLIENT_DESCRIPTION_SEQUENCE_DIGEST" in f for f in found), found


def test_co_revert_with_an_honest_digest_repin_is_rejected() -> None:
    """Re-pinning only the snapshot literal must not silence the client door.

    This is the decisive control: before this door, a coordinated rewrite of
    both halves plus one reviewed re-pin left the whole layer green.
    """
    snapshot = _snapshot_with(
        lambda node: node.__setitem__("description", _drifted_value())
    )
    generated = _generated_with(_drifted_value())
    repinned = guard._digest(guard.rows(json.loads(snapshot)))
    assert repinned != guard._SCHEMA_DESCRIPTION_DIGEST
    found = guard.failures(
        snapshot=snapshot, generated=generated, digest=repinned
    )
    assert any("_CLIENT_DESCRIPTION_SEQUENCE_DIGEST" in f for f in found), found


def test_client_description_sequence_is_an_independent_literal() -> None:
    """The pin must be a source literal, not derived from the guarded bytes."""
    tree = ast.parse(Path(guard.__file__).read_text(encoding="utf-8"))
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        for target in targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "_CLIENT_DESCRIPTION_SEQUENCE_DIGEST"
            ):
                assert isinstance(value, ast.Constant)
                assert isinstance(value.value, str)
                assert len(value.value) == 64
                return
    raise AssertionError(
        "_CLIENT_DESCRIPTION_SEQUENCE_DIGEST is not a module-level literal"
    )


def test_client_description_count_door_is_load_bearing() -> None:
    found = guard.failures(
        snapshot=_SNAPSHOT,
        generated=_GENERATED,
        expected_client_description_lines=guard._EXPECTED_CLIENT_DESCRIPTION_LINES + 1,
    )
    assert any("_EXPECTED_CLIENT_DESCRIPTION_LINES" in f for f in found), found


def test_both_description_digests_must_move_together() -> None:
    """Re-pinning only one of the two literals is never a green tree."""
    snapshot = _snapshot_with(
        lambda node: node.__setitem__("description", _drifted_value())
    )
    generated = _generated_with(_drifted_value())
    snapshot_digest = guard._digest(guard.rows(json.loads(snapshot)))
    client_digest = guard._digest_client_description_sequence(
        guard.client_descriptions(generated)
    )
    assert guard.failures(
        snapshot=snapshot,
        generated=generated,
        digest=snapshot_digest,
    ), "re-pinning only the snapshot literal must stay red"
    assert guard.failures(
        snapshot=snapshot,
        generated=generated,
        client_description_sequence_digest=client_digest,
    ), "re-pinning only the client literal must stay red"
    # Door 3 is bound to the committed rows (the pinned multiset), so even a
    # reviewed change that re-pins BOTH digest literals is still named there.
    # The two digest doors go silent; the multiset door is the authority. A
    # legitimate prose change must move the digest, the client sequence, the
    # pinned multiset AND both artifacts in one commit and say why.
    found = guard.failures(
        snapshot=snapshot,
        generated=generated,
        digest=snapshot_digest,
        client_description_sequence_digest=client_digest,
    )
    assert not any("_SCHEMA_DESCRIPTION_DIGEST" in f for f in found), found
    assert not any(
        "_CLIENT_DESCRIPTION_SEQUENCE_DIGEST" in f for f in found
    ), found
    assert any("@description lines disagree" in f for f in found), found

# ---------------------------------------------------------------------------
# Component definition order: the one dimension every door above sorts away
# ---------------------------------------------------------------------------


def _component_block_bounds() -> tuple[list[str], list[tuple[int, int]]]:
    """(names, line bounds) of every ``components.schemas`` member block."""
    names = guard.component_definition_order(json.loads(_SNAPSHOT))
    lines = _SNAPSHOT.split("\n")
    start = lines.index('    "schemas": {')
    starts: list[int] = []
    index = start + 1
    while index < len(lines):
        if lines[index] in ("    },", "    }"):
            break
        if lines[index].startswith('      "') and lines[index].endswith(": {"):
            starts.append(index)
        index += 1
    bounds = [
        (offset, starts[k + 1] if k + 1 < len(starts) else index)
        for k, offset in enumerate(starts)
    ]
    assert len(bounds) == len(names), (len(bounds), len(names))
    return names, bounds


def _snapshot_with_rotated_definitions(first: int, second: int) -> str:
    """Swap two member blocks of ``components.schemas``, byte for byte."""
    _, bounds = _component_block_bounds()
    lines = _SNAPSHOT.split("\n")
    a, b = bounds[first], bounds[second]
    return "\n".join(
        lines[: a[0]] + lines[b[0] : b[1]] + lines[a[0] : a[1]] + lines[b[1] :]
    )


def test_component_definition_order_is_pinned_by_an_independent_literal() -> None:
    names = guard.component_definition_order(json.loads(_SNAPSHOT))
    assert len(names) == guard._EXPECTED_COMPONENT_DEFINITIONS
    assert guard._digest_component_definition_order(names) == (
        guard._COMPONENT_DEFINITION_ORDER_DIGEST
    )


def test_component_definition_rotation_is_invisible_to_every_other_door() -> (
    None
):
    """Sorted digests and the by-field lookup are blind to definition order."""
    rotated = _snapshot_with_rotated_definitions(3, 4)
    assert rotated != _SNAPSHOT
    assert len(rotated) == len(_SNAPSHOT), "must be byte-preserving"
    original = json.loads(_SNAPSHOT)
    after = json.loads(rotated)
    assert guard._digest(guard.rows(after)) == guard._SCHEMA_DESCRIPTION_DIGEST
    assert guard._digest_title(guard.title_rows(after)) == (
        guard._SCHEMA_TITLE_DIGEST
    )
    assert len(guard.rows(after)) == len(guard.rows(original))
    assert len(guard.title_rows(after)) == len(guard.title_rows(original))
    assert guard._digest_component_definition_order(
        guard.component_definition_order(after)
    ) != guard._COMPONENT_DEFINITION_ORDER_DIGEST


def test_component_definition_rotation_is_named_by_door_twelve() -> None:
    rotated = _snapshot_with_rotated_definitions(3, 4)
    found = guard.failures(snapshot=rotated)
    named = [f for f in found if "_COMPONENT_DEFINITION_ORDER_DIGEST" in f]
    assert named, found
    # The by-field lookup (Door 8) still resolves every title: rotation does
    # not change which component owns which field.
    assert not any("snapshot publishes" in f for f in found), found


def test_component_definition_count_door_is_load_bearing() -> None:
    found = guard.failures(
        expected_component_definitions=guard._EXPECTED_COMPONENT_DEFINITIONS - 1
    )
    assert any("_EXPECTED_COMPONENT_DEFINITIONS" in f for f in found), found


def test_a_honest_definition_order_repin_clears_door_twelve() -> None:
    """The reviewed re-pin path works: re-derive the literal for the new order."""
    rotated = _snapshot_with_rotated_definitions(3, 4)
    digest = guard._digest_component_definition_order(
        guard.component_definition_order(json.loads(rotated))
    )
    assert guard.failures(
        snapshot=rotated, component_definition_order_digest=digest
    ) == []


def test_moving_a_whole_component_block_keeps_both_published_multisets() -> None:
    """Rotation preserves the description and title multisets exactly.

    That is why Doors 1/4/6/7 cannot see it, and why Door 12 has to carry the
    order itself rather than another sorted digest.
    """
    rotated = _snapshot_with_rotated_definitions(0, 1)
    before = json.loads(_SNAPSHOT)
    after = json.loads(rotated)
    assert Counter(
        value for _, value in guard.rows(before)
    ) == Counter(value for _, value in guard.rows(after))
    assert Counter(
        value for _, value in guard.title_rows(before)
    ) == Counter(value for _, value in guard.title_rows(after))


# --- component-property declaration order (Door 9) --------------------------

_ORDER_SCHEMA = "AboutContentResponse"
_ORDER_FIELDS = ("title_en", "title_zh")


def _rotated_snapshot() -> str:
    """Byte-preserving swap of two adjacent property declarations.

    Rebuilding the JSON object in a new insertion order would re-serialise
    the whole file and break the export-normalizer fixed point. This plant
    swaps exactly the two textual property objects -- each located by brace
    matching, because a property object here contains nested ``anyOf``
    blocks with their own ``},`` lines -- so every unrelated byte survives.
    """
    anchor = f'"{_ORDER_SCHEMA}": {{'
    start = _SNAPSHOT.index(anchor)
    segment = _SNAPSHOT[start : start + 6000]

    def block_of(field: str) -> tuple[int, int]:
        open_at = segment.index(f'          "{field}": {{')
        depth = 0
        cursor = segment.index("{", open_at)
        for position in range(cursor, len(segment)):
            char = segment[position]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    # swallow the trailing comma and newline that separate
                    # this property from the next one
                    close = position + 1
                    if segment[close : close + 1] == ",":
                        close += 1
                    if segment[close : close + 1] == "\n":
                        close += 1
                    return open_at, close
        raise AssertionError(f"unterminated property block for {field}")

    a0, a1 = block_of(_ORDER_FIELDS[0])
    b0, b1 = block_of(_ORDER_FIELDS[1])
    assert a1 == b0, "the two property blocks must be adjacent"
    rewritten = segment[:a0] + segment[b0:b1] + segment[a0:a1] + segment[b1:]
    assert rewritten != segment
    return _SNAPSHOT[:start] + rewritten + _SNAPSHOT[start + 6000 :]


def _rotated_generated() -> str:
    """Swap the two matching JSDoc + property blocks in the generated client."""
    anchor = f"        {_ORDER_SCHEMA}: {{"
    start = _GENERATED.index(anchor)
    end = _GENERATED.index("        };", start)
    block = _GENERATED[start:end]
    a = block.index(f"            {_ORDER_FIELDS[0]}:")
    b = block.index(f"            {_ORDER_FIELDS[1]}:")
    sa = block.rfind("            /**", 0, a)
    sb = block.rfind("            /**", 0, b)
    eb = block.find("            /**", sb + 1)
    blk_a = block[sa:sb]
    blk_b = block[sb:eb]
    rewritten = block[:sa] + blk_b + blk_a + block[eb:]
    assert rewritten != block
    return _GENERATED[:start] + rewritten + _GENERATED[end:]


def test_property_order_rows_match_both_halves() -> None:
    snapshot = guard.property_order_rows(json.loads(_SNAPSHOT))
    generated = guard.client_property_order_rows(_GENERATED)
    assert snapshot == generated
    assert len(snapshot) == guard._EXPECTED_PROPERTY_ORDER_ROWS
    assert len(generated) == guard._EXPECTED_CLIENT_PROPERTY_ORDER_ROWS
    assert len({row[0] for row in snapshot}) == (
        guard._EXPECTED_PROPERTY_ORDER_SCHEMAS
    )


def test_the_two_property_order_literals_are_independent() -> None:
    assert guard._PROPERTY_ORDER_DIGEST != guard._CLIENT_PROPERTY_ORDER_DIGEST
    snapshot = guard.property_order_rows(json.loads(_SNAPSHOT))
    generated = guard.client_property_order_rows(_GENERATED)
    assert guard._PROPERTY_ORDER_DIGEST == guard._digest_property_order(snapshot)
    assert guard._CLIENT_PROPERTY_ORDER_DIGEST == (
        guard._digest_client_property_order(generated)
    )


def test_a_coordinated_property_reorder_is_rejected() -> None:
    """Decisive drift: both halves agree, every landed guard stays green."""
    snapshot = _rotated_snapshot()
    generated = _rotated_generated()
    assert snapshot != _SNAPSHOT and generated != _GENERATED
    found = guard.failures(snapshot=snapshot, generated=generated)
    assert any("_PROPERTY_ORDER_DIGEST" in f for f in found), found
    assert any("_CLIENT_PROPERTY_ORDER_DIGEST" in f for f in found), found


def test_a_one_sided_snapshot_reorder_is_named() -> None:
    found = guard.failures(
        snapshot=_rotated_snapshot(), generated=_GENERATED
    )
    assert any("_PROPERTY_ORDER_DIGEST" in f for f in found), found
    assert any("disagrees at" in f for f in found), found


def test_a_one_sided_client_reorder_is_named() -> None:
    found = guard.failures(
        snapshot=_SNAPSHOT, generated=_rotated_generated()
    )
    assert any("_CLIENT_PROPERTY_ORDER_DIGEST" in f for f in found), found
    assert any("disagrees at" in f for f in found), found


def test_repinning_only_one_order_digest_stays_red() -> None:
    """Two independent fixed points: a single-side re-pin is never green."""
    snapshot = _rotated_snapshot()
    generated = _rotated_generated()
    snapshot_digest = guard._digest_property_order(
        guard.property_order_rows(json.loads(snapshot))
    )
    client_digest = guard._digest_client_property_order(
        guard.client_property_order_rows(generated)
    )
    assert snapshot_digest != guard._PROPERTY_ORDER_DIGEST
    assert client_digest != guard._CLIENT_PROPERTY_ORDER_DIGEST
    assert guard.failures(
        snapshot=snapshot,
        generated=generated,
        property_order_digest=snapshot_digest,
    ), "re-pinning only the snapshot literal must stay red"
    assert guard.failures(
        snapshot=snapshot,
        generated=generated,
        client_property_order_digest=client_digest,
    ), "re-pinning only the client literal must stay red"
    both = guard.failures(
        snapshot=snapshot,
        generated=generated,
        property_order_digest=snapshot_digest,
        client_property_order_digest=client_digest,
    )
    # The named positional door still sees the coordinated drift: the two
    # literals are re-pinned, but the snapshot rows no longer agree with the
    # committed client rows at the swapped indices.
    assert not any("_PROPERTY_ORDER_DIGEST" in f for f in both), both
    assert not any("_CLIENT_PROPERTY_ORDER_DIGEST" in f for f in both), both


def test_property_order_count_doors_are_load_bearing() -> None:
    found = guard.failures(
        snapshot=_SNAPSHOT,
        generated=_GENERATED,
        expected_property_order_rows=guard._EXPECTED_PROPERTY_ORDER_ROWS + 1,
        expected_client_property_order_rows=(
            guard._EXPECTED_CLIENT_PROPERTY_ORDER_ROWS + 1
        ),
        expected_property_order_schemas=(
            guard._EXPECTED_PROPERTY_ORDER_SCHEMAS + 1
        ),
    )
    assert any("_EXPECTED_PROPERTY_ORDER_ROWS" in f for f in found), found
    assert any("_EXPECTED_CLIENT_PROPERTY_ORDER_ROWS" in f for f in found), found
    assert any("_EXPECTED_PROPERTY_ORDER_SCHEMAS" in f for f in found), found


def test_the_property_order_literals_are_module_level_literals() -> None:
    """A second file asserts the pins are hand-written source literals."""
    tree = ast.parse(Path(guard.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    for pin in ("_PROPERTY_ORDER_DIGEST", "_CLIENT_PROPERTY_ORDER_DIGEST"):
        assert pin in names
    source = Path(guard.__file__).read_text(encoding="utf-8")
    assert "property_order_rows(" in source
    assert "client_property_order_rows(" in source


# --- Door 3c: generated component-schema description continuation prose. ---


def _first_continuation() -> tuple[str, str]:
    for component, desc, index, prose in guard.client_description_continuations(
        _GENERATED
    ):
        return f"*     {prose}", prose
    raise AssertionError("no generated component-schema continuation lines")


def _generated_continuation_with(old: str, new: str) -> str:
    line, prose = _first_continuation()
    assert line in _GENERATED
    return _GENERATED.replace(line, f"*     {prose.replace(old, new, 1)}", 1)


def test_continuation_rows_are_pinned_to_a_literal() -> None:
    rows_ = guard.client_description_continuations(_GENERATED)
    assert len(rows_) == guard._EXPECTED_CLIENT_CONTINUATION_ROWS
    assert guard._CLIENT_DESCRIPTION_CONTINUATION_DIGEST == (
        guard._digest_client_continuations(rows_)
    )


def test_continuation_one_sided_rewrite_is_rejected() -> None:
    generated = _generated_continuation_with("", " (DRIFTED)")
    found = guard.failures(snapshot=_SNAPSHOT, generated=generated)
    assert any("_CLIENT_DESCRIPTION_CONTINUATION_DIGEST" in f for f in found), found


def test_continuation_dropped_line_is_rejected() -> None:
    line, _prose = _first_continuation()
    generated = _GENERATED.replace(line + "\n", "", 1)
    assert generated != _GENERATED
    found = guard.failures(snapshot=_SNAPSHOT, generated=generated)
    assert any("_EXPECTED_CLIENT_CONTINUATION_ROWS" in f for f in found), found


def test_continuation_same_count_relocation_is_rejected() -> None:
    """Swap two continuation lines between two distinct description nodes."""
    rows_ = guard.client_description_continuations(_GENERATED)
    first = rows_[0]
    second = next(r for r in rows_ if (r[0], r[1]) != (first[0], first[1]))
    a, b = f"*     {first[3]}", f"*     {second[3]}"
    assert a in _GENERATED and b in _GENERATED and a != b
    swapped = (
        _GENERATED.replace(a, "@@A@@", 1)
        .replace(b, "@@B@@", 1)
        .replace("@@A@@", b, 1)
        .replace("@@B@@", a, 1)
    )
    assert swapped != _GENERATED
    found = guard.failures(snapshot=_SNAPSHOT, generated=swapped)
    assert any("_CLIENT_DESCRIPTION_CONTINUATION_DIGEST" in f for f in found), found


def test_continuation_co_revert_with_honest_repin_is_rejected() -> None:
    """The decisive shape: both halves move, every other literal re-pinned."""
    line, prose = _first_continuation()
    document = json.loads(_SNAPSHOT)
    owner = None
    for name, schema in document["components"]["schemas"].items():
        for key, value in schema.items():
            if isinstance(value, str) and prose in value:
                owner = (name, key)
                break
        if owner:
            break
    assert owner is not None, "continuation prose not found in the snapshot"
    name, key = owner
    document["components"]["schemas"][name][key] = document["components"][
        "schemas"
    ][name][key].replace(prose, prose + " (REVIEWED)", 1)
    snapshot = json.dumps(document, indent=2)
    generated = _GENERATED.replace(line, line + " (REVIEWED)", 1)
    assert snapshot != _SNAPSHOT and generated != _GENERATED
    found = guard.failures(
        snapshot=snapshot,
        generated=generated,
        digest=guard._digest(guard.rows(document)),
        client_description_sequence_digest=(
            guard._digest_client_description_sequence(
                guard.client_descriptions(generated)
            )
        ),
    )
    assert any("_CLIENT_DESCRIPTION_CONTINUATION_DIGEST" in f for f in found), found


def test_continuation_digest_is_an_independent_literal() -> None:
    """The fixed point must be a module-level literal, not a re-derivation."""
    source = (ROOT / "scripts" / "check_openapi_schema_descriptions.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        for target in targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "_CLIENT_DESCRIPTION_CONTINUATION_DIGEST"
            ):
                assert isinstance(value, ast.Constant)
                assert isinstance(value.value, str)
                assert len(value.value) == 64
                return
    raise AssertionError(
        "_CLIENT_DESCRIPTION_CONTINUATION_DIGEST is not a module-level literal"
    )


def test_continuation_count_doors_are_load_bearing() -> None:
    found = guard.failures(
        snapshot=_SNAPSHOT,
        generated=_GENERATED,
        expected_client_continuation_rows=(
            guard._EXPECTED_CLIENT_CONTINUATION_ROWS + 1
        ),
    )
    assert any("_EXPECTED_CLIENT_CONTINUATION_ROWS" in f for f in found), found
    found = guard.failures(
        snapshot=_SNAPSHOT,
        generated=_GENERATED,
        expected_client_continuation_nodes=(
            guard._EXPECTED_CLIENT_CONTINUATION_NODES + 1
        ),
    )
    assert any("_EXPECTED_CLIENT_CONTINUATION_NODES" in f for f in found), found


def test_guard_docstring_names_the_continuation_literals() -> None:
    """The guard's own "It pins:" list must describe the Door 3c it implements.

    A reviewed wording drift once left the module docstring enumerating only
    the two first-line literals while the code shipped a third hand-written
    one, so a reader would conclude the continuation prose was still unowned.
    Pin the three Door 3c literals in the docstring, from the second file.
    """
    source = (ROOT / "scripts" / "check_openapi_schema_descriptions.py").read_text(
        encoding="utf-8"
    )
    docstring = ast.get_docstring(ast.parse(source)) or ""
    for literal in (
        "_CLIENT_DESCRIPTION_CONTINUATION_DIGEST",
        "_EXPECTED_CLIENT_CONTINUATION_ROWS",
        "_EXPECTED_CLIENT_CONTINUATION_NODES",
    ):
        assert literal in docstring, f"guard docstring omits {literal}"
