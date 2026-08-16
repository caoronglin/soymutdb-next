/**
 * Genes search E2E — six-column result order + JBrowse 2 deep link.
 *
 * The result table renders only after a submitted/auto-run query, which
 * requires live assemblies + search data. Offline, the table never renders
 * (no fake data), so the live assertions below are marked skip with an
 * explicit enablement note. The URL-restore + form-presence assertions run
 * offline.
 */
import { test, expect, type Page } from "@playwright/test";

const BASE = "/soymutdb-next";

async function captureWindowOpen(page: Page): Promise<void> {
  await page.addInitScript(() => {
    window.open = ((url?: string) => {
      (window as unknown as { __opened: string | null }).__opened = url ?? null;
      return null;
    }) as typeof window.open;
  });
}

test.describe("genes — form and URL state", () => {
  test("gene ID form restores q from URL", async ({ page }) => {
    await page.goto(`${BASE}/search/genes?q=Glyma.01G000100`);
    await expect(page.getByLabel(/gene id/i)).toHaveValue(/Glyma.01G000100/);
  });
});

test.describe("genes — result column order", () => {
  test("renders Assembly → Chromosome → Position → Mutation feature → Gene ID → JBrowse 2", async ({ page }) => {
    // The e2e/static-server.mjs mock returns one default assembly + an empty
    // gene list, so the result table renders its column headers offline.
    await page.goto(`${BASE}/search/genes?q=Glyma.01G000100&run=1`);
    await expect(page.locator("table thead th").first()).toBeVisible({ timeout: 15_000 });
    const headers = await page.locator("table thead th").allTextContents();
    expect(headers.map((h) => h.trim())).toEqual([
      "Genome version",
      "Chromosome",
      "Position",
      "Mutation feature",
      "Gene ID",
      "JBrowse 2",
    ]);
  });

  test.skip(
    "JBrowse 2 action opens a locus deep link in a new tab",
    async ({ page }) => {
      await captureWindowOpen(page);
      await page.goto(`${BASE}/search/genes?q=Glyma.01G000100&run=1`);
      const jbrowse = page.getByRole("button", { name: /browser|jbrowse/i }).first();
      await jbrowse.click();
      const opened = await page.evaluate(
        () => (window as unknown as { __opened: string | null }).__opened,
      );
      expect(opened).toMatch(/browser\?assembly=.+&locus=.+:\d+-\d+/);
    },
  );
});
