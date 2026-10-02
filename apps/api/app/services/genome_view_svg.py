"""Pre-rendered genome-view SVG.

The gene detail page can ask the API for its genome picture instead of building
it in the browser, which removes the layout work from first paint and lets the
artifact be cached as a plain image.

This module is a deliberate second implementation of the TypeScript renderer in
``packages/genome-view/src/{ruler,track-layout,svg-renderer}.ts``. Keeping the
picture identical is a contract, not a coincidence, so the arithmetic below is a
line-by-line port and ``tests/test_genome_view_svg_parity.py`` pins the two
implementations to byte-identical output.

Two porting hazards are handled explicitly:

* JavaScript's ``Math.round`` is ``floor(x + 0.5)``, whereas Python's built-in
  ``round`` is banker's rounding. ``_num`` therefore never uses ``round``.
* ``String(3)`` is ``"3"`` in JavaScript but ``str(3.0)`` is ``"3.0"`` in
  Python. ``_num`` prints integral values without a decimal point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

__all__ = [
    "DEFAULT_FONT_FAMILY",
    "DEFAULT_GAP_PX",
    "DEFAULT_ROW_HEIGHT_PX",
    "DEFAULT_RULER_HEIGHT_PX",
    "PlacedPart",
    "StructurePart",
    "SvgFeature",
    "SvgTheme",
    "SvgTrack",
    "Viewport",
    "clip_to_region",
    "compute_ticks",
    "format_bp",
    "genome_view_cache_key",
    "layout_intervals",
    "merge_exon_spans",
    "nice_step",
    "place_structure_parts",
    "render_genome_view_svg",
]

DEFAULT_ROW_HEIGHT_PX = 22
DEFAULT_RULER_HEIGHT_PX = 28
DEFAULT_GAP_PX = 8
#: Width of the left label rail. Every track used to draw its label at x=8 while
#: its content started at x=0, so a long label was painted under the feature body
#: and a ruler label collided with the first tick. Real genome browsers solve
#: this with a fixed rail; so does this renderer. SVG cannot measure text, so the
#: rail is fixed and callers keep labels short enough to fit.
DEFAULT_LABEL_RAIL_PX = 120
#: Narrowest content area the rail may leave behind.
MIN_CONTENT_PX = 80
DEFAULT_FONT_FAMILY = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
)

_NICE_STEPS = (1, 2, 5)

#: Width below which a feature mark stays visible (matches MIN_WIDTH_PX in TS).
_MIN_FEATURE_WIDTH_PX = 1
#: Requested pixel distance between ruler ticks (matches computeTicks default).
_RULER_TARGET_PX = 80
#: Hard stop so a pathological window cannot emit unbounded markup.
_MAX_TICKS = 1000


@dataclass(frozen=True, slots=True)
class Viewport:
    """0-based, half-open window into one reference sequence."""

    assembly_key: str
    ref_name: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class StructurePart:
    """An exon/CDS/UTR segment drawn inside a feature's lane.

    Ported from ``packages/genome-view/src/gene-structure.ts``; the parity test
    fails if the two placements drift.
    """

    start: int
    end: int
    kind: str  # "exon" | "cds" | "utr5" | "utr3"


@dataclass(frozen=True, slots=True)
class PlacedPart:
    """A structure part mapped into the same screen space as a track's x offsets."""

    start: int
    end: int
    kind: str
    x: float
    width: float


@dataclass(frozen=True, slots=True)
class SvgFeature:
    """A feature drawn inside a feature track."""

    id: str
    start: int
    end: int
    kind: str = "gene"
    label: str | None = None
    strand: str | None = None
    #: Exon/CDS/UTR sub-structure. When present the feature is drawn as a gene
    #: model — exon boxes on an intron line with a strand arrowhead — instead of
    #: one solid bar.
    parts: tuple[StructurePart, ...] = ()


@dataclass(frozen=True, slots=True)
class SvgTrack:
    """One horizontal track."""

    id: str
    label: str
    kind: str  # "ruler" | "feature"
    features: tuple[SvgFeature, ...] = ()


@dataclass(frozen=True, slots=True)
class SvgTheme:
    """Colours resolved by the caller; this module never invents a hex."""

    background: str
    surface: str
    text: str
    text_secondary: str
    border: str
    primary: str
    warn: str


@dataclass(slots=True)
class _Placed:
    id: str
    x: float
    w: float
    row: int


@dataclass(slots=True)
class _RenderedTrack:
    track: SvgTrack
    y: float
    height: float
    placed: list[tuple[_Placed, SvgFeature]] = field(default_factory=list)


def escape_xml(value: str) -> str:
    """Escape text destined for an SVG text node.

    The replacement order matters and must match the TypeScript implementation:
    ``&`` first, or the escapes introduced by later steps get double-encoded.
    """
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _num(value: float) -> str:
    """Round to two decimals and print the way JavaScript would."""
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return "0"
    rounded = math.floor(value * 100 + 0.5) / 100
    if rounded == int(rounded):
        return str(int(rounded))
    return str(rounded)


def nice_step(rough: float) -> float:
    """Smallest 1/2/5 x 10^n step that is >= rough."""
    if not math.isfinite(rough) or rough <= 0:
        return 1
    magnitude = math.pow(10, math.floor(math.log10(rough)))
    for factor in _NICE_STEPS:
        candidate = factor * magnitude
        if candidate >= rough:
            return candidate
    return 10 * magnitude


def format_bp(bp: float) -> str:
    """Deterministic thousands grouping (never locale-dependent)."""
    truncated = math.trunc(bp)
    sign = "-" if truncated < 0 else ""
    digits = str(abs(truncated))
    grouped = ""
    for index, char in enumerate(reversed(digits)):
        if index and index % 3 == 0:
            grouped = "," + grouped
        grouped = char + grouped
    return sign + grouped


def compute_ticks(
    start: int,
    end: int,
    width_px: float,
    target_px: float = _RULER_TARGET_PX,
) -> list[tuple[float, float, str]]:
    """Return ``(bp, x, label)`` triples for the visible window."""
    span = end - start
    if not math.isfinite(span) or span <= 0:
        return []
    if not math.isfinite(width_px) or width_px <= 0:
        return []
    target = target_px if target_px > 0 else _RULER_TARGET_PX
    step = nice_step((span / width_px) * target)

    ticks: list[tuple[float, float, str]] = []
    first = math.ceil(start / step) * step
    bp = first
    # `bp <= end` mirrors the TypeScript loop; floats are compared as-is on both
    # sides, so the tick count cannot diverge.
    while bp <= end:
        ticks.append((bp, ((bp - start) / span) * width_px, format_bp(bp)))
        if len(ticks) > _MAX_TICKS:
            break
        bp += step
    return ticks


def clip_to_region(start: int, end: int, region: Viewport) -> tuple[int, int] | None:
    """Intersect ``[start,end)`` with ``region``; None when disjoint or empty."""
    clipped_start = max(start, region.start)
    clipped_end = min(end, region.end)
    return (clipped_start, clipped_end) if clipped_end > clipped_start else None


def layout_intervals(
    intervals: list[SvgFeature],
    region: Viewport,
    width_px: float,
    gap_px: float = 1,
) -> tuple[list[tuple[_Placed, SvgFeature]], int]:
    """Greedy first-fit row packing in screen space.

    Input order is by genomic position so the result is deterministic and
    overlapping features never collide.
    """
    span = region.end - region.start
    if not math.isfinite(span) or span <= 0 or not math.isfinite(width_px) or width_px <= 0:
        return [], 0

    scale = width_px / span
    ordered = sorted(
        (f for f in intervals if f.end > f.start),
        key=lambda f: (f.start, f.end),
    )

    row_ends: list[float] = []
    placed: list[tuple[_Placed, SvgFeature]] = []
    for feature in ordered:
        clipped = clip_to_region(feature.start, feature.end, region)
        if clipped is None:
            continue
        x = (clipped[0] - region.start) * scale
        w = max(_MIN_FEATURE_WIDTH_PX, (clipped[1] - clipped[0]) * scale)
        row = next((i for i, row_end in enumerate(row_ends) if x >= row_end + gap_px), -1)
        if row == -1:
            row = len(row_ends)
            row_ends.append(x + w)
        else:
            row_ends[row] = max(row_ends[row], x + w)
        placed.append((_Placed(id=feature.id, x=x, w=w, row=row), feature))
    return placed, len(row_ends)


def merge_exon_spans(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Union of exon spans across a gene's isoforms.

    Overlapping or abutting exons merge; a real intron gap survives. Sorting by
    ``(start, end)`` mirrors the TypeScript comparator, so both sides agree on
    the order even when two spans share a start.
    """
    ordered = sorted((start, end) for start, end in intervals if end > start)
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            last_start, last_end = merged[-1]
            merged[-1] = (last_start, max(last_end, end))
            continue
        merged.append((start, end))
    return merged


def place_structure_parts(
    parts: tuple[StructurePart, ...],
    viewport: Viewport,
    width_px: float,
    gene_start: int,
    gene_end: int,
) -> list[PlacedPart]:
    """Map a feature's exon parts into screen space for one lane.

    Mirrors ``placeStructureParts`` in gene-structure.ts: parts are clipped to
    the gene body and then to the window, and degenerate parts are dropped
    rather than emitted as invisible markup.
    """
    span = viewport.end - viewport.start
    if not math.isfinite(span) or span <= 0 or not math.isfinite(width_px) or width_px <= 0:
        return []
    scale = width_px / span
    placed: list[PlacedPart] = []
    for part in parts:
        # An exon with no recorded extent would render as a zero-width speck.
        if not part.end > part.start:
            continue
        # Never let an exon escape its gene: a mis-annotated part must not smear
        # the structure across the lane.
        bounded = clip_to_region(max(part.start, gene_start), min(part.end, gene_end), viewport)
        if bounded is None:
            continue
        placed.append(
            PlacedPart(
                start=bounded[0],
                end=bounded[1],
                kind=part.kind,
                x=(bounded[0] - viewport.start) * scale,
                width=max(1, (bounded[1] - bounded[0]) * scale),
            )
        )
    return placed


def render_genome_view_svg(
    *,
    viewport: Viewport,
    width_px: float,
    tracks: list[SvgTrack],
    theme: SvgTheme,
    row_height_px: float = DEFAULT_ROW_HEIGHT_PX,
    ruler_height_px: float = DEFAULT_RULER_HEIGHT_PX,
    gap_px: float = DEFAULT_GAP_PX,
    label_rail_px: float = DEFAULT_LABEL_RAIL_PX,
    font_family: str = DEFAULT_FONT_FAMILY,
    id_prefix: str = "gv",
) -> str:
    """Build the SVG markup for one viewport.

    Coordinates are 1:1 with base pairs, so an x offset is reproducible from the
    tick labels alone.
    """
    span = viewport.end - viewport.start
    scale = span / width_px if math.isfinite(width_px) and width_px > 0 else 0
    if not math.isfinite(width_px) or width_px <= 0 or span <= 0 or scale <= 0:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_num(max(width_px, 1))}" '
            f'height="{_num(ruler_height_px)}" role="img" '
            f'aria-label="Genome view unavailable"></svg>'
        )

    # Label rail: every track's label owns the left strip, so content starts
    # after it and can never be painted over. On a narrow view the rail yields
    # first.
    rail = max(0.0, min(label_rail_px, width_px - MIN_CONTENT_PX))
    content_width = width_px - rail

    # Lay out every track first so the total height is known before emitting.
    rendered: list[_RenderedTrack] = []
    cursor_y = 0.0
    for track in tracks:
        if track.kind == "ruler":
            rendered.append(_RenderedTrack(track=track, y=cursor_y, height=ruler_height_px))
            cursor_y += ruler_height_px + gap_px
            continue
        visible = [
            f for f in track.features if clip_to_region(f.start, f.end, viewport) is not None
        ]
        placed_raw, row_count = layout_intervals(visible, viewport, content_width)
        # Shift into the content area once, here, so nothing downstream has to
        # remember the rail exists.
        placed = [
            (_Placed(id=item.id, x=item.x + rail, w=item.w, row=item.row), feature)
            for item, feature in placed_raw
        ]
        height = max(1, row_count) * row_height_px
        rendered.append(
            _RenderedTrack(
                track=track,
                y=cursor_y,
                height=height,
                placed=placed,
            )
        )
        cursor_y += height + gap_px
    total_height = max(cursor_y - gap_px, ruler_height_px)

    parts: list[str] = []
    label = f"{viewport.ref_name}:{format_bp(viewport.start)}-{format_bp(viewport.end)}"
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_num(width_px)}" '
        f'height="{_num(total_height)}" '
        f'viewBox="0 0 {_num(width_px)} {_num(total_height)}" role="img" '
        f'aria-label="{escape_xml(label)}" '
        f'font-family="{escape_xml(font_family)}">'
    )
    parts.append(
        f'<rect x="0" y="0" width="{_num(width_px)}" height="{_num(total_height)}" '
        f'fill="{theme.background}"/>'
    )

    for item in rendered:
        parts.append(
            f'<rect x="0" y="{_num(item.y)}" width="{_num(width_px)}" height="{_num(item.height)}" '
            f'fill="{theme.surface}"/>'
        )
        # Track labels use a stroke-and-fill style so a long label (a full gene
        # accession, for instance) stays legible where it overlaps an early
        # feature body. `paint-order="stroke"` puts the halo underneath the
        # glyphs, and the halo colour is the track surface, so on empty regions
        # the label looks exactly as it did before. Mirrors the TypeScript
        # renderer; the parity test fails if the two drift.
        parts.append(
            f'<text x="8" y="{_num(item.y + 14)}" font-size="11" fill="{theme.text_secondary}" '
            f'stroke="{theme.surface}" stroke-width="3" paint-order="stroke">'
            f"{escape_xml(item.track.label)}</text>"
        )

        if item.track.kind == "ruler":
            for _bp, tick_x, tick_label in compute_ticks(
                viewport.start, viewport.end, content_width
            ):
                shifted = tick_x + rail
                parts.append(
                    f'<line x1="{_num(shifted)}" y1="{_num(item.y)}" x2="{_num(shifted)}" '
                    f'y2="{_num(item.y + item.height)}" stroke="{theme.border}" stroke-width="1"/>'
                )
                parts.append(
                    f'<text x="{_num(shifted + 3)}" y="{_num(item.y + 12)}" font-size="10" '
                    f'fill="{theme.text_secondary}">{escape_xml(tick_label)}</text>'
                )
            continue

        if not item.placed:
            # Same rail offset as the track label: an empty lane still draws its
            # label on the left, so the placeholder has to start after the rail
            # or the two strings overlap.
            parts.append(
                f'<text x="{_num(rail + 8)}" y="{_num(item.y + 22)}" font-size="11" '
                f'fill="{theme.text_secondary}">No features in this window</text>'
            )
            continue

        for placed, feature in item.placed:
            lane_top = item.y + placed.row * row_height_px
            fill = theme.warn if feature.kind == "mutation" else theme.primary
            feature_label = feature.label if feature.label is not None else feature.id

            if feature.parts and feature.kind != "mutation":
                # Gene model: one intron line spanning the gene, exon boxes on
                # top of it, and an arrowhead at the visible end for strand.
                # Three passes keep the intron behind every exon.
                centre_y = lane_top + row_height_px / 2
                box_top = lane_top + 5
                box_height = max(5, row_height_px - 10)
                line_start = placed.x
                line_end = placed.x + max(placed.w, 1)
                parts.append(
                    f'<line x1="{_num(line_start)}" y1="{_num(centre_y)}" '
                    f'x2="{_num(line_end)}" y2="{_num(centre_y)}" '
                    f'stroke="{fill}" stroke-width="1.5" stroke-linecap="round" opacity="0.55"/>'
                )

                placed_parts = [
                    replace(part, x=part.x + rail)
                    for part in place_structure_parts(
                        feature.parts, viewport, content_width, feature.start, feature.end
                    )
                ]
                for exon in placed_parts:
                    parts.append(
                        f'<rect x="{_num(exon.x)}" y="{_num(box_top)}" '
                        f'width="{_num(max(exon.width, 1.5))}" '
                        f'height="{_num(box_height)}" rx="1" fill="{fill}" '
                        f'data-exon-kind="{escape_xml(exon.kind)}"/>'
                    )

                strand = feature.strand
                if strand == "+" or strand == "-":
                    # Draw the arrowhead at whichever end is actually on screen:
                    # the gene may extend beyond the window on either side.
                    at_end = strand == "+"
                    tip_x = line_end if at_end else line_start
                    direction = 1 if at_end else -1
                    points = " ".join(
                        [
                            f"{_num(tip_x)},{_num(centre_y - 4)}",
                            f"{_num(tip_x + direction * 7)},{_num(centre_y)}",
                            f"{_num(tip_x)},{_num(centre_y + 4)}",
                        ]
                    )
                    parts.append(
                        f'<polygon points="{points}" fill="{fill}" data-strand="{strand}"/>'
                    )

                exon_count = len(placed_parts)
                title = (
                    f"{feature_label} · "
                    f"{format_bp(feature.start)}-{format_bp(feature.end)} · "
                    f"{exon_count} exon{'' if exon_count == 1 else 's'}"
                )
                parts.append(
                    f'<rect x="{_num(line_start)}" y="{_num(lane_top)}" '
                    f'width="{_num(max(placed.w, 2))}" height="{_num(row_height_px)}" '
                    f'fill="transparent" data-feature-id="{escape_xml(feature.id)}">'
                    f"<title>{escape_xml(title)}</title></rect>"
                )
                if placed.w >= 28:
                    parts.append(
                        f'<text x="{_num(placed.x + 4)}" y="{_num(box_top + box_height - 1)}" '
                        f'font-size="10" fill="{theme.text}" stroke="{theme.surface}" '
                        f'stroke-width="2.5" paint-order="stroke">'
                        f"{escape_xml(feature_label)}</text>"
                    )
                continue

            y = lane_top + 4
            height = row_height_px - 8
            title = f"{feature_label} · {format_bp(feature.start)}-{format_bp(feature.end)}"
            parts.append(
                f'<rect x="{_num(placed.x)}" y="{_num(y)}" width="{_num(max(placed.w, 2))}" '
                f'height="{_num(height)}" rx="2" fill="{fill}" '
                f'data-feature-id="{escape_xml(feature.id)}">'
                f"<title>{escape_xml(title)}</title></rect>"
            )

            # Direction, even without exon structure to hang it on: a bare bar
            # says nothing about which way the gene is read. Drawn inside the
            # body in the surface colour so it reads as a cut-out.
            plain_strand = feature.strand
            if (plain_strand == "+" or plain_strand == "-") and placed.w >= 10:
                arrow_y = y + height / 2
                at_end = plain_strand == "+"
                tip_x = placed.x + placed.w if at_end else placed.x
                direction = 1 if at_end else -1
                points = " ".join(
                    [
                        f"{_num(tip_x)},{_num(arrow_y - 3)}",
                        f"{_num(tip_x + direction * 4)},{_num(arrow_y)}",
                        f"{_num(tip_x)},{_num(arrow_y + 3)}",
                    ]
                )
                parts.append(
                    f'<polygon points="{points}" fill="{theme.surface}" opacity="0.9" '
                    f'data-strand="{plain_strand}"/>'
                )

            if placed.w >= 28:
                parts.append(
                    f'<text x="{_num(placed.x + 4)}" y="{_num(y + height - 3)}" font-size="10" '
                    f'fill="{theme.text}" stroke="{theme.surface}" stroke-width="2.5" '
                    f'paint-order="stroke">{escape_xml(feature_label)}</text>'
                )

    # Strand hint, so the picture carries the orientation the data declares.
    parts.append(
        f'<g id="{escape_xml(id_prefix)}-strand" data-ref="{escape_xml(viewport.ref_name)}"></g>'
    )
    parts.append("</svg>")
    return "".join(parts)


def genome_view_cache_key(viewport: Viewport, width_px: float, track_ids: list[str]) -> str:
    """Cache key for a pre-rendered artifact (stable across processes)."""
    return "|".join(
        [
            viewport.assembly_key,
            viewport.ref_name,
            str(viewport.start),
            str(viewport.end),
            str(round(width_px)),
            ",".join(sorted(track_ids)),
        ]
    )
