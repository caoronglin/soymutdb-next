/**
 * Analysis job result page (`/analyses/$jobId`).
 *
 * Polls the job while it is queued/running (2.5s interval via TanStack
 * Query) and stops once it reaches a terminal state. Renders:
 *   - fastp:  HTML report (pre-signed iframe) + reads/bases/Q30/dup cards
 *   - scanpy: UMAP image + cluster sizes table + top markers table +
 *             markers.csv / annotated downloads
 *   - failed: error message + retry hint.
 *
 * Object keys inside `result` are resolved to pre-signed GET URLs through
 * `getAnalysisDownload` (server validates the `analyses/{job_id}/` prefix).
 */

import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { FlaskConical, ScanSearch, Loader2, CircleCheck, CircleX, Download, FileText, Database } from "lucide-react";
import { PageHeader, Card, CardHeader, CardTitle, CardDescription, CardContent, Badge, Button, LoadingState, ErrorState, StatCard } from "../../lib/web-ui";
import { getAnalysis, getAnalysisDownload, type AnalysesJobResponse } from "@soymutdb/api-client";
import { DataTable } from "../../components/data-table";
import { ResearcherGate } from "../../components/analyses/researcher-gate";
import { formatDate } from "../../lib/format";

export const Route = createFileRoute("/analyses/$jobId")({
  component: JobResultComponent,
});

const POLL_INTERVAL_MS = 2_500;
const ACTIVE_STATUSES = new Set(["pending", "queued", "running"]);

// ---------------------------------------------------------------------------
// Result-object extraction helpers
//
// The worker's exact `result_summary` shape is not finalised yet (W1-C/D), so
// lookups tolerate a few plausible placements — nested under `output`/`stats`
// or flat — and fall back to "not available" gracefully.
// ---------------------------------------------------------------------------

function firstOf(result: Record<string, unknown>, paths: string[][]): unknown {
  for (const path of paths) {
    let cur: unknown = result;
    let ok = true;
    for (const key of path) {
      if (cur && typeof cur === "object" && key in (cur as Record<string, unknown>)) {
        cur = (cur as Record<string, unknown>)[key];
      } else {
        ok = false;
        break;
      }
    }
    if (ok && cur !== undefined && cur !== null) return cur;
  }
  return undefined;
}

function asString(v: unknown): string | undefined {
  return typeof v === "string" && v.length > 0 ? v : undefined;
}

function asNumber(v: unknown): number | undefined {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))) return Number(v);
  return undefined;
}

function percent(v: number | undefined): string {
  return v === undefined ? "—" : `${(v * 100).toFixed(1)}%`;
}

function fmtInt(v: number | undefined): string {
  return v === undefined ? "—" : v.toLocaleString("en-US");
}

// ---------------------------------------------------------------------------
// Components
// ---------------------------------------------------------------------------

function StatusBadge({ job }: { job: AnalysesJobResponse }) {
  if (job.status === "succeeded") {
    return (
      <Badge variant="success" className="gap-1 uppercase">
        <CircleCheck className="size-3" aria-hidden /> Succeeded
      </Badge>
    );
  }
  if (job.status === "failed") {
    return (
      <Badge variant="destructive" className="gap-1 uppercase">
        <CircleX className="size-3" aria-hidden /> Failed
      </Badge>
    );
  }
  if (ACTIVE_STATUSES.has(job.status)) {
    return (
      <Badge variant="default" className="gap-1 uppercase">
        <Loader2 className="size-3 animate-spin" aria-hidden /> {job.status}
      </Badge>
    );
  }
  return <Badge variant="secondary" className="uppercase">{job.status.replace("_", " ")}</Badge>;
}

function JobResultComponent() {
  const { jobId } = Route.useParams();

  const jobQuery = useQuery({
    queryKey: ["analysis-job", jobId],
    queryFn: () => getAnalysis(jobId),
    refetchInterval: (query) =>
      ACTIVE_STATUSES.has(query.state.data?.status ?? "") ? POLL_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
    retry: 1,
  });

  const job = jobQuery.data;

  // Pre-signed GET URL for a job result object (only resolved for success).
  const useDownloadUrl = (objectKey: string | undefined) =>
    useQuery({
      queryKey: ["analysis-download", jobId, objectKey ?? ""],
      queryFn: () => getAnalysisDownload(jobId, objectKey as string),
      enabled: Boolean(objectKey && job?.status === "succeeded"),
      staleTime: 5 * 60 * 1000,
      retry: false,
    });

  const result = job?.status === "succeeded" && job.result ? job.result : null;

  // --- fastp: report html key + summary stats ---------------------------------
  const fastpHtmlKey = result
    ? asString(firstOf(result, [["output", "html"], ["html"], ["report_html"], ["output", "report", "html"]]))
    : undefined;
  const fastpHtml = useDownloadUrl(fastpHtmlKey);
  const fastpStats = {
    reads: asNumber(firstOf(result ?? {}, [["stats", "reads_total"], ["reads_total"], ["stats", "total_reads"], ["total_reads"]])),
    bases: asNumber(firstOf(result ?? {}, [["stats", "bases_total"], ["bases_total"], ["stats", "total_bases"], ["total_bases"]])),
    q30: asNumber(firstOf(result ?? {}, [["stats", "q30_rate"], ["q30_rate"], ["stats", "q30"], ["q30"]])),
    duplication: asNumber(firstOf(result ?? {}, [["stats", "duplication_rate"], ["duplication_rate"], ["dup_rate"], ["stats", "dup_rate"]])),
  };

  // --- scanpy: umap + tables + downloads --------------------------------------
  const umapKey = result
    ? asString(firstOf(result, [["output", "umap", "png"], ["umap", "png"], ["umap_png"], ["umap"]]))
    : undefined;
  const umap = useDownloadUrl(umapKey);
  const markersCsvKey = result
    ? asString(firstOf(result, [["output", "markers", "csv"], ["markers", "csv"], ["markers_csv"]]))
    : undefined;
  const markersCsv = useDownloadUrl(markersCsvKey);
  const annotatedKey = result
    ? asString(firstOf(result, [["annotated", "h5ad"], ["annotated"], ["annotated_h5ad"]]))
    : undefined;
  const annotated = useDownloadUrl(annotatedKey);

  const clusterSizes = React.useMemo(() => {
    const raw = firstOf(result ?? {}, [["cluster_sizes"], ["output", "cluster_sizes"]]) as unknown;
    if (!Array.isArray(raw)) return [];
    return raw
      .map((row, i) => {
        const r = (row ?? {}) as Record<string, unknown>;
        return {
          cluster: asString(r.cluster) ?? String(i),
          nCells: asNumber(r.n_cells) ?? asNumber(r.size) ?? asNumber(r.count) ?? undefined,
        };
      })
      .sort((a, b) => (a.cluster < b.cluster ? -1 : 1));
  }, [result]);

  const topMarkers = React.useMemo(() => {
    const raw = firstOf(result ?? {}, [["top_markers"], ["output", "top_markers"]]) as unknown;
    if (!Array.isArray(raw)) return [];
    return raw
      .map((row) => {
        const r = (row ?? {}) as Record<string, unknown>;
        return {
          gene: asString(r.gene) ?? asString(r.gene_id) ?? "—",
          cluster: asString(r.cluster) ?? "—",
          avgLog2fc: asNumber(r.avg_log2fc) ?? asNumber(r.log2fc) ?? undefined,
          pct1: asNumber(r.pct_1) ?? asNumber(r.pct1) ?? undefined,
          pct2: asNumber(r.pct_2) ?? asNumber(r.pct2) ?? undefined,
          pvalAdj: asNumber(r.pval_adj) ?? asNumber(r.pval) ?? undefined,
        };
      })
      .slice(0, 100);
  }, [result]);

  if (jobQuery.isLoading) {
    return (
      <div className="container-prose section-rhythm">
        <ResearcherGate>
          <PageHeader icon={FlaskConical} title="Analysis job" breadcrumb={[{ label: "Analyze", href: "/analyses" }, { label: "Job" }]} />
          <LoadingState label="Loading job…" variant="spinner" className="py-24" />
        </ResearcherGate>
      </div>
    );
  }

  if (jobQuery.isError || !job) {
    return (
      <div className="container-prose section-rhythm">
        <ResearcherGate>
          <PageHeader icon={FlaskConical} title="Analysis job" breadcrumb={[{ label: "Analyze", href: "/analyses" }, { label: "Job" }]} />
          <ErrorState
            title="Could not load this job"
            message="The job may have been removed, or the job service is unavailable."
            onRetry={() => void jobQuery.refetch()}
          />
        </ResearcherGate>
      </div>
    );
  }

  const isFastp = job.analysis_type === "fastp";
  const retryTo = isFastp ? "/analyses/fastp" : "/analyses/scanpy";

  return (
    <div className="container-prose section-rhythm">
      <ResearcherGate>
        <PageHeader
          icon={isFastp ? FlaskConical : ScanSearch}
          title={`${isFastp ? "fastp" : "scanpy"} job`}
          description={`Job ${job.job_id.slice(0, 8)}… · submitted ${formatDate(job.created_at)}`}
          breadcrumb={[{ label: "Analyze", href: "/analyses" }, { label: job.job_id.slice(0, 8) }]}
          actions={<StatusBadge job={job} />}
        />

        {ACTIVE_STATUSES.has(job.status) ? (
          <Card className="mt-8">
            <CardContent className="flex items-center gap-3 py-6">
              <Loader2 className="size-5 animate-spin text-primary" aria-hidden />
              <div>
                <p className="text-sm font-medium">
                  {job.status === "queued" ? "Job queued — waiting for a worker…" : job.status === "pending" ? "Job pending…" : "Job running — this can take a few minutes…"}
                </p>
                <p className="text-xs text-muted-foreground">This page refreshes automatically every {POLL_INTERVAL_MS / 1000}s. You can leave and come back later.</p>
              </div>
            </CardContent>
          </Card>
        ) : null}

        {job.status === "failed" ? (
          <Card className="mt-8 border-destructive/40">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-destructive">
                <CircleX className="size-5" aria-hidden />
                Job failed
              </CardTitle>
              <CardDescription>The pipeline stopped with an error.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4">
              <pre className="overflow-x-auto rounded-lg border bg-muted/40 p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap">
                {job.error_message ?? "No error message provided."}
              </pre>
              <div>
                <Button asChild size="sm" variant="outline">
                  <Link to={retryTo}>Re-submit a {isFastp ? "fastp" : "scanpy"} job</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        ) : null}

        {job.status === "succeeded" && result ? (
          <>
            {isFastp ? (
              <>
                <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <StatCard label="Total reads" value={fmtInt(fastpStats.reads)} />
                  <StatCard label="Total bases" value={fmtInt(fastpStats.bases)} />
                  <StatCard label="Q30 bases" value={percent(fastpStats.q30)} />
                  <StatCard label="Duplication" value={percent(fastpStats.duplication)} />
                </div>

                {fastpHtmlKey ? (
                  <Card className="mt-6">
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2 text-sm">
                        <FileText className="size-4 text-primary" aria-hidden />
                        fastp HTML report
                      </CardTitle>
                      <CardDescription>Opens below (rendered from the job's stored report).</CardDescription>
                    </CardHeader>
                    <CardContent>
                      {fastpHtml.isLoading ? (
                        <LoadingState label="Preparing report…" variant="spinner" className="py-16" />
                      ) : fastpHtml.error || !fastpHtml.data ? (
                        <p className="py-10 text-center text-sm text-muted-foreground">
                          Report unavailable at the moment — try again later.
                        </p>
                      ) : (
                        <iframe
                          title="fastp HTML report"
                          src={fastpHtml.data.download_url}
                          sandbox=""
                          className="h-[75vh] w-full rounded-lg border bg-white"
                        />
                      )}
                    </CardContent>
                  </Card>
                ) : null}
              </>
            ) : (
              <>
                {umapKey ? (
                  <Card className="mt-8">
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2 text-sm">
                        <ScanSearch className="size-4 text-primary" aria-hidden />
                        UMAP projection
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      {umap.isLoading ? (
                        <LoadingState label="Loading UMAP…" variant="spinner" className="py-16" />
                      ) : umap.error || !umap.data ? (
                        <p className="py-10 text-center text-sm text-muted-foreground">UMAP unavailable.</p>
                      ) : (
                        <img
                          src={umap.data.download_url}
                          alt="Scanpy UMAP projection coloured by cluster"
                          className="mx-auto max-h-[70vh] w-auto max-w-full rounded-lg border bg-white"
                        />
                      )}
                    </CardContent>
                  </Card>
                ) : null}

                <div className="mt-6 grid gap-6 lg:grid-cols-2">
                  <Card>
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2 text-sm">
                        <Database className="size-4 text-primary" aria-hidden />
                        Cluster sizes
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      {clusterSizes.length > 0 ? (
                        <DataTable
                          columns={[
                            { id: "cluster", header: "Cluster", cell: (r) => <span className="font-mono text-xs">{r.cluster}</span> },
                            { id: "n", header: "Cells", numeric: true, cell: (r) => fmtInt(r.nCells) },
                          ]}
                          data={clusterSizes}
                          ariaLabel="Cluster sizes"
                        />
                      ) : (
                        <p className="py-6 text-center text-sm text-muted-foreground">No cluster size data in the result.</p>
                      )}
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2 text-sm">
                        <ScanSearch className="size-4 text-primary" aria-hidden />
                        Top marker genes
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      {topMarkers.length > 0 ? (
                        <DataTable
                          columns={[
                            { id: "gene", header: "Gene", cell: (r) => <span className="font-mono text-xs">{r.gene}</span> },
                            { id: "cluster", header: "Cluster", cell: (r) => <span className="font-mono text-xs">{r.cluster}</span> },
                            { id: "lfc", header: "Log₂FC", numeric: true, cell: (r) => (r.avgLog2fc === undefined ? "—" : r.avgLog2fc.toFixed(2)) },
                            { id: "pct1", header: "% expr. 1", numeric: true, cell: (r) => (r.pct1 === undefined ? "—" : `${(r.pct1 * 100).toFixed(0)}%`) },
                            { id: "pct2", header: "% expr. 2", numeric: true, cell: (r) => (r.pct2 === undefined ? "—" : `${(r.pct2 * 100).toFixed(0)}%`) },
                            { id: "pval", header: "Adj. p", numeric: true, cell: (r) => (r.pvalAdj === undefined ? "—" : r.pvalAdj.toExponential(1)) },
                          ]}
                          data={topMarkers}
                          ariaLabel="Top marker genes"
                        />
                      ) : (
                        <p className="py-6 text-center text-sm text-muted-foreground">No marker gene data in the result.</p>
                      )}
                    </CardContent>
                  </Card>
                </div>

                {markersCsvKey || annotatedKey ? (
                  <Card className="mt-6">
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2 text-sm">
                        <Download className="size-4 text-primary" aria-hidden />
                        Downloads
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="flex flex-wrap gap-2">
                      {markersCsvKey ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={markersCsv.isLoading}
                          onClick={() => markersCsv.data && window.open(markersCsv.data.download_url, "_blank", "noopener")}
                        >
                          <Download className="size-4" aria-hidden />
                          markers.csv
                        </Button>
                      ) : null}
                      {annotatedKey ? (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={annotated.isLoading}
                          onClick={() => annotated.data && window.open(annotated.data.download_url, "_blank", "noopener")}
                        >
                          <Download className="size-4" aria-hidden />
                          annotated .h5ad
                        </Button>
                      ) : null}
                    </CardContent>
                  </Card>
                ) : null}
              </>
            )}
          </>
        ) : null}

        {!ACTIVE_STATUSES.has(job.status) && job.status !== "succeeded" && job.status !== "failed" ? (
          <p className="mt-8 text-center text-sm text-muted-foreground">Job status: {job.status}.</p>
        ) : null}
      </ResearcherGate>
    </div>
  );
}
