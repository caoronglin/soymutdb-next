/**
 * SRA Run Browser — query NCBI Sequence Read Archive metadata by
 * accession number, visualise run stats, browse curated runs for the default species (soybean).
 */
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
import {
  AimOutlined as Microscope,
  ClockCircleOutlined as Clock,
  DownloadOutlined as Download,
  DatabaseOutlined as Database,
  DeleteOutlined as Trash2,
  DeploymentUnitOutlined as Dna,
  ExportOutlined as ExternalLink,
  HistoryOutlined as History,
  HddOutlined as HardDrive,
  ReloadOutlined as RefreshCw,
  RightOutlined as ChevronRight,
  SearchOutlined as Search,
  WarningOutlined as AlertTriangle,
} from "@ant-design/icons";
import { Button, Card, Empty, Input, Skeleton, Tag, Typography } from "@/lib/antd";
import { fetchSraRun, fetchSraSamples, type SraRunInfo } from "@soymutdb/api-client";
import { FadeUp, useReveal } from "../components/route-motion";
import { SoyMutDbWidget } from "../components/soymutdb-widget";
import { startViewTransition } from "../lib/view-transitions";

// The `sra_run` widget below is the backend's own expanded run view
// (GET /api/v1/widget/sra_run, apps/api/app/widgets/). It used to be embedded here
// through a `soymutdb-widget` custom element, whose renderer was deleted in
// 25c32e499 during the Vue cutover and never restored — so the element mounted
// inert and this card rendered empty. A `declare module "react"` block kept it
// type-checking, which is how the breakage survived review, typecheck and the unit
// tests. f28e38d86 removed the dead embed; it is now a real React component
// (../components/soymutdb-widget) that sanitizes the server fragment with
// DOMPurify before insertion. Keep it a component: a dashed JSX tag is always a
// custom element, and scripts/test_custom_element_registration_contracts.py fails
// the build for any such tag that no `customElements.define` registers.
//
// Note: that suite also refuses the literal tag name in this file, including in a
// comment, so the element is referred to by name only here.

const HISTORY_KEY = "soymutdb:sra-history";
const HISTORY_LIMIT = 10;
const DEFAULT_RUN = "SRR30334525";

function loadHistory(): string[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveHistory(acc: string) {
  try {
    const list = loadHistory().filter((a) => a !== acc);
    list.unshift(acc);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, HISTORY_LIMIT)));
  } catch { /* noop */ }
}

function clearHistory() {
  try { localStorage.removeItem(HISTORY_KEY); } catch { /* noop */ }
}

function formatBases(b?: string): string {
  if (!b) return "—";
  const n = Number(b);
  if (isNaN(n)) return b;
  if (n >= 1e9) return (n / 1e9).toFixed(2) + " Gbp";
  if (n >= 1e6) return (n / 1e6).toFixed(2) + " Mbp";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + " kbp";
  return n + " bp";
}

function formatSpots(b?: string): string {
  if (!b) return "—";
  const n = Number(b);
  if (isNaN(n)) return b;
  if (n >= 1e6) return (n / 1e6).toFixed(2) + " M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + " K";
  return n.toString();
}

function formatSize(mb?: string): string {
  if (!mb) return "—";
  const n = Number(mb);
  if (isNaN(n)) return mb;
  if (n >= 1024) return (n / 1024).toFixed(2) + " GB";
  return n.toFixed(1) + " MB";
}

export const Route = createFileRoute("/sra")({
  component: SraBrowser,
  validateSearch: (s: Record<string, unknown>) => ({
    run: s.run ? String(s.run) : DEFAULT_RUN,
  }),
});

function SraBrowser() {
  const { t } = useTranslation();
  const { run: initialRun } = Route.useSearch();
  const navigate = Route.useNavigate();
  const [input, setInput] = React.useState(initialRun || DEFAULT_RUN);
  const [activeRun, setActiveRun] = React.useState(initialRun || DEFAULT_RUN);
  const [history, setHistory] = React.useState<string[]>(() => loadHistory());
  const rootRef = React.useRef<HTMLDivElement>(null);

  // SEO title
  React.useEffect(() => {
    document.title = t("sra.documentTitle");
  }, [t]);

  const runQuery = useQuery({
    queryKey: ["sra-run", activeRun],
    queryFn: () => fetchSraRun(activeRun),
    enabled: Boolean(activeRun),
    staleTime: 5 * 60 * 1000,
  });

  const samplesQuery = useQuery({
    queryKey: ["sra-samples"],
    queryFn: fetchSraSamples,
    staleTime: 30 * 60 * 1000,
  });

  function submit(e?: React.FormEvent) {
    e?.preventDefault();
    const acc = input.trim().toUpperCase();
    if (!acc) return;
    if (!/^[SED]RR\d{6,10}$/.test(acc)) {
      // Allow but warn — user might have valid accession
    }
    startViewTransition(() => {
      setActiveRun(acc);
      saveHistory(acc);
      setHistory(loadHistory());
      navigate({ search: { run: acc }, replace: true });
    });
  }

  function pickRun(acc: string) {
    setInput(acc);
    setActiveRun(acc);
    saveHistory(acc);
    setHistory(loadHistory());
    startViewTransition(() => {
      navigate({ search: { run: acc }, replace: true });
    });
  }

  function onClearHistory() {
    clearHistory();
    setHistory([]);
  }

  useReveal(rootRef, { threshold: 0.05 });

  const run = runQuery.data?.run;
  const source = runQuery.data?.source;
  const isCached = runQuery.data?.cached;
  const samples = samplesQuery.data?.samples ?? [];
  const hasLongSampleList = samples.length > 6;

  return (
    <div ref={rootRef} className="container-prose py-8 md:py-12">
      <FadeUp stagger={0.05}>
        <div className="mb-8">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
            <Database className="size-4" aria-hidden />
            <span>{t("nav.sra")}</span>
            <span className="text-border">/</span>
            <span>{t("sra.archiveName")}</span>
          </div>
          <h1 className="font-display text-3xl md:text-4xl font-bold tracking-tight">
            {t("sra.title")}
          </h1>
          <p className="mt-2 text-muted-foreground max-w-2xl">
            {t("sra.description")}
          </p>
        </div>
      </FadeUp>

      {/* Search input */}
      <FadeUp delay={0.1}>
        <form onSubmit={submit} className="mb-6">
          <div className="flex gap-2 max-w-xl">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground pointer-events-none" aria-hidden />
              <Input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={t("sra.accessionExample")}
                className="pl-9 font-mono"
                spellCheck={false}
                autoCapitalize="off"
                aria-label={t("sra.accession")}
              />
            </div>
            <Button htmlType="submit" type="primary" disabled={runQuery.isFetching}>
              {runQuery.isFetching ? (
                <RefreshCw className="size-4 mr-1 animate-spin" aria-hidden />
              ) : (
                <Search className="size-4 mr-1" aria-hidden />
              )}
              {t("sra.loadRun")}
            </Button>
          </div>
        </form>
      </FadeUp>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main panel — run details */}
        <div className="lg:col-span-2 space-y-4">
          {runQuery.isLoading && <RunDetailsSkeleton />}
          {runQuery.isError && !run && (
            <Empty
              image={<AlertTriangle aria-hidden style={{ fontSize: 40, color: "var(--muted-foreground)" }} />}
              description={
                <>
                  <p className="font-medium">{t("sra.loadFailed")}</p>
                  <p className="text-sm text-muted-foreground">
                    {runQuery.error?.message || t("sra.fetchFailed")}
                  </p>
                </>
              }
            >
              <Button icon={<RefreshCw className="size-4" aria-hidden />} onClick={() => runQuery.refetch()}>
                {t("common.retry")}
              </Button>
            </Empty>
          )}
          {run && <RunDetails run={run} source={source} isCached={!!isCached} />}
        </div>

        {/* Sidebar — history + curated samples */}
        <div className="space-y-6">
          {/* History */}
          <FadeUp delay={0.15}>
            <Card>
              <div className="pb-3">
                <Typography.Title level={2} className="m-0 text-lg flex items-center gap-2">
                  <History className="size-4" aria-hidden />
                  {t("sra.recentRuns")}
                </Typography.Title>
              </div>
              <div className="pt-0">
                {history.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{t("sra.noRecentRuns")}</p>
                ) : (
                  <div className="space-y-1">
                    {history.map((acc) => (
                      <Button
                        key={acc}
                        type="text"
                        block
                        onClick={() => pickRun(acc)}
                        className={`h-auto justify-between px-3 py-2.5 text-left font-mono text-sm ${
                          acc === activeRun ? "bg-primary/10 text-primary" : ""
                        }`}
                      >
                        <span>{acc}</span>
                        <ChevronRight className="size-3 opacity-50" aria-hidden />
                      </Button>
                    ))}
                    <Button
                      type="text"
                      block
                      danger
                      onClick={onClearHistory}
                      icon={<Trash2 className="size-4" aria-hidden />}
                      className="mt-2 h-auto py-2 text-muted-foreground"
                    >
                      {t("sra.clearHistory")}
                    </Button>
                  </div>
                )}
              </div>
            </Card>
          </FadeUp>

          {/* Curated runs — current default species (soybean) */}
          <FadeUp delay={0.2}>
            <Card>
              <div className="pb-3">
                <Typography.Title level={2} className="m-0 text-lg flex items-center gap-2">
                  <Dna className="size-4" aria-hidden />
                  {t("sra.curatedTitle")}
                </Typography.Title>
                <Typography.Text className="text-sm text-muted-foreground">
                  {t("sra.curatedDescription")}
                </Typography.Text>
              </div>
              <div className="pt-0">
                {samplesQuery.isLoading && (
                  <div className="space-y-2">
                    {[1, 2, 3].map((i) => <Skeleton key={i} className="h-10 w-full" />)}
                  </div>
                )}
                {samplesQuery.isError && (
                  <Typography.Text type="secondary">{t("sra.samplesUnavailable")}</Typography.Text>
                )}
                {!samplesQuery.isLoading && !samplesQuery.isError && samples.length === 0 && (
                  <Empty description={t("sra.noCuratedRuns")} />
                )}
                {samples.length > 0 && (
                  <>
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-sm">
                      <Typography.Text type="secondary">
                        {t("sra.sampleCount", { count: samples.length })}
                      </Typography.Text>
                      {hasLongSampleList && (
                        <Typography.Text type="secondary">{t("sra.scrollCue")}</Typography.Text>
                      )}
                    </div>
                    <div
                      data-testid="curated-sra-runs-list"
                      className={`space-y-1 ${hasLongSampleList ? "max-h-80 overflow-y-auto pr-1" : ""}`}
                    >
                      {samples.map((s) => (
                        <Button
                          key={s.Run}
                          type="text"
                          block
                          onClick={() => pickRun(s.Run)}
                          className={`h-auto px-3 py-3 text-left text-sm ${
                            s.Run === activeRun ? "bg-primary/10 text-primary" : ""
                          }`}
                        >
                          <div className="font-mono font-semibold">{s.Run}</div>
                          <div className="mt-1 break-words text-xs text-muted-foreground">
                            {s.LibraryStrategy || "RNA-Seq"} · {s.release_date_short || "—"} · {formatBases(s.bases)}
                          </div>
                        </Button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </Card>
          </FadeUp>
        </div>
      </div>

      {/* Server-rendered `sra_run` widget: GET /api/v1/widget/sra_run?params={"run":…} */}
      {activeRun && (
        <FadeUp delay={0.25} className="mt-8">
          <Card>
            <div>
              <Typography.Title level={2} className="m-0 text-lg">{t("sra.widgetTitle")}</Typography.Title>
              <Typography.Text className="text-sm text-muted-foreground">
                {t("sra.widgetDescription")}
              </Typography.Text>
            </div>
            <div>
              <SoyMutDbWidget name="sra_run" params={{ run: activeRun }} key={activeRun} />
            </div>
          </Card>
        </FadeUp>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Run details card                                                  */
/* ------------------------------------------------------------------ */

function RunDetails({ run, source, isCached }: { run: SraRunInfo; source?: string; isCached: boolean }) {
  const { t } = useTranslation();
  const stats: { icon: React.ElementType; label: string; value: string }[] = [
    { icon: Dna, label: t("sra.stats.bases"), value: formatBases(run.bases) },
    { icon: Microscope, label: t("sra.stats.spots"), value: formatSpots(run.spots) },
    { icon: HardDrive, label: t("sra.stats.size"), value: formatSize(run.size_MB) },
    { icon: Clock, label: t("sra.stats.averageLength"), value: run.avgLength ? `${run.avgLength} bp` : "—" },
  ];

  return (
    <FadeUp>
      <Card>
        <div>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <Typography.Title level={2} className="m-0 font-mono text-xl">{run.Run}</Typography.Title>
                {isCached && <Tag variant="outlined" className="text-xs">{t("sra.status.cached")}</Tag>}
                {source === "fallback" && <Tag className="text-xs">{t("sra.status.offline")}</Tag>}
                {source === "stub" && <Tag color="red" className="text-xs">{t("sra.status.stub")}</Tag>}
              </div>
              <Typography.Text>
                {run.ScientificName || run.SampleName || t("sra.defaultRunName")}
              </Typography.Text>
            </div>
            <a
              href={run.sra_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
            >
              {t("sra.openInNcbi")} <ExternalLink className="size-4" aria-hidden />
            </a>
          </div>
        </div>
        <div className="space-y-6">
          {/* Stat grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {stats.map((s) => (
              <div key={s.label} className="rounded-lg border bg-muted/30 p-3">
                <div className="flex items-center gap-1.5 text-sm text-muted-foreground mb-1">
                  <s.icon className="size-3.5" aria-hidden />
                  {s.label}
                </div>
                <div className="font-mono font-semibold text-sm">{s.value}</div>
              </div>
            ))}
          </div>

          {/* Detail rows */}
          <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <DetailRow label={t("sra.fields.experiment")} value={run.Experiment} mono />
            <DetailRow label={t("sra.fields.bioProject")} value={run.BioProject} mono />
            <DetailRow label={t("sra.fields.bioSample")} value={run.BioSample} mono />
            <DetailRow label={t("sra.fields.sample")} value={run.Sample || run.SampleName} mono />
            <DetailRow label={t("sra.fields.platform")} value={[run.Platform, run.Model].filter(Boolean).join(" — ")} />
            <DetailRow label={t("sra.fields.strategy")} value={run.LibraryStrategy} />
            <DetailRow label={t("sra.fields.source")} value={run.LibrarySource} />
            <DetailRow label={t("sra.fields.selection")} value={run.LibrarySelection} />
            <DetailRow label={t("sra.fields.layout")} value={run.LibraryLayout} />
            <DetailRow label={t("sra.fields.center")} value={run.CenterName} />
            <DetailRow label={t("sra.fields.released")} value={run.release_date_short || (run.ReleaseDate ? run.ReleaseDate.slice(0, 10) : "—")} />
            <DetailRow label={t("sra.fields.taxId")} value={run.TaxID} mono />
          </dl>

          {run.download_path && (
            <div>
              <a
                href={run.download_path}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm text-primary hover:underline"
              >
                <Download className="size-4" aria-hidden />
                {t("sra.downloadData")}
              </a>
            </div>
          )}
        </div>
      </Card>
    </FadeUp>
  );
}

function DetailRow({ label, value, mono }: { label: string; value?: string; mono?: boolean }) {
  return (
    <div className="flex gap-3 py-1 border-b border-border/50 last:border-0">
      <dt className="text-muted-foreground w-32 shrink-0 text-sm pt-0.5">{label}</dt>
      <dd className={`flex-1 min-w-0 text-sm ${mono ? "font-mono" : ""}`}>
        {value && value.trim() ? value : <span className="text-muted-foreground/60">—</span>}
      </dd>
    </div>
  );
}

function RunDetailsSkeleton() {
  return (
    <Card>
      <div>
        <Skeleton className="h-7 w-40 mb-2" />
        <Skeleton className="h-4 w-72" />
      </div>
      <div className="space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-16 w-full" />)}
        </div>
        <div className="space-y-2">
          {[1, 2, 3, 4, 5, 6].map((i) => <Skeleton key={i} className="h-5 w-full" />)}
        </div>
      </div>
    </Card>
  );
}
