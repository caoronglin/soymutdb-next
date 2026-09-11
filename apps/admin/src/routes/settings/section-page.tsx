import { Link } from "@tanstack/react-router";
import SettingsPage from "../settings";
import { SETTINGS_DOMAIN_META, type SettingsDomain } from "./domains";
import { AppearanceSettingsForm } from "./appearance-form";
import { SiteSettingsForm } from "./site-form";
import { LocalizationSettingsForm } from "./localization-form";
import { SecuritySettingsForm } from "./security-form";
import { SettingsRevisionHistory } from "./revision-history";

export function SettingsDomainPage({ domain }: { domain: SettingsDomain }) {
  const meta = SETTINGS_DOMAIN_META[domain];
  return (
    <div className="space-y-4">
      <nav aria-label="Settings sections" className="text-sm">
        <Link to="/settings" className="text-primary hover:underline">
          Settings overview
        </Link>
      </nav>
      <header>
        <h1 className="text-2xl font-semibold">{meta.title}</h1>
        <p className="text-muted-foreground">{meta.description}</p>
      </header>
      {domain === "appearance" ? <AppearanceSettingsForm /> : domain === "site" ? <SiteSettingsForm /> : domain === "localization" ? <LocalizationSettingsForm /> : domain === "security" ? <SecuritySettingsForm /> : <SettingsPage domain={domain} />}
      {domain === "site" ? <p className="text-sm text-muted-foreground">Variant-specific site content remains available in the <Link to="/settings/legacy" className="text-primary hover:underline">complete settings form</Link> while its local editor is extracted.</p> : null}
      {domain === "localization" ? <p className="text-sm text-muted-foreground">Site-variant content selection remains available in the <Link to="/settings/legacy" className="text-primary hover:underline">complete settings form</Link> while its editor is extracted.</p> : null}
      <SettingsRevisionHistory sections={meta.revisionSections} />
    </div>
  );
}
