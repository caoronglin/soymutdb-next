/**
 * SiteFooter — full link map + copyright line.
 *
 * Since the PPTX V2 header keeps only five flat primary items, everything
 * else (Downloads, Guide, Genes, …) stays reachable here.
 */
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

/** Footer link map — deeper pages removed from the primary nav (PPTX V2). */
const FOOTER_LINKS: ReadonlyArray<{ to: string; labelKey: string }> = [
  { to: "/genes", labelKey: "nav.genes" },
  { to: "/variants", labelKey: "nav.variants" },
  { to: "/browser", labelKey: "nav.browser" },
  { to: "/blast", labelKey: "nav.blast" },
  { to: "/tools", labelKey: "nav.tools" },
  { to: "/downloads", labelKey: "nav.downloads" },
  { to: "/guide", labelKey: "nav.guide" },
  { to: "/news", labelKey: "nav.news" },
  { to: "/seed-request", labelKey: "nav.seedRequest" },
  { to: "/publications", labelKey: "nav.publications" },
  { to: "/about", labelKey: "nav.about" },
  { to: "/help", labelKey: "nav.help" },
];

export function SiteFooter() {
  const { t } = useTranslation();
  const year = new Date().getFullYear();

  return (
    <footer className="mt-auto border-t border-border/80 bg-muted/20">
      <div className="container-prose py-8">
        <nav
          aria-label="Footer"
          className="mb-6 flex flex-wrap gap-x-6 gap-y-2 text-sm text-muted-foreground"
        >
          {FOOTER_LINKS.map((link) => (
            <Link
              key={link.to}
              to={link.to}
              className="site-footer-link link-underline transition-colors hover:text-foreground"
            >
              {t(link.labelKey)}
            </Link>
          ))}
        </nav>
        <div className="flex flex-col items-start justify-between gap-3 border-t border-border/60 pt-4 text-xs text-muted-foreground sm:flex-row sm:items-center">
          <p>{t("footer.copyright", { year })}</p>
          <div className="flex items-center gap-4">
            <p className="font-mono">v2.0.0</p>
            <span className="text-border">·</span>
            <Link to="/about" className="site-footer-link link-underline hover:text-foreground">
              {t("nav.about")}
            </Link>
            <span className="text-border">·</span>
            <Link to="/help" className="site-footer-link link-underline hover:text-foreground">
              API Docs
            </Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
