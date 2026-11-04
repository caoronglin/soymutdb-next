import { assembliesQueryOptions } from "../../lib/query-options";
/**
 * Gene detail route — full gene information with tabbed sections for
 * overview, expression data, and homologs.
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
  BarChartOutlined as BarChart3,
  DeploymentUnitOutlined as Dna,
} from "@ant-design/icons";
import {
  Button,
  Card,
  Descriptions,
  Empty,
  Skeleton,
  Table,
  Tabs,
  Tag,
  Typography,
  type TableColumnsType,
} from "@/lib/antd";
import {
  getGene,
  getGeneExpression,
  getGeneHomologs,
  getReleaseId,
  listTestDataPreviewMutationSitesForGene,
  type ExpressionRecord,
  type HomologRecord,
  type TestDataPreviewMutationSite,
} from "@soymutdb/api-client";
import { GeneOrthologSection } from "../../components/comparative/ortholog-section";
import { GeneGenomeView } from "../../components/gene-genome-view";
import { GeneSeedRequestEntry } from "../../components/gene-seed-request-entry";
import { FadeUp, ScaleIn } from "../../components/route-motion";
import { isGeneDetailRecord } from "../../lib/api-contract-guards";
import { buildJbrowseLocusUrl } from "../../lib/deployment";
import { formatPosition } from "../../lib/format";
import { queryKeys } from "../../lib/query-keys";
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

export const Route = createFileRoute("/genes/$geneId")({
  component: GeneDetailComponent,
  // Keep deep-link assembly context typed, but do not render it until the
  // detail API accepts assembly and binds the returned record to it.
  validateSearch: (search: Record<string, unknown>) => ({
    assembly: search.assembly ? String(search.assembly) : undefined,
  }),
});

function GeneDetailComponent() {
  const { t } = useTranslation();
  const { geneId } = Route.useParams();
  const { assembly } = Route.useSearch();
  const releaseId = getReleaseId();
  const assembliesQuery = useQuery(assembliesQueryOptions({
    releaseId: getReleaseId(),
    siteVariant: SITE_VARIANT,
  }));
  const selectedAssembly = assembliesQuery.data?.find(
    (candidate) => String(candidate.id) === String(assembly),
  );
  const geneQuery = useQuery({
    queryKey: queryKeys.genes.detail(geneId, assembly, releaseId, SITE_VARIANT),
    queryFn: () => getGene(geneId, { assembly_id: assembly }),
  });

  const expressionQuery = useQuery({
    queryKey: queryKeys.genes.expression({ geneId, assemblyId: assembly, releaseId, siteVariant: SITE_VARIANT }),
    queryFn: () => getGeneExpression(geneId, { assembly_id: assembly }),
    enabled: !!geneId,
  });

  const homologQuery = useQuery({
    queryKey: queryKeys.genes.homologs({ geneId, assemblyId: assembly, releaseId, siteVariant: SITE_VARIANT }),
    queryFn: () => getGeneHomologs(geneId, { assembly_id: assembly }),
    enabled: !!geneId,
  });

  // A 200 response of the wrong shape (e.g. the search-list envelope) must render
  // the empty state, not crash the genome view on undefined coordinates.
  const gene = isGeneDetailRecord(geneQuery.data) ? geneQuery.data : undefined;

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

  const expressions = React.useMemo(
    () => expressionQuery.data?.expressions ?? [],
    [expressionQuery.data],
  );
  const homologs = homologQuery.data?.homologs ?? [];
  const jbrowseAssembly = gene?.assembly_name ?? selectedAssembly?.name;
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
      const key = `${expr.tissue}|${expr.treatment}`;
      const existing = grouped.get(key);
      if (existing) {
        existing.sum += expr.fpkm;
        existing.count += 1;
      } else {
        grouped.set(key, { sum: expr.fpkm, count: 1, treatment: expr.treatment });
      }
    }
    return Array.from(grouped.entries()).map(([key, val]) => {
      const [tissue] = key.split("|");
      return { tissue, mean_fpkm: val.sum / val.count, treatment: val.treatment };
    });
  }, [expressions]);

  const expressionColumns: TableColumnsType<ExpressionRecord> = [
    {
      title: t("genes.expression.library"),
      dataIndex: "library_name",
      key: "library_name",
    },
    { title: t("genes.expression.tissue"), dataIndex: "tissue", key: "tissue" },
    { title: t("genes.expression.treatment"), dataIndex: "treatment", key: "treatment" },
    {
      title: t("genes.expression.fpkm"),
      dataIndex: "fpkm",
      key: "fpkm",
      align: "right",
      render: (_, row) => row.fpkm == null ? "—" : row.fpkm.toFixed(2),
    },
    {
      title: t("genes.expression.tpm"),
      dataIndex: "tpm",
      key: "tpm",
      align: "right",
      render: (_, row) => row.tpm == null ? "—" : row.tpm.toFixed(2),
    },
  ];

  const homologColumns: TableColumnsType<HomologRecord> = [
    { title: t("genes.homologs.species"), dataIndex: "species", key: "species" },
    {
      title: t("genes.homologs.gene_id"),
      dataIndex: "gene_id",
      key: "gene_id",
      render: (_, row) => <span className="font-mono text-xs">{row.gene_id}</span>,
    },
    { title: t("genes.homologs.type"), dataIndex: "type", key: "type" },
    { title: t("genes.homologs.source"), dataIndex: "source", key: "source" },
  ];

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
            {grade === "H" ? "高" : grade === "M" ? "中" : "低"}
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
        <Tag color={row.available ? "green" : "default"}>{row.available ? "是" : "否"}</Tag>
      ),
    },
    // The W82_V2 / W82_V4 / DN53_V1 homolog accessions are deliberately NOT
    // columns here either: they are alternate identifiers for the same locus,
    // used by search, not fields to read off the page.
  ];

  return (
    <div className="container-prose section-rhythm" data-testid="gene-detail">
      <Link
        to="/genes"
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

      {geneQuery.isLoading ? (
        <div className="mt-8 grid gap-4">
          <Skeleton active paragraph={{ rows: 1 }} title={{ width: "66%" }} />
          <Skeleton active paragraph={{ rows: 8 }} title={false} />
        </div>
      ) : geneQuery.isError || !gene ? (
        <Card className="mt-8">
          <Empty description={t("common.noData")} className="py-8" />
        </Card>
      ) : (
        <>
          <FadeUp>
            <div className="mt-6 flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <Tag className="m-0 font-mono text-[10px] uppercase">{gene.biotype}</Tag>
                  <Tag className="m-0 font-mono text-[10px]">{gene.chromosome}</Tag>
                  <Tag data-testid="gene-assembly" className="m-0 font-mono text-[10px]" color="blue">
                    {gene.assembly_name ?? selectedAssembly?.name ?? assembly ?? "—"}
                  </Tag>
                </div>
                <h1 data-testid="gene-id" className="mt-3 font-mono text-3xl font-semibold tracking-tight">
                  {gene.gene_id}
                </h1>
                <p
                  data-testid="gene-coords"
                  className="mt-1 font-mono text-sm text-muted-foreground"
                >
                  {gene.chromosome}:{gene.start_pos}..{gene.end_pos}
                </p>
                {gene.symbol ? (
                  <p className="mt-1 font-display text-xl text-muted-foreground">
                    {gene.symbol}
                  </p>
                ) : null}
                {gene.description ? (
                  <p className="mt-2 max-w-2xl text-muted-foreground">
                    {gene.description}
                  </p>
                ) : null}
                {/* The gene model's provenance, stated once at the top so a
                    predicted model is never read as a curated one. */}
                <div className="mt-2" data-testid="gene-model-evidence">
                  <EvidenceLine evidence={gene.model_evidence ?? null} />
                </div>
              </div>
              <Button
                data-testid="gene-jbrowse"
                href={jbrowseHref}
                disabled={!jbrowseHref}
                icon={<Microscope className="size-4" aria-hidden />}
              >
                {t("genes.viewInBrowser")}
              </Button>
            </div>
          </FadeUp>

          {(() => {
            const tabItems = [
              {
                key: "overview",
                label: t("genes.tabs.overview"),
                children: (
                  <>
                    {/* The genome-annotation cards (assembly location, biotype/
                        source/annotation, transcript structure) were removed at
                        the operator's request: this page is driven by the table
                        they upload, not by the GFF3 annotation file. */}
                    <div className="grid gap-4 lg:grid-cols-3">
                    <ScaleIn delay={80}>
                      <Card title={<span className="text-base">{t("genes.variantSummary")}</span>}>
                        <Descriptions
                          size="small"
                          column={1}
                          items={[
                            {
                              key: "variant_count",
                              label: t("genes.variantCount"),
                              children: (
                                <span className="font-mono tabular-nums">
                                  {(gene.variant_count ?? 0).toLocaleString()}
                                </span>
                              ),
                            },
                            {
                              key: "high_impact",
                              label: t("genes.highImpactVariants"),
                              children: (
                                <span className="font-mono tabular-nums text-impact-high">
                                  {(gene.high_impact_variants ?? 0).toLocaleString()}
                                </span>
                              ),
                            },
                            {
                              key: "snp_count",
                              label: t("genes.snpCount"),
                              children: (
                                <span className="font-mono tabular-nums">
                                  {(gene.snp_count ?? 0).toLocaleString()}
                                </span>
                              ),
                            },
                            {
                              key: "indel_count",
                              label: t("genes.indelCount"),
                              children: (
                                <span className="font-mono tabular-nums">
                                  {(gene.indel_count ?? 0).toLocaleString()}
                                </span>
                              ),
                            },
                            {
                              key: "mutant_line_count",
                              label: t("genes.mutantLineCount"),
                              children: (
                                <span className="font-mono tabular-nums">
                                  {(gene.mutant_line_count ?? 0).toLocaleString()}
                                </span>
                              ),
                            },
                          ]}
                        />
                      </Card>
                    </ScaleIn>

                  </div>

                    {/* Simplified genome view: the gene body, its transcripts
                        and the operator's mutation sites in one SVG. This sits
                        alongside — never replaces — the full JBrowse 2 browser,
                        which stays reachable at /search/gbrowse and via the
                        "open in browser" action in the header. */}
                    <ScaleIn delay={200}>
                      <GeneGenomeView
                        className="mt-4"
                        gene={gene}
                        mutationSites={mutationSites}
                        assemblyLabel={jbrowseAssembly ?? assembly ?? undefined}
                      />
                    </ScaleIn>

                    {/* Local-only unpublished test-data preview. Rendered only
                        when the loopback-gated preview endpoint answers, so a
                        build without the local preview behaves exactly as
                        before and never shows an empty or erroring card. */}
                    {mutationSites.length > 0 ? (
                      <Card
                        className="mt-4"
                        data-testid="gene-mutation-sites"
                        title={t("genes.mutationSitesTitle", { defaultValue: "突变位点" })}
                        extra={
                          <Tag color="orange">
                            {t("genes.unpublishedPreview", { defaultValue: "未发布预览" })}
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
                key: "expression",
                label: t("genes.tabs.expression"),
                children: (
                  <ScaleIn>
                    {expressionQuery.isLoading ? (
                      <Skeleton active paragraph={{ rows: 8 }} title={false} />
                    ) : expressions.length === 0 ? (
                      <Empty
                        image={<BarChart3 className="size-10 text-muted-foreground" aria-hidden />}
                        description={t("genes.expression.no_data")}
                        className="py-10"
                      />
                    ) : (
                      <div className="space-y-6">
                        <React.Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} title={false} />}>
                          <ExpressionBarChart data={barChartData} />
                        </React.Suspense>
                        <Table<ExpressionRecord>
                          rowKey="library_public_id"
                          size="small"
                          columns={expressionColumns}
                          dataSource={expressions}
                          pagination={false}
                          locale={{ emptyText: t("genes.expression.no_data") }}
                        />
                      </div>
                    )}
                  </ScaleIn>
                ),
              },
              {
                key: "homologs",
                label: t("genes.tabs.homologs"),
                children: (
                  <ScaleIn>
                    {homologQuery.isLoading ? (
                      <Skeleton active paragraph={{ rows: 6 }} title={false} />
                    ) : homologs.length === 0 ? (
                      <Empty
                        image={<Dna className="size-10 text-muted-foreground" aria-hidden />}
                        description={t("genes.homologs.no_data")}
                        className="py-10"
                      />
                    ) : (
                      <Table<HomologRecord>
                        rowKey={(row) => `${row.species}-${row.gene_id}`}
                        size="small"
                        columns={homologColumns}
                        dataSource={homologs}
                        pagination={false}
                        locale={{ emptyText: t("genes.homologs.no_data") }}
                      />
                    )}
                  </ScaleIn>
                ),
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
                key: "sequences",
                label: t("genes.sequences.title"),
                children: (
                  <ScaleIn>
                    <GeneSequencePanel sequences={gene.sequences} />
                  </ScaleIn>
                ),
              },
            ];
            return <Tabs defaultActiveKey="overview" className="mt-8" items={tabItems} />;
          })()}

          <Card className="mt-4">
            <Card.Meta
              title={<span className="text-base">{t("genes.geneVariants")}</span>}
              description={
                <Typography.Text type="secondary">{t("genes.effectBreakdown")}</Typography.Text>
              }
            />
            <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
              <EffectPill
                label={t("genes.nonsenseCount")}
                value={gene.nonsense_count ?? 0}
                tone="high"
              />
              <EffectPill
                label={t("genes.missenseCount")}
                value={gene.missense_count ?? 0}
                tone="moderate"
              />
              <EffectPill
                label={t("genes.synonymousCount")}
                value={gene.synonymous_count ?? 0}
                tone="low"
              />
              <EffectPill
                label={t("genes.frameshiftCount")}
                value={gene.frameshift_count ?? 0}
                tone="high"
              />
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

function EffectPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "high" | "moderate" | "low";
}) {
  const color =
    tone === "high"
      ? "var(--impact-high)"
      : tone === "moderate"
        ? "var(--impact-moderate)"
        : "var(--impact-low)";
  return (
    <div className="rounded-lg border p-3">
      <div className="flex items-center gap-1.5">
        <span className="size-2 rounded-full" style={{ backgroundColor: color }} aria-hidden />
        <span className="text-xs text-muted-foreground">{label}</span>
      </div>
      <p className="mt-1 font-mono text-lg font-semibold tabular-nums">
        {value.toLocaleString()}
      </p>
    </div>
  );
}
