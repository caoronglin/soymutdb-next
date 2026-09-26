import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import { useAuth } from "../lib/auth";

import AnalyticsSettingsView from "../views/AnalyticsSettingsView.vue";
import AuditView from "../views/AuditView.vue";
import ContentLegacyMigrationView from "../views/ContentLegacyMigrationView.vue";
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
import StaticPagesView from "../views/StaticPagesView.vue";
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
  { path: "/content", name: "content", component: StaticPagesView, navKey: "admin.content" },
  { path: "/content/pages", name: "content-pages", component: StaticPagesView },
  {
    path: "/content/pages/:pageId",
    name: "content-page-detail",
    redirect: (to) => ({ path: "/content", query: { edit: String(to.params.pageId) } }),
  },
  { path: "/content/legacy", name: "content-legacy", component: ContentLegacyMigrationView },
  { path: "/table-templates", name: "table-templates", component: TableTemplatesView, navKey: "admin.tableViews" },
  { path: "/publications", name: "publications", component: PublicationsAdminView, navKey: "publications.title" },
  { path: "/news", name: "news", component: NewsAdminView, navKey: "admin.news.title" },
  { path: "/media", name: "media", component: MediaView, navKey: "admin.uploads" },
  { path: "/audit", name: "audit", component: AuditView, navKey: "admin.auditLogs" },
  { path: "/features", name: "features", component: FeaturesView, navKey: "admin.features" },
  { path: "/instances", name: "instances", component: () => import("../views/SpeciesInstancesView.vue"), navKey: "admin.instances.title" },
  { path: "/settings", name: "settings", component: SettingsView, navKey: "admin.settings" },
  { path: "/settings/brand", name: "settings-brand", component: () => import("../views/SiteBrandSettingsView.vue") },
  { path: "/analytics-settings", name: "analytics-settings", component: AnalyticsSettingsView },

  // --- Legacy React-console deep links ---------------------------------
  // A restored equivalent redirects; a workflow that has not been ported yet
  // lands on an explicit "not restored" page. Neither case may be a bare 404
  // or an empty shell (migration plan: "旧深链逐条可到达或有明确重定向").
  //
  // Settings sub-pages map onto the registered sections of the schema-driven
  // SettingsView. The ids below are the live keys returned by
  // GET /admin/settings/schema (app/core/settings_registry.py): appearance and
  // localization are the "general" section (defaultTheme / primaryColor /
  // defaultLanguage), integrations is "cdn", and advanced is "data". The legacy
  // monolithic form is replaced by the overview, which exposes every section.
  // If a section ever stops being registered, SettingsView renders a documented
  // unavailable state instead of silently opening the first section.
  { path: "/settings/site", redirect: "/settings/brand" },
  { path: "/settings/security", redirect: { path: "/settings", query: { section: "security" } } },
  { path: "/settings/appearance", redirect: { path: "/settings", query: { section: "general" } } },
  { path: "/settings/integrations", redirect: { path: "/settings", query: { section: "cdn" } } },
  { path: "/settings/localization", redirect: { path: "/settings", query: { section: "general" } } },
  { path: "/settings/advanced", redirect: { path: "/settings", query: { section: "data" } } },
  { path: "/settings/legacy", redirect: "/settings" },
  { path: "/news/new", redirect: { path: "/news", query: { new: "1" } } },
  { path: "/news/trash", redirect: { path: "/news", query: { status: "archived" } } },
  { path: "/news/:id", redirect: (to) => ({ path: "/news", query: { edit: String(to.params.id) } }) },
  // Resource catalog had no backing API in React (it was a static link grid)
  // and still has none, so it keeps an explicit, documented unavailable page
  // rather than fabricated catalog data. It links to the console destinations
  // that grid pointed at.
  {
    path: "/resource-catalog",
    name: "resource-catalog",
    component: LegacyUnavailableView,
    props: {
      reasonKey: "admin.legacyUnavailable.resourceCatalogReason",
      statusKey: "admin.legacyUnavailable.notImplemented",
      referenceTo: "/imports",
      referenceLabelKey: "admin.legacyUnavailable.applicationsReference",
    },
  },
  // ADR-0009 retirement boundary: the page builder and widget system stay
  // retired; these deep links must remain reachable but never become editors.
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
