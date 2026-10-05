/**
 * ExpressionHeatmap — heatmap of FPKM values across genes and libraries.
 * Lazy-loaded via React.lazy in routes that use it.
 */
import { useTranslation } from "react-i18next";
import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import { useECharts } from "../../lib/use-echarts";
import { Empty } from "@/lib/antd";
import { cn } from "@/lib/cn";

export interface ExpressionHeatmapProps {
  data: Array<{ gene_id: string; library_name: string; fpkm: number }>;
  className?: string;
}

export function ExpressionHeatmap({ data, className }: ExpressionHeatmapProps) {  const { t } = useTranslation();

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
    const geneIndex = new Map(genesArr.map((gene, index) => [gene, index]));
    const libraryIndex = new Map(libsArr.map((library, index) => [library, index]));
    const sData = data.map(
      (datum) =>
        [
          libraryIndex.get(datum.library_name) ?? 0,
          geneIndex.get(datum.gene_id) ?? 0,
          datum.fpkm,
        ] as [number, number, number],
    );
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
        aria-label={t("charts.heatmapTitle")}
      />
      {loading ? (
        <div className="skeleton-pulse absolute inset-0 rounded-lg bg-muted/40" aria-hidden />
      ) : null}
      {data.length === 0 && !loading ? <Empty className="absolute inset-0 flex items-center justify-center" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : null}
      <figcaption className="sr-only">
        {t("charts.heatmapDescription", { points: data.length, genes: genes.length, libraries: libraries.length })}
      </figcaption>
    </figure>
  );
}

export default ExpressionHeatmap;
