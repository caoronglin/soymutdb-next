/**
 * Simplified genome view for the gene detail page.
 *
 * The lightweight, always-available counterpart to the full JBrowse 2 browser
 * (still reachable at /search/gbrowse and from the "open in browser" action).
 * It draws a fixed locus window — 2000 bp upstream and 2000 bp downstream of the
 * gene, clamped to the chromosome — containing **every** annotated gene the API
 * reports for that window, plus the operator's mutation sites.
 *
 * Emphasis follows the question the picture answers ("what surrounds this
 * gene?"): the page's own gene is drawn at full strength in its own lane, and
 * every neighbouring gene is drawn dimmed (`SvgFeature.dim`, rendered at reduced
 * opacity). Dimming per feature rather than painting a rectangle over the
 * picture keeps the emphasis correct after a pan or zoom.
 *
 * The neighbouring genes come from `GET /genes/region-structure`, which is the
 * only endpoint that answers "which genes are in this window" — the per-gene
 * `/{gene_id}/genome-view.svg` route pictures one gene and cannot. When that
 * request fails, the component says so instead of drawing an empty context.
 *
 * Because `@soymutdb/genome-view` renders SVG, the same facts are also available
 * as text: the window and gene count are printed under the figure, and a
 * screen-reader-only table lists every gene in the window with its coordinates.
 *
 * Page placement and animation are the caller's concern; this component owns the
 * mapping from API records to tracks, and — because `@soymutdb/genome-view`
 * carries no UI kit — it also owns the control bar, which is built from antd
 * components here rather than from bare HTML inside the package.
 */
import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  CompressOutlined,
  LeftOutlined,
  RightOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from "@ant-design/icons";
import {
  Button,
  Card,
  Flex,
  Segmented,
  Space,
  Tag,
  Tooltip,
  Typography,
  theme as antdTheme,
} from "@/lib/antd";
import {
  GenomeView,
  mergeExonSpans,
  type GenomeViewControlsApi,
  type GenomeViewSvgTheme,
  type StructurePart,
  type SvgFeature,
  type SvgTrack,
} from "@soymutdb/genome-view";
import {
  getRegionStructure,
  type RegionGene,
  type TestDataPreviewMutationSite,
} from "@soymutdb/api-client";
import { isRegionStructureRecord } from "../lib/api-contract-guards";
import { formatNumber } from "../lib/format";
import {
  GENE_CONTEXT_FLANK_BP,
  buildGeneContextTracks,
  describeGeneContextPoint,
  geneContextRegion,
  geneContextWindow,
  type GeneContextPoint,
} from "../lib/gene-context-view";

/** The gene fields this view needs; kept structural so it accepts the page's type. */
export interface GenomeViewGene {
  gene_id: string;
  chromosome: string;
  start_pos: number;
  end_pos: number;
  strand?: string;
  /** Assembly scope of the coordinates; the region query is assembly-scoped. */
  assembly_id?: string | number | null;
  transcripts?: Array<{
    id: string;
    name?: string | null;
    start: number;
    end: number;
    is_canonical?: boolean;
    /** Exon spans; the union across isoforms becomes the gene model. */
    exons?: Array<{ start: number; end: number }>;
  }>;
}

export interface GeneGenomeViewProps {
  gene: GenomeViewGene;
  /** Operator mutation sites for this gene, drawn as separate marks. */
  mutationSites?: TestDataPreviewMutationSite[];
  /** Assembly label shown next to the title. */
  assemblyLabel?: string;
  /** Static SVG URL from the pre-render route, when the caller has one. */
  prerenderedSrc?: string;
  /** Called with the new window so the page can mirror it in the URL. */
  onViewportChange?: (window: { start: number; end: number }) => void;
  className?: string;
}

type TrackChoice = "gene" | "sites" | "both";

/** Base pairs per pixel at or above which the scale reads as bp/px. */
const BP_PER_PX_MIN = 1;

/**
 * The rendered track width the pointer snap is calibrated against.
 *
 * The SVG scales to its container, so the component cannot know the width at
 * render time. This is the measured desktop width; a narrower viewport makes
 * the real bp-per-pixel larger, so the snap radius below is slightly tighter
 * than one screen pixel there. That error points the safe way: the mark is
 * drawn with a minimum width on screen, so it is still visible, and a snap
 * that is too small under-claims rather than naming the wrong feature.
 */
const NOMINAL_TRACK_PX = 1300;

function formatSpan(bpPerPx: number): string {
  if (!Number.isFinite(bpPerPx) || bpPerPx <= 0) return "—";
  return bpPerPx >= BP_PER_PX_MIN
    ? `${Math.round(bpPerPx).toLocaleString()} bp/px`
    : `${(1 / bpPerPx).toFixed(1)} px/bp`;
}

export function GeneGenomeView({
  gene,
  mutationSites = [],
  assemblyLabel,
  prerenderedSrc,
  onViewportChange,
  className,
}: GeneGenomeViewProps) {
  const { t } = useTranslation();
  const { token } = antdTheme.useToken();
  const [choice, setChoice] = React.useState<TrackChoice>("both");
  // Local state only: the readout follows the pointer without touching routing,
  // so this stays an in-page update rather than a navigation.
  const [hoverBp, setHoverBp] = React.useState<number | null>(null);

  const { gene_id: geneId, chromosome, start_pos: geneStart, end_pos: geneEnd } = gene;
  const assemblyId = gene.assembly_id == null ? undefined : String(gene.assembly_id);

  // The chromosome length arrives with the region response, so this request
  // carries the half-clamped window (upstream edge at base 1) and the window is
  // re-derived below from the length the API reports for the same chromosome.
  const requestedWindow = React.useMemo(
    () => geneContextWindow({ start_pos: geneStart, end_pos: geneEnd }),
    [geneStart, geneEnd],
  );

  const regionQuery = useQuery({
    queryKey: [
      "gene-region-structure",
      assemblyId ?? null,
      chromosome,
      requestedWindow.start,
      requestedWindow.end,
    ],
    queryFn: () =>
      getRegionStructure({
        assemblyId: assemblyId!,
        chromosome,
        start: requestedWindow.start,
        end: requestedWindow.end,
      }),
    enabled: assemblyId !== undefined,
    retry: false,
  });
  // A list-shaped or empty body must read as "no context", never as a structure
  // whose `genes` array happens to be absent.
  const structure = isRegionStructureRecord(regionQuery.data) ? regionQuery.data : undefined;

  const chromosomeLength = structure?.chromosome_length ?? null;
  const window = React.useMemo(
    () => geneContextWindow({ start_pos: geneStart, end_pos: geneEnd }, chromosomeLength),
    [geneStart, geneEnd, chromosomeLength],
  );
  const region = React.useMemo(
    () => geneContextRegion({ chromosome, start_pos: geneStart, end_pos: geneEnd }, window, assemblyLabel),
    [chromosome, geneStart, geneEnd, window, assemblyLabel],
  );

  /** Every other gene in the window; the page's own gene is drawn separately. */
  const contextGenes = React.useMemo<RegionGene[]>(
    () => (structure?.genes ?? []).filter((candidate) => candidate.gene_id !== geneId),
    [structure, geneId],
  );

  // The antd theme is the single source of colour; the SVG renderer never
  // hard-codes a hex, which is what keeps this panel consistent in dark mode.
  const svgTheme = React.useMemo<GenomeViewSvgTheme>(
    () => ({
      background: token.colorFillQuaternary,
      surface: token.colorBgContainer,
      text: token.colorText,
      textSecondary: token.colorTextSecondary,
      border: token.colorBorderSecondary,
      primary: token.colorPrimary,
      warn: token.colorWarning,
    }),
    [token],
  );

  const transcripts = React.useMemo(() => gene.transcripts ?? [], [gene.transcripts]);
  /** Only worth its own lane once there is more than the gene body itself. */
  const showTranscriptLane = transcripts.length > 1;

  /**
   * The gene's exon structure, taken as the union across its isoforms.
   *
   * Overlapping or abutting exons merge; a genuine intron gap survives. This is
   * the gene's exon structure, never a fabricated single transcript — which is
   * why the merge is span-based rather than a pick-one-isoform shortcut.
   */
  const exonParts = React.useMemo<StructurePart[]>(() => {
    const spans = mergeExonSpans(
      transcripts.flatMap((transcript) =>
        (transcript.exons ?? []).map((exon) => ({ start: exon.start, end: exon.end })),
      ),
    );
    return spans.map((span) => ({ start: span.start, end: span.end, kind: "exon" as const }));
  }, [transcripts]);

  // The selected gene comes from the detail response, which is authoritative for
  // this gene; the region response is only trusted for the neighbours.
  const selectedFeature = React.useMemo<SvgFeature>(
    () => ({
      id: geneId,
      start: geneStart,
      end: geneEnd,
      kind: "gene",
      label: geneId,
      strand: gene.strand === "-" ? "-" : "+",
      // With exons on record the gene draws as a real gene model; without them
      // it falls back to a single bar rather than an empty lane.
      parts: exonParts,
    }),
    [geneId, geneStart, geneEnd, gene.strand, exonParts],
  );

  const transcriptLanes = React.useMemo<SvgTrack[]>(() => {
    if (!showTranscriptLane) return [];
    return [
      {
        id: "transcripts",
        label: t("genomeView.tracks.transcripts", { total: transcripts.length }),
        kind: "feature",
        features: transcripts.map((transcript) => ({
          id: transcript.id,
          start: transcript.start,
          end: transcript.end,
          kind: "gene" as const,
          label: `${transcript.name ?? transcript.id}${transcript.is_canonical ? " · canonical" : ""}`,
        })),
      },
    ];
  }, [showTranscriptLane, transcripts, t]);

  const mutationFeatures = React.useMemo<SvgFeature[]>(
    () =>
      mutationSites.map((site) => ({
        id: site.source_site_key,
        start: site.position,
        end: site.position + 1,
        kind: "mutation" as const,
        label: `${site.mutant_line_name} · ${
          site.confidence === "H" ? t("genes.confidence.high") : t("genes.confidence.low")
        }`,
      })),
    [mutationSites, t],
  );

  const tracks = React.useMemo<SvgTrack[]>(() => {
    const lanes = buildGeneContextTracks({
      chromosome,
      selected: selectedFeature,
      contextGenes,
      mutationFeatures,
      afterSelected: transcriptLanes,
      labels: {
        selected: t("genomeView.tracks.selected"),
        context: t("genomeView.tracks.context", { total: contextGenes.length }),
        sites: t("genomeView.tracks.sites", { total: mutationFeatures.length }),
      },
    });
    if (choice === "both") return lanes;
    const visible =
      choice === "gene"
        ? new Set(["ruler", "gene", "context", "transcripts"])
        : new Set(["ruler", "sites"]);
    return lanes.filter((lane) => visible.has(lane.id));
  }, [chromosome, selectedFeature, contextGenes, mutationFeatures, transcriptLanes, choice, t]);

  // A variant site is one base pair, but the renderer draws every mark at least
  // two pixels wide so it is visible at all. An exact-hit test therefore
  // answered "intron" for a mark the reader could plainly see: the hit zone was
  // 2 bp where the picture showed ~2 px. The snap radius is one pixel of bp, so
  // the reachable area matches the drawn mark instead of contradicting it.
  const mutationToleranceBp = React.useMemo(() => {
    const span = Math.abs(window.end - window.start);
    return span > 0 ? span / NOMINAL_TRACK_PX : 0;
  }, [window.end, window.start]);

  // The pointer readout is a *feature* readout, not just a coordinate: the
  // reader is pointing at the picture to ask "what is that?". The answer is
  // computed from the same spans the renderer draws, so the label and the
  // boxes under the cursor cannot disagree after a pan or zoom.
  const hoverPoint = React.useMemo<GeneContextPoint | null>(() => {
    if (hoverBp === null) return null;
    return describeGeneContextPoint(hoverBp, {
      gene: { gene_id: geneId, start_pos: geneStart, end_pos: geneEnd, strand: gene.strand },
      exons: exonParts,
      neighbours: contextGenes.map((neighbour) => ({
        gene_id: neighbour.gene_id,
        start: neighbour.start,
        end: neighbour.end,
      })),
      mutations: mutationSites.map((site) => ({
        position: site.position,
        label: [site.mutant_line_name || site.source_site_key, site.confidence === "H" ? t("genes.confidence.high") : t("genes.confidence.low"), site.feature?.trim()]
          .filter(Boolean)
          .join(" · "),
      })),
      mutationToleranceBp,
    });
  }, [hoverBp, geneId, geneStart, geneEnd, gene.strand, exonParts, contextGenes, mutationSites, mutationToleranceBp]);

  const hoverAnnotation = React.useMemo(() => {
    if (!hoverPoint) return null;
    switch (hoverPoint.kind) {
      case "exon":
        return t("genomeView.hover.exon", { index: hoverPoint.index, total: hoverPoint.total });
      case "intron":
        return t("genomeView.hover.intron", { index: hoverPoint.index, total: hoverPoint.total });
      case "gene-body":
        return t("genomeView.hover.geneBody");
      case "mutation":
        return t("genomeView.hover.mutation", { label: hoverPoint.label });
      case "neighbour":
        return t("genomeView.hover.neighbour", { geneId: hoverPoint.geneId });
      case "flank":
        return t(
          hoverPoint.side === "upstream"
            ? "genomeView.hover.upstream"
            : "genomeView.hover.downstream",
          { geneId: hoverPoint.geneId },
        );
    }
  }, [hoverPoint, t]);

  const renderControls = React.useCallback(
    (api: GenomeViewControlsApi) => (
      <Flex
        align="center"
        justify="space-between"
        wrap
        gap={token.marginXS}
        style={{ marginTop: token.marginXS }}
      >
        <Space size={token.marginXS}>
          <Tooltip title={t("genomeView.controls.panLeft")}>
            <Button
              size="small"
              icon={<LeftOutlined />}
              aria-label={t("genomeView.controls.panLeft")}
              onClick={() => api.pan(-api.panStepBp)}
            />
          </Tooltip>
          <Tooltip title={t("genomeView.controls.panRight")}>
            <Button
              size="small"
              icon={<RightOutlined />}
              aria-label={t("genomeView.controls.panRight")}
              onClick={() => api.pan(api.panStepBp)}
            />
          </Tooltip>
          <Tooltip title={t("genomeView.controls.zoomIn")}>
            <Button
              size="small"
              icon={<ZoomInOutlined />}
              aria-label={t("genomeView.controls.zoomIn")}
              onClick={() => api.zoom(0.5)}
            />
          </Tooltip>
          <Tooltip title={t("genomeView.controls.zoomOut")}>
            <Button
              size="small"
              icon={<ZoomOutOutlined />}
              aria-label={t("genomeView.controls.zoomOut")}
              onClick={() => api.zoom(2)}
            />
          </Tooltip>
          <Tooltip title={t("genomeView.controls.reset")}>
            <Button
              size="small"
              icon={<CompressOutlined />}
              aria-label={t("genomeView.controls.reset")}
              onClick={api.reset}
            />
          </Tooltip>
        </Space>

        <Space size={token.marginXS} wrap>
          {hoverBp !== null ? (
            // One line, in the control bar: a floating popover over the track
            // would cover the very feature it names.
            <Tag
              color="processing"
              style={{ marginInlineEnd: 0 }}
              data-testid="genome-view-hover"
            >
              {t("genomeView.pointer")} {hoverBp.toLocaleString()}
              {hoverAnnotation ? ` · ${hoverAnnotation}` : ""}
            </Tag>
          ) : null}
          <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
            {api.viewport.refName}:{api.viewport.start.toLocaleString()}–
            {api.viewport.end.toLocaleString()} · {formatSpan(api.bpPerPx)}
          </Typography.Text>
        </Space>
      </Flex>
    ),
    [hoverBp, hoverAnnotation, t, token],
  );

  const windowText = `${chromosome}:${formatNumber(window.start)}–${formatNumber(window.end)}`;
  // Every gene in the window, the page's own gene first.
  const rows = [
    { geneId, start: geneStart, end: geneEnd, strand: gene.strand ?? "—", selected: true },
    ...contextGenes.map((neighbour) => ({
      geneId: neighbour.gene_id,
      start: neighbour.start,
      end: neighbour.end,
      strand: neighbour.strand,
      selected: false,
    })),
  ];

  return (
    <Card
      className={className}
      data-testid="gene-genome-view"
      title={
        <Space size={token.marginXS} wrap>
          <span>{t("genomeView.eyebrow")}</span>
          {assemblyLabel ? <Tag color="blue">{assemblyLabel}</Tag> : null}
        </Space>
      }
      extra={
        <Segmented<TrackChoice>
          size="small"
          value={choice}
          onChange={(value) => setChoice(value)}
          options={[
            { label: t("genomeView.tracks.all"), value: "both" },
            { label: t("genomeView.tracks.genes"), value: "gene" },
            {
              label: t("genomeView.tracks.sites", { total: mutationSites.length }),
              value: "sites",
            },
          ]}
        />
      }
    >
      <GenomeView
        // The renderer's window is initial state: re-keying makes a late clamp
        // (the chromosome length arriving) take effect instead of being ignored.
        key={`${chromosome}:${window.start}-${window.end}`}
        region={region}
        tracks={tracks}
        theme={svgTheme}
        prerenderedSrc={prerenderedSrc}
        ariaLabel={t("genomeView.geneAriaLabel", {
          geneId,
          chromosome,
          start: formatNumber(window.start),
          end: formatNumber(window.end),
        })}
        onViewportChange={onViewportChange}
        onHover={setHoverBp}
        intronChevrons
        renderControls={renderControls}
      />

      <Typography.Text
        type="secondary"
        className="mt-2 block font-mono text-xs"
        data-testid="gene-genome-view-window"
      >
        {t("genomeView.contextWindow", {
          window: windowText,
          flank: formatNumber(GENE_CONTEXT_FLANK_BP),
          total: contextGenes.length,
        })}
      </Typography.Text>

      {regionQuery.isError ? (
        <Typography.Text type="warning" className="mt-1 block text-xs" data-testid="gene-genome-view-context-unavailable">
          {t("genomeView.contextUnavailable")}
        </Typography.Text>
      ) : null}

      {/* SVG has no text fallback of its own: the same coordinates, for every
          gene in the window, are repeated here as a precise-value table.

          The `sr-only` clip lives on a wrapping element, not on the table: a
          table lays itself out from its content's min-content width, so a
          1px-wide table still reported a 448px scroll width at a 390px
          viewport and gave the whole page a horizontal scrollbar. A clipped
          block wrapper removes the table from the layout instead. */}
      <div className="sr-only">
        <table data-testid="gene-context-table">
        <caption>
          {t("genomeView.contextTableCaption", {
            window: windowText,
            geneId,
          })}
        </caption>
        <thead>
          <tr>
            <th scope="col">{t("genes.geneId")}</th>
            <th scope="col">{t("genomeView.contextTableCoordinates")}</th>
            <th scope="col">{t("genes.strand")}</th>
            <th scope="col">{t("genomeView.contextTableRole")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.geneId} data-testid={`gene-context-row-${row.geneId}`}>
              <td>{row.geneId}</td>
              <td>
                {chromosome}:{formatNumber(row.start)}–{formatNumber(row.end)}
              </td>
              <td>{row.strand}</td>
              <td>
                {row.selected
                  ? t("genomeView.contextTableSelected")
                  : t("genomeView.contextTableContext")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </Card>
  );
}