import { lazy, Suspense } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ReloadOutlined } from "@ant-design/icons";
import { adminImportsApi, type ImportTask } from "@soymutdb/api-client";
import { formatNumber } from "../../lib/format";
import { useDashboardData } from "../../lib/dashboard";
import { Alert, Badge, Button, Card, Col, PageContainer, ProTable, Row, Statistic, Tag, type ProColumns } from "@/lib/antd";

const QueryLatencyChart = lazy(() => import("../../components/charts/query-latency").then((m) => ({ default: m.QueryLatencyChart })));
const ImportThroughputChart = lazy(() => import("../../components/charts/import-throughput").then((m) => ({ default: m.ImportThroughputChart })));

function ChartLoading() {
  return <div className="h-80 animate-pulse rounded-lg border border-border bg-muted/40" />;
}

const ACTIVE_STATUSES = new Set(["running", "queued", "pending"]);

const STATUS_COLOR: Record<string, string> = {
  completed: "success",
  running: "processing",
  queued: "default",
  pending: "default",
  failed: "error",
  cancelled: "warning",
};

/** Monitor workbench: a live, auto-refreshing view of pipeline and query health. */
export default function DashboardMonitorPage() {
  const { t } = useTranslation();
  const { homepage, stats, series, importThroughput, queryLatency } = useDashboardData(30_000);

  const recentImports = useQuery({
    queryKey: ["admin-dashboard-recent-imports"],
    queryFn: () => adminImportsApi.list({ page: 1, page_size: 8 }),
    refetchInterval: 30_000,
  });

  const serviceState = stats.isError || homepage.isError ? "error" : stats.isPending ? "pending" : "ok";
  const activeImports = (recentImports.data?.items ?? []).filter((task) => ACTIVE_STATUSES.has(task.status)).length;

  const columns: ProColumns<ImportTask>[] = [
    { title: t("admin.monitor.file", { defaultValue: "File" }), dataIndex: "filename", ellipsis: true },
    { title: t("admin.monitor.type", { defaultValue: "Type" }), dataIndex: "type", width: 110 },
    {
      title: t("admin.monitor.status", { defaultValue: "Status" }),
      dataIndex: "status",
      width: 120,
      render: (_, record) => <Tag color={STATUS_COLOR[record.status] ?? "default"}>{record.status}</Tag>,
    },
    { title: t("admin.monitor.records", { defaultValue: "Records" }), dataIndex: "total_records", valueType: "digit", width: 110 },
    { title: t("admin.monitor.submitted", { defaultValue: "Submitted" }), dataIndex: "submitted_at", valueType: "dateTime" },
  ];

  return (
    <PageContainer
      title={t("admin.monitor.title", { defaultValue: "Monitor" })}
      subTitle={t("admin.monitor.subtitle", { defaultValue: "Live pipeline and query health, refreshed every 30 seconds." })}
      extra={
        <Button
          icon={<ReloadOutlined aria-hidden />}
          onClick={() => {
            void homepage.refetch();
            void stats.refetch();
            void series.refetch();
            void recentImports.refetch();
          }}
          loading={stats.isFetching || recentImports.isFetching}
        >
          {t("common.refresh", { defaultValue: "Refresh" })}
        </Button>
      }
    >
      <div className="space-y-4">
        <Alert
          type={serviceState === "error" ? "error" : serviceState === "pending" ? "info" : "success"}
          showIcon
          title={
            serviceState === "error"
              ? t("admin.monitor.apiDown", { defaultValue: "Metrics API is not responding" })
              : serviceState === "pending"
                ? t("admin.monitor.apiChecking", { defaultValue: "Checking metrics API…" })
                : t("admin.monitor.apiHealthy", { defaultValue: "Metrics API is responding" })
          }
          description={t("admin.monitor.apiHint", { defaultValue: "The console refreshes automatically; use Refresh for an immediate snapshot." })}
        />

        <Row gutter={[16, 16]} data-testid="monitor-stats" data-pending={String(stats.isPending)}>
          <Col xs={24} sm={12} xl={6}>
            <Card>
              <Statistic
                title={t("admin.dashboard.queryP95", { defaultValue: "Query P95" })}
                value={stats.isPending ? "…" : stats.isError ? "—" : `${stats.data?.queryP95Ms ?? 0} ms`}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} xl={6}>
            <Card>
              <Statistic
                title={t("admin.monitor.activeReleases", { defaultValue: "Active releases" })}
                value={stats.isPending ? "…" : stats.isError ? "—" : formatNumber(stats.data?.activeReleases ?? 0)}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} xl={6}>
            <Card>
              <Statistic
                title={t("admin.monitor.activeImports", { defaultValue: "Active imports" })}
                value={recentImports.isPending ? "…" : activeImports}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} xl={6}>
            <Card>
              <Statistic
                title={t("admin.monitor.services", { defaultValue: "Service state" })}
                value={serviceState}
                formatter={() => (
                  <Badge
                    status={serviceState === "error" ? "error" : serviceState === "pending" ? "processing" : "success"}
                    text={
                      serviceState === "error"
                        ? t("admin.monitor.degraded", { defaultValue: "Degraded" })
                        : serviceState === "pending"
                          ? t("admin.monitor.checking", { defaultValue: "Checking" })
                          : t("admin.monitor.healthy", { defaultValue: "Healthy" })
                    }
                  />
                )}
              />
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]}>
          <Col xs={24} xl={12}>
            <Suspense fallback={<ChartLoading />}>
              <QueryLatencyChart data={series.isPending ? [] : queryLatency} />
            </Suspense>
          </Col>
          <Col xs={24} xl={12}>
            <Suspense fallback={<ChartLoading />}>
              <ImportThroughputChart data={series.isPending ? [] : importThroughput} />
            </Suspense>
          </Col>
        </Row>

        <ProTable<ImportTask>
          headerTitle={t("admin.monitor.recentImports", { defaultValue: "Recent import tasks" })}
          rowKey="id"
          search={false}
          options={false}
          pagination={false}
          loading={recentImports.isPending}
          dataSource={recentImports.data?.items ?? []}
          columns={columns}
        />
      </div>
    </PageContainer>
  );
}