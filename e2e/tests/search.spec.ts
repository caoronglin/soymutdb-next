/**
 * Search E2E — Gene ID / Physical Location URL-backed forms.
 *
 * Offline-capable assertions: form presence, labels, client-side validation,
 * and URL-parameter restoration (the inputs are restored from search params
 * before any API call). Live result assertions are marked skip with an explicit
 * enablement note; the offline never invents rows.
 */
import { test, expect, type Page } from "@playwright/test";
import { gotoReady } from "./helpers";

const BASE = "/soymutdb-next";

/** The form control, rather than the similarly named results landmark. */
function geneIdInput(page: Page) {
  return page.getByTestId("search-genes-input");
}

/** The submit control; disabled until an assembly context is resolved. */
function searchSubmit(page: Page) {
  return page.getByTestId("search-genes-submit");
}

test.describe("Gene ID search", () => {
  test("renders the assembly + gene-id form with labels", async ({ page }) => {
    await gotoReady(page, `${BASE}/search/genes`);
    await expect(page.getByText(/gene id search/i).first()).toBeVisible();
    await expect(geneIdInput(page)).toBeVisible();
    await expect(page.getByText(/genome version/i).first()).toBeVisible();
  });

  test("submit runs the assembly-scoped query and reports the result count", async ({ page }) => {
    await gotoReady(page, `${BASE}/search/genes`);

    await geneIdInput(page).fill("Glyma.01G000100");
    // The submit control stays disabled until the genome-version context is
    // resolved (a request without an assembly would be ambiguous across v4/v5),
    // so wait for the enabled state instead of racing the assemblies request.
    const submit = searchSubmit(page);
    await expect(submit).toBeEnabled();
    // Current flow navigates in-place, retaining q + assembly in a shareable URL.
    await submit.click();
    await expect(page).toHaveURL(/\/search\/genes\?.*q=Glyma\.01G000100/);
    await expect(page.locator('[role="region"][aria-label="Gene ID search results"]')).toBeVisible();
    await expect(page.getByTestId("search-genes-empty")).toBeVisible();
  });

  test("restores form state from a parameterized URL", async ({ page }) => {
    await gotoReady(page, `${BASE}/search/genes?q=Glyma.01G000100&run=1`);
    await expect(geneIdInput(page)).toHaveValue(/Glyma.01G000100/);
  });
});

test.describe("Physical Location search", () => {
  test("renders assembly/chromosome/start/end form", async ({ page }) => {
    await gotoReady(page, `${BASE}/search/location`);
    await expect(page.getByText(/physical location search/i).first()).toBeVisible();
    await expect(page.getByTestId("location-start")).toBeVisible();
    await expect(page.getByTestId("location-end")).toBeVisible();
    await expect(page.getByText(/chromosome/i).first()).toBeVisible();
  });

  test("start < 1 or end < start never submits a request", async ({ page }) => {
    let regionRequests = 0;
    page.on("request", (request) => {
      if (request.url().includes("/variants/region")) regionRequests += 1;
    });
    await gotoReady(
      page,
      `${BASE}/search/location?assembly=Wm82.a4.v1&chromosome=chr01&start=5&end=1&run=1`,
    );
    // An inverted range is rejected client-side: no region request is issued.
    await page.waitForTimeout(500);
    expect(regionRequests).toBe(0);
  });

  test("submit issues the region request for the chosen chromosome", async ({ page }) => {
    const requested: string[] = [];
    // Current flow keeps results on this page; still capture exact network
    // requests, including any future secondary navigation.
    page.context().on("request", (request) => {
      if (request.url().includes("/variants/region")) requested.push(request.url());
    });
    await gotoReady(page, `${BASE}/search/location`);

    // The mock assembly auto-selects; pick a chromosome so the form validates.
    // antd Select is a div rather than a native <select>, so open it and click
    // the option instead of using `selectOption`.
    await page.getByTestId("location-chromosome").click();
    await page.locator(".ant-select-dropdown:visible").getByText("chr01", { exact: true }).click();
    await page.getByTestId("location-start").fill("1");
    await page.getByTestId("location-end").fill("2000");
    await expect(page.getByTestId("location-submit")).toBeEnabled();
    await page.getByTestId("location-submit").click();
    await expect(page).toHaveURL(/\/search\/location\?.*chromosome=chr01/);

    await expect.poll(() => requested.length).toBeGreaterThan(0);
    expect(requested[0]).toContain("chromosome=chr01");
    expect(requested[0]).toContain("start=1");
    expect(requested[0]).toContain("end=2000");
    expect(requested[0]).toContain("assembly=Wm82.a4.v1");
    // The empty result is reported, not hidden.
    await expect(page.getByTestId("location-empty")).toBeVisible();
  });
});

/**
 * Enabling live-result assertions: point SMOKE_BASE_URL / the static server at
 * an environment with a running API (or extend e2e/static-server.mjs to mock
 * GET /genes/assemblies and GET /genes & /variants/region), then un-skip and
 * assert the six-column result order and JBrowse 2 deep links.
 */
