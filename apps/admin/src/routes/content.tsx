import { ReadOutlined, FileTextOutlined } from "@ant-design/icons";
import * as React from "react";
import { useTranslation } from "react-i18next";
import { useRouterState } from "@tanstack/react-router";
import { PageContainer, Typography } from "@/lib/antd";
import { PagesTab } from "./content/pages-tab";
import { PageFormDialog } from "./content/page-form-dialog";
import { VersionHistoryDialog } from "./content/version-history-dialog";
import { VersionDetail } from "./content/version-detail";
import { NewsPublicationTab } from "./content/news-publication-tab";
import { StaticPageMigrationReport } from "./content/static-page-migration-report";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContentType = "news" | "publication" | "page";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TYPE_CONFIG: Record<ContentType, { label: string; icon: typeof ReadOutlined }> = {
  news: { label: "News", icon: ReadOutlined },
  publication: { label: "Publication", icon: ReadOutlined },
  page: { label: "Pages", icon: FileTextOutlined },
};

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ContentPage() {
  const { t } = useTranslation();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const isLegacyRoute = pathname === "/content/legacy";
  const [tab, setTab] = React.useState<ContentType>("page");

  return (
    <PageContainer
      title={t("admin.content.title", { defaultValue: "Content Management" })}
      subTitle={t("admin.content.subtitle", { defaultValue: "Manage static pages, news articles, and publications with full version history." })}
    >
      <div className="space-y-6">
        {isLegacyRoute ? (
          <>
            <div className="rounded-lg border border-border bg-muted/30 px-4 py-3">
              <span className="mr-2 rounded-full bg-muted px-2 py-1 text-xs font-medium">{t("admin.content.legacyBadge")}</span>
              <Typography.Text type="secondary">
                {t("admin.content.legacyHint")}
              </Typography.Text>
            </div>
            <StaticPageMigrationReport />
          </>
        ) : (
          <>
            <div
              role="tablist"
              data-testid="content-tabs"
              className="flex items-center gap-1 border-b border-border"
            >
              {(Object.keys(TYPE_CONFIG) as ContentType[]).map((typeKey) => {
                const Icon = TYPE_CONFIG[typeKey].icon;
                return (
                  <button
                    key={typeKey}
                    type="button"
                    role="tab"
                    aria-selected={tab === typeKey}
                    data-testid={`content-tab-${typeKey}`}
                    onClick={() => setTab(typeKey)}
                    className={`flex items-center gap-1.5 border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
                      tab === typeKey
                        ? "border-primary text-primary"
                        : "border-transparent text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    <Icon className="size-3.5" />
                    {t(`admin.content.type_${typeKey}`, { defaultValue: TYPE_CONFIG[typeKey].label })}
                  </button>
                );
              })}
            </div>
            {tab === "page" && (
              <PagesTab
                PageFormDialog={PageFormDialog}
                VersionHistoryDialog={VersionHistoryDialog}
                VersionDetail={VersionDetail}
              />
            )}
            {tab === "news" && <NewsPublicationTab type="news" />}
            {tab === "publication" && <NewsPublicationTab type="publication" />}
          </>
        )}
      </div>
    </PageContainer>
  );
}

// ---------------------------------------------------------------------------
// Pages tab — full CRUD + version management
// ---------------------------------------------------------------------------

// PagesTab is extracted to ./content/pages-tab.tsx.

// ---------------------------------------------------------------------------
// Page create/edit form dialog
// ---------------------------------------------------------------------------

// PageFormDialog is extracted to ./content/page-form-dialog.tsx.

// ---------------------------------------------------------------------------
// Version history dialog
// ---------------------------------------------------------------------------

// VersionHistoryDialog is extracted to ./content/version-history-dialog.tsx.

// ---------------------------------------------------------------------------
// Version detail (inline within version history dialog)
// ---------------------------------------------------------------------------

// VersionDetail is extracted to ./content/version-detail.tsx.

// ---------------------------------------------------------------------------
// News / Publication tab — list view (existing behaviour)
// ---------------------------------------------------------------------------

// NewsPublicationTab is extracted to ./content/news-publication-tab.tsx.
