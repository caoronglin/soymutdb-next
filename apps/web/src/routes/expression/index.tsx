/**
 * Expression library browser (`/expression`).
 *
 * Every library the API returns is bound to the resolved published release and
 * to its own assembly; this page only chooses which slice of that set to show.
 * The filter state lives in the URL (`validateSearch`) so a colleague opening
 * the link sees the same tissue/treatment/assembly/page this operator saw.
 *
 * Units are stated in the column headers: FPKM and TPM are different
 * normalisations and a header that says "Value" hides which one was measured.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  Empty,
  Input,
  Select,
  Skeleton,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "@/lib/antd";
import { SearchOutlined } from "@ant-design/icons";
import {
  getExpressionLibraries,
  type ExpressionLibrary,
} from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { formatNumber } from "../../lib/format";
import { assembliesQueryOptions } from "../../lib/query-options";
import { queryKeys } from "../../lib/query-keys";
import { useReleaseId } from "../../lib/release-scope";
import { SITE_VARIANT } from "../../lib/site-variant";

const PAGE_SIZE = 20;

export interface ExpressionSearch {
  page: number;
  tissue: string;
  treatment: string;
  /** Assembly id as a string so an unset filter round-trips as "". */
  assembly: string;
}

/** Narrow a raw, possibly hostile search object into the typed filter state. */
export function validateExpressionSearch(
  search: Record<string, unknown>,
): ExpressionSearch {
  const rawPage = Number(search.page);
  return {
    page: Number.isFinite(rawPage) && rawPage >= 1 ? Math.floor(rawPage) : 1,
    tissue: typeof search.tissue === "string" ? search.tissue : "",
    treatment: typeof search.treatment === "string" ? search.treatment : "",
    assembly: typeof search.assembly === "string" ? search.assembly : "",
  };
}

export const Route = createFileRoute("/expression/")({
  component: ExpressionLibrariesComponent,
  validateSearch: validateExpressionSearch,
});

function ExpressionLibrariesComponent() {
  const { t } = useTranslation();
  const search = Route.useSearch() as ExpressionSearch;
  const navigate = Route.useNavigate();
  const releaseId = useReleaseId();
  const assemblyId = search.assembly ? Number(search.assembly) : undefined;

  const assembliesQuery = useQuery(
    assembliesQueryOptions({ releaseId, siteVariant: SITE_VARIANT }),
  );

  const librariesQuery = useQuery({
    queryKey: queryKeys.expression.libraries({
      page: search.page,
      pageSize: PAGE_SIZE,
      tissue: search.tissue || null,
      treatment: search.treatment || null,
      assemblyId: assemblyId ?? null,
      releaseId,
      siteVariant: SITE_VARIANT,
    }),
    queryFn: () =>
      getExpressionLibraries({
        page: search.page,
        page_size: PAGE_SIZE,
        ...(search.tissue ? { tissue: search.tissue } : {}),
        ...(search.treatment ? { treatment: search.treatment } : {}),
        ...(assemblyId !== undefined ? { assembly_id: assemblyId } : {}),
      }),
  });

  const [tissueDraft, setTissueDraft] = React.useState(search.tissue);
  const [treatmentDraft, setTreatmentDraft] = React.useState(search.treatment);

  React.useEffect(() => setTissueDraft(search.tissue), [search.tissue]);
  React.useEffect(() => setTreatmentDraft(search.treatment), [search.treatment]);

  // Any filter change restarts pagination: keeping page 4 of the previous
  // filter set would show an empty table that reads as "no libraries exist".
  const setSearch = (patch: Partial<ExpressionSearch>) => {
    void navigate({
      to: "/expression",
      search: { ...search, page: 1, ...patch },
    });
  };

  const hasFilters = Boolean(search.tissue || search.treatment || search.assembly);
  const libraries = librariesQuery.data?.items ?? [];
  const total = librariesQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const columns: TableColumnsType<ExpressionLibrary> = [
    {
      title: t("expression.list.sample"),
      key: "sample",
      render: (_, row) => (
        <Link
          to="/expression/$sampleId"
          params={{ sampleId: row.public_id }}
          data-testid="expression-library-row"
          className="font-mono text-xs text-primary hover:underline"
        >
          {row.public_id}
        </Link>
      ),
    },
    {
      title: t("expression.list.library"),
      dataIndex: "library_name",
      key: "library_name",
    },
    {
      title: t("expression.list.tissue"),
      key: "tissue",
      render: (_, row) => row.tissue || "—",
    },
    {
      title: t("expression.list.treatment"),
      key: "treatment",
      render: (_, row) => row.treatment || "—",
    },
    {
      title: t("expression.list.assembly"),
      key: "assembly_name",
      render: (_, row) =>
        row.assembly_name ? (
          <span className="font-mono text-xs">{row.assembly_name}</span>
        ) : (
          <Tag>{t("expression.list.assemblyUnknown")}</Tag>
        ),
    },
    {
      title: t("expression.list.study"),
      key: "study_ref",
      render: (_, row) =>
        row.study_ref ? (
          <span className="font-mono text-xs">{row.study_ref}</span>
        ) : (
          <span className="text-muted-foreground">{t("expression.list.noStudyRef")}</span>
        ),
    },
    {
      title: t("expression.list.measurements"),
      dataIndex: "expression_data_count",
      key: "expression_data_count",
      align: "right",
      render: (_, row) => (
        <span className="font-mono tabular-nums">
          {formatNumber(row.expression_data_count)}
        </span>
      ),
    },
  ];

  return (
    <FadeUp>
      <main className="container-prose py-10 md:py-14">
        <header>
          <p className="eyebrow">{t("expression.eyebrow")}</p>
          <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">
            {t("expression.title")}
          </h1>
          <Typography.Paragraph type="secondary" className="mt-3 max-w-2xl">
            {t("expression.subtitle")}
          </Typography.Paragraph>
        </header>

        <section className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-label={t("expression.filters.aria")}>
          <label className="block" htmlFor="expression-tissue">
            <span className="mb-2 block font-medium">{t("expression.filters.tissue")}</span>
            <Input
              id="expression-tissue"
              value={tissueDraft}
              onChange={(event) => setTissueDraft(event.target.value)}
              onPressEnter={() => setSearch({ tissue: tissueDraft.trim() })}
              placeholder={t("expression.filters.tissuePlaceholder")}
              allowClear
            />
          </label>
          <label className="block" htmlFor="expression-treatment">
            <span className="mb-2 block font-medium">{t("expression.filters.treatment")}</span>
            <Input
              id="expression-treatment"
              value={treatmentDraft}
              onChange={(event) => setTreatmentDraft(event.target.value)}
              onPressEnter={() => setSearch({ treatment: treatmentDraft.trim() })}
              placeholder={t("expression.filters.treatmentPlaceholder")}
              allowClear
            />
          </label>
          <label className="block" htmlFor="expression-assembly">
            <span className="mb-2 block font-medium">{t("expression.filters.assembly")}</span>
            <Select
              id="expression-assembly"
              value={search.assembly || undefined}
              onChange={(value) => setSearch({ assembly: value ?? "" })}
              allowClear
              placeholder={t("expression.filters.assemblyPlaceholder")}
              loading={assembliesQuery.isLoading}
              className="w-full"
              options={(assembliesQuery.data ?? []).map((assembly) => ({
                value: String(assembly.id),
                label: `${assembly.name} (${assembly.version})`,
              }))}
            />
          </label>
          <div className="flex items-end gap-2">
            <Button
              type="primary"
              onClick={() =>
                setSearch({ tissue: tissueDraft.trim(), treatment: treatmentDraft.trim() })
              }
            >
              <SearchOutlined className="size-4" aria-hidden />
              {t("expression.filters.apply")}
            </Button>
            {hasFilters ? (
              <Button
                onClick={() => {
                  setTissueDraft("");
                  setTreatmentDraft("");
                  void navigate({ to: "/expression", search: { page: 1, tissue: "", treatment: "", assembly: "" } });
                }}
              >
                {t("expression.filters.clear")}
              </Button>
            ) : null}
          </div>
        </section>

        <section className="mt-6" aria-label={t("expression.resultsAria")}>
          {librariesQuery.isLoading ? (
            <Skeleton active paragraph={{ rows: 6 }} aria-label={t("expression.loading")} />
          ) : librariesQuery.isError ? (
            <Empty
              description={
                <span>
                  {t("expression.error")}
                  <Button onClick={() => void librariesQuery.refetch()}>
                    {t("common.retry")}
                  </Button>
                </span>
              }
            />
          ) : (
            <>
              <Table<ExpressionLibrary>
                rowKey="public_id"
                columns={columns}
                dataSource={libraries}
                pagination={false}
                scroll={{ x: "max-content" }}
                locale={{
                  emptyText: (
                    <Empty
                      description={
                        hasFilters ? t("expression.emptyFiltered") : t("expression.empty")
                      }
                    />
                  ),
                }}
              />
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <Typography.Text type="secondary">
                  {t("expression.resultCount", { count: total })}
                </Typography.Text>
                <nav className="flex items-center gap-3" aria-label={t("common.pagination")}>
                  <Button
                    onClick={() => setSearch({ page: Math.max(1, search.page - 1) })}
                    disabled={search.page <= 1 || librariesQuery.isFetching}
                  >
                    {t("common.previous")}
                  </Button>
                  <span className="text-sm text-muted-foreground">
                    {t("expression.pageOf", { page: search.page, total: totalPages })}
                  </span>
                  <Button
                    onClick={() => setSearch({ page: search.page + 1 })}
                    disabled={search.page >= totalPages || librariesQuery.isFetching}
                  >
                    {t("common.next")}
                  </Button>
                </nav>
              </div>
            </>
          )}
        </section>
      </main>
    </FadeUp>
  );
}
