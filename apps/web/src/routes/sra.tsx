/**
 * SRA Run Browser — query NCBI Sequence Read Archive metadata by
 * accession number, visualise run stats, browse curated runs for the default species (soybean).
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import {
  Search,
  Database,
  ExternalLink,
  History,
  RefreshCw,
  AlertTriangle,
  Download,
  Dna,
  Clock,
  HardDrive,
  Microscope,
  ChevronRight,
  Trash2,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
  Input,
  Button,
  Skeleton,
  Badge,
  EmptyState,
} from "@soymutdb/ui";
import { fetchSraRun, fetchSraSamples, type SraRunInfo } from "@soymutdb/api-client";
import { FadeUp, useReveal } from "../components/route-motion";
import { startViewTransition } from "../lib/view-transitions";

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
    document.title = "SRA Run Browser — SoyMutDB";
  }, []);

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

  return (
    <div ref={rootRef} className="container-prose py-8 md:py-12">
      <FadeUp stagger={0.05}>
        <div className="mb-8">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
            <Database className="size-4" />
            <span>SRA Run Browser</span>
            <span className="text-border">/</span>
            <span>NCBI Sequence Read Archive</span>
          </div>
          <h1 className="font-display text-3xl md:text-4xl font-bold tracking-tight">
            SRA Run Metadata Browser
          </h1>
          <p className="mt-2 text-muted-foreground max-w-2xl">
            Look up sequencing run metadata from the NCBI Sequence Read Archive (SRA).
            Enter a run accession (SRR/DRR/ERR) to view library details, platform,
            and data provenance.
          </p>
        </div>
      </FadeUp>

      {/* Search input */}
      <FadeUp delay={0.1}>
        <form onSubmit={submit} className="mb-6">
          <div className="flex gap-2 max-w-xl">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground pointer-events-none" />
              <Input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="e.g. SRR30334525"
                className="pl-9 font-mono"
                spellCheck={false}
                autoCapitalize="off"
                aria-label="SRA accession"
              />
            </div>
            <Button type="submit" disabled={runQuery.isFetching}>
              {runQuery.isFetching ? (
                <RefreshCw className="size-4 mr-1 animate-spin" />
              ) : (
                <Search className="size-4 mr-1" />
              )}
              Load
            </Button>
          </div>
        </form>
      </FadeUp>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main panel — run details */}
        <div className="lg:col-span-2 space-y-4">
          {runQuery.isLoading && <RunDetailsSkeleton />}
          {runQuery.isError && !run && (
            <EmptyState
              icon={AlertTriangle}
              title="Failed to load run"
              description={runQuery.error?.message || "Could not fetch SRA metadata. Check the accession and try again."}
              action={<Button onClick={() => runQuery.refetch()}><RefreshCw className="size-4 mr-1" />Retry</Button>}
            />
          )}
          {run && <RunDetails run={run} source={source} isCached={!!isCached} />}
        </div>

        {/* Sidebar — history + curated samples */}
        <div className="space-y-6">
          {/* History */}
          <FadeUp delay={0.15}>
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm flex items-center gap-2">
                  <History className="size-4" />
                  Recent Runs
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                {history.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No recent accessions.</p>
                ) : (
                  <div className="space-y-1">
                    {history.map((acc) => (
                      <button
                        key={acc}
                        onClick={() => pickRun(acc)}
                        className={`w-full text-left px-2 py-1.5 rounded-md text-xs font-mono hover:bg-muted transition-colors flex items-center justify-between ${acc === activeRun ? "bg-primary/10 text-primary" : ""}`}
                      >
                        <span>{acc}</span>
                        <ChevronRight className="size-3 opacity-50" />
                      </button>
                    ))}
                    <button
                      onClick={onClearHistory}
                      className="w-full mt-2 text-[11px] text-muted-foreground hover:text-destructive flex items-center gap-1 justify-center py-1"
                    >
                      <Trash2 className="size-3" /> Clear history
                    </button>
                  </div>
                )}
              </CardContent>
            </Card>
          </FadeUp>

          {/* Curated runs — current default species (soybean) */}
          <FadeUp delay={0.2}>
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Dna className="size-4" />
                  Curated SRA Runs
                </CardTitle>
                <CardDescription className="text-xs">
                  Glycine max (soybean) sequencing runs — current default species
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-0">
                {samplesQuery.isLoading && (
                  <div className="space-y-2">
                    {[1, 2, 3].map((i) => <Skeleton key={i} className="h-8 w-full" />)}
                  </div>
                )}
                {samplesQuery.data?.samples && (
                  <div className="space-y-1 max-h-80 overflow-y-auto">
                    {samplesQuery.data.samples.map((s) => (
                      <button
                        key={s.Run}
                        onClick={() => pickRun(s.Run)}
                        className={`w-full text-left px-2 py-2 rounded-md hover:bg-muted transition-colors text-xs ${s.Run === activeRun ? "bg-primary/10 text-primary" : ""}`}
                      >
                        <div className="font-mono font-medium">{s.Run}</div>
                        <div className="text-[11px] text-muted-foreground truncate">
                          {s.LibraryStrategy || "RNA-Seq"} · {s.release_date_short || "—"} · {formatBases(s.bases)}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </FadeUp>
        </div>
      </div>

      {/* Use Web Component <soymutdb-widget> to embed the sra_run widget */}
      {activeRun && (
        <FadeUp delay={0.25} className="mt-8">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Rich Widget View</CardTitle>
              <CardDescription className="text-xs">
                Server-rendered widget with full run metadata (loaded via &lt;soymutdb-widget&gt; Web Component)
              </CardDescription>
            </CardHeader>
            <CardContent>
              {/* This is a Custom Element registered in soymutdb-widget.ts */}
              <soymutdb-widget
                name="sra_run"
                params={JSON.stringify({ run: activeRun })}
                key={activeRun}
              />
            </CardContent>
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
  const stats: { icon: React.ElementType; label: string; value: string }[] = [
    { icon: Dna, label: "Bases", value: formatBases(run.bases) },
    { icon: Microscope, label: "Spots", value: formatSpots(run.spots) },
    { icon: HardDrive, label: "Size", value: formatSize(run.size_MB) },
    { icon: Clock, label: "Avg Length", value: run.avgLength ? `${run.avgLength} bp` : "—" },
  ];

  return (
    <FadeUp>
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <CardTitle className="font-mono text-xl">{run.Run}</CardTitle>
                {isCached && <Badge variant="outline" className="text-[10px]">cached</Badge>}
                {source === "fallback" && <Badge variant="secondary" className="text-[10px]">offline</Badge>}
                {source === "stub" && <Badge variant="destructive" className="text-[10px]">stub</Badge>}
              </div>
              <CardDescription>
                {run.ScientificName || run.SampleName || "SRA sequencing run"}
              </CardDescription>
            </div>
            <a
              href={run.sra_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              Open in NCBI SRA <ExternalLink className="size-3" />
            </a>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Stat grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {stats.map((s) => (
              <div key={s.label} className="rounded-lg border bg-muted/30 p-3">
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
                  <s.icon className="size-3.5" />
                  {s.label}
                </div>
                <div className="font-mono font-semibold text-sm">{s.value}</div>
              </div>
            ))}
          </div>

          {/* Detail rows */}
          <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <DetailRow label="Experiment" value={run.Experiment} mono />
            <DetailRow label="BioProject" value={run.BioProject} mono />
            <DetailRow label="BioSample" value={run.BioSample} mono />
            <DetailRow label="Sample" value={run.Sample || run.SampleName} mono />
            <DetailRow label="Platform" value={[run.Platform, run.Model].filter(Boolean).join(" — ")} />
            <DetailRow label="Strategy" value={run.LibraryStrategy} />
            <DetailRow label="Source" value={run.LibrarySource} />
            <DetailRow label="Selection" value={run.LibrarySelection} />
            <DetailRow label="Layout" value={run.LibraryLayout} />
            <DetailRow label="Center" value={run.CenterName} />
            <DetailRow label="Released" value={run.release_date_short || (run.ReleaseDate ? run.ReleaseDate.slice(0, 10) : "—")} />
            <DetailRow label="TaxID" value={run.TaxID} mono />
          </dl>

          {run.download_path && (
            <div>
              <a
                href={run.download_path}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 text-sm text-primary hover:underline"
              >
                <Download className="size-4" />
                Download data from NCBI
              </a>
            </div>
          )}
        </CardContent>
      </Card>
    </FadeUp>
  );
}

function DetailRow({ label, value, mono }: { label: string; value?: string; mono?: boolean }) {
  return (
    <div className="flex gap-3 py-1 border-b border-border/50 last:border-0">
      <dt className="text-muted-foreground w-24 shrink-0 text-xs pt-0.5">{label}</dt>
      <dd className={`flex-1 min-w-0 ${mono ? "font-mono text-xs" : "text-sm"}`}>
        {value && value.trim() ? value : <span className="text-muted-foreground/60">—</span>}
      </dd>
    </div>
  );
}

function RunDetailsSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-7 w-40 mb-2" />
        <Skeleton className="h-4 w-72" />
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-16 w-full" />)}
        </div>
        <div className="space-y-2">
          {[1, 2, 3, 4, 5, 6].map((i) => <Skeleton key={i} className="h-5 w-full" />)}
        </div>
      </CardContent>
    </Card>
  );
}
