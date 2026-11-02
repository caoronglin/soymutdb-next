import * as React from "react";
import type { EChartsType } from "echarts";
import type { ChartDefinition } from "./definitions";
import { CHART_HEIGHT } from "./definitions";

export interface ChartFigureProps<TDatum = unknown> {
  /** An ECharts option built by the helpers in `./definitions`. */
  definition: ChartDefinition;
  data: readonly TDatum[];
  /** Accessible name for the graphic. */
  label: string;
  /** Longer description of what the chart shows. */
  description?: string;
  /** Column headers for the value table. */
  tableColumns: readonly string[];
  /** Row extractor for the value table: returns the cell strings. */
  tableRow: (datum: TDatum) => readonly string[];
  emptyText?: string;
  height?: number;
}

const visuallyHidden: React.CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0, 0, 0, 0)",
  whiteSpace: "nowrap",
  border: 0,
};

/**
 * One chart plus its exact-value alternative. A runtime failure degrades to
 * the same accessible table instead of taking down the containing route.
 */
export function ChartFigure<TDatum = unknown>({
  definition,
  data,
  label,
  description,
  tableColumns,
  tableRow,
  emptyText = "No data for this selection.",
  height = CHART_HEIGHT,
}: ChartFigureProps<TDatum>) {
  const chartElement = React.useRef<HTMLDivElement | null>(null);
  const chartRef = React.useRef<EChartsType | null>(null);
  const latestDefinition = React.useRef(definition);
  const [chartFailed, setChartFailed] = React.useState(false);
  const descriptionId = React.useId();
  const hasData = data.length > 0;

  latestDefinition.current = definition;

  React.useEffect(() => {
    if (!hasData || chartFailed || !chartElement.current) return;

    let disposed = false;
    let chart: EChartsType | null = null;
    let observer: ResizeObserver | null = null;
    let fallbackResize: (() => void) | null = null;

    void import("echarts")
      .then((echarts) => {
        if (disposed || !chartElement.current) return;
        try {
          chart = echarts.init(chartElement.current, undefined, { renderer: "canvas" });
          chartRef.current = chart;
          chart.setOption(latestDefinition.current, { notMerge: true });
          const resize = () => chart?.resize();
          if (typeof ResizeObserver !== "undefined") {
            observer = new ResizeObserver(resize);
            observer.observe(chartElement.current);
          } else {
            fallbackResize = resize;
            window.addEventListener("resize", fallbackResize);
          }
          chart.resize();
        } catch (error) {
          console.error("[ChartFigure] the chart runtime failed; showing the value table instead", error);
          setChartFailed(true);
        }
      })
      .catch((error: unknown) => {
        if (disposed) return;
        console.error("[ChartFigure] the chart runtime failed; showing the value table instead", error);
        setChartFailed(true);
      });

    return () => {
      disposed = true;
      observer?.disconnect();
      if (fallbackResize) window.removeEventListener("resize", fallbackResize);
      chart?.dispose();
      if (chartRef.current === chart) chartRef.current = null;
    };
  }, [hasData, chartFailed]);

  React.useEffect(() => {
    const chart = chartRef.current;
    if (!chart || chartFailed || !hasData) return;
    try {
      chart.setOption(definition, { notMerge: true });
    } catch (error) {
      console.error("[ChartFigure] the chart update failed; showing the value table instead", error);
      setChartFailed(true);
    }
  }, [definition, chartFailed, hasData]);

  return (
    <figure style={{ margin: 0 }}>
      {hasData && !chartFailed ? (
        <div
          role="img"
          aria-label={label}
          aria-describedby={description ? descriptionId : undefined}
          style={{ width: "100%", height }}
        >
          {description ? <p id={descriptionId} style={visuallyHidden}>{description}</p> : null}
          <div ref={chartElement} style={{ width: "100%", height: "100%" }} />
        </div>
      ) : null}

      {!hasData ? (
        <p
          data-testid="chart-empty"
          style={{ border: "1px dashed currentColor", borderRadius: 6, opacity: 0.7, padding: 24, textAlign: "center" }}
        >
          {emptyText}
        </p>
      ) : null}

      {hasData && chartFailed ? (
        <p
          data-testid="chart-unavailable"
          style={{ border: "1px dashed currentColor", borderRadius: 6, opacity: 0.7, padding: 16, textAlign: "center" }}
        >
          {/* The fallback has no `role="img"` wrapper, so the description the
              chart would have exposed to assistive tech must still be in the
              accessibility tree. */}
          {description ? <span id={descriptionId} style={visuallyHidden}>{description}</span> : null}
          {label} — the graphic could not be drawn; the exact values are listed below.
        </p>
      ) : null}

      <figcaption style={{ marginTop: 8, fontSize: "0.8em", opacity: 0.78 }}>
        {hasData ? (
          <details>
            <summary style={{ cursor: "pointer" }}>Show the values as a table</summary>
            <table data-testid="chart-values" style={{ marginTop: 8, width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
              <thead>
                <tr>
                  {tableColumns.map((column) => <th key={column} scope="col" style={{ padding: "4px 8px" }}>{column}</th>)}
                </tr>
              </thead>
              <tbody>
                {data.map((datum, index) => (
                  <tr key={index} style={{ borderTop: "1px solid currentColor" }}>
                    {tableRow(datum).map((cell, cellIndex) => <td key={cellIndex} style={{ padding: "4px 8px" }}>{cell}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        ) : null}
      </figcaption>
    </figure>
  );
}
