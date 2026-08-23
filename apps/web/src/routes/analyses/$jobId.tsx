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

import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { ExperimentOutlined, ScanOutlined, LoadingOutlined, CheckCircleOutlined, CloseCircleOutlined, DownloadOutlined, FileTextOutlined, DatabaseOutlined } from "@ant-design/icons";
import { Breadcrumb, Button, Card, Result, Spin, Statistic, Tag, Typography } from "@/lib/antd";
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
      <Tag color="success" className="gap-1 uppercase">
        <CheckCircleOutlined className="size-3" aria-hidden /> Succeeded
      </Tag>
    );
  }
  if (job.status === "failed") {
    return (
      <Tag color="error" className="gap-1 uppercase">
        <CloseCircleOutlined className="size-3" aria-hidden /> Failed
      </Tag>
    );
  }
  if (ACTIVE_STATUSES.has(job.status)) {
    return (
      <Tag color="processing" className="gap-1 uppercase">
        <LoadingOutlined className="size-3 animate-spin" aria-hidden /> {job.status}
      </Tag>
    );
  }
  return <Tag className="uppercase">{job.status.replace("_", " ")}</Tag>;
}

function JobResultComponent() {
  const { jobId } = Route.useParams();
  const navigate = useNavigate();

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
          <header className="flex flex-col gap-4">
            <Breadcrumb items={[{ title: <Link to="/analyses">Analyze</Link> }, { title: "Job" }]} />
            <div className="flex items-start gap-3.5">
              <span className="flex size-11 items-center justify-center rounded-xl border bg-card shadow-sm"><ExperimentOutlined className="size-5" aria-hidden /></span>
              <Typography.Title level={2} style={{ margin: 0 }}>Analysis job</Typography.Title>
            </div>
          </header>
          <Spin tip="Loading job…" className="py-24" />
        </ResearcherGate>
      </div>
    );
  }

  if (jobQuery.isError || !job) {
    return (
      <div className="container-prose section-rhythm">
        <ResearcherGate>
          <header className="flex flex-col gap-4">
            <Breadcrumb items={[{ title: <Link to="/analyses">Analyze</Link> }, { title: "Job" }]} />
            <div className="flex items-start gap-3.5">
              <span className="flex size-11 items-center justify-center rounded-xl border bg-card shadow-sm"><ExperimentOutlined className="size-5" aria-hidden /></span>
              <Typography.Title level={2} style={{ margin: 0 }}>Analysis job</Typography.Title>
            </div>
          </header>
          <Result
            status="error"
            title="Could not load this job"
            subTitle="The job may have been removed, or the job service is unavailable."
            extra={
              <Button type="primary" onClick={() => void jobQuery.refetch()}>
                Retry
              </Button>
            }
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
        <header className="flex flex-col gap-4">
          <Breadcrumb items={[{ title: <Link to="/analyses">Analyze</Link> }, { title: job.job_id.slice(0, 8) }]} />
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-start gap-3.5">
              <span className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-border bg-card shadow-sm">
                {isFastp ? <ExperimentOutlined className="size-5" aria-hidden /> : <ScanOutlined className="size-5" aria-hidden />}
              </span>
              <div>
                <Typography.Title level={2} style={{ margin: 0 }}>
                  {isFastp ? "fastp" : "scanpy"} job
                </Typography.Title>
                <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
                  Job {job.job_id.slice(0, 8)}… · submitted {formatDate(job.created_at)}
                </Typography.Paragraph>
              </div>
            </div>
            <div className="lg:shrink-0"><StatusBadge job={job} /></div>
          </div>
        </header>

        {ACTIVE_STATUSES.has(job.status) ? (
          <Card className="mt-8">
            <div className="flex items-center gap-3 py-6">
              <LoadingOutlined className="size-5 animate-spin text-primary" aria-hidden />
              <div>
                <p className="text-sm font-medium">
                  {job.status === "queued" ? "Job queued — waiting for a worker…" : job.status === "pending" ? "Job pending…" : "Job running — this can take a few minutes…"}
                </p>
                <p className="text-xs text-muted-foreground">This page refreshes automatically every {POLL_INTERVAL_MS / 1000}s. You can leave and come back later.</p>
              </div>
            </div>
          </Card>
        ) : null}

        {job.status === "failed" ? (
          <Card
            className="mt-8"
            title={
              <span className="flex items-center gap-2 text-destructive">
                <CloseCircleOutlined className="size-5" aria-hidden />
                Job failed
              </span>
            }
          >
            <div className="gap-4" style={{ display: "grid", gap: 16 }}>
              <pre className="overflow-x-auto rounded-lg border bg-muted/40 p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap">
                {job.error_message ?? "No error message provided."}
              </pre>
              <div>
                <Button size="small" variant="outlined" onClick={() => navigate({ to: retryTo })}>
                  Re-submit a {isFastp ? "fastp" : "scanpy"} job
                </Button>
              </div>
            </div>
          </Card>
        ) : null}

        {job.status === "succeeded" && result ? (
          <>
            {isFastp ? (
              <>
                <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <Card><Statistic title="Total reads" value={fmtInt(fastpStats.reads)} /></Card>
                  <Card><Statistic title="Total bases" value={fmtInt(fastpStats.bases)} /></Card>
                  <Card><Statistic title="Q30 bases" value={percent(fastpStats.q30)} /></Card>
                  <Card><Statistic title="Duplication" value={percent(fastpStats.duplication)} /></Card>
                </div>

                {fastpHtmlKey ? (
                  <Card
                    className="mt-6"
                    title={
                      <span className="flex items-center gap-2 text-sm">
                        <FileTextOutlined className="size-4 text-primary" aria-hidden />
                        fastp HTML report
                      </span>
                    }
                  >
                    <div>
                      {fastpHtml.isLoading ? (
                        <Spin tip="Preparing report…" className="py-16" />
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
                    </div>
                  </Card>
                ) : null}
              </>
            ) : (
              <>
                {umapKey ? (
                  <Card
                    className="mt-8"
                    title={
                      <span className="flex items-center gap-2 text-sm">
                        <ScanOutlined className="size-4 text-primary" aria-hidden />
                        UMAP projection
                      </span>
                    }
                  >
                    <div>
                      {umap.isLoading ? (
                        <Spin tip="Loading UMAP…" className="py-16" />
                      ) : umap.error || !umap.data ? (
                        <p className="py-10 text-center text-sm text-muted-foreground">UMAP unavailable.</p>
                      ) : (
                        <img
                          src={umap.data.download_url}
                          alt="Scanpy UMAP projection coloured by cluster"
                          className="mx-auto max-h-[70vh] w-auto max-w-full rounded-lg border bg-white"
                        />
                      )}
                    </div>
                  </Card>
                ) : null}

                <div className="mt-6 grid gap-6 lg:grid-cols-2">
                  <Card
                    title={
                      <span className="flex items-center gap-2 text-sm">
                        <DatabaseOutlined className="size-4 text-primary" aria-hidden />
                        Cluster sizes
                      </span>
                    }
                  >
                    <div>
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
                    </div>
                  </Card>

                  <Card
                    title={
                      <span className="flex items-center gap-2 text-sm">
                        <ScanOutlined className="size-4 text-primary" aria-hidden />
                        Top marker genes
                      </span>
                    }
                  >
                    <div>
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
                    </div>
                  </Card>
                </div>

                {markersCsvKey || annotatedKey ? (
                  <Card
                    className="mt-6"
                    title={
                      <span className="flex items-center gap-2 text-sm">
                        <DownloadOutlined className="size-4 text-primary" aria-hidden />
                        Downloads
                      </span>
                    }
                  >
                    <div className="flex flex-wrap gap-2">
                      {markersCsvKey ? (
                        <Button
                          size="small"
                          variant="outlined"
                          disabled={markersCsv.isLoading}
                          onClick={() => markersCsv.data && window.open(markersCsv.data.download_url, "_blank", "noopener")}
                        >
                          <DownloadOutlined className="size-4" aria-hidden />
                          markers.csv
                        </Button>
                      ) : null}
                      {annotatedKey ? (
                        <Button
                          size="small"
                          variant="outlined"
                          disabled={annotated.isLoading}
                          onClick={() => annotated.data && window.open(annotated.data.download_url, "_blank", "noopener")}
                        >
                          <DownloadOutlined className="size-4" aria-hidden />
                          annotated .h5ad
                        </Button>
                      ) : null}
                    </div>
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
