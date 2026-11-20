import { assembliesQueryOptions } from "../../lib/query-options";
/**
 * Gene detail route — full gene information, one tab per data block.
 *
 * The optional blocks (annotation / homolog / expression / variants / phenotype
 * / literature) come from the detail response itself: each carries its own
 * `SectionStatus`, so the page can say "this gene has none" and "this release
 * never imported it" differently. Because the block is *in* the response, the
 * page no longer issues its own `/genes/{id}/expression` or
 * `/genes/{id}/homologs` request — one dataset has one source, or the two drift.
 *
 * AntD 5 migration (A1): Card/Descriptions/Tabs/Table/Skeleton/Tag/Empty
 * replace the frozen shared UI components. TanStack Query data flow
 * unchanged.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { EvidenceLine } from "@/components/evidence-tag";
import { GeneSequencePanel } from "@/components/gene-sequence-panel";
import * as React from "react";
import {
  AimOutlined as Microscope,
  ArrowLeftOutlined as ArrowLeft,
  GlobalOutlined,
} from "@ant-design/icons";
import {
  Button,
  Card,
  Descriptions,
  Divider,
  Empty,
  Flex,
  Skeleton,
  Table,
  Tabs,
  Tag,
  Typography,
  type TableColumnsType,
} from "@/lib/antd";
import {
  getGene,
  listTestDataPreviewMutationSitesForGene,
  type AssemblyInfo,
  type GeneExpressionRecord,
  type TestDataPreviewMutationSite,
} from "@soymutdb/api-client";
import { GeneOrthologSection } from "../../components/comparative/ortholog-section";
import {
  GeneAnnotationSectionCard,
  GeneExpressionSectionCard,
  GeneHomologSectionCard,
  GeneLiteratureSectionCard,
  GenePhenotypeSectionCard,
  GeneVariantSectionCard,
} from "../../components/gene-sections";
import { GeneGenomeView } from "../../components/gene-genome-view";
import { GeneSeedRequestEntry } from "../../components/gene-seed-request-entry";
import { FadeUp, ScaleIn } from "../../components/route-motion";
import { isGeneDetailRecord } from "../../lib/api-contract-guards";
import { assemblyOptionLabel, resolveAssemblyParam, toAssemblyIdParam } from "../../lib/assembly-selection";
import { buildJbrowseLocusUrl } from "../../lib/deployment";
import { formatPosition } from "../../lib/format";
import { queryKeys } from "../../lib/query-keys";
import { useReleaseId } from "../../lib/release-scope";
import { SITE_VARIANT } from "../../lib/site-variant";

// The chart module exports the component by name only: its `export default` of
// the same symbol was removed so the file carries no duplicate export. `lazy`
// needs a module whose `default` is the component, so adapt here instead of
// keeping a second export.
const ExpressionBarChart = React.lazy(() =>
  import("../../components/charts/expression-bar-chart").then((module) => ({
    default: module.ExpressionBarChart,
  })),
);

/**
 * Half-window of the in-app locus view link, in kilobases.
 *
 * It matches that route's own default, so the link states the window the reader
 * will actually get instead of implying the gene page's ±2 kb context.
 */
const LOCUS_VIEW_FLANK_KB = 10;

export const Route = createFileRoute("/genes/$geneId")({
  component: GeneDetailComponent,
  // The deep-link assembly is a request hint, not an id: a link may carry the
  // legacy genome-name spelling, so it is resolved against this release's
  // catalogue before it reaches the API's numeric `assembly_id`.
  validateSearch: (search: Record<string, unknown>) => ({
    assembly: search.assembly ? String(search.assembly) : undefined,
  }),
});

function GeneDetailComponent() {
  const { t } = useTranslation();
  const { geneId } = Route.useParams();
  const { assembly } = Route.useSearch();
  // Controlled so the action area can jump into a data block without the reader
  // hunting a nine-item tab strip.
  const [activeTab, setActiveTab] = React.useState<string>("overview");
  const releaseId = useReleaseId();
  const assembliesQuery = useQuery(assembliesQueryOptions({
    releaseId,
    siteVariant: SITE_VARIANT,
  }));
  const assemblies = React.useMemo(() => assembliesQuery.data ?? [], [assembliesQuery.data]);

  // The catalogue is the authority on which assembly ids exist in this
  // release. An id-shaped string that is not in it is "unknown", never sent:
  // the endpoint would read another namespace's plausible-looking record.
  const assemblyParam = assembly?.trim() ? assembly.trim() : undefined;
  const assemblyResolution = React.useMemo(
    () => resolveAssemblyParam(assemblies, assemblyParam),
    [assemblies, assemblyParam],
  );
  const requestedAssemblyId = assemblyResolution.status === "resolved"
    ? toAssemblyIdParam(assemblyResolution.assembly.id)
    : undefined;
  // A requested assembly that cannot be resolved is a blocked context: the
  // page says so instead of sending an unscoped request whose rows could come
  // from the other genome version.
  const assemblyPending =
    Boolean(assemblyParam) && !assembliesQuery.isSuccess && !assembliesQuery.isError;
  const assemblyBlocked =
    Boolean(assemblyParam) &&
    (assembliesQuery.isError ||
      (assembliesQuery.isSuccess && requestedAssemblyId === undefined));
  const requestedAssemblyIdParam =
    requestedAssemblyId === undefined ? undefined : String(requestedAssemblyId);

  const geneQuery = useQuery({
    queryKey: queryKeys.genes.detail(geneId, requestedAssemblyIdParam, releaseId, SITE_VARIANT),
    queryFn: () => getGene(geneId, { assembly_id: requestedAssemblyIdParam }),
    enabled: !assemblyPending && !assemblyBlocked,
  });

  // A 200 response of the wrong shape (e.g. the search-list envelope) must render
  // the empty state, not crash the genome view on undefined coordinates.
  const gene = isGeneDetailRecord(geneQuery.data) ? geneQuery.data : undefined;

  // The record itself is authoritative for its assembly; the catalogue entry
  // contributes the version the detail payload does not carry. Without a
  // record, the resolved request context is all that is known.
  const assemblyEntry: AssemblyInfo | undefined = gene?.assembly_id != null
    ? assemblies.find((candidate) => String(candidate.id) === String(gene.assembly_id))
    : assemblyResolution.status === "resolved"
      ? assemblyResolution.assembly
      : undefined;

  // Local-only unpublished test-data preview. The operator asked for these
  // columns (line / mutation-site key / chromosome / position / confidence /
  // gene / feature / availability) to be visible on this page. The endpoint is
  // loopback-only and gated by `local_test_preview_enabled`, so a 404 is the
  // normal answer outside a local preview; `retry: false` plus an error check
  // keeps the section hidden instead of surfacing a stray error card.
  // Keyed on the gene, not on its coordinate interval: a share of the source
  // rows sit up- or downstream of the gene's own start/end (the source `feature`
  // column carries that offset), so an interval query silently drops them. This
  // is the same lookup the search result table uses, so both pages agree.
  const mutationSitesQuery = useQuery({
    queryKey: ["test-data-preview-mutation-sites", gene?.gene_id ?? null],
    queryFn: () => listTestDataPreviewMutationSitesForGene(gene!.gene_id, 1000),
    enabled: Boolean(gene?.gene_id),
    retry: false,
  });
  const mutationSites = React.useMemo(() => mutationSitesQuery.data ?? [], [mutationSitesQuery.data]);
  /** Gates the seed-request entry: no obtainable material, no entry. */
  const availableSiteCount = React.useMemo(
    () => mutationSites.filter((site) => site.available).length,
    [mutationSites],
  );

  // Every optional block, straight off the detail response: no second request
  // for the same rows, and an older API build omits a block rather than sending
  // an empty list, which each component reports as "nothing reported".
  const annotationSection = gene?.annotation_section ?? null;
  const homologSection = gene?.homolog_section ?? null;
  const expressionSection = gene?.expression_section ?? null;
  const variantsSection = gene?.variants_section ?? null;
  const phenotypeSection = gene?.phenotype_section ?? null;
  const literatureSection = gene?.literature_section ?? null;
  const expressions = React.useMemo<GeneExpressionRecord[]>(
    () => expressionSection?.records ?? [],
    [expressionSection],
  );
  const jbrowseAssembly = gene?.assembly_name ?? assemblyEntry?.name;
  const jbrowseHref = gene && jbrowseAssembly
    ? buildJbrowseLocusUrl(import.meta.env.BASE_URL, {
        assembly: jbrowseAssembly,
        locus: `${gene.chromosome}:${Math.max(1, gene.start_pos)}-${gene.end_pos}`,
        release: releaseId ?? undefined,
      }).href
    : undefined;

  // Build bar chart data: mean FPKM per tissue+treatment
  const barChartData = React.useMemo(() => {
    const grouped = new Map<string, { sum: number; count: number; treatment: string }>();
    for (const expr of expressions) {
      if (expr.fpkm == null) continue;
      const key = `${expr.tissue ?? ""}|${expr.treatment ?? ""}`;
      const existing = grouped.get(key);
      if (existing) {
        existing.sum += expr.fpkm;
        existing.count += 1;
      } else {
        grouped.set(key, { sum: expr.fpkm, count: 1, treatment: expr.treatment ?? "" });
      }
    }
    return Array.from(grouped.entries()).map(([key, val]) => {
      const [tissue] = key.split("|");
      return {
        tissue: tissue || val.treatment || "—",
        mean_fpkm: val.sum / val.count,
        treatment: val.treatment,
      };
    });
  }, [expressions]);

  // Columns exactly as the operator specified, in order: mutation system
  // (line parent + position), chromosome, position, confidence, gene, feature,
  // availability, then the three homolog accessions from the same source row.
  const mutationSiteColumns: TableColumnsType<TestDataPreviewMutationSite> = [
    {
      title: t("genes.mutationSites.siteKey", { defaultValue: "突变体系（株系母+位置）" }),
      dataIndex: "source_site_key",
      key: "source_site_key",
      render: (_, row) => <span className="font-mono text-xs">{row.source_site_key}</span>,
    },
    {
      title: t("genes.mutationSites.chromosome", { defaultValue: "染色体号" }),
      dataIndex: "chromosome",
      key: "chromosome",
      render: (_, row) => <span className="font-mono text-xs">{row.chromosome}</span>,
    },
    {
      title: t("genes.mutationSites.position", { defaultValue: "位点" }),
      dataIndex: "position",
      key: "position",
      align: "right",
      render: (_, row) => <span className="font-mono text-xs">{formatPosition(row.position)}</span>,
    },
    {
      title: t("genes.mutationSites.confidence", { defaultValue: "可信度" }),
      dataIndex: "confidence",
      key: "confidence",
      // The API types this as "H" | "L", while the table constraint also allows
      // "M"; compare through a string so either arrives without a type error.
      render: (_, row) => {
        const grade = String(row.confidence);
        return (
          <Tag color={grade === "H" ? "green" : grade === "M" ? "gold" : "default"}>
            {grade === "H" ? t("genes.confidence.high") : grade === "M" ? t("genes.confidence.medium") : t("genes.confidence.low")}
          </Tag>
        );
      },
    },
    {
      title: t("genes.mutationSites.geneId", { defaultValue: "基因号" }),
      dataIndex: "gene_id",
      key: "gene_id",
      render: (_, row) => <span className="font-mono text-xs">{row.gene_id}</span>,
    },
    {
      title: t("genes.mutationSites.feature", { defaultValue: "特征" }),
      dataIndex: "feature",
      key: "feature",
      render: (_, row) => <span className="font-mono text-xs">{row.feature}</span>,
    },
    {
      title: t("genes.mutationSites.available", { defaultValue: "可获得" }),
      dataIndex: "available",
      key: "available",
      render: (_, row) => (
        <Tag color={row.available ? "green" : "default"}>{row.available ? t("common.yes") : t("common.no")}</Tag>
      ),
    },
    // The W82_V2 / W82_V4 / DN53_V1 homolog accessions are deliberately NOT
    // columns here either: they are alternate identifiers for the same locus,
    // used by search, not fields to read off the page.
  ];

  /** Counts of the gene's variant set, as one definition list. */
  const variantItems = [
    {
      key: "variant_count",
      label: t("genes.variantCount"),
      children: <CountValue value={gene?.variant_count} />,
    },
    {
      key: "high_impact",
      label: t("genes.highImpactVariants"),
      children: <CountValue value={gene?.high_impact_variants} tone="high" />,
    },
    {
      key: "snp_count",
      label: t("genes.snpCount"),
      children: <CountValue value={gene?.snp_count} />,
    },
    {
      key: "indel_count",
      label: t("genes.indelCount"),
      children: <CountValue value={gene?.indel_count} />,
    },
    {
      key: "mutant_line_count",
      label: t("genes.mutantLineCount"),
      children: <CountValue value={gene?.mutant_line_count} />,
    },
  ];

  /**
   * The consequence classes, kept apart from the counts above on purpose: a
   * class the API did not count is `undefined`, and rendering it as a zero would
   * claim a measured zero.
   */
  const effectItems = [
    {
      key: "nonsense",
      label: t("genes.nonsenseCount"),
      children: <CountValue value={gene?.nonsense_count} tone="high" />,
    },
    {
      key: "missense",
      label: t("genes.missenseCount"),
      children: <CountValue value={gene?.missense_count} tone="moderate" />,
    },
    {
      key: "synonymous",
      label: t("genes.synonymousCount"),
      children: <CountValue value={gene?.synonymous_count} tone="low" />,
    },
    {
      key: "frameshift",
      label: t("genes.frameshiftCount"),
      children: <CountValue value={gene?.frameshift_count} tone="high" />,
    },
  ];

  // The in-app locus view is the secondary entry point. It is assembly-scoped
  // like every other link on this page: without the numeric assembly id the
  // same coordinates name a different place, so the link is simply not offered.
  const locusAssemblyId = Number(gene?.assembly_id);
  const locusViewSearch =
    gene && gene.assembly_id != null && Number.isFinite(locusAssemblyId)
      ? {
          assembly: locusAssemblyId,
          chromosome: gene.chromosome,
          position: Math.round((gene.start_pos + gene.end_pos) / 2),
          flank: LOCUS_VIEW_FLANK_KB * 1000,
        }
      : undefined;

  return (
    <div className="container-prose pb-16 pt-6" data-testid="gene-detail">
      <Link
        to="/genes"
        data-testid="gene-back-link"
        search={{
          assembly: assembly ?? "",
           q: "",
          chromosome: "",
          biotype: "",
          page: 1,
          sort_by: "gene_id",
          sort_dir: "asc",
        }}
        className="link-underline inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {t("genes.backToSearch")}
      </Link>

      {assemblyBlocked ? (
        <Card className="mt-8">
          <Empty description={t("search.assemblyUnavailable")} className="py-8" />
        </Card>
      ) : geneQuery.isLoading || assemblyPending ? (
        <GeneDetailSkeleton />
      ) : geneQuery.isError || !gene ? (
        <Card className="mt-8">
          <Empty description={t("common.noData")} className="py-8" />
        </Card>
      ) : (
        <>
          {/* Tier 1 — the identity anchor: every fact that says *which* record
              this page is about, in one definition list. The assembly is an
              item, not a floating tag: it is the coordinate namespace, so it
              belongs with the coordinates it qualifies. */}
          <FadeUp>
            <Card className="mt-6" data-testid="gene-identity">
              <h1
                data-testid="gene-id"
                className="break-all font-mono text-2xl font-semibold tracking-tight sm:text-3xl"
              >
                {gene.gene_id}
              </h1>
              {gene.symbol ? (
                <p className="mt-1 font-display text-lg text-muted-foreground">{gene.symbol}</p>
              ) : null}

              <Descriptions
                className="mt-4"
                size="small"
                column={{ xs: 1, sm: 2, lg: 5 }}
                items={[
                  {
                    key: "coordinates",
                    label: t("genes.coordinatesLabel"),
                    children: (
                      <span data-testid="gene-coords" className="font-mono break-all">
                        {gene.chromosome}:{formatPosition(gene.start_pos)}–{formatPosition(gene.end_pos)}
                      </span>
                    ),
                  },
                  {
                    key: "strand",
                    label: t("genes.strand"),
                    children: <span className="font-mono">{gene.strand || "—"}</span>,
                  },
                  {
                    key: "assembly",
                    label: t("genes.assemblyLabel"),
                    children: (
                      <span data-testid="gene-assembly" className="font-mono break-all">
                        {assemblyEntry ? assemblyOptionLabel(assemblyEntry) : (gene.assembly_name ?? "—")}
                      </span>
                    ),
                  },
                  {
                    key: "release",
                    label: t("genes.releaseLabel"),
                    children: <span className="font-mono">{releaseId ?? "—"}</span>,
                  },
                  {
                    key: "biotype",
                    label: t("genes.biotypeLabel"),
                    children: <span className="font-mono">{gene.biotype || "—"}</span>,
                  },
                ]}
              />

              {gene.description ? (
                <p className="mt-3 max-w-3xl text-sm text-muted-foreground">{gene.description}</p>
              ) : null}
              {/* The gene model's provenance, stated once at the top so a
                  predicted model is never read as a curated one. */}
              <div className="mt-2" data-testid="gene-model-evidence">
                <EvidenceLine evidence={gene.model_evidence ?? null} />
              </div>
            </Card>
          </FadeUp>

          {/* Tier 2 — one action area for everything that leaves this page: the
              genome browser and the in-app locus view. The data blocks are not
              listed a second time here -- the section tabs directly below are
              the page's single section navigation. */}
          <ScaleIn delay={80}>
            <Card
              className="mt-4"
              data-testid="gene-actions-card"
              title={<span className="text-base">{t("genes.actionsTitle")}</span>}
            >
              <Flex wrap align="center" gap={8} data-testid="gene-actions">
                <Button
                  type="primary"
                  data-testid="gene-jbrowse"
                  href={jbrowseHref}
                  disabled={!jbrowseHref}
                  icon={<Microscope className="size-4" aria-hidden />}
                >
                  {t("genes.viewInBrowser")}
                </Button>
                {locusViewSearch ? (
                  <Link
                    to="/genome-view"
                    search={locusViewSearch}
                    data-testid="gene-locus-view"
                    className="link-underline inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
                  >
                    <GlobalOutlined className="size-4" aria-hidden />
                    {t("genes.openLocusView", { flank: LOCUS_VIEW_FLANK_KB })}
                  </Link>
                ) : null}
              </Flex>
            </Card>
          </ScaleIn>

          {/* Tier 3 — the data blocks, one tab each, behind the page's single
              section navigation. The tab strip used to be duplicated: the
              action card listed the same nine destinations as chips, so every
              section was announced twice. Controlled state keeps a switch
              programmatic without a second list of links. */}
          {(() => {
            const tabItems = [
              {
                key: "overview",
                label: t("genes.tabs.overview"),
                children: (
                  <>
                    {/* The spatial context belongs to the record's overview:
                        ±2 kb around the gene, with every gene in that window,
                        which is the question the picture exists to answer. */}
                    <ScaleIn delay={120}>
                      <GeneGenomeView
                        gene={gene}
                        mutationSites={mutationSites}
                        assemblyLabel={jbrowseAssembly ?? assembly ?? undefined}
                      />
                    </ScaleIn>

                    {/* Variant totals and the effect breakdown are one dataset;
                        one card with two definition lists, not two cards. */}
                    <Card
                      className="mt-4"
                      data-testid="gene-variant-summary"
                      title={<span className="text-base">{t("genes.variantSummary")}</span>}
                    >
                      <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 5 }} items={variantItems} />
                      <Divider className="my-3" />
                      <Typography.Text type="secondary" className="text-xs">
                        {t("genes.effectBreakdown")}
                      </Typography.Text>
                      <Descriptions
                        className="mt-2"
                        size="small"
                        column={{ xs: 1, sm: 2, lg: 4 }}
                        items={effectItems}
                      />
                    </Card>

                    {/* Local-only unpublished test-data preview. Rendered only
                        when the loopback-gated preview endpoint answers, so a
                        build without the local preview behaves exactly as
                        before and never shows an empty or erroring card. */}
                    {mutationSites.length > 0 ? (
                      <Card
                        className="mt-4"
                        data-testid="gene-mutation-sites"
                        title={t("genes.mutationSitesTitle")}
                        extra={
                          <Tag color="orange">
                            {t("genes.unpublishedPreview")}
                          </Tag>
                        }
                      >
                        <Table<TestDataPreviewMutationSite>
                          rowKey="source_site_key"
                          size="small"
                          dataSource={mutationSites}
                          columns={mutationSiteColumns}
                          pagination={
                            mutationSites.length > 20
                              ? { pageSize: 20, showSizeChanger: false }
                              : false
                          }
                          scroll={{ x: 900 }}
                        />
                      </Card>
                    ) : null}

                    {/* Seed request: only meaningful when the gene has material
                        flagged obtainable, which the component checks itself.
                        In-page card, not a route; the form is a link away. */}
                    <ScaleIn delay={250}>
                      <GeneSeedRequestEntry
                        className="mt-4"
                        geneId={gene.gene_id ?? geneId}
                        availableSiteCount={availableSiteCount}
                      />
                    </ScaleIn>
                  </>
                ),
              },
              {
                key: "variants",
                label: t("genes.tabs.variants"),
                children: <GeneVariantSectionCard section={variantsSection} />,
              },
              {
                key: "annotation",
                label: t("genes.tabs.annotation"),
                children: <GeneAnnotationSectionCard section={annotationSection} />,
              },
              {
                key: "homologs",
                label: t("genes.tabs.homologs"),
                children: <GeneHomologSectionCard section={homologSection} />,
              },
              {
                // Comparative genomics lives on its own tab rather than inside
                // "Homologs": the homolog table is the older per-row view, while
                // these rows carry the source's own relationship classification
                // (one_to_one / one_to_many / many_to_many) and its evidence tag.
                key: "orthologs",
                label: t("comparative.orthologs.title"),
                children: (
                  <ScaleIn>
                    <GeneOrthologSection geneId={gene.gene_id ?? geneId} assemblyId={assembly} />
                  </ScaleIn>
                ),
              },
              {
                key: "expression",
                label: t("genes.tabs.expression"),
                children: (
                  <GeneExpressionSectionCard
                    section={expressionSection}
                    loading={geneQuery.isLoading}
                    chart={
                      expressions.length > 0 ? (
                        <React.Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} title={false} />}>
                          <ExpressionBarChart data={barChartData} />
                        </React.Suspense>
                      ) : null
                    }
                  />
                ),
              },
              {
                key: "phenotype",
                label: t("genes.tabs.phenotype"),
                children: <GenePhenotypeSectionCard section={phenotypeSection} />,
              },
              {
                key: "literature",
                label: t("genes.tabs.literature"),
                children: <GeneLiteratureSectionCard section={literatureSection} />,
              },
              {
                key: "sequences",
                label: t("genes.sequences.title"),
                children: (
                  <ScaleIn>
                    <GeneSequencePanel sequences={gene.sequences} />
                  </ScaleIn>
                ),
              },
            ];
            return (
              <div data-testid="gene-section-nav">
                <Tabs
                  activeKey={activeTab}
                  onChange={setActiveTab}
                  className="mt-4"
                  items={tabItems}
                />
              </div>
            );
          })()}
        </>
      )}
    </div>
  );
}

/**
 * The page's shape while the record loads: the facts anchor, the action area,
 * the section navigation and the open section — not a blank column.
 *
 * Placeholders match the blocks they stand in for (a title line, five fact
 * pairs, one button row, the tab strip, the genome strip and one content card),
 * so the page does not reflow into a different silhouette when the response
 * arrives. The static document the build prerenders carries the same facts for
 * a reader whose JS never runs; this is what the SPA shows in the meantime.
 */
function GeneDetailSkeleton() {
  const { t } = useTranslation();
  // Plain blocks, not `<Skeleton>`: antd's component always lays out its
  // default title + paragraph rows *inside* whatever height the caller sets, so
  // nine of them measured 1334 px of identity card alone. A block with a fixed
  // height and the same muted pulse keeps the silhouette exact.
  const bar = (className: string) => (
    <span className={`block animate-pulse rounded bg-muted ${className}`} aria-hidden />
  );
  return (
    <div
      className="mt-6 grid gap-4"
      data-testid="gene-skeleton"
      aria-busy="true"
      aria-live="polite"
    >
      <span className="sr-only">{t("genes.loading")}</span>

      <div className="rounded-lg border border-border bg-card p-4" data-testid="gene-skeleton-identity">
        {bar("h-3 w-24")}
        {bar("mt-3 h-8 w-2/3 max-w-72")}
        <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {[0, 1, 2, 3, 4].map((slot) => (
            <div key={slot}>
              {bar("h-3 w-16")}
              {bar("mt-2 h-4 w-full")}
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card p-4" data-testid="gene-skeleton-actions">
        {bar("h-4 w-32")}
        <div className="mt-3 flex flex-wrap gap-2">
          {bar("h-8 w-36")}
          {bar("h-8 w-32")}
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card p-4" data-testid="gene-skeleton-sections">
        {/* The tab strip: the page's only section navigation, so the skeleton
            shows it once, where the loaded page puts it. */}
        <div className="flex flex-wrap gap-2 pb-3" data-testid="gene-skeleton-section-nav">
          {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((slot) => (
            <span key={slot}>{bar("h-5 w-16")}</span>
          ))}
        </div>
        {bar("h-24 w-full")}
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          {[0, 1].map((slot) => (
            <div key={slot}>
              {bar("h-4 w-40")}
              {bar("mt-3 h-4 w-full")}
              {bar("mt-2 h-4 w-5/6")}
              {bar("mt-2 h-4 w-2/3")}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function CountValue({
  value,
  tone,
}: {
  value?: number | null;
  tone?: "high" | "moderate" | "low";
}) {
  return (
    <span className="inline-flex items-center gap-1.5 font-mono tabular-nums">
      {tone ? (
        <span
          className="size-2 rounded-full"
          style={{ backgroundColor: impactColor(tone) }}
          aria-hidden
        />
      ) : null}
      {(value ?? 0).toLocaleString()}
    </span>
  );
}

/** Impact colour tokens, shared by every consequence readout on the page. */
function impactColor(tone: "high" | "moderate" | "low"): string {
  return tone === "high"
    ? "var(--impact-high)"
    : tone === "moderate"
      ? "var(--impact-moderate)"
      : "var(--impact-low)";
}
