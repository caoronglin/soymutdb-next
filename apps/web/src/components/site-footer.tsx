/**
 * SiteFooter — rich footer with navigation columns, consortium logos,
 * and citation/DOI block.
 */
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Dna, ExternalLink, BookOpen } from "lucide-react";

interface FooterColumn {
  titleKey: string;
  links: ReadonlyArray<{ to: string; labelKey: string; external?: boolean }>;
}

const COLUMNS: ReadonlyArray<FooterColumn> = [
  {
    titleKey: "footer.resources",
    links: [
      { to: "/help", labelKey: "footer.documentation" },
      { to: "/help", labelKey: "footer.help" },
      { to: "/downloads", labelKey: "footer.downloads" },
      { to: "/publications", labelKey: "footer.publications" },
    ],
  },
  {
    titleKey: "footer.dataTools",
    links: [
      { to: "/browser", labelKey: "footer.browser" },
      { to: "/blast", labelKey: "footer.blast" },
      { to: "/analytics", labelKey: "nav.analytics" },
      { to: "/help", labelKey: "footer.api" },
    ],
  },
  {
    titleKey: "footer.aboutUs",
    links: [
      { to: "/help", labelKey: "footer.about" },
      { to: "/help", labelKey: "footer.contact" },
      { to: "/help", labelKey: "footer.privacy" },
      { to: "/help", labelKey: "footer.terms" },
    ],
  },
];

const CONSORTIA = [
  "Soybean Research Institute",
  "NCBI",
  "EMBL-EBI",
  "Phytozome",
  "USDA-ARS",
];

export function SiteFooter() {
  const { t } = useTranslation();
  const year = new Date().getFullYear();

  return (
    <footer className="mt-auto border-t border-border/80 bg-muted/20">
      <div className="container-prose py-14">
        {/* Top section: brand + columns */}
        <div className="grid gap-10 md:grid-cols-2 lg:grid-cols-5">
          {/* Brand blurb */}
          <div className="lg:col-span-2 lg:pr-12">
            <Link to="/" className="flex items-center gap-2 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label="SoyMutDB home">
              <span className="flex size-8 items-center justify-center rounded-lg bg-gradient-to-br from-[var(--primary-gradient-start)] to-[var(--primary-gradient-end)] text-primary-foreground shadow-sm">
                <Dna className="size-5" aria-hidden />
              </span>
              <span className="font-display text-lg font-semibold tracking-tight">
                Soy<span className="text-gradient">Mut</span>DB
              </span>
            </Link>
            <p className="mt-4 max-w-sm text-sm leading-relaxed text-muted-foreground">
              {t("footer.description")}
            </p>

            {/* Citation / DOI block */}
            <div className="mt-6 rounded-xl border bg-card p-4">
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <BookOpen className="size-3.5" aria-hidden />
                <span>Cite SoyMutDB</span>
              </div>
              <p className="mt-2 text-sm leading-relaxed">
                If you use SoyMutDB in your research, please cite:
              </p>
              <p className="mt-2 rounded-md bg-muted p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">
                SoyMutDB Consortium (2024). SoyMutDB: a comprehensive database of soybean mutations for functional genomics and crop improvement. <span className="text-primary">Nucleic Acids Research</span>. DOI: <span className="font-semibold text-foreground">10.1093/nar/gkacXXXX</span>
              </p>
              <Link
                to="/publications"
                className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary link-underline"
              >
                View all publications
                <ExternalLink className="size-3" aria-hidden />
              </Link>
            </div>
          </div>

          {COLUMNS.map((col) => (
            <nav key={col.titleKey} aria-label={t(col.titleKey)}>
              <h2 className="eyebrow mb-4">{t(col.titleKey)}</h2>
              <ul className="flex flex-col gap-2.5">
                {col.links.map((link) => (
                  <li key={link.labelKey}>
                    <Link
                      to={link.to}
                      className="link-underline text-sm text-muted-foreground transition-colors hover:text-foreground"
                    >
                      {t(link.labelKey)}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>

        {/* Consortium logos */}
        <div className="mt-12 border-t pt-8">
          <p className="eyebrow mb-5 text-center">In collaboration with</p>
          <div className="flex flex-wrap items-center justify-center gap-3">
            {CONSORTIA.map((name) => (
              <div key={name} className="consortium-logo" role="img" aria-label={name}>
                {name}
              </div>
            ))}
          </div>
        </div>

        {/* Bottom bar */}
        <div className="mt-10 flex flex-col items-start justify-between gap-3 border-t pt-6 text-xs text-muted-foreground sm:flex-row sm:items-center">
          <p>{t("footer.copyright", { year })}</p>
          <div className="flex items-center gap-4">
            <p className="font-mono">v2.0.0</p>
            <span className="text-border">·</span>
            <p className="font-mono">Assembly Wm82.a4.v1</p>
            <span className="text-border">·</span>
            <Link to="/help" className="link-underline hover:text-foreground">
              API Docs
            </Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
