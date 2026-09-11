import { type ReactNode, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { AdminSidebar } from "../components/admin-sidebar";
import { AdminHeader } from "../components/admin-header";
import { AdminUsageGuide } from "../components/admin-usage-guide";
import { useRouterState } from "@tanstack/react-router";

interface AdminLayoutProps {
  children: ReactNode;
}

/** Page titles mapped by route path prefix. */
const PAGE_TITLES: Record<string, { key: string; defaultValue: string }> = {
  "/": { key: "admin.dashboard.title", defaultValue: "Dashboard" },
  "/resource-catalog": { key: "admin.shell.resourceCatalog", defaultValue: "Resource Catalog" },
  "/imports": { key: "admin.imports", defaultValue: "Data Imports" },
  "/content": { key: "admin.content.title", defaultValue: "Content Management" },
  "/publications": { key: "admin.content.publications", defaultValue: "Publications" },
  "/news": { key: "admin.news.title", defaultValue: "News Management" },
  "/audit": { key: "admin.auditLogs", defaultValue: "Audit Logs" },
  "/settings": { key: "admin.settings.title", defaultValue: "System Settings" },
  "/widgets": { key: "admin.shell.widgetManager", defaultValue: "Widget Manager" },
  "/layout": { key: "admin.shell.layoutEditor", defaultValue: "Layout Editor" },
  "/widget-preview": { key: "admin.shell.widgetPreview", defaultValue: "Widget Preview" },
  "/widget-health": { key: "admin.shell.widgetHealth", defaultValue: "Widget Health" },
};

/**
 * Admin root layout: collapsible sidebar + sticky header + scrollable content.
 * Responsive: sidebar collapses to icons on desktop and overlays on mobile.
 */
export default function AdminLayout({ children }: AdminLayoutProps) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const pathname = useRouterState({ select: (s) => s.location.pathname });
  // Exact match first, then longest-prefix match for sub-routes like /widgets/foo
  const titleEntry =
    PAGE_TITLES[pathname] ??
    Object.entries(PAGE_TITLES)
      .filter(([p]) => p !== "/" && pathname.startsWith(p + "/"))
      .sort((a, b) => b[0].length - a[0].length)[0]?.[1];
  const title = titleEntry
    ? t(titleEntry.key, { defaultValue: titleEntry.defaultValue })
    : t("admin.shell.fallbackTitle", { defaultValue: "Admin" });

  const toggleCollapsed = useCallback(() => setCollapsed((p) => !p), []);
  const toggleMobile = useCallback(() => setMobileOpen((p) => !p), []);

  const usageItems = [
    {
      key: "workflow",
      title: t("admin.usage.workflowTitle", { defaultValue: "Standard admin workflow" }),
      steps: [
        t("admin.usage.workflowStep1", { defaultValue: "Sign in with an administrator account." }),
        t("admin.usage.workflowStep2", { defaultValue: "Load the current resource before editing." }),
        t("admin.usage.workflowStep3", { defaultValue: "Save through the bound API and wait for success." }),
        t("admin.usage.workflowStep4", { defaultValue: "Review audit or version history before publishing." }),
      ],
      api: ["POST /auth/refresh", "GET|PUT /api/v1/admin/*"],
      tables: ["users", "audit_logs"],
      note: t("admin.usage.workflowNote", { defaultValue: "The Admin UI never writes PostgreSQL directly." }),
    },
    {
      key: "content",
      title: t("admin.usage.contentTitle", { defaultValue: "Content and publication workflow" }),
      steps: [
        t("admin.usage.contentStep1", { defaultValue: "Edit bilingual fields independently." }),
        t("admin.usage.contentStep2", { defaultValue: "Preview the saved server payload before publishing." }),
        t("admin.usage.contentStep3", { defaultValue: "Check links, images, fallback, and layout." }),
        t("admin.usage.contentStep4", { defaultValue: "Use version history to restore static pages." }),
      ],
      api: ["GET|POST|PUT /admin/content/pages", "GET|POST|PUT|DELETE /admin/publications", "GET /content/snapshot"],
      tables: ["static_pages", "content_versions", "publications"],
      note: t("admin.usage.contentNote", { defaultValue: "PostgreSQL content is copied into a release-aware snapshot for public reads." }),
    },
    {
      key: "data",
      title: t("admin.usage.dataTitle", { defaultValue: "Import, validation, and release workflow" }),
      steps: [
        t("admin.usage.dataStep1", { defaultValue: "Create an import task and wait for validation." }),
        t("admin.usage.dataStep2", { defaultValue: "Resolve validation errors before ingestion." }),
        t("admin.usage.dataStep3", { defaultValue: "Build a release from ready datasets." }),
        t("admin.usage.dataStep4", { defaultValue: "Use rollback and audit evidence when withdrawing a release." }),
      ],
      api: ["POST /admin/imports", "POST /admin/releases", "POST /admin/releases/{id}/publish"],
      tables: ["import_tasks", "data_sets", "releases", "release_data_sets"],
      note: t("admin.usage.dataNote", { defaultValue: "PostgreSQL owns state; object storage holds files and workers execute long jobs." }),
    },
    {
      key: "performance",
      title: t("admin.usage.performanceTitle", { defaultValue: "Performance and failure boundaries" }),
      steps: [
        t("admin.usage.performanceStep1", { defaultValue: "Use pagination and search for lists." }),
        t("admin.usage.performanceStep2", { defaultValue: "Reuse query data and invalidate only changed resources." }),
        t("admin.usage.performanceStep3", { defaultValue: "Keep ingestion and analysis in workers." }),
        t("admin.usage.performanceStep4", { defaultValue: "Show explicit errors instead of fake values." }),
      ],
      api: ["GET /admin/dashboard-*", "GET /admin/widgets/health"],
      tables: ["PostgreSQL indexes", "Redis widget cache"],
      note: t("admin.usage.performanceNote", { defaultValue: "Bounded pools, statement timeouts, and cache invalidation protect the API." }),
    },
  ];

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Desktop sidebar */}
      <div className="hidden lg:block">
        <AdminSidebar collapsed={collapsed} onToggleCollapsed={toggleCollapsed} />
      </div>

      {/* Mobile sidebar overlay */}
      {mobileOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setMobileOpen(false)}
            aria-hidden
          />
          <div className="absolute left-0 top-0 h-full">
            <AdminSidebar collapsed={false} onToggleCollapsed={() => setMobileOpen(false)} />
          </div>
        </div>
      ) : null}

      {/* Main content area */}
      <div className="flex min-w-0 flex-1 flex-col">
        <AdminHeader onToggleSidebar={toggleMobile} title={title} />
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-7xl space-y-4 p-4 md:space-y-6 md:p-6">
            <AdminUsageGuide items={usageItems} />
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
