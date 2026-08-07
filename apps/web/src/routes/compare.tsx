/**
 * Variant Comparison — select 2-4 variants and compare their attributes
 * side-by-side with an impact/mutation-type distribution chart.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import * as React from "react";
import {
  GitCompareArrows,
  Check,
  X,
  Dna,
  FlaskConical,
  MapPin,
  Activity,
  Plus,
  BarChart3,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
  Badge,
  Button,
  EmptyState,
  Checkbox,
  Label,
} from "@soymutdb/ui";
import { FadeUp, useReveal } from "../components/route-motion";
import { startViewTransition } from "../lib/view-transitions";
import { COMPARE_VARIANTS, type CompareVariant } from "../lib/compare-data";

const MAX_COMPARE = 4;

const IMPACT_COLORS: Record<string, string> = {
  HIGH: "bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30",
  MODERATE: "bg-orange-500/15 text-orange-600 dark:text-orange-400 border-orange-500/30",
  LOW: "bg-blue-500/15 text-blue-600 dark:text-blue-400 border-blue-500/30",
  MODIFIER: "bg-slate-500/15 text-slate-600 dark:text-slate-400 border-slate-500/30",
};

export const Route = createFileRoute("/compare")({
  component: ComparePage,
  validateSearch: (s: Record<string, unknown>) => ({
    ids: s.ids ? String(s.ids) : "",
  }),
});

function ComparePage() {
  const { t } = useTranslation();
  const { ids } = Route.useSearch();
  const navigate = Route.useNavigate();
  const rootRef = React.useRef<HTMLDivElement>(null);

  const initial = React.useMemo(() => {
    const list = ids ? ids.split(",").filter(Boolean) : [COMPARE_VARIANTS[0].id, COMPARE_VARIANTS[1].id];
    return list.filter((id) => COMPARE_VARIANTS.some((v) => v.id === id)).slice(0, MAX_COMPARE);
  }, [ids]);

  const [selected, setSelected] = React.useState<string[]>(initial);
  useReveal(rootRef, { threshold: 0.05 });

  React.useEffect(() => {
    document.title = "Variant Comparison — SoyMutDB";
  }, []);

  // Sync to URL
  React.useEffect(() => {
    navigate({ search: { ids: selected.join(",") }, replace: true });
  }, [selected, navigate]);

  function toggle(id: string) {
    startViewTransition(() => {
      setSelected((prev) => {
        if (prev.includes(id)) return prev.filter((x) => x !== id);
        if (prev.length >= MAX_COMPARE) return prev;
        return [...prev, id];
      });
    });
  }

  const selectedVariants = selected
    .map((id) => COMPARE_VARIANTS.find((v) => v.id === id))
    .filter((v): v is CompareVariant => Boolean(v));

  return (
    <div ref={rootRef} className="container-prose py-8 md:py-12">
      <FadeUp stagger={0.05}>
        <div className="mb-8">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
            <GitCompareArrows className="size-4" />
            <span>Variant Comparison</span>
          </div>
          <h1 className="font-display text-3xl md:text-4xl font-bold tracking-tight">
            Compare Mutant Variants
          </h1>
          <p className="mt-2 text-muted-foreground max-w-2xl">
            Select up to {MAX_COMPARE} variants to compare gene, mutation type,
            impact, mutagen, and phenotype side-by-side.
          </p>
        </div>
      </FadeUp>

      <div className="grid grid-cols-1 lg:grid-cols-[280px,1fr] gap-6">
        {/* Variant picker */}
        <FadeUp delay={0.1}>
          <Card className="lg:sticky lg:top-20 h-fit max-h-[70vh] overflow-hidden flex flex-col">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Select Variants</CardTitle>
              <CardDescription className="text-xs">
                {selected.length} / {MAX_COMPARE} selected
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-0 overflow-y-auto space-y-1">
              {COMPARE_VARIANTS.map((v) => {
                const isSelected = selected.includes(v.id);
                const disabled = !isSelected && selected.length >= MAX_COMPARE;
                return (
                  <label
                    key={v.id}
                    className={`flex items-start gap-2 px-2 py-2 rounded-md cursor-pointer transition-colors ${
                      disabled ? "opacity-40 cursor-not-allowed" : "hover:bg-muted"
                    } ${isSelected ? "bg-primary/10" : ""}`}
                  >
                    <Checkbox
                      checked={isSelected}
                      disabled={disabled}
                      onCheckedChange={() => toggle(v.id)}
                      className="mt-0.5"
                      aria-label={`Select ${v.id}`}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-semibold">{v.id}</span>
                        <Badge
                          variant="outline"
                          className={`text-[10px] border ${IMPACT_COLORS[v.impact] || ""}`}
                        >
                          {v.impact}
                        </Badge>
                      </div>
                      <div className="text-xs font-medium truncate">{v.geneName || v.gene}</div>
                      <div className="text-[11px] text-muted-foreground truncate">
                        {v.mutagen} · {v.chromosome}
                      </div>
                    </div>
                  </label>
                );
              })}
            </CardContent>
          </Card>
        </FadeUp>

        {/* Comparison panel */}
        <div className="space-y-6 min-w-0">
          {selectedVariants.length < 2 ? (
            <EmptyState
              icon={Plus}
              title="Select at least 2 variants"
              description="Pick variants from the list to start a comparison."
            />
          ) : (
            <>
              {/* Summary cards */}
              <div
                className="grid gap-4"
                style={{
                  gridTemplateColumns: `repeat(${Math.min(selectedVariants.length, 4)}, minmax(0, 1fr))`,
                }}
              >
                {selectedVariants.map((v, i) => (
                  <FadeUp key={v.id} delay={0.05 + i * 0.05}>
                    <VariantCard v={v} onRemove={() => toggle(v.id)} />
                  </FadeUp>
                ))}
              </div>

              {/* Comparison grid */}
              <FadeUp delay={0.2}>
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base flex items-center gap-2">
                      <BarChart3 className="size-4" /> Attribute Comparison
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0 overflow-x-auto">
                    <table className="w-full text-sm">
                      <tbody>
                        <CompareRow
                          label="Gene"
                          icon={<Dna className="size-3.5" />}
                          values={selectedVariants.map((v) => (
                            <span key={v.id}>
                              <span className="font-semibold">{v.geneName || v.gene}</span>
                              {v.geneName && (
                                <span className="text-muted-foreground font-mono text-xs ml-1">
                                  ({v.gene})
                                </span>
                              )}
                            </span>
                          ))}
                          ids={selectedVariants.map((v) => v.id)}
                        />
                        <CompareRow
                          label="Location"
                          icon={<MapPin className="size-3.5" />}
                          values={selectedVariants.map((v) => (
                            <span key={v.id} className="font-mono text-xs">
                              {v.chromosome}:{v.position.toLocaleString()}
                            </span>
                          ))}
                          ids={selectedVariants.map((v) => v.id)}
                        />
                        <CompareRow
                          label="Allele change"
                          icon={<Activity className="size-3.5" />}
                          values={selectedVariants.map((v) => (
                            <span key={v.id} className="font-mono text-xs">
                              <span className="text-muted-foreground">{v.refAllele}</span>
                              <span className="mx-1">→</span>
                              <span className="text-primary font-semibold">{v.altAllele}</span>
                            </span>
                          ))}
                          ids={selectedVariants.map((v) => v.id)}
                        />
                        <CompareRow
                          label="Mutation"
                          icon={<Dna className="size-3.5" />}
                          values={selectedVariants.map((v) => (
                            <Badge key={v.id} variant="secondary" className="text-xs">
                              {v.mutationType}
                            </Badge>
                          ))}
                          ids={selectedVariants.map((v) => v.id)}
                        />
                        <CompareRow
                          label="Impact"
                          icon={<Activity className="size-3.5" />}
                          values={selectedVariants.map((v) => (
                            <Badge
                              key={v.id}
                              variant="outline"
                              className={`text-xs border ${IMPACT_COLORS[v.impact] || ""}`}
                            >
                              {v.impact}
                            </Badge>
                          ))}
                          ids={selectedVariants.map((v) => v.id)}
                        />
                        {selectedVariants.some((v) => v.proteinChange) && (
                          <CompareRow
                            label="Protein"
                            icon={<Activity className="size-3.5" />}
                            values={selectedVariants.map((v) => (
                              <span key={v.id} className="font-mono text-xs">
                                {v.proteinChange || <span className="text-muted-foreground">—</span>}
                              </span>
                            ))}
                            ids={selectedVariants.map((v) => v.id)}
                          />
                        )}
                        <CompareRow
                          label="Mutagen"
                          icon={<FlaskConical className="size-3.5" />}
                          values={selectedVariants.map((v) => v.mutagen)}
                          ids={selectedVariants.map((v) => v.id)}
                        />
                        <CompareRow
                          label="Cultivar"
                          icon={<Dna className="size-3.5" />}
                          values={selectedVariants.map((v) => v.cultivar)}
                          ids={selectedVariants.map((v) => v.id)}
                        />
                        <tr>
                          <th className="text-left text-xs text-muted-foreground py-3 pr-4 align-top font-medium w-28">
                            Phenotype
                          </th>
                          {selectedVariants.map((v) => (
                            <td key={v.id} className="py-3 px-3 align-top text-xs max-w-[200px] border-t border-border/50">
                              {v.phenotype}
                            </td>
                          ))}
                        </tr>
                      </tbody>
                    </table>
                  </CardContent>
                </Card>
              </FadeUp>

              {/* Distribution chart (pure SVG, no heavy lib needed) */}
              <FadeUp delay={0.25}>
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base flex items-center gap-2">
                      <BarChart3 className="size-4" /> Impact Distribution
                    </CardTitle>
                    <CardDescription className="text-xs">
                      Counts of HIGH / MODERATE / LOW / MODIFIER impact in current selection
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ImpactChart variants={selectedVariants} />
                  </CardContent>
                </Card>
              </FadeUp>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function VariantCard({ v, onRemove }: { v: CompareVariant; onRemove: () => void }) {
  return (
    <Card className="relative">
      <button
        onClick={onRemove}
        className="absolute top-2 right-2 size-6 inline-flex items-center justify-center rounded-full bg-muted/60 hover:bg-destructive hover:text-destructive-foreground transition-colors"
        aria-label={`Remove ${v.id}`}
      >
        <X className="size-3" />
      </button>
      <CardContent className="p-4">
        <div className="font-mono text-xs text-muted-foreground mb-1">{v.id}</div>
        <div className="font-display text-lg font-bold leading-tight mb-1">
          {v.geneName || v.gene}
        </div>
        <div className="font-mono text-[11px] text-muted-foreground truncate mb-3">{v.gene}</div>
        <Badge
          variant="outline"
          className={`text-[10px] border ${IMPACT_COLORS[v.impact] || ""}`}
        >
          {v.impact}
        </Badge>
        <div className="mt-3 space-y-1 text-[11px] text-muted-foreground">
          <div className="flex items-center gap-1">
            <MapPin className="size-3" />
            {v.chromosome}:{v.position.toLocaleString()}
          </div>
          <div className="flex items-center gap-1">
            <FlaskConical className="size-3" />
            {v.mutagen}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function CompareRow({
  label,
  icon,
  values,
  ids,
}: {
  label: string;
  icon: React.ReactNode;
  values: React.ReactNode[];
  ids: string[];
}) {
  return (
    <tr>
      <th className="text-left text-xs text-muted-foreground py-2.5 pr-4 align-middle font-medium w-28">
        <span className="inline-flex items-center gap-1.5">
          {icon}
          {label}
        </span>
      </th>
      {values.map((val, i) => (
        <td
          key={ids[i]}
          className="py-2.5 px-3 align-middle text-sm border-t border-border/50"
        >
          {val}
        </td>
      ))}
    </tr>
  );
}

function ImpactChart({ variants }: { variants: CompareVariant[] }) {
  const counts: Record<string, number> = { HIGH: 0, MODERATE: 0, LOW: 0, MODIFIER: 0 };
  for (const v of variants) counts[v.impact] = (counts[v.impact] || 0) + 1;
  const total = variants.length;
  const colors: Record<string, string> = {
    HIGH: "#ef4444",
    MODERATE: "#f97316",
    LOW: "#3b82f6",
    MODIFIER: "#94a3b8",
  };
  const W = 400, H = 160, BAR_W = 60, GAP = 30;
  const maxH = H - 50;
  const keys = ["HIGH", "MODERATE", "LOW", "MODIFIER"] as const;
  const totalBarWidth = keys.length * BAR_W + (keys.length - 1) * GAP;
  const startX = (W - totalBarWidth) / 2;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-md mx-auto" role="img" aria-label="Impact distribution bar chart">
      {keys.map((k, i) => {
        const c = counts[k];
        const h = total > 0 ? (c / total) * maxH : 0;
        const x = startX + i * (BAR_W + GAP);
        const y = H - 30 - h;
        return (
          <g key={k}>
            <rect x={x} y={y} width={BAR_W} height={h} rx={4} fill={colors[k]} opacity={c ? 1 : 0.2}>
              {c > 0 && (
                <animate
                  attributeName="height"
                  from="0"
                  to={h}
                  dur="0.6s"
                  fill="freeze"
                  begin={`${i * 0.08}s`}
                />
              )}
            </rect>
            <text x={x + BAR_W / 2} y={y - 6} textAnchor="middle" className="text-xs font-semibold" fill="currentColor" fontSize="12">
              {c}
            </text>
            <text x={x + BAR_W / 2} y={H - 12} textAnchor="middle" fill="currentColor" fontSize="10" opacity="0.6">
              {k}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
