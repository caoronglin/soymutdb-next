/**
 * News index route — published news list.
 *
 * TanStack Query + AntD 5: category Tabs (all / news / update /
 * announcement), client-side search box (backend has no search param —
 * FastAPI would reject unknown params with 422, so filtering happens on the
 * current page), paginated AntD List of NewsCard. Loading / error / empty
 * states included; no fake data.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
import { Alert, Empty, Input, List, Pagination, Result, Skeleton, Tabs, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { ApiError, listNews, type NewsSummary } from "@soymutdb/api-client";
import { NewsCard } from "../../components/news-card";

export const Route = createFileRoute("/news/")({
  component: NewsIndexComponent,
});

const PAGE_SIZE = 10;

/** Backend stores lowercase category slugs; UI maps them to labels. */
export const NEWS_CATEGORIES = ["news", "update", "announcement"] as const;
export type NewsCategory = (typeof NEWS_CATEGORIES)[number];

function matchesSearch(item: NewsSummary, q: string): boolean {
  const haystack = `${item.title_en} ${item.title_zh ?? ""} ${item.category ?? ""}`.toLowerCase();
  return haystack.includes(q);
}

function NewsIndexComponent() {
  const { t } = useTranslation();
  const [category, setCategory] = React.useState<string>("all");
  const [page, setPage] = React.useState(1);
  const [search, setSearch] = React.useState("");

  const listQuery = useQuery({
    queryKey: ["news-list", category, page],
    queryFn: () => listNews(category === "all" ? undefined : category, page, PAGE_SIZE),
    staleTime: 60_000,
  });

  const items = listQuery.data?.items ?? [];
  const total = listQuery.data?.total ?? 0;

  const q = search.trim().toLowerCase();
  const filtered = q ? items.filter((item) => matchesSearch(item, q)) : items;

  const tabs = [
    { key: "all", label: t("news.categories.all") },
    ...NEWS_CATEGORIES.map((c) => ({ key: c, label: t(`news.categories.${c}`) })),
  ];

  return (
    <div className="container-prose section-rhythm">
      <p className="eyebrow">{t("news.title")}</p>
      <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{t("news.subtitle")}</h1>

      <div className="mt-8 flex flex-wrap items-center justify-between gap-4">
        <Tabs
          activeKey={category}
          onChange={(key) => {
            setCategory(key);
            setPage(1);
          }}
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
            setPage(1);
          }}
          style={{ width: 280 }}
          aria-label={t("news.searchPlaceholder")}
        />
      </div>

      <div className="mt-4">
        {listQuery.isError ? (
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
        ) : listQuery.isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="news-loading">
            {Array.from({ length: 6 }, (_, i) => (
              <div key={i} className="rounded-xl border border-border bg-card p-4">
                <Skeleton.Image active style={{ height: 160, width: "100%" }} />
                <Skeleton active paragraph={{ rows: 2 }} title={false} className="mt-4" />
              </div>
            ))}
          </div>
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
                onChange={setPage}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
