/**
 * News detail route — single article view.
 *
 * Fetches via getNewsBySlug; preview token (?preview=&exp=) from the URL
 * query is forwarded to the API so admin preview links work without login.
 * Drafts without a valid token 404 on the backend → "article not found".
 * Body HTML is sanitised with DOMPurify before rendering. Prev/next
 * navigation derives from the same-category published list (cap 200).
 *
 * E3 (snapshot takeover): SSG detail pages embed a `#rl-bootstrap` JSON for
 * the current slug; it prefills the query cache so the first paint renders
 * the snapshot article (no loading flash) with the API refreshing in the
 * background. Preview/exp requests ALWAYS hit the API. Slugs missing from
 * the snapshot (e.g. visibility-window articles) fall back to the normal
 * API load.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
import { Button, Result, Skeleton, Tag } from "antd";
import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  CalendarOutlined,
  EyeInvisibleOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import DOMPurify from "dompurify";
import {
  ApiError,
  getNewsBySlug,
  listNews,
  type NewsSummary,
} from "@soymutdb/api-client";
import { formatDate } from "../../lib/format";
import {
  isDetailData,
  prefillQueryData,
  readBootstrap,
  snapshotTimestamp,
} from "../../lib/content-snapshot";

export const Route = createFileRoute("/news/$slug")({
  component: NewsDetailComponent,
});

const SIBLING_PAGE_SIZE = 200;
/** Snapshot-prefilled detail refreshes from the API after this long. */
const PREFILL_STALE_TIME = 30_000;

interface PreviewSearch {
  preview?: string;
  exp?: number;
}

function NewsDetailComponent() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const { slug } = Route.useParams();
  const { preview, exp } = Route.useSearch({ select: (s) => s as PreviewSearch });

  // Bootstrap is read synchronously once per mount — SSG detail pages embed
  // it only for the generated slug. Preview/exp never prefill.
  const bootstrap = React.useMemo(() => readBootstrap(), []);
  const bootstrapArticle =
    !preview && !exp && bootstrap?.page === "news-detail" && bootstrap.slug === slug && isDetailData(bootstrap.data)
      ? bootstrap.data
      : undefined;

  const detailQuery = useQuery({
    queryKey: ["news-detail", slug, preview ?? null, exp ?? null],
    queryFn: () => getNewsBySlug(slug, preview, exp),
    staleTime: bootstrapArticle ? PREFILL_STALE_TIME : 60_000,
    retry: false,
    // First paint renders the snapshot article — no loading flash on SSG pages.
    initialData: bootstrapArticle,
    initialDataUpdatedAt: bootstrapArticle
      ? snapshotTimestamp(bootstrap?.generated_at)
      : undefined,
  });

  // Pin the bootstrap article into the cache (dataUpdatedAt = generated_at)
  // so the query is already stale and the background API refresh replaces it.
  React.useEffect(() => {
    if (!bootstrapArticle || !bootstrap) return;
    prefillQueryData(
      queryClient,
      ["news-detail", slug, null, null],
      bootstrapArticle,
      bootstrap.generated_at,
    );
  }, [bootstrapArticle, bootstrap, slug, queryClient]);

  const article = detailQuery.data;
  const isZh = i18n.language.toLowerCase().startsWith("zh");

  const title = article
    ? isZh && article.title_zh
      ? article.title_zh
      : article.title_en
    : "";

  const siblingsQuery = useQuery({
    queryKey: ["news-siblings", article?.category ?? "all"],
    queryFn: () =>
      listNews(article?.category ?? undefined, 1, SIBLING_PAGE_SIZE).then((r) => r.items),
    enabled: Boolean(article),
    staleTime: 5 * 60 * 1000,
  });

  const siblings = siblingsQuery.data ?? [];
  const idx = article ? siblings.findIndex((s) => s.slug === article.slug) : -1;
  const prevItem: NewsSummary | undefined = idx > 0 ? siblings[idx - 1] : undefined;
  const nextItem: NewsSummary | undefined =
    idx >= 0 && idx < siblings.length - 1 ? siblings[idx + 1] : undefined;

  const isNotFound =
    detailQuery.isError &&
    detailQuery.error instanceof ApiError &&
    detailQuery.error.status === 404;

  return (
    <div className="container-prose section-rhythm">
      <Link
        to="/news"
        search={{ category: undefined, page: undefined }}
        className="link-underline inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeftOutlined className="text-xs" aria-hidden />
        {t("news.backToList")}
      </Link>

      {detailQuery.isLoading && !article ? (
        <div className="mt-8 max-w-3xl" data-testid="news-detail-loading">
          <Skeleton active paragraph={{ rows: 1 }} title={{ width: 200 }} />
          <Skeleton.Image active style={{ height: 360, width: "100%", marginTop: 16 }} />
          <Skeleton active paragraph={{ rows: 6 }} className="mt-6" />
        </div>
      ) : isNotFound && !article ? (
        <Result
          status="404"
          title={t("news.articleNotFound")}
          subTitle={t("news.articleNotFoundHint")}
          extra={
            <Link to="/news" search={{ category: undefined, page: undefined }}>
              <Button type="primary">{t("news.backToList")}</Button>
            </Link>
          }
        />
      ) : !article ? (
        <Result
          status="error"
          title={t("news.loadErrorTitle")}
          subTitle={
            detailQuery.error instanceof ApiError
              ? detailQuery.error.message
              : t("news.loadErrorSubtitle")
          }
          extra={
            <Button icon={<ReloadOutlined />} onClick={() => void detailQuery.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (
        <article className="mt-8 max-w-3xl">
          {article.cover_url ? (
            <img
              src={article.cover_url}
              alt={title}
              className="mb-8 w-full rounded-xl border border-border object-cover"
              style={{ maxHeight: 380 }}
            />
          ) : null}

          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            {article.category ? (
              <Tag color="green" className="m-0">
                {article.category}
              </Tag>
            ) : null}
            {article.published_at ? (
              <span className="inline-flex items-center gap-1 font-mono">
                <CalendarOutlined aria-hidden />
                {formatDate(article.published_at)}
              </span>
            ) : null}
            {preview ? (
              <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400">
                <EyeInvisibleOutlined aria-hidden />
                {t("news.previewMode")}
              </span>
            ) : null}
          </div>

          <h1 className="mt-4 font-display text-4xl font-semibold tracking-tight">
            {title}
          </h1>

          <div
            data-testid="news-content"
            className="news-content prose-sm mt-6 max-w-none text-base leading-relaxed text-foreground/90"
            // Body is admin-authored, bleach-sanitised HTML from the backend;
            // DOMPurify re-sanitises as defence in depth.
            dangerouslySetInnerHTML={{
              __html: DOMPurify.sanitize(
                article.content_zh && isZh ? article.content_zh : article.content_en,
              ),
            }}
          />

          {(prevItem || nextItem) && (
            <nav className="mt-10 grid gap-4 border-t border-border pt-6 sm:grid-cols-2" aria-label={t("news.siblingsAria")}>
              {prevItem ? (
                <NewsSiblingLink item={prevItem} direction="prev" />
              ) : (
                <span />
              )}
              {nextItem ? (
                <NewsSiblingLink item={nextItem} direction="next" />
              ) : (
                <span />
              )}
            </nav>
          )}
        </article>
      )}
    </div>
  );
}

function NewsSiblingLink({ item, direction }: { item: NewsSummary; direction: "prev" | "next" }) {
  const { t, i18n } = useTranslation();
  const isZh = i18n.language.toLowerCase().startsWith("zh");
  const title = isZh && item.title_zh ? item.title_zh : item.title_en;
  const label = direction === "prev" ? t("news.prev") : t("news.next");

  return (
    <Link
      to="/news/$slug"
      params={{ slug: item.slug }}
      className={`group flex flex-col gap-1 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40 ${
        direction === "next" ? "text-right" : ""
      }`}
    >
      <span className="text-xs text-muted-foreground">
        {direction === "prev" ? (
          <ArrowLeftOutlined className="mr-1 text-[10px]" aria-hidden />
        ) : null}
        {label}
        {direction === "next" ? (
          <ArrowRightOutlined className="ml-1 text-[10px]" aria-hidden />
        ) : null}
      </span>
      <span className="line-clamp-2 text-sm font-medium text-foreground transition-colors group-hover:text-primary">
        {title}
      </span>
    </Link>
  );
}
