/**
 * Phenotypes of one mutant line (`/phenotypes/$lineId`).
 *
 * A deep link from the browser table lands here, so a trait row can be cited
 * with its line and its observations in one URL. The line id in the path is the
 * **public** id — the same value the line detail page and the API accept; the
 * internal key is never accepted or produced.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Descriptions,
  Empty,
  Skeleton,
  Table,
  Tag,
  type TableColumnsType,
} from "@/lib/antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import {
  getMutantLine,
  getMutantLinePhenotypes,
  isMutantLineId,
  type PhenotypeResponse,
} from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { queryKeys } from "../../lib/query-keys";
import { useReleaseId } from "../../lib/release-scope";
import { SITE_VARIANT } from "../../lib/site-variant";

export const Route = createFileRoute("/phenotypes/$lineId")({
  component: PhenotypeLineDetail,
});

function PhenotypeLineDetail() {
  const { t } = useTranslation();
  const { lineId } = Route.useParams();
  const releaseId = useReleaseId();
  const validId = isMutantLineId(lineId);

  const lineQuery = useQuery({
    queryKey: queryKeys.mutants.detail(lineId, releaseId, SITE_VARIANT),
    queryFn: () => getMutantLine(lineId),
    enabled: validId,
  });

  const phenotypeQuery = useQuery({
    queryKey: queryKeys.mutants.phenotypes(lineId, releaseId, SITE_VARIANT),
    queryFn: () => getMutantLinePhenotypes(lineId),
    enabled: validId && lineQuery.isSuccess,
  });

  const columns: TableColumnsType<PhenotypeResponse> = [
    {
      title: t("phenotypes.columns.category"),
      dataIndex: "trait_category",
      key: "trait_category",
      render: (category: string) => <Tag>{category}</Tag>,
    },
    { title: t("phenotypes.columns.trait"), dataIndex: "trait_name", key: "trait_name" },
    {
      title: t("phenotypes.columns.value"),
      key: "trait_value",
      align: "right",
      render: (_, row) =>
        row.trait_value === null || row.trait_value === "" ? (
          <span className="text-muted-foreground">{t("phenotypes.notRecorded")}</span>
        ) : (
          <span className="font-mono tabular-nums">{row.trait_value}</span>
        ),
    },
    {
      title: t("phenotypes.columns.unit"),
      key: "unit",
      render: (_, row) =>
        row.unit ? (
          <span className="font-mono text-xs">{row.unit}</span>
        ) : (
          <span className="text-muted-foreground">{t("phenotypes.notRecorded")}</span>
        ),
    },
    {
      title: t("phenotypes.columns.description"),
      key: "description",
      render: (_, row) =>
        row.description ? (
          row.description
        ) : (
          <span className="text-muted-foreground">{t("phenotypes.notRecorded")}</span>
        ),
    },
  ];

  if (!validId) {
    return (
      <main className="container-prose py-10 md:py-14">
        <Empty description={t("phenotypes.detail.notFound")} />
      </main>
    );
  }

  if (lineQuery.isLoading) {
    return (
      <main className="container-prose py-10 md:py-14" aria-busy="true">
        <Skeleton active paragraph={{ rows: 6 }} aria-label={t("phenotypes.detail.loading")} />
      </main>
    );
  }

  if (lineQuery.isError || !lineQuery.data) {
    return (
      <main className="container-prose py-10 md:py-14">
        <Empty description={t("phenotypes.detail.notFound")} />
        <div className="mt-4 text-center">
          <Link to="/phenotypes" search={{ category: "", trait: "" }}>
            {t("phenotypes.detail.back")}
          </Link>
        </div>
      </main>
    );
  }

  const line = lineQuery.data;
  const observations = phenotypeQuery.data ?? [];

  return (
    <FadeUp>
      <main className="container-prose py-10 md:py-14" data-testid="phenotype-line-detail">
        <Link
          to="/phenotypes"
          search={{ category: "", trait: "" }}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline"
        >
          <ArrowLeftOutlined className="size-4" aria-hidden />
          {t("phenotypes.detail.back")}
        </Link>

        <header className="mt-5">
          <p className="eyebrow">{t("phenotypes.eyebrow")}</p>
          <h1 className="mt-2 font-display text-3xl font-semibold tracking-tight">
            {line.name}
          </h1>
          <p
            className="mt-2 font-mono text-sm text-muted-foreground"
            data-public-id={line.public_id}
            data-testid="phenotype-line-public-id"
          >
            {t("mutantLines.lineId")}: {line.public_id}
          </p>
        </header>

        <section className="mt-8" aria-labelledby="phenotype-line-context">
          <h2 id="phenotype-line-context" className="font-display text-2xl font-semibold">
            {t("phenotypes.detail.context")}
          </h2>
          <Descriptions
            className="mt-4"
            bordered
            column={{ xs: 1, sm: 2 }}
            items={[
              { key: "species", label: t("mutants.fields.species"), children: line.species },
              {
                key: "cultivar",
                label: t("mutants.fields.cultivar"),
                children: line.cultivar || t("phenotypes.notRecorded"),
              },
              {
                key: "mutagen",
                label: t("mutants.fields.mutagen"),
                children: line.mutagen || t("phenotypes.notRecorded"),
              },
              {
                key: "phenotype_summary",
                label: t("mutants.fields.phenotypeSummary"),
                children: line.phenotype_summary || t("phenotypes.notRecorded"),
                span: 2,
              },
            ]}
          />
        </section>

        <section className="mt-10" aria-labelledby="phenotype-line-observations">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="phenotype-line-observations" className="font-display text-2xl font-semibold">
              {t("phenotypes.detail.observations")}
            </h2>
            <Link
              to="/mutants/$id"
              params={{ id: line.public_id }}
              className="text-sm font-medium text-primary hover:underline"
            >
              {t("phenotypes.detail.openLine")}
            </Link>
          </div>
          <Alert className="mt-4" type="info" showIcon title={t("phenotypes.detail.boundary")} />
          <div className="mt-5">
            {phenotypeQuery.isLoading ? (
              <Skeleton active paragraph={{ rows: 4 }} aria-label={t("phenotypes.loading")} />
            ) : phenotypeQuery.isError ? (
              <Empty description={t("phenotypes.error")} />
            ) : observations.length === 0 ? (
              <Alert
                type="info"
                showIcon
                data-testid="phenotypes-state-no-data"
                title={t("phenotypes.detail.noObservationsTitle")}
                description={t("phenotypes.detail.noObservationsDesc")}
              />
            ) : (
              <Table<PhenotypeResponse>
                rowKey="id"
                columns={columns}
                dataSource={observations}
                pagination={false}
                scroll={{ x: "max-content" }}
                locale={{ emptyText: <Empty description={t("phenotypes.empty")} /> }}
              />
            )}
          </div>
        </section>
      </main>
    </FadeUp>
  );
}
