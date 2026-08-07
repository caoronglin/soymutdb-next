/**
 * News index route — list of news articles.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Newspaper, ArrowRight } from "lucide-react";
import { Card, CardContent } from "@soymutdb/ui";
import { FadeUp, Stagger } from "../../components/route-motion";
import { formatDate } from "../../lib/format";

export const Route = createFileRoute("/news/")({
  component: NewsIndexComponent,
});

interface NewsItem {
  slug: string;
  title: string;
  excerpt: string;
  date: string;
  category: string;
}

const NEWS: NewsItem[] = [
  { slug: "v2-release", title: "SoyMutDB v2.0 released", excerpt: "We are excited to announce SoyMutDB v2.0 with 32.6M variants, 1,247 mutant lines, and a redesigned genome browser.", date: "2025-06-15", category: "Release" },
  { slug: "new-crispr-lines", title: "New CRISPR/Cas9 mutant lines added", excerpt: "120 new CRISPR-edited lines targeting flowering time genes have been added to the database.", date: "2025-05-20", category: "Data update" },
  { slug: "jbrowse-upgrade", title: "JBrowse 2 integration complete", excerpt: "The genome browser now runs on JBrowse 2 with improved performance and multi-track support.", date: "2025-04-10", category: "Tool" },
  { slug: "publication-award", title: "SoyMutDB paper accepted at Plant Biotechnology Journal", excerpt: "Our manuscript describing SoyMutDB has been accepted for publication.", date: "2025-03-01", category: "Publication" },
];

function NewsIndexComponent() {
  const { t } = useTranslation();

  return (
    <div className="container-prose section-rhythm">
      <FadeUp>
        <p className="eyebrow">{t("news.title")}</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{t("news.subtitle")}</h1>
      </FadeUp>

      <Stagger className="mt-10 grid gap-4">
        {NEWS.map((item) => (
          <Card key={item.slug} className="card-lift">
            <CardContent>
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-mono">{formatDate(item.date)}</span>
                    <span>·</span>
                    <span className="rounded-full bg-accent px-2 py-0.5 text-[10px] font-medium text-accent-foreground">{item.category}</span>
                  </div>
                  <h2 className="mt-2 font-display text-xl font-semibold tracking-tight">{item.title}</h2>
                  <p className="mt-2 text-sm text-muted-foreground">{item.excerpt}</p>
                  <Link
                    to="/news/$slug"
                    params={{ slug: item.slug }}
                    className="link-underline mt-4 inline-flex items-center gap-1 text-sm font-medium text-primary"
                  >
                    {t("news.readMore")}
                    <ArrowRight className="size-3.5" aria-hidden />
                  </Link>
                </div>
                <div className="hidden size-12 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground sm:flex">
                  <Newspaper className="size-5" aria-hidden />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </Stagger>
    </div>
  );
}
