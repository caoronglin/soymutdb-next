import { describe, expect, it } from "vitest";

import { genomeViewCacheKey, renderGenomeViewSvg, type GenomeViewSvgTheme } from "./svg-renderer";
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
