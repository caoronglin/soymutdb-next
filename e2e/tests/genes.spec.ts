/**
 * Genes search E2E — six-column result order + JBrowse 2 deep link.
 *
 * The gene search table renders only after a submitted/auto-run query with an
 * assembly context. e2e/static-server.mjs returns an empty envelope by default,
 * so the offline suite asserts the empty state. The JBrowse 2 deep-link test is
 * gated on a real target: either the opt-in offline fixture
 * (GENES_JBROWSE_FIXTURE=1, same static server) or a live stack query
 * (GENES_JBROWSE_QUERY=<gene id>). That is a conditional skip with the concrete
 * missing prerequisite, never a compile-time no-op.
 */
import { test, expect } from "@playwright/test";
import { gotoReady } from "./helpers";

const BASE = "/soymutdb-next";

/** Opt-in deterministic offline fixture served by e2e/static-server.mjs. */
const JBROWSE_FIXTURE_ENABLED = process.env.GENES_JBROWSE_FIXTURE === "1";
/** Deterministic fixture query; keep in step with e2e/static-server.mjs. */
const JBROWSE_FIXTURE_QUERY = "SMDB-E2E-GENE-1";
/** Live-stack query override (a gene id the target actually serves). */
const JBROWSE_LIVE_QUERY = (process.env.GENES_JBROWSE_QUERY ?? "").trim();
/** The query this run can resolve rows for, or "" when no target is available. */
const JBROWSE_QUERY = JBROWSE_FIXTURE_ENABLED ? JBROWSE_FIXTURE_QUERY : JBROWSE_LIVE_QUERY;

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
    await expect(page.getByTestId("search-gene-row")).toHaveCount(0);
  });

  test("JBrowse 2 action opens an assembly-scoped locus deep link in a new tab", async ({
    page,
  }) => {
    // Conditional, not unconditional: the target must return a gene row with a
    // JBrowse action. Skip only when neither the offline fixture nor a live
    // stack query was supplied, and name the missing prerequisite.
    test.skip(
      !JBROWSE_QUERY,
      "set GENES_JBROWSE_FIXTURE=1 (offline fixture in e2e/static-server.mjs) " +
        "or GENES_JBROWSE_QUERY=<gene id> (live stack that returns rows) " +
        "to exercise the JBrowse 2 deep link",
    );

    await gotoReady(
      page,
      `${BASE}/search/genes?q=${encodeURIComponent(JBROWSE_QUERY)}&run=1`,
    );

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
    expect(assembly, "the deep link must carry the assembly context").toBeTruthy();
    expect(locus, "the deep link must carry a chromosome:start-end locus").toMatch(
      /^[^:\s]+:\d+-\d+$/,
    );

    if (JBROWSE_FIXTURE_ENABLED) {
      // The fixture pins these values, so assert them exactly when offline.
      expect(assembly).toBe("Wm82.a4.v1");
      expect(locus).toBe("chr01:12345-12345");
    }

    // Clicking opens the same deep link in a new tab.
    const [popup] = await Promise.all([page.waitForEvent("popup"), link.click()]);
    await popup.waitForURL((url) => url.pathname === "/browser", { timeout: 10_000 });
    const popupUrl = new URL(popup.url());
    expect(popupUrl.searchParams.get("assembly")).toBe(assembly);
    expect(popupUrl.searchParams.get("loc")).toBe(locus);
    await popup.close();
  });
});
