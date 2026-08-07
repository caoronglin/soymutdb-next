/**
 * ExpressionHeatmap — heatmap of FPKM values across genes and libraries.
 * Lazy-loaded via React.lazy in routes that use it.
 */
import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import { useECharts } from "../../lib/use-echarts";
import { ChartEmptyState, cn } from "@soymutdb/ui";

export interface ExpressionHeatmapProps {
  data: Array<{ gene_id: string; library_name: string; fpkm: number }>;
  className?: string;
}

export function ExpressionHeatmap({ data, className }: ExpressionHeatmapProps) {
  const { genes, libraries, seriesData, maxFpkm } = useMemo(() => {
    const geneSet = new Set<string>();
    const libSet = new Set<string>();
    let mx = 0;
    for (const d of data) {
      geneSet.add(d.gene_id);
      libSet.add(d.library_name);
      if (d.fpkm > mx) mx = d.fpkm;
    }
    const genesArr = [...geneSet].sort();
    const libsArr = [...libSet].sort();
    const sData = data.map((d) => [libsArr.indexOf(d.library_name), genesArr.indexOf(d.gene_id), d.fpkm] as [number, number, number]);
    return { genes: genesArr, libraries: libsArr, seriesData: sData, maxFpkm: mx };
  }, [data]);

  const option: EChartsOption = {
    tooltip: {
      position: "top",
      formatter: (params) => {
        const p = params as unknown as { value: [number, number, number] };
        const lib = libraries[p.value[0]] ?? "";
        const gene = genes[p.value[1]] ?? "";
        return `${gene}<br/>${lib}<br/><strong>${p.value[2].toFixed(2)} FPKM</strong>`;
      },
    },
    grid: {
      left: genes.length > 1 ? 120 : 60,
      right: 60,
      top: 8,
      bottom: 80,
    },
    xAxis: {
      type: "category",
      data: libraries,
      splitArea: { show: true },
      axisLabel: {
        fontSize: 10,
        color: "var(--muted-foreground)",
        rotate: libraries.length > 6 ? 45 : 0,
        interval: 0,
        overflow: "truncate",
        width: 80,
      },
      axisLine: { lineStyle: { color: "var(--border)" } },
    },
    yAxis: {
      type: "category",
      data: genes,
      splitArea: { show: true },
      axisLabel: {
        fontSize: 10,
        color: "var(--foreground)",
        fontFamily: "JetBrains Mono, monospace",
      },
      axisLine: { lineStyle: { color: "var(--border)" } },
    },
    visualMap: {
      min: 0,
      max: maxFpkm || 1,
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      textStyle: { fontSize: 10, color: "var(--muted-foreground)" },
      inRange: {
        color: ["var(--chart-5)", "var(--chart-3)", "var(--chart-1)"],
      },
    },
    series: [
      {
        name: "FPKM",
        type: "heatmap",
        data: seriesData,
        label: {
          show: libraries.length * genes.length <= 50,
          fontSize: 10,
          color: "var(--foreground)",
        },
        emphasis: {
          itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,0.15)" },
        },
      },
    ],
  };

  const { ref, loading } = useECharts(option, [data]);

  return (
    <figure className={cn("relative", className)}>
      <div
        ref={ref}
        className="h-80 w-full"
        role="img"
        aria-label="Expression heatmap of FPKM values across genes and libraries"
      />
      {loading ? (
        <div className="skeleton-pulse absolute inset-0 rounded-lg bg-muted/40" aria-hidden />
      ) : null}
      <ChartEmptyState visible={data.length === 0 && !loading} />
      <figcaption className="sr-only">
        Expression heatmap: {data.length} data points across {genes.length} genes and{" "}
        {libraries.length} libraries.
      </figcaption>
    </figure>
  );
}

export default ExpressionHeatmap;
