/**
 * Public home page — driven by the published PageDefinition for "/" (Phase 8).
 *
 * The content (navigation → tool entries → news list → rich text) comes from
 * the real `/page-definitions/{route}` API via `usePageDefinition`, hydrated
 * from the SSG bootstrap when the pinned version matches, and falls back to
 * the immutable seed when the API is unavailable. The hero search and
 * statistics strip are removed (outside the approved reference structure);
 * their underlying APIs remain unchanged.
 *
 * Motion (FadeUp) and reduced-motion behavior are preserved via the
 * app-level animation policy (AnimationProvider).
 */
import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Skeleton } from "@/lib/antd";
import { FadeUp } from "../components/route-motion";
import { PageDefinitionRenderer } from "../page-builder/renderer";
import { usePageDefinition } from "../page-builder/loader";

export const Route = createFileRoute("/")({
  component: HomeComponent,
});

function HomeComponent() {
  const { t } = useTranslation();
  const { definition, isLoading, isFallback, hasError } = usePageDefinition("/");

  return (
    <div className="container-prose py-10">
        {isLoading && !definition ? (
          <div className="space-y-4" aria-label={t("common.loading")}>
            <Skeleton active />
            <Skeleton active />
            <Skeleton active />
          </div>
        ) : hasError ? (
          <p className="text-sm text-muted-foreground">{t("common.noResults")}</p>
        ) : definition ? (
          <>
            {isFallback ? (
              <p className="mb-4 text-xs text-muted-foreground" role="status">
                {t("home.offlineFallback")}
              </p>
            ) : null}
            <FadeUp>
              <PageDefinitionRenderer definition={definition} />
            </FadeUp>
          </>
        ) : null}
    </div>
  );
}
