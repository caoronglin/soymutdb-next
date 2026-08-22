/**
 * ExpPattern tool — gene × condition expression matrix with optional row
 * clustering, rendered as an ECharts heatmap (lazy-loaded via useECharts)
 * plus a raw matrix table.
 *
 * POST /api/v1/tools/exppattern: 1–50 genes, ≤200 conditions, rows are
 * z-scored by default and can be reordered by clustering. The returned
 * matrix is already in display order (see `row_order`).
 */
import { createFileRoute } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import { Activity, Play, Loader2, RotateCcw } from "lucide-react";
import {
  PageHeader,
  Card,
  CardHeader,
  CardContent,
  CardTitle,
  CardDescription,
  Label,
  Textarea,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
  Button,
  Badge,
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
  ErrorState,
  EmptyState,
  ToastProvider,
  useToast,
} from "../../lib/web-ui";
import { useECharts } from "../../lib/use-echarts";
import { runExpPattern, type ExpPatternResponse } from "./api";

export const Route = createFileRoute("/tools/exppattern")({
  component: ExpPatternComponent,
});

const MAX_INPUT_GENES = 50;
/** Above this many cells we warn that the heatmap is dense. */
const LARGE_MATRIX_CELLS = 2000;

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

function fmtV(v: number | null): string {
  if (v === null || Number.isNaN(v)) return "—";
  return v.toFixed(2);
}

function ExpPatternComponent() {
  return (
    <ToastProvider>
      <ExpPatternInner />
    </ToastProvider>
  );
}

function ExpPatternInner() {
  const { t } = useTranslation();
  const { success, error } = useToast();

  const [genesRaw, setGenesRaw] = React.useState("");
  const [clusterRows, setClusterRows] = React.useState(false);
  const [scale, setScale] = React.useState<"zscore" | "none">("zscore");
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  const [result, setResult] = React.useState<ExpPatternResponse | null>(null);

  const patternMutation = useMutation({
    mutationFn: () =>
      runExpPattern({
        genes: parseGenes(genesRaw),
        cluster_rows: clusterRows,
        scale,
      }),
    onSuccess: (data) => {
      setResult(data);
      success(
        t("tools.exppattern.toastDone"),
        t("tools.exppattern.toastDoneDesc", { genes: data.genes.length, conds: data.conditions.length }),
      );
    },
    onError: (err: Error) => {
      error(t("tools.exppattern.toastFailed"), err.message);
    },
  });

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    const genes = parseGenes(genesRaw);
    if (genes.length === 0) errs.genes = t("tools.exppattern.errorGenesEmpty");
    else if (genes.length > MAX_INPUT_GENES) errs.genes = t("tools.exppattern.errorGenesMax");
    setFieldErrors(errs);
    if (Object.keys(errs).length > 0) return;
    setResult(null);
    patternMutation.mutate();
  };

  const onClear = () => {
    setGenesRaw("");
    setClusterRows(false);
    setScale("zscore");
    setFieldErrors({});
    setResult(null);
    patternMutation.reset();
  };

  const hasData = !!result && result.conditions.length > 0 && result.matrix.some((row) => row.some((v) => v !== null));
  const cellCount = result ? result.genes.length * result.conditions.length : 0;
  const isLarge = cellCount > LARGE_MATRIX_CELLS;

  return (
    <div className="container-prose section-rhythm">
      <PageHeader
        icon={Activity}
        title={t("tools.exppattern.title")}
        description={t("tools.exppattern.subtitle")}
        breadcrumb={[
          { label: t("tools.title"), href: "/tools" },
          { label: t("tools.exppattern.title") },
        ]}
      />

      <div className="mt-10 grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>{t("tools.exppattern.formTitle")}</CardTitle>
            <CardDescription>{t("tools.exppattern.formDesc")}</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="grid gap-5">
              <div className="grid gap-2">
                <Label htmlFor="ep-genes">{t("tools.exppattern.genesLabel")}</Label>
                <Textarea
                  id="ep-genes"
                  value={genesRaw}
                  onChange={(e) => setGenesRaw(e.target.value)}
                  placeholder={t("tools.exppattern.genesPlaceholder")}
                  className="min-h-[130px] font-mono text-sm"
                  aria-invalid={!!fieldErrors.genes}
                />
                <p className="text-xs text-muted-foreground">{t("tools.exppattern.genesHint")}</p>
                {fieldErrors.genes ? (
                  <p className="text-xs text-destructive">{fieldErrors.genes}</p>
                ) : null}
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-2">
                  <Label htmlFor="ep-scale">{t("tools.exppattern.scaleLabel")}</Label>
                  <Select value={scale} onValueChange={(v) => setScale(v as "zscore" | "none")}>
                    <SelectTrigger id="ep-scale">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="zscore">{t("tools.exppattern.scaleZscore")}</SelectItem>
                      <SelectItem value="none">{t("tools.exppattern.scaleNone")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-end gap-2 pb-1">
                  <label
                    htmlFor="ep-cluster"
                    className="flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-muted/20 px-3 py-2.5 text-sm font-medium transition-colors hover:bg-muted/40"
                  >
                    <input
                      id="ep-cluster"
                      type="checkbox"
                      checked={clusterRows}
                      onChange={(e) => setClusterRows(e.target.checked)}
                      className="size-4 accent-primary"
                    />
                    {t("tools.exppattern.clusterLabel")}
                  </label>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={patternMutation.isPending}>
                  {patternMutation.isPending ? (
                    <Loader2 className="size-4 animate-spin" aria-hidden />
                  ) : (
                    <Play className="size-4" aria-hidden />
                  )}
                  {t("tools.exppattern.submit")}
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
          {patternMutation.isError ? (
            <ErrorState
              title={t("tools.exppattern.errorTitle")}
              message={(patternMutation.error as Error).message}
              onRetry={() => patternMutation.mutate()}
              retryLabel={t("common.retry")}
            />
          ) : null}

          {!result && !patternMutation.isError ? (
            <Card>
              <CardContent className="p-6">
                <EmptyState
                  mode="empty"
                  title={t("tools.exppattern.emptyTitle")}
                  description={t("tools.exppattern.emptyDesc")}
                />
              </CardContent>
            </Card>
          ) : null}

          {result ? (
            <Card>
              <CardHeader>
                <CardTitle>{t("tools.exppattern.summaryTitle")}</CardTitle>
                <CardDescription>
                  {t("tools.exppattern.summaryDesc", {
                    genes: result.genes.length,
                    conds: result.conditions.length,
                  })}
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3">
                <div className="flex flex-wrap gap-2">
                  <Badge variant="secondary">
                    {t("tools.exppattern.clusteringBadge", { method: result.clustering })}
                  </Badge>
                  <Badge variant="secondary">{result.scale === "zscore" ? "z-score" : "raw FPKM"}</Badge>
                  {isLarge ? (
                    <Badge variant="secondary">{t("tools.exppattern.largeBadge")}</Badge>
                  ) : null}
                </div>
                {result.missing_genes.length > 0 ? (
                  <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2">
                    <p className="text-xs font-medium">
                      {t("tools.exppattern.missingTitle", { count: result.missing_genes.length })}
                    </p>
                    <p className="mt-1 flex flex-wrap gap-1">
                      {result.missing_genes.map((g) => (
                        <Badge key={g} variant="secondary" className="font-mono text-[10px]">
                          {g}
                        </Badge>
                      ))}
                    </p>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>

      {result ? (
        <section className="mt-10 grid gap-6">
          {!hasData ? (
            <Card>
              <CardContent className="p-6">
                <EmptyState
                  mode="filtered"
                  icon={Activity}
                  title={t("tools.exppattern.noDataTitle")}
                  description={t("tools.exppattern.noDataDesc")}
                />
              </CardContent>
            </Card>
          ) : (
            <>
              <Card>
                <CardHeader>
                  <CardTitle>{t("tools.exppattern.heatmapTitle")}</CardTitle>
                  <CardDescription>{t("tools.exppattern.heatmapDesc")}</CardDescription>
                </CardHeader>
                <CardContent>
                  {isLarge ? (
                    <p className="mb-3 rounded-lg border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
                      {t("tools.exppattern.largeHint")}
                    </p>
                  ) : null}
                  <ExpPatternHeatmap result={result} />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>{t("tools.exppattern.matrixTitle")}</CardTitle>
                  <CardDescription>{t("tools.exppattern.matrixDesc")}</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="overflow-auto rounded-xl border border-border">
                    <Table className="min-w-max text-xs">
                      <TableHeader>
                        <TableRow>
                          <TableHead className="sticky left-0 z-10 bg-card font-mono">
                            {t("tools.exppattern.geneCol")}
                          </TableHead>
                          {result.conditions.map((c) => (
                            <TableHead key={c} className="max-w-[140px] truncate font-mono">
                              {c}
                            </TableHead>
                          ))}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {result.genes.map((gene, i) => (
                          <TableRow key={gene}>
                            <TableCell className="sticky left-0 z-10 bg-card font-mono font-medium">
                              {gene}
                            </TableCell>
                            {result.conditions.map((c, j) => (
                              <TableCell key={`${gene}-${c}`} align="right" className="font-mono tabular-nums">
                                {fmtV(result.matrix[i]?.[j] ?? null)}
                              </TableCell>
                            ))}
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
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
 * ECharts heatmap — echarts itself is lazy-loaded by useECharts (dynamic
 * import inside the hook), so no static echarts import here.
 */
function ExpPatternHeatmap({ result }: { result: ExpPatternResponse }) {
  const { t } = useTranslation();
  const [min, max] = result.value_range;
  const option: EChartsOption = useMemo(() => {
    const data: [number, number, number][] = [];
    for (let i = 0; i < result.genes.length; i += 1) {
      for (let j = 0; j < result.conditions.length; j += 1) {
        const v = result.matrix[i]?.[j];
        if (v !== null && v !== undefined && !Number.isNaN(v)) {
          data.push([j, i, v]);
        }
      }
    }
    const isZ = result.scale === "zscore";
    return {
      tooltip: {
        position: "top",
        formatter: (params) => {
          const p = params as unknown as { value: [number, number, number] };
          const cond = result.conditions[p.value[0]] ?? "";
          const gene = result.genes[p.value[1]] ?? "";
          return `${gene}<br/>${cond}<br/><strong>${p.value[2].toFixed(2)}</strong>`;
        },
      },
      grid: {
        left: result.genes.length > 1 ? 110 : 70,
        right: 60,
        top: 8,
        bottom: 90,
      },
      xAxis: {
        type: "category",
        data: result.conditions,
        splitArea: { show: true },
        axisLabel: {
          fontSize: 10,
          color: "var(--muted-foreground)",
          rotate: result.conditions.length > 6 ? 45 : 0,
          interval: 0,
          overflow: "truncate",
          width: 80,
        },
        axisLine: { lineStyle: { color: "var(--border)" } },
      },
      yAxis: {
        type: "category",
        data: result.genes,
        splitArea: { show: true },
        axisLabel: {
          fontSize: 10,
          color: "var(--foreground)",
          fontFamily: "JetBrains Mono, monospace",
        },
        axisLine: { lineStyle: { color: "var(--border)" } },
      },
      visualMap: {
        min: min ?? 0,
        max: max ?? 1,
        calculable: true,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        textStyle: { fontSize: 10, color: "var(--muted-foreground)" },
        inRange: {
          // z-scored data centres on 0 (blue → white → green); raw FPKM
          // stays on the green ramp used across the site charts.
          color: isZ
            ? ["var(--impact-low)", "#F6F8F6", "var(--chart-1)"]
            : ["var(--chart-5)", "var(--chart-3)", "var(--chart-1)"],
        },
      },
      series: [
        {
          name: result.scale,
          type: "heatmap",
          data,
          label: {
            show: data.length <= 50,
            fontSize: 10,
            color: "var(--foreground)",
          },
          emphasis: {
            itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,0.15)" },
          },
        },
      ],
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);

  const { ref, loading } = useECharts(option, [result]);

  return (
    <figure className="relative">
      <div
        ref={ref}
        className="h-80 w-full"
        role="img"
        aria-label={t("tools.exppattern.heatmapAria")}
      />
      {loading ? (
        <div className="skeleton-pulse absolute inset-0 rounded-lg bg-muted/40" aria-hidden />
      ) : null}
      <figcaption className="sr-only">
        {t("tools.exppattern.heatmapAria")}: {result.genes.length} genes × {result.conditions.length} conditions.
      </figcaption>
    </figure>
  );
}
