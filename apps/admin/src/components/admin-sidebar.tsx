import {
  AppstoreOutlined,
  BarChartOutlined,
  CheckOutlined,
  CloudUploadOutlined,
  DashboardOutlined,
  DeleteOutlined,
  EnvironmentOutlined,
  ExperimentOutlined,
  FileAddOutlined,
  FileTextOutlined,
  FundOutlined,
  HomeOutlined,
  LayoutOutlined,
  MonitorOutlined,
  PictureOutlined,
  ReadOutlined,
  RiseOutlined,
  SettingOutlined,
  SnippetsOutlined,
} from "@ant-design/icons";
import type { ComponentType } from "react";

/**
 * The console's navigation data, and nothing else.
 *
 * `AdminShell` renders it with ProLayout, and the reachability and render
 * regression tests read the same list. An entry without a `path` is a submenu
 * whose destinations are its children, so a top-level label never has to point
 * at a placeholder page just to stay clickable.
 */
export interface NavItem {
  path?: string;
  label: string;
  labelKey: string;
  icon?: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  /** Optional badge count. */
  badge?: number;
  children?: NavItem[];
}

export interface NavSection {
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
      {
        label: "Dashboards",
        labelKey: "admin.shell.dashboards",
        icon: DashboardOutlined,
        children: [
          { path: "/", label: "Welcome", labelKey: "admin.dashboard.welcome", icon: HomeOutlined },
          { path: "/dashboard/analysis", label: "Analysis", labelKey: "admin.dashboard.analysis", icon: FundOutlined },
          { path: "/dashboard/monitor", label: "Monitor", labelKey: "admin.dashboard.monitor", icon: MonitorOutlined },
        ],
      },
      { path: "/guide", label: "Usage guide", labelKey: "admin.usage.title", icon: ReadOutlined },
    ],
  },
  {
    label: "Data Management",
    labelKey: "admin.shell.dataManagement",
    items: [
      {
        label: "Imports",
        labelKey: "admin.shell.imports",
        icon: CloudUploadOutlined,
        children: [
          { path: "/imports", label: "All imports", labelKey: "admin.shell.allImports", icon: SnippetsOutlined },
          { path: "/imports/new", label: "New import", labelKey: "admin.shell.newImport", icon: FileAddOutlined },
        ],
      },
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
      {
        label: "Pages",
        labelKey: "admin.shell.pagesGroup",
        icon: FileTextOutlined,
        children: [
          { path: "/content/pages", label: "Pages", labelKey: "admin.shell.pages", icon: FileTextOutlined },
        ],
      },
      {
        label: "News",
        labelKey: "admin.shell.newsGroup",
        icon: ReadOutlined,
        children: [
          { path: "/news", label: "All news", labelKey: "admin.shell.news", icon: ReadOutlined },
          { path: "/news/new", label: "New article", labelKey: "admin.shell.newArticle", icon: FileAddOutlined },
          { path: "/news/trash", label: "Trash", labelKey: "admin.shell.newsTrash", icon: DeleteOutlined },
        ],
      },
      { path: "/publications", label: "Publications", labelKey: "admin.shell.publications", icon: SnippetsOutlined },
      { path: "/media", label: "Media Library", labelKey: "admin.shell.media", icon: PictureOutlined },
    ],
  },
  {
    label: "Administration",
    labelKey: "admin.shell.administration",
    items: [
      { path: "/audit", label: "Audit Logs", labelKey: "admin.auditLogs", icon: SnippetsOutlined },
      {
        label: "Settings",
        labelKey: "admin.shell.settings",
        icon: SettingOutlined,
        children: [
          { path: "/settings", label: "Overview", labelKey: "admin.shell.settingsOverview", icon: SettingOutlined },
          { path: "/settings/brand", label: "Site branding", labelKey: "admin.brand.title", icon: PictureOutlined },
          { path: "/settings/appearance", label: "Appearance", labelKey: "admin.settings.appearance", icon: AppstoreOutlined },
          { path: "/settings/integrations", label: "Integrations", labelKey: "admin.settings.integrations", icon: SnippetsOutlined },
          { path: "/settings/security", label: "Security", labelKey: "admin.settings.security", icon: CheckOutlined },
          { path: "/settings/localization", label: "Localization", labelKey: "admin.settings.localization", icon: ReadOutlined },
          { path: "/settings/advanced", label: "Advanced", labelKey: "admin.settings.advanced", icon: ExperimentOutlined },
        ],
      },
      { path: "/table-templates", label: "Table templates", labelKey: "admin.tableViews.title", icon: FileTextOutlined },
      { path: "/features", label: "Feature Flags", labelKey: "admin.shell.featureFlags", icon: CheckOutlined },
      { path: "/analytics-settings", label: "Analytics", labelKey: "admin.shell.analytics", icon: BarChartOutlined },
    ],
  },
];