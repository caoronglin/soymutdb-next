/**
 * Gene detail route — full gene information with tabbed sections for
 * overview, expression data, and homologs.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { ArrowLeft, Microscope, BarChart3, Dna } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
  Skeleton,
  Badge,
  Button,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  EmptyState,
} from "@soymutdb/ui";
import { getGene, getGeneExpression, getGeneHomologs } from "@soymutdb/api-client";
import { FadeUp, ScaleIn } from "../../components/route-motion";
import { formatPosition, formatMb, jbrowseUrl } from "../../lib/format";
import { DataTable, type DataTableColumn } from "../../components/data-table";

const ExpressionBarChart = React.lazy(
  () => import("../../components/charts/expression-bar-chart"),
);

export const Route = createFileRoute("/genes/$geneId")({
  component: GeneDetailComponent,
});

function GeneDetailComponent() {
  const { t } = useTranslation();
  const { geneId } = Route.useParams();

  const geneQuery = useQuery({
    queryKey: ["gene", geneId],
    queryFn: () => getGene(geneId),
  });

  const expressionQuery = useQuery({
    queryKey: ["gene-expression", geneId],
    queryFn: () => getGeneExpression(geneId),
    enabled: !!geneId,
  });

  const homologQuery = useQuery({
    queryKey: ["gene-homologs", geneId],
    queryFn: () => getGeneHomologs(geneId),
    enabled: !!geneId,
  });

  const gene = geneQuery.data;
  const expressions = expressionQuery.data?.expressions ?? [];
  const homologs = homologQuery.data?.homologs ?? [];

  // Build bar chart data: mean FPKM per tissue+treatment
  const barChartData = React.useMemo(() => {
    const grouped = new Map<string, { sum: number; count: number; treatment: string }>();
    for (const expr of expressions) {
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

  const expressionColumns: DataTableColumn<(typeof expressions)[number]>[] = [
    {
      id: "library_name",
      header: t("genes.expression.library"),
      cell: (row) => row.library_name,
    },
    {
      id: "tissue",
      header: t("genes.expression.tissue"),
      cell: (row) => row.tissue,
    },
    {
      id: "treatment",
      header: t("genes.expression.treatment"),
      cell: (row) => row.treatment,
    },
    {
      id: "fpkm",
      header: t("genes.expression.fpkm"),
      cell: (row) => row.fpkm.toFixed(2),
      numeric: true,
    },
    {
      id: "tpm",
      header: t("genes.expression.tpm"),
      cell: (row) => row.tpm.toFixed(2),
      numeric: true,
    },
  ];

  const homologColumns: DataTableColumn<(typeof homologs)[number]>[] = [
    {
      id: "species",
      header: t("genes.homologs.species"),
      cell: (row) => row.species,
    },
    {
      id: "gene_id",
      header: t("genes.homologs.gene_id"),
      cell: (row) => (
        <span className="font-mono text-xs">{row.gene_id}</span>
      ),
    },
    {
      id: "type",
      header: t("genes.homologs.type"),
      cell: (row) => row.type,
    },
    {
      id: "source",
      header: t("genes.homologs.source"),
      cell: (row) => row.source,
    },
  ];

  return (
    <div className="container-prose section-rhythm">
      <Link
        to="/genes"
        search={{
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
          <Skeleton className="h-12 w-2/3" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : geneQuery.isError || !gene ? (
        <Card className="mt-8">
          <CardContent className="p-8 text-center text-muted-foreground">
            {t("common.noData")}
          </CardContent>
        </Card>
      ) : (
        <>
          <FadeUp>
            <div className="mt-6 flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <Badge variant="secondary" className="font-mono text-[10px] uppercase">
                    {gene.biotype}
                  </Badge>
                  <Badge variant="outline" className="font-mono text-[10px]">
                    {gene.chromosome}
                  </Badge>
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
              <Button asChild>
                <a
                  href={jbrowseUrl({
                    chromosome: gene.chromosome,
                    start: gene.start_pos,
                    end: gene.end_pos,
                  })}
                >
                  <Microscope className="size-4" aria-hidden />
                  {t("genes.viewInBrowser")}
                </a>
              </Button>
            </div>
          </FadeUp>

          <Tabs defaultValue="overview" className="mt-8">
            <TabsList>
              <TabsTrigger value="overview">
                {t("genes.tabs.overview")}
              </TabsTrigger>
              <TabsTrigger value="expression">
                {t("genes.tabs.expression")}
              </TabsTrigger>
              <TabsTrigger value="homologs">
                {t("genes.tabs.homologs")}
              </TabsTrigger>
            </TabsList>

            {/* ── Overview Tab ── */}
            <TabsContent value="overview">
              <div className="grid gap-4 lg:grid-cols-3">
                <ScaleIn>
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">
                        {t("genes.genomicLocation")}
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-2 text-sm">
                      <DetailRow
                        label={t("genes.chromosomeLabel")}
                        value={<span className="font-mono">{gene.chromosome}</span>}
                      />
                      <DetailRow
                        label={t("genes.position")}
                        value={
                          <span className="font-mono">
                            {formatPosition(gene.start_pos)}–{formatPosition(gene.end_pos)}
                          </span>
                        }
                      />
                      <DetailRow
                        label="Length"
                        value={
                          <span className="font-mono">
                            {formatMb(gene.end_pos - gene.start_pos)}
                          </span>
                        }
                      />
                      <DetailRow
                        label={t("genes.strand")}
                        value={<span className="font-mono">{gene.strand}</span>}
                      />
                    </CardContent>
                  </Card>
                </ScaleIn>

                <ScaleIn delay={80}>
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">
                        {t("genes.variantSummary")}
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-2 text-sm">
                      <DetailRow
                        label={t("genes.variantCount")}
                        value={
                          <span className="font-mono tabular-nums">
                            {(gene.variant_count ?? 0).toLocaleString()}
                          </span>
                        }
                      />
                      <DetailRow
                        label={t("genes.highImpactVariants")}
                        value={
                          <span className="font-mono tabular-nums text-impact-high">
                            {(gene.high_impact_variants ?? 0).toLocaleString()}
                          </span>
                        }
                      />
                      <DetailRow
                        label={t("genes.snpCount")}
                        value={
                          <span className="font-mono tabular-nums">
                            {(gene.snp_count ?? 0).toLocaleString()}
                          </span>
                        }
                      />
                      <DetailRow
                        label={t("genes.indelCount")}
                        value={
                          <span className="font-mono tabular-nums">
                            {(gene.indel_count ?? 0).toLocaleString()}
                          </span>
                        }
                      />
                      <DetailRow
                        label={t("genes.mutantLineCount")}
                        value={
                          <span className="font-mono tabular-nums">
                            {(gene.mutant_line_count ?? 0).toLocaleString()}
                          </span>
                        }
                      />
                    </CardContent>
                  </Card>
                </ScaleIn>

                <ScaleIn delay={160}>
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">
                        {t("genes.generalInfo")}
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-2 text-sm">
                      <DetailRow
                        label="Biotype"
                        value={<span className="font-mono">{gene.biotype}</span>}
                      />
                      <DetailRow
                        label="Source"
                        value={
                          <span className="font-mono">{gene.source ?? "—"}</span>
                        }
                      />
                      <DetailRow
                        label="Annotation"
                        value={<span className="font-mono">Wm82.a4.v1</span>}
                      />
                    </CardContent>
                  </Card>
                </ScaleIn>
              </div>

              <Card className="mt-4">
                <CardHeader>
                  <CardTitle className="text-base">
                    {t("genes.geneVariants")}
                  </CardTitle>
                  <CardDescription>
                    Effect breakdown for this gene
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
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
                </CardContent>
              </Card>
            </TabsContent>

            {/* ── Expression Tab ── */}
            <TabsContent value="expression">
              <ScaleIn>
                {expressionQuery.isLoading ? (
                  <Skeleton className="h-72 w-full" />
                ) : expressions.length === 0 ? (
                  <EmptyState
                    icon={BarChart3}
                    title={t("genes.expression.no_data")}
                  />
                ) : (
                  <div className="space-y-6">
                    <React.Suspense
                      fallback={<Skeleton className="h-72 w-full" />}
                    >
                      <ExpressionBarChart data={barChartData} />
                    </React.Suspense>
                    <DataTable
                      columns={expressionColumns}
                      data={expressions}
                      ariaLabel={t("genes.expression.library")}
                    />
                  </div>
                )}
              </ScaleIn>
            </TabsContent>

            {/* ── Homologs Tab ── */}
            <TabsContent value="homologs">
              <ScaleIn>
                {homologQuery.isLoading ? (
                  <Skeleton className="h-64 w-full" />
                ) : homologs.length === 0 ? (
                  <EmptyState
                    icon={Dna}
                    title={t("genes.homologs.no_data")}
                  />
                ) : (
                  <DataTable
                    columns={homologColumns}
                    data={homologs}
                    ariaLabel={t("genes.homologs.species")}
                  />
                )}
              </ScaleIn>
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{value}</span>
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
