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

const FALLBACK_CONTACT_PERSON = "联系人: 周玲";
const FALLBACK_CONTACT_PHONE = "电话: 025-84391957";
const FALLBACK_CONTACT_EMAIL = "电子邮件: zlingxiaoyao@163.com";
const FALLBACK_ADDRESS = "地址: 南京市玄武区钟灵街50号 邮编210014";

export function SiteFooter() {
  const { t } = useTranslation();
  const year = new Date().getFullYear();

  const footerQuery = useQuery({
    queryKey: ["site-footer"],
    queryFn: getSiteFooter,
    staleTime: 60_000,
    retry: false,
  });
  const site = footerQuery.data;

  const contactPerson =
    site?.contact_person ?? t("footer.contactPerson", { defaultValue: FALLBACK_CONTACT_PERSON });
  const contactPhone =
    site?.contact_phone ?? t("footer.contactPhone", { defaultValue: FALLBACK_CONTACT_PHONE });
  const contactEmail =
    site?.contact_email ?? t("footer.contactEmail", { defaultValue: FALLBACK_CONTACT_EMAIL });
  const address = site?.address ?? t("footer.address", { defaultValue: FALLBACK_ADDRESS });

  const copyrightText = site?.copyright ?? t("footer.copyright", { year });
  const copyright = copyrightText.replaceAll("{{year}}", String(year));

  return (
    <footer className="mt-auto border-t border-border/80 bg-muted/20">
      <div className="container-prose py-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="text-sm text-muted-foreground">
            <p>{contactPerson}</p>
            <p className="mt-1">{contactPhone}</p>
            <p className="mt-1">{contactEmail}</p>
          </div>
          <div className="text-right text-sm text-muted-foreground">
            <p>{copyright}</p>
            <p className="mt-1">{address}</p>
          </div>
        </div>
        <p className="mt-4 border-t border-border/60 pt-3 text-xs text-muted-foreground">
          <span className="font-mono">v2.0.0</span>
        </p>
      </div>
    </footer>
  );
}
