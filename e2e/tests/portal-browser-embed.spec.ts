/**
 * Portal /browser — JBrowse embed regression for a DEPLOYED stack.
 *
 * Asserts the public contract of the embed, not its cosmetics:
 *   1. the `/browser` route mounts the shell iframe and passes the embedding
 *      portal's origin as `portalOrigin`, so the shell can validate the parent
 *      and post its ready envelope back;
 *   2. the postMessage bridge reaches its ready state (observable as
 *      [data-testid="browser-ready"]); a timeout/error label is a hard failure,
 *      never a pass;
 *   3. no URL in the embed — the portal location, the iframe `src`, the shell
 *      frame URL or the open-in-new-tab link — exposes a private persistence
 *      identifier. Only public identifiers (assembly, locus, released public
 *      ids) may appear. A private/internal key handed to the portal is dropped
 *      when the shell URL is built, never forwarded to the frame.
 *
 * This is the external-site boundary from docs/dev/database-core-contract.md:
 * public URLs carry public identifiers only.
 *
 * Prerequisites
 * -------------
 *   - a deployed public portal served at PORTAL_BASE_URL, built with the
 *     JBrowse shell URL and a CSP `frame-src` that allows it (`/browser` must
 *     be enabled by its feature gate);
 *   - the shell reachable from the browser and able to post its ready envelope
 *     over the bridge (its data files make the embed meaningful, but the ready
 *     assertion only needs the app).
 *
 * Unlike `playwright-jbrowse.config.ts`, this suite does not test the
 * standalone shell; it only needs the portal origin. Set PORTAL_BASE_URL (or
 * SMOKE_BASE_URL) — otherwise every test here SKIPS.
 *
 * Run (from e2e/):
 *   PORTAL_BASE_URL=https://soymutdb.test/ \
 *     npx playwright test -c playwright-portal-embed.config.ts
 *
 * Discover without a browser:
 *   PORTAL_BASE_URL=https://soymutdb.test/ \
 *     npx playwright test -c playwright-portal-embed.config.ts --list
 */
import { expect, test } from "@playwright/test";

import { gotoReady } from "./helpers";

/** Deployed portal base that embeds the shell at /browser. */
const PORTAL_BASE_URL = (
  process.env.PORTAL_BASE_URL ??
  process.env.SMOKE_BASE_URL ??
  ""
).trim();

/**
 * Query keys the portal may put on the shell URL. Mirrors
 * `buildJbrowseUrl` in apps/web/src/routes/browser.tsx; an unexpected key is
 * a leakage vector, not an extension point.
 */
const BRIDGE_QUERY_KEYS = new Set(["assembly", "locus", "tracks", "release", "portalOrigin"]);

/**
 * Case-insensitive markers for private persistence keys, which must never
 * appear in a browser URL (including percent-encoded spellings).
 */
const INTERNAL_ID_MARKERS = [
  "internal_id",
  "internalid",
  "internal-id",
  "internal%5fid",
  "internal%2did",
];

/** Query keys that name a private persistence key rather than a public one. */
const INTERNAL_ID_QUERY_KEYS = new Set([
  "internal_id",
  "internalid",
  "internal-id",
  "record_id",
  "recordid",
  "record-id",
  "db_id",
  "dbid",
  "db-id",
  "pk",
  "row_id",
  "rowid",
  "row-id",
]);

/** Resolve a path under a base that may carry a sub-path prefix. */
function underBase(base: string, path = ""): string {
  const root = base.endsWith("/") ? base : `${base}/`;
  return new URL(path.replace(/^\//, ""), root).toString();
}

/** Fail if a URL exposes a private persistence identifier in any position. */
function expectNoInternalIdentifiers(rawUrl: string, where: string): void {
  const lower = rawUrl.toLowerCase();
  for (const marker of INTERNAL_ID_MARKERS) {
    expect(lower, `${where} must not contain the private marker "${marker}"`).not.toContain(
      marker,
    );
  }
  const url = new URL(rawUrl);
  for (const [key, value] of url.searchParams) {
    const normalized = key.toLowerCase();
    expect(
      INTERNAL_ID_QUERY_KEYS.has(normalized),
      `${where} must not use the private query key "${key}"`,
    ).toBe(false);
    if (normalized === "id") {
      expect(
        /^\d+$/.test(value),
        `${where} must not carry a numeric "id" query value ("${value}")`,
      ).toBe(false);
    }
  }
}

/** Fail if the shell URL forwards a query key outside the bridge allowlist. */
function expectOnlyBridgeParams(rawUrl: string, where: string): void {
  const url = new URL(rawUrl);
  for (const key of url.searchParams.keys()) {
    expect(
      BRIDGE_QUERY_KEYS.has(key),
      `${where} must not forward the unexpected query key "${key}"`,
    ).toBe(true);
  }
}

test.describe("portal /browser — JBrowse iframe embed", () => {
  test("mounts the shell with portalOrigin, reaches ready, and leaks no internal identifier", async ({
    page,
  }) => {
    test.skip(
      !PORTAL_BASE_URL,
      "set PORTAL_BASE_URL (or SMOKE_BASE_URL) to the deployed portal",
    );

    // The portal's prerendered markup is inert until React commits; interact only
    // after the shared SPA handoff helper reports readiness.
    await gotoReady(page, underBase(PORTAL_BASE_URL, "browser"));

    const iframe = page.getByTestId("browser-iframe");
    await expect(iframe).toBeVisible();

    const src = await iframe.getAttribute("src");
    expect(src, "the shell iframe must have a src").toBeTruthy();
    const shellUrl = new URL(src as string, underBase(PORTAL_BASE_URL, "browser"));

    // portalOrigin must equal the embedding portal's origin.
    expect(shellUrl.searchParams.get("portalOrigin")).toBe(
      new URL(underBase(PORTAL_BASE_URL)).origin,
    );
    expectOnlyBridgeParams(shellUrl.toString(), "the shell iframe src");

    // Ready is only valid when the shell posts a ready envelope; timeout/error
    // states are hard failures.
    await expect(page.getByTestId("browser-ready")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("browser-timeout")).toHaveCount(0);
    await expect(page.getByTestId("browser-error")).toHaveCount(0);

    // Prove the frame is the real JBrowse shell document, not a blocked stub.
    await expect(
      page
        .frameLocator('[data-testid="browser-iframe"]')
        .getByText("SoyMutDB", { exact: true }),
    ).toBeVisible({ timeout: 15_000 });

    // No URL in the embed may expose a private persistence identifier.
    expectNoInternalIdentifiers(page.url(), "the portal /browser URL");
    expectNoInternalIdentifiers(shellUrl.toString(), "the shell iframe src");

    const newTabHref = await page.getByTestId("browser-open-new-tab").getAttribute("href");
    expect(newTabHref, "the open-in-new-tab link must have an href").toBeTruthy();
    const newTabUrl = new URL(newTabHref as string, underBase(PORTAL_BASE_URL, "browser"));
    expectNoInternalIdentifiers(newTabUrl.toString(), "the standalone shell link");
    // The standalone link must not carry the embedding origin.
    expect(newTabUrl.searchParams.has("portalOrigin")).toBe(false);

    // The shell frame's own URL is the deepest place an identifier could leak.
    const handle = await iframe.elementHandle();
    const frame = await handle?.contentFrame();
    if (frame && /^https?:/i.test(frame.url())) {
      expectNoInternalIdentifiers(frame.url(), "the shell frame URL");
    }
  });

  test("drops a private identifier handed to the portal instead of forwarding it", async ({
    page,
  }) => {
    test.skip(
      !PORTAL_BASE_URL,
      "set PORTAL_BASE_URL (or SMOKE_BASE_URL) to the deployed portal",
    );

    // A stale/legacy link carrying a private persistence key alongside a public
    // locus: the portal must build the shell URL from known public params only.
    await gotoReady(
      page,
      `${underBase(PORTAL_BASE_URL, "browser")}?internal_id=42&locus=chr01:1-1000`,
    );

    const iframe = page.getByTestId("browser-iframe");
    await expect(iframe).toBeVisible();
    const src = await iframe.getAttribute("src");
    expect(src, "the shell iframe must have a src").toBeTruthy();
    const shellUrl = new URL(src as string, underBase(PORTAL_BASE_URL, "browser"));

    expect(shellUrl.searchParams.has("internal_id")).toBe(false);
    expectOnlyBridgeParams(shellUrl.toString(), "the shell iframe src");
    // The public locus still reaches the shell.
    expect(shellUrl.searchParams.get("locus")).toBe("chr01:1-1000");

    await expect(page.getByTestId("browser-ready")).toBeVisible({ timeout: 20_000 });
  });
});
