/**
 * Analyses index — recent analysis jobs for the current user.
 *
 * Data source: `GET /analyses?limit=50` (own jobs, newest first). The endpoint
 * is the only source: a browser-side job-id cache previously shadowed an empty
 * or failed response, which could show another account's jobs on a shared
 * browser and hide backend errors.
 */

import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
import { ExperimentOutlined, ScanOutlined, ArrowRightOutlined, FolderOpenOutlined } from "@ant-design/icons";
import { Breadcrumb, Button, Result, Skeleton, Tag, Typography } from "@/lib/antd";
import { type AnalysesJobResponse, type AnalysisJobStatus } from "@soymutdb/api-client";
import { DataTable, type DataTableColumn } from "../../components/data-table";
import { ResearcherGate } from "../../components/analyses/researcher-gate";
import { secureHttp } from "../../lib/api";
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

function statusColor(v: "default" | "secondary" | "destructive" | "outline" | "success" | "warning"): string {
  switch (v) {
    case "success":
      return "success";
    case "destructive":
      return "error";
    case "warning":
      return "warning";
    default:
      return "default";
  }
}

function statusLabel(status: AnalysisJobStatus): string {
  return status.replace("_", " ");
}

function AnalysesIndexComponent() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <div className="container-prose section-rhythm">
      <ResearcherGate>
        <header className="flex flex-col gap-4">
          <Breadcrumb items={[{ title: t("analyses.title") }]} />
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-start gap-3.5">
              <span className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-border bg-card shadow-sm">
                <FolderOpenOutlined className="size-5" aria-hidden />
              </span>
              <div>
                <Typography.Title level={1} className="mb-0">
                  {t("analyses.title")}
                </Typography.Title>
                <Typography.Paragraph type="secondary" style={{ margin: 0, maxWidth: "52rem" }}>
                  {t("analyses.indexIntro")}
                </Typography.Paragraph>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2 lg:shrink-0">
              <Button
                size="small"
                type="primary"
                icon={<ExperimentOutlined aria-hidden />}
                onClick={() => navigate({ to: "/analyses/fastp" })}
              >
                {t("analyses.newFastp")}
              </Button>
              <Button
                size="small"
                variant="outlined"
                icon={<ScanOutlined aria-hidden />}
                onClick={() => navigate({ to: "/analyses/scanpy" })}
              >
                {t("analyses.newScanpy")}
              </Button>
            </div>
          </div>
        </header>
        {/* The job list is a CHILD of the gate on purpose: mounting the query
            above the gate made every anonymous visitor issue a personal
            `GET /api/v1/analyses` (401 + refresh attempts) before the
            research-access state rendered. The module's contract is that an
            anonymous visitor issues zero personal requests. */}
        <AnalysesJobList />
      </ResearcherGate>
    </div>
  );
}

function AnalysesJobList() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const jobsQuery = useQuery({
    queryKey: ["analysis-jobs"],
    queryFn: async (): Promise<AnalysisJobRow[]> => {
      const res = await secureHttp.get<AnalysisJobListResponse>("/analyses", {
        params: { limit: 50 },
      });
      return res.items;
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
            <ExperimentOutlined className="size-3.5 text-muted-foreground" aria-hidden />
          ) : (
            <ScanOutlined className="size-3.5 text-muted-foreground" aria-hidden />
          )}
          {row.analysis_type}
        </span>
      ),
    },
    {
      id: "status",
      header: "Status",
      cell: (row) => (
        <Tag color={statusColor(STATUS_VARIANT[row.status] ?? "secondary")} className="text-[10px] uppercase">
          {statusLabel(row.status)}
        </Tag>
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
        <ArrowRightOutlined className="ml-auto size-4 text-muted-foreground transition-colors group-hover/row:text-primary" aria-hidden />
      ),
    },
  ];

  return (
        <div className="mt-8">
          {jobsQuery.isLoading ? (
            <Skeleton active paragraph={{ rows: 5 }} />
          ) : jobsQuery.isError ? (
            <Result
              status="error"
              title={t("analyses.jobsErrorTitle")}
              subTitle={t("analyses.jobsErrorHint")}
              extra={
                <Button type="primary" onClick={() => void jobsQuery.refetch()}>
                  {t("common.retry")}
                </Button>
              }
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
  );
}
