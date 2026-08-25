import { DashboardOutlined, CloudUploadOutlined, FolderOpenOutlined, FileTextOutlined, ReadOutlined, SnippetsOutlined, SettingOutlined, CheckOutlined, BarChartOutlined, LeftOutlined, RightOutlined, EnvironmentOutlined, AppstoreOutlined, LayoutOutlined, RiseOutlined, EyeOutlined, PartitionOutlined } from "@ant-design/icons";
import type { ComponentType } from "react";
import { Link, useRouterState } from "@tanstack/react-router";
import { cn } from "../lib/cn";
interface NavItem {
  path: string;
  label: string;
  icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  /** Optional badge count. */
  badge?: number;
}

interface NavSection {
  label: string;
  items: NavItem[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    label: "Overview",
    items: [
      { path: "/", label: "Dashboard", icon: DashboardOutlined },
    ],
  },
  {
    label: "Data Management",
    items: [
      { path: "/resource-catalog", label: "Resource Catalog", icon: FolderOpenOutlined },
      { path: "/imports", label: "Imports", icon: CloudUploadOutlined },
    ],
  },
  {
    label: "Tools",
    items: [
      { path: "/news", label: "News", icon: ReadOutlined },
      { path: "/content", label: "Content", icon: FileTextOutlined },
    ],
  },
  {
    label: "Presentation",
    items: [
      { path: "/widgets", label: "Widgets", icon: AppstoreOutlined },
      { path: "/layout", label: "Layout Editor", icon: LayoutOutlined },
      { path: "/widget-preview", label: "Widget Preview", icon: EyeOutlined },
      { path: "/widget-health", label: "Widget Health", icon: RiseOutlined },
      { path: "/page-builder", label: "Page Builder", icon: PartitionOutlined },
    ],
  },
  {
    label: "Administration",
    items: [
      { path: "/audit", label: "Audit Logs", icon: SnippetsOutlined },
      { path: "/settings", label: "SettingOutlined", icon: SettingOutlined },
      { path: "/features", label: "Feature Flags", icon: CheckOutlined },
      { path: "/analytics-settings", label: "Analytics", icon: BarChartOutlined },
    ],
  },
];

interface AdminSidebarProps {
  /** Controlled collapsed state. */
  collapsed: boolean;
  /** Toggle collapsed state. */
  onToggleCollapsed: () => void;
}

/**
 * Admin sidebar navigation with collapsible sections and active-route
 * highlighting. Keyboard navigable via semantic <nav> and <a> elements.
 */
export function AdminSidebar({ collapsed, onToggleCollapsed }: AdminSidebarProps) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  return (
    <aside
      className={cn(
        "flex h-full flex-col border-r border-border bg-card transition-[width] duration-200",
        collapsed ? "w-16" : "w-64",
      )}
      aria-label="Admin navigation"
    >
      {/* Brand */}
      <div className="flex h-14 items-center gap-2 border-b border-border px-4">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <EnvironmentOutlined className="size-5" aria-hidden />
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate font-serif text-sm font-semibold">SoyMutDB</p>
            <p className="truncate text-xs text-muted-foreground">Admin Console</p>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="admin-sidebar-scroll flex-1 overflow-y-auto py-3">
        {NAV_SECTIONS.map((section) => (
          <SidebarSection key={section.label} section={section} collapsed={collapsed} pathname={pathname} />
        ))}
      </nav>

      {/* Collapse toggle */}
      <div className="border-t border-border p-2">
        <button
          type="button"
          onClick={onToggleCollapsed}
          className="flex w-full items-center justify-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
        >
          {collapsed ? (
            <RightOutlined className="size-4" aria-hidden />
          ) : (
            <>
              <LeftOutlined className="size-4" aria-hidden />
              <span>Collapse</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}

function SidebarSection({
  section,
  collapsed,
  pathname,
}: {
  section: NavSection;
  collapsed: boolean;
  pathname: string;
}) {
  return (
    <div className="mb-4">
      {!collapsed && (
        <p className="px-4 pb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground/70">
          {section.label}
        </p>
      )}
      <ul className="space-y-0.5 px-2">
        {section.items.map((item) => {
          const isActive =
            item.path === "/"
              ? pathname === "/"
              : pathname.startsWith(item.path);
          const Icon = item.icon;
          return (
            <li key={item.path}>
              <Link
                to={item.path}
                data-active={isActive}
                className={cn(
                  "admin-nav-item flex items-center gap-3 rounded-md px-2.5 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  isActive
                    ? "bg-primary/10 font-medium text-primary"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                  collapsed && "justify-center",
                )}
                title={collapsed ? item.label : undefined}
                aria-current={isActive ? "page" : undefined}
              >
                <Icon className="size-4 shrink-0" aria-hidden />
                {!collapsed && <span className="truncate">{item.label}</span>}
                {!collapsed && item.badge ? (
                  <span className="ml-auto rounded-full bg-primary/15 px-2 py-0.5 text-xs font-medium text-primary">
                    {item.badge}
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default AdminSidebar;
