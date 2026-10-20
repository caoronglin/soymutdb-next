import * as React from "react";

import {
  ChartCanvas,
  type ChartAxisFormatter,
  type ChartAnimationInput,
  type ChartDatumStyleFn,
  type ChartCanvasStatus,
  type ChartTooltipFormatter,
} from "./ChartCanvas";
import type { ChartDefinition } from "./definitions";
import { CHART_HEIGHT } from "./definitions";
import type { ChartThemeInput } from "./theme";

export interface ChartFigureProps<TDatum = Record<string, unknown>> {
  /** The serializable chart contract built by the helpers in ./definitions. */
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
  /** Already-resolved theme; see ChartCanvas. Never required. */
  theme?: ChartThemeInput;
  animation?: ChartAnimationInput;
  /** Formats value-axis tick labels; pass formatFileSize unchanged. */
  axisFormatter?: ChartAxisFormatter;
  datumStyle?: ChartDatumStyleFn;
  /**
   * Mirrors the canvas lifecycle so a consumer can drive its own loading
   * skeleton. The facade does not render a skeleton, so without this the
   * consumer would have to poll the DOM.
   */
  onStatusChange?: (status: ChartCanvasStatus) => void;
  tooltipFormatter?: ChartTooltipFormatter;
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
 * One chart plus its exact-value alternative.
 *
 * The accessibility contract is unchanged from the previous implementation:
 * role="img" with aria-label and aria-describedby, a details/summary table of
 * exact values, and the chart-empty / chart-unavailable / chart-values test
 * ids. A runtime failure degrades to the same accessible table instead of
 * taking down the containing route.
 */
export function ChartFigure<TDatum = Record<string, unknown>>({
  definition,
  data,
  label,
  description,
  tableColumns,
  tableRow,
  emptyText = "No data for this selection.",
  height = CHART_HEIGHT,
  theme,
  animation,
  axisFormatter,
  datumStyle,
  onStatusChange,
  tooltipFormatter,
}: ChartFigureProps<TDatum>) {
  const [chartFailed, setChartFailed] = React.useState(false);
  const descriptionId = React.useId();
  const hasData = data.length > 0;

  // A definition change must not resurrect a chart that already failed; the
  // failure is sticky for the life of the mounted figure.
  const markFailed = React.useCallback(() => setChartFailed(true), []);

  return (
    <figure style={{ margin: 0 }}>
      {hasData && !chartFailed ? (
        <ChartCanvas<TDatum>
          definition={definition}
          data={data}
          label={label}
          {...(description ? { description } : {})}
          height={height}
          {...(theme ? { theme } : {})}
          {...(animation ? { animation } : {})}
          {...(axisFormatter ? { axisFormatter } : {})}
          {...(datumStyle ? { datumStyle } : {})}
          {...(onStatusChange ? { onStatus: onStatusChange } : {})}
          {...(tooltipFormatter ? { tooltipFormatter } : {})}
          onFailure={markFailed}
        />
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
          {/* The fallback has no role="img" wrapper, so the description the
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
