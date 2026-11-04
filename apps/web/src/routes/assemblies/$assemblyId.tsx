/**
 * One assembly (`/assemblies/$assemblyId`).
 *
 * The counts come from the same per-assembly aggregate as the list page. The
 * chromosome table is the reason this page exists: an assembly with zero
 * chromosomes and an assembly that does not exist must not look the same.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  Card,
  Descriptions,
  Empty,
  Skeleton,
  Table,
  Tag,
  type TableColumnsType,
} from "@/lib/antd";
import { ArrowLeftOutlined as ArrowLeft } from "@ant-design/icons";
import type { AssemblyChromosome } from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { formatNumber, formatPosition } from "../../lib/format";
import { assemblyDetailQueryOptions } from "../../lib/query-options";
import { useReleaseId } from "../../lib/release-scope";
import { SITE_VARIANT } from "../../lib/site-variant";

export const Route = createFileRoute("/assemblies/$assemblyId")({
  component: AssemblyDetailComponent,
});

function AssemblyDetailComponent() {
  const { t } = useTranslation();
  const { assemblyId } = Route.useParams();
  const releaseId = useReleaseId();
  const query = useQuery(
    assemblyDetailQueryOptions({ assemblyId, releaseId, siteVariant: SITE_VARIANT }),
  );

  const columns: TableColumnsType<AssemblyChromosome> = [
    {
      title: t("assemblies.columns.chromosome"),
      dataIndex: "name",
      key: "name",
      render: (value: string) => <span className="font-mono text-sm">{value}</span>,
    },
    {
      title: t("assemblies.columns.length"),
      dataIndex: "length",
      key: "length",
      align: "right",
      render: (value: number) => formatPosition(value),
    },
  ];

  const back = (
    <Link to="/assemblies" className="mb-3 inline-flex items-center gap-1 text-sm">
      <ArrowLeft /> {t("assemblies.backToList")}
    </Link>
  );

  if (query.isPending) {
    return (
      <FadeUp>
        <Card>
          {back}
          <Skeleton active paragraph={{ rows: 6 }} />
        </Card>
      </FadeUp>
    );
  }

  if (query.isError || !query.data) {
    // The API answers 404 both for an unknown assembly and for one outside the
    // resolved release. Rendering "not found" for both keeps that boundary.
    return (
      <FadeUp>
        <Card>
          {back}
          <Empty description={t("assemblies.notFound")} />
        </Card>
      </FadeUp>
    );
  }

  const assembly = query.data;

  return (
    <FadeUp>
      <Card>
        {back}
        <h1 className="mb-1 flex items-center gap-2 font-mono text-xl">
          {assembly.name}
          {assembly.is_default ? <Tag color="blue">{t("assemblies.default")}</Tag> : null}
        </h1>
        <p className="mb-4 text-sm opacity-70">
          {assembly.species} · {assembly.version}
        </p>

        <Descriptions column={2} size="small" className="mb-4">
          <Descriptions.Item label={t("assemblies.columns.genes")}>
            {formatNumber(assembly.statistics.gene_count)}
          </Descriptions.Item>
          <Descriptions.Item label={t("assemblies.columns.transcripts")}>
            {formatNumber(assembly.statistics.transcript_count)}
          </Descriptions.Item>
          <Descriptions.Item label={t("assemblies.columns.chromosomes")}>
            {formatNumber(assembly.statistics.chromosome_count)}
          </Descriptions.Item>
          <Descriptions.Item label={t("assemblies.columns.length")}>
            {formatPosition(assembly.statistics.total_length)}
          </Descriptions.Item>
          <Descriptions.Item label={t("assemblies.columns.downloads")} span={2}>
            <span
              className="text-xs opacity-70"
              title={assembly.statistics.download_count_reason ?? undefined}
              data-download-count="unavailable"
            >
              {t("assemblies.downloadsNotRecorded")}
            </span>
          </Descriptions.Item>
          <Descriptions.Item label={t("assemblies.release")} span={2}>
            {assembly.release_version ?? t("assemblies.releaseUnavailable")}
          </Descriptions.Item>
        </Descriptions>

        {assembly.chromosomes.length === 0 ? (
          <Empty description={t("assemblies.noChromosomes")} />
        ) : (
          <Table
            rowKey={(row) => String(row.id)}
            columns={columns}
            dataSource={assembly.chromosomes}
            pagination={false}
            scroll={{ x: "max-content" }}
          />
        )}
      </Card>
    </FadeUp>
  );
}
