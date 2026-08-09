import { lazy, Suspense } from "react";
import {
  createRouter,
  createRootRoute,
  createRoute,
  RouterProvider,
  Outlet,
} from "@tanstack/react-router";
import { Skeleton } from "@soymutdb/ui";
import AdminLayout from "./routes/__root";
import LoginPage from "./routes/login";
import { useAuth } from "./lib/auth-context";

// Lazy-loaded route components (code-splitting per route).
const DashboardPage = lazy(() => import("./routes/index"));
const UsersPage = lazy(() => import("./routes/users"));
const ReleasesPage = lazy(() => import("./routes/releases"));
const ImportsPage = lazy(() => import("./routes/imports"));
const AssembliesPage = lazy(() => import("./routes/assemblies"));
const VariantsPage = lazy(() => import("./routes/variants"));
const TracksPage = lazy(() => import("./routes/tracks"));
const BlastPage = lazy(() => import("./routes/blast"));
const SeedsPage = lazy(() => import("./routes/seeds"));
const ContentPage = lazy(() => import("./routes/content"));
const NewsListPage = lazy(() => import("./routes/news/index"));
const NewsNewPage = lazy(() => import("./routes/news/new"));
const NewsEditPage = lazy(() => import("./routes/news/$id"));
const AuditPage = lazy(() => import("./routes/audit"));
const SettingsPage = lazy(() => import("./routes/settings"));
const WidgetsPage = lazy(() => import("./routes/widgets"));
const WidgetEditorPage = lazy(() => import("./routes/widgets/$name"));
const LayoutEditorPage = lazy(() => import("./routes/layout"));
const WidgetPreviewPage = lazy(() => import("./routes/widget-preview"));
const WidgetHealthPage = lazy(() => import("./routes/widget-health"));

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
    <Suspense fallback={<RouteLoading />}>
      <Component />
    </Suspense>
  );
}

// --- Route tree (manual, no code generation required) -----------------

/**
 * Root shell: renders whichever child matched (the public `/login` route or
 * the auth-guarded admin layout). No chrome here so `/login` can render
 * standalone, outside the AdminLayout.
 */
const rootRoute = createRootRoute({
  component: () => <Outlet />,
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
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) {
    return <LoginPage />;
  }
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

const usersRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/users",
  component: () => withSuspense(UsersPage),
});

const releasesRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/releases",
  component: () => withSuspense(ReleasesPage),
});

const importsRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/imports",
  component: () => withSuspense(ImportsPage),
});

const assembliesRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/assemblies",
  component: () => withSuspense(AssembliesPage),
});

const variantsRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/variants",
  component: () => withSuspense(VariantsPage),
});

const tracksRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/tracks",
  component: () => withSuspense(TracksPage),
});

const blastRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/blast",
  component: () => withSuspense(BlastPage),
});

const seedsRoute = createRoute({
  getParentRoute: () => authLayoutRoute,
  path: "/seeds",
  component: () => withSuspense(SeedsPage),
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

const routeTree = rootRoute.addChildren([
  loginRoute,
  authLayoutRoute.addChildren([
    dashboardRoute,
    usersRoute,
    releasesRoute,
    importsRoute,
    assembliesRoute,
    variantsRoute,
    tracksRoute,
    blastRoute,
    seedsRoute,
    contentRoute,
    newsRoute,
    newsNewRoute,
    newsEditRoute,
    auditRoute,
    settingsRoute,
    widgetsRoute,
    widgetEditorRoute,
    layoutRoute,
    widgetPreviewRoute,
    widgetHealthRoute,
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
  const skip =
    (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) ||
    (navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData;
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
