/**
 * React JBrowse shell E2E — standalone shell chrome + portal "/browser" embed.
 *
 * Coverage
 * --------
 *  1. Standalone shell (apps/jbrowse, the React rewrite of the old Vue shell):
 *     header wordmark, the Ant Design assembly Select, the locus-search input,
 *     the share + fullscreen controls, the locus/active-tracks/assembly summary
 *     bar, the JBrowse view container, and the footer text.
 *  2. Portal embed (apps/web "/browser"): the JBrowse <iframe> is mounted with
 *     the portal origin, the postMessage bridge reaches its "ready" state
 *     (observable as [data-testid="browser-ready"]), and the frame document is
 *     the real React shell rather than a CSP-blocked / error stub.
 *  3. Fail-closed context: a /browser deep link without an explicit assembly and
 *     release renders the neutral [data-testid="browser-missing-context"] state
 *     and mounts no iframe, rather than silently showing the v4 namespace.
 *
 * How to run — requires a DEPLOYED stack (it cannot run in this offline repo)
 * --------------------------------------------------------------------------
 * Prerequisites
 *   - apps/jbrowse built and served at JBROWSE_BASE_URL;
 *   - apps/web built with VITE_JBROWSE_BASE_URL=<JBROWSE_BASE_URL> and a CSP
 *     frame-src that allows that origin, served at PORTAL_BASE_URL;
 *   - the shell origin serves /jbrowse-data with the REAL files its config
 *     references (the assembly FASTA + .fai/.gzi, chrom.sizes, the variant /
 *     annotation track files and the Trix index). The chrome assertions need
 *     only the built app; the view-container assertion additionally requires
 *     the release-scoped config to load, which is why this suite is a
 *     deployed-stack gate rather than an offline one.
 *   - a seeded API with a PUBLISHED release so /genes/assemblies and
 *     /tracks/jbrowse-config answer normally. The shell does NOT fall back to a
 *     built-in assembly: without a resolvable release+assembly it shows an
 *     explicit unavailable state, and this suite reports that as a failure.
 *
 * Command (from e2e/):
 *
 *   JBROWSE_BASE_URL=https://jbrowse.soymutdb.test/ \
 *   PORTAL_BASE_URL=https://soymutdb.test/ \
 *     npx playwright test -c playwright-jbrowse.config.ts
 *
 * JBROWSE_BASE_URL gates the standalone tests and PORTAL_BASE_URL gates the
 * embed tests; a missing value reports the dependent tests as SKIPPED instead of
 * silently testing the wrong environment. SMOKE_JBROWSE_BASE_URL and
 * SMOKE_BASE_URL are accepted as fallbacks.
 *
 * Offline note
 *   e2e/static-server.mjs serves only apps/web/dist and knows nothing about the
 *   shell or /jbrowse-data, so with these variables unset — the state of this
 *   repository environment — there is nothing to execute and every test here
 *   skips.
 */
import { expect, test, type Page } from "@playwright/test";

import { gotoReady } from "./helpers";

/** Standalone React shell base, e.g. "https://jbrowse.soymutdb.test/". */
const SHELL_BASE_URL =
  process.env.JBROWSE_BASE_URL ?? process.env.SMOKE_JBROWSE_BASE_URL ?? "";

/** Portal base that embeds the shell at /browser. */
const PORTAL_BASE_URL =
  process.env.PORTAL_BASE_URL ?? process.env.SMOKE_BASE_URL ?? "";

/**
 * Default active tracks (reference_sequence, gene_models, variants_v4).
 * Mirrors apps/jbrowse/src/config.ts `DEFAULT_TRACKS`.
 */
const DEFAULT_ACTIVE_TRACK_COUNT = 3;

/**
 * Assembly/locus used by the deep-link assertions. The shell resolves the
 * assembly *name* against the published release's assembly list, so the value
 * must exist in the deployed release (override with E2E_JBROWSE_ASSEMBLY).
 */
const DEEP_LINK_ASSEMBLY = process.env.E2E_JBROWSE_ASSEMBLY ?? "Wm82v4.0";
const DEEP_LINK_LOCUS = "chr01:1-1000";

/** Resolve a path under a base that may carry a sub-path prefix. */
function underBase(base: string, path = ""): string {
  const root = base.endsWith("/") ? base : base + "/";
  return new URL(path, root).toString();
}

/** Navigate to the shell and wait for its header (the shell has no SSG handoff). */
async function gotoShell(page: Page, path = ""): Promise<void> {
  await page.goto(underBase(SHELL_BASE_URL, path), { waitUntil: "domcontentloaded" });
  await expect(page.locator("header")).toBeVisible();
}

test.describe("React JBrowse shell — standalone chrome", () => {
  test("renders the wordmark, assembly select, locus search, actions and footer", async ({
    page,
  }) => {
    test.skip(!SHELL_BASE_URL, "set JBROWSE_BASE_URL to the deployed React JBrowse shell");
    await gotoShell(page);

    const header = page.locator("header");
    await expect(header.getByText("SoyMutDB", { exact: true })).toBeVisible();
    await expect(header.getByText("Genome Browser", { exact: true })).toBeVisible();

    // Ant Design renders a combobox, not a native <select>. The option list is
    // whatever the published release exposes (no hardcoded trio), so the
    // assertion is that a selectable control exists and is operable.
    const assembly = page.getByLabel("Select reference assembly");
    await expect(assembly).toBeVisible();
    await assembly.click();
    const options = page.getByRole("option");
    await expect(options.first()).toBeVisible();
    expect(await options.count()).toBeGreaterThan(0);
    await page.keyboard.press("Escape");

    // Locus search: the accessible name is the input contract.
    await expect(page.getByLabel("Genomic location or gene search")).toBeVisible();

    // Share + fullscreen controls are icon buttons, so they are asserted by
    // their accessible name rather than by an icon.
    await expect(page.getByRole("button", { name: "Share current view" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Enter fullscreen" })).toBeVisible();

    const footer = page.locator("footer");
    await expect(footer).toBeVisible();
    await expect(footer).toContainText("Powered by JBrowse 2");
    await expect(footer).toContainText("SoyMutDB Genome Browser");
    await expect(footer).toContainText(DEFAULT_ACTIVE_TRACK_COUNT + " tracks loaded");
  });

  test("summary bar reports the default locus, active tracks and assembly", async ({
    page,
  }) => {
    test.skip(!SHELL_BASE_URL, "set JBROWSE_BASE_URL to the deployed React JBrowse shell");
    await gotoShell(page);

    const header = page.locator("header");
    await expect(header.getByText("No location selected")).toBeVisible();
    await expect(
      header.getByText(DEFAULT_ACTIVE_TRACK_COUNT + " active tracks"),
    ).toBeVisible();
    // The assembly is resolved from the release (or adopted as its default) and
    // is always rendered — an empty label would mean no context was resolved.
    await expect(header.getByText(/^Assembly: .+/)).toBeVisible();
  });

  test("a deep link restores the locus into the search box and summary bar", async ({
    page,
  }) => {
    test.skip(!SHELL_BASE_URL, "set JBROWSE_BASE_URL to the deployed React JBrowse shell");
    await gotoShell(
      page,
      `?assembly=${encodeURIComponent(DEEP_LINK_ASSEMBLY)}&locus=${encodeURIComponent(DEEP_LINK_LOCUS)}`,
    );

    await expect(page.getByLabel("Genomic location or gene search")).toHaveValue(DEEP_LINK_LOCUS);
    await expect(page.locator("header").getByText(DEEP_LINK_LOCUS)).toBeVisible();
    await expect(page.locator("header").getByText(`Assembly: ${DEEP_LINK_ASSEMBLY}`)).toBeVisible();
  });

  test("renders the JBrowse view container without the unavailable state", async ({ page }) => {
    test.skip(!SHELL_BASE_URL, "set JBROWSE_BASE_URL to the deployed React JBrowse shell");
    await gotoShell(page, `?assembly=${encodeURIComponent(DEEP_LINK_ASSEMBLY)}`);

    // @jbrowse/react-linear-genome-view owns its internal DOM, so the shell
    // contract is the container plus "not in the unavailable state": the
    // previous implementation fell back to a renamed v4 assembly here, and the
    // replacement must instead reach a real view for a resolvable assembly.
    await expect(page.locator("main.jbrowse-container")).toBeVisible();
    await expect(page.getByTestId("jbrowse-unavailable")).toHaveCount(0);
  });
});

test.describe("Portal /browser — JBrowse iframe embed", () => {
  test("mounts the shell iframe and reaches the bridge ready state", async ({ page }) => {
    test.skip(!PORTAL_BASE_URL, "set PORTAL_BASE_URL to the deployed portal");

    // The portal route now requires explicit context; pass the assembly (and a
    // release when the deployed portal is not pinned at build time).
    const release = process.env.E2E_RELEASE_ID;
    const params = new URLSearchParams({ assembly: DEEP_LINK_ASSEMBLY });
    if (release) params.set("release", release);

    // Reuse the shared SPA handoff helper: the portal's prerendered markup is
    // inert until React commits, so interacting before data-app-ready is unsafe.
    await gotoReady(page, `${underBase(PORTAL_BASE_URL, "browser")}?${params.toString()}`);

    const iframe = page.getByTestId("browser-iframe");
    await expect(iframe).toBeVisible();

    // The iframe must carry the embedding portal's origin so the shell can
    // validate the parent and post its ready envelope back.
    const src = await iframe.getAttribute("src");
    expect(src, "the shell iframe must have a src").toBeTruthy();
    const resolvedSrc = new URL(src as string, underBase(PORTAL_BASE_URL));
    expect(resolvedSrc.searchParams.get("portalOrigin")).toBe(
      new URL(underBase(PORTAL_BASE_URL)).origin,
    );

    // The portal flips to ready only after the canonical bridge helper
    // (packages/shared/src/jbrowse-bridge.ts) validates a ready envelope from
    // the frame. A timeout/error label is a hard failure, never a pass.
    await expect(page.getByTestId("browser-ready")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("browser-timeout")).toHaveCount(0);
    await expect(page.getByTestId("browser-error")).toHaveCount(0);

    // Prove the frame document is the real React shell, not a blocked stub.
    await expect(
      page
        .frameLocator('[data-testid="browser-iframe"]')
        .getByText("SoyMutDB", { exact: true }),
    ).toBeVisible({ timeout: 15_000 });
  });

  test("a context-free /browser deep link fails closed instead of opening v4", async ({
    page,
  }) => {
    test.skip(!PORTAL_BASE_URL, "set PORTAL_BASE_URL to the deployed portal");

    await gotoReady(page, underBase(PORTAL_BASE_URL, "browser"));

    // No assembly/release context: the route must NOT silently select a genome
    // namespace (that was the v4 fallback defect). It renders the neutral state
    // and never mounts the JBrowse frame.
    await expect(page.getByTestId("browser-missing-context")).toBeVisible();
    await expect(page.getByTestId("browser-iframe")).toHaveCount(0);
  });
});
