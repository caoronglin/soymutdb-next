/**
 * Vue JBrowse shell E2E — standalone shell chrome + portal "/browser" embed.
 *
 * Coverage
 * --------
 *  1. Standalone shell (apps/jbrowse, the Vue rewrite of the old React shell):
 *     header wordmark, the three-option assembly <select>, the locus-search
 *     placeholder, the share + fullscreen controls, the locus/active-tracks/
 *     assembly summary bar, the ruler + track container, and the footer text.
 *  2. Portal embed (apps/web "/browser"): the JBrowse <iframe> is mounted with
 *     the portal origin, the postMessage bridge reaches its "ready" state
 *     (observable as [data-testid="browser-ready"]), and the frame document is
 *     the real Vue shell rather than a CSP-blocked / error stub.
 *
 * How to run — requires a DEPLOYED stack (it cannot run in this offline repo)
 * --------------------------------------------------------------------------
 * Prerequisites
 *   - apps/jbrowse built and served at JBROWSE_BASE_URL;
 *   - apps/web built with VITE_JBROWSE_BASE_URL=<JBROWSE_BASE_URL> and a CSP
 *     frame-src that allows that origin, served at PORTAL_BASE_URL;
 *   - the shell origin serves /jbrowse-data with the REAL files its config
 *     references: Wm82_v4.0.fa.gz (+ .fai/.gzi), Wm82_v4.0.chrom.sizes,
 *     variants.vcf.gz (+ .tbi), structural_variants.vcf.gz (+ .tbi),
 *     genes.gff3.gz (+ .tbi), repeats.bb, gc_content.bw and the Trix index
 *     genes.ix / genes.ixx / genes_meta.json. The shell chrome assertions need
 *     only the built app; the ruler/track container assertions see track bodies
 *     report load errors if the data is absent, which is why this suite is a
 *     deployed-stack gate rather than an offline one.
 *   - seeded API releases so the portal /browser page and the shell's
 *     /tracks/jbrowse-config endpoint answer normally (the shell falls back to
 *     its built-in config, but the portal page itself still needs its API).
 *
 * Command (from e2e/):
 *
 *   JBROWSE_BASE_URL=https://jbrowse.soymutdb.test/ \
 *   PORTAL_BASE_URL=https://soymutdb.test/ \
 *     npx playwright test -c playwright-jbrowse.config.ts
 *
 * JBROWSE_BASE_URL gates the standalone tests and PORTAL_BASE_URL gates the
 * embed test; a missing value reports the dependent tests as SKIPPED instead of
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

/** Standalone Vue shell base, e.g. "https://jbrowse.soymutdb.test/". */
const SHELL_BASE_URL =
  process.env.JBROWSE_BASE_URL ?? process.env.SMOKE_JBROWSE_BASE_URL ?? "";

/** Portal base that embeds the shell at /browser. */
const PORTAL_BASE_URL =
  process.env.PORTAL_BASE_URL ?? process.env.SMOKE_BASE_URL ?? "";

/**
 * The three assemblies the shell must offer, in render order. Mirrors
 * apps/jbrowse/src/components/AppHeader.vue.
 */
const ASSEMBLY_OPTIONS = [
  { value: "Wm82v4.0", label: "Wm82 v4.0" },
  { value: "Wm82.a4.v1", label: "Wm82.a4.v1" },
  { value: "Wm82.a2.v1", label: "Wm82.a2.v1" },
] as const;

/** Default active tracks (reference_sequence, gene_models, variants_v4). */
const DEFAULT_ACTIVE_TRACK_COUNT = 3;

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

test.describe("Vue JBrowse shell — standalone chrome", () => {
  test("renders the wordmark, assembly select, locus search, actions and footer", async ({
    page,
  }) => {
    test.skip(!SHELL_BASE_URL, "set JBROWSE_BASE_URL to the deployed Vue JBrowse shell");
    await gotoShell(page);

    const header = page.locator("header");
    await expect(header.getByText("SoyMutDB", { exact: true })).toBeVisible();
    await expect(header.getByText("Genome Browser", { exact: true })).toBeVisible();

    // The assembly <select> carries exactly the three real assembly namespaces.
    const assembly = page.getByLabel("Select reference assembly");
    await expect(assembly).toBeVisible();
    await expect(assembly).toHaveValue(ASSEMBLY_OPTIONS[0].value);
    await expect(assembly.locator("option")).toHaveCount(ASSEMBLY_OPTIONS.length);
    expect(
      await assembly.locator("option").evaluateAll((options) =>
        options.map((option) => ({
          value: (option as HTMLOptionElement).value,
          label: (option.textContent ?? "").trim(),
        })),
      ),
    ).toEqual(ASSEMBLY_OPTIONS.map(({ value, label }) => ({ value, label })));

    // Locus search: the placeholder is the documented input contract.
    await expect(page.getByPlaceholder("chr01:1-1000000 or gene ID")).toBeVisible();
    await expect(page.getByLabel("Genomic location or gene search")).toBeVisible();

    // Share + fullscreen controls are icon buttons, so they are asserted by
    // their accessible name (and title) rather than by an icon.
    const share = page.getByRole("button", { name: "Share current view" });
    await expect(share).toBeVisible();
    await expect(share).toHaveAttribute("title", "Share this view");
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
    test.skip(!SHELL_BASE_URL, "set JBROWSE_BASE_URL to the deployed Vue JBrowse shell");
    await gotoShell(page);

    const header = page.locator("header");
    await expect(header.getByText("No location selected")).toBeVisible();
    await expect(
      header.getByText(DEFAULT_ACTIVE_TRACK_COUNT + " active tracks"),
    ).toBeVisible();
    await expect(header.getByText("Assembly: Wm82v4.0")).toBeVisible();
  });

  test("a deep link restores the locus into the search box and summary bar", async ({
    page,
  }) => {
    test.skip(!SHELL_BASE_URL, "set JBROWSE_BASE_URL to the deployed Vue JBrowse shell");
    await gotoShell(page, "?locus=chr01:1-1000");

    await expect(page.getByPlaceholder("chr01:1-1000000 or gene ID")).toHaveValue(
      "chr01:1-1000",
    );
    await expect(page.locator("header").getByText("chr01:1-1000")).toBeVisible();
  });

  test("renders the genome ruler and track container", async ({ page }) => {
    test.skip(!SHELL_BASE_URL, "set JBROWSE_BASE_URL to the deployed Vue JBrowse shell");
    await gotoShell(page);

    await expect(page.locator("main.jbrowse-container")).toBeVisible();
    await expect(page.getByTestId("genome-ruler")).toBeVisible();
    await expect(page.getByTestId("genome-tracks")).toBeVisible();
    await expect(page.getByTestId("genome-ruler")).toContainText("chr01");
  });
});

test.describe("Portal /browser — JBrowse iframe embed", () => {
  test("mounts the shell iframe and reaches the bridge ready state", async ({ page }) => {
    test.skip(!PORTAL_BASE_URL, "set PORTAL_BASE_URL to the deployed portal");

    // Reuse the shared SPA handoff helper: the portal's prerendered markup is
    // inert until Vue commits, so interacting before data-app-ready is unsafe.
    await gotoReady(page, underBase(PORTAL_BASE_URL, "browser"));

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

    // Prove the frame document is the real Vue shell, not a blocked stub.
    await expect(
      page
        .frameLocator('[data-testid="browser-iframe"]')
        .getByText("SoyMutDB", { exact: true }),
    ).toBeVisible({ timeout: 15_000 });
  });
});
