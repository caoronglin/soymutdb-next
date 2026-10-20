/**
 * Genome-browser artifact gate (offline).
 *
 * The app needs a deployed release API for a live view, so this gate pins the
 * contract that must hold without one: the emitted shell boots, the degraded
 * "unable to load" surface renders instead of a crash, and the split HarmonyOS
 * faces declared in the CSS are served by the artifact (not 404, not the
 * retired full-file names).
 */
import { expect, test } from "@playwright/test";

import { mockJbrowseApis } from "./helpers";

interface FontResponse {
  url: string;
  status: number;
  contentType: string;
}

test("the built genome browser boots, degrades honestly and serves its split fonts", async ({
  page,
}) => {
  const pageErrors: string[] = [];
  const fonts: FontResponse[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("response", (response) => {
    const url = response.url();
    if (!url.includes("/fonts/harmonyos/")) return;
    fonts.push({
      url,
      status: response.status(),
      contentType: response.headers()["content-type"] ?? "",
    });
  });

  await page.goto("/", { waitUntil: "load" });

  // React handoff: the shell, not the inert Umi document.
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.appReady ?? null), {
      message: "the genome browser never announced readiness (<html data-app-ready>)",
      timeout: 20_000,
    })
    .toBe("true");

  // No API here: the honest outcome is the "unable to load" alert, never a
  // blank page or an unhandled error.
  const unavailable = page.getByTestId("jbrowse-unavailable");
  const view = page.getByTestId("jbrowse-view");
  await expect
    .poll(async () => (await unavailable.count()) > 0 || (await view.count()) > 0, {
      message: "neither the genome view nor its degraded state rendered",
      timeout: 20_000,
    })
    .toBe(true);

  // The CSS declares the split faces; the artifact must serve them once each.
  await expect
    .poll(() => fonts.length, { message: "no HarmonyOS font was requested", timeout: 10_000 })
    .toBeGreaterThan(0);
  for (const font of fonts) {
    expect(font.status, `${font.url} must be served by the artifact`).toBe(200);
    expect(font.contentType, `${font.url} content-type`).toContain("font/woff2");
    expect(font.url, `${font.url} must be a split face`).toMatch(
      /HarmonyOS-Sans-SC-(Regular|Medium|Bold)-(latin|cjk)\.woff2$/,
    );
  }
  expect(
    fonts.some((font) => font.url.endsWith("-latin.woff2")),
    "the latin face must load for the English UI text",
  ).toBe(true);

  expect(
    pageErrors,
    "the emitted genome-browser artifact must not throw while booting",
  ).toEqual([]);
});


test("renders the linear genome view from a release config with an inline reference", async ({
  page,
}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await mockJbrowseApis(page);

  await page.goto("/", { waitUntil: "load" });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.appReady ?? null), {
      message: "the genome browser never announced readiness",
      timeout: 20_000,
    })
    .toBe("true");

  // `data-view-ready` is set only after createViewState() succeeded; a degraded
  // state renders `jbrowse-unavailable` inside the same container instead.
  const view = page.locator('[data-testid="jbrowse-view"][data-view-ready="true"]');
  await expect(view).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("jbrowse-unavailable")).toHaveCount(0);

  // The mock assembly is the one the view reports in its summary bar.
  await expect(page.getByText(/Wm82\.a4\.v1/).first()).toBeVisible();
  expect(pageErrors, "the linear genome view must mount without pageerrors").toEqual([]);
});
