/**
 * useECharts — lazy-loaded ECharts hook with CSS variable resolution.
 *
 * ECharts canvas renderer cannot resolve CSS `var(--xxx)` colors, so we
 * read the computed values from the document and substitute them into
 * the option before calling setOption.
 *
 * The hook also re-renders on theme / animation intensity changes.
 */
import * as React from "react";
import type { EChartsOption } from "echarts";
import { useTheme } from "../lib/theme-provider";
import { useAnimation } from "../lib/animation-context";


export interface ChartPalette {
  background: string;
  foreground: string;
  mutedForeground: string;
  border: string;
  chart1: string;
  chart2: string;
  chart3: string;
  chart4: string;
  chart5: string;
  impactHigh: string;
  impactModerate: string;
  impactLow: string;
  impactModifier: string;
}

/** Read a CSS custom property from :root, with a fallback. */
function readVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** Build a palette by reading CSS variables from the document. */
function buildPalette(): ChartPalette {
  return {
    background: readVar("--background", "#FBFCFB"),
    foreground: readVar("--foreground", "#1F2A24"),
    mutedForeground: readVar("--muted-foreground", "#6B7A70"),
    border: readVar("--border", "#DDE3DC"),
    chart1: readVar("--chart-1", "oklch(0.55 0.13 151)"),
    chart2: readVar("--chart-2", "oklch(0.68 0.11 150)"),
    chart3: readVar("--chart-3", "oklch(0.78 0.09 148)"),
    chart4: readVar("--chart-4", "oklch(0.86 0.06 146)"),
    chart5: readVar("--chart-5", "oklch(0.45 0.10 155)"),
    impactHigh: readVar("--impact-high", "oklch(0.58 0.21 27)"),
    impactModerate: readVar("--impact-moderate", "oklch(0.72 0.16 65)"),
    impactLow: readVar("--impact-low", "oklch(0.60 0.13 240)"),
    impactModifier: readVar("--impact-modifier", "oklch(0.62 0.02 150)"),
  };
}

export interface UseEChartsResult {
  ref: React.RefObject<HTMLDivElement | null>;
  /** Resolved color palette for use in ECharts options. */
  palette: ChartPalette;
  /** True while the ECharts module is loading. */
  loading: boolean;
}

/**
 * Recursively replace `var(--xxx)` strings in an object with resolved values.
 * This lets chart components reference semantic tokens that ECharts canvas
 * would otherwise ignore.
 */
function resolveVars(obj: unknown, palette: ChartPalette): unknown {
  if (typeof obj === "string") {
    return obj.replace(/var\(([a-z-]+)\)/g, (_match, name: string) => {
      const map: Record<string, string> = {
        "--background": palette.background,
        "--foreground": palette.foreground,
        "--muted-foreground": palette.mutedForeground,
        "--border": palette.border,
        "--chart-1": palette.chart1,
        "--chart-2": palette.chart2,
        "--chart-3": palette.chart3,
        "--chart-4": palette.chart4,
        "--chart-5": palette.chart5,
        "--impact-high": palette.impactHigh,
        "--impact-moderate": palette.impactModerate,
        "--impact-low": palette.impactLow,
        "--impact-modifier": palette.impactModifier,
      };
      return map[name] ?? obj;
    });
  }
  if (Array.isArray(obj)) return obj.map((item) => resolveVars(item, palette));
  if (obj && typeof obj === "object") {
    const result: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(obj)) {
      result[key] = resolveVars(value, palette);
    }
    return result;
  }
  return obj;
}

export function useECharts(option: EChartsOption, deps: React.DependencyList = []): UseEChartsResult {
  const ref = React.useRef<HTMLDivElement | null>(null);
  const chartRef = React.useRef<import("echarts").EChartsType | null>(null);
  const initialisedRef = React.useRef(false);
  const [loading, setLoading] = React.useState(true);
  // The option effect needs a signal when lazy ECharts initialization finishes.
  const [chartReady, setChartReady] = React.useState(0);
  const { theme } = useTheme();
  const { reduced, intensity, durationSlow } = useAnimation();
  const palette = React.useMemo(() => {
    // Theme is the invalidation signal; colors are read from CSS variables.
    void theme;
    return buildPalette();
  }, [theme]);

  // Initialise the chart instance once the lazy module loads. The cleanup is
  // owned by this effect (not an ignored async-IIFE return value), so observers
  // and chart canvases cannot survive a route/theme change.
  React.useEffect(() => {
    let disposed = false;
    let chart: import("echarts").EChartsType | null = null;
    let observer: ResizeObserver | null = null;
    let fallbackResize: (() => void) | null = null;
    initialisedRef.current = false;

    void (async () => {
      const echarts = await import("echarts");
      if (disposed || !ref.current) return;
      chart = echarts.init(ref.current, theme === "dark" ? "dark" : undefined, {
        renderer: "canvas",
      });
      chartRef.current = chart;
      const resize = () => chart?.resize();
      if (typeof ResizeObserver !== "undefined") {
        observer = new ResizeObserver(resize);
        observer.observe(ref.current);
      } else {
        fallbackResize = resize;
        window.addEventListener("resize", fallbackResize);
      }
      chart.resize();
      setLoading(false);
      setChartReady((version) => version + 1);
    })();

    return () => {
      disposed = true;
      observer?.disconnect();
      if (fallbackResize) window.removeEventListener("resize", fallbackResize);
      chart?.dispose();
      if (chartRef.current === chart) chartRef.current = null;
      initialisedRef.current = false;
    };
  }, [theme]);

  // Apply option when it changes — resolve CSS vars first.
  React.useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const resolved = resolveVars(option, palette) as EChartsOption;

    // Detect empty data arrays to avoid ECharts animation interpolation crash.
    // When series data transitions between empty and populated states,
    // interpolate1DArray receives undefined and throws "Cannot read properties
    // of undefined (reading 'length')". Using notMerge:true replaces the option
    // entirely, bypassing the animation interpolation path.
    const seriesArr = (resolved.series ?? []) as Array<{ data?: unknown[] }>;
    const hasEmptyData = seriesArr.some((s) => !s.data || s.data.length === 0);
    const notMerge = !initialisedRef.current || hasEmptyData;

    const chartDuration =
      intensity === "minimal" ? Math.min(180, durationSlow) : durationSlow;
    const merged: EChartsOption = {
      ...resolved,
      animation: !reduced,
      animationDuration: reduced ? 0 : chartDuration,
      animationDurationUpdate: reduced ? 0 : chartDuration,
      animationEasing: "cubicOut",
    };
    chart.setOption(merged, { notMerge });
    initialisedRef.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chartReady, option, palette, reduced, intensity, durationSlow, ...deps]);

  return { ref, palette, loading };
}
