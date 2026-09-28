/**
 * Genes search E2E — six-column result order + JBrowse 2 deep link.
 *
 * The result table renders only after a submitted/auto-run query. The default
 * static server returns an empty envelope, so the empty-state test asserts the
 * honest "no rows" answer; the deep-link test installs deterministic in-browser
 * API mocks (helpers.mockEntityApis) so a real row exists and the JBrowse action
 * can be exercised end to end — no unconditional `test.skip`.
 */
import { test, expect } from "@playwright/test";
import { gotoReady, mockEntityApis, MOCK_ASSEMBLY, MOCK_GENE_ID } from "./helpers";

const BASE = "/soymutdb-next";

test.describe("genes — form and URL state", () => {
  test("gene ID form restores q from URL", async ({ page }) => {
    await gotoReady(page, `${BASE}/search/genes?q=Glyma.01G000100`);
    await expect(page.getByTestId("search-genes-input")).toHaveValue(/Glyma.01G000100/);
  });
});

test.describe("genes — result column order", () => {
  test("renders Assembly → Chromosome → Position → Mutation feature → Gene ID → JBrowse 2", async ({ page }) => {
    // The e2e/static-server.mjs mock returns one default assembly, the built-in
    // column template, and an empty gene list — so the result table renders its
    // configured column headers offline without inventing rows.
    await gotoReady(page, `${BASE}/search/genes?q=Glyma.01G000100&run=1`);
    const headers = page.getByTestId("search-genes-table").locator("thead th");
    await expect(headers.first()).toBeVisible({ timeout: 15_000 });
    expect((await headers.allTextContents()).map((header) => header.trim())).toEqual([
      "Genome version",
      "Chromosome",
      "Position",
      "Mutation feature",
      "Gene ID",
      "JBrowse 2",
    ]);
  });

  test("renders no row when the API returns none", async ({ page }) => {
    await gotoReady(page, `${BASE}/search/genes?q=Glyma.01G000100&run=1`);
    await expect(page.getByTestId("search-genes-empty")).toBeVisible();
    await expect(page.getByTestId("configurable-row")).toHaveCount(0);
  });

  test("JBrowse 2 action opens an assembly-scoped locus deep link", async ({ page }) => {
    // Deterministic offline data: one gene row carrying assembly/coordinates, so
    // the action is guaranteed to exist and its contract can be asserted exactly.
    await mockEntityApis(page);
    await gotoReady(page, `${BASE}/search/genes?q=${encodeURIComponent(MOCK_GENE_ID)}&run=1`);

    // The action is the row's anchor (ConfigurableTable emits
    // `jbrowse-link-<index>`), not a button; target it precisely so the
    // assertion cannot pass vacuously.
    const link = page.getByTestId(/^jbrowse-link-/).first();
    await expect(link).toBeVisible({ timeout: 15_000 });

    const href = await link.getAttribute("href");
    expect(href, "the JBrowse 2 action must be an anchor with an href").toBeTruthy();
    const deepLink = new URL(href as string, "http://e2e.invalid");
    expect(deepLink.pathname).toBe("/browser");
    const assembly = deepLink.searchParams.get("assembly");
    const locus = deepLink.searchParams.get("loc");
    // DB-CORE-3/4: the deep link must carry the assembly context, never an
    // assembly-less locus that would resolve to another coordinate namespace.
    expect(assembly).toBe(MOCK_ASSEMBLY.name);
    expect(locus).toMatch(/^[^:\s]+:\d+-\d+$/);
    expect(locus).toBe("chr01:100-200");

    // Follow the deep link into the portal browser route and prove the locus is
    // carried into the JBrowse shell URL (the shell iframe itself is not served
    // by the offline static server, so the frame *src* is the contract here).
    await gotoReady(page, `${BASE}${href}`);
    await expect(page.getByTestId("browser-locus-input")).toHaveValue("chr01:100-200");
    // The assembly is echoed in the browser header (the <select> only offers
    // chromosome options, so it is not a reliable assembly assertion).
    await expect(page.getByText(`${MOCK_ASSEMBLY.name} · chr01:100-200`)).toBeVisible();
    const frame = page.getByTestId("browser-iframe");
    await expect(frame).toHaveAttribute("src", /assembly=Wm82\.a4\.v1/);
    await expect(frame).toHaveAttribute("src", /locus=chr01%3A100-200/);
  });
});
