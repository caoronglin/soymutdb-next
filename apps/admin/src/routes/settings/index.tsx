import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { PageContainer } from "@/lib/antd";
import { SETTINGS_DOMAIN_META, SETTINGS_DOMAINS } from "./domains";

export default function SettingsOverviewPage() {
  const { t } = useTranslation();
  return (
    <PageContainer
      title={t("admin.settings.overviewTitle", { defaultValue: "Settings" })}
      subTitle={t("admin.settings.overviewDescription", {
        defaultValue: "Choose a domain to edit and save independently.",
      })}
    >
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <div className="grid gap-4 sm:grid-cols-2">
          {SETTINGS_DOMAINS.map((domain) => {
            const meta = SETTINGS_DOMAIN_META[domain];
            return (
              <Link
                key={domain}
                to={(`/settings/${domain}`) as "/settings/site"}
                className="rounded-lg border border-border bg-card p-5 transition-colors hover:border-primary hover:bg-accent"
              >
                <h2 className="font-medium">
                  {t(`admin.settings.domains.${domain}.title`, { defaultValue: meta.title })}
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {t(`admin.settings.domains.${domain}.description`, { defaultValue: meta.description })}
                </p>
              </Link>
            );
          })}
        </div>
        <Link to="/settings/legacy" className="text-sm text-primary hover:underline">
          {t("admin.settings.completeForm", { defaultValue: "Open the complete settings form" })}
        </Link>
      </div>
    </PageContainer>
  );
}
