/**
 * Admin console — authenticated route E2E for a DEPLOYED stack.
 *
 * Coverage
 * --------
 *   1. Anonymous deep link: a protected route (/imports) must render the login
 *      surface in place of the console chrome. The guard does NOT navigate to
 *      /login — `RequireAuth` (apps/admin/src/App.tsx) swaps the admin layout for
 *      `LoginPage`, so the requested path stays in the URL, the console chrome
 *      (`shell-header`) is absent, and the form (identifier, password, submit)
 *      is usable and cannot be bypassed with an empty submission.
 *   2. Authenticated rendering: / (dashboard), /imports, /settings,
 *      /settings/brand, /news and /content must mount inside the console chrome,
 *      let their data query settle (ready or error — both are valid render
 *      outcomes), expose their real controls, and raise no unexpected console
 *      error or pageerror.
 *
 * Anchor policy
 * -------------
 * Every selector below is a `data-testid` that the console renders today, or a
 * `data-state`/`data-pending` attribute the component owning that query publishes
 * when it settles. The console is Chinese-first (`initI18n("zh")` in
 * `apps/admin/src/react-app.tsx`), so no assertion here may depend on copy: an
 * i18n change must not be able to turn a rendering regression into a false pass
 * or a false failure.
 *
 * This is deliberately separate from `admin-production-login.spec.ts`: that
 * suite serves the emitted `apps/admin/dist` through a local static server and
 * stops at the login form, so it can prove the bundle boots but cannot reach a
 * protected route. Everything past /login needs a live API and a session.
 *
 * Prerequisites
 * -------------
 *   - A deployed admin console whose API/CORS/CSP are configured, reachable at
 *     ADMIN_BASE_URL.
 *   - A signed-in session for the authenticated routes, provided as a
 *     Playwright storage state at ADMIN_STORAGE_STATE. The console keeps its
 *     access token in memory and its refresh token in an HttpOnly cookie, so a
 *     storage state captured from a real login restores the session on load.
 *     Produce it out of band; this suite never reads or fabricates credentials:
 *
 *       npx playwright codegen --save-storage=admin-storage-state.json \
 *         "$ADMIN_BASE_URL/login"
 *       # sign in in the opened browser, then close it
 *
 * Env vars (both optional — the dependent tests SKIP when unset, they never
 * silently test the wrong environment):
 *   ADMIN_BASE_URL        e.g. https://admin.soymutdb.test/
 *   ADMIN_STORAGE_STATE   path to the signed-in storage state JSON
 *
 * Run (from e2e/):
 *   ADMIN_BASE_URL=https://admin.soymutdb.test/ \
 *   ADMIN_STORAGE_STATE=/secure/admin-storage-state.json \
 *     npx playwright test -c playwright-admin-console.config.ts
 *
 * Discover without running:
 *   ADMIN_BASE_URL=https://admin.soymutdb.test/ \
 *     npx playwright test -c playwright-admin-console.config.ts --list
 *
 * A real run requires the deployed stack; without it every test here skips.
 */
import { expect, test, type Page } from "@playwright/test";

import { waitForAppReady } from "./helpers";

/** Deployed admin console base, e.g. "https://admin.soymutdb.test/". */
const ADMIN_BASE_URL = (process.env.ADMIN_BASE_URL ?? "").trim();

/** Signed-in Playwright storage state; required only by the authenticated tests. */
const STORAGE_STATE = (process.env.ADMIN_STORAGE_STATE ?? "").trim();

/** Resolve a path under a base that may carry a sub-path prefix. */
function underBase(base: string, path = ""): string {
  const root = base.endsWith("/") ? base : `${base}/`;
  return new URL(path.replace(/^\//, ""), root).toString();
}

/**
 * Console errors that are environment/network noise rather than script bugs.
 * The admin API is cross-origin, so a failed call surfaces as a resource load
 * failure; the app handles it by rendering an error state. Any other
 * console.error (or any pageerror) is treated as a regression.
 */
const TOLERATED_CONSOLE_ERRORS: readonly RegExp[] = [
  /Failed to load resource/i,
  /net::ERR_/i,
  /ERR_ABORTED/i,
  /Failed to fetch/i,
  /NetworkError/i,
  /Load failed/i,
  /frame-ancestors/i,
];

/** Track pageerrors and non-tolerated console errors until the end of the test. */
function trackErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    if (TOLERATED_CONSOLE_ERRORS.some((pattern) => pattern.test(text))) return;
    errors.push(`console: ${text}`);
  });
  return errors;
}

interface ConsoleRoute {
  /** Router path, relative to the console base. */
  path: string;
  /** Short label for the test title. */
  label: string;
  /** Stable marker that is always present once the view mounts. */
  anchor: string;
  /**
   * Marker that appears only once the view's data query settled. A settled
   * query has one of two honest outcomes, and both are asserted: ready (rows,
   * cards or the route's own empty state) and error (the API refused). A route
   * that publishes no async state repeats its mount marker and says so.
   */
  settled: string;
  /** Further real controls the view must render (its own toolbar). */
  controls?: readonly string[];
  /**
   * Error surface plus its retry control, asserted only when the deployed API
   * actually failed: a route whose error is a silent empty list has no such
   * contract and omits this.
   */
  errorContract?: { error: string; retry: string };
}

/**
 * The protected routes this suite gates. Every anchor is a `data-testid` (or an
 * attribute the owning component publishes when its query settles) rather than
 * translated copy, so an i18n change cannot turn a rendering regression into a
 * false failure.
 */
const CONSOLE_ROUTES: readonly ConsoleRoute[] = [
  {
    // Dashboard reads GET /admin/dashboard-stats plus the public homepage stats
    // for its cards, and GET /admin/dashboard-series for the charts. The cards
    // publish `data-pending` until both metric queries settle; a failed metric
    // query still settles (the cards fall back to the "—" placeholder) and is
    // announced by `dashboard-stats-error` with a retry control.
    path: "/",
    label: "dashboard",
    anchor: '[data-testid="dashboard-stats"]',
    settled: '[data-testid="dashboard-stats"][data-pending="false"]',
    controls: ['[data-testid="dashboard-trends"]'],
    errorContract: {
      error: '[data-testid="dashboard-stats-error"]',
      retry: '[data-testid="dashboard-stats-retry"]',
    },
  },
  {
    // /imports lists GET /admin/imports and offers the new-import action plus
    // the task search box. The list wrapper publishes `data-state`.
    path: "/imports",
    label: "imports",
    anchor: '[data-testid="imports-new"]',
    settled:
      '[data-testid="imports-table"][data-state="ready"], [data-testid="imports-table"][data-state="error"]',
    controls: ['[data-testid="imports-search"]'],
  },
  {
    // /settings is the settings navigation hub: it issues no data query, so the
    // domain grid is both its mount marker and its settled marker.
    path: "/settings",
    label: "settings overview",
    anchor: '[data-testid="settings-domains"]',
    settled: '[data-testid="settings-domains"]',
  },
  {
    // /settings/brand is the one settings surface with an explicit
    // loading/error/ready state machine already marked for tests
    // (brand-loading → brand-form | brand-load-error).
    path: "/settings/brand",
    label: "settings brand",
    anchor: '[data-testid="brand-variant-external"]',
    settled: '[data-testid="brand-form"], [data-testid="brand-load-error"]',
    controls: ['[data-testid="brand-variant-internal"]'],
    errorContract: {
      error: '[data-testid="brand-load-error"]',
      retry: '[data-testid="brand-retry"]',
    },
  },
  {
    // /news lists GET /admin/news with a title search, a category box and the
    // status filter; a failed list is surfaced as a toast and an empty table, so
    // its settled state is the table's own readiness.
    path: "/news",
    label: "news",
    anchor: '[data-testid="news-new"]',
    settled: '[data-testid="news-table"][data-state="ready"]',
    controls: [
      '[data-testid="news-status-filter"]',
      '[data-testid="news-search"]',
    ],
  },
  {
    // /content defaults to its Pages tab, which lists GET /admin/content/pages
    // behind a status filter and a category filter, next to the New Page action.
    path: "/content",
    label: "content pages",
    anchor: '[data-testid="content-tabs"]',
    settled:
      '[data-testid="pages-table"][data-state="ready"], [data-testid="pages-table"][data-state="error"]',
    controls: [
      '[data-testid="content-tab-page"]',
      '[data-testid="pages-status-filter"]',
      '[data-testid="pages-new"]',
    ],
  },
];

/** Skip a test unless both the deployed console and a signed-in session exist. */
function skipWithoutDeployment(): void {
  test.skip(!ADMIN_BASE_URL, "set ADMIN_BASE_URL to the deployed admin console");
  test.skip(
    !STORAGE_STATE,
    "set ADMIN_STORAGE_STATE to a signed-in Playwright storage state",
  );
}

test.describe("admin console — anonymous deep link", () => {
  test("gates a protected route with the login surface and keeps the console chrome hidden", async ({
    browser,
  }) => {
    test.skip(!ADMIN_BASE_URL, "set ADMIN_BASE_URL to the deployed admin console");

    // A fresh context is required: the suite's default context is signed in
    // when ADMIN_STORAGE_STATE is set, and this test asserts the guard's
    // anonymous behaviour.
    const context = await browser.newContext({ locale: "en-US" });
    const page = await context.newPage();
    const errors = trackErrors(page);
    try {
      await page.goto(underBase(ADMIN_BASE_URL, "imports"), { waitUntil: "load" });
      await waitForAppReady(page);

      // The guard renders the login form in place of the admin layout, so the
      // requested path is preserved rather than rewritten to /login.
      await expect(page.getByTestId("admin-identifier")).toBeVisible();
      await expect(page.getByTestId("admin-password")).toBeVisible();
      await expect(page.getByTestId("admin-login-submit")).toBeVisible();
      expect(new URL(page.url()).pathname).toContain("/imports");

      // No protected data may leak through the unauthenticated guard.
      await expect(page.getByTestId("shell-header")).toHaveCount(0);

      // An empty submission is refused client-side: the guard cannot be walked
      // past, and the console does not navigate away from the guarded path.
      await page.getByTestId("admin-login-submit").click();
      await expect(page.getByTestId("admin-identifier")).toBeVisible();
      expect(new URL(page.url()).pathname).toContain("/imports");

      expect(
        errors,
        "the guard must not raise unexpected console errors or pageerrors",
      ).toEqual([]);
    } finally {
      await context.close();
    }
  });
});

test.describe("admin console — authenticated routes", () => {
  for (const route of CONSOLE_ROUTES) {
    test(`${route.label} renders without console errors`, async ({ page }) => {
      skipWithoutDeployment();

      const errors = trackErrors(page);
      await page.goto(underBase(ADMIN_BASE_URL, route.path), { waitUntil: "load" });
      await waitForAppReady(page);

      // A valid session must not be bounced back to the login form.
      expect(
        new URL(page.url()).pathname.endsWith("/login"),
        `${route.path} must render for a signed-in operator, not redirect to /login`,
      ).toBe(false);

      // Console chrome plus the route's own view, then its data query result.
      await expect(page.getByTestId("shell-header")).toBeVisible();
      await expect(page.locator(route.anchor).first()).toBeVisible();
      await expect(page.locator(route.settled).first()).toBeVisible({ timeout: 20_000 });
      for (const control of route.controls ?? []) {
        await expect(
          page.locator(control).first(),
          `${route.path} must render its own controls`,
        ).toBeVisible();
      }

      // Once the query has settled its outcome is final: a refused API must say
      // so, and must offer the retry the view itself renders.
      if (route.errorContract) {
        const failed = await page
          .locator(route.errorContract.error)
          .first()
          .isVisible();
        if (failed) {
          await expect(
            page.locator(route.errorContract.retry).first(),
            `${route.path} must offer a retry when its API failed`,
          ).toBeVisible();
        }
      }

      expect(
        errors,
        `${route.path} must render without unexpected console errors or pageerrors`,
      ).toEqual([]);
    });
  }
});
