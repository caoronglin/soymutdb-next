/**
 * Reproducible local artifact budget and navigation-timing smoke.
 *
 * This is lab evidence for a built static artifact, not RUM: it must never be
 * presented as production LCP/INP P75. Resource-transfer values are captured
 * from the browser Resource Timing API after a cold page load.
 */
import { expect, test } from "@playwright/test";
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

type ResourceMetric = {
  name: string;
  initiatorType: string;
  transferSize: number;
  encodedBodySize: number;
  decodedBodySize: number;
  durationMs: number;
};

type PerformanceReport = {
  generatedAt: string;
  target: string;
  methodology: string;
  assertions: Record<string, number>;
  metrics: {
    navigation: Record<string, number>;
    resources: {
      count: number;
      transferBytes: number;
      scriptTransferBytes: number;
      stylesheetTransferBytes: number;
      initialScriptTransferBytes: number;
      initialStylesheetTransferBytes: number;
      largestResources: ResourceMetric[];
    };
  };
};

const LIMITS = {
  // A-11 initial JavaScript target: emitted HTML module script + preloads.
  initialScriptTransferBytes: 1_200_000,
  initialStylesheetTransferBytes: 250_000,
  initialResourceTransferBytes: 3_000_000,
};

const reportPath = resolve(import.meta.dirname, "..", "test-results-web-performance", "performance-report.json");

test("built public Web artifact stays within initial asset budgets", async ({ page, baseURL }) => {
  const pageErrors: Error[] = [];
  page.on("pageerror", (error) => pageErrors.push(error));
  const assets = new Map<string, number>();
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.origin !== new URL(baseURL!).origin || !url.pathname.startsWith("/assets/")) return;
    assets.set(url.pathname, response.status());
  });

  const response = await page.goto(baseURL!, { waitUntil: "load" });
  expect(response?.status()).toBe(200);
  // The assertion is intentionally artifact-level: dynamic application content
  // can depend on unavailable local API configuration, but all emitted entry
  // files must be fetched successfully before timing is recorded.
  await expect(page.locator("#root")).toBeAttached();
  // The explicit page response assertion above verifies the document; module
  // fetches are captured below for bytes and the browser rejects malformed
  // module responses during execution. Do not fail on duplicated preloads.
  expect(assets.size).toBeGreaterThan(0);
  const artifactRoot = resolve(import.meta.dirname, "..", "..", "apps", "web", "dist");
  // Read build output rather than the live DOM: module loading may append lazy
  // chunks after navigation, which are not initial HTML dependencies.
  const initialAssetPaths = [...readFileSync(resolve(artifactRoot, "index.html"), "utf8").matchAll(
    /(?:src|href)="(\/assets\/[^"]+\.(?:js|css))"/g,
  )].map((match) => match[1]);

  const report = await page.evaluate(() => {
    const navigation = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
    const resources = performance
      .getEntriesByType("resource")
      .filter((entry): entry is PerformanceResourceTiming => entry instanceof PerformanceResourceTiming)
      .map((entry) => ({
        name: new URL(entry.name).pathname,
        initiatorType: entry.initiatorType,
        transferSize: entry.transferSize,
        encodedBodySize: entry.encodedBodySize,
        decodedBodySize: entry.decodedBodySize,
        durationMs: Number(entry.duration.toFixed(2)),
      }));

    // ResourceTiming names are paths without the deployment prefix because the
    // static server strips it before serving the baked /assets URLs. Keep only
    // same-origin emitted files and exclude the document navigation.
    const sameOrigin = resources.filter((resource) => resource.name.startsWith("/assets/") || resource.name.startsWith("/fonts/") || resource.name === "/sw.js" || resource.name === "/favicon.svg");
    const byType = (type: string) => sameOrigin.filter((resource) => resource.initiatorType === type);
    // Resource Timing remains useful for local timing diagnostics. Budget
    // assertions below use emitted-file sizes for the exact HTML-referenced
    // initial JS/CSS artifacts, independent of browser transfer accounting.
    const bytes = (item: ResourceMetric) => item.decodedBodySize || item.encodedBodySize || item.transferSize;
    const sum = (items: typeof resources) => items.reduce((total, item) => total + bytes(item), 0);
    const scripts = byType("script");
    const stylesheets = byType("link").filter((resource) => resource.name.endsWith(".css"));
    const initialScripts = scripts.filter((resource) => resource.name.endsWith(".js"));

    return {
      navigation: {
        responseStartMs: Number((navigation?.responseStart ?? 0).toFixed(2)),
        domContentLoadedMs: Number((navigation?.domContentLoadedEventEnd ?? 0).toFixed(2)),
        loadEventEndMs: Number((navigation?.loadEventEnd ?? 0).toFixed(2)),
      },
      resources: {
        count: sameOrigin.length,
        transferBytes: sum(sameOrigin),
        scriptTransferBytes: sum(scripts),
        stylesheetTransferBytes: sum(stylesheets),
        initialScriptTransferBytes: sum(initialScripts),
        initialStylesheetTransferBytes: sum(stylesheets),
        largestResources: [...sameOrigin].sort((a, b) => b.transferSize - a.transferSize).slice(0, 10),
      },
    };
  });

  // Resource Timing intentionally does not expose a stable body size in this
  // local Chromium/static-server combination. Count the exact immutable files
  // that the emitted HTML references instead, and independently require the
  // browser to have received each one successfully.
  const emittedFileSize = (pathname: string) => {
    expect(assets.get(pathname)).toBe(200);
    const file = resolve(artifactRoot, `.${pathname}`);
    expect(file.startsWith(`${artifactRoot}/`)).toBe(true);
    expect(existsSync(file)).toBe(true);
    return statSync(file).size;
  };
  const scriptAssetBytes = initialAssetPaths
    .filter((pathname) => pathname.endsWith(".js"))
    .reduce((total, pathname) => total + emittedFileSize(pathname), 0);
  const stylesheetAssetBytes = initialAssetPaths
    .filter((pathname) => pathname.endsWith(".css"))
    .reduce((total, pathname) => total + emittedFileSize(pathname), 0);
  report.resources.transferBytes = scriptAssetBytes + stylesheetAssetBytes;
  report.resources.scriptTransferBytes = scriptAssetBytes;
  report.resources.stylesheetTransferBytes = stylesheetAssetBytes;
  report.resources.initialScriptTransferBytes = scriptAssetBytes;
  report.resources.initialStylesheetTransferBytes = stylesheetAssetBytes;

  const fullReport: PerformanceReport = {
    generatedAt: new Date().toISOString(),
    target: baseURL!,
    methodology: "Single cold local Chromium navigation to apps/web/dist via e2e/static-server.mjs. Navigation timings are browser Performance Timing values; asset bytes are exact emitted files referenced by the loaded HTML and independently verified as 200 responses. This is not production RUM and does not measure or claim LCP/INP P75.",
    assertions: LIMITS,
    metrics: report,
  };
  mkdirSync(dirname(reportPath), { recursive: true });
  writeFileSync(reportPath, JSON.stringify(fullReport, null, 2) + "\\n", "utf8");

  expect(report.resources.initialScriptTransferBytes).toBeLessThanOrEqual(LIMITS.initialScriptTransferBytes);
  expect(report.resources.initialStylesheetTransferBytes).toBeLessThanOrEqual(LIMITS.initialStylesheetTransferBytes);
  expect(report.resources.transferBytes).toBeLessThanOrEqual(LIMITS.initialResourceTransferBytes);
  expect(report.navigation.domContentLoadedMs).toBeGreaterThan(0);
  expect(pageErrors.map((error) => error.message)).toEqual([]);
  expect(existsSync(reportPath)).toBe(true);
});