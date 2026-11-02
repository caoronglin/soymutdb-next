import { useTranslation } from "react-i18next";
import type { SiteFooterNavigationGroup } from "@soymutdb/api-client";
import { safeExternalUrl } from "../lib/url-safety";

interface FooterNavigationProps {
  groups: SiteFooterNavigationGroup[];
}

function safeHref(target: SiteFooterNavigationGroup["links"][number]["target"], href: string): string | null {
  if (href !== href.trim() || /\s|\\/.test(href) || [...href].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)) return null;
  if (target === "internal") {
    return href.startsWith("/") && !href.startsWith("//") ? href : null;
  }
  if (target !== "external") return null;
  const safe = safeExternalUrl(href);
  if (!safe?.startsWith("https://")) return null;
  const url = new URL(safe);
  return url.username || url.password ? null : safe;
}

export function FooterNavigation({ groups }: FooterNavigationProps) {
  const { t, i18n } = useTranslation();
  const language = i18n.language.toLowerCase().startsWith("zh") ? "zh" : "en";
  const visibleGroups = groups.filter((group) => group.enabled).sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));

  if (!visibleGroups.length) return null;

  return (
    <nav aria-label={t("footer.label")} className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
      {visibleGroups.map((group) => {
        const links = group.links
          .filter((link) => link.enabled)
          .sort((a, b) => a.order - b.order || a.id.localeCompare(b.id));
        if (!links.length) return null;
        return (
          <div key={group.id}>
            <h2 className="text-sm font-semibold">{language === "zh" ? group.title_zh : group.title_en}</h2>
            <ul className="mt-2 space-y-1.5">
              {links.map((link) => {
                const href = safeHref(link.target, link.href);
                if (!href) return null;
                return (
                  <li key={link.id}>
                    <a
                      className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                      href={href}
                      {...(link.target === "external" ? { target: "_blank", rel: "noopener noreferrer" } : {})}
                    >
                      {language === "zh" ? link.label_zh : link.label_en}
                    </a>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}
