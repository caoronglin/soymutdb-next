/**
 * Public login production-artifact gate.
 *
 * The web app is built before this suite runs and is served through
 * e2e/static-server.mjs at the same subpath used by Pages. The mock only
 * supplies deterministic auth responses so these tests exercise real browser
 * fetch, JSON serialization, response handling, and router navigation.
 */
import { expect, test, type Page, type Request } from "@playwright/test";
import { waitForAppReady } from "./helpers";

const BASE = "/soymutdb-next";
const LOGIN_ENDPOINT = "/api/v1/auth/login";

const VALID_CREDENTIALS = {
  email: "researcher@example.org",
  password: "correct-horse-battery-staple",
};

const INVALID_CREDENTIALS = {
  email: "researcher@example.org",
  password: "not-the-test-password",
};

function isLoginRequest(request: Request): boolean {
  return new URL(request.url()).pathname.endsWith(LOGIN_ENDPOINT);
}

function collectPageErrors(page: Page): string[] {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  return pageErrors;
}

async function openLogin(page: Page, redirect = "/analyses"): Promise<void> {
  await page.goto(`${BASE}/login?redirect=${encodeURIComponent(redirect)}`, {
    waitUntil: "load",
  });
  // The static fallback is inert: wait for the SPA to own the document before
  // interacting, otherwise a click is silently discarded and no request fires.
  await waitForAppReady(page);
  await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
  await expect(page.getByLabel(/^email$/i)).toBeVisible();
  await expect(page.getByLabel(/^password$/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
}

async function submitLogin(
  page: Page,
  credentials: { email: string; password: string },
): Promise<{ request: Request; status: number }> {
  const requestPromise = page.waitForRequest(isLoginRequest);
  const responsePromise = page.waitForResponse((response) =>
    response.request().method() === "POST" && isLoginRequest(response.request()),
  );

  await page.getByLabel(/^email$/i).fill(credentials.email);
  await page.getByLabel(/^password$/i).fill(credentials.password);
  await page.getByRole("button", { name: /sign in/i }).click();

  const [request, response] = await Promise.all([requestPromise, responsePromise]);
  expect(new URL(request.url()).pathname).toBe(`${BASE}${LOGIN_ENDPOINT}`);
  expect(request.method()).toBe("POST");
  expect(request.headers()["content-type"]).toContain("application/json");
  expect(request.postDataJSON()).toEqual(credentials);

  return { request, status: response.status() };
}

async function expectHealthyLoginSurface(page: Page, pageErrors: string[]): Promise<void> {
  expect(pageErrors, "the emitted public artifact must not throw while handling login").toEqual([]);
  await expect(
    page.locator(
      "vite-error-overlay, #webpack-dev-server-client-overlay, [data-nextjs-dialog-overlay], [data-nextjs-toast-errors-parent]",
    ),
  ).toHaveCount(0);
  await expect(page.getByText("Unexpected Application Error", { exact: false })).toHaveCount(0);
}

test.describe("public production artifact — login", () => {
  test("POSTs JSON and keeps a generic, healthy 401 error state on desktop", async ({ page }) => {
    const pageErrors = collectPageErrors(page);
    await openLogin(page);

    const { status } = await submitLogin(page, INVALID_CREDENTIALS);

    expect(status).toBe(401);
    const alert = page.getByRole("alert");
    await expect(alert).toHaveText("Invalid email or password.");
    await expect(alert).not.toContainText("Mock authentication detail");
    await expectHealthyLoginSurface(page, pageErrors);
  });

  test("redirects a successful login to the safe internal analyses route", async ({ page }) => {
    const pageErrors = collectPageErrors(page);
    await openLogin(page, "/analyses");

    const { status } = await submitLogin(page, VALID_CREDENTIALS);

    expect(status).toBe(200);
    await expect(page).toHaveURL(/\/soymutdb-next\/analyses$/);
    await expectHealthyLoginSurface(page, pageErrors);
  });

  test("keeps the complete form visible at a narrow viewport", async ({ page }) => {
    const pageErrors = collectPageErrors(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await openLogin(page);

    await expectHealthyLoginSurface(page, pageErrors);
  });
});
