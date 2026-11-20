/**
 * About route — editable "About us" content (D4/E3).
 *
 * Data sources, in priority order:
 *   1. `#rl-bootstrap` JSON embedded by the SSG /about.html (first paint —
 *      no loading flash, API refreshes in the background);
 *   2. the site-wide snapshot JSON (`data/content.json`) `about` block;
 *   3. the public API `GET /site/about` (plain-API fallback).
 *
 * Content is admin-authored, bleach-sanitised HTML; DOMPurify re-sanitises
 * as defence in depth. A missing/empty about block renders an empty state.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
import { Button, Empty, Result, Skeleton, Typography } from "@/lib/antd";
import { ReloadOutlined } from "@ant-design/icons";
import DOMPurify from "dompurify";
import { ApiError, getSiteAbout } from "@soymutdb/api-client";
import { IS_INTERNAL_SITE, SITE_VARIANT } from "../lib/site-variant";
import {
  isAboutData,
  loadSnapshotJson,
  prefillQueryData,
  readBootstrap,
  snapshotTimestamp,
} from "../lib/content-snapshot";

export const Route = createFileRoute("/about")({
  component: AboutComponent,
});

/** Snapshot-prefilled about refreshes from the API after this long. */
const PREFILL_STALE_TIME = 30_000;

function AboutComponent() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const isZh = i18n.language.toLowerCase().startsWith("zh");

  // Bootstrap is read synchronously once per mount — SSG /about.html embeds it.
  const bootstrap = React.useMemo(() => (IS_INTERNAL_SITE ? undefined : readBootstrap()), []);
  const bootstrapAbout =
    bootstrap?.page === "about" && isAboutData(bootstrap.data)
      ? bootstrap.data
      : undefined;

  const aboutQuery = useQuery({
    queryKey: ["site-about", SITE_VARIANT],
    queryFn: () => getSiteAbout(SITE_VARIANT),
    staleTime: bootstrapAbout ? PREFILL_STALE_TIME : 60_000,
    retry: false,
    // First paint renders the snapshot about block — no loading flash.
    initialData: bootstrapAbout,
    initialDataUpdatedAt: bootstrapAbout
      ? snapshotTimestamp(bootstrap?.generated_at)
      : undefined,
  });

  // Pin the bootstrap about block into the cache (dataUpdatedAt =
  // generated_at) so the query is already stale and the background API
  // refresh replaces it.
  React.useEffect(() => {
    if (!bootstrapAbout || !bootstrap) return;
    prefillQueryData(queryClient, ["site-about", SITE_VARIANT], bootstrapAbout, bootstrap.generated_at);
  }, [bootstrapAbout, bootstrap, queryClient]);

  // No bootstrap (plain SPA / dev): the site-wide snapshot JSON can still
  // prefill the about block. Fetch once per session, silently.
  React.useEffect(() => {
    if (bootstrap || IS_INTERNAL_SITE) return;
    let cancelled = false;
    void loadSnapshotJson().then((snap) => {
      if (cancelled || !snap?.about) return;
      prefillQueryData(queryClient, ["site-about", SITE_VARIANT], snap.about, snap.generated_at);
    });
    return () => {
      cancelled = true;
    };
  }, [bootstrap, queryClient]);

  const about = aboutQuery.data;
  const title = about
    ? isZh && about.title_zh
      ? about.title_zh
      : about.title_en ?? t("about.title")
    : t("about.title");
  const summary = about
    ? isZh && about.summary_zh
      ? about.summary_zh
      : about.summary_en
    : null;
  const content = about
    ? isZh && about.content_zh
      ? about.content_zh
      : about.content_en
    : null;
  const hasContent = Boolean(content?.trim() || summary?.trim());

  return (
    <div className="container-prose section-rhythm">
      <p className="eyebrow">{t("about.title")}</p>
      <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{title}</h1>

      <div className="mt-8 max-w-3xl">
        {aboutQuery.isLoading && !about ? (
          <div data-testid="about-loading">
            <Skeleton active paragraph={{ rows: 2 }} title={false} />
            <Skeleton active paragraph={{ rows: 8 }} title={false} className="mt-6" />
          </div>
        ) : aboutQuery.isError && !about ? (
          <Result
            status="error"
            title={t("about.loadErrorTitle")}
            subTitle={
              aboutQuery.error instanceof ApiError
                ? aboutQuery.error.message
                : t("about.loadErrorSubtitle")
            }
            extra={
              <Button icon={<ReloadOutlined aria-hidden />} onClick={() => void aboutQuery.refetch()}>
                {t("common.retry")}
              </Button>
            }
          />
        ) : !hasContent ? (
          /* The about text is operator-authored and is not published yet. An
             empty box in a large empty page says nothing; this says what is
             missing, why, and what the visitor can do meanwhile. */
          <div data-testid="about-empty" className="py-6">
            <Empty
              description={
                <Typography.Text type="secondary">{t("about.empty")}</Typography.Text>
              }
            />
            <Typography.Paragraph className="mx-auto mt-2 max-w-2xl text-center text-sm text-muted-foreground">
              {t("about.emptyExplain")}
            </Typography.Paragraph>
            <div className="mx-auto mt-6 grid max-w-2xl gap-3 sm:grid-cols-2">
              <Link
                to="/search"
                className="rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary hover:bg-accent"
              >
                <p className="font-medium">{t("about.emptySearchTitle")}</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {t("about.emptySearchBody")}
                </p>
              </Link>
              <Link
                to="/assemblies"
                className="rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary hover:bg-accent"
              >
                <p className="font-medium">{t("about.emptyAssembliesTitle")}</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {t("about.emptyAssembliesBody")}
                </p>
              </Link>
            </div>
          </div>
        ) : (
          <>
            {summary ? (
              <Typography.Paragraph className="text-lg leading-relaxed text-muted-foreground">
                {summary}
              </Typography.Paragraph>
            ) : null}
            {content ? (
              <div
                data-testid="about-content"
                className="news-content prose-sm mt-4 max-w-none text-base leading-relaxed text-foreground/90"
                // Admin-authored, bleach-sanitised HTML from the backend /
                // snapshot; DOMPurify re-sanitises as defence in depth.
                dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(content) }}
              />
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
