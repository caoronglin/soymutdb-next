import { ReadOutlined, EyeOutlined, FileTextOutlined, HistoryOutlined, EditOutlined, PlusOutlined, RedoOutlined, SaveOutlined, SendOutlined, DeleteOutlined, CloseOutlined } from "@ant-design/icons";
import * as React from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { http } from "@soymutdb/api-client";
import { Modal, Typography, Badge, Button, Card, Input, Select } from "@/lib/antd";
import { DataTable, type DataTableColumn } from "../components/data-table";
import { ConfirmDialog } from "../components/confirm-dialog";
import { contentKeys } from "./content/query-keys";
import { VersionMetadata } from "./content/version-metadata";
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
type PageStatus = "draft" | "published" | "archived";

interface ContentItem {
  id: string;
  type: ContentType;
  title: string;
  slug: string;
  status: PageStatus;
  author: string;
  publishedAt: string | null;
  updatedAt: string;
}

interface StaticPage {
  id: string;
  slug: string;
  title_en: string;
  title_zh: string | null;
  content_en: string;
  content_zh: string | null;
  summary: string | null;
  category: string | null;
  status: PageStatus;
  sort_order: number;
  author_name: string | null;
  published_at: string | null;
  current_version: number;
  created_at: string;
  updated_at: string;
}

interface StaticPageCreate {
  slug: string;
  title_en: string;
  title_zh?: string;
  content_en: string;
  content_zh?: string;
  summary?: string;
  category?: string;
  sort_order?: number;
  status?: PageStatus;
  edit_comment?: string;
}

interface StaticPageUpdate {
  title_en?: string;
  title_zh?: string;
  content_en?: string;
  content_zh?: string;
  summary?: string;
  category?: string;
  sort_order?: number;
  edit_comment?: string;
}

interface ContentVersion {
  id: string;
  page_id: string;
  version: number;
  title_en: string;
  title_zh: string | null;
  content_en: string;
  content_zh: string | null;
  summary: string | null;
  edited_by: string | null;
  edit_comment: string | null;
  created_at: string;
}

interface PageListResponse {
  items: StaticPage[];
  total: number;
}

interface PageFormValues {
  slug: string;
  title_en: string;
  title_zh: string;
  content_en: string;
  content_zh: string;
  summary: string;
  category: string;
  sort_order: string;
  status: PageStatus;
  edit_comment: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TYPE_CONFIG: Record<ContentType, { label: string; icon: typeof ReadOutlined }> = {
  news: { label: "News", icon: ReadOutlined },
  publication: { label: "Publication", icon: ReadOutlined },
  page: { label: "Pages", icon: FileTextOutlined },
};

function statusBadgeVariant(
  status: PageStatus,
): "warning" | "success" | "secondary" {
  if (status === "published") return "success";
  if (status === "draft") return "warning";
  return "secondary";
}

function getErrorMessage(err: unknown, t: (key: string, options?: Record<string, unknown>) => string): string {
  if (err instanceof Error) return err.message;
  return t("admin.content.unknownError", { defaultValue: "An unknown error occurred" });
}

function initFormValues(editing: StaticPage | null): PageFormValues {
  if (editing) {
    return {
      slug: editing.slug,
      title_en: editing.title_en,
      title_zh: editing.title_zh ?? "",
      content_en: editing.content_en,
      content_zh: editing.content_zh ?? "",
      summary: editing.summary ?? "",
      category: editing.category ?? "",
      sort_order: String(editing.sort_order ?? 0),
      status: editing.status === "published" ? "published" : "draft",
      edit_comment: "",
    };
  }
  return {
    slug: "",
    title_en: "",
    title_zh: "",
    content_en: "",
    content_zh: "",
    summary: "",
    category: "",
    sort_order: "0",
    status: "draft",
    edit_comment: "",
  };
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ContentPage() {
  const { t } = useTranslation();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const isLegacyRoute = pathname === "/content/legacy";
  const [tab, setTab] = React.useState<ContentType>("page");

  return (
    <div className="space-y-6">
      <div><Typography.Title level={2}>{t("admin.content.title", { defaultValue: "Content Management" })}</Typography.Title><Typography.Text type="secondary">{t("admin.content.subtitle", { defaultValue: "Manage static pages, news articles, and publications with full version history." })}</Typography.Text></div>

      {isLegacyRoute && (
        <>
          <div className="rounded-lg border border-border bg-muted/30 px-4 py-3">
            <span className="mr-2 rounded-full bg-muted px-2 py-1 text-xs font-medium">Legacy Pages</span>
            <Typography.Text type="secondary">
              Existing pages remain editable. The migration preview below is read-only and proposes draft candidates only.
            </Typography.Text>
          </div>
          <StaticPageMigrationReport />
        </>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-border">
        {(Object.keys(TYPE_CONFIG) as ContentType[]).map((typeKey) => {
          const Icon = TYPE_CONFIG[typeKey].icon;
          return (
            <button
              key={typeKey}
              type="button"
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
    </div>
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
