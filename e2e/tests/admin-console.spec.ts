/**
 * Admin console — authenticated route E2E for a DEPLOYED stack.
 *
 * Coverage
 * --------
 *   1. Anonymous deep link: a protected route (/imports) must bounce to
 *      /login with the original target in the `redirect` query, and the login
 *      form must be usable (identifier, password, submit).
 *   2. Authenticated rendering: / (dashboard), /imports, /settings, /news and
 *      /content must mount inside the console chrome, let their data query
 *      settle (loaded, empty or error state — all are valid render outcomes),
 *      and raise no unexpected console error or pageerror.
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
  /** Language-independent marker that is always present once the view mounts. */
  anchor: string;
  /** Marker that appears only after the view's data query settles. */
  settled: string;
}

/**
 * The protected routes this suite gates. Anchors are stable data-testids (or a
 * structural heading) rather than translated copy, so an i18n change cannot
 * turn a rendering regression into a false failure.
 */
const CONSOLE_ROUTES: readonly ConsoleRoute[] = [
  {
    path: "/",
    label: "dashboard",
    anchor: "main h1",
    settled: '[data-testid="dashboard-releases"], [data-testid="dashboard-error"]',
  },
  {
    path: "/imports",
    label: "imports",
    anchor: '[data-testid="imports-new"]',
    settled:
      '[data-testid="imports-error"], [data-testid="imports-empty"], [data-testid="imports-table"]',
  },
  {
    path: "/settings",
    label: "settings",
    anchor: '[data-testid="settings-brand-link"]',
    settled:
      '[data-testid="settings-error"], [data-testid="settings-section-missing"], [data-testid^="settings-section-"]',
  },
  {
    path: "/news",
    label: "news",
    anchor: '[data-testid="news-status-filter"]',
    settled: '[data-testid="news-error"], [data-testid="news-empty"], [data-testid="news-table"]',
  },
  {
    path: "/content",
    label: "content",
    anchor: '[data-testid="pages-status-filter"]',
    settled:
      '[data-testid="pages-error"], [data-testid="pages-empty"], [data-testid="pages-table"]',
  },
];

test.describe("admin console — anonymous deep link", () => {
  test("redirects a protected route to the login form with the original target", async ({
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

      await expect(page).toHaveURL(/\/login(\?|$)/);
      const redirectTarget = new URL(page.url()).searchParams.get("redirect");
      expect(redirectTarget).toBe("/imports");

      await expect(page.getByTestId("admin-identifier")).toBeVisible();
      await expect(page.getByTestId("admin-password")).toBeVisible();
      await expect(page.getByTestId("admin-login-submit")).toBeVisible();

      expect(
        errors,
        "the guard redirect must not raise unexpected console errors or pageerrors",
      ).toEqual([]);
    } finally {
      await context.close();
    }
  });
});

test.describe("admin console — authenticated routes", () => {
  for (const route of CONSOLE_ROUTES) {
    test(`${route.label} renders without console errors`, async ({ page }) => {
      test.skip(!ADMIN_BASE_URL, "set ADMIN_BASE_URL to the deployed admin console");
      test.skip(
        !STORAGE_STATE,
        "set ADMIN_STORAGE_STATE to a signed-in Playwright storage state",
      );

      const errors = trackErrors(page);
      await page.goto(underBase(ADMIN_BASE_URL, route.path), { waitUntil: "load" });
      await waitForAppReady(page);

      // A valid session must not be bounced back to the login form.
      expect(
        new URL(page.url()).pathname.endsWith("/login"),
        `${route.path} must render for a signed-in operator, not redirect to /login`,
      ).toBe(false);

      // Console chrome plus the route's own view, then its data query result.
      await expect(page.getByTestId("admin-sidebar")).toBeVisible();
      await expect(page.locator(route.anchor).first()).toBeVisible();
      await expect(page.locator(route.settled).first()).toBeVisible({ timeout: 20_000 });

      expect(
        errors,
        `${route.path} must render without unexpected console errors or pageerrors`,
      ).toEqual([]);
    });
  }
});
