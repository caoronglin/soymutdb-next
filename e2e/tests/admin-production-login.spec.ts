/**
 * Admin production-artifact gate.
 *
 * Serves the built `apps/admin/dist` through `admin-static-server.mjs` — the
 * emitted files, exactly as a static host would deliver them — and asserts that
 * the console boots, renders its sign-in form and raises no runtime error.
 *
 * Locale note: `apps/admin/src/react-app.tsx` initialises i18n with `"zh"` (the
 * operator console is Chinese-first), so the assertions here are deliberately
 * locale-independent — stable `data-testid`s plus the app-ready handoff, not
 * English copy. The suite previously asserted English headings and drifted red
 * without anyone noticing; it must test the artifact, not a language default.
 *
 * The console has no public surface: this suite deliberately stops at the login
 * form. Everything past it needs administrator credentials, and a test that
 * fabricates them would be testing a mock auth path rather than the artifact.
 */
import { expect, test } from "@playwright/test";

async function waitForAppReady(page: import("@playwright/test").Page): Promise<void> {
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.appReady ?? null), {
      message: "the admin SPA never announced readiness (<html data-app-ready>)",
      timeout: 15_000,
    })
    .toBe("true");
}

test.describe("admin production artifact — login", () => {
  test("boots the console and renders the sign-in form", async ({ page }) => {
    const pageErrors: Error[] = [];
    page.on("pageerror", (error) => pageErrors.push(error));

    await page.goto("/login", { waitUntil: "load" });

    await expect(page.getByTestId("admin-identifier")).toBeVisible();
    await expect(page.getByTestId("admin-password")).toBeVisible();
    await expect(page.getByTestId("admin-login-submit")).toBeVisible();

    // The SPA announced its handoff, so what is on screen is the app and not the
    // inert document it was prerendered from.
    await waitForAppReady(page);

    expect(
      pageErrors.map((error) => error.message),
      "the emitted admin artifact must not throw while loading /login",
    ).toEqual([]);
  });

  test("keeps the form usable at a narrow viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/login", { waitUntil: "load" });
    await waitForAppReady(page);

    await expect(page.getByTestId("admin-identifier")).toBeVisible();
    await expect(page.getByTestId("admin-login-submit")).toBeVisible();

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test("rejects a submission with no credentials without leaving the page", async ({ page }) => {
    await page.goto("/login", { waitUntil: "load" });
    await waitForAppReady(page);
    await page.getByTestId("admin-login-submit").click();

    // The API rejects it (the static server has no backend), and the console
    // stays on the form with a generic message rather than navigating away.
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByTestId("admin-identifier")).toBeVisible();
  });

  test("serves the split HarmonyOS faces and preloads only the latin one", async ({ page }) => {
    const fontResponses: { url: string; status: number; contentType: string }[] = [];
    page.on("response", (response) => {
      const url = response.url();
      if (!url.includes("/fonts/harmonyos/")) return;
      fontResponses.push({
        url,
        status: response.status(),
        contentType: response.headers()["content-type"] ?? "",
      });
    });

    await page.goto("/login", { waitUntil: "load" });
    await waitForAppReady(page);
    // CJK text in the zh UI may fetch the cjk face lazily; give the font
    // requests a moment to settle after the first commit.
    await expect
      .poll(() => fontResponses.length, { message: "no HarmonyOS font was requested", timeout: 10_000 })
      .toBeGreaterThan(0);

    const preload = page.locator('link[rel="preload"][as="font"]');
    await expect(preload).toHaveCount(1);
    const preloadHref = await preload.getAttribute("href");
    expect(preloadHref, "the font preload must target the small latin face").toMatch(
      /HarmonyOS-Sans-SC-Regular-latin\.woff2$/,
    );

    for (const font of fontResponses) {
      expect(font.status, `${font.url} must be served by the artifact`).toBe(200);
      expect(font.contentType, `${font.url} content-type`).toContain("font/woff2");
      // The unsuffixed single-file names are the retired 900 KB world; a build
      // that emits them again has lost the latin/CJK split.
      expect(font.url, `${font.url} must be a split face`).toMatch(
        /HarmonyOS-Sans-SC-(Regular|Medium|Bold)-(latin|cjk)\.woff2$/,
      );
    }
    expect(
      fontResponses.some((font) => font.url.endsWith("-latin.woff2")),
      "the latin face must load for the latin UI text",
    ).toBe(true);
  });
});
