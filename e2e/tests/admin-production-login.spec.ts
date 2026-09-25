/**
 * Admin production-artifact gate.
 *
 * Serves the built `apps/admin/dist` through `admin-static-server.mjs` — the
 * emitted files, exactly as a static host would deliver them — and asserts that
 * the console boots, renders its sign-in form and raises no runtime error.
 *
 * The console has no public surface: this suite deliberately stops at the login
 * form. Everything past it needs administrator credentials, and a test that
 * fabricates them would be testing a mock auth path rather than the artifact.
 */
import { expect, test } from "@playwright/test";

test.describe("admin production artifact — login", () => {
  test("boots the console and renders the sign-in form", async ({ page }) => {
    const pageErrors: Error[] = [];
    page.on("pageerror", (error) => pageErrors.push(error));

    await page.goto("/login", { waitUntil: "load" });

    await expect(page.getByRole("heading", { name: /admin/i })).toBeVisible();
    await expect(page.getByTestId("admin-identifier")).toBeVisible();
    await expect(page.getByTestId("admin-password")).toBeVisible();
    await expect(page.getByTestId("admin-login-submit")).toBeVisible();

    // The SPA announced its handoff, so what is on screen is the app and not the
    // inert document it was prerendered from.
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.appReady ?? null))
      .toBe("true");

    expect(
      pageErrors.map((error) => error.message),
      "the emitted admin artifact must not throw while loading /login",
    ).toEqual([]);
  });

  test("keeps the form usable at a narrow viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/login", { waitUntil: "load" });

    await expect(page.getByTestId("admin-identifier")).toBeVisible();
    await expect(page.getByTestId("admin-login-submit")).toBeVisible();

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test("rejects a submission with no credentials without leaving the page", async ({ page }) => {
    await page.goto("/login", { waitUntil: "load" });
    await page.getByTestId("admin-login-submit").click();

    // The API rejects it (the static server has no backend), and the console
    // stays on the form with a generic message rather than navigating away.
    await expect(page).toHaveURL(/\/login/);
  });
});
