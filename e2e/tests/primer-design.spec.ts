/**
 * Primer-design page E2E — local, offline (no backend required).
 *
 * Covered flows (pure-frontend heuristic design):
 *   1. Paste mode — sequence input → results table (pair rows, Tm/GC/
 *      amplicon/score columns) → per-sequence copy to clipboard.
 *   2. Genome mode — assembly/chromosome/start/end form → seqfetch mock
 *      (e2e/static-server.mjs) → results → Gbrowse cross-link opens the
 *      browser with assembly+locus.
 *   3. Validation — empty paste shows the required-field error.
 *
 * Target: local static server at /soymutdb-next/ (playwright-primer.config.ts).
 */
import { test, expect, type Page } from "@playwright/test";

const MOCK_TEMPLATE =
  "ACGTACGTACGTACGTACGT".repeat(15); // GC-balanced 300 bp — yields valid pairs

const BASE = "/soymutdb-next";

/** Switch the page to "paste sequence" mode and fill the textarea. */
async function switchToPasteMode(page: Page, sequence: string): Promise<void> {
  await page.getByRole("button", { name: /paste sequence/i }).click();
  await page.getByRole("textbox").fill(sequence);
}

test.describe("primer design — paste mode", () => {
  test("designs pairs from a pasted sequence and shows the results table", async ({
    page,
  }) => {
    await page.goto(`${BASE}/search/primer`);
    await expect(page.getByText(/primer design/i).first()).toBeVisible();

    await switchToPasteMode(page, `>seq1\n${MOCK_TEMPLATE}`);
    await page.getByRole("button", { name: /design primers/i }).click();

    // Results card with at least one pair (F1/R1).
    await expect(page.getByText("F1/R1")).toBeVisible({ timeout: 15_000 });
    const rows = page.locator("table tbody tr");
    expect(await rows.count()).toBeGreaterThanOrEqual(1);
    expect(await rows.count()).toBeLessThanOrEqual(3);

    // Column content sanity: Tm and GC percentages rendered.
    const firstRow = rows.first();
    await expect(firstRow.getByText(/%$/)).toBeVisible();
    await expect(firstRow.getByText(/bp$/)).toBeVisible();
  });

  test("copies a primer sequence to the clipboard", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"], {
      origin: "http://localhost:4173",
    });
    await page.goto(`${BASE}/search/primer`);
    await switchToPasteMode(page, MOCK_TEMPLATE);
    await page.getByRole("button", { name: /design primers/i }).click();

    await expect(page.getByText("F1/R1")).toBeVisible({ timeout: 15_000 });
    const forwardSeq = await page
      .locator("table tbody tr")
      .first()
      .locator("code")
      .first()
      .innerText();

    await page
      .locator("table tbody tr")
      .first()
      .getByRole("button", { name: /copy sequence/i })
      .first()
      .click();

    await expect(page.getByText(/sequence copied/i)).toBeVisible();
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    expect(clip).toBe(forwardSeq.trim());
  });

  test("rejects an empty paste with the required-field error", async ({ page }) => {
    await page.goto(`${BASE}/search/primer`);
    await switchToPasteMode(page, "");
    await page.getByRole("button", { name: /design primers/i }).click();
    await expect(page.getByText(/paste a sequence/i)).toBeVisible();
  });
});

test.describe("primer design — genome mode (seqfetch mock)", () => {
  test("extracts a region, designs pairs and opens Gbrowse with locus", async ({
    page,
  }) => {
    await page.goto(`${BASE}/search/primer`);
    await expect(page.getByText(/primer design/i).first()).toBeVisible();

    // "From genome" mode is the default; fill the region form.
    await page.getByLabel(/chromosome/i).click();
    await page.getByTitle("chr01").click();
    await page.getByLabel(/^start$/i).fill("1");
    await page.getByLabel(/^end$/i).fill("300");
    await page.getByRole("button", { name: /design primers/i }).click();

    // Mock seqfetch returns the 300 bp template → pairs appear.
    await expect(page.getByText("F1/R1")).toBeVisible({ timeout: 15_000 });

    // Gbrowse cross-link: window.open stub captures the target URL.
    await page.addInitScript(() => {
      window.open = (url: string) => {
        (window as unknown as { __openedUrl: string }).__openedUrl = url;
        return null;
      };
    });
    await page.reload();
    // Re-run the search after the reload (page state resets).
    await page.getByLabel(/chromosome/i).click();
    await page.getByTitle("chr01").click();
    await page.getByLabel(/^start$/i).fill("1");
    await page.getByLabel(/^end$/i).fill("300");
    await page.getByRole("button", { name: /design primers/i }).click();
    await expect(page.getByText("F1/R1")).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: /gbrowse/i }).first().click();
    const openedUrl = await page.evaluate(
      () => (window as unknown as { __openedUrl: string }).__openedUrl,
    );
    expect(openedUrl).toContain("/browser?assembly=");
    expect(openedUrl).toContain("&locus=chr01:1-300");
  });
});
