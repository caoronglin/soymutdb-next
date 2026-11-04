/**
 * Phenotype browser (`/phenotypes`).
 *
 * ## What the backend can answer
 *
 * There is no cross-line phenotype endpoint: observations are served per line
 * (`GET /mutants/{public_id}/phenotypes`). This page therefore scans the public
 * mutant-line set with an explicit, advertised budget (see `-scan.ts`) and says
 * so on the page. It does not fabricate a paginated "all phenotypes" list that
 * no endpoint backs.
 *
 * ## Identity
 *
 * Every row is tied to the line's **public** id, which is also the only id put
 * in the DOM, the link path and the React key. The observation's numeric `id`
 * is a persistence key and is never rendered or linked.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQueries, useQuery } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Card,
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
import { getMutantLinePhenotypes, listMutantLines } from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { queryKeys } from "../../lib/query-keys";
import { useReleaseId } from "../../lib/release-scope";
import { SITE_VARIANT } from "../../lib/site-variant";
import {
  PHENOTYPE_SCAN_LINE_LIMIT,
  traitCategories,
  type PhenotypeRow,
} from "./-scan";

/**
 * Lines the page is willing to read before it starts reporting a partial view.
 *
 * The scan is this page's `useQueries` fan-out over the per-line endpoint (see
 * `-scan.ts`), so the budget is also the number of parallel per-line reads the
 * page can issue.
 *
 * Why 40: a browser opens about six HTTP/1.1 connections per origin, so 40
 * requests occupy the pool for a few waves — long enough to be visible, short
 * enough to stay below the point where the rest of the page stalls behind
 * them. It is a per-page ceiling, not a data limit: raising it past the pool
 * size buys latency, not coverage, because the cut is still a scan and the
 * page already says so. Removing it entirely is the real fix, and that needs a
 * cross-line phenotype endpoint (see the open item in the PR).
 */
export const PHENOTYPE_LINE_BUDGET = 40;

export interface PhenotypesSearch {
  category: string;
  trait: string;
}

export function validatePhenotypesSearch(
  search: Record<string, unknown>,
): PhenotypesSearch {
  return {
    category: typeof search.category === "string" ? search.category : "",
    trait: typeof search.trait === "string" ? search.trait : "",
  };
}

export const Route = createFileRoute("/phenotypes/")({
  component: PhenotypesIndex,
  validateSearch: validatePhenotypesSearch,
});

function PhenotypesIndex() {
  const { t } = useTranslation();
  const search = Route.useSearch() as PhenotypesSearch;
  const navigate = Route.useNavigate();
  const releaseId = useReleaseId();

  const linesQuery = useQuery({
    queryKey: [
      ...queryKeys.mutants.all(),
      "list",
      "phenotype-scan",
      PHENOTYPE_SCAN_LINE_LIMIT,
      releaseId,
      SITE_VARIANT,
    ],
    queryFn: () =>
      listMutantLines({ limit: PHENOTYPE_SCAN_LINE_LIMIT, offset: 0 }),
  });

  const lines = React.useMemo(
    () => (linesQuery.data ?? []).slice(0, PHENOTYPE_LINE_BUDGET),
    [linesQuery.data],
  );
  const linesAvailable = linesQuery.data?.length ?? 0;

  // One cached read per line through the endpoint that actually exists. The
  // mutant detail page owns the same key, so opening a line and coming back
  // reuses that read instead of issuing it twice.
  const phenotypeQueries = useQueries({
    queries: lines.map((line) => ({
      queryKey: queryKeys.mutants.phenotypes(line.public_id, releaseId, SITE_VARIANT),
      queryFn: () => getMutantLinePhenotypes(line.public_id),
      staleTime: 5 * 60_000,
    })),
  });

  const isScanning = linesQuery.isLoading || phenotypeQueries.some((query) => query.isLoading);
  const failedLines = phenotypeQueries.filter((query) => query.isError).length;

  // `useQueries` returns a new array each render but the entries are stable
  // objects, so the dependency below is the per-line payloads, not the array.
  const linePayloads = phenotypeQueries.map((query) => query.data);
  const rows = React.useMemo<PhenotypeRow[]>(() => {
    const collected: PhenotypeRow[] = [];
    lines.forEach((line, index) => {
      const data = linePayloads[index];
      if (!data) return;
      for (const observation of data) {
        collected.push({
          ...observation,
          // The line's public id is the only identity a row may carry.
          mutant_line_public_id: line.public_id,
          line_public_id: line.public_id,
          line_name: line.name,
        });
      }
    });
    return collected;
  }, [lines, linePayloads]);

  const categories = React.useMemo(() => traitCategories(rows), [rows]);
  const traitNeedle = search.trait.trim().toLowerCase();
  const filtered = React.useMemo(
    () =>
      rows.filter((row) => {
        if (search.category && row.trait_category !== search.category) return false;
        if (!traitNeedle) return true;
        return (
          row.trait_name.toLowerCase().includes(traitNeedle) ||
          (row.description ?? "").toLowerCase().includes(traitNeedle)
        );
      }),
    [rows, search.category, traitNeedle],
  );

  const [traitDraft, setTraitDraft] = React.useState(search.trait);
  React.useEffect(() => setTraitDraft(search.trait), [search.trait]);

  const applyFilters = (patch: Partial<PhenotypesSearch>) => {
    void navigate({ to: "/phenotypes", search: { ...search, ...patch } });
  };

  const columns: TableColumnsType<PhenotypeRow> = [
    {
      title: t("phenotypes.columns.line"),
      key: "line",
      render: (_, row) => (
        <Link
          to="/mutants/$id"
          params={{ id: row.line_public_id }}
          data-testid="phenotype-line-link"
          data-public-id={row.line_public_id}
          className="font-mono text-xs text-primary hover:underline"
        >
          {row.line_public_id}
        </Link>
      ),
    },
    {
      title: t("phenotypes.columns.category"),
      dataIndex: "trait_category",
      key: "trait_category",
      render: (category: string) => <Tag>{category}</Tag>,
    },
    {
      title: t("phenotypes.columns.trait"),
      dataIndex: "trait_name",
      key: "trait_name",
    },
    {
      title: t("phenotypes.columns.value"),
      key: "trait_value",
      align: "right",
      // A recorded observation without a value is not a zero measurement.
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

  if (linesQuery.isError) {
    return (
      <main className="container-prose py-10 md:py-14">
        <Empty
          description={
            <span>
              {t("phenotypes.error")}
              <Button className="ml-2" onClick={() => void linesQuery.refetch()}>
                {t("common.retry")}
              </Button>
            </span>
          }
        />
      </main>
    );
  }

  return (
    <FadeUp>
      <main className="container-prose py-10 md:py-14" data-testid="phenotypes-index">
        <header>
          <p className="eyebrow">{t("phenotypes.eyebrow")}</p>
          <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">
            {t("phenotypes.title")}
          </h1>
          <Typography.Paragraph type="secondary" className="mt-3 max-w-3xl">
            {t("phenotypes.subtitle")}
          </Typography.Paragraph>
        </header>

        {/* The boundary is stated on the page, not buried in a comment: the
            reader must know this is a bounded scan of the public line set. */}
        <Alert
          className="mt-6"
          type="info"
          showIcon
          data-testid="phenotypes-scan-boundary"
          title={t("phenotypes.boundary.title")}
          description={t("phenotypes.boundary.body", {
            budget: PHENOTYPE_LINE_BUDGET,
            limit: PHENOTYPE_SCAN_LINE_LIMIT,
          })}
        />

        <section className="mt-8 grid gap-4 sm:grid-cols-3" aria-label={t("phenotypes.filters.aria")}>
          <label className="block" htmlFor="phenotype-category">
            <span className="mb-2 block font-medium">{t("phenotypes.filters.category")}</span>
            <Select
              id="phenotype-category"
              className="w-full"
              value={search.category || undefined}
              onChange={(value) => applyFilters({ category: value ?? "" })}
              allowClear
              placeholder={t("phenotypes.filters.categoryPlaceholder")}
              options={categories.map((category) => ({ value: category, label: category }))}
            />
          </label>
          <label className="block" htmlFor="phenotype-trait">
            <span className="mb-2 block font-medium">{t("phenotypes.filters.trait")}</span>
            <Input
              id="phenotype-trait"
              value={traitDraft}
              onChange={(event) => setTraitDraft(event.target.value)}
              onPressEnter={() => applyFilters({ trait: traitDraft.trim() })}
              placeholder={t("phenotypes.filters.traitPlaceholder")}
              allowClear
            />
          </label>
          <div className="flex items-end gap-2">
            <Button type="primary" onClick={() => applyFilters({ trait: traitDraft.trim() })}>
              <SearchOutlined className="size-4" aria-hidden />
              {t("phenotypes.filters.apply")}
            </Button>
            {search.category || search.trait ? (
              <Button
                onClick={() => {
                  setTraitDraft("");
                  void navigate({ to: "/phenotypes", search: { category: "", trait: "" } });
                }}
              >
                {t("phenotypes.filters.clear")}
              </Button>
            ) : null}
          </div>
        </section>

        <section className="mt-6" aria-label={t("phenotypes.resultsAria")}>
          {isScanning ? (
            <Skeleton active paragraph={{ rows: 6 }} aria-label={t("phenotypes.loading")} />
          ) : linesAvailable === 0 ? (
            <Alert
              className="mt-2"
              type="info"
              showIcon
              data-testid="phenotypes-state-no-data"
              title={t("phenotypes.noLinesTitle")}
              description={t("phenotypes.noLinesDesc")}
            />
          ) : (
            <>
              <Card className="mb-6">
                <dl className="grid gap-4 sm:grid-cols-3">
                  <div>
                    <dt className="text-xs uppercase text-muted-foreground">
                      {t("phenotypes.scan.linesRead")}
                    </dt>
                    <dd className="font-mono text-lg tabular-nums">{lines.length}</dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase text-muted-foreground">
                      {t("phenotypes.scan.observations")}
                    </dt>
                    <dd className="font-mono text-lg tabular-nums">{rows.length}</dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase text-muted-foreground">
                      {t("phenotypes.scan.coverage")}
                    </dt>
                    <dd className="font-mono text-lg tabular-nums">
                      {linesAvailable >= PHENOTYPE_SCAN_LINE_LIMIT
                        ? t("phenotypes.scan.partial")
                        : t("phenotypes.scan.complete")}
                    </dd>
                  </div>
                </dl>
              </Card>

              {linesAvailable >= PHENOTYPE_SCAN_LINE_LIMIT ? (
                <Alert
                  className="mb-6"
                  type="warning"
                  showIcon
                  data-testid="phenotypes-scan-truncated"
                  title={t("phenotypes.scan.truncatedTitle")}
                  description={t("phenotypes.scan.truncatedDesc", {
                    budget: PHENOTYPE_LINE_BUDGET,
                    limit: PHENOTYPE_SCAN_LINE_LIMIT,
                  })}
                />
              ) : null}

              {failedLines > 0 ? (
                <Alert
                  className="mb-6"
                  type="warning"
                  showIcon
                  data-testid="phenotypes-scan-failed"
                  title={t("phenotypes.scan.failedTitle", { count: failedLines })}
                  description={t("phenotypes.scan.failedDesc")}
                />
              ) : null}

              <Table<PhenotypeRow>
                rowKey={(row) => [
                  row.line_public_id,
                  row.trait_category,
                  row.trait_name,
                  row.trait_value ?? "",
                  row.unit ?? "",
                ].join("|")}
                columns={columns}
                dataSource={filtered}
                pagination={false}
                scroll={{ x: "max-content" }}
                locale={{
                  emptyText: (
                    <Empty
                      description={
                        search.category || search.trait
                          ? t("phenotypes.emptyFiltered")
                          : t("phenotypes.empty")
                      }
                    />
                  ),
                }}
              />
              <Typography.Text type="secondary" className="mt-3 block">
                {t("phenotypes.resultCount", { count: filtered.length })}
              </Typography.Text>
            </>
          )}
        </section>
      </main>
    </FadeUp>
  );
}
