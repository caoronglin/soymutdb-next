import { expect, test, type Page, type Response } from "@playwright/test";

/**
 * PRODUCTION E2E hard gate.
 *
 * Targets a REAL production/staging deployment (PRODUCTION_BASE_URL). Unlike
 * the gh-pages DEMO smoke (online-smoke.spec.ts), this suite treats fixture /
 * placeholder / fallback content as a hard failure:
 *   - API data endpoints must answer 2xx (a 404/405 means the SPA is showing a
 *     fallback state, not real release data);
 *   - embedded demo markers (SMDB-00001, "Demo fixture"), placeholder origins
 *     (example.com, localhost) and change-me must be ABSENT from every key
 *     page;
 *   - the demo sample fixture route /samples/SMDB-00001.html must NOT exist;
 *   - the public portal, JBrowse frame and Admin console are reachable and
 *     render.
 *
 * Set PRODUCTION_BASE_URL to the deployed origin. A missing value fails the
 * whole gate instead of silently testing the wrong thing.
 */

const PRODUCTION_BASE_URL = process.env.PRODUCTION_BASE_URL ?? "";

const RELEASE_ROUTES = ["/", "/about", "/browser", "/search", "/genes", "/downloads"] as const;

/** Placeholder / demo markers that must never appear in a release page. */
const FORBIDDEN_MARKERS = [
  "SMDB-00001",
  "Demo fixture",
  "demonstration data",
  "change-me",
  "localhost",
  "example.com",
  "api.example.com",
] as const;

/** Match API-shaped request paths so we can classify their responses. */
const API_PATH_RE =
  /^\/(api\/|auth\/|stats\/|genes\/|variants\/|news\/|site\/|blast\/|tools\/|analyses\/|gwas\/|notifications\/|seed-requests\/|content\/|expression\/|homolog\/|releases\/|sra\/|downloads\/|mutants\/|health\/|admin\/|widget\/)/i;

test.beforeAll(() => {
  if (!PRODUCTION_BASE_URL) {
    throw new Error(
      "PRODUCTION_BASE_URL is not set — the production E2E gate must target a real release deployment.",
    );
  }
});

async function collectText(page: Page, route: string): Promise<string> {
  await page.goto(route, { waitUntil: "networkidle" });
  return (await page.locator("body").innerText()).trim();
}

test.describe("production gate — no demo / placeholder / fallback content", () => {
  test("key routes must be free of demo & placeholder markers and render", async ({ page }) => {
    const apiStatuses: number[] = [];
    const badResponses: { url: string; status: number }[] = [];

    page.on("response", (res: Response) => {
      const path = new URL(res.url()).pathname;
      if (API_PATH_RE.test(path)) apiStatuses.push(res.status());
      if (res.status() >= 400 && !API_PATH_RE.test(path)) {
        badResponses.push({ url: res.url(), status: res.status() });
      }
    });

    for (const route of RELEASE_ROUTES) {
      const body = await collectText(page, route);
      expect(body.length, `body must not be blank on ${route}`).toBeGreaterThan(0);
      expect(body, `'Not Found' must not appear on ${route}`).not.toContain("Not Found");
      expect(body, `'Unexpected application error' must not appear on ${route}`).not.toContain(
        "Unexpected application error",
      );

      for (const marker of FORBIDDEN_MARKERS) {
        expect(
          body,
          `release page ${route} must not contain demo/placeholder marker: ${marker}`,
        ).not.toContain(marker);
      }

      expect(
        (await page.locator("h1, h2").count()),
        `at least one h1/h2 must render on release route ${route}`,
      ).toBeGreaterThan(0);
    }

    expect(
      badResponses,
      "no static-asset HTTP >=400 responses are allowed on production (missing asset is a deploy bug)",
    ).toEqual([]);
    expect(
      apiStatuses.some((s) => s >= 200 && s < 300),
      "at least one API data endpoint must answer 2xx — a production deployment must serve release data, never a fallback state",
    ).toBe(true);
    expect(
      apiStatuses.filter((s) => s === 404 || s === 405),
      "API endpoints must not answer 404/405 in production (SPA is in fallback mode)",
    ).toEqual([]);
  });

  test("demo sample fixture must not be served in production", async ({ page }) => {
    const control = await page.goto("/samples/SMDB-00001.html", {
      waitUntil: "domcontentloaded",
    });
    // Production must not publish the demo sample fixtures. A 404 is the
    // desired outcome; anything reachable means demo data leaked into release.
    expect(control?.status()).toBe(404);
  });
});

test.describe("production gate — release subsystems reachable", () => {
  test("JBrowse frame is reachable and not CSP-blocked", async ({ page }) => {
    await page.goto("/browser", { waitUntil: "networkidle" });
    // The browser route must render; if JBrowse is mounted as an iframe it must
    // load a live frame (not a CSP-blocked / failed frame).
    expect(
      (await page.locator("h1, h2").count()) +
        (await page.locator("iframe").count()),
    ).toBeGreaterThan(0);

    const frames = page.frames();
    const jbrowseFrame = frames.find((f) =>
      /jbrowse|\/browser\//i.test(f.url() || ""),
    );
    if (jbrowseFrame) {
      await expect(jbrowseFrame.locator("body")).not.toBeEmpty({ timeout: 15_000 });
    }
  });

  test("admin console login page is reachable and renders", async ({ page, request }) => {
    // Admin is a protected origin — resolve its base from the deployment.
    const adminCandidate = new URL(PRODUCTION_BASE_URL);
    const adminUrl = `${adminCandidate.origin}/login`;

    const res = await request.get(adminUrl);
    expect(res.status(), `admin login must be reachable at ${adminUrl}`).toBeLessThan(400);

    await page.goto(adminUrl, { waitUntil: "load" });
    await expect(page).toHaveTitle("SoyMutDB Admin");
  });
});
