import { getReleaseId } from "@soymutdb/api-client";
import { SITE_VARIANT } from "../../lib/site-variant";
import { assembliesQueryOptions } from "../../lib/query-options";
/**
 * ExpPattern tool — gene × condition expression matrix with optional row
 * clustering, rendered as an ECharts heatmap (lazy-loaded via useECharts)
 * plus a raw matrix table.
 *
 * POST /api/v1/tools/exppattern: 1–50 genes, ≤200 conditions, rows are
 * z-scored by default and can be reordered by clustering. The returned
 * matrix is already in display order (see `row_order`).
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import { RiseOutlined, CaretRightOutlined, LoadingOutlined, RedoOutlined } from "@ant-design/icons";
import {
  Breadcrumb,
  Button,
  Card,
  Checkbox,
  Empty,
  Input,
  Result,
  Select,
  Table,
  Tag,
  Typography,
} from "@/lib/antd";
import { useToast } from "../../lib/toast";
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
  return <ExpPatternInner />;
}

function ExpPatternInner() {
  const { t } = useTranslation();
  const { success, error } = useToast();

  const [genesRaw, setGenesRaw] = React.useState("");
  const [clusterRows, setClusterRows] = React.useState(false);
  const [scale, setScale] = React.useState<"zscore" | "none">("zscore");
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  const [result, setResult] = React.useState<ExpPatternResponse | null>(null);
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

  const patternMutation = useMutation({
    mutationFn: () =>
      runExpPattern({
        assembly_id: Number(assemblyId),
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
    if (!assemblyId) errs.assembly = t("tools.exppattern.errorAssemblyRequired");
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
      <header className="flex flex-col gap-4">
        <Breadcrumb
          items={[
            { title: <Link to="/tools">{t("tools.title")}</Link> },
            { title: t("tools.exppattern.title") },
          ]}
        />
        <div className="flex items-start gap-3.5">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-border bg-card shadow-sm">
            <RiseOutlined className="size-5" aria-hidden />
          </span>
          <div>
            <Typography.Title level={2} style={{ margin: 0 }}>
              {t("tools.exppattern.title")}
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
              {t("tools.exppattern.subtitle")}
            </Typography.Paragraph>
          </div>
        </div>
      </header>

      <div className="mt-10 grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <Card
          title={
            <>
              <Typography.Title level={5} style={{ margin: 0 }}>
                {t("tools.exppattern.formTitle")}
              </Typography.Title>
              <Typography.Text type="secondary">{t("tools.exppattern.formDesc")}</Typography.Text>
            </>
          }
        >
          <form onSubmit={onSubmit} className="grid gap-5">
            <div className="grid gap-2">
              <label htmlFor="ep-assembly" className="text-sm font-medium">{t("tools.exppattern.assemblyLabel")}</label>
               <Select
                 id="ep-assembly"
                 value={assemblyId || undefined}
                 onChange={(value) => {
                   setAssemblyId(value);
                   setResult(null);
                   setFieldErrors({});
                   patternMutation.reset();
                 }}
                 placeholder={t("tools.exppattern.assemblyPlaceholder")}
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
                   ? t("tools.exppattern.assembliesError")
                   : t("tools.exppattern.assemblyHelp")}
               </p>
               {fieldErrors.assembly ? (
                 <p className="text-xs text-destructive">{fieldErrors.assembly}</p>
               ) : null}
             </div>

             <div className="grid gap-2">
               <label htmlFor="ep-genes" className="text-sm font-medium">
                {t("tools.exppattern.genesLabel")}
              </label>
              <Input.TextArea
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
                <label htmlFor="ep-scale" className="text-sm font-medium">
                  {t("tools.exppattern.scaleLabel")}
                </label>
                <Select
                  id="ep-scale"
                  value={scale}
                  onChange={(v) => setScale(v as "zscore" | "none")}
                  options={[
                    { value: "zscore", label: t("tools.exppattern.scaleZscore") },
                    { value: "none", label: t("tools.exppattern.scaleNone") },
                  ]}
                />
              </div>
              <div className="flex items-end gap-2 pb-1">
                <Checkbox
                  id="ep-cluster"
                  checked={clusterRows}
                  onChange={(e) => setClusterRows(e.target.checked)}
                  className="rounded-lg border border-border bg-muted/20 px-3 py-2.5 text-sm font-medium transition-colors hover:bg-muted/40"
                >
                  {t("tools.exppattern.clusterLabel")}
                </Checkbox>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button type="primary" htmlType="submit" disabled={patternMutation.isPending}>
                {patternMutation.isPending ? (
                  <LoadingOutlined className="size-4 animate-spin" aria-hidden />
                ) : (
                  <CaretRightOutlined className="size-4" aria-hidden />
                )}
                {t("tools.exppattern.submit")}
              </Button>
              <Button htmlType="button" onClick={onClear}>
                <RedoOutlined className="size-4" aria-hidden />
                {t("common.clear")}
              </Button>
            </div>
          </form>
        </Card>

        <div className="grid gap-6">
          {patternMutation.isError ? (
            <Result
              status="error"
              title={t("tools.exppattern.errorTitle")}
              subTitle={(patternMutation.error as Error).message}
              extra={
                <Button type="primary" onClick={() => patternMutation.mutate()}>
                  {t("common.retry")}
                </Button>
              }
            />
          ) : null}

          {!result && !patternMutation.isError ? (
            <Card>
              <Empty
                description={
                  <>
                    <p className="font-medium">{t("tools.exppattern.emptyTitle")}</p>
                    <p className="text-sm text-muted-foreground">{t("tools.exppattern.emptyDesc")}</p>
                  </>
                }
              />
            </Card>
          ) : null}

          {result ? (
            <Card
              title={
                <>
                  <Typography.Title level={5} style={{ margin: 0 }}>
                    {t("tools.exppattern.summaryTitle")}
                  </Typography.Title>
                  <Typography.Text type="secondary">
                    {t("tools.exppattern.summaryDesc", {
                      genes: result.genes.length,
                      conds: result.conditions.length,
                    })}
                  </Typography.Text>
                </>
              }
            >
              <div className="grid gap-3">
                <div className="flex flex-wrap gap-2">
                  <Tag>{t("tools.exppattern.clusteringBadge", { method: result.clustering })}</Tag>
                  <Tag>{result.scale === "zscore" ? t("tools.exppattern.scaleZscore") : t("tools.exppattern.scaleRawFpkm")}</Tag>
                  {isLarge ? <Tag>{t("tools.exppattern.largeBadge")}</Tag> : null}
                </div>
                {result.missing_genes.length > 0 ? (
                  <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2">
                    <p className="text-xs font-medium">
                      {t("tools.exppattern.missingTitle", { count: result.missing_genes.length })}
                    </p>
                    <p className="mt-1 flex flex-wrap gap-1">
                      {result.missing_genes.map((g) => (
                        <Tag key={g} className="font-mono text-[10px]">
                          {g}
                        </Tag>
                      ))}
                    </p>
                  </div>
                ) : null}
              </div>
            </Card>
          ) : null}
        </div>
      </div>

      {result ? (
        <section className="mt-10 grid gap-6">
          {!hasData ? (
            <Card>
              <Empty
                image={<RiseOutlined style={{ fontSize: 40, color: "var(--muted-foreground)" }} />}
                description={
                  <>
                    <p className="font-medium">{t("tools.exppattern.noDataTitle")}</p>
                    <p className="text-sm text-muted-foreground">{t("tools.exppattern.noDataDesc")}</p>
                  </>
                }
              />
            </Card>
          ) : (
            <>
              <Card
                title={
                  <>
                    <Typography.Title level={5} style={{ margin: 0 }}>
                      {t("tools.exppattern.heatmapTitle")}
                    </Typography.Title>
                    <Typography.Text type="secondary">{t("tools.exppattern.heatmapDesc")}</Typography.Text>
                  </>
                }
              >
                {isLarge ? (
                  <p className="mb-3 rounded-lg border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
                    {t("tools.exppattern.largeHint")}
                  </p>
                ) : null}
                <ExpPatternHeatmap result={result} />
              </Card>

              <Card
                title={
                  <>
                    <Typography.Title level={5} style={{ margin: 0 }}>
                      {t("tools.exppattern.matrixTitle")}
                    </Typography.Title>
                    <Typography.Text type="secondary">{t("tools.exppattern.matrixDesc")}</Typography.Text>
                  </>
                }
              >
                {/* antd's Table owns the frozen gene column (`fixed: "left"`)
                    and the horizontal scroll the matrix needs. */}
                <Table<{ gene: string; index: number }>
                  size="small"
                  bordered
                  rowKey="gene"
                  pagination={false}
                  scroll={{ x: "max-content" }}
                  dataSource={result.genes.map((gene, index) => ({ gene, index }))}
                  columns={[
                    {
                      title: t("tools.exppattern.geneCol"),
                      dataIndex: "gene",
                      key: "gene",
                      fixed: "left",
                      render: (gene: string) => <span className="font-mono font-medium">{gene}</span>,
                    },
                    ...result.conditions.map((condition, j) => ({
                      title: <span className="font-mono">{condition}</span>,
                      key: `c${j}`,
                      align: "right" as const,
                      render: (_: unknown, row: { gene: string; index: number }) => (
                        <span className="font-mono tabular-nums">
                          {fmtV(result.matrix[row.index]?.[j] ?? null)}
                        </span>
                      ),
                    })),
                  ]}
                />
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
        {t("tools.exppattern.heatmapAria", { genes: result.genes.length, conditions: result.conditions.length })}
      </figcaption>
    </figure>
  );
}
