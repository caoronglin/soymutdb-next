import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import { useAuth } from "../lib/auth";

import AuditView from "../views/AuditView.vue";
import DashboardView from "../views/DashboardView.vue";
import FeaturesView from "../views/FeaturesView.vue";
import ImportCreateView from "../views/ImportCreateView.vue";
import ImportDetailView from "../views/ImportDetailView.vue";
import ImportsView from "../views/ImportsView.vue";
import LegacyUnavailableView from "../views/LegacyUnavailableView.vue";
import LoginView from "../views/LoginView.vue";
import MediaView from "../views/MediaView.vue";
import NewsAdminView from "../views/NewsAdminView.vue";
import NotFoundView from "../views/NotFoundView.vue";
import PublicationsAdminView from "../views/PublicationsAdminView.vue";
import ReleasesView from "../views/ReleasesView.vue";
import SettingsView from "../views/SettingsView.vue";
import TableTemplatesView from "../views/TableTemplatesView.vue";

/**
 * Admin routes.
 *
 * The console is administrator-only end to end: every route except `/login`
 * requires a session, and the guard redirects rather than rendering a page that
 * would then fail every request with 401. The API enforces the role itself; the
 * guard is a UX affordance, never the authorization boundary.
 */
export const ADMIN_ROUTES: readonly (RouteRecordRaw & { navKey?: string })[] = [
  { path: "/login", name: "login", component: LoginView },
  { path: "/", name: "dashboard", component: DashboardView, navKey: "admin.dashboard" },
  { path: "/releases", name: "releases", component: ReleasesView, navKey: "admin.releases" },
  { path: "/imports", name: "imports", component: ImportsView, navKey: "admin.imports" },
  { path: "/imports/new", name: "import-create", component: ImportCreateView },
  { path: "/imports/:taskId", name: "import-detail", component: ImportDetailView },
  { path: "/table-templates", name: "table-templates", component: TableTemplatesView, navKey: "admin.tableViews" },
  { path: "/publications", name: "publications", component: PublicationsAdminView, navKey: "publications.title" },
  { path: "/news", name: "news", component: NewsAdminView, navKey: "admin.news.title" },
  { path: "/media", name: "media", component: MediaView, navKey: "admin.uploads" },
  { path: "/audit", name: "audit", component: AuditView, navKey: "admin.auditLogs" },
  { path: "/features", name: "features", component: FeaturesView, navKey: "admin.features" },
  { path: "/instances", name: "instances", component: () => import("../views/SpeciesInstancesView.vue"), navKey: "admin.instances.title" },
  { path: "/settings", name: "settings", component: SettingsView, navKey: "admin.settings" },
  { path: "/settings/brand", name: "settings-brand", component: () => import("../views/SiteBrandSettingsView.vue") },

  // --- Legacy React-console deep links ---------------------------------
  // A restored equivalent redirects; a workflow that has not been ported yet
  // lands on an explicit "not restored" page. Neither case may be a bare 404
  // or an empty shell (migration plan: "旧深链逐条可到达或有明确重定向").
  { path: "/settings/site", redirect: "/settings/brand" },
  { path: "/settings/security", redirect: { path: "/settings", query: { section: "security" } } },
  { path: "/news/new", redirect: { path: "/news", query: { new: "1" } } },
  { path: "/news/trash", redirect: { path: "/news", query: { status: "archived" } } },
  { path: "/news/:id", redirect: (to) => ({ path: "/news", query: { edit: String(to.params.id) } }) },
  { path: "/resource-catalog", component: LegacyUnavailableView },
  { path: "/content", component: LegacyUnavailableView },
  { path: "/content/pages", component: LegacyUnavailableView },
  { path: "/content/legacy", component: LegacyUnavailableView },
  { path: "/settings/legacy", component: LegacyUnavailableView },
  { path: "/settings/appearance", component: LegacyUnavailableView },
  { path: "/settings/integrations", component: LegacyUnavailableView },
  { path: "/settings/localization", component: LegacyUnavailableView },
  { path: "/settings/advanced", component: LegacyUnavailableView },
  { path: "/analytics-settings", component: LegacyUnavailableView },
  { path: "/widgets", component: LegacyUnavailableView },
  { path: "/widgets/:name", component: LegacyUnavailableView },
  { path: "/layout", component: LegacyUnavailableView },
  { path: "/widget-preview", component: LegacyUnavailableView },
  { path: "/widget-health", component: LegacyUnavailableView },
  { path: "/page-builder", component: LegacyUnavailableView },
  { path: "/page-builder/:pageId", component: LegacyUnavailableView },
  { path: "/:pathMatch(.*)*", name: "not-found", component: NotFoundView },
];

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [...ADMIN_ROUTES],
});

router.beforeEach(async (to) => {
  const auth = useAuth();
  await auth.restore();
  if (to.name === "login") return true;
  if (!auth.isAuthenticated.value) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  return true;
});
