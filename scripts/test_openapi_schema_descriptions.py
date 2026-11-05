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

import json
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
