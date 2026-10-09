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
import { gotoReady, mockEntityApis, MOCK_ASSEMBLY, MOCK_GENE_ID, MOCK_RELEASE_ID } from "./helpers";

const BASE = "/soymutdb-next";

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
    await gotoReady(page, `${BASE}/search/genes?q=Glyma.01G000100&run=1`);
    const headers = page.getByTestId("search-genes-table").locator("thead th");
    await expect(headers.first()).toBeVisible({ timeout: 15_000 });
    expect((await headers.allTextContents()).map((header) => header.trim())).toEqual([
      "搜索基因",
      "突变体系（株系母+位置）",
      "染色体号",
      "位点",
      "可信度",
      "基因号",
      "特征",
      "可获得",
      "Genome version",
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
    expect(assembly).toBe(MOCK_ASSEMBLY.name);
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
    // The assembly is echoed in the browser header (the <select> only offers
    // chromosome options, so it is not a reliable assembly assertion).
    await expect(page.getByText(`${MOCK_ASSEMBLY.name} · chr01:100-200`)).toBeVisible();
    const frame = page.getByTestId("browser-iframe");
    await expect(frame).toHaveAttribute("src", /assembly=Wm82\.a4\.v1/);
    await expect(frame).toHaveAttribute("src", /locus=chr01%3A100-200/);
  });
});
