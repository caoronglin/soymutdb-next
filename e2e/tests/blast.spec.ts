/**
 * BLAST E2E — full form at /blast, /search/blast compatibility redirect,
 * FASTA validation, and result cross-links.
 *
 * The full form renders offline (no databases → empty select + disabled/submit
 * guard). The job-submit and result cross-link assertions require a live
 * backend and are marked skip accordingly.
 */
import { test, expect } from "@playwright/test";

const BASE = "/soymutdb-next";

test.describe("BLAST — form and routing", () => {
  test("/blast renders the full form", async ({ page }) => {
    await page.goto(`${BASE}/blast`);
    await expect(page.getByText(/blast/i).first()).toBeVisible();
    // Program/FASTA fields: the form has a program selector and sequence area.
    await expect(page.getByText(/blastn/i).first()).toBeVisible();
    await expect(page.getByLabel(/sequence/i, { exact: false })).toBeVisible();
  });

  test("/search/blast redirects to /blast", async ({ page }) => {
    await page.goto(`${BASE}/search/blast`);
    await page.waitForURL(/\/blast/, { timeout: 15_000 });
    expect(page.url()).toContain("/blast");
  });

  test("empty FASTA is rejected client-side", async ({ page }) => {
    await page.goto(`${BASE}/blast`);
    // Submit without a sequence → no job is created; an error state surfaces.
    const submit = page.getByRole("button", { name: /submit|run blast/i });
    await submit.click();
    // The sequence validation message appears (min 10 chars) instead of a job.
    await expect(page.getByText(/at least 10 characters/i)).toBeVisible();
  });
});

test.describe("BLAST — live results (requires backend)", () => {
  test.skip("completed job exposes JBrowse 2 + gene-search cross links", async ({ page }) => {
    // Requires a live backend: submit a job, wait for completion, then assert
    // the hits table actions (JBrowse 2 deep link + "Gene search" → /search/genes?q=).
    await page.goto(`${BASE}/blast`);
    await expect(page.getByText(/jbrowse 2|gene search/i).first()).toBeVisible();
  });
});
