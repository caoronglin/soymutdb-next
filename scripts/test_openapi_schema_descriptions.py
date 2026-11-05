"""Regression coverage for ``scripts/check_openapi_schema_descriptions.py``.

The guard pins 257 published component-schema ``description`` strings to a
hand-written literal and checks the generated client's ``@description`` lines
against them. These cases prove each failure direction on real committed
bytes: the decisive byte-preserving co-revert of both halves (with provenance
blob ids re-pinned) still fails via the digest, a one-sided client edit is
named, the digest is independent of the artifact it audits, the count doors
are load-bearing, and the generated half cannot be silently dropped.

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
