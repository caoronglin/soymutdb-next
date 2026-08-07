/**
 * perf.ts — lightweight Core Web Vitals performance monitoring.
 *
 * Uses PerformanceObserver to collect LCP, FID (INP fallback), and CLS.
 * Reports metrics to the /track.gif beacon endpoint as 'performance' events.
 * Designed to be <1KB gzipped and non-blocking.
 *
 * Usage:
 *   import { initPerfMonitoring } from "~/lib/perf";
 *   initPerfMonitoring({ endpoint: "/track.gif" });
 */

export interface PerfMetric {
  name: "LCP" | "FID" | "INP" | "CLS" | "TTFB" | "FCP";
  value: number;
  rating: "good" | "needs-improvement" | "poor";
  id?: string;
}

export interface PerfMonitorOptions {
  /** Beacon endpoint (1x1 gif or similar). Defaults to /track.gif. */
  endpoint?: string;
  /** Called for each metric (for dev logging or additional processing). */
  onMetric?: (metric: PerfMetric) => void;
  /** Sample rate 0..1 (default 0.1 = 10%). */
  sampleRate?: number;
}

interface FidEntry extends PerformanceEntry {
  processingStart: number;
  startTime: number;
}

/** Web Vitals thresholds per Google's 2024 guidance. */
const THRESHOLDS = {
  LCP: { good: 2500, poor: 4000 },
  FID: { good: 100, poor: 300 },
  INP: { good: 200, poor: 500 },
  CLS: { good: 0.1, poor: 0.25 },
  FCP: { good: 1800, poor: 3000 },
  TTFB: { good: 800, poor: 1800 },
} as const;

function rate(name: PerfMetric["name"], value: number): PerfMetric["rating"] {
  const t = THRESHOLDS[name];
  if (!t) return "good";
  if (value <= t.good) return "good";
  if (value <= t.poor) return "needs-improvement";
  return "poor";
}

/** Send a metric via sendBeacon (non-blocking) or image pixel fallback. */
function send(endpoint: string, metric: PerfMetric): void {
  const payload = {
    event: "performance",
    name: metric.name,
    value: Math.round(metric.value * 1000) / 1000,
    rating: metric.rating,
    id: metric.id,
    url: typeof location !== "undefined" ? location.pathname : "",
    ts: Date.now(),
  };
  const body = JSON.stringify(payload);
  try {
    if (typeof navigator !== "undefined" && "sendBeacon" in navigator) {
      const blob = new Blob([body], { type: "application/json" });
      navigator.sendBeacon(endpoint, blob);
      return;
    }
  } catch {
    /* beacon may fail in some contexts; fall through to image pixel */
  }
  // Fallback: image pixel with query params
  if (typeof document !== "undefined") {
    const img = new Image();
    const params = new URLSearchParams();
    params.set("event", "performance");
    params.set("name", metric.name);
    params.set("value", String(metric.value));
    params.set("rating", metric.rating);
    img.src = `${endpoint}?${params.toString()}`;
  }
}

function createObserver(
  type: string,
  callback: (entries: PerformanceEntryList) => void,
  opts: PerformanceObserverInit = {},
): PerformanceObserver | null {
  if (typeof PerformanceObserver === "undefined") return null;
  try {
    const obs = new PerformanceObserver((list) => callback(list.getEntries()));
    obs.observe({ type, buffered: true, ...opts });
    return obs;
  } catch {
    return null;
  }
}

export function initPerfMonitoring(options: PerfMonitorOptions = {}): () => void {
  const { endpoint = "/track.gif", onMetric, sampleRate = 0.1 } = options;

  // Respect sample rate
  if (Math.random() > sampleRate) return () => {};
  if (typeof window === "undefined") return () => {};

  const observers: PerformanceObserver[] = [];
  const reported = new Set<string>();

  const report = (name: PerfMetric["name"], value: number, id?: string) => {
    const key = id ? `${name}:${id}` : name;
    if (reported.has(key)) return;
    reported.add(key);
    const metric: PerfMetric = { name, value, rating: rate(name, value), id };
    onMetric?.(metric);
    send(endpoint, metric);
  };

  // LCP — takes the last candidate (final render)
  let lcpValue = 0;
  const lcpObs = createObserver("largest-contentful-paint", (entries) => {
    const last = entries[entries.length - 1];
    if (last) lcpValue = last.startTime;
  });
  if (lcpObs) observers.push(lcpObs);

  // Report LCP on user interaction or page hidden (final value)
  const reportLcp = () => {
    if (lcpValue > 0) report("LCP", lcpValue);
  };
  addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") reportLcp();
  }, { once: true });
  addEventListener("pagehide", reportLcp, { once: true });

  // FID — first input delay
  const fidObs = createObserver("first-input", (entries) => {
    for (const entry of entries as FidEntry[]) {
      const value = entry.processingStart - entry.startTime;
      report("FID", value, entry.name);
    }
  });
  if (fidObs) observers.push(fidObs);

  // INP — interaction to next paint (FID successor, Chromium 96+)
  let inpValue = 0;
  try {
    const inpObs = createObserver("event", (entries) => {
      for (const entry of entries as PerformanceEventTiming[]) {
        // Only track discrete interactions, not continuous (like scroll)
        // interactionId is optional in older TS DOM types; cast safely.
        const evtEntry = entry as PerformanceEventTiming & { interactionId?: number };
        if (!evtEntry.interactionId) continue;
        const value = entry.processingStart + entry.duration - entry.startTime;
        if (value > inpValue) inpValue = value;
      }
    }, { durationThreshold: 40, buffered: true } as PerformanceObserverInit);
    if (inpObs) observers.push(inpObs);
  } catch {
    /* event timing with interactionId may not be supported */
  }

  addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && inpValue > 0) {
      report("INP", inpValue);
    }
  }, { once: true });

  // CLS — cumulative layout shift (session-windowed)
  let clsValue = 0;
  let sessionValue = 0;
  let sessionEntries: PerformanceEntry[] = [];
  const clsObs = createObserver("layout-shift", (entries) => {
    for (const entry of entries as Array<PerformanceEntry & { value: number; hadRecentInput: boolean; startTime: number }>) {
      if (entry.hadRecentInput) continue;
      const last = sessionEntries[sessionEntries.length - 1];
      if (last && entry.startTime - last.startTime < 1000 && entry.startTime - sessionEntries[0].startTime < 5000) {
        sessionValue += entry.value;
        sessionEntries.push(entry);
      } else {
        sessionValue = entry.value;
        sessionEntries = [entry];
      }
      if (sessionValue > clsValue) clsValue = sessionValue;
    }
  });
  if (clsObs) observers.push(clsObs);

  addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") report("CLS", clsValue);
  }, { once: true });

  // FCP — first contentful paint
  const fcpObs = createObserver("paint", (entries) => {
    for (const entry of entries) {
      if (entry.name === "first-contentful-paint") {
        report("FCP", entry.startTime);
      }
    }
  });
  if (fcpObs) observers.push(fcpObs);

  // TTFB from navigation timing
  try {
    const navEntry = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
    if (navEntry) {
      // Use responseStart if available (network TTFB), else startTime
      const ttfb = navEntry.responseStart || navEntry.fetchStart;
      report("TTFB", ttfb);
    }
  } catch {
    /* navigation timing unavailable */
  }

  // Cleanup function
  return () => {
    for (const obs of observers) {
      try { obs.disconnect(); } catch { /* ignore */ }
    }
  };
}
