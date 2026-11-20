/**
 * One expression library (`/expression/$sampleId`).
 *
 * The page answers "what was measured, where does it come from, and in which
 * unit". `study_ref`, `source`, `assembly_name`, `developmental_stage` and
 * `extra_metadata` are rendered as provenance, not as optional extras — a
 * library without a stated study is not a measurement anybody can cite.
 *
 * The per-library expression rows come from `GET /expression/search`, which
 * accepts the public sample id as `library`; the persistence key never reaches
 * the browser, so it cannot be rendered, linked or logged.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Skeleton,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "@/lib/antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import {
  getExpressionLibrary,
  searchExpression,
  type ExpressionSearchRecord,
} from "@soymutdb/api-client";
import { ChartFigure } from "@soymutdb/charts";
import { FadeUp } from "../../components/route-motion";
import { formatNumber } from "../../lib/format";
import { queryKeys } from "../../lib/query-keys";
import { useReleaseId } from "../../lib/release-scope";
import { SITE_VARIANT } from "../../lib/site-variant";
import {
  buildLibraryAbundanceChart,
  formatAbundance,
  libraryAbundanceRows,
  type AbundanceDatum,
  type AbundanceUnit,
} from "./-abundance";

const PAGE_SIZE = 100;

/**
 * A public sample id is a short safe token. The guard rejects blank, oversized
 * or path-ish values before they reach a URL segment; the server stays
 * authoritative for existence.
 */
export function isExpressionSampleId(value: string): boolean {
  return /^[A-Za-z0-9_.:-]{1,64}$/.test(value);
}

export const Route = createFileRoute("/expression/$sampleId")({
  component: ExpressionLibraryComponent,
});

function ExpressionLibraryComponent() {
  const { t } = useTranslation();
  const { sampleId } = Route.useParams();
  const releaseId = useReleaseId();
  const validId = isExpressionSampleId(sampleId);
  const [unit, setUnit] = React.useState<AbundanceUnit>("fpkm");

  const libraryQuery = useQuery({
    queryKey: queryKeys.expression.library(sampleId, releaseId, SITE_VARIANT),
    queryFn: () => getExpressionLibrary(sampleId),
    enabled: validId,
  });

  const rowsQuery = useQuery({
    queryKey: queryKeys.expression.rows({
      library: sampleId,
      page: 1,
      pageSize: PAGE_SIZE,
      releaseId,
      siteVariant: SITE_VARIANT,
    }),
    queryFn: () =>
      searchExpression({ library: sampleId, page: 1, page_size: PAGE_SIZE }),
    enabled: validId && libraryQuery.isSuccess,
  });

  const library = libraryQuery.data;
  const rows = React.useMemo(() => rowsQuery.data?.items ?? [], [rowsQuery.data]);
  const total = rowsQuery.data?.total ?? 0;

  // A chart over rows that are all null must not draw: an empty figure reads
  // as "measured zero", which is the one thing this data is not.
  const chartRows = React.useMemo(
    () => libraryAbundanceRows(rows, unit, t("expression.detail.geneColumn")),
    [rows, unit, t],
  );
  const unitLabel =
    unit === "fpkm" ? t("expression.detail.unitFpkm") : t("expression.detail.unitTpm");

  const columns: TableColumnsType<ExpressionSearchRecord> = [
    {
      title: t("expression.detail.geneColumn"),
      dataIndex: "gene_id",
      key: "gene_id",
      render: (geneId: string) => (
        <Link
          to="/genes/$geneId"
          params={{ geneId }}
          // No assembly filter: the gene's assembly is resolved by the API from
          // the accession + release context, and this page does not know it.
          search={{ assembly: undefined }}
          className="font-mono text-xs text-primary hover:underline"
        >
          {geneId}
        </Link>
      ),
    },
    {
      title: t("expression.detail.fpkmColumn"),
      key: "fpkm",
      align: "right",
      render: (_, row) => (
        <span className="font-mono tabular-nums">{formatMeasure(row.fpkm)}</span>
      ),
    },
    {
      title: t("expression.detail.tpmColumn"),
      key: "tpm",
      align: "right",
      render: (_, row) => (
        <span className="font-mono tabular-nums">{formatMeasure(row.tpm)}</span>
      ),
    },
    {
      title: t("expression.detail.rawCountColumn"),
      key: "raw_count",
      align: "right",
      render: (_, row) => (
        <span className="font-mono tabular-nums">{formatMeasure(row.raw_count)}</span>
      ),
    },
  ];

  if (!validId) {
    return (
      <main className="container-prose py-10 md:py-14">
        <Empty description={t("expression.detail.notFound")} />
      </main>
    );
  }

  if (libraryQuery.isLoading) {
    return (
      <main className="container-prose py-10 md:py-14" aria-busy="true">
        <Skeleton active paragraph={{ rows: 8 }} aria-label={t("expression.detail.loading")} />
      </main>
    );
  }

  if (libraryQuery.isError || !library) {
    return (
      <main className="container-prose py-10 md:py-14">
        <Empty description={t("expression.detail.notFound")} />
        <div className="mt-4 text-center">
          <Link to="/expression" search={{ page: 1, tissue: "", treatment: "", assembly: "" }}>
            {t("expression.detail.back")}
          </Link>
        </div>
      </main>
    );
  }

  const metadataEntries = library.extra_metadata
    ? Object.entries(library.extra_metadata)
    : [];

  return (
    <FadeUp>
      <main className="container-prose py-10 md:py-14" data-testid="expression-library-detail">
        <Link
          to="/expression"
          search={{ page: 1, tissue: "", treatment: "", assembly: "" }}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline"
        >
          <ArrowLeftOutlined className="size-4" aria-hidden />
          {t("expression.detail.back")}
        </Link>

        <header className="mt-5">
          <p className="eyebrow">{t("expression.eyebrow")}</p>
          <h1
            data-testid="expression-sample-id"
            className="mt-2 font-mono text-3xl font-semibold tracking-tight"
          >
            {library.sample_id}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">{library.library_name}</p>
        </header>

        <section className="mt-8" aria-labelledby="expression-provenance">
          <h2 id="expression-provenance" className="font-display text-2xl font-semibold">
            {t("expression.detail.provenance")}
          </h2>
          <Descriptions
            className="mt-4"
            bordered
            column={{ xs: 1, sm: 2 }}
            items={[
              {
                key: "study_ref",
                label: t("expression.detail.studyRef"),
                children: library.study_ref ? (
                  <span className="font-mono text-xs" data-testid="expression-study-ref">
                    {library.study_ref}
                  </span>
                ) : (
                  <span className="text-muted-foreground" data-testid="expression-study-ref-missing">
                    {t("expression.detail.missing")}
                  </span>
                ),
              },
              {
                key: "source",
                label: t("expression.detail.source"),
                children: library.source ? (
                  <span data-testid="expression-source">{library.source}</span>
                ) : (
                  <span className="text-muted-foreground" data-testid="expression-source-missing">
                    {t("expression.detail.missing")}
                  </span>
                ),
              },
              {
                key: "assembly_name",
                label: t("expression.detail.assembly"),
                children: library.assembly_name ? (
                  <span className="font-mono text-xs" data-testid="expression-assembly">
                    {library.assembly_name}
                  </span>
                ) : (
                  <span className="text-muted-foreground" data-testid="expression-assembly-missing">
                    {t("expression.detail.assemblyUnknown")}
                  </span>
                ),
              },
              {
                key: "developmental_stage",
                label: t("expression.detail.developmentalStage"),
                children: library.developmental_stage ? (
                  <span data-testid="expression-stage">{library.developmental_stage}</span>
                ) : (
                  <span className="text-muted-foreground" data-testid="expression-stage-missing">
                    {t("expression.detail.missing")}
                  </span>
                ),
              },
              {
                key: "tissue",
                label: t("expression.detail.tissue"),
                children: library.tissue || t("expression.detail.missing"),
              },
              {
                key: "treatment",
                label: t("expression.detail.treatment"),
                children: library.treatment || t("expression.detail.missing"),
              },
            ]}
          />
        </section>

        <section className="mt-8" aria-labelledby="expression-metadata">
          <h2 id="expression-metadata" className="font-display text-2xl font-semibold">
            {t("expression.detail.extraMetadata")}
          </h2>
          {metadataEntries.length === 0 ? (
            <Alert
              className="mt-4"
              type="info"
              showIcon
              title={t("expression.detail.extraMetadataEmpty")}
            />
          ) : (
            <dl
              className="mt-4 grid gap-2 rounded-xl border border-border bg-card p-4 sm:grid-cols-2"
              data-testid="expression-extra-metadata"
            >
              {metadataEntries.map(([key, value]) => (
                <div key={key} className="min-w-0">
                  <dt className="font-mono text-[11px] uppercase text-muted-foreground">{key}</dt>
                  <dd className="truncate text-sm">{formatMetadataValue(value)}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>

        <section className="mt-10" aria-labelledby="expression-rows">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 id="expression-rows" className="font-display text-2xl font-semibold">
                {t("expression.detail.measurementsTitle")}
              </h2>
              <Typography.Text type="secondary">
                {t("expression.detail.measurementsDesc")}
              </Typography.Text>
            </div>
            <Tag>{t("expression.detail.rowCount", { count: formatNumber(total) })}</Tag>
          </div>

          {rowsQuery.isLoading ? (
            <Skeleton className="mt-5" active paragraph={{ rows: 6 }} aria-label={t("expression.detail.rowsLoading")} />
          ) : rowsQuery.isError ? (
            <Empty className="mt-5" description={t("expression.detail.rowsError")} />
          ) : total === 0 ? (
            <Alert
              className="mt-5"
              type="info"
              showIcon
              data-testid="expression-rows-no-data"
              title={t("expression.detail.rowsEmptyTitle")}
              description={t("expression.detail.rowsEmptyDesc")}
            />
          ) : (
            <>
              <Card className="mt-5">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <Typography.Title level={5} style={{ margin: 0 }}>
                      {t("expression.detail.distributionTitle")}
                    </Typography.Title>
                    <Typography.Text type="secondary">
                      {t("expression.detail.distributionDesc")}
                    </Typography.Text>
                  </div>
                  <div className="flex gap-2" role="group" aria-label={t("expression.detail.unitSwitchAria")}>
                    <Button
                      size="small"
                      type={unit === "fpkm" ? "primary" : "default"}
                      onClick={() => setUnit("fpkm")}
                    >
                      {t("expression.detail.unitFpkm")}
                    </Button>
                    <Button
                      size="small"
                      type={unit === "tpm" ? "primary" : "default"}
                      onClick={() => setUnit("tpm")}
                    >
                      {t("expression.detail.unitTpm")}
                    </Button>
                  </div>
                </div>
                <ChartFigure<AbundanceDatum>
                  definition={buildLibraryAbundanceChart(unit, unitLabel)}
                  data={chartRows}
                  label={t("expression.detail.distributionTitle")}
                  description={t("expression.detail.distributionDesc")}
                  tableColumns={[t("expression.detail.geneColumn"), unitLabel]}
                  tableRow={(datum) => [datum.category, formatAbundance(datum.value)]}
                  emptyText={t("expression.detail.distributionEmpty")}
                  height={300}
                />
              </Card>

              <Table<ExpressionSearchRecord>
                className="mt-6"
                rowKey="gene_id"
                columns={columns}
                dataSource={rows}
                pagination={false}
                scroll={{ x: "max-content" }}
                locale={{ emptyText: <Empty description={t("expression.detail.rowsEmptyDesc")} /> }}
              />
              {total > rows.length ? (
                <Typography.Text type="secondary" className="mt-3 block">
                  {t("expression.detail.rowsTruncated", {
                    shown: formatNumber(rows.length),
                    total: formatNumber(total),
                  })}
                </Typography.Text>
              ) : null}
            </>
          )}
        </section>
      </main>
    </FadeUp>
  );
}

/**
 * A missing measurement renders as an explicit dash, never as 0: the API uses
 * `null` for "not measured in this library", and printing a zero would turn an
 * absent observation into an expressed gene.
 */
function formatMeasure(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (!Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 }).format(value);
}

function formatMetadataValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return "—";
  }
}
