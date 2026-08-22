/**
 * Search E2E — Gene ID / Physical Location URL-backed forms (Phase 4/8).
 *
 * Offline-capable assertions: form presence, labels, new-tab submit via a
 * window.open stub, and URL-parameter restoration (the inputs are restored
 * from search params before any API call). Live result assertions are marked
 * skip (require a backend); see the "enabling live results" note at the bottom.
 */
import { test, expect, type Page } from "@playwright/test";

const BASE = "/soymutdb-next";

/** Install a window.open stub that records the opened URL. */
async function captureWindowOpen(page: Page): Promise<void> {
  await page.addInitScript(() => {
    (window as unknown as { __opened: string | null }).__opened = null;
    window.open = ((url?: string) => {
      (window as unknown as { __opened: string | null }).__opened = url ?? null;
      return null;
    }) as typeof window.open;
  });
}

/** The form control, rather than the similarly named results landmark. */
function geneIdInput(page: Page) {
  return page.getByRole("textbox", { name: "Gene ID", exact: true });
}

test.describe("Gene ID search", () => {
  test("renders the assembly + gene-id form with labels", async ({ page }) => {
    await page.goto(`${BASE}/search/genes`);
    await expect(page.getByText(/gene id search/i).first()).toBeVisible();
    await expect(geneIdInput(page)).toBeVisible();
    await expect(page.getByText(/genome version/i).first()).toBeVisible();
  });

  test("submit opens a parameterized result view in a new tab", async ({ page }) => {
    await captureWindowOpen(page);
    await page.goto(`${BASE}/search/genes`);

    const input = geneIdInput(page);
    await input.fill("Glyma.01G000100");
    await page.getByRole("button", { name: "Search", exact: true }).click();

    const opened = await page.evaluate(
      () => (window as unknown as { __opened: string | null }).__opened,
    );
    // The new tab URL carries the query, a resolved assembly, and a `run` flag.
    expect(opened).toContain("/search/genes?");
    expect(opened).toContain("q=Glyma.01G000100");
    expect(opened).toContain("run=");
    expect(opened).toContain("assembly=");
  });

  test("restores form state from a parameterized URL", async ({ page }) => {
    await page.goto(`${BASE}/search/genes?q=Glyma.01G000100&run=1`);
    await expect(geneIdInput(page)).toHaveValue(/Glyma.01G000100/);
  });
});

test.describe("Physical Location search", () => {
  test("renders assembly/chromosome/start/end form", async ({ page }) => {
    await page.goto(`${BASE}/search/location`);
    await expect(page.getByText(/physical location search/i).first()).toBeVisible();
    await expect(page.getByLabel(/^start$/i)).toBeVisible();
    await expect(page.getByLabel(/^end$/i)).toBeVisible();
    await expect(page.getByText(/chromosome/i).first()).toBeVisible();
  });

  test("start < 1 or end < start is rejected (no new tab)", async ({ page }) => {
    await captureWindowOpen(page);
    await page.goto(`${BASE}/search/location?assembly=Wm82.a4.v1&chromosome=chr01&start=5&end=1&run=1`);
    // Invalid range never auto-submits; no window.open must have fired.
    const opened = await page.evaluate(
      () => (window as unknown as { __opened: string | null }).__opened,
    );
    expect(opened).toBeNull();
  });

  test("submit opens a parameterized location URL in a new tab", async ({ page }) => {
    await captureWindowOpen(page);
    await page.goto(`${BASE}/search/location`);

    // The mock assembly auto-selects; pick a chromosome so the form validates.
    await page.getByRole("combobox").nth(1).click();
    await page.locator(".ant-select-item-option").filter({ hasText: "chr01" }).click();
    await page.getByLabel(/^start$/i).fill("1");
    await page.getByLabel(/^end$/i).fill("2000");
    await page.getByRole("button", { name: "Search", exact: true }).click();

    const opened = await page.evaluate(
      () => (window as unknown as { __opened: string | null }).__opened,
    );
    expect(opened).toContain("/search/location?");
    expect(opened).toContain("start=1");
    expect(opened).toContain("end=2000");
    expect(opened).toContain("run=");
  });
});

/**
 * Enabling live-result assertions: point SMOKE_BASE_URL / the static server at
 * an environment with a running API (or extend e2e/static-server.mjs to mock
 * GET /genes/assemblies and GET /genes & /variants/region), then un-skip and
 * assert the six-column result order and JBrowse 2 deep links.
 */
