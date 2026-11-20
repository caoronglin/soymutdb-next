/**
 * Sub-path deployment gate (`/soymutdb-next/`).
 *
 * Every other offline gate serves a base-`/` artifact at the origin root, so a
 * base-path mistake is invisible to all of them: the artifact would 404 on its
 * own bundles, emit root-absolute asset URLs, or lose the mount prefix on a
 * client-side route, and every root-base gate would still pass. This gate serves
 * the artifact where a gh-pages deploy actually puts it and asserts the four
 * things a prefix can break:
 *
 * 1. the document loads and the SPA takes over;
 * 2. every asset the document requests resolves UNDER the prefix — a
 *    root-absolute `/assets/…` request is the classic symptom;
 * 3. a deep link (not just the root) resolves; the prefix is not a redirect
 *    trick that only works for `/`;
 * 4. the deploy-read files (`routes.json`, `robots.txt`) are served at the
 *    prefix and name the SITE origin, never the API origin.
 *
 * These three assertions cover what the general public suite cannot see on its
 * own: the suite proves the pages work, this file proves they work *because the
 * prefix is right* — no root-absolute asset, the deep link keeps the prefix, and
 * the deploy-read files name the site origin. Both run in the same gate.
 */
import { test, expect, type Page } from "@playwright/test";

const PREFIX = "/soymutdb-next";

/** Path of every request the page made, relative to the origin. */
function trackRequests(page: Page): string[] {
  const paths: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.origin === new URL(page.url() || "http://localhost").origin) {
      paths.push(url.pathname);
    }
  });
  return paths;
}

test("the artifact loads under its mount prefix and never fetches a root-absolute asset", async ({
  page,
}) => {
  const requests = trackRequests(page);
  const failures: string[] = [];
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.pathname.startsWith(`${PREFIX}/assets/`) && response.status() >= 400) {
      failures.push(`${response.status()} ${url.pathname}`);
    }
  });

  await page.goto(`${PREFIX}/`, { waitUntil: "load" });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.appReady ?? null), {
      message: "the SPA never announced readiness under the mount prefix",
      timeout: 20_000,
    })
    .toBe("true");

  // The application is interactive, not just a served HTML file.
  await expect(page.locator("main, #root > *").first()).toBeVisible({ timeout: 15_000 });

  // Decisive base-path check: no asset may be requested from the origin root.
  const rootAbsolute = requests.filter(
    (path) => path.startsWith("/assets/") && !path.startsWith(`${PREFIX}/assets/`),
  );
  expect(rootAbsolute, "assets were requested from the origin root, not the prefix").toEqual([]);
  expect(failures, "a prefixed asset failed to load").toEqual([]);
});

test("a deep link resolves under the prefix", async ({ page }) => {
  // Not the root: a base that only works for `/` is a redirect, not a mount.
  await page.goto(`${PREFIX}/search/genes`, { waitUntil: "load" });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.appReady ?? null), {
      message: "the SPA never announced readiness on a deep link",
      timeout: 20_000,
    })
    .toBe("true");

  await expect(page.getByTestId("search-genes-form")).toBeVisible({ timeout: 15_000 });
  // The URL keeps the prefix; a client-side redirect to the origin root would
  // silently move the user out of the deployment.
  expect(new URL(page.url()).pathname.startsWith(`${PREFIX}/`)).toBe(true);
});

test("the deploy-read files are served at the prefix and name the site origin", async ({
  request,
}) => {
  const manifest = await request.get(`${PREFIX}/routes.json`);
  expect(manifest.ok(), "routes.json is not served at the mount prefix").toBe(true);
  const document = (await manifest.json()) as { origin: string; entries: unknown[] };
  expect(document.entries.length).toBeGreaterThan(0);
  // The canonical/sitemap origin must be the deployment's own site, never the
  // API host — that mistake shipped once and is invisible to every root gate.
  expect(document.origin).toMatch(/^https:\/\//);
  expect(document.origin).not.toContain("api.");

  const robots = await request.get(`${PREFIX}/robots.txt`);
  expect(robots.ok(), "robots.txt is not served at the mount prefix").toBe(true);
  const policy = await robots.text();
  expect(policy).toContain("Allow: /");
  expect(policy).toContain("Sitemap:");
});