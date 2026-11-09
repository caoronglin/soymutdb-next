import { DashboardOutlined, CloudUploadOutlined, FileTextOutlined, ReadOutlined, SnippetsOutlined, SettingOutlined, CheckOutlined, BarChartOutlined, EnvironmentOutlined, RiseOutlined, PictureOutlined, ExperimentOutlined, AppstoreOutlined, LayoutOutlined } from "@ant-design/icons";
import type { ComponentType } from "react";

/**
 * The console's navigation data, and nothing else.
 *
 * This module used to also export an `AdminSidebar` React component.
 * `AdminShell` renders the navigation with antd `Layout`/`Menu` from the very
 * same list, so that component was never rendered by a route, a test, or an
 * entry point -- a second navigation renderer that only looked live. It
 * outlived its role because the regression tests import `NAV_SECTIONS` from
 * here. The console's one navigation renderer lives in `admin-shell.tsx`.
 */
interface NavItem {
  path: string;
  label: string;
  labelKey: string;
  icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  /** Optional badge count. */
  badge?: number;
}

interface NavSection {
  label: string;
  labelKey: string;
  items: NavItem[];
}

/**
 * The one navigation source of truth for the console.
 *
 * Every entry must land on a page that does something. The routes that resolve
 * to `LegacyUnavailablePage` — the ADR-0009 retirements and `/resource-catalog`,
 * which has no backing API — are deliberately absent: a menu entry that opens
 * "this page is unavailable" is a dead end an operator cannot act on. They stay
 * in the router so an old deep link still explains itself, and
 * `regression/nav-reachability.test.ts` fails if one of them reappears here.
 */
export const NAV_SECTIONS: NavSection[] = [
  {
    label: "Overview",
    labelKey: "admin.shell.overview",
    items: [
      { path: "/", label: "Dashboard", labelKey: "admin.dashboard.title", icon: DashboardOutlined },
      { path: "/guide", label: "Usage guide", labelKey: "admin.usage.title", icon: ReadOutlined },
    ],
  },
  {
    label: "Data Management",
    labelKey: "admin.shell.dataManagement",
    items: [
      { path: "/imports", label: "Imports", labelKey: "admin.shell.imports", icon: CloudUploadOutlined },
      { path: "/releases", label: "Releases", labelKey: "admin.releases", icon: RiseOutlined },
      { path: "/data-views", label: "Data views", labelKey: "admin.shell.dataViews", icon: LayoutOutlined },
      { path: "/instances", label: "Instances", labelKey: "admin.instances.title", icon: EnvironmentOutlined },
      { path: "/preview-test-data", label: "Test Data Preview", labelKey: "admin.shell.previewTestData", icon: ExperimentOutlined },
    ],
  },
  {
    label: "Content",
    labelKey: "admin.shell.content",
    items: [
      { path: "/site-control", label: "Site control", labelKey: "admin.siteControl.title", icon: AppstoreOutlined },
      { path: "/page-builder", label: "Page Builder", labelKey: "admin.pageBuilder.title", icon: LayoutOutlined },
      { path: "/content/pages", label: "Pages", labelKey: "admin.shell.pages", icon: FileTextOutlined },
      { path: "/content/legacy", label: "Legacy Pages", labelKey: "admin.shell.legacyPages", icon: FileTextOutlined },
      { path: "/news", label: "News", labelKey: "admin.shell.news", icon: ReadOutlined },
      { path: "/publications", label: "Publications", labelKey: "admin.shell.publications", icon: SnippetsOutlined },
      { path: "/media", label: "Media Library", labelKey: "admin.shell.media", icon: PictureOutlined },
    ],
  },
  {
    label: "Administration",
    labelKey: "admin.shell.administration",
    items: [
      { path: "/audit", label: "Audit Logs", labelKey: "admin.auditLogs", icon: SnippetsOutlined },
      { path: "/settings", label: "Settings", labelKey: "admin.shell.settings", icon: SettingOutlined },
      { path: "/settings/brand", label: "Site branding", labelKey: "admin.brand.title", icon: PictureOutlined },
      { path: "/table-templates", label: "Table templates", labelKey: "admin.tableViews.title", icon: FileTextOutlined },
      { path: "/features", label: "Feature Flags", labelKey: "admin.shell.featureFlags", icon: CheckOutlined },
      { path: "/analytics-settings", label: "Analytics", labelKey: "admin.shell.analytics", icon: BarChartOutlined },
    ],
  },
];
