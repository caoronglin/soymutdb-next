/**
 * ChromosomeHero — the signature visual element of SoyMutDB.
 *
 * Renders the default species' (soybean) 20 chromosomes as SVG-based interactive ideograms with
 * mini density sparklines below each label. Subtle scroll-linked parallax
 * applied via IntersectionObserver + RAF.
 *
 * SSR-friendly: renders static content immediately; JS enhances interactivity.
 */
import * as React from "react";
import { ExportOutlined } from "@ant-design/icons";
import { cn } from "@/lib/cn";
import { useAnimation } from "../lib/animation-context";
import { CHROMOSOME_LENGTHS_BP, formatMb, jbrowseUrl } from "../lib/format";
import { getMotionPrefs } from "../lib/motion-prefs";

export interface ChromosomeDensityPoint {
  chromosome: string;
  variantCount: number;
  lengthBp?: number;
  bands?: Array<{ start: number; end: number; density: number; name?: string }>;
  /** Optional per-chromosome mini-sparkline values (0..1) for the gene density preview. */
  sparkline?: number[];
}

export interface ChromosomeHeroProps {
  data?: ChromosomeDensityPoint[];
  /**
   * Explicit assembly name used for JBrowse deep links. Without it the
   * standalone-browser fallback is disabled rather than defaulting to a
   * genome namespace (v4/v5 are distinct coordinate spaces).
   */
  assembly?: string;
  onSelectChromosome?: (chromosome: string, band?: { start: number; end: number }) => void;
  className?: string;
}

function resolveDensity(data?: ChromosomeDensityPoint[]): ChromosomeDensityPoint[] {
  if (data && data.length > 0) {
    return data;
  }
  return [];
}

/** Map 0..1 density to low-saturation green stops. */
function densityColor(t: number, alpha = 1): string {
  const stops = [
    [0.48, 0.10, 155],
    [0.58, 0.13, 151],
    [0.68, 0.11, 150],
    [0.78, 0.09, 148],
    [0.86, 0.07, 146],
  ];
  const idx = Math.min(stops.length - 1, Math.max(0, Math.floor(t * stops.length)));
  const [l, c, h] = stops[idx];
  return alpha < 1 ? `oklch(${l} ${c} ${h} / ${alpha})` : `oklch(${l} ${c} ${h})`;
}

interface TooltipData {
  chromosome: string;
  label: string;
  position: { x: number; y: number };
  variantCount: number;
  lengthBp: number;
  geneDensity: string;
}

export function ChromosomeHero({ data, assembly, onSelectChromosome, className }: ChromosomeHeroProps) {
  const { reduced, intensity } = useAnimation();
  const points = React.useMemo(() => resolveDensity(data), [data]);
  const maxCount = React.useMemo(() => Math.max(...points.map((p) => p.variantCount), 1), [points]);

  const svgContainerRef = React.useRef<HTMLDivElement | null>(null);
  const parallaxRef = React.useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = React.useState(false);
  const [hovered, setHovered] = React.useState<TooltipData | null>(null);
  const [focusedChr, setFocusedChr] = React.useState<string | null>(null);

  // IntersectionObserver for entry animation.
  React.useEffect(() => {
    const container = svgContainerRef.current;
    if (!container) return;
    const { reduced: reducedMotion } = getMotionPrefs();
    if (reducedMotion) {
      const frame = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(frame);
    }
    const obs = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) { setVisible(true); obs.disconnect(); break; }
        }
      },
      { threshold: 0.15 },
    );
    obs.observe(container);
    return () => obs.disconnect();
  }, []);

  // Scroll-linked parallax (subtle, ~12px max shift).
  React.useEffect(() => {
    if (reduced) return;
    const target = parallaxRef.current;
    if (!target) return;
    let rafId = 0;
    const onScroll = () => {
      if (rafId) return;
      rafId = requestAnimationFrame(() => {
        const rect = target.getBoundingClientRect();
        const vh = window.innerHeight;
        const progress = (vh - rect.top) / (vh + rect.height);
        const clamped = Math.max(0, Math.min(1, progress));
        const y = (clamped - 0.5) * -10; // -5px to +5px
        target.style.transform = `translateY(${y}px)`;
        rafId = 0;
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, [reduced]);

  // Bounded opacity-only entry animation.
  React.useEffect(() => {
    if (!visible || reduced) return;
    const container = svgContainerRef.current;
    if (!container) return;
    const duration = intensity === "minimal" ? 140 : 180;
    const elements = container.querySelectorAll<SVGElement>(
      "[data-chrom-outline], [data-chrom-band]",
    );
    const animations = Array.from(elements, (element, index) =>
      element.animate([{ opacity: 0 }, { opacity: 1 }], {
        duration,
        delay: Math.min(index * 8, 120),
        easing: "ease-out",
        fill: "both",
      }),
    );
    return () => animations.forEach((animation) => animation.cancel());
  }, [visible, reduced, intensity, points]);

  const handleChromosomeClick = React.useCallback(
    (point: ChromosomeDensityPoint) => {
      if (onSelectChromosome) { onSelectChromosome(point.chromosome); }
      else {
        // No parent handler: only navigate when an explicit assembly was
        // supplied. A missing context renders nothing instead of guessing v4.
        const href = jbrowseUrl({ chromosome: point.chromosome }, assembly);
        if (href) window.location.href = href;
      }
    },
    [assembly, onSelectChromosome],
  );

  const handleBandClick = React.useCallback(
    (point: ChromosomeDensityPoint, band: { start: number; end: number; name?: string }) => {
      const lengthBp = point.lengthBp ?? CHROMOSOME_LENGTHS_BP[point.chromosome] ?? 50_000_000;
      const startBp = Math.floor(band.start * lengthBp);
      const endBp = Math.floor(band.end * lengthBp);
      if (onSelectChromosome) { onSelectChromosome(point.chromosome, { start: startBp, end: endBp }); }
      else {
        const href = jbrowseUrl(
          { chromosome: point.chromosome, start: startBp, end: endBp },
          assembly,
        );
        if (href) window.location.href = href;
      }
    },
    [assembly, onSelectChromosome],
  );

  const CHROM_W = 28;
  const CHROM_H = 160;
  const CHROM_R = 12;
  const SPARK_H = 14;

  if (points.length === 0) {
    return (
      <div className={cn("flex min-h-64 items-center justify-center rounded-lg border border-dashed text-center text-sm text-muted-foreground", className)} role="status">
        Variant density data unavailable.
      </div>
    );
  }

  return (
    <div ref={svgContainerRef} className={cn("relative", className)}>
      <div ref={parallaxRef} style={{ willChange: reduced ? undefined : "transform" }}>
        <div
          className="grid grid-cols-5 gap-x-6 gap-y-6 sm:grid-cols-10 md:grid-cols-[repeat(20,minmax(0,1fr))]"
          role="group"
          aria-label="Soybean chromosomes (default species) — click to open in genome browser"
        >
          {points.map((point) => {
            const lengthBp = point.lengthBp ?? CHROMOSOME_LENGTHS_BP[point.chromosome] ?? 50_000_000;
            const t = point.variantCount / maxCount;
            const bodyColor = densityColor(t);
            const isFocused = focusedChr === point.chromosome;
            const heightScale = 0.4 + (lengthBp / 62_465_519) * 0.6;
            const svgH = CHROM_H * heightScale;
            const bands = point.bands ?? [];
            const spark = point.sparkline ?? [];

            return (
              <div key={point.chromosome} className="flex flex-col items-center gap-2">
                <button
                  type="button"
                  className="group/chrom flex flex-col items-center gap-2 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  onMouseEnter={(e) => {
                    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                    const containerRect = svgContainerRef.current?.getBoundingClientRect();
                    setHovered({
                      chromosome: point.chromosome,
                      label: point.chromosome,
                      position: containerRect
                        ? { x: rect.left - containerRect.left + rect.width / 2, y: rect.top - containerRect.top }
                        : { x: 0, y: 0 },
                      variantCount: point.variantCount,
                      lengthBp,
                      geneDensity: `${(point.variantCount / (lengthBp / 1_000_000)).toFixed(0)} variants/Mb`,
                    });
                  }}
                  onMouseLeave={() => setHovered(null)}
                  onFocus={() => setFocusedChr(point.chromosome)}
                  onBlur={() => setFocusedChr(null)}
                  onClick={() => handleChromosomeClick(point)}
                  aria-label={`${point.chromosome} — ${formatMb(lengthBp)}, ${point.variantCount.toLocaleString()} variants. Open in genome browser.`}
                >
                  <svg
                    width={CHROM_W}
                    height={svgH}
                    viewBox={`0 0 ${CHROM_W} ${svgH}`}
                    className={cn(
                      "transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]",
                      isFocused ? "scale-110" : "group-hover/chrom:scale-105",
                    )}
                    style={{ willChange: reduced ? undefined : "transform" }}
                    data-chrom-svg
                  >
                    <defs>
                      <clipPath id={`chrom-clip-${point.chromosome}`}>
                        <rect x="0" y="0" width={CHROM_W} height={svgH} rx={CHROM_R} ry={CHROM_R} />
                      </clipPath>
                      <linearGradient id={`chrom-grad-${point.chromosome}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={densityColor(Math.min(1, t * 1.1))} />
                        <stop offset="100%" stopColor={bodyColor} />
                      </linearGradient>
                    </defs>

                    <rect
                      x="0" y="0" width={CHROM_W} height={svgH} rx={CHROM_R} ry={CHROM_R}
                      fill={`url(#chrom-grad-${point.chromosome})`}
                      data-chrom-body
                    />

                    <g clipPath={`url(#chrom-clip-${point.chromosome})`}>
                      {bands.map((band, i) => {
                        const y = band.start * svgH;
                        const h = Math.max(1, (band.end - band.start) * svgH);
                        const isCentromere = band.name === "cen";
                        const fillColor = isCentromere
                          ? "oklch(0.3 0.05 150)"
                          : densityColor(band.density, 0.85);
                        return (
                          <rect
                            key={i}
                            x={isCentromere ? CHROM_W * 0.25 : 0}
                            y={y}
                            width={isCentromere ? CHROM_W * 0.5 : CHROM_W}
                            height={h}
                            fill={fillColor}
                            data-chrom-band
                            data-band-name={band.name}
                            data-band-start={band.start}
                            data-band-end={band.end}
                            style={reduced ? undefined : { opacity: visible ? undefined : 0 }}
                            onClick={(e) => { e.stopPropagation(); handleBandClick(point, band); }}
                            className={cn("cursor-pointer transition-[filter] duration-150", !isCentromere && "hover:brightness-125")}
                            role="button"
                            aria-label={`${point.chromosome} ${band.name} band`}
                          />
                        );
                      })}
                    </g>

                    <rect
                      x="0" y="0" width={CHROM_W} height={svgH} rx={CHROM_R} ry={CHROM_R}
                      fill="none"
                      stroke="oklch(0.35 0.08 150)"
                      strokeWidth="1"
                      data-chrom-outline
                      style={reduced ? undefined : { opacity: visible ? 1 : 0 }}
                    />

                    <circle cx={CHROM_W / 2} cy={CHROM_R / 2} r="1.5" fill="oklch(0.45 0.05 148 / 0.5)" />
                    <circle cx={CHROM_W / 2} cy={svgH - CHROM_R / 2} r="1.5" fill="oklch(0.45 0.05 148 / 0.5)" />
                  </svg>
                </button>

                {/* Mini density sparkline */}
                <svg
                  width={CHROM_W + 8}
                  height={SPARK_H}
                  viewBox={`0 0 ${CHROM_W + 8} ${SPARK_H}`}
                  className="opacity-70 transition-opacity group-hover/chrom:opacity-100"
                  aria-hidden
                >
                  {spark.map((v, i) => {
                    const barW = (CHROM_W + 8) / spark.length - 1;
                    const barH = Math.max(1, v * (SPARK_H - 2));
                    return (
                      <rect
                        key={i}
                        x={i * ((CHROM_W + 8) / spark.length) + 0.5}
                        y={SPARK_H - barH}
                        width={barW}
                        height={barH}
                        rx={0.5}
                        fill="var(--primary)"
                        opacity={0.35 + v * 0.45}
                        className="sparkline-bar"
                      />
                    );
                  })}
                </svg>

                <span
                  className={cn(
                    "font-mono text-[10px] tabular-nums transition-colors",
                    isFocused ? "text-foreground" : "text-muted-foreground group-hover/chrom:text-foreground",
                  )}
                >
                  {point.chromosome.replace("chr", "")}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Floating tooltip */}
      {hovered && (
        <div
          className="pointer-events-none absolute z-20 -translate-x-1/2 -translate-y-full rounded-lg border bg-popover/95 px-3 py-2 text-xs shadow-lg backdrop-blur-sm"
          style={{ left: hovered.position.x, top: hovered.position.y - 8 }}
          role="tooltip"
        >
          <div className="font-mono text-sm font-semibold">{hovered.chromosome}</div>
          <div className="mt-0.5 text-muted-foreground">
            {formatMb(hovered.lengthBp)} · {hovered.geneDensity}
          </div>
          <div className="mt-0.5 font-mono tabular-nums">
            {hovered.variantCount.toLocaleString()} variants
          </div>
        </div>
      )}

      {/* Hover detail popover */}
      <div className="mt-6 flex min-h-[3.5rem] items-start gap-3 rounded-lg border bg-card/60 p-3 backdrop-blur-sm">
        {hovered ? (
          <div className="flex w-full items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <span
                className="size-3 shrink-0 rounded-full shadow-sm"
                style={{ backgroundColor: densityColor(hovered.variantCount / maxCount) }}
                aria-hidden
              />
              <div>
                <p className="font-mono text-sm font-medium">{hovered.chromosome}</p>
                <p className="text-xs text-muted-foreground">
                  {formatMb(hovered.lengthBp)} ·{" "}
                  <span className="font-mono tabular-nums">{hovered.variantCount.toLocaleString()}</span> variants · {hovered.geneDensity}
                </p>
              </div>
            </div>
            <span className="inline-flex items-center gap-1 text-xs font-medium text-primary">
              Open in browser
              <ExportOutlined className="size-3" aria-hidden />
            </span>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            Hover a chromosome to inspect variant density; click a band to navigate to that region.
          </p>
        )}
      </div>

      {/* Density legend */}
      <div className="mt-4 flex items-center justify-end gap-2 text-[10px] text-muted-foreground">
        <span>Low density</span>
        <span className="flex h-2 w-24 overflow-hidden rounded-full" aria-hidden>
          {[0.8, 0.6, 0.4, 0.2, 0].map((t) => (
            <span key={t} className="flex-1" style={{ backgroundColor: densityColor(t) }} />
          ))}
        </span>
        <span>High density</span>
      </div>
    </div>
  );
}
