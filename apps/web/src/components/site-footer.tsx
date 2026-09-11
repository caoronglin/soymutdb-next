/**
 * SiteFooter — editable contact/info block backed by site settings.
 *
 * Values are fetched from the public site-settings endpoint (GET /site/footer)
 * on mount via TanStack Query. When the endpoint is unavailable or errors, the
 * component falls back to the current placeholder values. An administrator can
 * edit 联系人 / 电话 / 邮箱 / 版权 / 地址 at runtime from the admin settings UI.
 */
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { getSiteFooter } from "@soymutdb/api-client";
import { SITE_VARIANT } from "../lib/site-variant";

const FALLBACK_ADDRESS = "地址: 南京市玄武区钟灵街50号 邮编210014";

export function SiteFooter() {
  const { t } = useTranslation();
  const year = new Date().getFullYear();

  const footerQuery = useQuery({
    queryKey: ["site-footer", SITE_VARIANT],
    queryFn: () => getSiteFooter(SITE_VARIANT),
    staleTime: 60_000,
    retry: false,
  });
  const site = footerQuery.data;

  const address = site?.address || t("footer.address", { defaultValue: FALLBACK_ADDRESS }) || FALLBACK_ADDRESS;

  const copyrightText = site?.copyright || t("footer.copyright", { year }) || "© " + year + " SoyMutDB. All rights reserved.";
  const copyright = copyrightText.replaceAll("{{year}}", String(year));

  return (
    <footer className="mt-auto border-t border-border/80 bg-muted/20">
      <div className="container-prose py-8">
        {/* Personal contact info intentionally removed; keep copyright + address only. */}
        <div className="text-right text-sm text-muted-foreground">
          <p>{copyright}</p>
          <p className="mt-1">{address}</p>
        </div>
      </div>
    </footer>
  );
}
