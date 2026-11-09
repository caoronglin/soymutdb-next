import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { PageContainer } from "@/lib/antd";
import SettingsPage from "../settings";
import { SETTINGS_DOMAIN_META, type SettingsDomain } from "./domains";
import { AppearanceSettingsForm } from "./appearance-form";
import { SiteSettingsForm } from "./site-form";
import { LocalizationSettingsForm } from "./localization-form";
import { SecuritySettingsForm } from "./security-form";
import { SettingsRevisionHistory } from "./revision-history";

interface SettingsDomainPageProps {
  domain: SettingsDomain;
  /**
   * Extra sections this domain owns, rendered inside the same `PageContainer`.
   * A domain with its own content (`integrations`) passes it here rather than
   * rendering a second page wrapper beside this one, so the domain still has
   * exactly one page header.
   */
  children?: ReactNode;
}


export function SettingsDomainPage({ domain, children }: SettingsDomainPageProps) {
  const { t } = useTranslation();
  const meta = SETTINGS_DOMAIN_META[domain];
  const title = t(`admin.settings.domains.${domain}.title`, { defaultValue: meta.title });
  const description = t(`admin.settings.domains.${domain}.description`, { defaultValue: meta.description });
  const translatedSections = meta.revisionSections.map((section) => ({
    ...section,
    label: t(`admin.settings.sections.${section.id}`, { defaultValue: section.label }),
  }));
  return (
    <PageContainer
      title={title}
      subTitle={description}
      breadcrumb={{
        items: [{
          title: (
            <Link to="/settings" className="text-primary hover:underline">
              {t("admin.settings.overview", { defaultValue: "Settings overview" })}
            </Link>
          ),
        }],
      }}
    >
      <div className="space-y-4">
        {domain === "appearance" ? <AppearanceSettingsForm /> : domain === "site" ? <SiteSettingsForm /> : domain === "localization" ? <LocalizationSettingsForm /> : domain === "security" ? <SecuritySettingsForm /> : <SettingsPage domain={domain} />}
        {children}
        <SettingsRevisionHistory sections={translatedSections} />
      </div>
    </PageContainer>
  );
}
