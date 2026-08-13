import { type ReactNode, useState, useCallback } from "react";
import { AdminSidebar } from "../components/admin-sidebar";
import { AdminHeader } from "../components/admin-header";
import { useRouterState } from "@tanstack/react-router";

interface AdminLayoutProps {
  children: ReactNode;
}

/** Page titles mapped by route path prefix. */
const PAGE_TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/resource-catalog": "Resource Catalog",
  "/imports": "Data Imports",
  "/content": "Content Management",
  "/news": "News Management",
  "/audit": "Audit Logs",
  "/settings": "System Settings",
  "/widgets": "Widget Manager",
  "/layout": "Layout Editor",
  "/widget-preview": "Widget Preview",
  "/widget-health": "Widget Health",
};

/**
 * Admin root layout: collapsible sidebar + sticky header + scrollable content.
 * Responsive: sidebar collapses to icons on desktop and overlays on mobile.
 */
export default function AdminLayout({ children }: AdminLayoutProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const pathname = useRouterState({ select: (s) => s.location.pathname });
  // Exact match first, then longest-prefix match for sub-routes like /widgets/foo
  const title =
    PAGE_TITLES[pathname] ??
    Object.entries(PAGE_TITLES)
      .filter(([p]) => p !== "/" && pathname.startsWith(p + "/"))
      .sort((a, b) => b[0].length - a[0].length)[0]?.[1] ??
    "Admin";

  const toggleCollapsed = useCallback(() => setCollapsed((p) => !p), []);
  const toggleMobile = useCallback(() => setMobileOpen((p) => !p), []);

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
          <div className="mx-auto max-w-7xl p-4 md:p-6">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
