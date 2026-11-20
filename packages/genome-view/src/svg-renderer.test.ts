import { describe, expect, it } from "vitest";

import {
  DIM_OPACITY,
  genomeViewCacheKey,
  renderGenomeViewSvg,
  type GenomeViewSvgTheme,
} from "./svg-renderer";
import { createViewport } from "./viewport";

const theme: GenomeViewSvgTheme = {
  background: "#f5f5f5",
  surface: "#ffffff",
  text: "rgba(0,0,0,0.88)",
  textSecondary: "rgba(0,0,0,0.65)",
  border: "#d9d9d9",
  primary: "#0f6b3c",
  warn: "#d48806",
};

const viewport = createViewport({
  assemblyKey: "Gmax_880_v6.0",
  refName: "Gm01",
  start: 0,
  end: 10000,
});

describe("renderGenomeViewSvg", () => {
  it("emits a self-contained svg element", () => {
    const svg = renderGenomeViewSvg({ viewport, widthPx: 600, tracks: [], theme });
    expect(svg.startsWith("<svg ")).toBe(true);
    expect(svg.endsWith("</svg>")).toBe(true);
    expect(svg).toContain('viewBox="0 0 600 ');
  });

  it("is identical for identical input, so the pre-rendered artifact matches", () => {
    const options = { viewport, widthPx: 600, tracks: [], theme };
    expect(renderGenomeViewSvg(options)).toBe(renderGenomeViewSvg(options));
  });

  it("draws a tick label per ruler tick", () => {
    const svg = renderGenomeViewSvg({
      viewport,
      widthPx: 600,
      theme,
      tracks: [{ id: "ruler", label: "Ruler", kind: "ruler" }],
    });
    // 0 and 10,000 bound the window; the grouping separator is deterministic.
    expect(svg).toContain(">0</text>");
    expect(svg).toContain("10,000");
  });

  it("draws features that intersect the window and drops the rest", () => {
    const svg = renderGenomeViewSvg({
      viewport,
      widthPx: 600,
      theme,
      tracks: [
        {
          id: "genes",
          label: "Genes",
          kind: "feature",
          features: [
            { id: "inside", start: 1000, end: 2000, label: "inside" },
            { id: "before", start: 50000, end: 60000, label: "before" },
          ],
        },
      ],
    });
    expect(svg).toContain('data-feature-id="inside"');
    expect(svg).not.toContain('data-feature-id="before"');
  });

  it("escapes interpolated text so markup cannot break out of the attribute", () => {
    const svg = renderGenomeViewSvg({
      viewport,
      widthPx: 600,
      theme,
      tracks: [
        {
          id: "genes",
          label: 'Genes <script>alert("x")</script>',
          kind: "feature",
          features: [
            { id: 'a"b<c', start: 1000, end: 2000, label: "<img src=x onerror=1>" },
          ],
        },
      ],
    });
    expect(svg).not.toContain("<script>");
    expect(svg).not.toContain("<img");
    expect(svg).toContain("&lt;script&gt;");
    expect(svg).toContain("&lt;img");
  });

  it("states the window in the accessible label", () => {
    const svg = renderGenomeViewSvg({ viewport, widthPx: 600, tracks: [], theme });
    expect(svg).toContain('aria-label="Gm01:0-10,000"');
  });

  it("lets the caller name what the picture is of", () => {
    const svg = renderGenomeViewSvg({
      viewport,
      widthPx: 600,
      tracks: [],
      theme,
      ariaLabel: "Genes around AT1G01010, window Gm01:0-10,000",
    });
    expect(svg).toContain('aria-label="Genes around AT1G01010, window Gm01:0-10,000"');
  });

  it("draws a dimmed feature as one translucent group, leaving the focus at full strength", () => {
    const svg = renderGenomeViewSvg({
      viewport,
      widthPx: 600,
      theme,
      tracks: [
        {
          id: "genes",
          label: "Genes",
          kind: "feature",
          features: [
            { id: "focus", start: 4000, end: 6000, label: "focus", strand: "+" },
            { id: "context", start: 1000, end: 2000, label: "context", dim: true },
          ],
        },
      ],
    });
    // The flanking gene is one group, so its body, label and strand dim together.
    const open = `<g opacity="${DIM_OPACITY}" data-dim="true">`;
    const groupStart = svg.indexOf(open);
    expect(groupStart).toBeGreaterThan(-1);
    expect(svg.slice(groupStart, svg.indexOf("</g>", groupStart))).toContain(
      'data-feature-id="context"',
    );
    // The focus feature carries no opacity of its own.
    expect(svg).toContain('data-feature-id="focus"');
    expect(svg.match(/data-dim="true"/g)?.length).toBe(1);
  });

  it("draws introns as chevrons between the exon boxes when asked", () => {
    const options = {
      viewport,
      widthPx: 900,
      theme,
      tracks: [
        {
          id: "gene",
          label: "gene",
          kind: "feature" as const,
          features: [
            {
              id: "G",
              start: 1000,
              end: 8000,
              kind: "gene" as const,
              label: "G",
              strand: "+" as const,
              parts: [
                { start: 1000, end: 2000, kind: "exon" as const },
                { start: 5000, end: 6000, kind: "exon" as const },
                { start: 7000, end: 8000, kind: "exon" as const },
              ],
            },
          ],
        },
      ],
    };

    const plain = renderGenomeViewSvg(options);
    // Default output is the byte-parity contract with the Python pre-renderer:
    // no intron marker may appear unless the caller asks for one.
    expect(plain).not.toContain("data-intron");

    const svg = renderGenomeViewSvg({ ...options, intronChevrons: true });
    // Three exon boxes stay rectangles; each of the two gaps between them gets a
    // chevron, so an intron is a mark of its own and not just a gap.
    expect(svg.match(/data-exon-kind="exon"/g)?.length).toBe(3);
    expect(svg.match(/data-intron="true"/g)?.length).toBe(2);
    expect(svg).toContain('data-intron-line="true"');
    // Shape, not colour: the intron marker is a polyline, never a box.
    expect(svg).toMatch(
      /<polyline points="[^"]+" fill="none" stroke="#0f6b3c" stroke-width="1\.5" stroke-linecap="round" stroke-linejoin="round" data-intron="true"\/>/,
    );
    expect(svg).not.toMatch(/<rect[^>]*data-intron="true"/);
  });

  it("keeps a narrow intron a line, because two chevrons there read as noise", () => {
    // 200 bp of exon, 1 bp of intron, 200 bp of exon across a 1000 bp window at
    // 900 px: the gap is under a pixel wide.
    const svg = renderGenomeViewSvg({
      viewport,
      widthPx: 900,
      theme,
      intronChevrons: true,
      tracks: [
        {
          id: "gene",
          label: "gene",
          kind: "feature",
          features: [
            {
              id: "G",
              start: 0,
              end: 401,
              kind: "gene",
              label: "G",
              strand: "+",
              parts: [
                { start: 0, end: 200, kind: "exon" },
                { start: 201, end: 401, kind: "exon" },
              ],
            },
          ],
        },
      ],
    });
    expect(svg).not.toContain('data-intron="true"');
    expect(svg).toContain('data-intron-line="true"');
  });

  it("returns a placeholder for a degenerate width instead of throwing", () => {
    const svg = renderGenomeViewSvg({ viewport, widthPx: 0, tracks: [], theme });
    expect(svg).toContain("Genome view unavailable");
    expect(svg).not.toContain("undefined");
  });
});

describe("genomeViewCacheKey", () => {
  it("varies with the window, the width and the track set", () => {
    const base = genomeViewCacheKey(viewport, 600, ["b", "a"]);
    // Track order must not matter, so a reordered registration set hits the cache.
    expect(genomeViewCacheKey(viewport, 600, ["a", "b"])).toBe(base);
    expect(genomeViewCacheKey(viewport, 601, ["a", "b"])).not.toBe(base);
  });
});
