import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
import { Button, Empty, Input, Skeleton, Table, Typography, type TableColumnsType } from "@/lib/antd";
import { listMutantLines, type MutantLineResponse } from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { useReleaseId } from "../../lib/release-scope";
import { queryKeys } from "../../lib/query-keys";
import { SITE_VARIANT } from "../../lib/site-variant";

export const Route = createFileRoute("/mutants/")({
  component: MutantsIndex,
  validateSearch: (search: Record<string, unknown>): { q?: string; mutagen: string; page?: number } => ({
    // Free-text search over name / cultivar / mutagen (server-side `q`).
    q: typeof search.q === "string" ? search.q : undefined,
    // Exact mutagen filter — unchanged semantics, kept for deep links.
    mutagen: typeof search.mutagen === "string" ? search.mutagen : "",
    page: Number.isSafeInteger(Number(search.page)) && Number(search.page) > 0
      && Number(search.page) <= 1_000_000 ? Number(search.page) : 1,
  }),
});

/** Rows per API request; the API caps `limit` at 200. */
const PAGE_SIZE = 50;

/**
 * The free-text filter length the API accepts.
 *
 * The API refuses a longer query with 422; the input stops at the same
 * length so the refusal is a paste that never leaves the browser.
 */
const MUTANT_SEARCH_MAX_LENGTH = 200;

function MutantsIndex() {
  const { t } = useTranslation();
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  const [queryDraft, setQueryDraft] = React.useState(search.q ?? "");
  const [mutagenDraft, setMutagenDraft] = React.useState(search.mutagen);

  React.useEffect(() => {
    setQueryDraft(search.q ?? "");
  }, [search.q]);

  React.useEffect(() => {
    setMutagenDraft(search.mutagen);
  }, [search.mutagen]);

  const queryText = search.q ?? "";
  const targetPage = search.page ?? 1;
  const hasFilters = Boolean(queryText || search.mutagen);

  // Applying a filter always restarts at the first page: the previous
  // windows belong to the previous result set.
  const applyFilters = () => {
    navigate({
      to: "/mutants",
      search: {
        q: queryDraft || undefined,
        mutagen: mutagenDraft,
        page: 1,
      },
    });
  };

  const clearFilters = () => {
    setQueryDraft("");
    setMutagenDraft("");
    navigate({ to: "/mutants", search: { q: undefined, mutagen: "", page: 1 } });
  };

  const releaseId = useReleaseId();
  const previousRelease = React.useRef(releaseId);
  React.useEffect(() => {
    if (previousRelease.current !== releaseId) {
      previousRelease.current = releaseId;
      if (targetPage !== 1) void navigate({ to: "/mutants", search: { ...search, page: 1 } });
    }
  }, [releaseId, targetPage, navigate, search]);
  const offset = (targetPage - 1) * PAGE_SIZE;
  const query = useQuery({
    // Every dimension that changes the rows belongs in the key: the free-text
    // query, the exact mutagen filter, the page size, the release and the
    // site variant (a cache hit across those would leak another release).
    queryKey: [
      ...queryKeys.mutants.all(),
      "list",
      queryText || null,
      search.mutagen || null,
      PAGE_SIZE,
      offset,
      releaseId,
      SITE_VARIANT,
    ],
    queryFn: () =>
      listMutantLines({
        q: queryText || undefined,
        mutagen: search.mutagen || undefined,
        // One look-ahead row establishes whether another page exists.
        limit: PAGE_SIZE + 1,
        offset,
      }),
  });

  const lines = (query.data ?? []).slice(0, PAGE_SIZE);
  const hasNextPage = (query.data?.length ?? 0) > PAGE_SIZE;
  const changePage = (page: number) => {
    navigate({ to: "/mutants", search: { ...search, page } });
  };

  const columns: TableColumnsType<MutantLineResponse> = [
    {
      title: t("mutantLines.lineId", { defaultValue: "Public ID" }),
      dataIndex: "public_id",
      key: "public_id",
      render: (_, line) => (
        <Link
          to="/mutants/$id"
          params={{ id: line.public_id }}
          data-public-id={line.public_id}
          data-testid="mutant-row"
          className="font-mono text-xs text-primary hover:underline"
        >
          {line.public_id}
        </Link>
      ),
    },
    {
      title: t("mutants.columns.name"),
      dataIndex: "name",
      key: "name",
      render: (name, line) => <Link to="/mutants/$id" params={{ id: line.public_id }}>{name}</Link>,
    },
    {
      title: t("mutants.columns.cultivar"),
      dataIndex: "cultivar",
      key: "cultivar",
      render: (value) => value ?? "—",
    },
    {
      title: t("mutants.columns.mutagen"),
      dataIndex: "mutagen",
      key: "mutagen",
      render: (value) => value ?? "—",
    },
    {
      title: t("mutants.columns.linkedVariants"),
      dataIndex: "variant_count",
      key: "variant_count",
      align: "right",
    },
  ];

  return (
    <FadeUp>
      <main className="container-prose py-10 md:py-14">
        <div>
          <p className="eyebrow">{t("mutants.eyebrow")}</p>
          <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{t("mutants.title")}</h1>
          <Typography.Paragraph type="secondary" className="mt-3 max-w-2xl">
            {t("mutants.subtitle")}
          </Typography.Paragraph>
        </div>

        <div className="mt-8 max-w-md">
          <label className="block" htmlFor="mutant-search">
            <span className="mb-2 block font-medium">{t("mutants.filter.label")}</span>
            <Input
              id="mutant-search"
              value={queryDraft}
              onChange={(event) => setQueryDraft(event.target.value)}
              onPressEnter={applyFilters}
              placeholder={t("mutants.filter.placeholder")}
              // The API caps the free-text filter at 200 characters and
              // answers a longer one with 422. The box stops there, so the
              // visitor gets a rejected paste instead of a generic
              // "the list could not be loaded".
              maxLength={MUTANT_SEARCH_MAX_LENGTH}
              allowClear
            />
          </label>
          <label className="mt-4 block" htmlFor="mutagen-filter">
            <span className="mb-2 block font-medium">{t("mutants.filter.mutagenExact")}</span>
            <Input
              id="mutagen-filter"
              value={mutagenDraft}
              onChange={(event) => setMutagenDraft(event.target.value)}
              onPressEnter={applyFilters}
            />
          </label>
          <div className="mt-3 flex gap-2">
            <Button type="primary" onClick={applyFilters}>{t("mutants.filter.apply")}</Button>
            {hasFilters ? <Button onClick={clearFilters}>{t("mutants.filter.clear")}</Button> : null}
          </div>
        </div>

        <section className="mt-6" aria-label={t("mutants.resultsAria")}>
          {query.isLoading ? (
            <Skeleton active paragraph={{ rows: 5 }} aria-label={t("mutants.loading")} />
          ) : query.isError && !query.data ? (
            <Empty
              description={
                <span>
                  {t("mutants.error")}
                  <Button onClick={() => void query.refetch()}>{t("common.retry")}</Button>
                </span>
              }
            />
          ) : (
            <>
              <Table<MutantLineResponse>
                rowKey="public_id"
                columns={columns}
                dataSource={lines}
                pagination={false}
                // The table keeps its natural width on a phone and the region
                // scrolls sideways, so a public id stays readable instead of
                // being squeezed into an unreadable stub.
                scroll={{ x: "max-content" }}
                locale={{
                  emptyText: (
                    <Empty description={hasFilters ? t("mutants.emptyFiltered") : t("mutants.empty")} />
                  ),
                }}
              />
              <Typography.Text type="secondary" className="mt-3 block">
                {t("mutants.resultCount", { count: lines.length })}
              </Typography.Text>
              <nav className="mt-4 flex justify-center gap-3" aria-label={t("common.pagination")}>
                <Button onClick={() => changePage(targetPage - 1)} disabled={targetPage <= 1 || query.isFetching}>
                  {t("common.previous")}
                </Button>
                <Button onClick={() => changePage(targetPage + 1)} disabled={!hasNextPage || query.isFetching}>
                  {t("common.next")}
                </Button>
              </nav>
            </>
          )}
        </section>
      </main>
    </FadeUp>
  );
}
