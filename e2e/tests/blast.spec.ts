/**
 * BLAST E2E — full form at /blast, the /search/blast compatibility route, FASTA
 * validation, and result cross-links.
 *
 * The full form renders offline (no databases → empty select + disabled submit
 * guard). `/search/blast` is a compatibility route that renders the same form:
 * a redirect would break a bookmarked URL's referrer, so the route is served
 * directly instead of bounced. The job-submit and result cross-link assertions
 * require a live backend and are marked skip accordingly.
 */
import { test, expect } from "@playwright/test";
import { gotoReady } from "./helpers";

const BASE = "/soymutdb-next";

test.describe("BLAST — form and routing", () => {
  test("/blast renders the full form", async ({ page }) => {
    await gotoReady(page, `${BASE}/blast`);
    // The title block is an eyebrow label ("BLAST Search") plus a descriptive
    // level-1 heading; assert the rendered structure instead of binding the
    // heading to one i18n string.
    await expect(page.getByText("BLAST Search").first()).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/search sequences/i);
    // The current default is DIAMOND BLASTP; both the selected programme
    // and query input must be visible, regardless of backend availability.
    const programme = page.getByTestId("blast-program");
    // antd Select renders a div rather than an <input>, so assert the rendered
    // selection label instead of an input value.
    await expect(programme).toContainText("BLASTP");
    // "Reference sequence type" also matches /sequence/i, so target the query
    // textarea by its exact label ("Input Sequence").
    await expect(page.getByRole("textbox", { name: "Input Sequence" })).toBeVisible();
  });

  test("/search/blast serves the same form (compatibility route)", async ({ page }) => {
    await gotoReady(page, `${BASE}/search/blast`);
    await expect(page.getByRole("textbox", { name: "Input Sequence" })).toBeVisible();
    await expect(page.getByTestId("blast-program")).toBeVisible();
    await expect(page.getByTestId("blast-database")).toBeVisible();
  });

  test("empty FASTA never reaches the API", async ({ page }) => {
    const submissions: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/blast/jobs") && request.method() === "POST") {
        submissions.push(request.url());
      }
    });
    await gotoReady(page, `${BASE}/blast`);
    // The contract is that an incomplete form never reaches the API. The client
    // rejects it locally through schema/FASTA validation, so assert the absence
    // of a request rather than a particular disabled styling.
    await page.getByTestId("blast-submit").click();
    await page.waitForTimeout(500);
    expect(submissions).toEqual([]);
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
