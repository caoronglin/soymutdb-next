/**
 * Primer-design page E2E — local, offline (no backend required).
 *
 * Targeted at the React implementation (`apps/web/src/routes/search/primer.tsx`).
 * The previous version of this spec was written against the retired Vue UI
 * (`/design primers/` button, F1/R1 rows with a different table); the button is
 * now "Submit primer design" and the results table is the antd Table described
 * below. Covered flows:
 *   1. Paste mode — sequence input -> results table (pair rows, Tm/GC/
 *      amplicon/score columns) -> per-sequence copy to clipboard.
 *   2. Genome mode — assembly/chromosome/start/end form -> deterministic
 *      `mockPrimerApis` (the artifact bakes an absolute API origin, so the
 *      static server's same-origin mocks cannot answer) -> results -> Gbrowse
 *      cross-link opens the browser with assembly+locus.
 *   3. Validation — empty paste shows the required-field error.
 *
 * Target: local static server at the origin root (playwright-primer.config.ts),
 * serving the base-`/` `apps/web/dist/external` artifact.
 */
import { test, expect, type Page } from "@playwright/test";

import { mockPrimerApis, waitForAppReady } from "./helpers";

// Deterministic API per page: the artifact's data layer must not depend on the
// static-server fixtures, and a cross-origin/absolute base would bypass them.
// NOTE: the helper deliberately does NOT mock /releases/active — a fabricated
// release changes the assembly query context and breaks genome mode.
test.beforeEach(async ({ page }) => {
  await mockPrimerApis(page);
});

const MOCK_TEMPLATE =
  "ACGTACGTACGTACGTACGT".repeat(15); // GC-balanced 300 bp — yields valid pairs

// Empty for the standard-base sweep; set E2E_BASE_PATH for a
// sub-path deployment artifact.
const BASE = (process.env.E2E_BASE_PATH ?? "").replace(/\/+$/, "");
const SUBMIT = /submit primer design/i;

/** Switch the page to "paste sequence" mode and fill its textarea. */
async function switchToPasteMode(page: Page, sequence: string): Promise<void> {
  await page.getByRole("button", { name: /paste sequence/i }).click();
  await page.locator("textarea").fill(sequence);
}

async function fillRegionForm(page: Page): Promise<void> {
  // "From genome" mode is the default. The assembly field is populated by an
  // async assemblies query, so submitting before it settles leaves
  // `assemblyName` undefined and the page rejects the region as incomplete.
  // Wait for the default assembly to be selected before touching the rest.
  await expect(page.getByText("Wm82.a4.v1").first()).toBeVisible();

  await page.getByLabel(/^chromosome$/i).click();
  await page.getByText("chr01", { exact: true }).last().click();
  await page.getByLabel(/^start$/i).fill("1");
  await page.getByLabel(/^end$/i).fill("300");
}

test.describe("primer design — paste mode", () => {
  test("designs pairs from a pasted sequence and shows the results table", async ({
    page,
  }) => {
    await page.goto(`${BASE}/search/primer`);
    await waitForAppReady(page);
    await expect(page.getByText(/primer design/i).first()).toBeVisible();

    await switchToPasteMode(page, `>seq1\n${MOCK_TEMPLATE}`);
    await page.getByRole("button", { name: SUBMIT }).click();

    // Results table with at least one pair (F1/R1).
    await expect(page.getByText("F1/R1")).toBeVisible({ timeout: 15_000 });
    // antd renders a hidden measure row inside <tbody>; exclude it from the
    // pair count.
    const rows = page.locator("table tbody tr:not(.ant-table-measure-row)");
    expect(await rows.count()).toBeGreaterThanOrEqual(1);
    expect(await rows.count()).toBeLessThanOrEqual(3);

    // Column content sanity: GC percentages and amplicon lengths render.
    const firstRow = rows.first();
    await expect(firstRow.getByText(/%$/).first()).toBeVisible();
    await expect(firstRow.getByText(/bp$/).first()).toBeVisible();
  });

  test("copies a primer sequence to the clipboard", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"], {
      origin: "http://localhost:4173",
    });
    await page.goto(`${BASE}/search/primer`);
    await switchToPasteMode(page, MOCK_TEMPLATE);
    await page.getByRole("button", { name: SUBMIT }).click();

    await expect(page.getByText("F1/R1")).toBeVisible({ timeout: 15_000 });
    const forwardSeq = await page
      .locator("table tbody tr:not(.ant-table-measure-row)")
      .first()
      .locator("code")
      .first()
      .innerText();

    await page
      .locator("table tbody tr:not(.ant-table-measure-row)")
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
    await page.getByRole("button", { name: SUBMIT }).click();
    await expect(page.getByText("Please paste a sequence", { exact: true })).toBeVisible();
  });
});

test.describe("primer design — genome mode (seqfetch mock)", () => {
  test("extracts a region, designs pairs and opens Gbrowse with locus", async ({
    page,
  }) => {
    await page.goto(`${BASE}/search/primer`);
    await expect(page.getByText(/primer design/i).first()).toBeVisible();

    // Install the window.open capture before the first submit so the
    // Gbrowse action can be asserted without a deployed browser bundle.
    await page.addInitScript(() => {
      window.open = (url: string) => {
        (window as unknown as { __openedUrl: string }).__openedUrl = url;
        return null;
      };
    });
    await page.reload();
    await waitForAppReady(page);
    await expect(page.getByText(/primer design/i).first()).toBeVisible();

    await fillRegionForm(page);
    await page.getByRole("button", { name: SUBMIT }).click();

    // Mock seqfetch returns the 300 bp template -> pairs appear.
    await expect(page.getByText("F1/R1")).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: /jbrowse 2/i }).first().click();
    const openedUrl = await page.evaluate(
      () => (window as unknown as { __openedUrl: string }).__openedUrl,
    );
    expect(openedUrl).toContain("/browser?assembly=");
    expect(openedUrl).toContain("locus=chr01%3A1-300");
  });
});
