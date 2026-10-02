/**
 * Simplified genome view for the gene detail page.
 *
 * The lightweight, always-available counterpart to the full JBrowse 2 browser
 * (still reachable at /search/gbrowse and from the "open in browser" action).
 * It draws the gene body, its transcripts and the operator's mutation sites as
 * one SVG, either pre-rendered by the API or produced in the browser.
 *
 * Page placement and animation are the caller's concern; this component owns the
 * mapping from API records to tracks, and — because `@soymutdb/genome-view`
 * carries no UI kit — it also owns the control bar, which is built from antd
 * components here rather than from bare HTML inside the package.
 */
import * as React from "react";
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
  type SvgTrack,
} from "@soymutdb/genome-view";
import type { TestDataPreviewMutationSite } from "@soymutdb/api-client";

/** The gene fields this view needs; kept structural so it accepts the page's type. */
export interface GenomeViewGene {
  gene_id: string;
  chromosome: string;
  start_pos: number;
  end_pos: number;
  strand?: string;
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

/** Pad the window so the gene sits in context rather than edge to edge. */
const FLANK_FRACTION = 0.25;
/** Below this span the ruler labels collapse into each other. */
const MIN_SPAN_BP = 200;

type TrackChoice = "gene" | "sites" | "both";

/** Base pairs per pixel at or above which the scale reads as bp/px. */
const BP_PER_PX_MIN = 1;

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
  const { token } = antdTheme.useToken();
  const [choice, setChoice] = React.useState<TrackChoice>("both");
  // Local state only: the readout follows the pointer without touching routing,
  // so this stays an in-page update rather than a navigation.
  const [hoverBp, setHoverBp] = React.useState<number | null>(null);

  const span = Math.max(MIN_SPAN_BP, gene.end_pos - gene.start_pos);
  const flank = Math.round(span * FLANK_FRACTION);
  const region = React.useMemo(
    () => ({
      assemblyKey: assemblyLabel ?? gene.chromosome,
      refName: gene.chromosome,
      start: Math.max(0, gene.start_pos - flank),
      end: gene.end_pos + flank,
    }),
    [assemblyLabel, gene.chromosome, gene.start_pos, gene.end_pos, flank],
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

  const transcripts = gene.transcripts ?? [];
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

  const tracks = React.useMemo<SvgTrack[]>(() => {
    // A ruler always leads: without coordinates on screen the picture is
    // decorative rather than readable.
    const list: SvgTrack[] = [{ id: "ruler", label: gene.chromosome, kind: "ruler" }];
    if (choice !== "sites") {
      list.push({
        id: "gene",
        label: `基因${gene.strand ? ` (${gene.strand})` : ""}`,
        kind: "feature",
        features: [
          {
            id: gene.gene_id,
            start: gene.start_pos,
            end: gene.end_pos,
            kind: "gene",
            label: gene.gene_id,
            strand: gene.strand === "-" ? "-" : "+",
            // With exons on record the gene draws as a real gene model; without
            // them it falls back to a single bar rather than an empty lane.
            parts: exonParts,
          },
          ...(showTranscriptLane
            ? []
            : transcripts.map((transcript) => ({
                id: transcript.id,
                start: transcript.start,
                end: transcript.end,
                kind: "gene" as const,
                label: transcript.name ?? transcript.id,
              }))),
        ],
      });
    }
    if (choice !== "sites" && showTranscriptLane) {
      list.push({
        id: "transcripts",
        label: `转录本 (${transcripts.length})`,
        kind: "feature",
        features: transcripts.map((transcript) => ({
          id: transcript.id,
          start: transcript.start,
          end: transcript.end,
          kind: "gene" as const,
          label: `${transcript.name ?? transcript.id}${transcript.is_canonical ? " · canonical" : ""}`,
        })),
      });
    }
    if (choice !== "gene") {
      list.push({
        id: "sites",
        label: `位点 (${mutationSites.length})`,
        kind: "feature",
        features: mutationSites.map((site) => ({
          id: site.source_site_key,
          start: site.position,
          end: site.position + 1,
          kind: "mutation" as const,
          label: `${site.mutant_line_name} · ${site.confidence === "H" ? "高" : "低"}`,
        })),
      });
    }
    return list;
  }, [choice, gene, mutationSites, showTranscriptLane, transcripts, exonParts]);

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
          <Tooltip title="左移">
            <Button
              size="small"
              icon={<LeftOutlined />}
              aria-label="左移"
              onClick={() => api.pan(-api.panStepBp)}
            />
          </Tooltip>
          <Tooltip title="右移">
            <Button
              size="small"
              icon={<RightOutlined />}
              aria-label="右移"
              onClick={() => api.pan(api.panStepBp)}
            />
          </Tooltip>
          <Tooltip title="放大">
            <Button
              size="small"
              icon={<ZoomInOutlined />}
              aria-label="放大"
              onClick={() => api.zoom(0.5)}
            />
          </Tooltip>
          <Tooltip title="缩小">
            <Button
              size="small"
              icon={<ZoomOutOutlined />}
              aria-label="缩小"
              onClick={() => api.zoom(2)}
            />
          </Tooltip>
          <Tooltip title="复位到基因区间">
            <Button
              size="small"
              icon={<CompressOutlined />}
              aria-label="复位"
              onClick={api.reset}
            />
          </Tooltip>
        </Space>

        <Space size={token.marginXS} wrap>
          {hoverBp !== null ? (
            <Tag color="processing" style={{ marginInlineEnd: 0 }}>
              指针 {hoverBp.toLocaleString()}
            </Tag>
          ) : null}
          <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
            {api.viewport.refName}:{api.viewport.start.toLocaleString()}–
            {api.viewport.end.toLocaleString()} · {formatSpan(api.bpPerPx)}
          </Typography.Text>
        </Space>
      </Flex>
    ),
    [hoverBp, token],
  );

  return (
    <Card
      className={className}
      data-testid="gene-genome-view"
      title={
        <Space size={token.marginXS} wrap>
          <span>基因组视图</span>
          {assemblyLabel ? <Tag color="blue">{assemblyLabel}</Tag> : null}
          <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
            {gene.chromosome}:{gene.start_pos.toLocaleString()}–
            {gene.end_pos.toLocaleString()}
          </Typography.Text>
        </Space>
      }
      extra={
        <Segmented<TrackChoice>
          size="small"
          value={choice}
          onChange={(value) => setChoice(value)}
          options={[
            { label: "全部", value: "both" },
            { label: "基因", value: "gene" },
            { label: `位点 (${mutationSites.length})`, value: "sites" },
          ]}
        />
      }
    >
      <GenomeView
        region={region}
        tracks={tracks}
        theme={svgTheme}
        prerenderedSrc={prerenderedSrc}
        ariaLabel={`${gene.gene_id} 基因组视图`}
        onViewportChange={onViewportChange}
        onHover={setHoverBp}
        renderControls={renderControls}
      />
    </Card>
  );
}
