/**
 * Assemblies in the current release (`/assemblies`).
 *
 * Every count on this page comes from the API's own aggregate over rows that
 * carry an assembly id — never from a release-level counter. Two assemblies in
 * one release therefore show two different gene counts, which is the whole
 * point of the page: a reader comparing v4 and v5 must not be shown the same
 * number twice.
 *
 * Every count is an `AssemblyMetric`: a number, or "not counted" plus the
 * reason the aggregate could not answer. `download_count` is always the second
 * kind -- `download_files` has no assembly dimension -- and is never shown as 0
 * nor replaced by the release's download total.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Card, Empty, Skeleton, Table, Tag, type TableColumnsType } from "@/lib/antd";
import type { AssemblySummary } from "@soymutdb/api-client";
import { AssemblyMetricText } from "../../components/assembly-metric";
import { FadeUp } from "../../components/route-motion";
import { assemblyStatisticsQueryOptions } from "../../lib/query-options";
import { useReleaseId } from "../../lib/release-scope";
import { SITE_VARIANT } from "../../lib/site-variant";

export const Route = createFileRoute("/assemblies/")({
  component: AssembliesComponent,
});

function AssembliesComponent() {
  const { t } = useTranslation();
  const releaseId = useReleaseId();
  const query = useQuery(assemblyStatisticsQueryOptions({ releaseId, siteVariant: SITE_VARIANT }));

  const columns: TableColumnsType<AssemblySummary> = [
    {
      title: t("assemblies.columns.assembly"),
      dataIndex: "name",
      key: "name",
      render: (_value, row) => (
        <div className="flex flex-col">
          <Link
            to="/assemblies/$assemblyId"
            params={{ assemblyId: String(row.id) }}
            className="font-mono text-sm"
          >
            {row.name}
          </Link>
          <span className="text-xs opacity-70">{row.species}</span>
        </div>
      ),
    },
    {
      title: t("assemblies.columns.version"),
      dataIndex: "version",
      key: "version",
      render: (value: string, row) => (
        <span className="flex items-center gap-2 font-mono text-xs">
          {value}
          {row.is_default ? <Tag color="blue">{t("assemblies.default")}</Tag> : null}
        </span>
      ),
    },
    {
      title: t("assemblies.columns.genes"),
      key: "gene_count",
      align: "right",
      render: (_value, row) => <AssemblyMetricText metric={row.statistics.gene_count} />,
    },
    {
      title: t("assemblies.columns.transcripts"),
      key: "transcript_count",
      align: "right",
      render: (_value, row) => <AssemblyMetricText metric={row.statistics.transcript_count} />,
    },
    {
      title: t("assemblies.columns.chromosomes"),
      key: "chromosome_count",
      align: "right",
      render: (_value, row) => (
        <AssemblyMetricText metric={row.statistics.chromosome_count} />
      ),
    },
    {
      title: t("assemblies.columns.length"),
      key: "total_length",
      align: "right",
      render: (_value, row) => (
        <AssemblyMetricText metric={row.statistics.total_length} basePairs />
      ),
    },
    {
      title: t("assemblies.columns.downloads"),
      key: "download_count",
      align: "right",
      render: (_value, row) => <AssemblyMetricText metric={row.statistics.download_count} />,
    },
  ];

  return (
    <FadeUp>
      <Card>
        <h1 className="mb-1 text-xl">{t("assemblies.title")}</h1>
        <p className="mb-4 text-sm opacity-70">{t("assemblies.subtitle")}</p>
        {query.isPending ? (
          <Skeleton active paragraph={{ rows: 6 }} />
        ) : query.isError ? (
          <Empty description={t("assemblies.loadFailed")} />
        ) : query.data.length === 0 ? (
          <Empty description={t("assemblies.empty")} />
        ) : (
          <Table
            rowKey={(row) => String(row.id)}
            columns={columns}
            dataSource={query.data}
            pagination={false}
            scroll={{ x: "max-content" }}
          />
        )}
      </Card>
    </FadeUp>
  );
}
