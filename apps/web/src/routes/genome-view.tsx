/**
 * Locus genome view — the portal's own browser, centred on a place rather than
 * a gene.
 *
 * Reached from the mutation-site table (`/genome-view?assembly=…&chromosome=…&
 * position=…&flank=10000`), where every insertion site is a link. The window is
 * the site plus 10 kb on each side, and it shows every gene that overlaps that
 * window with its CDS and UTR segments — the question "what did this insertion
 * land next to" that the JBrowse 2 service answers only after a full browser
 * boot.
 *
 * The same `@soymutdb/genome-view` renderer as the gene detail page draws it,
 * so the two pictures cannot drift: the package owns the SVG, this page only
 * maps an API response into tracks (see `lib/locus-structure.ts`).
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import {
  ArrowLeftOutlined,
  CompressOutlined,
  LeftOutlined,
  RightOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Empty,
  Flex,
  Segmented,
  Skeleton,
  Tag,
  Tooltip,
  Typography,
  theme as antdTheme,
} from "@/lib/antd";
import {
  GenomeView,
  type GenomeViewControlsApi,
  type GenomeViewSvgTheme,
} from "@soymutdb/genome-view";
import { getRegionStructure } from "@soymutdb/api-client";
import { FadeUp } from "../components/route-motion";
import { buildLocusTracks, locusWindow } from "../lib/locus-structure";
import { formatNumber } from "../lib/format";

/** Default half-window; the link carries it so a caller can ask for another. */
const DEFAULT_FLANK_BP = 10_000;
/** Guards against a hand-edited URL asking for a whole chromosome. */
const MAX_FLANK_BP = 1_000_000;
/** One zoom-button click; matches the renderer's own wheel step direction. */
const ZOOM_STEP = 1.5;

interface LocusSearch {
  assembly?: number;
  chromosome?: string;
  position?: number;
  flank?: number;
}

export const Route = createFileRoute("/genome-view")({
  validateSearch: (search: Record<string, unknown>): LocusSearch => {
    const asNumber = (value: unknown): number | undefined => {
      const parsed = typeof value === "number" ? value : Number(value);
      return Number.isFinite(parsed) ? parsed : undefined;
    };
    const chromosome = typeof search.chromosome === "string" ? search.chromosome.trim() : "";
    return {
      assembly: asNumber(search.assembly),
      chromosome: chromosome || undefined,
      position: asNumber(search.position),
      flank: asNumber(search.flank),
    };
  },
  component: LocusGenomeViewPage,
});

type TrackChoice = "all" | "genes" | "markers";

function LocusGenomeViewPage() {
  const { t } = useTranslation();
  const search = Route.useSearch();
  const { token } = antdTheme.useToken();
  const [choice, setChoice] = React.useState<TrackChoice>("all");
  const [hoverBp, setHoverBp] = React.useState<number | null>(null);

  const flank = Math.min(Math.max(search.flank ?? DEFAULT_FLANK_BP, 1), MAX_FLANK_BP);
  const requested = React.useMemo(
    () =>
      search.chromosome && search.position != null
        ? locusWindow(search.position, flank, undefined)
        : null,
    [search.chromosome, search.position, flank],
  );

  const structureQuery = useQuery({
    queryKey: [
      "locus-region-structure",
      search.assembly ?? null,
      search.chromosome ?? null,
      requested?.start ?? null,
      requested?.end ?? null,
    ],
    queryFn: () =>
      getRegionStructure({
        assemblyId: search.assembly!,
        chromosome: search.chromosome!,
        start: requested!.start,
        end: requested!.end,
      }),
    enabled: Boolean(search.assembly && requested),
    retry: false,
  });

  // The API clamps to the chromosome it actually knows; trust its numbers over
  // the ones derived from the link.
  const structure = structureQuery.data ?? null;
  const region = React.useMemo(
    () =>
      structure
        ? {
            assemblyKey: structure.assembly_name,
            refName: structure.chromosome,
            start: structure.start,
            end: structure.end,
          }
        : null,
    [structure],
  );

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

  const markers = React.useMemo(() => {
    if (search.position == null) return [];
    return [
      {
        position: search.position,
        label: `${search.chromosome ?? ""}:${formatNumber(search.position)}`,
      },
    ];
  }, [search.position, search.chromosome]);

  const allTracks = React.useMemo(
    () =>
      buildLocusTracks({
        chromosome: structure?.chromosome ?? search.chromosome ?? "",
        genes: structure?.genes ?? [],
        markers,
        spanBp: structure ? structure.end - structure.start : flank * 2,
      }),
    [structure, markers, search.chromosome, flank],
  );

  const tracks = React.useMemo(() => {
    if (choice === "all") return allTracks;
    if (choice === "genes") return allTracks.filter((track) => track.id !== "markers");
    return allTracks.filter(
      (track) => track.id === "ruler" || track.id === "markers" || track.kind === "ruler",
    );
  }, [allTracks, choice]);

  const renderControls = React.useCallback(
    (api: GenomeViewControlsApi) => (
      <Flex wrap align="center" gap={8}>
        <Tooltip title={t("genomeView.controls.panLeft", { defaultValue: "左移" })}>
          <Button
            size="small"
            icon={<LeftOutlined />}
            aria-label={t("genomeView.controls.panLeft", { defaultValue: "左移" })}
            onClick={() => api.pan(-api.panStepBp)}
          />
        </Tooltip>
        <Tooltip title={t("genomeView.controls.panRight", { defaultValue: "右移" })}>
          <Button
            size="small"
            icon={<RightOutlined />}
            aria-label={t("genomeView.controls.panRight", { defaultValue: "右移" })}
            onClick={() => api.pan(api.panStepBp)}
          />
        </Tooltip>
        <Tooltip title={t("genomeView.controls.zoomIn", { defaultValue: "放大" })}>
          <Button
            size="small"
            icon={<ZoomInOutlined />}
            aria-label={t("genomeView.controls.zoomIn", { defaultValue: "放大" })}
            onClick={() => api.zoom(ZOOM_STEP)}
          />
        </Tooltip>
        <Tooltip title={t("genomeView.controls.zoomOut", { defaultValue: "缩小" })}>
          <Button
            size="small"
            icon={<ZoomOutOutlined />}
            aria-label={t("genomeView.controls.zoomOut", { defaultValue: "缩小" })}
            onClick={() => api.zoom(1 / ZOOM_STEP)}
          />
        </Tooltip>
        <Tooltip title={t("genomeView.controls.reset", { defaultValue: "复位" })}>
          <Button
            size="small"
            icon={<CompressOutlined />}
            aria-label={t("genomeView.controls.reset", { defaultValue: "复位" })}
            onClick={api.reset}
          />
        </Tooltip>
        <Segmented<TrackChoice>
          size="small"
          value={choice}
          onChange={setChoice}
          options={[
            { label: t("genomeView.tracks.all", { defaultValue: "全部" }), value: "all" },
            { label: t("genomeView.tracks.genes", { defaultValue: "基因" }), value: "genes" },
            { label: t("genomeView.tracks.markers", { defaultValue: "标记" }), value: "markers" },
          ]}
        />
        <Typography.Text type="secondary" className="font-mono text-xs">
          {hoverBp != null ? `${formatNumber(hoverBp)} bp` : "—"}
        </Typography.Text>
      </Flex>
    ),
    [choice, hoverBp, t],
  );

  const missingParams = !search.assembly || !search.chromosome || search.position == null;

  return (
    <FadeUp>
      <div className="container-prose section-rhythm">
        <Link
          to="/search/genes"
          className="link-underline inline-flex items-center gap-1 text-sm text-muted-foreground"
        >
          <ArrowLeftOutlined aria-hidden />
          {t("genomeView.back", { defaultValue: "返回基因搜索" })}
        </Link>

        <p className="eyebrow mt-6">{t("genomeView.eyebrow", { defaultValue: "基因组视图" })}</p>
        <h1 className="mt-2 font-display text-3xl font-semibold tracking-tight">
          {search.chromosome && search.position != null
            ? `${search.chromosome}:${formatNumber(search.position)}`
            : t("genomeView.title", { defaultValue: "位点基因组视图" })}
        </h1>
        {structure ? (
          <Typography.Paragraph type="secondary" className="mt-2">
            {t("genomeView.window", {
              start: formatNumber(structure.start),
              end: formatNumber(structure.end),
              flank: formatNumber(flank),
              assembly: structure.assembly_name,
            })}
          </Typography.Paragraph>
        ) : null}

        {missingParams ? (
          <Alert
            className="mt-6"
            type="warning"
            showIcon
            title={t("genomeView.missingParams", {
              defaultValue: "链接缺少组装版本、染色体或位点参数。",
            })}
          />
        ) : null}

        {structureQuery.isError ? (
          <Alert
            className="mt-6"
            type="error"
            showIcon
            title={t("genomeView.loadError", { defaultValue: "无法加载该位点的注释。" })}
          />
        ) : null}

        <Card
          className="mt-6"
          title={
            <span className="text-base">
              {t("genomeView.cardTitle", { defaultValue: "位点注释" })}
            </span>
          }
          extra={
            <Flex align="center" gap={8}>
              <Tag className="m-0 font-mono text-[10px]">
                {structure?.assembly_version ?? "—"}
              </Tag>
              <Typography.Text type="secondary" className="text-xs">
                {t("genomeView.geneCount", {
                  variants: structure?.genes.length ?? 0,
                })}
              </Typography.Text>
            </Flex>
          }
        >
          {missingParams ? null : structureQuery.isLoading ? (
            <Skeleton active paragraph={{ rows: 5 }} title={false} />
          ) : !structure || structure.genes.length === 0 ? (
            <Empty
              description={t("genomeView.noGenes", {
                defaultValue: "该窗口内没有已注释的基因。",
              })}
            />
          ) : (
            <GenomeView
              region={region!}
              tracks={tracks}
              theme={svgTheme}
              ariaLabel={t("genomeView.ariaLabel", { defaultValue: "位点基因组视图" })}
              renderControls={renderControls}
              onHover={setHoverBp}
              onViewportChange={() => undefined}
            />
          )}
        </Card>

        {structure && structure.genes.length > 0 ? (
          <Card
            className="mt-6"
            title={
              <span className="text-base">
                {t("genomeView.geneList", { defaultValue: "窗口内基因" })}
              </span>
            }
          >
            <Flex vertical gap={8}>
              {structure.genes.map((gene) => {
                const withStructure = gene.transcripts.some(
                  (transcript) => transcript.parts.length > 0,
                );
                return (
                  <Flex key={gene.gene_id} wrap align="center" gap={12}>
                    <Link
                      to="/genes/$geneId"
                      params={{ geneId: gene.gene_id }}
                      search={{ assembly: String(structure.assembly_id) }}
                      className="link-underline font-mono text-xs font-medium text-primary"
                    >
                      {gene.gene_id}
                    </Link>
                    <Tag className="m-0 font-mono text-[10px]">{gene.strand}</Tag>
                    <Typography.Text type="secondary" className="font-mono text-xs">
                      {formatNumber(gene.start)}–{formatNumber(gene.end)}
                    </Typography.Text>
                    {withStructure ? (
                      <Tag color="green" className="m-0 text-[10px]">
                        {t("genomeView.hasStructure", {
                          defaultValue: "含 CDS/UTR",
                        })}
                      </Tag>
                    ) : (
                      <Tag className="m-0 text-[10px]">
                        {t("genomeView.bodyOnly", { defaultValue: "仅基因主体" })}
                      </Tag>
                    )}
                  </Flex>
                );
              })}
            </Flex>
          </Card>
        ) : null}
      </div>
    </FadeUp>
  );
}
