/**
 * Root layout — Header + Outlet + Footer.
 */
import * as React from "react";
import { useTranslation } from "react-i18next";
import { Outlet, createRootRouteWithContext, useRouterState } from "@tanstack/react-router";
import type { QueryClient } from "@tanstack/react-query";
import { SiteHeader } from "../components/site-header";
import { SiteContentProvider } from "../lib/site-content-react";
import { SiteFooter } from "../components/site-footer";
import { ErrorBoundary } from "../components/error-boundary";
import { CommandPalette } from "../components/command-palette";
import { useAnimation } from "../lib/animation-context";
const RouteMotionRuntime = React.lazy(() => import("../components/route-motion-runtime"));

interface RouterContext {
  queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootComponent,
});

const STANDALONE_ROUTE_PREFIXES = ["/login"];

function isStandaloneRoute(pathname: string): boolean {
  return STANDALONE_ROUTE_PREFIXES.some((prefix) =>
    prefix === "/" ? pathname === "/" : pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

function RootComponent() {
  const { t } = useTranslation();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { intensity } = useAnimation();
  const standalone = isStandaloneRoute(pathname);
  const allowRouteMotion =
    intensity === "standard" &&
    (pathname === "/" || pathname === "/guide" || pathname.startsWith("/news"));

  if (standalone) {
    return (
      <SiteContentProvider>
        <ErrorBoundary>
          <a href="#main" className="skip-link">{t("a11y.skipToContent")}</a>
          <main id="main" className="flex-1">
            {allowRouteMotion ? <React.Suspense fallback={null}><RouteMotionRuntime /></React.Suspense> : null}
            <Outlet />
          </main>
        </ErrorBoundary>
      </SiteContentProvider>
    );
  }

  return (
    <SiteContentProvider>
      <ErrorBoundary>
        <a href="#main" className="skip-link">{t("a11y.skipToContent")}</a>
        <div className="flex min-h-screen flex-col">
          <SiteHeader />
          <main id="main" className="flex-1">
            {allowRouteMotion ? <React.Suspense fallback={null}><RouteMotionRuntime /></React.Suspense> : null}
            <Outlet />
          </main>
          <SiteFooter />
        </div>
        <CommandPalette />
      </ErrorBoundary>
    </SiteContentProvider>
  );
}
