import { lazy, Suspense } from "react";
import { useTranslation } from "react-i18next";
import { formatNumber } from "../../lib/format";
import { useDashboardData, type ImportThroughputPoint } from "../../lib/dashboard";
import { Alert, Button, Card, Col, PageContainer, ProTable, Row, Statistic, type ProColumns } from "@/lib/antd";

const ImportThroughputChart = lazy(() => import("../../components/charts/import-throughput").then((m) => ({ default: m.ImportThroughputChart })));
const QueryLatencyChart = lazy(() => import("../../components/charts/query-latency").then((m) => ({ default: m.QueryLatencyChart })));
const StorageGrowthChart = lazy(() => import("../../components/charts/storage-growth").then((m) => ({ default: m.StorageGrowthChart })));

function ChartLoading() {
  return <div className="h-80 animate-pulse rounded-lg border border-border bg-muted/40" />;
}

/** Analysis workbench: import throughput, query latency and storage trends. */
export default function DashboardAnalysisPage() {
  const { t } = useTranslation();
  const data = useDashboardData();
  const { homepage, stats, series, importThroughput, queryLatency, storageGrowth } = data;
  const pending = homepage.isPending || stats.isPending;
  const failed = homepage.isError || stats.isError || series.isError;

  const columns: ProColumns<ImportThroughputPoint>[] = [
    { title: t("admin.analysis.date", { defaultValue: "Date" }), dataIndex: "date", valueType: "date" },
    { title: t("admin.analysis.imported", { defaultValue: "Imported" }), dataIndex: "imported", valueType: "digit" },
    { title: t("admin.analysis.failed", { defaultValue: "Failed" }), dataIndex: "failed", valueType: "digit" },
  ];

  return (
    <PageContainer
      title={t("admin.analysis.title", { defaultValue: "Analysis" })}
      subTitle={t("admin.analysis.subtitle", { defaultValue: "Import throughput and query performance over time." })}
      extra={
        <Button
          onClick={() => {
            void homepage.refetch();
            void stats.refetch();
            void series.refetch();
          }}
          loading={series.isFetching || stats.isFetching}
        >
          {t("common.refresh", { defaultValue: "Refresh" })}
        </Button>
      }
    >
      <div className="space-y-4">
        {failed ? (
          <Alert
            type="error"
            showIcon
            title={t("admin.dashboard.metricsUnavailable", { defaultValue: "Dashboard metrics unavailable" })}
            description={t("admin.dashboard.metricsUnavailableDesc", { defaultValue: "The API did not return a current metric snapshot; no placeholder values are shown." })}
          />
        ) : null}

        <Row gutter={[16, 16]} data-testid="analysis-stats" data-pending={String(pending)}>
          {[
            { key: "imported", label: t("admin.analysis.totalImported", { defaultValue: "Records imported" }), value: importThroughput.reduce((sum, point) => sum + point.imported, 0) },
            { key: "failed", label: t("admin.analysis.totalFailed", { defaultValue: "Failed records" }), value: importThroughput.reduce((sum, point) => sum + point.failed, 0) },
            { key: "p95", label: t("admin.dashboard.queryP95", { defaultValue: "Query P95" }), value: stats.data?.queryP95Ms ?? 0, suffix: "ms" },
            { key: "variants", label: t("admin.totalVariants", { defaultValue: "Total Variants" }), value: homepage.data?.total_variants ?? stats.data?.totalVariants ?? 0 },
          ].map((metric) => (
            <Col key={metric.key} xs={24} sm={12} xl={6}>
              <Card>
                <Statistic
                  title={metric.label}
                  value={pending || series.isPending ? "…" : failed ? "—" : formatNumber(metric.value)}
                  suffix={metric.suffix}
                />
              </Card>
            </Col>
          ))}
        </Row>

        <Row gutter={[16, 16]}>
          <Col xs={24} xl={12}>
            <Suspense fallback={<ChartLoading />}>
              <ImportThroughputChart data={series.isPending ? [] : importThroughput} />
            </Suspense>
          </Col>
          <Col xs={24} xl={12}>
            <Suspense fallback={<ChartLoading />}>
              <QueryLatencyChart data={series.isPending ? [] : queryLatency} />
            </Suspense>
          </Col>
        </Row>

        {!series.isPending && storageGrowth.length > 0 ? (
          <Suspense fallback={<ChartLoading />}>
            <StorageGrowthChart data={storageGrowth} />
          </Suspense>
        ) : null}

        <ProTable<ImportThroughputPoint>
          headerTitle={t("admin.analysis.throughputDetail", { defaultValue: "Import throughput detail" })}
          rowKey="date"
          search={false}
          options={false}
          pagination={false}
          loading={series.isPending}
          dataSource={importThroughput}
          columns={columns}
        />
      </div>
    </PageContainer>
  );
}