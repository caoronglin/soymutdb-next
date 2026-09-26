/**
 * Internal site variant E2E — a separate origin/base path with its own policy.
 *
 * The internal artifact is served at the origin root (/), while the public
 * artifact lives under a sub-path (/soymutdb-next). This suite proves that
 * boundary and that the internal-only surfaces behave:
 *
 *   1. the document is served from the root base, carries the internal
 *      noindex/nofollow/noarchive robots meta, loads its assets from root-
 *      relative /assets/* URLs (never the public sub-path), and serves a
 *      robots.txt that disallows all indexing;
 *   2. the internal homepage advertises the internal site variant, and the
 *      login route lives at /login on the internal origin — the public
 *      sub-path route is not the internal route.
 *
 * Prerequisites
 * -------------
 *   - the internal artifact deployed at INTERNAL_BASE_URL, served at /.
 *   - PUBLIC_BASE_URL (or PORTAL_BASE_URL / SMOKE_BASE_URL) is optional; when
 *     set, the suite additionally asserts the internal base is not the public
 *     origin + base path.
 *
 * Every test SKIPS when INTERNAL_BASE_URL is unset. No credential is ever
 * submitted: the login test only proves the internal-only login surface
 * renders.
 *
 * Run (from e2e/):
 *   INTERNAL_BASE_URL=https://internal.soymutdb.test/ \
 *     npx playwright test -c playwright-internal.config.ts
 */
import { expect, test } from "@playwright/test";

import { gotoReady, trackErrors } from "./helpers";

/** Deployed internal variant base. The internal artifact is served at "/". */
const INTERNAL_BASE_URL = (process.env.INTERNAL_BASE_URL ?? "").trim();

/** Optional public base, used to prove the two variants are separate. */
const PUBLIC_BASE_URL = (
  process.env.PUBLIC_BASE_URL ??
  process.env.PORTAL_BASE_URL ??
  process.env.SMOKE_BASE_URL ??
  ""
).trim();

/** The public artifact's sub-path; the internal artifact must never use it. */
const PUBLIC_BASE_PATH = "/soymutdb-next";

const SKIP_NO_BASE =
  "set INTERNAL_BASE_URL to the deployed internal variant (served at /)";

/** Resolve a path under a base that may carry a sub-path prefix. */
function underBase(base: string, path = ""): string {
  const root = base.endsWith("/") ? base : `${base}/`;
  return new URL(path.replace(/^\//, ""), root).toString();
}

test.describe("internal site variant — separate origin/base path", () => {
  test("serves the internal artifact at its root base with internal-only policy", async ({
    page,
    request,
  }) => {
    test.skip(!INTERNAL_BASE_URL, SKIP_NO_BASE);

    const internal = new URL(INTERNAL_BASE_URL);
    // The internal artifact is addressed at the origin root, not a sub-path.
    expect(
      internal.pathname.replace(/\/+$/, ""),
      "INTERNAL_BASE_URL must point at / (the internal artifact's base)",
    ).toBe("");

    // When the public base is known, the two variants must not collapse onto
    // the same origin + base path.
    if (PUBLIC_BASE_URL) {
      const publicUrl = new URL(PUBLIC_BASE_URL);
      const sameOrigin = internal.origin === publicUrl.origin;
      const samePath =
        internal.pathname.replace(/\/+$/, "") === publicUrl.pathname.replace(/\/+$/, "");
      expect(
        sameOrigin && samePath,
        "the internal variant must not share the public artifact's origin and base path",
      ).toBe(false);
    }

    const errors = trackErrors(page);
    await gotoReady(page, underBase(INTERNAL_BASE_URL));

    // Internal-only index policy on the document itself.
    const robotsMeta = page.locator('meta[name="robots"]');
    await expect(robotsMeta).toHaveAttribute("content", /noindex/i);
    await expect(robotsMeta).toHaveAttribute("content", /nofollow/i);
    await expect(robotsMeta).toHaveAttribute("content", /noarchive/i);

    // Base-path proof: every same-origin asset resolves under the internal
    // origin and none is fetched through the public sub-path.
    const baseOrigin = new URL(underBase(INTERNAL_BASE_URL)).origin;
    const assetUrls = await page
      .locator("script[src], link[href]")
      .evaluateAll((nodes, origin) =>
        nodes
          .map((node) => node.getAttribute("src") ?? node.getAttribute("href") ?? "")
          .filter(Boolean)
          .map((raw) => new URL(raw, origin).toString())
          .filter((url) => url.startsWith(origin)),
        baseOrigin,
      );
    expect(assetUrls.length, "the internal document must reference its own assets").toBeGreaterThan(0);
    expect(
      assetUrls.some((url) => new URL(url).pathname.startsWith("/assets/")),
      "at least one root-relative /assets/* bundle must load",
    ).toBe(true);
    for (const url of assetUrls) {
      expect(
        new URL(url).pathname.startsWith(`${PUBLIC_BASE_PATH}/`),
        `${url} must not be served through the public sub-path ${PUBLIC_BASE_PATH}`,
      ).toBe(false);
    }

    // The internal artifact publishes a deny-all robots.txt (the public one
    // allows crawling), which is an internal-only surface.
    const robots = await request.get(underBase(INTERNAL_BASE_URL, "robots.txt"));
    expect(robots.status()).toBe(200);
    expect(await robots.text()).toMatch(/^\s*Disallow:\s*\/\s*$/m);

    expect(
      errors,
      "the internal document must render without unexpected console errors or pageerrors",
    ).toEqual([]);
  });

  test("internal-only surfaces behave at the root base path", async ({ page }) => {
    test.skip(!INTERNAL_BASE_URL, SKIP_NO_BASE);

    const errors = trackErrors(page);

    // The running SPA reports its deployment variant; on the internal artifact
    // that value is "internal", never "external".
    await gotoReady(page, underBase(INTERNAL_BASE_URL));
    await expect(page.getByTestId("home-context")).toContainText(/internal/i);
    expect(new URL(page.url()).pathname).not.toMatch(
      new RegExp(`^${PUBLIC_BASE_PATH}(/|$)`),
    );

    // The internal login surface is the root-relative /login route; the public
    // suite's /soymutdb-next/login is a different (public) base path.
    await gotoReady(page, underBase(INTERNAL_BASE_URL, "login"));
    await expect(page.getByTestId("login-form")).toBeVisible();
    await expect(page.getByTestId("login-email")).toBeVisible();
    await expect(page.getByTestId("login-password")).toBeVisible();
    await expect(page.getByTestId("login-submit")).toBeVisible();
    expect(new URL(page.url()).pathname).toBe("/login");
    // No credential is filled or submitted by this suite.
    await expect(page.getByTestId("login-email")).toHaveValue("");

    expect(
      errors,
      "the internal-only surfaces must render without unexpected console errors or pageerrors",
    ).toEqual([]);
  });
});
