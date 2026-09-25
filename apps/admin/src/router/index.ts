import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import { useAuth } from "../lib/auth";

import AuditView from "../views/AuditView.vue";
import DashboardView from "../views/DashboardView.vue";
import FeaturesView from "../views/FeaturesView.vue";
import ImportsView from "../views/ImportsView.vue";
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
export const ADMIN_ROUTES: readonly (RouteRecordRaw & { nav?: string })[] = [
  { path: "/login", name: "login", component: LoginView },
  { path: "/", name: "dashboard", component: DashboardView, nav: "Dashboard" },
  { path: "/releases", name: "releases", component: ReleasesView, nav: "Releases" },
  { path: "/imports", name: "imports", component: ImportsView, nav: "Imports" },
  { path: "/table-templates", name: "table-templates", component: TableTemplatesView, nav: "Table templates" },
  { path: "/publications", name: "publications", component: PublicationsAdminView, nav: "Publications" },
  { path: "/news", name: "news", component: NewsAdminView, nav: "News" },
  { path: "/media", name: "media", component: MediaView, nav: "Media" },
  { path: "/audit", name: "audit", component: AuditView, nav: "Audit log" },
  { path: "/features", name: "features", component: FeaturesView, nav: "Capabilities" },
  { path: "/settings", name: "settings", component: SettingsView, nav: "Settings" },
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
