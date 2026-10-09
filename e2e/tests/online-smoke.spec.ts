import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";

// Online smoke checks deployed artifacts. Local preview API fixtures belong to
// local-preview.spec.ts and are NEVER prerequisites for this test suite.
const routes = [
  "",
  "search",
  "genes",
  "variants",
  "blast",
  "news",
  "browser",
  "about",
  "help",
  "tools",
] as const;

type RouteEvidence = {
  route: string;
  url: string;
  status: number;
  title: string;
  bodyLength: number;
  assetFailures: string[];
  pageErrors: string[];
  consoleErrors: string[];
  toleratedDemoConsoleErrors: string[];
};
const report: RouteEvidence[] = [];
// Demo has deliberately missing external API/JBrowse targets. Do not classify
// such network messages as frontend JS errors; never tolerate a failed same-
// origin JS/CSS load, even if its console message also matches this pattern.
const demoNetworkNoise =
  /404|net::ERR_|Failed to load resource|Failed to fetch|NetworkError|ERR_ABORTED|frame-ancestors|EventSource|Content Security Policy|CSP violation/i;

test.afterAll(() => {
  mkdirSync("test-results", { recursive: true });
  writeFileSync(
    join("test-results", "smoke-report.json"),
    JSON.stringify({ routes: report }, null, 2) + "\n",
    "utf8",
  );
});

for (const route of routes) {
  test("deployed demo renders /" + route + " with healthy assets", async ({ page, baseURL }) => {
    if (!baseURL) throw new Error("Online smoke requires a baseURL");
    const origin = new URL(baseURL).origin;
    const assetFailures: string[] = [];
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];
    const toleratedDemoConsoleErrors: string[] = [];

    page.on("response", (response) => {
      const resourceType = response.request().resourceType();
      if (
        (resourceType === "script" || resourceType === "stylesheet") &&
        new URL(response.url()).origin === origin &&
        response.status() >= 400
      ) {
        assetFailures.push(String(response.status()) + " " + response.url());
      }
    });
    page.on("requestfailed", (request) => {
      const resourceType = request.resourceType();
      if (
        (resourceType === "script" || resourceType === "stylesheet") &&
        new URL(request.url()).origin === origin
      ) {
        assetFailures.push((request.failure()?.errorText ?? "request failed") + " " + request.url());
      }
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      if (demoNetworkNoise.test(message.text())) {
        toleratedDemoConsoleErrors.push(message.text());
      } else {
        consoleErrors.push(message.text());
      }
    });

    // "./" retains the /soymutdb-next/ prefix in Playwright's baseURL.
    // Absolute "/genes" would silently navigate to the domain root.
    const navigation = await page.goto(route ? "./" + route : "./", {
      waitUntil: "domcontentloaded",
    });
    const status = navigation?.status() ?? 0;
    await expect(page.locator("main").first()).toBeVisible();
    await expect.poll(async () => (await page.locator("body").innerText()).trim().length)
      .toBeGreaterThan(20);
    await page.waitForLoadState("load");
    const body = await page.locator("body").innerText();

    report.push({
      route: "/" + route,
      url: page.url(),
      status,
      title: await page.title(),
      bodyLength: body.trim().length,
      assetFailures,
      pageErrors,
      consoleErrors,
      toleratedDemoConsoleErrors,
    });

    expect(status, "document status").toBeGreaterThanOrEqual(200);
    expect(status, "document status").toBeLessThan(400);
    expect(body).not.toContain("Unexpected application error");
    expect(body).not.toContain("404: Not Found");
    expect(assetFailures, "same-origin JS/CSS failures").toEqual([]);
    expect(pageErrors, "uncaught exceptions").toEqual([]);
    expect(consoleErrors, "unexpected browser console errors").toEqual([]);
  });
}
