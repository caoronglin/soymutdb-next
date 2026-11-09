/**
 * Authenticated admin-shell artifact gate (offline).
 *
 * The console has no public surface beyond login, so the deployed E2E suite
 * needs credentials + a storage state and therefore never runs in this
 * repository's CI. This gate signs in through the real form against the static
 * server's mocked auth endpoint (`e2e/static-server.mjs`) and proves the
 * authenticated chrome mounts: the failure this catches is a shell that cannot
 * bootstrap after a successful login (the exact class of rot that left the old
 * admin-console spec permanently red).
 */
import { test, expect, type Page } from "@playwright/test";

// The static server's documented local test principal (not a real account).
const TEST_IDENTIFIER = "researcher@example.org";
const TEST_PASSWORD = "correct-horse-battery-staple";

test("signs in through the form and mounts the authenticated admin shell", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.goto("/login", { waitUntil: "load" });

  // React handoff before interacting; the login form is prerendered markup.
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.appReady ?? null), {
      message: "the admin SPA never announced readiness (<html data-app-ready>)",
      timeout: 20_000,
    })
    .toBe("true");

  await page.getByTestId("admin-identifier").fill(TEST_IDENTIFIER);
  await page.getByTestId("admin-password").fill(TEST_PASSWORD);
  await page.getByTestId("admin-login-submit").click();

  // The authenticated shell: header/sidebar chrome replaces the login route.
  const header = page.getByTestId("shell-header");
  await expect(header).toBeVisible({ timeout: 20_000 });
  expect(
    new URL(page.url()).pathname.endsWith("/login"),
    "a successful sign-in must leave the login route",
  ).toBe(false);

  // Dashboard data endpoints are not mocked; the shell must still survive the
  // failed queries and keep its chrome (honest degraded state, not a crash).
  await expect(page.locator("main").first()).toBeVisible();

  expect(pageErrors, "the admin shell must not throw after sign-in").toEqual([]);
});


/**
 * Every top-level console route must at least mount the authenticated shell.
 *
 * The admin suite has no data fixtures, so the data endpoints below return a
 * JSON 404: pages are expected to render their honest error/empty states, not
 * crash or bounce back to login. This is the cheapest catch for the rot that
 * previously left whole console sections unreachable after a refactor.
 */
const ADMIN_ROUTES = [
  // Registered paths from apps/admin/src/App.tsx (route tree is manual, so a
  // renamed file without a route update shows up as "Not Found").
  "/",
  "/releases",
  "/publications",
  "/imports",
  "/content",
  "/content/pages",
  "/news",
  "/media",
  "/audit",
  "/settings",
  "/settings/brand",
  "/settings/security",
  "/instances",
  "/features",
  "/analytics-settings",
  "/table-views",
  "/table-templates",
  "/guide",
  "/preview-test-data",
  "/resource-catalog",
  "/site-control",
  "/page-builder",
  "/widgets",
  "/widget-health",
];

async function stubAdminApi(page: Page): Promise<void> {
  await page.route(/\/api\/v1\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const origin = request.headers()["origin"];
    const headers: Record<string, string> = {
      "access-control-allow-origin": origin ?? "*",
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "authorization,content-type,x-soymutdb-release,x-csrf-token",
      "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
      vary: "Origin",
    };
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", headers, body: JSON.stringify(body) });
    const path = url.pathname;
    if (path.endsWith("/auth/login")) return json({ access_token: "e2e-access-token", expires_in: 900 });
    if (path.endsWith("/auth/refresh")) return json({ access_token: "e2e-access-token", expires_in: 900 });
    if (path.endsWith("/auth/me")) return json({ username: TEST_IDENTIFIER, email: TEST_IDENTIFIER });
    // No console fixtures: honest 404 so every page renders its error/empty state.
    return json({}, 404);
  });
}

test("every console route mounts the authenticated shell without crashing", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await stubAdminApi(page);

  // The stored refresh cookie is absent, so the console restores a session via
  // the stubbed /auth/refresh endpoint and mounts authenticated (the login form
  // itself is covered by the previous test).
  await page.goto("/", { waitUntil: "load" });
  await expect(page.getByTestId("shell-header")).toBeVisible({ timeout: 20_000 });

  for (const route of ADMIN_ROUTES) {
    await test.step(`route ${route}`, async () => {
      await page.goto(route, { waitUntil: "load" });
      await expect(page.getByTestId("shell-header")).toBeVisible({ timeout: 20_000 });
      expect(
        new URL(page.url()).pathname,
        `${route}: the authenticated shell must not bounce to login`,
      ).not.toBe("/login");
    });
  }

  expect(pageErrors, "no console route may throw while rendering its data").toEqual([]);
});
