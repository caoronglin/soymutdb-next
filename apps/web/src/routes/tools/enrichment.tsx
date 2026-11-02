import { getReleaseId } from "@soymutdb/api-client";
import { SITE_VARIANT } from "../../lib/site-variant";
import { assembliesQueryOptions } from "../../lib/query-options";
/**
 * Enrichment tool — GO/KEGG enrichment with two analysis modes.
 *
 * POST /api/v1/tools/enrichment:
 *   - "ora" (default): hypergeometric over-representation test; terms filtered
 *     by raw p_threshold, sorted by q-value ascending, capped at max_terms.
 *   - "gsea": simplified rank-based gene-set test over per-gene values
 *     (e.g. log2FC); requires values aligned 1:1 with genes and a minimum
 *     term size (min_genes).
 *
 * Results render as a significance plot (bubble / bar of -log10(q), drawn by
 * the shared @soymutdb/charts facade, which imports its engine lazily) plus the
 * DataTable of enriched terms.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { useMemo } from "react";
import { NodeIndexOutlined, RiseOutlined, CaretRightOutlined, LoadingOutlined, RedoOutlined } from "@ant-design/icons";
import { Breadcrumb, Button, Card, Empty, Input, Result, Select, Tabs, Tag, Typography } from "@/lib/antd";
import { useToast } from "@/lib/toast";
import { DataTable } from "../../components/data-table";
import {
  buildEnrichmentCanvasData,
  buildEnrichmentChartDefinition,
  ENRICHMENT_CANVAS_TABLE_COLUMNS,
  enrichmentCanvasTableRow,
  enrichmentCanvasTooltipFormatter,
  enrichmentDatumStyle,
} from "../../components/charts/tool-chart-definitions";
import { ToolChartFigure } from "../../components/charts/tool-chart-figure";
import {
  enrichmentDescription,
  enrichmentFormatP as fmtP,
  enrichmentFormatSigned as fmtSigned,
  type EnrichmentChartRow as ChartRow,
  type EnrichmentChartView,
} from "../../components/charts/tool-enrichment-mapping";
import { runEnrichment } from "./api";
import type {
  EnrichmentResponse,
  EnrichmentGseaResponse,
} from "./api";

export const Route = createFileRoute("/tools/enrichment")({
  component: EnrichmentComponent,
});

const MAX_INPUT_GENES = 500;

type Mode = "ora" | "gsea";
type EnrichmentResult = EnrichmentResponse | EnrichmentGseaResponse;

/** Unified result row used by the table and the charts. */
interface ResultRow {
  id: string;
  name: string;
  p_value: number;
  q_value: number;
  gene_count: number;
  es?: number;
  nes?: number;
  genes: string[];
}

function parseGenes(raw: string): string[] {
  return [
    ...new Set(
      raw
        .split(/[\s,;]+/)
        .map((g) => g.trim())
        .filter(Boolean),
    ),
  ];
}

interface ParsedGeneValues {
  pairs: Array<{ gene: string; value: number }>;
  error?: "empty" | "badLine" | "finite";
}

/** Parse "gene<TAB>value" lines; duplicates keep the first value (matches
 *  the server-side dedup semantics). */
function parseGeneValues(raw: string): ParsedGeneValues {
  const pairs: Array<{ gene: string; value: number }> = [];
  const seen = new Set<string>();
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const parts = trimmed.split(/[\s\t]+/);
    if (parts.length !== 2) return { pairs, error: "badLine" };
    const [gene, valueStr] = parts;
    const value = Number(valueStr);
    if (!Number.isFinite(value)) return { pairs, error: "finite" };
    if (!seen.has(gene)) {
      seen.add(gene);
      pairs.push({ gene, value });
    }
  }
  if (pairs.length === 0) return { pairs, error: "empty" };
  return { pairs };
}

function EnrichmentComponent() {
  const { t } = useTranslation();
  const { success, error } = useToast();

  const [mode, setMode] = React.useState<Mode>("ora");
  const [genesRaw, setGenesRaw] = React.useState("");
  const [gseaRaw, setGseaRaw] = React.useState("");
  const [minGenesRaw, setMinGenesRaw] = React.useState("5");
  const [ontology, setOntology] = React.useState<"go" | "kegg">("go");
  const [pThreshold, setPThreshold] = React.useState("0.05");
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  const [result, setResult] = React.useState<EnrichmentResult | null>(null);
  const [chartView, setChartView] = React.useState<"bubble" | "bar">("bubble");
  const [assemblyId, setAssemblyId] = React.useState("");
  const assembliesQuery = useQuery(assembliesQueryOptions({
    releaseId: getReleaseId(),
    siteVariant: SITE_VARIANT,
  }));
  const assemblies = React.useMemo(() => assembliesQuery.data ?? [], [assembliesQuery.data]);

  React.useEffect(() => {
    if (assemblyId || assemblies.length === 0) return;
    const defaultAssembly = assemblies.find((assembly) => assembly.is_default) ?? assemblies[0];
    if (defaultAssembly) setAssemblyId(String(defaultAssembly.id));
  }, [assemblies, assemblyId]);

  const enrichMutation = useMutation({
    mutationFn: async (): Promise<EnrichmentResult> => {
      const p = Number(pThreshold);
      if (mode === "gsea") {
        const { pairs } = parseGeneValues(gseaRaw);
        return runEnrichment({
          assembly_id: Number(assemblyId),
          genes: pairs.map((x) => x.gene),
          values: pairs.map((x) => x.value),
          mode: "gsea",
          ontology,
          p_threshold: p,
          max_terms: 50,
          min_genes: Number(minGenesRaw),
        });
      }
      return runEnrichment({
        assembly_id: Number(assemblyId),
        genes: parseGenes(genesRaw),
        mode: "ora",
        ontology,
        p_threshold: p,
        max_terms: 50,
        min_genes: 5, // ignored by the server in ora mode
      });
    },
    onSuccess: (data) => {
      setResult(data);
      success(
        t("tools.enrichment.toastDone"),
        t("tools.enrichment.toastDoneDesc", { count: data.terms?.length ?? 0 }),
      );
    },
    onError: (err: Error) => {
      error(t("tools.enrichment.toastFailed"), err.message);
    },
  });

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!assemblyId) errs.assembly = t("tools.enrichment.errorAssemblyRequired");
    if (mode === "gsea") {
      const parsed = parseGeneValues(gseaRaw);
      if (parsed.error === "empty") errs.gsea = t("tools.enrichment.gsea.errorEmpty");
      else if (parsed.error === "badLine") errs.gsea = t("tools.enrichment.gsea.errorBadLine");
      else if (parsed.error === "finite") errs.gsea = t("tools.enrichment.gsea.errorFinite");
      if (parsed.pairs.length > MAX_INPUT_GENES) {
        errs.gsea = t("tools.enrichment.errorGenesMax");
      }
      const mg = Number(minGenesRaw);
      if (!Number.isInteger(mg) || mg < 1 || mg > MAX_INPUT_GENES) {
        errs.minGenes = t("tools.enrichment.gsea.errorMinGenes");
      }
    } else {
      const genes = parseGenes(genesRaw);
      if (genes.length === 0) errs.genes = t("tools.enrichment.errorGenesEmpty");
      else if (genes.length > MAX_INPUT_GENES) errs.genes = t("tools.enrichment.errorGenesMax");
    }
    const p = Number(pThreshold);
    if (!Number.isFinite(p) || p <= 0 || p > 1) errs.p = t("tools.enrichment.errorP");
    setFieldErrors(errs);
    if (Object.keys(errs).length > 0) return;
    setResult(null);
    enrichMutation.mutate();
  };

  const onModeChange = (next: Mode) => {
    setMode(next);
    setResult(null);
    setFieldErrors({});
    enrichMutation.reset();
  };

  const onClear = () => {
    setGenesRaw("");
    setGseaRaw("");
    setMinGenesRaw("5");
    setOntology("go");
    setPThreshold("0.05");
    setFieldErrors({});
    setResult(null);
    enrichMutation.reset();
  };

  const isGsea = result?.mode === "gsea";
  const terms = React.useMemo(() => result?.terms ?? [], [result]);
  const rows: ResultRow[] = useMemo(() => {
    return terms.map((row) => ({
      id: row.id,
      name: row.name,
      p_value: row.p_value,
      q_value: row.q_value,
      gene_count: "size" in row ? row.size : row.gene_count,
      es: "es" in row ? row.es : undefined,
      nes: "nes" in row ? row.nes : undefined,
      genes: row.genes,
    }));
  }, [terms]);

  const chartRows: ChartRow[] = useMemo(
    () =>
      rows.map((r) => ({
        id: r.id,
        name: r.name,
        p: r.p_value,
        q: r.q_value,
        size: r.gene_count,
        es: r.es,
      })),
    [rows],
  );

  const columns = isGsea
    ? [
        {
          key: "term",
          header: t("tools.enrichment.colTerm"),
          cell: (row: ResultRow) => (
            <div className="min-w-0">
              <p className="font-mono text-xs font-medium">{row.id}</p>
              <p className="truncate text-xs text-muted-foreground">{row.name}</p>
            </div>
          ),
        },
        {
          key: "es",
          header: t("tools.enrichment.gsea.colEs"),
          align: "right" as const,
          cell: (row: ResultRow) => (
            <span className="font-mono text-xs">{fmtSigned(row.es)}</span>
          ),
        },
        {
          key: "nes",
          header: t("tools.enrichment.gsea.colNes"),
          align: "right" as const,
          cell: (row: ResultRow) => (
            <span className="font-mono text-xs">{fmtSigned(row.nes)}</span>
          ),
        },
        {
          key: "p",
          header: t("tools.enrichment.colP"),
          align: "right" as const,
          cell: (row: ResultRow) => <span className="font-mono text-xs">{fmtP(row.p_value)}</span>,
        },
        {
          key: "q",
          header: t("tools.enrichment.colQ"),
          align: "right" as const,
          cell: (row: ResultRow) => <span className="font-mono text-xs">{fmtP(row.q_value)}</span>,
        },
        {
          key: "size",
          header: t("tools.enrichment.gsea.colSize"),
          align: "right" as const,
          cell: (row: ResultRow) => (
            <span className="font-mono text-xs">{row.gene_count}</span>
          ),
        },
        {
          key: "members",
          header: t("tools.enrichment.colMembers"),
          cell: (row: ResultRow) => (
            <div className="flex max-w-[420px] flex-wrap gap-1">
              {row.genes.map((g) => (
                <Tag key={g} className="font-mono text-[10px]">
                  {g}
                </Tag>
              ))}
            </div>
          ),
        },
      ]
    : [
        {
          key: "term",
          header: t("tools.enrichment.colTerm"),
          cell: (row: ResultRow) => (
            <div className="min-w-0">
              <p className="font-mono text-xs font-medium">{row.id}</p>
              <p className="truncate text-xs text-muted-foreground">{row.name}</p>
            </div>
          ),
        },
        {
          key: "p",
          header: t("tools.enrichment.colP"),
          align: "right" as const,
          cell: (row: ResultRow) => <span className="font-mono text-xs">{fmtP(row.p_value)}</span>,
        },
        {
          key: "q",
          header: t("tools.enrichment.colQ"),
          align: "right" as const,
          cell: (row: ResultRow) => <span className="font-mono text-xs">{fmtP(row.q_value)}</span>,
        },
        {
          key: "gene_count",
          header: t("tools.enrichment.colGenes"),
          align: "right" as const,
          cell: (row: ResultRow) => (
            <span className="font-mono text-xs">{row.gene_count}</span>
          ),
        },
        {
          key: "members",
          header: t("tools.enrichment.colMembers"),
          cell: (row: ResultRow) => (
            <div className="flex max-w-[420px] flex-wrap gap-1">
              {row.genes.map((g) => (
                <Tag key={g} className="font-mono text-[10px]">
                  {g}
                </Tag>
              ))}
            </div>
          ),
        },
      ];

  return (
    <div className="container-prose section-rhythm">
      <header className="flex flex-col gap-4">
        <Breadcrumb items={[{ title: t("tools.title") }, { title: t("tools.enrichment.title") }]} />
        <div className="flex items-start gap-3.5">
          <span className="flex size-11 items-center justify-center rounded-xl border bg-card shadow-sm"><NodeIndexOutlined className="size-5" aria-hidden /></span>
          <div>
            <Typography.Title level={1} style={{ margin: 0 }}>{t("tools.enrichment.title")}</Typography.Title>
            <Typography.Paragraph type="secondary" style={{ margin: 0 }}>{t("tools.enrichment.subtitle")}</Typography.Paragraph>
          </div>
        </div>
      </header>

      <div className="mt-10 grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <Card>
          <div className="mb-5">
            <Typography.Title level={5} style={{ margin: 0 }}>{t("tools.enrichment.formTitle")}</Typography.Title>
            <Typography.Text type="secondary">
              {mode === "gsea" ? t("tools.enrichment.gsea.desc") : t("tools.enrichment.formDesc")}
            </Typography.Text>
          </div>
          <div>
            <form onSubmit={onSubmit} className="grid gap-5">
              <div className="grid gap-2">
                <label htmlFor="en-assembly">{t("tools.enrichment.assemblyLabel")}</label>
                 <Select
                   id="en-assembly"
                   value={assemblyId || undefined}
                   onChange={(value) => {
                     setAssemblyId(value);
                     setResult(null);
                     setFieldErrors({});
                     enrichMutation.reset();
                   }}
                   placeholder={t("tools.enrichment.assemblyPlaceholder")}
                   loading={assembliesQuery.isLoading}
                   disabled={assembliesQuery.isError}
                   options={assemblies.map((assembly) => ({
                     value: String(assembly.id),
                     label: `${assembly.name} (${assembly.version})`,
                   }))}
                   aria-invalid={!!fieldErrors.assembly}
                 />
                 <p className="text-xs text-muted-foreground">
                   {assembliesQuery.isError
                     ? t("tools.enrichment.assembliesError")
                     : t("tools.enrichment.assemblyHelp")}
                 </p>
                 {fieldErrors.assembly ? (
                   <p className="text-xs text-destructive">{fieldErrors.assembly}</p>
                 ) : null}
               </div>

               <div className="grid gap-2">
                 <label>{t("tools.enrichment.modeLabel")}</label>
                <Tabs
                  activeKey={mode}
                  onChange={(value) => onModeChange(value as Mode)}
                  items={[
                    { key: "ora", label: t("tools.enrichment.modeOra") },
                    { key: "gsea", label: t("tools.enrichment.modeGsea") },
                  ]}
                />
                <p className="text-xs text-muted-foreground">
                  {mode === "gsea"
                    ? t("tools.enrichment.modeGseaDesc")
                    : t("tools.enrichment.modeOraDesc")}
                </p>
              </div>

              {mode === "ora" ? (
                <div className="grid gap-2">
                  <label htmlFor="en-genes">{t("tools.enrichment.genesLabel")}</label>
                  <Input.TextArea
                    id="en-genes"
                    value={genesRaw}
                    onChange={(e) => setGenesRaw(e.target.value)}
                    placeholder={t("tools.enrichment.genesPlaceholder")}
                    className="min-h-[150px] font-mono text-sm"
                    aria-invalid={!!fieldErrors.genes}
                  />
                  <p className="text-xs text-muted-foreground">{t("tools.enrichment.genesHint")}</p>
                  {fieldErrors.genes ? (
                    <p className="text-xs text-destructive">{fieldErrors.genes}</p>
                  ) : null}
                </div>
              ) : (
                <div className="grid gap-2">
                  <label htmlFor="en-gsea-values">{t("tools.enrichment.gsea.valuesLabel")}</label>
                  <Input.TextArea
                    id="en-gsea-values"
                    value={gseaRaw}
                    onChange={(e) => setGseaRaw(e.target.value)}
                    placeholder={t("tools.enrichment.gsea.valuesPlaceholder")}
                    className="min-h-[150px] font-mono text-sm"
                    aria-invalid={!!fieldErrors.gsea}
                  />
                  <p className="text-xs text-muted-foreground">
                    {t("tools.enrichment.gsea.valuesHint")}
                  </p>
                  {fieldErrors.gsea ? (
                    <p className="text-xs text-destructive">{fieldErrors.gsea}</p>
                  ) : null}
                </div>
              )}

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-2">
                  <label htmlFor="en-ontology">{t("tools.enrichment.ontologyLabel")}</label>
                  <Select
                    id="en-ontology"
                    value={ontology}
                    onChange={(v) => setOntology(v as "go" | "kegg")}
                    options={[
                      { value: "go", label: "GO" },
                      { value: "kegg", label: "KEGG" },
                    ]}
                  />
                </div>
                <div className="grid gap-2">
                  <label htmlFor="en-p">{t("tools.enrichment.pLabel")}</label>
                  <Input
                    id="en-p"
                    type="number"
                    min={0.000001}
                    max={1}
                    // `step="any"`: with a fixed step the browser blocks native
                    // form submission on a step mismatch (min=0.000001 + step
                    // 0.01 made the default 0.05 invalid, so the tool could not
                    // run at all). Validation lives in onSubmit, not the step.
                    step="any"
                    value={pThreshold}
                    onChange={(e) => setPThreshold(e.target.value)}
                    className="font-mono"
                    aria-invalid={!!fieldErrors.p}
                  />
                  {fieldErrors.p ? (
                    <p className="text-xs text-destructive">{fieldErrors.p}</p>
                  ) : null}
                </div>
                {mode === "gsea" ? (
                  <div className="grid gap-2">
                    <label htmlFor="en-min-genes">
                      {t("tools.enrichment.gsea.minGenesLabel")}
                    </label>
                    <Input
                      id="en-min-genes"
                      type="number"
                      min={1}
                      max={MAX_INPUT_GENES}
                      step={1}
                      value={minGenesRaw}
                      onChange={(e) => setMinGenesRaw(e.target.value)}
                      className="font-mono"
                      aria-invalid={!!fieldErrors.minGenes}
                    />
                    {fieldErrors.minGenes ? (
                      <p className="text-xs text-destructive">{fieldErrors.minGenes}</p>
                    ) : null}
                  </div>
                ) : null}
              </div>

              <div className="flex flex-wrap gap-2">
                <Button type="primary" htmlType="submit" disabled={enrichMutation.isPending}>
                  {enrichMutation.isPending ? (
                    <LoadingOutlined className="size-4 animate-spin" aria-hidden />
                  ) : (
                    <CaretRightOutlined className="size-4" aria-hidden />
                  )}
                  {t("tools.enrichment.submit")}
                </Button>
                <Button htmlType="button" onClick={onClear}>
                  <RedoOutlined className="size-4" aria-hidden />
                  {t("common.clear")}
                </Button>
              </div>
            </form>
          </div>
        </Card>

        <div className="grid gap-6">
          {enrichMutation.isError ? (
            <Result
              status="error"
              title={t("tools.enrichment.errorTitle")}
              subTitle={(enrichMutation.error as Error).message}
              extra={
                <Button type="primary" onClick={() => enrichMutation.mutate()}>
                  {t("common.retry")}
                </Button>
              }
            />
          ) : null}

          {!result && !enrichMutation.isError ? (
            <Card>
              <Empty
                description={
                  <>
                    <p className="font-medium">{t("tools.enrichment.emptyTitle")}</p>
                    <p className="text-sm text-muted-foreground">{t("tools.enrichment.emptyDesc")}</p>
                  </>
                }
              />
            </Card>
          ) : null}

          {result ? (
            <Card>
              <div className="mb-5">
                <Typography.Title level={5} style={{ margin: 0 }}>{t("tools.enrichment.summaryTitle")}</Typography.Title>
                <Typography.Text type="secondary">
                  {isGsea
                    ? t("tools.enrichment.gsea.summaryDesc", {
                        input: result.input_genes,
                        background: result.background_genes,
                      })
                    : t("tools.enrichment.summaryDesc", {
                        input: result.input_genes,
                        background: result.background_genes,
                      })}
                </Typography.Text>
              </div>
              <div className="grid gap-3">
                <div className="flex flex-wrap gap-2">
                  <Tag>{result.ontology.toUpperCase()}</Tag>
                  <Tag>{isGsea ? "GSEA" : "ORA"}</Tag>
                  <Tag>
                    {t("tools.enrichment.termsBadge", { count: terms.length })}
                  </Tag>
                </div>
                {result.message ? (
                  <p className="rounded-lg border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
                    {result.message}
                  </p>
                ) : null}
              </div>
            </Card>
          ) : null}
        </div>
      </div>

      {result ? (
        <section className="mt-10 grid gap-6">
          {terms.length === 0 ? (
            <Empty
              image={
                isGsea ? (
                  <RiseOutlined style={{ fontSize: 40, color: "var(--muted-foreground)" }} />
                ) : (
                  <NodeIndexOutlined style={{ fontSize: 40, color: "var(--muted-foreground)" }} />
                )
              }
              description={
                <>
                  <p className="font-medium">{t("tools.enrichment.noTermsTitle")}</p>
                  <p className="text-sm text-muted-foreground">{t("tools.enrichment.noTermsDesc")}</p>
                </>
              }
            />
          ) : (
            <>
              <Card>
                <div className="mb-5">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <Typography.Title level={5} style={{ margin: 0 }}>{t("tools.enrichment.gsea.chartTitle")}</Typography.Title>
                      <Typography.Text type="secondary">{t("tools.enrichment.gsea.chartDesc")}</Typography.Text>
                    </div>
                    <Tabs
                      activeKey={chartView}
                      onChange={(v) => setChartView(v as "bubble" | "bar")}
                      items={[
                        { key: "bubble", label: t("tools.enrichment.gsea.chartBubble") },
                        { key: "bar", label: t("tools.enrichment.gsea.chartBar") },
                      ]}
                    />
                  </div>
                  {isGsea ? (
                    <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
                      <span className="inline-flex items-center gap-1.5">
                        <span
                          className="inline-block size-2.5 rounded-full"
                          style={{ backgroundColor: "var(--chart-1)" }}
                          aria-hidden
                        />
                        {t("tools.enrichment.gsea.chartLegendUp")}
                      </span>
                      <span className="inline-flex items-center gap-1.5">
                        <span
                          className="inline-block size-2.5 rounded-full"
                          style={{ backgroundColor: "var(--impact-low)" }}
                          aria-hidden
                        />
                        {t("tools.enrichment.gsea.chartLegendDown")}
                      </span>
                    </div>
                  ) : null}
                </div>
                <div>
                  <EnrichmentSignificanceChart
                    rows={chartRows}
                    isGsea={isGsea}
                    view={chartView}
                  />
                </div>
              </Card>

              <Card>
                <div className="mb-5">
                  <Typography.Title level={5} style={{ margin: 0 }}>{t("tools.enrichment.resultsTitle")}</Typography.Title>
                  <Typography.Text type="secondary">{t("tools.enrichment.resultsDesc")}</Typography.Text>
                </div>
                <div>
                  <DataTable
                    ariaLabel={t("tools.enrichment.resultsTitle")}
                    rowKey={(row) => row.id}
                    data={rows}
                    responsive
                    columns={columns}
                  />
                </div>
              </Card>
            </>
          )}
        </section>
      ) : null}
    </div>
  );
}

/**
 * Significance plot — bubble (x = -log10(q), y = term, radius from the member
 * gene count) or horizontal bar of -log10(q).
 *
 * The contract and its rows come from components/charts/
 * tool-chart-definitions; the numbers behind them live in
 * tool-enrichment-mapping, which is where they are unit-tested.
 */
export function EnrichmentSignificanceChart({
  rows,
  isGsea,
  view,
}: {
  rows: ChartRow[];
  isGsea: boolean;
  view: EnrichmentChartView;
}) {
  const { t } = useTranslation();

  // ToolChartFigure owns the accessible figure, the loading skeleton, the
  // exact-value table and the empty / unavailable states; the definition and
  // the rows are built by the shared tool-chart adapter so the chart's
  // semantics have one home.
  return (
    <ToolChartFigure
      definition={buildEnrichmentChartDefinition(rows, {
        isGsea,
        view,
        axisTitle: t("tools.enrichment.gsea.chartX"),
      })}
      data={buildEnrichmentCanvasData(rows, { isGsea })}
      label={t("tools.enrichment.gsea.chartTitle")}
      description={`${t("tools.enrichment.gsea.chartTitle")}: ${enrichmentDescription(rows)}.`}
      tableColumns={ENRICHMENT_CANVAS_TABLE_COLUMNS}
      tableRow={enrichmentCanvasTableRow}
      height={320}
      tooltipFormatter={enrichmentCanvasTooltipFormatter(isGsea)}
      datumStyle={enrichmentDatumStyle}
    />
  );
}
