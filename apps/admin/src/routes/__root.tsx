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

/**
 * Admin root layout: collapsible sidebar + sticky header + scrollable content.
 * Responsive: sidebar collapses to icons on desktop and overlays on mobile.
 *
 * The shell does NOT name the current page. The former `PAGE_TITLES` map
 * resolved a title here and handed it to `AdminHeader`, which put a second
 * `<h1>` above every page that already declares its own `PageContainer`
 * `title`/`subTitle` (2026-10-01 admin Pro migration §3.1). Two authorities for
 * one page name is exactly the divergence the slice existed to remove, and the
 * map could only ever cover the paths somebody remembered to add. `PageContainer`
 * is now the single owner: the title lives with the page that owns the content.
 */
export default function AdminLayout({ children }: AdminLayoutProps) {
  const { t } = useTranslation();
  const pathname = useRouterState({ select: (s) => s.location.pathname });

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
    <div data-testid="admin-shell" className="min-h-screen min-w-0">
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
        <AdminHeader />
        <div className="w-full min-w-0 space-y-6">
          {children}
        </div>
      </div>
      </ProLayout>
    </div>
  );
}
