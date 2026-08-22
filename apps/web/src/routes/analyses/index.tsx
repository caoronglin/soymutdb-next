/**
 * Analyses index — recent analysis jobs for the current user.
 *
 * Data source: `GET /analyses?limit=50` (own jobs, newest first — added
 * alongside the Wave-1 single-job endpoints). When that endpoint is not yet
 * deployed (404), the page falls back to the browser's localStorage record
 * of submitted job ids and resolves each via `getAnalysis(jobId)`.
 */

import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { FlaskConical, ScanSearch, ArrowRight, FolderKanban } from "lucide-react";
import { PageHeader, Badge, Button, LoadingState, ErrorState } from "../../lib/web-ui";
import { getAnalysis, type AnalysesJobResponse, type AnalysisJobStatus } from "@soymutdb/api-client";
import { DataTable, type DataTableColumn } from "../../components/data-table";
import { ResearcherGate } from "../../components/analyses/researcher-gate";
import { secureHttp } from "../../lib/api";
import { readRecentJobs, forgetRecentJob } from "../../lib/analyses-local";
import { formatDate } from "../../lib/format";

export const Route = createFileRoute("/analyses/")({
  component: AnalysesIndexComponent,
});

/** Server list payload — mirrors AnalysesJobListResponse (added in this wave). */
interface AnalysisJobListResponse {
  items: AnalysisJobRow[];
}

/** Row shape — backend list payload mirrors AnalysesJobResponse. */
type AnalysisJobRow = AnalysesJobResponse & { job_id: string };

const STATUS_VARIANT: Record<AnalysisJobStatus, "default" | "secondary" | "destructive" | "outline" | "success" | "warning"> = {
  pending: "secondary",
  queued: "secondary",
  running: "default",
  succeeded: "success",
  failed: "destructive",
  cancel_requested: "warning",
  cancelled: "outline",
};

function statusLabel(status: AnalysisJobStatus): string {
  return status.replace("_", " ");
}

function AnalysesIndexComponent() {
  const navigate = useNavigate();

  const jobsQuery = useQuery({
    queryKey: ["analysis-jobs"],
    queryFn: async (): Promise<AnalysisJobRow[]> => {
      // Preferred: backend list endpoint (own jobs, newest first).
      try {
        const res = await secureHttp.get<AnalysisJobListResponse>("/analyses", {
          params: { limit: 50 },
        });
        if (res && Array.isArray(res.items) && res.items.length > 0) return res.items;
        // Empty server list is authoritative when the endpoint exists — but
        // we can't distinguish "endpoint missing" from "empty" on 200, so an
        // empty response still falls through to the local record below.
      } catch {
        // Endpoint not deployed yet — fall back to the local record.
      }
      // Fallback: localStorage recent job ids resolved individually.
      // TODO: remove once `GET /analyses` ships everywhere (local record
      // stays useful for cross-device anonymous previews).
      const jobs: AnalysisJobRow[] = [];
      for (const jobId of readRecentJobs()) {
        try {
          jobs.push(await getAnalysis(jobId));
        } catch {
          forgetRecentJob(jobId);
        }
      }
      return jobs;
    },
    staleTime: 30_000,
    retry: false,
  });

  const columns: DataTableColumn<AnalysisJobRow>[] = [
    {
      id: "job_id",
      header: "Job",
      cell: (row) => (
        <span className="font-mono text-xs text-muted-foreground">{row.job_id.slice(0, 8)}…</span>
      ),
    },
    {
      id: "analysis_type",
      header: "Pipeline",
      cell: (row) => (
        <span className="inline-flex items-center gap-1.5 capitalize">
          {row.analysis_type === "fastp" ? (
            <FlaskConical className="size-3.5 text-muted-foreground" aria-hidden />
          ) : (
            <ScanSearch className="size-3.5 text-muted-foreground" aria-hidden />
          )}
          {row.analysis_type}
        </span>
      ),
    },
    {
      id: "status",
      header: "Status",
      cell: (row) => (
        <Badge variant={STATUS_VARIANT[row.status] ?? "secondary"} className="text-[10px] uppercase">
          {statusLabel(row.status)}
        </Badge>
      ),
    },
    {
      id: "created_at",
      header: "Submitted",
      cell: (row) => <span className="text-muted-foreground">{formatDate(row.created_at)}</span>,
    },
    {
      id: "open",
      header: "",
      className: "w-12 text-right",
      cell: () => (
        <ArrowRight className="ml-auto size-4 text-muted-foreground transition-colors group-hover/row:text-primary" aria-hidden />
      ),
    },
  ];

  return (
    <div className="container-prose section-rhythm">
      <ResearcherGate>
        <PageHeader
          icon={FolderKanban}
          title="Analyze"
          description="Run RNA-seq quality control (fastp) and single-cell clustering (scanpy) pipelines on your uploaded data. Jobs run asynchronously; results appear here once finished."
          breadcrumb={[{ label: "Analyze" }]}
          actions={
            <>
              <Button asChild size="sm">
                <Link to="/analyses/fastp">
                  <FlaskConical className="size-4" aria-hidden />
                  New fastp job
                </Link>
              </Button>
              <Button asChild variant="outline" size="sm">
                <Link to="/analyses/scanpy">
                  <ScanSearch className="size-4" aria-hidden />
                  New scanpy job
                </Link>
              </Button>
            </>
          }
        />

        <div className="mt-8">
          {jobsQuery.isLoading ? (
            <LoadingState label="Loading analysis jobs…" rows={5} />
          ) : jobsQuery.isError ? (
            <ErrorState
              title="Could not load analysis jobs"
              message="The jobs service is unavailable. Please try again shortly."
              onRetry={() => void jobsQuery.refetch()}
            />
          ) : (
            <DataTable
              columns={columns}
              data={jobsQuery.data ?? []}
              ariaLabel="Recent analysis jobs"
              emptyTitle="No analysis jobs yet"
              emptyDescription="Submit a fastp or scanpy job to see it here."
              onRowClick={(row) => void navigate({ to: "/analyses/$jobId", params: { jobId: row.job_id } })}
            />
          )}
        </div>
      </ResearcherGate>
    </div>
  );
}
