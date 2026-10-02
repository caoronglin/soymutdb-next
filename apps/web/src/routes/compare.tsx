/**
 * Variant Comparison — select 2-4 variants and compare their attributes
 * side-by-side with an impact/mutation-type distribution chart.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import * as React from "react";
import {
  BarChartOutlined as BarChart3,
  CloseOutlined as X,
  DeploymentUnitOutlined as Dna,
  EnvironmentOutlined as MapPin,
  ExperimentOutlined as FlaskConical,
  PlusOutlined as Plus,
  RiseOutlined as Activity,
  SwapOutlined as GitCompareArrows,
} from "@ant-design/icons";
import { Button, Card, Checkbox, Empty, Table, Tag, Typography } from "@/lib/antd";
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
    document.title = t("compare.curated.documentTitle");
  }, [t]);

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

  // The comparison grid is transposed: antd's Table takes fields as rows and
  // the selected variants as columns, so each row carries one rendered cell per
  // variant.
  const comparisonRows: ComparisonRow[] = [
    {
      key: "gene",
      label: t("compare.curated.fields.gene"),
      icon: <Dna className="size-3.5" />,
      cells: selectedVariants.map((v) => (
        <span key={v.id}>
          <span className="font-semibold">{v.geneName || v.gene}</span>
          {v.geneName && (
            <span className="ml-1 font-mono text-xs text-muted-foreground">({v.gene})</span>
          )}
        </span>
      )),
    },
    {
      key: "location",
      label: t("compare.curated.fields.location"),
      icon: <MapPin className="size-3.5" />,
      cells: selectedVariants.map((v) => (
        <span key={v.id} className="font-mono text-xs">
          {v.chromosome}:{v.position.toLocaleString()}
        </span>
      )),
    },
    {
      key: "alleleChange",
      label: t("compare.curated.fields.alleleChange"),
      icon: <Activity className="size-3.5" />,
      cells: selectedVariants.map((v) => (
        <span key={v.id} className="font-mono text-xs">
          <span className="text-muted-foreground">{v.refAllele}</span>
          <span className="mx-1">→</span>
          <span className="font-semibold text-primary">{v.altAllele}</span>
        </span>
      )),
    },
    {
      key: "mutation",
      label: t("compare.curated.fields.mutation"),
      icon: <Dna className="size-3.5" />,
      cells: selectedVariants.map((v) => (
        <Tag key={v.id} className="text-xs">{v.mutationType}</Tag>
      )),
    },
    {
      key: "impact",
      label: t("compare.curated.fields.impact"),
      icon: <Activity className="size-3.5" />,
      cells: selectedVariants.map((v) => (
        <Tag
          key={v.id}
          variant="outlined"
          className={`text-xs border ${IMPACT_COLORS[v.impact] || ""}`}
        >
          {v.impact}
        </Tag>
      )),
    },
    ...(selectedVariants.some((v) => v.proteinChange)
      ? [
          {
            key: "protein",
            label: t("compare.curated.fields.protein"),
            icon: <Activity className="size-3.5" />,
            cells: selectedVariants.map((v) => (
              <span key={v.id} className="font-mono text-xs">
                {v.proteinChange || <span className="text-muted-foreground">—</span>}
              </span>
            )),
          },
        ]
      : []),
    {
      key: "mutagen",
      label: t("compare.curated.fields.mutagen"),
      icon: <FlaskConical className="size-3.5" />,
      cells: selectedVariants.map((v) => <span key={v.id}>{v.mutagen}</span>),
    },
    {
      key: "cultivar",
      label: t("compare.curated.fields.cultivar"),
      icon: <Dna className="size-3.5" />,
      cells: selectedVariants.map((v) => <span key={v.id}>{v.cultivar}</span>),
    },
    {
      key: "phenotype",
      label: t("compare.curated.fields.phenotype"),
      icon: null,
      cells: selectedVariants.map((v) => (
        <span key={v.id} className="break-words text-sm">
          {t(`compare.curated.phenotypes.${v.id}`)}
        </span>
      )),
    },
  ];

  return (
    <div ref={rootRef} className="container-prose py-8 md:py-12">
      <FadeUp stagger={0.05}>
        <div className="mb-8">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
            <GitCompareArrows className="size-4" />
            <span>{t("compare.curated.eyebrow")}</span>
          </div>
          <h1 className="font-display text-3xl md:text-4xl font-bold tracking-tight">
            {t("compare.curated.pageTitle")}
          </h1>
          <p className="mt-2 text-muted-foreground max-w-2xl">
            {t("compare.curated.subtitle", { max: MAX_COMPARE })}
          </p>
          <p className="mt-2 text-sm text-amber-700 dark:text-amber-300" role="note">
            {t("compare.curated.referenceNote")}
          </p>
        </div>
      </FadeUp>

      <section className="mt-8" aria-labelledby="compare-picker-heading">
        <div className="mb-4">
          <Typography.Title id="compare-picker-heading" level={2} className="m-0 text-xl md:text-2xl">
            {t("compare.curated.picker.title")}
          </Typography.Title>
          <Typography.Text className="text-sm text-muted-foreground">
            {t("compare.curated.picker.selectedCount", { count: selected.length, max: MAX_COMPARE })}
          </Typography.Text>
        </div>
        <div
          data-testid="compare-picker"
          role="group"
          aria-label={t("compare.curated.picker.gridLabel")}
          className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3"
        >
          {COMPARE_VARIANTS.map((v) => {
            const isSelected = selected.includes(v.id);
            const disabled = !isSelected && selected.length >= MAX_COMPARE;
            // antd Checkbox renders its own <label>, so the card IS the
            // checkbox: the whole card stays clickable and keyboard-reachable
            // while the control itself becomes a native antd component.
            return (
              <Checkbox
                key={v.id}
                checked={isSelected}
                disabled={disabled}
                onChange={() => toggle(v.id)}
                aria-label={t("compare.curated.picker.selectVariant", { id: v.id })}
                className={`h-full items-start rounded-xl border p-4 transition-colors [&_.ant-checkbox]:mt-0.5 [&>span:last-child]:w-full ${
                  disabled ? "cursor-not-allowed opacity-50" : "hover:border-primary/60"
                } ${isSelected ? "border-primary bg-primary/10" : "border-border bg-card"}`}
              >
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-semibold">{v.id}</span>
                    <Tag variant="outlined" className={`text-xs border ${IMPACT_COLORS[v.impact] || ""}`}>
                      {v.impact}
                    </Tag>
                  </div>
                  <div className="break-words text-sm font-medium">{v.geneName || v.gene}</div>
                  <div className="break-words text-xs text-muted-foreground">
                    {v.mutagen} · {v.chromosome}
                  </div>
                </div>
              </Checkbox>
            );
          })}
        </div>
      </section>

      {/* Comparison panel */}
      <div className="mt-8 space-y-6 min-w-0">
          {selectedVariants.length < 2 ? (
            <Empty
              image={<Plus style={{ fontSize: 40, color: "var(--muted-foreground)" }} />}
              description={
                <>
                  <p className="font-medium">{t("compare.curated.empty.title")}</p>
                  <p className="text-sm text-muted-foreground">{t("compare.curated.empty.description")}</p>
                </>
              }
            />
          ) : (
            <>
              {/* Summary cards */}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {selectedVariants.map((v, i) => (
                  <FadeUp key={v.id} delay={0.05 + i * 0.05}>
                    <VariantCard
                      v={v}
                      onRemove={() => toggle(v.id)}
                      removeLabel={t("compare.curated.removeVariant", { id: v.id })}
                    />
                  </FadeUp>
                ))}
              </div>

              {/* Comparison grid */}
              <FadeUp delay={0.2}>
                <Card>
                  <div className="pb-3">
                    <Typography.Title level={2} className="m-0 text-lg flex items-center gap-2">
                      <BarChart3 className="size-4" /> {t("compare.curated.comparisonTitle")}
                    </Typography.Title>
                  </div>
                  <Table<ComparisonRow>
                    size="small"
                    bordered
                    rowKey="key"
                    pagination={false}
                    scroll={{ x: "max-content" }}
                    columns={[
                      {
                        title: t("compare.curated.comparisonTitle"),
                        dataIndex: "label",
                        key: "label",
                        fixed: "left",
                        width: 170,
                        render: (_: unknown, row: ComparisonRow) => (
                          <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                            {row.icon}
                            {row.label}
                          </span>
                        ),
                      },
                      ...selectedVariants.map((v, index) => ({
                        title: <span className="font-mono text-xs">{v.id}</span>,
                        key: v.id,
                        width: 220,
                        render: (_: unknown, row: ComparisonRow) => row.cells[index],
                      })),
                    ]}
                    dataSource={comparisonRows}
                  />
                </Card>
              </FadeUp>

              {/* Distribution chart (pure SVG, no heavy lib needed) */}
              <FadeUp delay={0.25}>
                <Card>
                  <div className="pb-3">
                    <Typography.Title level={2} className="m-0 text-lg flex items-center gap-2">
                      <BarChart3 className="size-4" /> {t("compare.curated.impactDistribution.title")}
                    </Typography.Title>
                    <Typography.Text className="text-sm text-muted-foreground">
                      {t("compare.curated.impactDistribution.description")}
                    </Typography.Text>
                  </div>
                  <div>
                    <ImpactChart
                      variants={selectedVariants}
                      ariaLabel={t("compare.curated.impactDistribution.ariaLabel")}
                    />
                  </div>
                </Card>
              </FadeUp>
            </>
          )}
        </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function VariantCard({
  v,
  onRemove,
  removeLabel,
}: {
  v: CompareVariant;
  onRemove: () => void;
  removeLabel: string;
}) {
  return (
    <Card className="relative">
      <Button
        type="text"
        shape="circle"
        onClick={onRemove}
        aria-label={removeLabel}
        className="absolute top-3 right-3"
        icon={<X className="size-3" />}
      />
      <div className="p-4">
        <div className="font-mono text-xs text-muted-foreground mb-1">{v.id}</div>
        <div className="font-display text-lg font-bold leading-tight mb-1">
          {v.geneName || v.gene}
        </div>
        <div className="font-mono text-xs text-muted-foreground break-words mb-3 pr-12">{v.gene}</div>
        <Tag
          variant="outlined"
          className={`text-xs border ${IMPACT_COLORS[v.impact] || ""}`}
        >
          {v.impact}
        </Tag>
        <div className="mt-3 space-y-1 text-xs text-muted-foreground">
          <div className="flex items-center gap-1">
            <MapPin className="size-3" />
            {v.chromosome}:{v.position.toLocaleString()}
          </div>
          <div className="flex items-center gap-1">
            <FlaskConical className="size-3" />
            {v.mutagen}
          </div>
        </div>
      </div>
    </Card>
  );
}

/** One field row of the transposed comparison grid. */
interface ComparisonRow {
  key: string;
  label: string;
  icon: React.ReactNode;
  /** One rendered cell per selected variant, in `selectedVariants` order. */
  cells: React.ReactNode[];
}


function ImpactChart({ variants, ariaLabel }: { variants: CompareVariant[]; ariaLabel: string }) {
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
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-md mx-auto" role="img" aria-label={ariaLabel}>
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
