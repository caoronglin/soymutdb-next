import * as React from "react";

import type { ChartDefinition } from "./definitions";
import type { ChartDatumStyle } from "./definitions";
import type { ChartInstance } from "./g2-runtime";
import { themeIdentity, type ChartThemeInput } from "./theme";

/**
 * Animation policy.
 *
 * This is an input, not a context. The portal passes what its animation
 * provider already resolved; the admin console, which has no such provider,
 * omits it and gets the default. Nothing here reads app state.
 */
export type ChartAnimationIntensity = "off" | "minimal" | "standard";

export interface ChartAnimationInput {
  /** True when the user asked for reduced motion. Wins over intensity. */
  readonly reduced?: boolean;
  readonly intensity?: ChartAnimationIntensity;
}

export interface ChartTooltipContext {
  readonly datum: Record<string, unknown>;
  readonly definition: ChartDefinition;
}

export type ChartTooltipFormatter = (context: ChartTooltipContext) => string;

/**
 * Formats value-axis tick labels.
 *
 * A prop, not part of ChartDefinition, so the definition stays serializable
 * and a consumer can reuse an existing formatter verbatim (the admin console
 * passes formatFileSize unchanged).
 */
export type ChartAxisFormatter = (value: number) => string;

/** Per-datum style computed by a consumer's own mapping module. */
export type ChartDatumStyleFn = (datum: Record<string, unknown>) => ChartDatumStyle;

/** Lifecycle state, mirrored onto the host element as data-status. */
export type ChartCanvasStatus = "idle" | "loading" | "rendered" | "failed";

export interface ChartCanvasProps<TDatum = Record<string, unknown>> {
  /** The serializable chart contract. */
  definition: ChartDefinition;
  data: readonly TDatum[];
  /** Accessible name for the graphic. */
  label: string;
  /** Longer description of what the chart shows. */
  description?: string;
  height?: number;
  /**
   * Already-resolved theme. Omit it and the canvas reads the portal CSS
   * variables; omit it with no CSS variables present and it uses the built-in
   * fallback. Never required.
   */
  theme?: ChartThemeInput;
  animation?: ChartAnimationInput;
  axisFormatter?: ChartAxisFormatter;
  datumStyle?: ChartDatumStyleFn;
  /**
   * Custom tooltip content. Deliberately a prop and not part of
   * ChartDefinition, so the definition stays serializable.
   */
  tooltipFormatter?: ChartTooltipFormatter;
  /** Called when the engine cannot be loaded or drawn. */
  onFailure?: (error: unknown) => void;
  /** Mirrors the lifecycle, so a consumer can drive its own skeleton. */
  onStatus?: (status: ChartCanvasStatus) => void;
}

const DEFAULT_WIDTH = 440;

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

/** Resolve the animation policy to a single boolean. */
export function shouldAnimate(
  definition: ChartDefinition,
  animation: ChartAnimationInput | undefined,
): boolean {
  if (animation?.reduced || animation?.intensity === "off") return false;
  if (definition.animate !== undefined) return definition.animate;
  if (!animation) return false;
  return true;
}

/**
 * The runtime wrapper.
 *
 * It owns the lazy engine import, creates the chart on a measured element,
 * resizes with the element, and disposes on unmount and on a theme change.
 * A data or definition change updates options in place; only a theme change
 * tears the chart down, because the engine holds the theme as plot state.
 *
 * It renders its own role="img" so it is usable on its own; ChartFigure wraps
 * it with the exact-value table and the empty/unavailable states.
 */
export function ChartCanvas<TDatum = Record<string, unknown>>({
  definition,
  data,
  label,
  description,
  height = 280,
  theme,
  animation,
  axisFormatter,
  datumStyle,
  tooltipFormatter,
  onFailure,
  onStatus,
}: ChartCanvasProps<TDatum>) {
  const host = React.useRef<HTMLDivElement | null>(null);
  const descriptionId = React.useId();
  const [status, setStatus] = React.useState<ChartCanvasStatus>("idle");

  const chartRef = React.useRef<ChartInstance | null>(null);

  // Latest inputs, so changing them never re-runs the create effect.
  const latest = React.useRef({ definition, data, animation, tooltipFormatter, datumStyle });
  latest.current = { definition, data, animation, tooltipFormatter, datumStyle };

  const failRef = React.useRef(onFailure);
  failRef.current = onFailure;

  const themeRef = React.useRef(theme);
  themeRef.current = theme;

  const axisRef = React.useRef(axisFormatter);
  axisRef.current = axisFormatter;

  const hasData = data.length > 0;

  const statusRef = React.useRef(onStatus);
  statusRef.current = onStatus;

  React.useEffect(() => {
    statusRef.current?.(status);
  }, [status]);

  // Stable string identities: consumers legitimately pass inline object
  // literals, so object identity must not drive the lifecycle.
  const definitionKey = JSON.stringify(definition);
  const animationKey = JSON.stringify(animation ?? null);
  const themeKey = themeIdentity(theme);

  React.useEffect(() => {
    if (!hasData || !host.current) {
      setStatus("idle");
      return;
    }

    let disposed = false;
    let observer: ResizeObserver | null = null;
    const element = host.current;

    setStatus("loading");

    void (async () => {
      try {
        const [themeModule, runtime] = await Promise.all([
          import("./theme"),
          import("./g2-runtime"),
        ]);
        if (disposed || !host.current) return;

        const rect = element.getBoundingClientRect();
        const width = Math.max(1, Math.round(rect.width || DEFAULT_WIDTH));
        const resolvedTheme = themeModule.resolveChartTheme(themeRef.current, element);

        const options = runtime.buildChartOptions({
          definition: latest.current.definition,
          data: latest.current.data as readonly Record<string, unknown>[],
          theme: resolvedTheme,
          animate: shouldAnimate(latest.current.definition, latest.current.animation),
          tooltipFormatter: latest.current.tooltipFormatter,
          axisFormatter: axisRef.current,
          datumStyle: latest.current.datumStyle,
        });

        chartRef.current = runtime.createChart(element, width, height, options);
        await chartRef.current.render();
        if (!disposed) setStatus("rendered");
      } catch (error) {
        if (disposed) return;
        console.error("[ChartCanvas] the chart runtime failed", error);
        setStatus("failed");
        failRef.current?.(error);
      }
    })();

    const onResize = () => {
      if (!host.current) return;
      const rect = host.current.getBoundingClientRect();
      const chart = chartRef.current;
      const resized = chart?.resize(Math.max(1, Math.round(rect.width || DEFAULT_WIDTH)), height);
      resized?.catch((error) => {
        if (disposed || chartRef.current !== chart) return;
        console.error("[ChartCanvas] the chart resize failed", error);
        setStatus("failed");
        failRef.current?.(error);
      });
    };
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(onResize);
      observer.observe(element);
    }

    return () => {
      disposed = true;
      observer?.disconnect();
      chartRef.current?.destroy();
      chartRef.current = null;
    };
  }, [hasData, height, themeKey]);

  // Data and definition changes update the existing chart in place.
  React.useEffect(() => {
    const chart = chartRef.current;
    if (!chart || status !== "rendered") return;
    let disposed = false;
    void (async () => {
      try {
        const [themeModule, runtime] = await Promise.all([
          import("./theme"),
          import("./g2-runtime"),
        ]);
        if (disposed || chartRef.current !== chart) return;
        chart.options(
          runtime.buildChartOptions({
            definition: latest.current.definition,
            data: latest.current.data as readonly Record<string, unknown>[],
            theme: themeModule.resolveChartTheme(themeRef.current, host.current),
            animate: shouldAnimate(latest.current.definition, latest.current.animation),
            tooltipFormatter: latest.current.tooltipFormatter,
            axisFormatter: axisRef.current,
            datumStyle: latest.current.datumStyle,
          }),
        );
        await chart.render();
      } catch (error) {
        if (disposed || chartRef.current !== chart) return;
        console.error("[ChartCanvas] the chart update failed", error);
        setStatus("failed");
        failRef.current?.(error);
      }
    })();
    return () => { disposed = true; };
  }, [data, definitionKey, animationKey, status, tooltipFormatter, axisFormatter, datumStyle]);

  return (
    <div
      role="img"
      aria-label={label}
      aria-describedby={description ? descriptionId : undefined}
      style={{ width: "100%", height }}
    >
      {description ? <p id={descriptionId} style={visuallyHidden}>{description}</p> : null}
      <div
        ref={host}
        data-testid="chart-canvas"
        data-status={status}
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
}
