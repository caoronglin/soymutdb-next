/**
 * Genes index route — the gene search entry.
 *
 * The server-paginated table and its filter bar were removed at the operator's
 * request: the page rendered results that did not work for them, so it now
 * presents the same single identifier search box as the home hero and submits
 * into the global search route. The six-column gene result table remains
 * available on the dedicated tool page `/search/genes`.
 *
 * `validateSearch` is kept permissive on purpose: bookmarked `/genes?...` deep
 * links must keep resolving instead of throwing, even though this page no
 * longer reads those parameters itself.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { useSiteContent } from "../../lib/site-content-react";
import { FadeUp } from "../../components/route-motion";
import { PortalSearchBox } from "../../components/portal-search-box";

export const Route = createFileRoute("/genes/")({
  component: GenesComponent,
  validateSearch: (search: Record<string, unknown>) => ({
    assembly: String(search.assembly ?? ""),
    q: String(search.q ?? ""),
    chromosome: String(search.chromosome ?? ""),
    biotype: String(search.biotype ?? ""),
    page: Number(search.page ?? 1),
    sort_by: String(search.sort_by ?? "gene_id"),
    sort_dir: (search.sort_dir as "asc" | "desc") ?? "asc",
  }),
});

function GenesComponent() {
  const { t } = useTranslation();
  const { get } = useSiteContent();
  const { q } = Route.useSearch();

  return (
    <FadeUp>
      <div className="container-prose py-10 md:py-14">
        <p className="eyebrow">{get("genes.title", t("genes.title"))}</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">
          {get("genes.subtitle", t("genes.subtitle"))}
        </h1>
        <div className="mt-8">
          <PortalSearchBox testId="genes-search" defaultValue={q} />
        </div>
      </div>
    </FadeUp>
  );
}
