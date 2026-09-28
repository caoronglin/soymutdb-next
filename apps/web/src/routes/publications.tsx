/**
 * Publications route — bibliography of research citing SoyMutDB.
 *
 * Data source: GET /api/v1/content/publications. The site-wide snapshot
 * (`data/content.json`) prefills the first paint for SSG pages; the API
 * then refreshes in the background. No hardcoded fallback data is used so
 * the route cannot masquerade missing state as real content.
 */
import * as React from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ExportOutlined as ExternalLink, ReadOutlined as BookOpen } from "@ant-design/icons";
import { Alert, Button, Card, Empty, Skeleton, Tag } from "@/lib/antd";
import { FadeUp, Stagger } from "../components/route-motion";
import { listPublications } from "@soymutdb/api-client";
import {
  isPublicationsArray,
  loadSnapshotJson,
  prefillQueryData,
  readBootstrap,
  snapshotTimestamp,
} from "../lib/content-snapshot";

export const Route = createFileRoute("/publications")({
  component: PublicationsComponent,
});

/** Snapshot-prefilled queries refresh from the API after this long. */
const PREFILL_STALE_TIME = 30_000;

function pickLocalized(
  value: { en: string | null; zh: string | null },
  isZh: boolean,
): string {
  if (isZh && value.zh) return value.zh;
  return value.en ?? value.zh ?? "";
}

function PublicationsComponent() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const isZh = i18n.language.toLowerCase().startsWith("zh");

  const bootstrap = React.useMemo(() => readBootstrap(), []);
  const bootstrapData =
    bootstrap?.page === "publications-list" && isPublicationsArray(bootstrap.data)
      ? bootstrap.data
      : undefined;

  const query = useQuery({
    queryKey: ["publications"],
    queryFn: () => listPublications(),
    staleTime: bootstrapData ? PREFILL_STALE_TIME : 60_000,
    initialData: bootstrapData,
    initialDataUpdatedAt: bootstrapData
      ? snapshotTimestamp(bootstrap?.generated_at)
      : undefined,
  });

  // Pin the snapshot data into the cache (dataUpdatedAt = generated_at) so
  // the query is already stale and the background API refresh replaces it.
  React.useEffect(() => {
    if (!bootstrapData || !bootstrap) return;
    prefillQueryData(queryClient, ["publications"], bootstrapData, bootstrap.generated_at);
  }, [bootstrapData, bootstrap, queryClient]);

  // No bootstrap (plain SPA / dev): the site-wide snapshot JSON can still
  // prefill the list. Fetch once per session, silently.
  React.useEffect(() => {
    if (bootstrap) return;
    let cancelled = false;
    void loadSnapshotJson().then((snap) => {
      if (cancelled || !snap || !isPublicationsArray(snap.publications)) return;
      prefillQueryData(queryClient, ["publications"], snap.publications, snap.generated_at);
    });
    return () => {
      cancelled = true;
    };
  }, [bootstrap, queryClient]);

  const items = query.data ?? [];
  const loading = query.isPending && !query.data;
  const errored = query.isError && !query.data;

  return (
    <div className="container-prose section-rhythm">
      <FadeUp>
        <p className="eyebrow">{t("publications.title")}</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">
          {t("publications.subtitle")}
        </h1>
        <p className="mt-3 max-w-2xl text-sm text-muted-foreground">
          {t("publications.description", { defaultValue: "Peer-reviewed publications that cite SoyMutDB. Managed by the platform administrators from the Admin console." })}
        </p>
      </FadeUp>

      {loading ? (
        <div className="mt-8 grid gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i}>
              <Skeleton active paragraph={{ rows: 2 }} title={false} />
            </Card>
          ))}
        </div>
      ) : errored ? (
        <Alert
          type="error"
          showIcon
          className="mt-8"
          message={t("publications.loadError", { defaultValue: "Publications unavailable" })}
          description={t("publications.loadErrorDesc", { defaultValue: "The publications list could not be retrieved from the backend. Please try again later." })}
        />
      ) : items.length === 0 ? (
        <Empty
          className="mt-16"
          description={t("publications.empty", { defaultValue: "No publications have been published yet." })}
        />
      ) : (
        <Stagger className="mt-10 grid gap-4">
          {items.map((pub) => {
            const title = pickLocalized({ en: pub.title, zh: pub.title_zh }, isZh);
            const authors = pickLocalized({ en: pub.authors, zh: pub.authors_zh }, isZh);
            const abstract = pickLocalized({ en: pub.abstract, zh: pub.abstract_zh }, isZh);
            // Keyed by the public locator: the payload no longer carries a
            // persistence key. A DOI-less row falls back to title+year so the
            // list still renders.
            const cardKey = pub.doi ?? `${pub.title}-${pub.year ?? ""}`;
            return (
              <Card key={cardKey} className="card-lift">
                <div>
                  <div className="flex items-start gap-4">
                    <div className="hidden size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground sm:flex">
                      <BookOpen className="size-5" aria-hidden />
                    </div>
                    <div className="min-w-0 flex-1">
                      <h2 className="font-display text-lg font-semibold leading-snug">{title}</h2>
                      <p className="mt-2 text-sm text-muted-foreground">{authors}</p>
                      {abstract ? (
                        <p className="mt-3 text-sm leading-relaxed text-foreground/80">{abstract}</p>
                      ) : null}
                      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                        {pub.journal ? <Tag className="font-mono">{pub.journal}</Tag> : null}
                        {pub.year ? <span className="font-mono text-muted-foreground">{pub.year}</span> : null}
                        {pub.doi ? (
                          <span className="font-mono text-muted-foreground">DOI: {pub.doi}</span>
                        ) : null}
                      </div>
                    </div>
                    {pub.doi ? (
                      <Button
                        type="text"
                        className="shrink-0"
                        href={`https://doi.org/${pub.doi}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={t("publications.viewPaper", { defaultValue: "View paper {{doi}}", doi: pub.doi })}
                      >
                        <ExternalLink className="size-4" aria-hidden />
                      </Button>
                    ) : null}
                  </div>
                </div>
              </Card>
            );
          })}
        </Stagger>
      )}
    </div>
  );
}
