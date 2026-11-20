import { ReadOutlined, FileTextOutlined } from "@ant-design/icons";
import * as React from "react";
import { useTranslation } from "react-i18next";
import { PageContainer, Tabs } from "@/lib/antd";
import { PagesTab } from "./content/pages-tab";
import { PageFormDialog } from "./content/page-form-dialog";
import { VersionHistoryDialog } from "./content/version-history-dialog";
import { VersionDetail } from "./content/version-detail";
import { NewsPublicationTab } from "./content/news-publication-tab";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContentType = "news" | "publication" | "page";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Tab metadata. `labelKey` is spelled out instead of being built as
 * `admin.content.type_${typeKey}`: the catalogs register `admin.contentTab.*`,
 * and a template-built key that matches nothing renders the raw key in a zh
 * console instead of failing loudly.
 */
const TYPE_CONFIG: Record<ContentType, { label: string; labelKey: string; icon: typeof ReadOutlined }> = {
  news: { label: "News", labelKey: "admin.contentTab.news", icon: ReadOutlined },
  publication: { label: "Publications", labelKey: "admin.contentTab.publication", icon: ReadOutlined },
  page: { label: "Pages", labelKey: "admin.contentTab.page", icon: FileTextOutlined },
};

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ContentPage() {
  const { t } = useTranslation();
  const [tab, setTab] = React.useState<ContentType>("page");

  return (
    <PageContainer
      title={t("admin.content.title", { defaultValue: "Content Management" })}
      subTitle={t("admin.content.subtitle", { defaultValue: "Manage static pages, news articles, and publications with full version history." })}
    >
      <div className="space-y-6">
        <Tabs
          data-testid="content-tabs"
          activeKey={tab}
          onChange={(key) => setTab(key as ContentType)}
          items={(Object.keys(TYPE_CONFIG) as ContentType[]).map((typeKey) => {
            const Icon = TYPE_CONFIG[typeKey].icon;
            return {
                key: typeKey,
                label: (
                  <span
                    data-testid={`content-tab-${typeKey}`}
                    className="inline-flex items-center gap-1.5"
                  >
                    <Icon className="size-3.5" />
                    {t(TYPE_CONFIG[typeKey].labelKey, { defaultValue: TYPE_CONFIG[typeKey].label })}
                  </span>
                ),
                children:
                  typeKey === "page" ? (
                    <PagesTab
                      PageFormDialog={PageFormDialog}
                      VersionHistoryDialog={VersionHistoryDialog}
                      VersionDetail={VersionDetail}
                    />
                  ) : (
                    <NewsPublicationTab type={typeKey} />
                  ),
              };
            })}
          />
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
