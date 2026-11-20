/**
 * Genes search E2E — source mutation-site result table + JBrowse 2 deep link.
 *
 * The result table renders only after a submitted/auto-run query. The default
 * static server returns an empty envelope, so the empty-state test asserts the
 * honest "no rows" answer; the deep-link test installs deterministic in-browser
 * API mocks (helpers.mockEntityApis) so a real row exists and the JBrowse action
 * can be exercised end to end — no unconditional `test.skip`.
 */
import { test, expect } from "@playwright/test";
import { gotoReady, mockEntityApis, MOCK_PREVIEW_ASSEMBLY, MOCK_GENE_ID, MOCK_RELEASE_ID } from "./helpers";

// Empty for the standard-base sweep; set E2E_BASE_PATH for a
// sub-path deployment artifact.
const BASE = (process.env.E2E_BASE_PATH ?? "").replace(/\/+$/, "");

test.describe("genes — form and URL state", () => {
  test("gene ID form restores q from URL", async ({ page }) => {
    await gotoReady(page, `${BASE}/search/genes?q=Glyma.01G000100`);
    await expect(page.getByTestId("search-genes-input")).toHaveValue(/Glyma.01G000100/);
  });
});

test.describe("genes — result column order", () => {
  test("renders source mutation fields followed by assembly and JBrowse 2", async ({ page }) => {
    // The e2e/static-server.mjs mock returns one default assembly, the built-in
    // column template, and an empty gene list — so the result table renders its
    // configured column headers offline without inventing rows.
    await gotoReady(page, `${BASE}/search/genes?q=Glyma.01G000100&assembly=${encodeURIComponent(MOCK_PREVIEW_ASSEMBLY.name)}&run=1`);
    const headers = page.getByTestId("search-genes-table").locator("thead th");
    await expect(headers.first()).toBeVisible({ timeout: 15_000 });
    // The config pins `locale: "en-US"` on purpose (see
    // playwright-public.config.ts): the specs assert the English catalog so
    // host detection cannot make the result depend on the machine. The first
    // eight headers used to be hard-coded Chinese before the i18n migration;
    // they are now translated from the English catalog like the last two.
    expect((await headers.allTextContents()).map((header) => header.trim())).toEqual([
      "Search a gene",
      "Mutant system (parent + position)",
      "Chromosome",
      "Position",
      "Confidence",
      "Gene ID",
      "Feature",
      "Available",
      "Genome version",
      "JBrowse 2",
    ]);
  });

  test("renders no row when the API returns none", async ({ page }) => {
    await gotoReady(page, `${BASE}/search/genes?q=Glyma.01G000100&assembly=${encodeURIComponent(MOCK_PREVIEW_ASSEMBLY.name)}&run=1`);
    await expect(page.getByTestId("search-genes-empty")).toBeVisible();
    // The empty-state answer must come from a rendered (header-only) results
    // table with zero data rows. `gene-row` is the per-row testid the table
    // actually emits (apps/web/src/routes/search/genes.tsx); asserting its
    // absence is a real negative check. The previous `configurable-row` testid
    // is not emitted anywhere in apps/web/src, so that assertion could never
    // fail and proved nothing.
    await expect(page.getByTestId("search-genes-table")).toBeVisible();
    await expect(page.getByTestId("gene-row")).toHaveCount(0);
  });

  test("shows an error rather than a fabricated empty result when source preview fails", async ({ page }) => {
    await page.route("**/preview/test-data/mutation-sites/by-gene?*", async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "SERVICE_UNAVAILABLE", message: "E2E backend offline" } }),
      });
    });
    await gotoReady(page, `${BASE}/search/genes?q=Glyma.01G000100&assembly=${encodeURIComponent(MOCK_PREVIEW_ASSEMBLY.name)}&run=1`);
    const region = page.getByRole("region", { name: "Gene ID search results" });
    await expect(region.getByRole("alert")).toBeVisible();
    await expect(page.getByTestId("search-genes-empty")).toHaveCount(0);
  });

  test("JBrowse 2 action opens an assembly-scoped locus deep link", async ({ page }) => {
    // Deterministic offline data: one gene row carrying assembly/coordinates, so
    // the action is guaranteed to exist and its contract can be asserted exactly.
    await mockEntityApis(page, { assembly: MOCK_PREVIEW_ASSEMBLY });
    await gotoReady(page, `${BASE}/search/genes?q=${encodeURIComponent(MOCK_GENE_ID)}&assembly=${encodeURIComponent(MOCK_PREVIEW_ASSEMBLY.name)}&run=1`);

    // The action carries a stable `jbrowse-link-<index>` handle; target it
    // precisely so the assertion cannot pass vacuously.
    const link = page.getByTestId(/^jbrowse-link-/).first();
    await expect(link).toBeVisible({ timeout: 15_000 });

    // ReleaseScopeProvider resolves /releases/active asynchronously and then
    // pins the active release for links. Never assert on a transient
    // assembly-only URL or bypass the browser context safety gate.
    await expect.poll(async () => {
      const current = await link.getAttribute("href");
      return new URL(current ?? "/", "http://e2e.invalid").searchParams.get("release");
    }).toBe(MOCK_RELEASE_ID);
    const href = await link.getAttribute("href");
    expect(href, "the JBrowse 2 action must be an anchor with an href").toBeTruthy();
    const deepLink = new URL(href as string, "http://e2e.invalid");
    // Base-aware: the artifact is built for a sub-path, so the browser route is
    // `${BASE}/browser` rather than `/browser`.
    expect(deepLink.pathname).toBe(`${BASE}/browser`);
    const assembly = deepLink.searchParams.get("assembly");
    // `locus` is the canonical parameter (browser.tsx accepts `loc` only as a
    // legacy alias), so assert the real contract rather than the alias.
    const locus = deepLink.searchParams.get("locus");
    // DB-CORE-3/4: the deep link must carry the assembly context, never an
    // assembly-less locus that would resolve to another coordinate namespace.
    expect(assembly).toBe(MOCK_PREVIEW_ASSEMBLY.name);
    expect(deepLink.searchParams.get("release")).toBe(MOCK_RELEASE_ID);
    expect(locus).toMatch(/^[^:\s]+:\d+-\d+$/);
    expect(locus).toBe("chr01:100-200");

    // Follow the deep link into the portal browser route and prove the locus is
    // carried into the JBrowse shell URL (the shell iframe itself is not served
    // by the offline static server, so the frame *src* is the contract here).
    // `href` is already base-qualified (`${BASE}/browser?...`), so it must not
    // be prefixed with BASE again.
    await gotoReady(page, href as string);
    await expect(page.getByTestId("browser-locus-input")).toHaveValue("chr01:100-200");
    // The current browser route no longer prints a combined header label.
    // Check the actual route and context guard, then validate the iframe URL
    // itself: this is the data handoff JBrowse receives.
    await expect(page.getByTestId("browser-missing-context")).toHaveCount(0);
    await expect(page).toHaveURL(/assembly=Gmax_880_v6\.0/);
    // TanStack Router may canonicalize a numeric-looking release string as a
    // JSON search value (release=%227%22). Assert the *parsed* release value
    // and independently verify the downstream JBrowse iframe received it.
    await expect.poll(() => {
      const raw = new URL(page.url()).searchParams.get("release");
      if (raw == null) return null;
      try {
        return String(JSON.parse(raw));
      } catch {
        return raw;
      }
    }).toBe(MOCK_RELEASE_ID);
    const frame = page.getByTestId("browser-iframe");
    await expect(frame).toHaveAttribute("src", /assembly=Gmax_880_v6\.0/);
    await expect(frame).toHaveAttribute("src", /locus=chr01%3A100-200/);
    await expect(frame).toHaveAttribute("src", /release=7/);
  });
});
