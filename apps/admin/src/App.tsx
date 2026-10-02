import { lazy, Suspense } from "react";
import {
  createRouter,
  createRootRoute,
  createRoute,
  redirect,
  RouterProvider,
  Outlet,
} from "@tanstack/react-router";
import { Skeleton } from "@/lib/antd";
import { ErrorBoundary } from "./components/error-boundary";
import { RouteErrorBoundary } from "./components/route-error-boundary";
import AdminLayout from "./routes/__root";
import LoginPage from "./routes/login";
import { useAuth } from "./lib/auth-context";
import { InstanceContextProvider } from "./lib/instance-context-react";
import { parseContentPageSearch } from "./routes/content/search";
import {
  parseMotionPreference,
  resolveMotionDecision,
  type MotionPreference,
} from "./lib/motion-policy";

// Lazy-loaded route components (code-splitting per route).
const DashboardPage = lazy(() => import("./routes/index"));
const UsageGuidePage = lazy(() => import("./routes/usage-guide"));
const LegacyUnavailablePage = lazy(() => import("./routes/legacy-unavailable"));
const ReleasesPage = lazy(() => import("./routes/releases"));
const PreviewTestDataPage = lazy(() => import("./routes/preview-test-data"));
const InstancesPage = lazy(() => import("./routes/instances"));
const SiteBrandPage = lazy(() => import("./routes/settings/brand"));
const ImportsPage = lazy(() => import("./routes/imports"));
const NewImportPage = lazy(() => import("./routes/imports/new"));
const ImportTaskDetailPage = lazy(() => import("./routes/imports/task-detail"));
const ContentPage = lazy(() => import("./routes/content"));
const MediaPage = lazy(() => import("./routes/media"));
const NewsListPage = lazy(() => import("./routes/news/index"));
const NewsNewPage = lazy(() => import("./routes/news/new"));
const NewsTrashPage = lazy(() => import("./routes/news/trash"));
const NewsEditPage = lazy(() => import("./routes/news/$id"));
const AuditPage = lazy(() => import("./routes/audit"));
const SettingsLegacyPage = lazy(() => import("./routes/settings"));
const SettingsOverviewPage = lazy(() => import("./routes/settings/index"));
const SettingsAppearancePage = lazy(() => import("./routes/settings/appearance"));
const SettingsIntegrationsPage = lazy(() => import("./routes/settings/integrations"));
const SettingsSecurityPage = lazy(() => import("./routes/settings/security"));
const SettingsLocalizationPage = lazy(() => import("./routes/settings/localization"));
const SettingsAdvancedPage = lazy(() => import("./routes/settings/advanced"));
const FeaturesPage = lazy(() => import("./routes/features"));
const AnalyticsSettingsPage = lazy(() => import("./routes/analytics-settings"));
const PublicationsAdminPage = lazy(() => import("./routes/publications"));
const TableViewsPage = lazy(() => import("./routes/table-views"));

/** Loading fallback for lazy-loaded routes. */
function RouteLoading() {
  return (
    <div className="route-fade-in space-y-4 p-6" role="status" aria-live="polite">
      <Skeleton className="h-8 w-48" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-28 w-full rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-96 w-full rounded-lg" />
    </div>
  );
}

/** Wrap a lazy component in a Suspense boundary. */
function withSuspense(Component: React.LazyExoticComponent<React.ComponentType>) {
  return (
    <RouteErrorBoundary>
      <Suspense fallback={<RouteLoading />}>
        <Component />
      </Suspense>
    </RouteErrorBoundary>
  );
}

// --- Route tree (manual, no code generation required) -----------------

/**
 * Root shell: renders whichever child matched (the public `/login` route or
 * the auth-guarded admin layout). No chrome here so `/login` can render
 * standalone, outside the AdminLayout.
 */
const rootRoute = createRootRoute({
  component: () => (
    <ErrorBoundary>
      <Outlet />
    </ErrorBoundary>
  ),
});

/** Public login route — no AdminLayout, no auth guard. */
const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  component: LoginPage,
});

/**
 * Pathless layout route guarding the admin section. When unauthenticated it
 * shows the Login page instead of the admin chrome; when authenticated it
 * wraps the matched child in the AdminLayout.
 */
const authLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "_auth",
  component: RequireAuth,
});

/** Auth guard + admin chrome wrapper. */
function RequireAuth() {
  const { isRestoringSession, isAuthenticated } = useAuth();
  if (isRestoringSession) {
    return <RouteLoading />;
  }
  if (!isAuthenticated) {
    return <LoginPage />;
  }
  return (
    <InstanceContextProvider>
      <AdminLayout>
        <Outlet />
      </AdminLayout>
    </InstanceContextProvider>
  );
}

const dashboardRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/",
  component: () => withSuspense(DashboardPage),
});

const usageGuideRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/guide",
  component: () => withSuspense(UsageGuidePage),
});

const releasesRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/releases",
  component: () => withSuspense(ReleasesPage),
});

const instancesRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/instances",
  component: () => withSuspense(InstancesPage),
});

const previewTestDataRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/preview-test-data",
  component: () => withSuspense(PreviewTestDataPage),
});

const resourceCatalogRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/resource-catalog",
  component: () => withSuspense(LegacyUnavailablePage),
});

const importsRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/imports",
  component: () => withSuspense(ImportsPage),
});

const newImportRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/imports/new",
  component: () => withSuspense(NewImportPage),
});

const importTaskDetailRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/imports/$taskId",
  component: () => withSuspense(ImportTaskDetailPage),
});

const contentRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/content",
  validateSearch: parseContentPageSearch,
  component: () => withSuspense(ContentPage),
});

const contentPagesRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/content/pages",
  validateSearch: parseContentPageSearch,
  component: () => withSuspense(ContentPage),
});

const contentPageDetailRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/content/pages/$pageId",
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/content",
      search: { page: 1, status: "all", category: "", edit: params.pageId },
    });
  },
});

const contentLegacyRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/content/legacy",
  validateSearch: parseContentPageSearch,
  component: () => withSuspense(ContentPage),
});

const mediaRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/media",
  component: () => withSuspense(MediaPage),
});

const newsRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/news",
  component: () => withSuspense(NewsListPage),
});

const newsNewRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/news/new",
  component: () => withSuspense(NewsNewPage),
});

const newsTrashRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/news/trash",
  component: () => withSuspense(NewsTrashPage),
});

const newsEditRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/news/$id",
  component: () => withSuspense(NewsEditPage),
});

const auditRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/audit",
  component: () => withSuspense(AuditPage),
});

const settingsRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/settings",
  component: () => withSuspense(SettingsOverviewPage),
});

const settingsLegacyRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/settings/legacy",
  component: () => withSuspense(SettingsLegacyPage),
});

const settingsBrandRoute = createRoute({ getParentRoute: () => authLayoutRoute, path: "/settings/brand", component: () => withSuspense(SiteBrandPage) });
const settingsSiteRedirectRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/settings/site",
  beforeLoad: () => { throw redirect({ to: "/settings/brand" }); },
});
const settingsAppearanceRoute = createRoute({ getParentRoute: () => authLayoutRoute, path: "/settings/appearance", component: () => withSuspense(SettingsAppearancePage) });
const settingsIntegrationsRoute = createRoute({ getParentRoute: () => authLayoutRoute, path: "/settings/integrations", component: () => withSuspense(SettingsIntegrationsPage) });
const settingsSecurityRoute = createRoute({ getParentRoute: () => authLayoutRoute, path: "/settings/security", component: () => withSuspense(SettingsSecurityPage) });
const settingsLocalizationRoute = createRoute({ getParentRoute: () => authLayoutRoute, path: "/settings/localization", component: () => withSuspense(SettingsLocalizationPage) });
const settingsAdvancedRoute = createRoute({ getParentRoute: () => authLayoutRoute, path: "/settings/advanced", component: () => withSuspense(SettingsAdvancedPage) });

const featuresRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/features",
  component: () => withSuspense(FeaturesPage),
});

const analyticsSettingsRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/analytics-settings",
  component: () => withSuspense(AnalyticsSettingsPage),
});

const widgetsRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/widgets",
  component: () => withSuspense(LegacyUnavailablePage),
});

const widgetEditorRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/widgets/$name",
  component: () => withSuspense(LegacyUnavailablePage),
});

const layoutRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/layout",
  component: () => withSuspense(LegacyUnavailablePage),
});

const widgetPreviewRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/widget-preview",
  component: () => withSuspense(LegacyUnavailablePage),
});

const widgetHealthRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/widget-health",
  component: () => withSuspense(LegacyUnavailablePage),
});

const pageBuilderIndexRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/page-builder",
  component: () => withSuspense(LegacyUnavailablePage),
});

const pageBuilderEditRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/page-builder/$pageId",
  component: () => withSuspense(LegacyUnavailablePage),
});

const publicationsAdminRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/publications",
  component: () => withSuspense(PublicationsAdminPage),
});

const tableTemplatesRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/table-templates",
  component: () => withSuspense(TableViewsPage),
});

const tableViewsRedirectRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/table-views",
  beforeLoad: () => { throw redirect({ to: "/table-templates" }); },
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  authLayoutRoute.addChildren([
    dashboardRoute,
    usageGuideRoute,
    releasesRoute,
    instancesRoute,
    previewTestDataRoute,
    resourceCatalogRoute,
    importsRoute,
    newImportRoute,
    importTaskDetailRoute,
    contentRoute,
    contentPagesRoute,
    contentPageDetailRoute,
    contentLegacyRoute,
    mediaRoute,
    newsRoute,
    newsNewRoute,
    newsTrashRoute,
    newsEditRoute,
    auditRoute,
    settingsRoute,
    settingsLegacyRoute,
    settingsBrandRoute,
    settingsSiteRedirectRoute,
    settingsAppearanceRoute,
    settingsIntegrationsRoute,
    settingsSecurityRoute,
    settingsLocalizationRoute,
    settingsAdvancedRoute,
    featuresRoute,
    analyticsSettingsRoute,
    widgetsRoute,
    widgetEditorRoute,
    layoutRoute,
    widgetPreviewRoute,
    widgetHealthRoute,
    pageBuilderIndexRoute,
    pageBuilderEditRoute,
    publicationsAdminRoute,
    tableTemplatesRoute,
    tableViewsRedirectRoute,
  ]),
]);

const router = createRouter({
  routeTree,
  basepath: import.meta.env.BASE_URL.replace(/\/$/, "") || "/",
  defaultPreload: "intent",
  // Keep intent-prefetched route chunks/data warm for one navigation window;
  // React Query uses the same 30s freshness budget in main.tsx.
  defaultPreloadStaleTime: 30_000,
});

// View Transitions API is the only route-change animation mechanism (admin).
if (typeof document !== "undefined" && typeof document.startViewTransition === "function") {
  const origLoad = router.load.bind(router);
  const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 4;
  let preference: MotionPreference = "auto";
  try {
    preference = parseMotionPreference(localStorage.getItem("soymutdb-animation-prefs"));
  } catch {
    // Storage can be unavailable in privacy modes; auto remains safe.
  }
  const skip = resolveMotionDecision(preference, {
    reduced: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true,
    saveData: connection?.saveData === true,
    lowResource:
      (navigator.hardwareConcurrency ?? 4) <= 4 ||
      memory <= 2 ||
      /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent),
  }).effective !== "standard";
  if (!skip) {
    router.load = (async (opts: Parameters<typeof origLoad>[0]) => {
      const vt = document.startViewTransition!(() => origLoad(opts));
      vt.ready.catch(() => {});
      return vt.finished;
    }) as typeof router.load;
  }
}

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

export default function App() {
  return <RouterProvider router={router} />;
}
