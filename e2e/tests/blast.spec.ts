/**
 * BLAST E2E — full form at /blast, /search/blast compatibility redirect,
 * FASTA validation, and result cross-links.
 *
 * The full form renders offline (no databases → empty select + disabled/submit
 * guard). The job-submit and result cross-link assertions require a live
 * backend and are marked skip accordingly.
 */
import { test, expect } from "@playwright/test";
import { gotoReady, waitForAppReady } from "./helpers";

const BASE = "/soymutdb-next";

test.describe("BLAST — form and routing", () => {
  test("/blast renders the full form", async ({ page }) => {
    await gotoReady(page, `${BASE}/blast`);
    await expect(page.getByText(/blast/i).first()).toBeVisible();
    // Program/FASTA fields: the form has a program selector and sequence area.
    await expect(page.getByText(/blastn/i).first()).toBeVisible();
    // "Reference sequence type" also matches /sequence/i, so target the query
    // textarea by its exact label ("Input Sequence").
    await expect(page.getByRole("textbox", { name: "Input Sequence" })).toBeVisible();
  });

  test("/search/blast redirects to /blast", async ({ page }) => {
    await page.goto(`${BASE}/search/blast`);
    await page.waitForURL(/\/blast/, { timeout: 15_000 });
    await waitForAppReady(page);
    expect(page.url()).toContain("/blast");
  });

  test("empty FASTA is rejected client-side", async ({ page }) => {
    await gotoReady(page, `${BASE}/blast`);
    // The submit control is labelled "BLAST" (blast.submit) — there is no
    // "Submit" / "Run BLAST" label in the current i18n contract.
    const submit = page.getByRole("button", { name: "BLAST", exact: true });
    await submit.click();
    // The sequence validation message appears (min 10 chars) instead of a job.
    await expect(page.getByText(/at least 10 characters/i)).toBeVisible();
  });
});

test.describe("BLAST — live results (requires backend)", () => {
  test.skip("completed job exposes JBrowse 2 + gene-search cross links", async ({ page }) => {
    // Requires a live backend: submit a job, wait for completion, then assert
    // the hits table actions (JBrowse 2 deep link + "Gene search" → /search/genes?q=).
    await gotoReady(page, `${BASE}/blast`);
    await expect(page.getByText(/jbrowse 2|gene search/i).first()).toBeVisible();
  });
});
