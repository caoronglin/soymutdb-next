/**
 * Regenerate the SVG golden file that pins the Python pre-renderer to this one.
 *
 * The API re-implements this renderer in Python so a gene page can fetch a
 * pre-rendered picture. Two implementations of one picture is exactly the kind
 * of drift that review does not catch, so the contract is enforced by bytes:
 * this script writes the TypeScript output, and
 * `apps/api/tests/test_genome_view_svg_parity.py` asserts the Python renderer
 * reproduces it character for character.
 *
 * Usage (from the repo root):
 *   apps/admin/node_modules/.bin/tsx packages/genome-view/scripts/gen-svg-golden.ts
 */
import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  renderGenomeViewSvg,
  type GenomeViewSvgOptions,
} from "../src/svg-renderer";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, "../../../apps/api/tests/fixtures/genome_view_svg_golden.json");

/** Fixed palette: the golden must not depend on a live antd theme. */
const theme = {
  background: "#fafafa",
  surface: "#ffffff",
  text: "#262626",
  textSecondary: "#8c8c8c",
  border: "#f0f0f0",
  primary: "#2f6f4f",
  warn: "#faad14",
};

interface Case {
  name: string;
  why: string;
  options: GenomeViewSvgOptions;
}

const GENE = {
  id: "Glyma.01G066600.Wm82.a6.v1",
  start: 10685338,
  end: 10694003,
  kind: "gene" as const,
  label: "Glyma.01G066600.Wm82.a6.v1",
  strand: "+" as const,
};

const cases: Case[] = [
  {
    name: "ruler-and-single-gene",
    why: "The ordinary gene page: a leading ruler plus one body.",
    options: {
      viewport: { assemblyKey: "Gmax_880_v6.0", refName: "Gm01", start: 10685338, end: 10694003 },
      widthPx: 900,
      tracks: [
        { id: "ruler", label: "Gm01", kind: "ruler" },
        { id: "gene", label: "Glyma.01G066600.Wm82.a6.v1 (+)", kind: "feature", features: [GENE] },
      ],
      theme,
    },
  },
  {
    name: "overlapping-features-wrap-to-rows",
    why: "Exercises the greedy first-fit row packing and the max-row height.",
    options: {
      viewport: { assemblyKey: "Gmax_880_v6.0", refName: "Gm01", start: 1000, end: 2000 },
      widthPx: 300,
      tracks: [
        { id: "ruler", label: "Gm01", kind: "ruler" },
        {
          id: "gene",
          label: "overlapping",
          kind: "feature",
          features: [
            { id: "a", start: 1000, end: 1500, kind: "gene", label: "A" },
            { id: "b", start: 1010, end: 1520, kind: "gene", label: "B" },
            { id: "c", start: 1020, end: 1540, kind: "gene", label: "C" },
          ],
        },
      ],
      theme,
    },
  },
  {
    name: "mutation-marks-use-warn-colour",
    why: "Mutation sites must be visually distinct from gene bodies.",
    options: {
      viewport: { assemblyKey: "Gmax_880_v6.0", refName: "Gm01", start: 10690000, end: 10693000 },
      widthPx: 600,
      tracks: [
        { id: "ruler", label: "Gm01", kind: "ruler" },
        {
          id: "sites",
          label: "Mutation sites (2)",
          kind: "feature",
          features: [
            { id: "SOYTE1M-Gm01-10692035", start: 10692035, end: 10692036, kind: "mutation", label: "line-a" },
            { id: "SOYTE1M-Gm01-10692100", start: 10692100, end: 10692101, kind: "mutation", label: "line-b" },
          ],
        },
      ],
      theme,
    },
  },
  {
    name: "empty-track",
    why: 'Pins the "No features in this window" placeholder.',
    options: {
      viewport: { assemblyKey: "Gmax_880_v6.0", refName: "Gm02", start: 0, end: 5000 },
      widthPx: 640,
      tracks: [
        { id: "ruler", label: "Gm02", kind: "ruler" },
        { id: "sites", label: "Mutation sites (0)", kind: "feature", features: [] },
      ],
      theme,
    },
  },
  {
    name: "narrow-window-tight-ticks",
    why: "Small spans change the nice-step ladder and the px/bp direction.",
    options: {
      viewport: { assemblyKey: "Gmax_880_v6.0", refName: "Gm01", start: 10692000, end: 10692120 },
      widthPx: 1200,
      tracks: [{ id: "ruler", label: "Gm01", kind: "ruler" }],
      theme,
    },
  },
  {
    name: "wide-feature-shows-inline-label",
    why: "The w >= 28 label threshold is a visible behaviour change if it drifts.",
    options: {
      viewport: { assemblyKey: "Gmax_880_v6.0", refName: "Gm03", start: 0, end: 100 },
      widthPx: 2000,
      tracks: [
        { id: "ruler", label: "Gm03", kind: "ruler" },
        {
          id: "gene",
          label: "wide",
          kind: "feature",
          features: [
            { id: "wide", start: 0, end: 60, kind: "gene", label: "WIDE-LABEL" },
            { id: "tiny", start: 70, end: 71, kind: "mutation", label: "T" },
          ],
        },
      ],
      theme,
    },
  },
  {
    name: "escapes-hostile-labels",
    why: "Pins XML escaping so a crafted label cannot break the picture or inject markup.",
    options: {
      viewport: { assemblyKey: "x<&>y", refName: 'chr"1\'', start: 0, end: 1000 },
      widthPx: 500,
      tracks: [
        { id: "ruler", label: '<script>&"\'', kind: "ruler" },
        {
          id: "gene",
          label: "a&b",
          kind: "feature",
          features: [{ id: "f<&>", start: 100, end: 900, kind: "gene", label: '"quoted" & <tag>' }],
        },
      ],
      theme,
      idPrefix: 'p"x',
    },
  },
  {
    name: "gene-model-with-exons",
    why: "The gene model: exon boxes on an intron line plus a forward strand arrowhead.",
    options: {
      viewport: { assemblyKey: "Gmax_880_v6.0", refName: "Gm01", start: 10685338, end: 10694003 },
      widthPx: 900,
      tracks: [
        { id: "ruler", label: "Gm01", kind: "ruler" },
        {
          id: "gene",
          label: "基因 (+)",
          kind: "feature",
          features: [
            {
              id: "Glyma.01G066600.Wm82.a6.v1",
              start: 10685338,
              end: 10694003,
              kind: "gene",
              label: "Glyma.01G066600.Wm82.a6.v1",
              strand: "+",
              parts: [
                { start: 10685338, end: 10685700, kind: "exon" },
                { start: 10687000, end: 10687450, kind: "exon" },
                { start: 10691500, end: 10692100, kind: "exon" },
                { start: 10693500, end: 10694003, kind: "exon" },
              ],
            },
          ],
        },
      ],
      theme,
    },
  },
  {
    name: "gene-model-reverse-strand",
    why: "A minus-strand gene puts its arrowhead on the left, where the other end is.",
    options: {
      viewport: { assemblyKey: "Gmax_880_v6.0", refName: "Gm02", start: 0, end: 10000 },
      widthPx: 800,
      tracks: [
        { id: "ruler", label: "Gm02", kind: "ruler" },
        {
          id: "gene",
          label: "reverse",
          kind: "feature",
          features: [
            {
              id: "rev",
              start: 1000,
              end: 9000,
              kind: "gene",
              label: "REV",
              strand: "-",
              parts: [
                { start: 1000, end: 2000, kind: "exon" },
                { start: 8000, end: 9000, kind: "exon" },
              ],
            },
          ],
        },
      ],
      theme,
    },
  },
  {
    name: "gene-model-no-strand-no-arrow",
    why: "An unrecorded strand must not be drawn as if it were forward.",
    options: {
      viewport: { assemblyKey: "Gmax_880_v6.0", refName: "Gm03", start: 0, end: 10000 },
      widthPx: 800,
      tracks: [
        { id: "ruler", label: "Gm03", kind: "ruler" },
        {
          id: "gene",
          label: "unknown strand",
          kind: "feature",
          features: [
            {
              id: "unk",
              start: 1000,
              end: 9000,
              kind: "gene",
              label: "UNK",
              parts: [{ start: 2000, end: 3000, kind: "exon" }],
            },
          ],
        },
      ],
      theme,
    },
  },
  {
    name: "gene-model-exon-overhangs-gene",
    why: "A mis-annotated exon is clamped to the gene body, not smeared past it.",
    options: {
      viewport: { assemblyKey: "Gmax_880_v6.0", refName: "Gm04", start: 0, end: 10000 },
      widthPx: 800,
      tracks: [
        { id: "ruler", label: "Gm04", kind: "ruler" },
        {
          id: "gene",
          label: "overhang",
          kind: "feature",
          features: [
            {
              id: "ovh",
              start: 2000,
              end: 8000,
              kind: "gene",
              label: "OVH",
              strand: "+",
              parts: [
                { start: 500, end: 2500, kind: "exon" },
                { start: 7500, end: 9500, kind: "exon" },
              ],
            },
          ],
        },
      ],
      theme,
    },
  },
  {
    name: "gene-model-partly-offscreen",
    why: "Zoomed in far enough that the gene starts before the window.",
    options: {
      viewport: { assemblyKey: "Gmax_880_v6.0", refName: "Gm05", start: 4000, end: 8000 },
      widthPx: 800,
      tracks: [
        { id: "ruler", label: "Gm05", kind: "ruler" },
        {
          id: "gene",
          label: "clipped",
          kind: "feature",
          features: [
            {
              id: "clip",
              start: 1000,
              end: 9000,
              kind: "gene",
              label: "CLIP",
              strand: "+",
              parts: [
                { start: 1000, end: 5000, kind: "exon" },
                { start: 6000, end: 9000, kind: "exon" },
              ],
            },
          ],
        },
      ],
      theme,
    },
  },
  {
    name: "plain-feature-strand-arrow",
    why: "Without exon data a gene is only a bar, but it must still show direction; a sliver must not.",
    options: {
      viewport: { assemblyKey: "Gmax_880_v6.0", refName: "Gm06", start: 0, end: 10000 },
      widthPx: 800,
      tracks: [
        { id: "ruler", label: "Gm06", kind: "ruler" },
        {
          id: "gene",
          label: "plain",
          kind: "feature",
          features: [
            { id: "fwd", start: 1000, end: 4000, kind: "gene", label: "FWD", strand: "+" },
            { id: "rev", start: 5000, end: 8000, kind: "gene", label: "REV", strand: "-" },
            // 5 bp across 800 px is 0.4 px wide: below the arrow threshold.
            { id: "sliver", start: 8100, end: 8105, kind: "gene", label: "S", strand: "+" },
          ],
        },
      ],
      theme,
    },
  },
  {
    name: "KNOWN-LIMIT-overlong-track-label-overflows-rail",
    why:
      "Records a deliberate limit: the label rail is a fixed 120 px because SVG " +
      "cannot measure text, so a label past ~18 characters spills over its content. " +
      "Callers must pass short track labels (the web gene page passes '基因 (+)'); " +
      "the full accession belongs in the feature label and the page heading.",
    options: {
      viewport: { assemblyKey: "Gmax_880_v6.0", refName: "Gm07", start: 0, end: 10000 },
      widthPx: 800,
      tracks: [
        { id: "ruler", label: "Gm07", kind: "ruler" },
        {
          id: "gene",
          label: "Glyma.01G066600.Wm82.a6.v1 (+)",
          kind: "feature",
          features: [{ id: "long", start: 1000, end: 9000, kind: "gene", label: "LONG", strand: "+" }],
        },
      ],
      theme,
    },
  },
];

const golden = {
  generator: "packages/genome-view/scripts/gen-svg-golden.ts",
  note: "Byte-for-byte contract between the TypeScript and Python genome-view SVG renderers.",
  cases: cases.map((item) => ({
    name: item.name,
    why: item.why,
    options: item.options,
    svg: renderGenomeViewSvg(item.options),
  })),
};

writeFileSync(OUT, `${JSON.stringify(golden, null, 2)}\n`, "utf8");
console.log(`wrote ${golden.cases.length} cases to ${OUT}`);
