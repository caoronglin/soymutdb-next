import { DashboardOutlined, CloudUploadOutlined, FolderOpenOutlined, FileTextOutlined, ReadOutlined, SnippetsOutlined, SettingOutlined, CheckOutlined, BarChartOutlined, EnvironmentOutlined, RiseOutlined, PictureOutlined, ExperimentOutlined } from "@ant-design/icons";
import type { ComponentType } from "react";
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
      { path: "/resource-catalog", label: "Resource Catalog", labelKey: "admin.shell.resourceCatalog", icon: FolderOpenOutlined },
      { path: "/imports", label: "Imports", labelKey: "admin.shell.imports", icon: CloudUploadOutlined },
      { path: "/releases", label: "Releases", labelKey: "admin.releases", icon: RiseOutlined },
      { path: "/instances", label: "Instances", labelKey: "admin.instances.title", icon: EnvironmentOutlined },
      { path: "/preview-test-data", label: "Test Data Preview", labelKey: "admin.shell.previewTestData", icon: ExperimentOutlined },
    ],
  },
  {
    label: "Content",
    labelKey: "admin.shell.content",
    items: [
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


// ProLayout renders the menu directly from NAV_SECTIONS.
// The retired hand-crafted sidebar component was never mounted or imported.
