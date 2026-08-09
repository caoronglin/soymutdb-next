/**
 * News index route — published news list.
 *
 * TanStack Query + AntD 5: category Tabs (all / news / update /
 * announcement), client-side search box (backend has no search param —
 * FastAPI would reject unknown params with 422, so filtering happens on the
 * current page), paginated AntD List of NewsCard. Loading / error / empty
 * states included; no fake data.
 *
 * E3 (snapshot takeover): `category` / `page` live in the URL search params
 * (same semantics for the static ?category=&page= pages), and SSG pages
 * embed a `#rl-bootstrap` JSON that prefills the query cache for the first
 * render (no loading flash) — the API then refreshes in the background.
 * Without a bootstrap, the site-wide snapshot JSON prefills the first page;
 * without a snapshot at all, behaviour is the plain-API path.
 */
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
import { Alert, Empty, Input, List, Pagination, Result, Skeleton, Tabs, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { ApiError, listNews, type NewsListResponse, type NewsSummary } from "@soymutdb/api-client";
import { NewsCard } from "../../components/news-card";
import {
  isListResponseData,
  loadSnapshotJson,
  prefillQueryData,
  readBootstrap,
  snapshotTimestamp,
} from "../../lib/content-snapshot";

export const Route = createFileRoute("/news/")({
  component: NewsIndexComponent,
  // Optional search fields keep `Link to="/news"` call sites uncluttered;
  // the component normalises undefined → "all" / 1.
  validateSearch: (search: Record<string, unknown>) => ({
    category: search.category === undefined ? undefined : String(search.category),
    page:
      search.page === undefined
        ? undefined
        : Math.max(1, Math.floor(Number(search.page)) || 1),
  }),
});

const PAGE_SIZE = 10;
/** Snapshot-prefilled queries refresh from the API after this long. */
const PREFILL_STALE_TIME = 30_000;

/** Backend stores lowercase category slugs; UI maps them to labels. */
export const NEWS_CATEGORIES = ["news", "update", "announcement"] as const;
export type NewsCategory = (typeof NEWS_CATEGORIES)[number];

function matchesSearch(item: NewsSummary, q: string): boolean {
  const haystack = `${item.title_en} ${item.title_zh ?? ""} ${item.category ?? ""}`.toLowerCase();
  return haystack.includes(q);
}

function NewsIndexComponent() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const searchParams = Route.useSearch();
  const category = searchParams.category ?? "all";
  const page = searchParams.page ?? 1;
  const [search, setSearch] = React.useState("");

  // Bootstrap is read synchronously once per mount — SSG pages embed it.
  const bootstrap = React.useMemo(() => readBootstrap(), []);
  const bootstrapData =
    bootstrap?.page === "news-list" &&
    (bootstrap.category ?? "all") === category &&
    page === 1 &&
    isListResponseData(bootstrap.data)
      ? bootstrap.data
      : undefined;

  const listQuery = useQuery({
    queryKey: ["news-list", category, page],
    queryFn: () => listNews(category === "all" ? undefined : category, page, PAGE_SIZE),
    staleTime: bootstrapData ? PREFILL_STALE_TIME : 60_000,
    // First paint renders the snapshot data — no loading flash on SSG pages.
    initialData: bootstrapData,
    initialDataUpdatedAt: bootstrapData
      ? snapshotTimestamp(bootstrap?.generated_at)
      : undefined,
  });

  // Pin the bootstrap data into the cache (dataUpdatedAt = generated_at) so
  // the query is already stale and the background API refresh replaces it.
  React.useEffect(() => {
    if (!bootstrapData || !bootstrap) return;
    prefillQueryData(queryClient, ["news-list", category, page], bootstrapData, bootstrap.generated_at);
  }, [bootstrapData, bootstrap, category, page, queryClient]);

  // No bootstrap (plain SPA / dev): the site-wide snapshot JSON can still
  // prefill the first page. Fetch once per session, silently.
  React.useEffect(() => {
    if (bootstrap || category !== "all" || page !== 1) return;
    let cancelled = false;
    void loadSnapshotJson().then((snap) => {
      if (cancelled || !snap || !snap.news?.items?.length) return;
      const listData: NewsListResponse = {
        items: snap.news.items,
        total: snap.news.source_total ?? snap.news.items.length,
        page: 1,
        page_size: PAGE_SIZE,
      };
      prefillQueryData(queryClient, ["news-list", "all", 1], listData, snap.generated_at);
    });
    return () => {
      cancelled = true;
    };
  }, [bootstrap, category, page, queryClient]);

  const items = listQuery.data?.items ?? [];
  const total = listQuery.data?.total ?? 0;

  const q = search.trim().toLowerCase();
  const filtered = q ? items.filter((item) => matchesSearch(item, q)) : items;

  const tabs = [
    { key: "all", label: t("news.categories.all") },
    ...NEWS_CATEGORIES.map((c) => ({ key: c, label: t(`news.categories.${c}`) })),
  ];

  const goCategory = (key: string) => {
    void navigate({ to: "/news", search: { category: key, page: 1 } });
  };

  const goPage = (next: number) => {
    void navigate({ to: "/news", search: { category, page: next } });
  };

  return (
    <div className="container-prose section-rhythm">
      <p className="eyebrow">{t("news.title")}</p>
      <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{t("news.subtitle")}</h1>

      <div className="mt-8 flex flex-wrap items-center justify-between gap-4">
        <Tabs
          activeKey={category}
          onChange={goCategory}
          items={tabs}
          className="mb-0"
        />
        <Input.Search
          data-testid="news-search"
          allowClear
          placeholder={t("news.searchPlaceholder")}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            goPage(1);
          }}
          style={{ width: 280 }}
          aria-label={t("news.searchPlaceholder")}
        />
      </div>

      <div className="mt-4">
        {listQuery.isLoading && !listQuery.data ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="news-loading">
            {Array.from({ length: 6 }, (_, i) => (
              <div key={i} className="rounded-xl border border-border bg-card p-4">
                <Skeleton.Image active style={{ height: 160, width: "100%" }} />
                <Skeleton active paragraph={{ rows: 2 }} title={false} className="mt-4" />
              </div>
            ))}
          </div>
        ) : listQuery.isError && !listQuery.data ? (
          <Result
            status="error"
            title={t("news.loadErrorTitle")}
            subTitle={
              listQuery.error instanceof ApiError
                ? listQuery.error.message
                : t("news.loadErrorSubtitle")
            }
            extra={
              <button
                type="button"
                onClick={() => void listQuery.refetch()}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-4 py-2 text-sm text-foreground transition-colors hover:border-primary/40"
              >
                <ReloadOutlined aria-hidden />
                {t("common.retry")}
              </button>
            }
          />
        ) : filtered.length === 0 ? (
          <Empty
            description={
              <Typography.Text type="secondary">
                {q ? t("news.searchNoResults") : t("news.noNews")}
              </Typography.Text>
            }
            className="py-16"
          />
        ) : (
          <>
            {q ? (
              <Alert
                type="info"
                showIcon
                message={t("news.searchFiltering", { count: filtered.length })}
                className="mb-4"
              />
            ) : null}
            <List<NewsSummary>
              grid={{ gutter: 16, xs: 1, sm: 2, lg: 3 }}
              dataSource={filtered}
              renderItem={(item) => (
                <List.Item className="border-0!">
                  <NewsCard item={item} />
                </List.Item>
              )}
            />
            <div className="mt-8 flex justify-center">
              <Pagination
                current={page}
                total={total}
                pageSize={PAGE_SIZE}
                showSizeChanger={false}
                showTotal={(n) => t("news.total", { count: n })}
                onChange={goPage}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
