/**
 * The tool charts' own figure: a canvas, a loading skeleton, the empty and
 * unavailable states, and the exact-value table.
 *
 * Why this exists instead of ChartFigure: the tools' charts carried a loading
 * skeleton overlay, and ChartFigure does not expose the canvas lifecycle, so a
 * consumer cannot paint one. This wrapper reads the status ChartCanvas already
 * mirrors onto its host (`data-status`) and rebuilds the affordances the tools
 * had before the migration -- skeleton while loading, an accessible table of
 * exact values always, and a text fallback if the engine fails.
 *
 * If the shared package grows an `onStatusChange` prop, the observer below is
 * the only thing that should be replaced; the rest of this file is the same
 * contract ChartFigure already implements.
 */

import * as React from "react";
import { useTranslation } from "react-i18next";

import { ChartCanvas, type ChartAnimationInput, type ChartTooltipFormatter } from "@soymutdb/charts";

export interface ToolChartFigureProps<TDatum extends object> {
  readonly definition: unknown;
  readonly data: readonly TDatum[];
  readonly label: string;
  readonly description?: string;
  readonly tableColumns: readonly string[];
  readonly tableRow: (datum: TDatum) => string[];
  readonly emptyText?: string;
  readonly height?: number;
  readonly tooltipFormatter?: ChartTooltipFormatter;
  readonly datumStyle?: (datum: Record<string, unknown>) => { fill?: string };
  readonly animation?: ChartAnimationInput;
  /** Rendered under the chart; the heatmap puts its colour scale here. */
  readonly footer?: React.ReactNode;
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

/** Track the canvas lifecycle from the status ChartCanvas mirrors on its host. */
function useCanvasStatus(): [React.RefObject<HTMLDivElement | null>, string] {
  const host = React.useRef<HTMLDivElement | null>(null);
  const [status, setStatus] = React.useState("idle");

  const read = React.useCallback(() => {
    const root = host.current;
    const canvas = root?.querySelector('[data-testid="chart-canvas"]');
    const next = canvas?.getAttribute("data-status") ?? "idle";
    setStatus((previous) => (previous === next ? previous : next));
  }, []);

  // Re-read after every render: a remount, or a status the canvas changed
  // without a mutation record, must not leave a stale skeleton on screen.
  React.useEffect(read);

  React.useEffect(() => {
    const root = host.current;
    if (!root) return;
    read();
    if (typeof MutationObserver === "undefined") return;
    const observer = new MutationObserver(read);
    observer.observe(root, { attributes: true, subtree: true, attributeFilter: ["data-status"] });
    return () => observer.disconnect();
  }, [read]);

  return [host, status];
}

export function ToolChartFigure<TDatum extends object>({
  definition,
  data,
  label,
  description,
  tableColumns,
  tableRow,
  emptyText,
  height = 320,
  tooltipFormatter,
  datumStyle,
  animation,
  footer,
}: ToolChartFigureProps<TDatum>) {
  const { t } = useTranslation();
  const resolvedEmptyText = emptyText ?? t("charts.emptySelection");
  const [failed, setFailed] = React.useState(false);
  const [host, status] = useCanvasStatus();
  const hasData = data.length > 0;
  // A definition change must not resurrect a chart that already failed.
  const markFailed = React.useCallback(() => setFailed(true), []);
  const loading = hasData && !failed && status !== "rendered";

  return (
    <figure style={{ margin: 0 }}>
      {hasData && !failed ? (
        <div style={{ position: "relative" }} ref={host}>
          <ChartCanvas<TDatum>
            definition={definition as never}
            data={data as never}
            label={label}
            {...(description ? { description } : {})}
            height={height}
            {...(animation ? { animation } : {})}
            {...(tooltipFormatter ? { tooltipFormatter } : {})}
            {...(datumStyle ? { datumStyle: datumStyle as never } : {})}
            onFailure={markFailed}
          />
          {loading ? (
            <div
              data-testid="chart-skeleton"
              className="skeleton-pulse absolute inset-0 rounded-lg bg-muted/40"
              aria-hidden
            />
          ) : null}
        </div>
      ) : null}

      {!hasData ? (
        <p
          data-testid="chart-empty"
          style={{ border: "1px dashed currentColor", borderRadius: 6, opacity: 0.7, padding: 24, textAlign: "center" }}
        >
          {resolvedEmptyText}
        </p>
      ) : null}

      {hasData && failed ? (
        <p
          data-testid="chart-unavailable"
          style={{ border: "1px dashed currentColor", borderRadius: 6, opacity: 0.7, padding: 16, textAlign: "center" }}
        >
          {description ? <span style={visuallyHidden}>{description}</span> : null}
          {label} {t("charts.renderFallback")}
        </p>
      ) : null}

      {footer}

      <figcaption style={{ marginTop: 8, fontSize: "0.8em", opacity: 0.78 }}>
        {hasData ? (
          <details>
            <summary style={{ cursor: "pointer" }}>{t("charts.valueTableToggle")}</summary>
            <table data-testid="chart-values" style={{ marginTop: 8, width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
              <thead>
                <tr>
                  {tableColumns.map((column) => (
                    <th key={column} scope="col" style={{ padding: "4px 8px" }}>
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.map((datum, index) => (
                  <tr key={index} style={{ borderTop: "1px solid currentColor" }}>
                    {tableRow(datum).map((cell, cellIndex) => (
                      <td key={cellIndex} style={{ padding: "4px 8px" }}>
                        {cell}
                      </td>
                    ))}
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

// ---------------------------------------------------------------------------
// Continuous colour scale
// ---------------------------------------------------------------------------

export interface ToolColorScaleProps {
  /** The full range the control may select within, i.e. the response's range. */
  readonly bounds: readonly [number, number];
  /** The domain currently in force. */
  readonly value: readonly [number, number];
  readonly ramp: readonly [string, string, string];
  readonly onChange: (next: [number, number]) => void;
  readonly format?: (value: number) => string;
  readonly label?: string;
}

/**
 * The heatmap's continuous colour scale, with the draggable ends the ECharts
 * visualMap had.
 *
 * A canvas cannot host an HTML control, so the scale is the consumer's to
 * render -- which is also why the domain is plain React state rather than an
 * engine option: narrowing the ends re-colours the chart immediately, and the
 * exact-value table below is unaffected because it always lists the raw
 * numbers rather than the selected range.
 */
export function ToolColorScale({
  bounds,
  value,
  ramp,
  onChange,
  format = (input) => input.toFixed(2),
  label,
}: ToolColorScaleProps) {
  const { t } = useTranslation();
  const resolvedLabel = label ?? t("charts.colorRange");
  const boundsMin = bounds[0];
  const boundsMax = bounds[1];
  const span = boundsMax - boundsMin;
  const step = span > 0 ? span / 200 : 0.01;
  const low = value[0];
  const high = value[1];
  const gradient = "linear-gradient(90deg, " + ramp[0] + ", " + ramp[1] + ", " + ramp[2] + ")";

  return (
    <div role="group" aria-label={resolvedLabel} style={{ marginTop: 12 }}>
      <div aria-hidden style={{ height: 8, borderRadius: 4, background: gradient }} />
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
        <label htmlFor="tool-color-scale-min" style={{ fontSize: "0.75rem" }}>
          {t("charts.axisMin")}
        </label>
        <input
          id="tool-color-scale-min"
          type="range"
          min={boundsMin}
          max={high}
          step={step}
          value={low}
          aria-label={`${resolvedLabel} ${t("charts.ariaMinimum")}`}
          onChange={(event) => {
            const next = Number(event.target.value);
            // The low end may never cross the high end: a reversed domain is
            // not a selection, it silently hides data instead of selecting it.
            onChange([Math.min(next, high), high]);
          }}
        />
        <label htmlFor="tool-color-scale-max" style={{ fontSize: "0.75rem" }}>
          {t("charts.axisMax")}
        </label>
        <input
          id="tool-color-scale-max"
          type="range"
          min={low}
          max={boundsMax}
          step={step}
          value={high}
          aria-label={`${resolvedLabel} ${t("charts.ariaMaximum")}`}
          onChange={(event) => {
            const next = Number(event.target.value);
            onChange([low, Math.max(next, low)]);
          }}
        />
        <output style={{ fontFamily: "JetBrains Mono, monospace", fontSize: "0.75rem", whiteSpace: "nowrap" }}>
          {format(low)} – {format(high)}
        </output>
      </div>
    </div>
  );
}
