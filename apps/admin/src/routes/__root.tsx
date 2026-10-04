import * as React from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { AdminHeader } from "../components/admin-header";
import { Link, useRouterState } from "@tanstack/react-router";
import { ProLayout } from "../lib/antd";
import { NAV_SECTIONS } from "../components/admin-sidebar";

interface AdminLayoutProps {
  children: ReactNode;
}

/** Page titles mapped by route path prefix. */
const PAGE_TITLES: Record<string, { key: string; defaultValue: string }> = {
  "/": { key: "admin.dashboard.title", defaultValue: "Dashboard" },
  "/guide": { key: "admin.usage.title", defaultValue: "Usage guide" },
  "/resource-catalog": { key: "admin.shell.resourceCatalog", defaultValue: "Resource Catalog" },
  "/releases": { key: "admin.releases", defaultValue: "Releases" },
  "/instances": { key: "admin.instances.title", defaultValue: "Instances" },
  "/imports": { key: "admin.imports", defaultValue: "Data Imports" },
  "/content": { key: "admin.content.title", defaultValue: "Content Management" },
  "/publications": { key: "admin.content.publications", defaultValue: "Publications" },
  "/media": { key: "admin.shell.media", defaultValue: "Media Library" },
  "/table-templates": { key: "admin.tableViews.title", defaultValue: "Table templates" },
  "/features": { key: "admin.shell.featureFlags", defaultValue: "Feature Flags" },
  "/analytics-settings": { key: "admin.shell.analytics", defaultValue: "Analytics Settings" },
  "/news": { key: "admin.news.title", defaultValue: "News Management" },
  "/audit": { key: "admin.auditLogs", defaultValue: "Audit Logs" },
  "/settings": { key: "admin.settings.title", defaultValue: "System Settings" },
  "/settings/brand": { key: "admin.brand.title", defaultValue: "Site branding" },
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

  // Keep every admin destination visible by default. The former nested menu
  // rendered only collapsed section labels, which looked like a blank sidebar
  // until an operator discovered the tiny disclosure arrows.
  const proRoute = React.useMemo(() => ({
    path: "/",
    routes: NAV_SECTIONS.flatMap((section) => section.items.map((item) => ({
      path: item.path,
      name: t(item.labelKey, { defaultValue: item.label }),
      icon: React.createElement(item.icon),
    }))),
  }), [t]);



  return (
    <ProLayout
      title="SoyMutDB"
      logo={false}
      layout="side"
      navTheme="light"
      fixSiderbar
      location={{ pathname }}
      route={proRoute}
      headerRender={false}
      menuItemRender={(item, dom) =>
        // Client-side navigation: an <a href> reloads the whole document on
        // every sidebar click (2026-10-01 admin Pro migration §3.1).
        item.path ? <Link to={item.path}>{dom}</Link> : dom
      }
      breadcrumbRender={false}
      contentStyle={{ padding: 24, minHeight: "calc(100vh - 56px)" }}
      menu={{ locale: true }}
    >
      <div className="w-full min-w-0 space-y-6">
        <AdminHeader title={title} />
        <div className="w-full min-w-0 space-y-6">
          {children}
        </div>
      </div>
    </ProLayout>
  );
}
