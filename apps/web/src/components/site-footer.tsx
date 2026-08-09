/**
 * SiteFooter — minimal footer: copyright, version, API docs.
 * Navigation/citation/consortium sections removed (2026-08 redesign).
 */
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

export function SiteFooter() {
  const { t } = useTranslation();
  const year = new Date().getFullYear();

  return (
    <footer className="mt-auto border-t border-border/80 bg-muted/20">
      <div className="container-prose py-8">
        <div className="flex flex-col items-start justify-between gap-3 text-xs text-muted-foreground sm:flex-row sm:items-center">
          <p>{t("footer.copyright", { year })}</p>
          <div className="flex items-center gap-4">
            <p className="font-mono">v2.0.0</p>
            <span className="text-border">·</span>
            <Link to="/about" className="link-underline hover:text-foreground">
              {t("nav.about")}
            </Link>
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
