import { lazy, Suspense } from "react";
import {
  createRouter,
  createRootRoute,
  createRoute,
  RouterProvider,
  Outlet,
} from "@tanstack/react-router";
import { Skeleton } from "@/lib/antd";
import { ErrorBoundary } from "./components/error-boundary";
import { RouteErrorBoundary } from "./components/route-error-boundary";
import AdminLayout from "./routes/__root";
import LoginPage from "./routes/login";
import { useAuth } from "./lib/auth-context";
import {
  parseMotionPreference,
  resolveMotionDecision,
  type MotionPreference,
} from "./lib/motion-policy";

// Lazy-loaded route components (code-splitting per route).
const DashboardPage = lazy(() => import("./routes/index"));
const ResourceCatalogPage = lazy(() => import("./routes/resource-catalog"));
const ImportsPage = lazy(() => import("./routes/imports"));
const ContentPage = lazy(() => import("./routes/content"));
const NewsListPage = lazy(() => import("./routes/news/index"));
const NewsNewPage = lazy(() => import("./routes/news/new"));
const NewsEditPage = lazy(() => import("./routes/news/$id"));
const AuditPage = lazy(() => import("./routes/audit"));
const SettingsPage = lazy(() => import("./routes/settings"));
const FeaturesPage = lazy(() => import("./routes/features"));
const AnalyticsSettingsPage = lazy(() => import("./routes/analytics-settings"));
const WidgetsPage = lazy(() => import("./routes/widgets"));
const WidgetEditorPage = lazy(() => import("./routes/widgets/$name"));
const LayoutEditorPage = lazy(() => import("./routes/layout"));
const WidgetPreviewPage = lazy(() => import("./routes/widget-preview"));
const WidgetHealthPage = lazy(() => import("./routes/widget-health"));
const PageBuilderIndexPage = lazy(() => import("./routes/page-builder/index"));
const PageBuilderEditPage = lazy(() => import("./routes/page-builder/$pageId"));

/** Loading fallback for lazy-loaded routes. */
function RouteLoading() {
  return (
    <div className="route-fade-in space-y-4 p-6" role="status" aria-live="polite">
      <Skeleton className="h-8 w-48" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-28 w-full rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-96 w-full rounded-xl" />
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

/** Auth guard + admin chrome wrapper.
 * TEMP (layout preview): bypass login so the admin chrome renders directly.
 * Remove this bypass before production. */
function RequireAuth() {
  // const { isAuthenticated } = useAuth();
  // if (!isAuthenticated) return <LoginPage />;
  return (
    <AdminLayout>
      <Outlet />
    </AdminLayout>
  );
}

const dashboardRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/",
  component: () => withSuspense(DashboardPage),
});

const resourceCatalogRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/resource-catalog",
  component: () => withSuspense(ResourceCatalogPage),
});

const importsRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/imports",
  component: () => withSuspense(ImportsPage),
});

const contentRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/content",
  component: () => withSuspense(ContentPage),
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
  component: () => withSuspense(SettingsPage),
});

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
  component: () => withSuspense(WidgetsPage),
});

const widgetEditorRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/widgets/$name",
  component: () => withSuspense(WidgetEditorPage),
});

const layoutRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/layout",
  component: () => withSuspense(LayoutEditorPage),
});

const widgetPreviewRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/widget-preview",
  component: () => withSuspense(WidgetPreviewPage),
});

const widgetHealthRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/widget-health",
  component: () => withSuspense(WidgetHealthPage),
});

const pageBuilderIndexRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/page-builder",
  component: () => withSuspense(PageBuilderIndexPage),
});

const pageBuilderEditRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/page-builder/$pageId",
  component: () => withSuspense(PageBuilderEditPage),
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  authLayoutRoute.addChildren([
    dashboardRoute,
    resourceCatalogRoute,
    importsRoute,
    contentRoute,
    newsRoute,
    newsNewRoute,
    newsEditRoute,
    auditRoute,
    settingsRoute,
    featuresRoute,
    analyticsSettingsRoute,
    widgetsRoute,
    widgetEditorRoute,
    layoutRoute,
    widgetPreviewRoute,
    widgetHealthRoute,
    pageBuilderIndexRoute,
    pageBuilderEditRoute,
  ]),
]);

const router = createRouter({
  routeTree,
  defaultPreload: "intent",
  defaultPreloadStaleTime: 0,
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
