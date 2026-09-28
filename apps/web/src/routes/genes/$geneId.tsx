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
  getAssemblies,
  getGene,
  getGeneExpression,
  getGeneHomologs,
  getReleaseId,
  type ExpressionRecord,
  type HomologRecord,
} from "@soymutdb/api-client";
import { FadeUp, ScaleIn } from "../../components/route-motion";
import { buildJbrowseLocusUrl } from "../../lib/deployment";
import { formatPosition, formatMb } from "../../lib/format";
import { queryKeys } from "../../lib/query-keys";
import { SITE_VARIANT } from "../../lib/site-variant";

const ExpressionBarChart = React.lazy(
  () => import("../../components/charts/expression-bar-chart"),
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
  const assembliesQuery = useQuery({
    queryKey: ["assemblies", releaseId, SITE_VARIANT],
    queryFn: getAssemblies,
    staleTime: 30 * 60 * 1000,
  });
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

  const gene = geneQuery.data;
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

  return (
    <div className="container-prose section-rhythm">
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
                </div>
                <h1 className="mt-3 font-mono text-3xl font-semibold tracking-tight">
                  {gene.gene_id}
                </h1>
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
              </div>
              <Button
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
                    <div className="grid gap-4 lg:grid-cols-3">
                    <ScaleIn>
                      <Card title={<span className="text-base">{t("genes.genomicLocation")}</span>}>
                        <Descriptions
                          size="small"
                          column={1}
                          items={[
                            {
                              key: "chromosome",
                              label: t("genes.chromosomeLabel"),
                              children: <span className="font-mono">{gene.chromosome}</span>,
                            },
                            {
                              key: "position",
                              label: t("genes.position"),
                              children: (
                                <span className="font-mono">
                                  {formatPosition(gene.start_pos)}–{formatPosition(gene.end_pos)}
                                </span>
                              ),
                            },
                            {
                              key: "length",
                              label: "Length",
                              children: (
                                <span className="font-mono">{formatMb(gene.end_pos - gene.start_pos)}</span>
                              ),
                            },
                            {
                              key: "strand",
                              label: t("genes.strand"),
                              children: <span className="font-mono">{gene.strand}</span>,
                            },
                          ]}
                        />
                      </Card>
                    </ScaleIn>

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

                    <ScaleIn delay={160}>
                      <Card title={<span className="text-base">{t("genes.generalInfo")}</span>}>
                        <Descriptions
                          size="small"
                          column={1}
                          items={[
                            {
                              key: "biotype",
                              label: "Biotype",
                              children: <span className="font-mono">{gene.biotype}</span>,
                            },
                            {
                              key: "source",
                              label: "Source",
                              children: <span className="font-mono">{gene.source ?? "—"}</span>,
                            },
                            {
                              key: "annotation",
                              label: "Annotation",
                              children: <span className="font-mono" data-testid="gene-assembly-context">{jbrowseAssembly ?? assembly ?? "—"}</span>,
                            },
                          ]}
                        />
                      </Card>
                    </ScaleIn>
                  </div>
                  {gene.transcripts?.length ? (
                    <Card className="mt-4" data-testid="gene-transcript-structure" title={t("genes.structureTitle", { defaultValue: "Gene structure" })}>
                      <div className="space-y-3">
                        {gene.transcripts.map((transcript) => (
                          <div key={transcript.id} data-testid={`gene-transcript-${transcript.id}`} className="rounded-lg border p-3">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <span className="font-mono text-sm">{transcript.name ?? transcript.id}</span>
                              <span className="text-xs text-muted-foreground">
                                {transcript.start.toLocaleString()}–{transcript.end.toLocaleString()} · {transcript.strand}
                                {transcript.is_canonical ? " · canonical" : ""}
                              </span>
                            </div>
                            <div className="mt-2 flex h-3 items-center gap-1" aria-label="Exons">
                              {transcript.exons.map((exon) => (
                                <span
                                  key={exon.id}
                                  data-testid="gene-transcript-exon"
                                  className="h-3 min-w-2 rounded-sm bg-primary"
                                  style={{ flex: Math.max(1, exon.end - exon.start + 1) }}
                                  title={`${exon.start.toLocaleString()}–${exon.end.toLocaleString()}`}
                                />
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    </Card>
                    ) : null}
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
            ];
            return <Tabs defaultActiveKey="overview" className="mt-8" items={tabItems} />;
          })()}

          <Card className="mt-4">
            <Card.Meta
              title={<span className="text-base">{t("genes.geneVariants")}</span>}
              description={
                <Typography.Text type="secondary">Effect breakdown for this gene</Typography.Text>
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
