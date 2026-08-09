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
 * Results render as a significance plot (bubble / bar of -log10(q), ECharts
 * lazy-loaded via useECharts) plus the DataTable of enriched terms.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import { Network, Activity, Play, Loader2, RotateCcw } from "lucide-react";
import {
  PageHeader,
  Card,
  CardHeader,
  CardContent,
  CardTitle,
  CardDescription,
  Label,
  Textarea,
  Input,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
  Button,
  Badge,
  DataTable,
  Tabs,
  TabsList,
  TabsTrigger,
  ErrorState,
  EmptyState,
  ToastProvider,
  useToast,
} from "@soymutdb/ui";
import { useECharts } from "../../lib/use-echarts";
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

/** Row shape consumed by the ECharts components. */
interface ChartRow {
  id: string;
  name: string;
  p: number;
  q: number;
  size: number;
  es?: number;
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

function fmtP(v: number): string {
  if (v === 0) return "0";
  if (v < 0.001) return v.toExponential(2);
  return v.toFixed(4);
}

function fmtSigned(v: number | undefined): string {
  if (v === undefined || Number.isNaN(v)) return "–";
  return `${v >= 0 ? "+" : ""}${v.toFixed(3)}`;
}

/** Escape term names for the ECharts HTML tooltip. */
function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** -log10(q), clamped: q=0 (underflow) renders at the 10 ceiling. */
function logQ(q: number): number {
  return q <= 0 ? 10 : Math.min(10, -Math.log10(q));
}

/** Truncated label shared by the y axis and the series data (ECharts
 *  category matching requires identical strings). */
function termLabel(name: string, id: string): string {
  const label = name || id;
  return label.length > 40 ? `${label.slice(0, 40)}…` : label;
}

function EnrichmentComponent() {
  return (
    <ToastProvider>
      <EnrichmentInner />
    </ToastProvider>
  );
}

function EnrichmentInner() {
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

  const enrichMutation = useMutation({
    mutationFn: async (): Promise<EnrichmentResult> => {
      const p = Number(pThreshold);
      if (mode === "gsea") {
        const { pairs } = parseGeneValues(gseaRaw);
        return runEnrichment({
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
  const terms = result?.terms ?? [];
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
                <Badge key={g} variant="secondary" className="font-mono text-[10px]">
                  {g}
                </Badge>
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
                <Badge key={g} variant="secondary" className="font-mono text-[10px]">
                  {g}
                </Badge>
              ))}
            </div>
          ),
        },
      ];

  return (
    <div className="container-prose section-rhythm">
      <PageHeader
        icon={Network}
        title={t("tools.enrichment.title")}
        description={t("tools.enrichment.subtitle")}
        breadcrumb={[
          { label: t("tools.title"), href: "/tools" },
          { label: t("tools.enrichment.title") },
        ]}
      />

      <div className="mt-10 grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>{t("tools.enrichment.formTitle")}</CardTitle>
            <CardDescription>
              {mode === "gsea" ? t("tools.enrichment.gsea.desc") : t("tools.enrichment.formDesc")}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="grid gap-5">
              <div className="grid gap-2">
                <Label>{t("tools.enrichment.modeLabel")}</Label>
                <Tabs value={mode} onValueChange={(v) => onModeChange(v as Mode)}>
                  <TabsList>
                    <TabsTrigger value="ora">{t("tools.enrichment.modeOra")}</TabsTrigger>
                    <TabsTrigger value="gsea">{t("tools.enrichment.modeGsea")}</TabsTrigger>
                  </TabsList>
                </Tabs>
                <p className="text-xs text-muted-foreground">
                  {mode === "gsea"
                    ? t("tools.enrichment.modeGseaDesc")
                    : t("tools.enrichment.modeOraDesc")}
                </p>
              </div>

              {mode === "ora" ? (
                <div className="grid gap-2">
                  <Label htmlFor="en-genes">{t("tools.enrichment.genesLabel")}</Label>
                  <Textarea
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
                  <Label htmlFor="en-gsea-values">{t("tools.enrichment.gsea.valuesLabel")}</Label>
                  <Textarea
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
                  <Label htmlFor="en-ontology">{t("tools.enrichment.ontologyLabel")}</Label>
                  <Select value={ontology} onValueChange={(v) => setOntology(v as "go" | "kegg")}>
                    <SelectTrigger id="en-ontology">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="go">GO</SelectItem>
                      <SelectItem value="kegg">KEGG</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="en-p">{t("tools.enrichment.pLabel")}</Label>
                  <Input
                    id="en-p"
                    type="number"
                    min={0.000001}
                    max={1}
                    step="0.01"
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
                    <Label htmlFor="en-min-genes">
                      {t("tools.enrichment.gsea.minGenesLabel")}
                    </Label>
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
                <Button type="submit" disabled={enrichMutation.isPending}>
                  {enrichMutation.isPending ? (
                    <Loader2 className="size-4 animate-spin" aria-hidden />
                  ) : (
                    <Play className="size-4" aria-hidden />
                  )}
                  {t("tools.enrichment.submit")}
                </Button>
                <Button type="button" variant="outline" onClick={onClear}>
                  <RotateCcw className="size-4" aria-hidden />
                  {t("common.clear")}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <div className="grid gap-6">
          {enrichMutation.isError ? (
            <ErrorState
              title={t("tools.enrichment.errorTitle")}
              message={(enrichMutation.error as Error).message}
              onRetry={() => enrichMutation.mutate()}
              retryLabel={t("common.retry")}
            />
          ) : null}

          {!result && !enrichMutation.isError ? (
            <Card>
              <CardContent className="p-6">
                <EmptyState
                  mode="empty"
                  title={t("tools.enrichment.emptyTitle")}
                  description={t("tools.enrichment.emptyDesc")}
                />
              </CardContent>
            </Card>
          ) : null}

          {result ? (
            <Card>
              <CardHeader>
                <CardTitle>{t("tools.enrichment.summaryTitle")}</CardTitle>
                <CardDescription>
                  {isGsea
                    ? t("tools.enrichment.gsea.summaryDesc", {
                        input: result.input_genes,
                        background: result.background_genes,
                      })
                    : t("tools.enrichment.summaryDesc", {
                        input: result.input_genes,
                        background: result.background_genes,
                      })}
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3">
                <div className="flex flex-wrap gap-2">
                  <Badge variant="secondary">{result.ontology.toUpperCase()}</Badge>
                  <Badge variant="secondary">{isGsea ? "GSEA" : "ORA"}</Badge>
                  <Badge variant="secondary">
                    {t("tools.enrichment.termsBadge", { count: terms.length })}
                  </Badge>
                </div>
                {result.message ? (
                  <p className="rounded-lg border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
                    {result.message}
                  </p>
                ) : null}
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>

      {result ? (
        <section className="mt-10 grid gap-6">
          {terms.length === 0 ? (
            <EmptyState
              mode="filtered"
              icon={isGsea ? Activity : Network}
              title={t("tools.enrichment.noTermsTitle")}
              description={t("tools.enrichment.noTermsDesc")}
            />
          ) : (
            <>
              <Card>
                <CardHeader className="gap-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <CardTitle>{t("tools.enrichment.gsea.chartTitle")}</CardTitle>
                      <CardDescription>{t("tools.enrichment.gsea.chartDesc")}</CardDescription>
                    </div>
                    <Tabs
                      value={chartView}
                      onValueChange={(v) => setChartView(v as "bubble" | "bar")}
                    >
                      <TabsList>
                        <TabsTrigger value="bubble">
                          {t("tools.enrichment.gsea.chartBubble")}
                        </TabsTrigger>
                        <TabsTrigger value="bar">{t("tools.enrichment.gsea.chartBar")}</TabsTrigger>
                      </TabsList>
                    </Tabs>
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
                </CardHeader>
                <CardContent>
                  <EnrichmentSignificanceChart
                    rows={chartRows}
                    isGsea={isGsea}
                    view={chartView}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>{t("tools.enrichment.resultsTitle")}</CardTitle>
                  <CardDescription>{t("tools.enrichment.resultsDesc")}</CardDescription>
                </CardHeader>
                <CardContent>
                  <DataTable
                    ariaLabel={t("tools.enrichment.resultsTitle")}
                    rowKey={(row) => row.id}
                    data={rows}
                    responsive
                    columns={columns}
                  />
                </CardContent>
              </Card>
            </>
          )}
        </section>
      ) : null}
    </div>
  );
}

/**
 * ECharts significance plot — bubble (x = -log10(q), y = term, size = member
 * gene count) or horizontal bar of -log10(q).  echarts itself is lazy-loaded
 * by useECharts (dynamic import inside the hook), so no static echarts
 * import here.
 */
function EnrichmentSignificanceChart({
  rows,
  isGsea,
  view,
}: {
  rows: ChartRow[];
  isGsea: boolean;
  view: "bubble" | "bar";
}) {
  const { t } = useTranslation();

  const option: EChartsOption = useMemo(() => {
    // Most significant term first (top of the y axis).
    const sorted = [...rows].sort((a, b) => a.q - b.q);
    const labels = sorted.map((r) => termLabel(r.name, r.id)).reverse();
    const maxSize = Math.max(1, ...sorted.map((r) => r.size));
    const colorFor = (r: ChartRow): string =>
      isGsea ? (r.es !== undefined && r.es < 0 ? "var(--impact-low)" : "var(--chart-1)") : "var(--chart-2)";

    const tooltipFormatter = (params: unknown) => {
      const p = params as { data: { value: unknown[] } };
      const v = p.data.value;
      const [x, , size, fullName, q, pv, es, nes] = v as [
        number,
        string,
        number,
        string,
        number,
        number,
        number | null,
        number | null,
      ];
      const lines = [
        `<div style="max-width:320px;font-weight:600;word-break:break-word">${escapeHtml(fullName)}</div>`,
        `<div style="color:var(--muted-foreground);margin-top:2px">-log10(q): <b>${x.toFixed(2)}</b> · q: <b>${fmtP(q)}</b> · p: <b>${fmtP(pv)}</b> · size: <b>${size}</b></div>`,
      ];
      if (isGsea) {
        lines.push(
          `<div style="color:var(--muted-foreground);margin-top:2px">ES: <b>${es === null ? "–" : fmtSigned(es)}</b> · NES: <b>${nes === null ? "–" : fmtSigned(nes)}</b></div>`,
        );
      }
      return lines.join("");
    };

    const baseGrid = { left: 8, right: 24, top: 8, bottom: 44 };
    const yAxis = {
      type: "category" as const,
      data: labels,
      inverse: true,
      axisLabel: {
        fontSize: 10,
        color: "var(--muted-foreground)",
        width: 150,
        overflow: "truncate" as const,
      },
      axisLine: { lineStyle: { color: "var(--border)" } },
    };
    const xAxis = {
      type: "value" as const,
      name: t("tools.enrichment.gsea.chartX"),
      min: 0,
      nameTextStyle: { fontSize: 10, color: "var(--muted-foreground)" },
      axisLabel: { fontSize: 10, color: "var(--muted-foreground)" },
      splitLine: { lineStyle: { color: "var(--border)", type: "dashed" as const } },
    };

    if (view === "bubble") {
      return {
        tooltip: { trigger: "item", formatter: tooltipFormatter },
        grid: baseGrid,
        xAxis,
        yAxis,
        series: [
          {
            name: t("tools.enrichment.gsea.chartX"),
            type: "scatter",
            data: sorted.map((r) => ({
              value: [
                logQ(r.q),
                termLabel(r.name, r.id),
                r.size,
                r.name || r.id,
                r.q,
                r.p,
                r.es ?? null,
                null,
              ],
              symbolSize: 8 + 16 * Math.sqrt(r.size / maxSize),
              itemStyle: { color: colorFor(r) },
            })),
          },
        ],
      };
    }

    return {
      tooltip: { trigger: "item", formatter: tooltipFormatter },
      grid: baseGrid,
      xAxis,
      yAxis,
      series: [
        {
          name: t("tools.enrichment.gsea.chartX"),
          type: "bar",
          barWidth: "60%",
          data: sorted.map((r) => ({
            value: [logQ(r.q), termLabel(r.name, r.id), r.size, r.name || r.id, r.q, r.p, r.es ?? null, null],
            itemStyle: { color: colorFor(r), borderRadius: [0, 2, 2, 0] },
          })),
        },
      ],
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, isGsea, view, t]);

  const { ref, loading } = useECharts(option, [rows, isGsea, view]);

  return (
    <figure className="relative">
      <div
        ref={ref}
        className="h-80 w-full"
        role="img"
        aria-label={t("tools.enrichment.gsea.chartTitle")}
      />
      {loading ? (
        <div className="skeleton-pulse absolute inset-0 rounded-lg bg-muted/40" aria-hidden />
      ) : null}
      <figcaption className="sr-only">
        {t("tools.enrichment.gsea.chartTitle")}:{" "}
        {rows.map((r) => `${r.name || r.id} ${logQ(r.q).toFixed(2)} ${r.size}`).join(", ")}.
      </figcaption>
    </figure>
  );
}
