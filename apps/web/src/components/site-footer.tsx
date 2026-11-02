/** SiteFooter — variant-aware, bilingual public footer backed by site settings. */
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { getSiteFooter } from "@soymutdb/api-client";
import { SITE_VARIANT } from "../lib/site-variant";
import { FooterNavigation } from "./footer-navigation";

const FALLBACK_ADDRESS = "地址: 南京市玄武区钟灵街50号 邮编210014";
const PHONE_RE = /^\+?[0-9][0-9 .()-]{0,30}$/;

function legacyValue(value: string | null | undefined): string | undefined {
  return value?.replace(/^(?:联系人|电话|电子邮件|地址)[:：]\s*/, "");
}

function phoneHref(value: string | null | undefined): string | null {
  if (!value || !PHONE_RE.test(value)) return null;
  const normalized = value.replace(/[^0-9+]/g, "");
  return /^\+?[0-9]{6,15}$/.test(normalized) ? `tel:${normalized}` : null;
}

function emailHref(value: string | null | undefined): string | null {
  if (!value || /\s|[?#%]/.test(value) || [...value].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)) return null;
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value) ? `mailto:${value}` : null;
}

export function SiteFooter() {
  const { t, i18n } = useTranslation();
  const year = new Date().getFullYear();
  const language = i18n.language.toLowerCase().startsWith("zh") ? "zh" : "en";
  const footerQuery = useQuery({
    queryKey: ["site-footer", SITE_VARIANT],
    queryFn: () => getSiteFooter(SITE_VARIANT),
    staleTime: 60_000,
    retry: false,
  });
  const site = footerQuery.data;
  const address = (language === "zh" ? site?.address_zh : site?.address_en) || legacyValue(site?.address) || t("footer.address", { defaultValue: FALLBACK_ADDRESS });
  const copyrightText = (language === "zh" ? site?.copyright_zh : site?.copyright_en) || site?.copyright || t("footer.copyright", { year });
  const copyright = copyrightText.replaceAll("{{year}}", String(year));
  const person = (language === "zh" ? site?.contact_person_zh : site?.contact_person_en) || legacyValue(site?.contact_person);
  const phone = site?.contact_phone_value || legacyValue(site?.contact_phone);
  const email = site?.contact_email_value || legacyValue(site?.contact_email);
  const phoneLink = phoneHref(phone);
  const emailLink = emailHref(email);

  return (
    <footer className="mt-auto border-t border-border/80 bg-muted/20">
      <div className="container-prose space-y-8 py-8">
        <FooterNavigation groups={site?.navigation ?? []} />
        <div className="grid gap-4 break-words text-sm text-muted-foreground sm:grid-cols-2">
          <div className="space-y-1">
            {person ? <p>{t("footer.contactPerson")}: {person}</p> : null}
            {phone ? <p>{t("footer.phone")}: {phoneLink ? <a className="hover:text-foreground" href={phoneLink}>{phone}</a> : phone}</p> : null}
            {email ? <p>{t("footer.email")}: {emailLink ? <a className="hover:text-foreground" href={emailLink}>{email}</a> : email}</p> : null}
          </div>
          <div className="text-left sm:text-right"><p>{copyright}</p><p className="mt-1">{address}</p></div>
        </div>
      </div>
    </footer>
  );
}
