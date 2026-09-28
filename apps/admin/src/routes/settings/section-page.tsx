import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import SettingsPage from "../settings";
import { SETTINGS_DOMAIN_META, type SettingsDomain } from "./domains";
import { AppearanceSettingsForm } from "./appearance-form";
import { SiteSettingsForm } from "./site-form";
import { LocalizationSettingsForm } from "./localization-form";
import { SecuritySettingsForm } from "./security-form";
import { SettingsRevisionHistory } from "./revision-history";

export function SettingsDomainPage({ domain }: { domain: SettingsDomain }) {
  const { t } = useTranslation();
  const meta = SETTINGS_DOMAIN_META[domain];
  const title = t(`admin.settings.domains.${domain}.title`, { defaultValue: meta.title });
  const description = t(`admin.settings.domains.${domain}.description`, { defaultValue: meta.description });
  const translatedSections = meta.revisionSections.map((section) => ({
    ...section,
    label: t(`admin.settings.sections.${section.id}`, { defaultValue: section.label }),
  }));
  return (
    <div className="space-y-4">
      <nav aria-label={t("admin.settings.sectionsLabel", { defaultValue: "Settings sections" })} className="text-sm">
        <Link to="/settings" className="text-primary hover:underline">
          {t("admin.settings.overview", { defaultValue: "Settings overview" })}
        </Link>
      </nav>
      <header>
        <h1 className="text-2xl font-semibold">{title}</h1>
        <p className="text-muted-foreground">{description}</p>
      </header>
      {domain === "appearance" ? <AppearanceSettingsForm /> : domain === "site" ? <SiteSettingsForm /> : domain === "localization" ? <LocalizationSettingsForm /> : domain === "security" ? <SecuritySettingsForm /> : <SettingsPage domain={domain} />}
      {domain === "site" ? <p className="text-sm text-muted-foreground">Variant-specific site content remains available in the <Link to="/settings/legacy" className="text-primary hover:underline">complete settings form</Link> while its local editor is extracted.</p> : null}
      {domain === "localization" ? <p className="text-sm text-muted-foreground">Site-variant content selection remains available in the <Link to="/settings/legacy" className="text-primary hover:underline">complete settings form</Link> while its editor is extracted.</p> : null}
      <SettingsRevisionHistory sections={translatedSections} />
    </div>
  );
}
