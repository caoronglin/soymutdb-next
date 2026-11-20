/**
 * Genome view -> SVG, as a pure function.
 *
 * Two consumers share this one implementation:
 *
 * 1. the pre-rendered route, which calls it in Node and caches the string, so a
 *    gene page ships a static picture instead of running a layout engine; and
 * 2. the interactive React component, which calls it for the current window.
 *
 * Keeping it free of DOM and framework APIs is what makes the static and the
 * interactive picture identical by construction rather than by review.
 */
import { computeTicks, formatBp } from "./ruler";
import { clipToRegion, layoutIntervals, type IntervalLike } from "./track-layout";
import { placeStructureParts, type PlacedPart, type StructurePart } from "./gene-structure";
import { bpPerPx, type GenomeViewport } from "./viewport";

/** A feature drawn inside a feature track. */
export interface SvgFeature extends IntervalLike {
  /** Rendering role; mutation sites are drawn as discrete marks. */
  kind?: "gene" | "mutation";
  label?: string;
  strand?: "+" | "-";
  /**
   * Exon/CDS/UTR sub-structure. When present the feature is drawn as a gene
   * model — exon boxes on an intron line with a strand arrowhead — instead of
   * one solid bar, which is what makes a real gene distinguishable from a
   * placeholder rectangle.
   */
  parts?: StructurePart[];
  /**
   * Draw the feature at reduced opacity.
   *
   * Used for flanking context: a locus picture shows every gene in the window,
   * but the one the page is about must be the feature the eye lands on first.
   * Dimming is per feature rather than a rectangle painted over the picture, so
   * the emphasis survives panning and zooming — the flanking genes stay dim and
   * the focus gene stays at full strength wherever the window moves to.
   */
  dim?: boolean;
}

/** One horizontal track. */
export interface SvgTrack {
  id: string;
  label: string;
  kind: "ruler" | "feature";
  features?: SvgFeature[];
}

/** Colours resolved from the antd theme by the caller; no hard-coded hexes. */
export interface GenomeViewSvgTheme {
  /** Page background (`colors.bgLayout`). */
  background: string;
  /** Track surface (`colors.bgContainer`). */
  surface: string;
  /** Primary text (`colors.text`, alpha 0.88). */
  text: string;
  /** Secondary text (`colors.textSecondary`, alpha 0.65). */
  textSecondary: string;
  /** Border / gridline (`colors.borderSecondary`). */
  border: string;
  /** Accent for feature bodies (`colors.primary`). */
  primary: string;
  /** Accent for mutation marks (`colors.warning`). */
  warn: string;
}

export interface GenomeViewSvgOptions {
  viewport: GenomeViewport;
  /**
   * Accessible name for the figure.
   *
   * Defaults to the window (`ref:start-end`, the only thing this function knows).
   * A caller that renders a locus *of something* passes its own name here so the
   * picture announces what it is a picture of, coordinates included.
   */
  ariaLabel?: string;
  /** Rendered width in CSS pixels; the SVG scales to its container. */
  widthPx: number;
  tracks: SvgTrack[];
  theme: GenomeViewSvgTheme;
  /** Height of one feature lane. */
  rowHeightPx?: number;
  /** Height of the ruler strip. */
  rulerHeightPx?: number;
  /** Gap between tracks. */
  gapPx?: number;
  /**
   * Width of the left label rail, in CSS pixels.
   *
   * Every track used to draw its label at x=8 while its content started at x=0,
   * so a long label (a full gene accession) was painted under the feature body
   * and a ruler label collided with the first tick. Real genome browsers solve
   * this with a fixed label rail; so does this renderer. SVG cannot measure
   * text, so the rail is a fixed width and callers keep their labels short
   * enough to fit — the rail fits {@link RAIL_CHARS_AT_11PX}.
   */
  labelRailPx?: number;
  /**
   * Draw a gene model's introns as strand chevrons between the exon boxes.
   *
   * Exons are solid boxes and introns are the line between them, so the two are
   * already different shapes; the chevrons add the standard gene-model
   * convention and make an intron readable as a gap with a direction rather
   * than as empty space — without relying on colour, which a dimmed flanking
   * gene or a colour-vision deficiency would flatten.
   *
   * Opt-in, not default: the Python pre-renderer reproduces this function byte
   * for byte (`apps/api/tests/fixtures/genome_view_svg_golden.json`), so a new
   * default would change every pre-rendered picture before that side can emit
   * the same markup. Callers that render for a person turn it on.
   */
  intronChevrons?: boolean;
  /** Font stack for labels. */
  fontFamily?: string;
  /** Stable id prefix so several views can live in one document. */
  idPrefix?: string;
}

const DEFAULTS = {
  rowHeightPx: 22,
  rulerHeightPx: 28,
  gapPx: 8,
  labelRailPx: 120,
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
} as const;

/**
 * Narrowest content area the rail may leave behind. On a phone-width view the
 * rail shrinks rather than squeezing the picture to nothing.
 */
const MIN_CONTENT_PX = 80;

/** Opacity for a `dim` feature: readable, but clearly not the focus. */
export const DIM_OPACITY = 0.35;

/** Escape text destined for an SVG text node. */
function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

/** Round to two decimals so the emitted markup stays small and diffable. */
function n(value: number): string {
  return Number.isFinite(value) ? String(Math.round(value * 100) / 100) : "0";
}

/** Narrowest a chevron gap may be before the chevrons would crowd the line. */
const MIN_CHEVRON_GAP_PX = 8;

/**
 * Chevrons inside a gene model's introns, one per gap between exon boxes.
 *
 * The gap between two placed exon boxes *is* the intron on screen, so the
 * chevrons are derived from the drawn boxes rather than from a separate intron
 * list — the picture and the marker cannot disagree. A gap narrower than
 * {@link MIN_CHEVRON_GAP_PX} is a line only: two chevrons in 3 px of space read
 * as noise, and the box edges already say where the intron starts.
 */
function intronChevrons(
  exons: readonly PlacedPart[],
  centreY: number,
  strand: "+" | "-" | undefined,
  fill: string,
): string[] {
  const marks: string[] = [];
  const direction = strand === "-" ? -1 : 1;
  const size = 3;
  for (let index = 1; index < exons.length; index += 1) {
    const previous = exons[index - 1];
    const next = exons[index];
    const gapStart = previous.x + previous.width;
    const gapEnd = next.x;
    if (!(gapEnd - gapStart >= MIN_CHEVRON_GAP_PX)) continue;
    const middle = (gapStart + gapEnd) / 2;
    const points = [
      `${n(middle - direction * size)},${n(centreY - size)}`,
      `${n(middle + direction * size)},${n(centreY)}`,
      `${n(middle - direction * size)},${n(centreY + size)}`,
    ].join(" ");
    marks.push(
      `<polyline points="${points}" fill="none" stroke="${fill}" stroke-width="1.5" ` +
        `stroke-linecap="round" stroke-linejoin="round" data-intron="true"/>`,
    );
  }
  return marks;
}

/**
 * Build the SVG markup for one viewport.
 *
 * Returns a complete `<svg>` element string. Coordinates are 1:1 with base
 * pairs through `bpPerPx`, so an x offset is reproducible from the tick labels.
 */
/**
 * Emit one feature's drawn elements into the track output.
 *
 * A `dim` feature (flanking context) is wrapped in a single translucent group so
 * its body, exons, strand arrowhead and label dim together; anything else is
 * emitted unchanged, which keeps the pre-rendered artifact byte-identical for a
 * caller that never sets the flag.
 */
function flushFeature(out: string[], drawn: string[], dim: boolean | undefined): void {
  if (drawn.length === 0) return;
  out.push(
    dim === true ? `<g opacity="${DIM_OPACITY}" data-dim="true">${drawn.join("")}</g>` : drawn.join(""),
  );
}

export function renderGenomeViewSvg(options: GenomeViewSvgOptions): string {
  const rowHeight = options.rowHeightPx ?? DEFAULTS.rowHeightPx;
  const rulerHeight = options.rulerHeightPx ?? DEFAULTS.rulerHeightPx;
  const gap = options.gapPx ?? DEFAULTS.gapPx;
  const font = options.fontFamily ?? DEFAULTS.fontFamily;
  const prefix = options.idPrefix ?? "gv";
  const { viewport, widthPx, tracks, theme } = options;

  const span = viewport.end - viewport.start;
  const scale = bpPerPx(viewport, widthPx);
  if (!Number.isFinite(widthPx) || widthPx <= 0 || span <= 0 || scale <= 0) {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${n(Math.max(widthPx, 1))}" height="${rulerHeight}" role="img" aria-label="Genome view unavailable"></svg>`;
  }

  // Label rail: every track's label owns the left strip, so content starts after
  // it and can never be painted over. On a narrow view the rail yields first.
  const rail = Math.max(
    0,
    Math.min(options.labelRailPx ?? DEFAULTS.labelRailPx, widthPx - MIN_CONTENT_PX),
  );
  const contentWidth = widthPx - rail;

  // Lay out every track first so the total height is known before emitting.
  interface RenderedTrack {
    track: SvgTrack;
    y: number;
    height: number;
    placed: Array<{ id: string; x: number; w: number; row: number; feature: SvgFeature }>;
    rowCount: number;
  }

  const rendered: RenderedTrack[] = [];
  let cursorY = 0;
  for (const track of tracks) {
    if (track.kind === "ruler") {
      rendered.push({ track, y: cursorY, height: rulerHeight, placed: [], rowCount: 0 });
      cursorY += rulerHeight + gap;
      continue;
    }
    const features = (track.features ?? []).filter((f) => clipToRegion(f, viewport) !== null);
    const layout = layoutIntervals(features, viewport, contentWidth);
    const height = Math.max(1, layout.rowCount) * rowHeight;
    const byId = new Map(features.map((f) => [f.id, f]));
    rendered.push({
      track,
      y: cursorY,
      height,
      rowCount: layout.rowCount,
      placed: layout.placed.flatMap((p) => {
        const feature = byId.get(p.id);
        // Shift into the content area once, here, so nothing downstream has to
        // remember the rail exists.
        return feature ? [{ ...p, x: p.x + rail, feature }] : [];
      }),
    });
    cursorY += height + gap;
  }
  const totalHeight = Math.max(cursorY - gap, rulerHeight);

  const parts: string[] = [];
  const figureLabel =
    options.ariaLabel ??
    `${viewport.refName}:${formatBp(viewport.start)}-${formatBp(viewport.end)}`;
  parts.push(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${n(widthPx)}" height="${n(totalHeight)}" ` +
      `viewBox="0 0 ${n(widthPx)} ${n(totalHeight)}" role="img" ` +
      `aria-label="${escapeXml(figureLabel)}" ` +
      `font-family="${escapeXml(font)}">`,
  );
  parts.push(
    `<rect x="0" y="0" width="${n(widthPx)}" height="${n(totalHeight)}" fill="${theme.background}"/>`,
  );

  for (const item of rendered) {
    parts.push(
      `<rect x="0" y="${n(item.y)}" width="${n(widthPx)}" height="${n(item.height)}" fill="${theme.surface}"/>`,
    );
    // Track labels are drawn in a stroke-and-fill style so a long label (a full
    // gene accession, for instance) stays legible where it overlaps an early
    // feature body. `paint-order="stroke"` puts the halo underneath the glyphs,
    // and the halo colour is the track surface, so on empty regions the label
    // looks exactly as it did before.
    parts.push(
      `<text x="8" y="${n(item.y + 14)}" font-size="11" fill="${theme.textSecondary}" ` +
        `stroke="${theme.surface}" stroke-width="3" paint-order="stroke">` +
        `${escapeXml(item.track.label)}</text>`,
    );

    if (item.track.kind === "ruler") {
      const ticks = computeTicks(viewport, contentWidth);
      for (const tick of ticks) {
        const tickX = tick.x + rail;
        parts.push(
          `<line x1="${n(tickX)}" y1="${n(item.y)}" x2="${n(tickX)}" ` +
            `y2="${n(item.y + item.height)}" stroke="${theme.border}" stroke-width="1"/>`,
        );
        parts.push(
          `<text x="${n(tickX + 3)}" y="${n(item.y + 12)}" font-size="10" ` +
            `fill="${theme.textSecondary}">${escapeXml(tick.label)}</text>`,
        );
      }
      continue;
    }

    if (item.placed.length === 0) {
      // Same rail offset as the track label: an empty lane still draws its label
      // on the left, so the placeholder has to start after the rail or the two
      // strings overlap.
      parts.push(
        `<text x="${n(rail + 8)}" y="${n(item.y + 22)}" font-size="11" fill="${theme.textSecondary}">` +
          `No features in this window</text>`,
      );
      continue;
    }

    for (const placed of item.placed) {
      // One buffer per feature so a dimmed feature becomes a single <g>, not a
      // stack of individually translucent elements that leak at the seams.
      const featureParts: string[] = [];
      const laneTop = item.y + placed.row * rowHeight;
      const fill = placed.feature.kind === "mutation" ? theme.warn : theme.primary;

      const structure = placed.feature.parts;
      if (structure && structure.length > 0 && placed.feature.kind !== "mutation") {
        // Gene model: one intron line spanning the gene, exon boxes on top of
        // it, and an arrowhead at the visible end for strand. Splitting these
        // into three passes keeps the intron behind every exon.
        const centreY = laneTop + rowHeight / 2;
        const boxTop = laneTop + 5;
        const boxHeight = Math.max(5, rowHeight - 10);
        const lineStart = placed.x;
        const lineEnd = placed.x + Math.max(placed.w, 1);
        featureParts.push(
          `<line x1="${n(lineStart)}" y1="${n(centreY)}" x2="${n(lineEnd)}" y2="${n(centreY)}" ` +
            `stroke="${fill}" stroke-width="1.5" stroke-linecap="round" opacity="0.55"` +
            `${options.intronChevrons ? ' data-intron-line="true"' : ""}/>`,
        );

        const placedParts: PlacedPart[] = placeStructureParts(
          structure,
          viewport,
          contentWidth,
          placed.feature.start,
          placed.feature.end,
        ).map((part) => ({ ...part, x: part.x + rail }));
        for (const exon of placedParts) {
          featureParts.push(
            `<rect x="${n(exon.x)}" y="${n(boxTop)}" width="${n(Math.max(exon.width, 1.5))}" ` +
              `height="${n(boxHeight)}" rx="1" fill="${fill}" data-exon-kind="${escapeXml(exon.kind)}"/>`,
          );
        }
        if (options.intronChevrons) {
          featureParts.push(...intronChevrons(placedParts, centreY, placed.feature.strand, fill));
        }

        const strand = placed.feature.strand;
        if (strand === "+" || strand === "-") {
          // Draw the arrowhead at whichever end is actually on screen: the
          // gene may extend beyond the window on either side.
          const atEnd = strand === "+";
          const tipX = atEnd ? lineEnd : lineStart;
          const direction = atEnd ? 1 : -1;
          const points = [
            `${n(tipX)},${n(centreY - 4)}`,
            `${n(tipX + direction * 7)},${n(centreY)}`,
            `${n(tipX)},${n(centreY + 4)}`,
          ].join(" ");
          featureParts.push(`<polygon points="${points}" fill="${fill}" data-strand="${strand}"/>`);
        }

        // An exon-accurate tooltip beats a bare coordinate range once the
        // picture actually shows structure.
        const featureLabel = placed.feature.label ?? placed.feature.id;
        featureParts.push(
          `<rect x="${n(lineStart)}" y="${n(laneTop)}" width="${n(Math.max(placed.w, 2))}" ` +
            `height="${n(rowHeight)}" fill="transparent" data-feature-id="${escapeXml(placed.feature.id)}">` +
            `<title>${escapeXml(
              `${featureLabel} · ${formatBp(placed.feature.start)}-${formatBp(placed.feature.end)} · ` +
                `${placedParts.length} exon${placedParts.length === 1 ? "" : "s"}`,
            )}</title></rect>`,
        );
        if (placed.w >= 28) {
          // Haloed like the track label above, and for the same reason: a gene
          // model is not a solid block. The label starts inside the gene body
          // and runs across the intron gaps between the exon boxes, so a
          // surface-coloured glyph is invisible over the background half the
          // time. The halo gives it an outline on either surface.
          featureParts.push(
            `<text x="${n(placed.x + 4)}" y="${n(boxTop + boxHeight - 1)}" font-size="10" ` +
              `fill="${theme.text}" stroke="${theme.surface}" stroke-width="2.5" ` +
              `paint-order="stroke">${escapeXml(featureLabel)}</text>`,
          );
        }
        flushFeature(parts, featureParts, placed.feature.dim);
        continue;
      }

      const y = laneTop + 4;
      const height = rowHeight - 8;
      featureParts.push(
        `<rect x="${n(placed.x)}" y="${n(y)}" width="${n(Math.max(placed.w, 2))}" height="${n(height)}" ` +
          `rx="2" fill="${fill}" data-feature-id="${escapeXml(placed.feature.id)}">` +
          `<title>${escapeXml(
            `${placed.feature.label ?? placed.feature.id} · ${formatBp(placed.feature.start)}-${formatBp(placed.feature.end)}`,
          )}</title></rect>`,
      );

      // Direction, even without exon structure to hang it on: a bare bar says
      // nothing about which way the gene is read. Drawn inside the body in the
      // surface colour so it reads as a cut-out rather than another feature.
      const plainStrand = placed.feature.strand;
      if ((plainStrand === "+" || plainStrand === "-") && placed.w >= 10) {
        const arrowY = y + height / 2;
        const atEnd = plainStrand === "+";
        const tipX = atEnd ? placed.x + placed.w : placed.x;
        const direction = atEnd ? 1 : -1;
        const points = [
          `${n(tipX)},${n(arrowY - 3)}`,
          `${n(tipX + direction * 4)},${n(arrowY)}`,
          `${n(tipX)},${n(arrowY + 3)}`,
        ].join(" ");
        featureParts.push(
          `<polygon points="${points}" fill="${theme.surface}" opacity="0.9" ` +
            `data-strand="${plainStrand}"/>`,
        );
      }

      if (placed.w >= 28) {
        // Same halo as the gene-model branch: a bar label that runs past its
        // body must stay readable against the lane background.
        featureParts.push(
          `<text x="${n(placed.x + 4)}" y="${n(y + height - 3)}" font-size="10" ` +
            `fill="${theme.text}" stroke="${theme.surface}" stroke-width="2.5" ` +
            `paint-order="stroke">` +
            `${escapeXml(placed.feature.label ?? placed.feature.id)}</text>`,
        );
      }

      flushFeature(parts, featureParts, placed.feature.dim);
    }
  }

  // Strand hint, so the picture carries the orientation the data declares.
  parts.push(`<g id="${escapeXml(prefix)}-strand" data-ref="${escapeXml(viewport.refName)}"></g>`);
  parts.push("</svg>");
  return parts.join("");
}

/** Cache key for a pre-rendered artifact. */
export function genomeViewCacheKey(
  viewport: GenomeViewport,
  widthPx: number,
  trackIds: readonly string[],
): string {
  return [
    viewport.assemblyKey,
    viewport.refName,
    viewport.start,
    viewport.end,
    Math.round(widthPx),
    [...trackIds].sort().join(","),
  ].join("|");
}
