/**
 * News detail route — single article view.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Calendar, Tag } from "lucide-react";
import { Card, CardContent } from "@soymutdb/ui";
import { FadeUp } from "../../components/route-motion";
import { formatDate } from "../../lib/format";

export const Route = createFileRoute("/news/$slug")({
  component: NewsDetailComponent,
});

const ARTICLES: Record<string, { title: string; date: string; category: string; body: string[] }> = {
  "v2-release": {
    title: "SoyMutDB v2.0 released",
    date: "2025-06-15",
    category: "Release",
    body: [
      "We are excited to announce SoyMutDB v2.0, a major update to the multi-species mutant database (soybean as the current default species). This release brings 32.6 million variants across 1,247 mutant lines, a redesigned genome browser based on JBrowse 2, and a new visual analytics center.",
      "The v2.0 release introduces a new API with cursor-based pagination for efficient traversal of large variant sets, BLAST sequence homology search, and an integrated seed request system for germplasm distribution.",
      "All data is available for download in VCF, GFF3, and FASTA formats. The genome browser supports deep linking from gene and variant detail pages, enabling seamless integration into research workflows.",
    ],
  },
  "new-crispr-lines": {
    title: "New CRISPR/Cas9 mutant lines added",
    date: "2025-05-20",
    category: "Data update",
    body: [
      "120 new CRISPR/Cas9-edited mutant lines targeting flowering time genes have been added to SoyMutDB. These lines were generated in the Williams 82 background and include edits to GmFT2a, GmFT5a, GmE1, and GmE2.",
      "Each line has been whole-genome sequenced to at least 15× coverage and variants have been called against the Wm82.a4.v1 reference assembly. Phenotypic data for flowering time under long-day and short-day conditions is also available.",
    ],
  },
};

function NewsDetailComponent() {
  const { t } = useTranslation();
  const { slug } = Route.useParams();
  const article = ARTICLES[slug];

  return (
    <div className="container-prose section-rhythm">
      <Link to="/news" className="link-underline inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden />
        {t("news.backToList")}
      </Link>

      {article ? (
        <FadeUp>
          <article className="mt-8 max-w-3xl">
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <Calendar className="size-3" aria-hidden />
                <span className="font-mono">{formatDate(article.date)}</span>
              </span>
              <span className="inline-flex items-center gap-1">
                <Tag className="size-3" aria-hidden />
                {article.category}
              </span>
            </div>
            <h1 className="mt-4 font-display text-4xl font-semibold tracking-tight">{article.title}</h1>
            <div className="mt-6 space-y-4 text-base leading-relaxed text-foreground/90">
              {article.body.map((para, i) => (
                <p key={i}>{para}</p>
              ))}
            </div>
          </article>
        </FadeUp>
      ) : (
        <Card className="mt-8"><CardContent className="p-8 text-center text-muted-foreground">{t("news.noNews")}</CardContent></Card>
      )}
    </div>
  );
}
