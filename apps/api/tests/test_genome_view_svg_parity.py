"""Byte-for-byte parity between the TypeScript and Python genome-view renderers.

The portal builds its genome picture from the TypeScript renderer; the API
serves a pre-rendered one from the Python port. If the two ever disagree, the
same gene would look different depending on whether the picture came from the
cache or from the browser, and nothing else in the suite would notice.

The golden file is generated from the TypeScript implementation by
``packages/genome-view/scripts/gen-svg-golden.ts``; regenerate it there and this
test fails until the Python port is brought back into line.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.services.genome_view_svg import (
    StructurePart,
    SvgFeature,
    SvgTheme,
    SvgTrack,
    Viewport,
    render_genome_view_svg,
)

GOLDEN = Path(__file__).parent / "fixtures" / "genome_view_svg_golden.json"


def _load_cases() -> list[dict[str, Any]]:
    if not GOLDEN.exists():  # pragma: no cover - fixture is checked in
        pytest.fail(
            f"missing golden fixture {GOLDEN}; regenerate it with "
            "apps/admin/node_modules/.bin/tsx packages/genome-view/scripts/gen-svg-golden.ts"
        )
    payload = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return payload["cases"]


CASES = _load_cases()


def _to_viewport(raw: dict[str, Any]) -> Viewport:
    return Viewport(
        assembly_key=raw["assemblyKey"],
        ref_name=raw["refName"],
        start=raw["start"],
        end=raw["end"],
    )


def _to_tracks(raw_tracks: list[dict[str, Any]]) -> list[SvgTrack]:
    tracks: list[SvgTrack] = []
    for raw in raw_tracks:
        features = tuple(
            SvgFeature(
                id=feature["id"],
                start=feature["start"],
                end=feature["end"],
                kind=feature.get("kind", "gene"),
                label=feature.get("label"),
                strand=feature.get("strand"),
                parts=tuple(
                    StructurePart(
                        start=part["start"],
                        end=part["end"],
                        kind=part.get("kind", "exon"),
                    )
                    for part in feature.get("parts", [])
                ),
            )
            for feature in raw.get("features", [])
        )
        tracks.append(SvgTrack(id=raw["id"], label=raw["label"], kind=raw["kind"], features=features))
    return tracks


def _to_theme(raw: dict[str, Any]) -> SvgTheme:
    return SvgTheme(
        background=raw["background"],
        surface=raw["surface"],
        text=raw["text"],
        text_secondary=raw["textSecondary"],
        border=raw["border"],
        primary=raw["primary"],
        warn=raw["warn"],
    )


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_python_renderer_matches_typescript_golden(case: dict[str, Any]) -> None:
    """The Python port must reproduce the TypeScript SVG exactly."""
    options = case["options"]
    produced = render_genome_view_svg(
        viewport=_to_viewport(options["viewport"]),
        width_px=options["widthPx"],
        tracks=_to_tracks(options["tracks"]),
        theme=_to_theme(options["theme"]),
        row_height_px=options.get("rowHeightPx", 22),
        ruler_height_px=options.get("rulerHeightPx", 28),
        gap_px=options.get("gapPx", 8),
        font_family=options.get(
            "fontFamily",
            '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
        ),
        id_prefix=options.get("idPrefix", "gv"),
    )
    expected = case["svg"]

    if produced != expected:
        # Show the first divergence instead of two unreadable blobs.
        limit = min(len(produced), len(expected))
        offset = next((i for i in range(limit) if produced[i] != expected[i]), limit)
        raise AssertionError(
            f"{case['name']}: renderers diverge at offset {offset}\n"
            f"  expected (TS): ...{expected[max(0, offset - 60):offset + 60]!r}\n"
            f"  produced (PY): ...{produced[max(0, offset - 60):offset + 60]!r}"
        )


def test_golden_covers_the_contract_surface() -> None:
    """Guard against a regenerated golden silently losing its edge cases."""
    names = {case["name"] for case in CASES}
    assert {
        "ruler-and-single-gene",
        "overlapping-features-wrap-to-rows",
        "mutation-marks-use-warn-colour",
        "empty-track",
        "narrow-window-tight-ticks",
        "wide-feature-shows-inline-label",
        "escapes-hostile-labels",
    } <= names


def test_escaping_is_not_double_encoded() -> None:
    """`&` must be replaced first, or later escapes get mangled."""
    from app.services.genome_view_svg import escape_xml

    assert escape_xml("a&b") == "a&amp;b"
    assert escape_xml("<x>") == "&lt;x&gt;"
    assert escape_xml('"q"') == "&quot;q&quot;"
    assert escape_xml("&lt;") == "&amp;lt;"
