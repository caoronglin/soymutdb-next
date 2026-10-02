/**
 * GenomeBrowserWidget — embeddable genome browser widget for dashboard layouts.
 *
 * Can operate in two modes:
 *   1. iframe mode: wraps JBrowse 2 in a sandboxed iframe (full-featured).
 *   2. linear mode: lightweight SVG-based linear view with gene density
 *      histogram, zoom/pan controls — no iframe needed (fast, data-saver).
 *
 * Features:
 *   - Position display: Chr:Start-End (e.g., chr01:1,000,000-2,000,000)
 *   - Zoom controls (in / out / reset) with smooth transitions
 *   - Gene density histogram rendered as SVG bars
 *   - View transitions via CSS View Transitions API when region changes
 *   - Respects prefers-reduced-motion and navigator.connection?.saveData
 *   - Passive wheel/touch listeners for scroll performance
 *   - SSR/SSG fallback visible (noscript-friendly)
 *
 * Intended for use in admin widget layouts and the homepage dashboard,
 * not the full /browser route (which has its own embed).
 */
import * as React from "react";
import { ZoomInOutlined, ZoomOutOutlined, ExpandOutlined, ExportOutlined, LoadingOutlined, AimOutlined, ExclamationCircleOutlined } from "@ant-design/icons";
import { cn } from "@/lib/cn";
import { Button } from "@/lib/antd";
import { useAnimation } from "../lib/animation-context";
import { buildJbrowseLocusUrl, isMinimalDeploymentMode, resolveJbrowseBaseUrl } from "../lib/deployment";
import { formatPosition, formatMb, CHROMOSOME_LENGTHS_BP } from "../lib/format";
import { getMotionPrefs } from "../lib/motion-prefs";

export interface GenomeBrowserWidgetProps {
  /** Initial chromosome (default: chr01) */
  chromosome?: string;
  /** Initial start position (bp). Defaults to 0. */
  start?: number;
  /** Initial end position (bp). Defaults to 5Mb view. */
  end?: number;
  /** Widget mode. 'iframe' wraps JBrowse; 'linear' is lightweight SVG. */
  mode?: "iframe" | "linear" | "auto";
  /** JBrowse base URL for iframe mode. */
  jbrowseUrl?: string;
  /** Explicit assembly key; iframe mode is disabled when absent. */
  assembly?: string;
  /** Explicit published release pin; iframe mode is disabled when absent. */
  release?: string;
  /** Optional gene density data for histogram mode */
  densityData?: Array<{ position: number; count: number }>;
  /** Called when region changes (for parent-controlled state). */
  onRegionChange?: (region: { chromosome: string; start: number; end: number }) => void;
  /** Show header with position + controls */
  showHeader?: boolean;
  /** Widget height (default: 400px) */
  height?: number | string;
  className?: string;
}

interface Region {
  chromosome: string;
  start: number;
  end: number;
}

const DEFAULT_REGION: Region = {
  chromosome: "chr01",
  start: 0,
  end: 5_000_000,
};

const JBROWSE_BASE = resolveJbrowseBaseUrl(
  typeof import.meta !== "undefined" ? import.meta.env?.VITE_JBROWSE_URL : undefined,
);
const MINIMAL_DEPLOYMENT = isMinimalDeploymentMode(
  typeof import.meta !== "undefined" ? import.meta.env?.VITE_DEPLOYMENT_MODE : undefined,
);

/** Generate deterministic pseudo-density histogram data for demo/fallback. */
function generateDensity(chromosome: string, start: number, end: number, bins = 60): Array<{ position: number; count: number }> {
  // Seed from chromosome name
  let seed = 0;
  for (let i = 0; i < chromosome.length; i++) seed = (seed * 31 + chromosome.charCodeAt(i)) >>> 0;
  const rand = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 0xffffffff;
  };
  const binSize = (end - start) / bins;
  return Array.from({ length: bins }, (_, i) => {
    const pos = start + i * binSize;
    // Create a plausible gene-density pattern: higher near chromosome arms, lower near centromere
    const midpoint = (start + end) / 2;
    const distFromCenter = Math.abs(pos - midpoint) / ((end - start) / 2);
    const base = 10 + distFromCenter * 40;
    const noise = rand() * 20;
    return {
      position: pos,
      count: Math.max(1, Math.floor(base + noise)),
    };
  });
}

export function GenomeBrowserWidget({
  chromosome: initialChr = DEFAULT_REGION.chromosome,
  start: initialStart = DEFAULT_REGION.start,
  end: initialEnd = DEFAULT_REGION.end,
  mode = "auto",
  jbrowseUrl: jbrowseBase = JBROWSE_BASE,
  assembly,
  release,
  densityData,
  onRegionChange,
  showHeader = true,
  height = 400,
  className,
}: GenomeBrowserWidgetProps) {
  const { reduced } = useAnimation();
  const [region, setRegion] = React.useState<Region>({
    chromosome: initialChr,
    start: initialStart,
    end: initialEnd,
  });
  const [iframeLoaded, setIframeLoaded] = React.useState(false);
  const [iframeError, setIframeError] = React.useState(false);
  // Mirrors the load signal for the timeout closure (state would be stale).
  const iframeLoadedRef = React.useRef(false);
  const [hoveredBin, setHoveredBin] = React.useState<{ x: number; y: number; count: number; position: number } | null>(null);
  const linearViewRef = React.useRef<HTMLDivElement | null>(null);
  const histogramRef = React.useRef<SVGSVGElement | null>(null);
  const panStateRef = React.useRef<{ active: boolean; startX: number; startStart: number; startEnd: number }>({
    active: false,
    startX: 0,
    startStart: 0,
    startEnd: 0,
  });

  // Resolve effective mode
  const effectiveMode = React.useMemo<"iframe" | "linear">(() => {
    // Minimal Pages releases do not publish the iframe application; force the
    // existing lightweight implementation rather than trying localhost.
    if (MINIMAL_DEPLOYMENT || !assembly || !release) return "linear";
    if (mode !== "auto") return mode;
    const { saveData, lowPower } = getMotionPrefs();
    return saveData || lowPower ? "linear" : "iframe";
  }, [assembly, mode, release]);

  const chromLength = CHROMOSOME_LENGTHS_BP[region.chromosome] ?? 50_000_000;
  const viewWidth = region.end - region.start;

  const histogram = React.useMemo(() => {
    if (densityData && densityData.length > 0) return densityData;
    return generateDensity(region.chromosome, region.start, region.end);
  }, [densityData, region.chromosome, region.start, region.end]);

  const maxCount = React.useMemo(() => Math.max(...histogram.map((d) => d.count), 1), [histogram]);

  // Smooth region transition via View Transitions API
  const setRegionSmooth = React.useCallback(
    (next: Region) => {
      const apply = () => {
        setRegion(next);
        onRegionChange?.(next);
      };
      if (!reduced && typeof document !== "undefined" && "startViewTransition" in document) {
        try {
          (document as Document & { startViewTransition: (cb: () => void) => unknown }).startViewTransition(apply);
          return;
        } catch {
          /* fall through */
        }
      }
      apply();
    },
    [reduced, onRegionChange],
  );

  const zoomIn = React.useCallback(() => {
    const center = (region.start + region.end) / 2;
    const newWidth = viewWidth / 2;
    setRegionSmooth({
      ...region,
      start: Math.max(0, Math.floor(center - newWidth / 2)),
      end: Math.min(chromLength, Math.ceil(center + newWidth / 2)),
    });
  }, [region, viewWidth, chromLength, setRegionSmooth]);

  const zoomOut = React.useCallback(() => {
    const center = (region.start + region.end) / 2;
    const newWidth = Math.min(chromLength, viewWidth * 2);
    setRegionSmooth({
      ...region,
      start: Math.max(0, Math.floor(center - newWidth / 2)),
      end: Math.min(chromLength, Math.ceil(center + newWidth / 2)),
    });
  }, [region, viewWidth, chromLength, setRegionSmooth]);

  const resetView = React.useCallback(() => {
    setRegionSmooth({
      chromosome: region.chromosome,
      start: 0,
      end: chromLength,
    });
  }, [region.chromosome, chromLength, setRegionSmooth]);

  // Pan with mouse drag (passive listeners where possible)
  React.useEffect(() => {
    const el = linearViewRef.current;
    if (!el || effectiveMode !== "linear") return;

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      // Ctrl/Cmd + wheel = zoom; plain wheel = pan
      if (e.ctrlKey || e.metaKey) {
        const factor = e.deltaY > 0 ? 1.2 : 0.8;
        const center = (region.start + region.end) / 2;
        const newWidth = Math.min(chromLength, Math.max(1000, viewWidth * factor));
        setRegionSmooth({
          ...region,
          start: Math.max(0, Math.floor(center - newWidth / 2)),
          end: Math.min(chromLength, Math.ceil(center + newWidth / 2)),
        });
      } else {
        const delta = (e.deltaY / el.clientWidth) * viewWidth;
        let newStart = region.start + delta;
        let newEnd = region.end + delta;
        if (newStart < 0) {
          newEnd -= newStart;
          newStart = 0;
        }
        if (newEnd > chromLength) {
          newStart -= newEnd - chromLength;
          newEnd = chromLength;
        }
        setRegionSmooth({ ...region, start: Math.max(0, Math.floor(newStart)), end: Math.floor(newEnd) });
      }
    };

    const onMouseDown = (e: MouseEvent) => {
      panStateRef.current = {
        active: true,
        startX: e.clientX,
        startStart: region.start,
        startEnd: region.end,
      };
    };

    const onMouseMove = (e: MouseEvent) => {
      if (!panStateRef.current.active) return;
      const dx = e.clientX - panStateRef.current.startX;
      const delta = -(dx / el.clientWidth) * (panStateRef.current.startEnd - panStateRef.current.startStart);
      let newStart = panStateRef.current.startStart + delta;
      let newEnd = panStateRef.current.startEnd + delta;
      if (newStart < 0) { newEnd -= newStart; newStart = 0; }
      if (newEnd > chromLength) { newStart -= newEnd - chromLength; newEnd = chromLength; }
      setRegion({ ...region, start: Math.max(0, Math.floor(newStart)), end: Math.floor(newEnd) });
    };

    const onMouseUp = () => {
      panStateRef.current.active = false;
      onRegionChange?.(region);
    };

    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("mousedown", onMouseDown);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);

    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [effectiveMode, region, viewWidth, chromLength, setRegionSmooth, onRegionChange]);

  // iframe error timeout
  React.useEffect(() => {
    if (effectiveMode !== "iframe") return;
    iframeLoadedRef.current = false;
    setIframeLoaded(false);
    setIframeError(false);
    const timer = setTimeout(() => {
      if (!iframeLoadedRef.current) setIframeError(true);
    }, 8000);
    return () => clearTimeout(timer);
  }, [effectiveMode, region]);

  const positionLabel = `${region.chromosome}:${formatPosition(region.start)}-${formatPosition(region.end)}`;
  const jbrowseSrc = assembly && release
    ? `${jbrowseBase.replace(/\/$/, "")}/?assembly=${encodeURIComponent(assembly)}&locus=${encodeURIComponent(positionLabel)}&release=${encodeURIComponent(release)}`
    : undefined;
  const fullBrowserHref = assembly && release
    ? buildJbrowseLocusUrl(import.meta.env.BASE_URL, {
        assembly,
        locus: `${region.chromosome}:${Math.max(1, region.start)}-${region.end}`,
        release,
      }).href
    : undefined;

  return (
    <div
      className={cn("flex flex-col overflow-hidden rounded-lg border bg-card", className)}
      data-widget="genome-browser"
      style={{ height }}
    >
      {showHeader && (
        <div className="flex items-center justify-between border-b bg-muted/30 px-3 py-2">
          <div className="flex items-center gap-2">
            <AimOutlined className="size-4 text-primary" aria-hidden />
            <span className="font-mono text-xs tabular-nums text-foreground/80">{positionLabel}</span>
            <span className="text-[10px] text-muted-foreground">({formatMb(viewWidth)})</span>
          </div>
          <div className="flex items-center gap-1">
            <Button
              type="text"
              onClick={zoomIn}
              aria-label="Zoom in"
              title="Zoom in"
              icon={<ZoomInOutlined className="size-4" />}
            />
            <Button
              type="text"
              onClick={zoomOut}
              aria-label="Zoom out"
              title="Zoom out"
              icon={<ZoomOutOutlined className="size-4" />}
            />
            <Button
              type="text"
              onClick={resetView}
              aria-label="Reset view"
              title="Reset view"
              icon={<ExpandOutlined className="size-4" />}
            />
            {effectiveMode === "iframe" && (
              <a
                href={fullBrowserHref}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                aria-label="Open in full browser"
                title="Open in full browser"
              >
                <ExportOutlined className="size-4" />
              </a>
            )}
          </div>
        </div>
      )}

      <div className="relative flex-1 min-h-0">
        {effectiveMode === "iframe" ? (
          <>
            {!iframeLoaded && !iframeError && (
              <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-muted/50">
                <LoadingOutlined className="size-6 animate-spin text-primary" aria-hidden />
                <p className="mt-2 text-xs text-muted-foreground">Loading genome browser…</p>
              </div>
            )}
            {iframeError && (
              <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-card p-4 text-center">
                <ExclamationCircleOutlined className="size-8 text-muted-foreground" />
                <p className="mt-2 text-xs text-muted-foreground">JBrowse unavailable. Using linear view.</p>
                <Button
                  size="small"
                  className="mt-2"
                  onClick={() => { iframeLoadedRef.current = false; setIframeError(false); setIframeLoaded(false); }}
                >
                  Retry
                </Button>
              </div>
            )}
            <iframe
              src={jbrowseSrc}
              title={`Genome browser — ${positionLabel}`}
              className="h-full w-full border-0"
              sandbox="allow-scripts allow-same-origin allow-forms"
              loading="lazy"
              onLoad={() => { iframeLoadedRef.current = true; setIframeLoaded(true); }}
              onError={() => setIframeError(true)}
            />
          </>
        ) : (
          <div
            ref={linearViewRef}
            className="flex h-full cursor-grab flex-col active:cursor-grabbing select-none"
            style={{ touchAction: "none" }}
            role="img"
            aria-label={`Linear genome view: ${positionLabel}`}
          >
            {/* Coordinate ruler */}
            <div className="relative h-6 border-b bg-muted/20 px-1">
              <svg className="h-full w-full" preserveAspectRatio="none" aria-hidden>
                {Array.from({ length: 11 }, (_, i) => {
                  const pos = region.start + (viewWidth * i) / 10;
                  return (
                    <g key={i}>
                      <line
                        x1={`${i * 10}%`}
                        y1={i % 5 === 0 ? 4 : 10}
                        x2={`${i * 10}%`}
                        y2="24"
                        stroke="currentColor"
                        strokeOpacity="0.2"
                        strokeWidth="1"
                      />
                      {i % 2 === 0 && (
                        <text
                          x={`${i * 10}%`}
                          y="8"
                          textAnchor="middle"
                          className="fill-muted-foreground"
                          fontSize="8"
                          fontFamily="var(--font-mono), monospace"
                        >
                          {formatMb(pos).replace(" Mb", "")}
                        </text>
                      )}
                    </g>
                  );
                })}
              </svg>
            </div>

            {/* Chromosome ideogram track (thin) */}
            <div className="relative h-8 border-b px-1">
              <svg className="h-full w-full" viewBox="0 0 600 32" preserveAspectRatio="none" aria-hidden>
                {/* Full chromosome background */}
                <rect x="0" y="10" width="600" height="12" rx="6" fill="oklch(0.86 0.06 146)" />
                {/* Current view indicator */}
                <rect
                  x={(region.start / chromLength) * 600}
                  y="6"
                  width={(viewWidth / chromLength) * 600}
                  height="20"
                  rx="4"
                  fill="oklch(0.55 0.13 151)"
                />
              </svg>
            </div>

            {/* Gene density histogram */}
            <div className="relative flex-1 p-1">
              <svg
                ref={histogramRef}
                className="h-full w-full"
                viewBox={`0 0 ${histogram.length} 100`}
                preserveAspectRatio="none"
                aria-label="Gene density histogram"
              >
                {histogram.map((bin, i) => {
                  const h = (bin.count / maxCount) * 90;
                  return (
                    <rect
                      key={i}
                      x={i}
                      y={100 - h}
                      width={Math.max(0.8, 1 - 0.1)}
                      height={h}
                      fill="oklch(0.55 0.13 151)"
                      className="transition-opacity hover:opacity-80"
                      onMouseEnter={() => {
                        const svg = histogramRef.current;
                        if (!svg) return;
                        const rect = svg.getBoundingClientRect();
                        setHoveredBin({
                          x: (i / histogram.length) * rect.width,
                          y: (1 - h / 100) * rect.height,
                          count: bin.count,
                          position: bin.position,
                        });
                      }}
                      onMouseLeave={() => setHoveredBin(null)}
                    />
                  );
                })}
              </svg>

              {hoveredBin && (
                <div
                  className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded border bg-popover px-2 py-1 font-mono text-[10px] shadow"
                  style={{ left: hoveredBin.x, top: hoveredBin.y - 4 }}
                >
                  {formatPosition(hoveredBin.position)} — {hoveredBin.count} variants
                </div>
              )}
            </div>

            {/* Position indicator track */}
            <div className="h-4 border-t bg-muted/20 px-1">
              <div className="flex h-full items-center justify-center font-mono text-[9px] text-muted-foreground">
                {positionLabel}
              </div>
            </div>

            {/* No-JS fallback notice */}
            <noscript>
              <div className="absolute inset-0 flex items-center justify-center bg-card text-xs text-muted-foreground">
                Interactive genome view requires JavaScript.{" "}
                <a href={fullBrowserHref} className="underline">
                  Open JBrowse
                </a>
                .
              </div>
            </noscript>
          </div>
        )}
      </div>
    </div>
  );
}
