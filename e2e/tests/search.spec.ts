/**
 * Search E2E — Gene ID / Physical Location URL-backed forms.
 *
 * Offline-capable assertions: form presence, labels, client-side validation,
 * and URL-parameter restoration (the inputs are restored from search params
 * before any API call). Live result assertions are marked skip with an explicit
 * enablement note; the offline never invents rows.
 *
 * Assembly identity in a shared link: the canonical identity of a genome
 * version is its stable catalogue id, because a *name* can repeat across
 * versions (v4/v5 both carry "Wm82"). A link assembled by the page therefore
 * carries `assembly=<id>`. A link that still carries a *unique* legacy name
 * stays valid — it is resolved to the same catalogue row instead of being
 * reported as an unknown genome version — and both forms have to select the
 * same assembly and run the same request.
 */
import { test, expect, type Page } from "@playwright/test";
import { gotoReady, MOCK_PREVIEW_ASSEMBLY } from "./helpers";

// Empty for the standard-base sweep; set E2E_BASE_PATH for a
// sub-path deployment artifact.
const BASE = (process.env.E2E_BASE_PATH ?? "").replace(/\/+$/, "");

/** The form control, rather than the similarly named results landmark. */
function geneIdInput(page: Page) {
  return page.getByTestId("search-genes-input");
}

/** The submit control; disabled until an assembly context is resolved. */
function searchSubmit(page: Page) {
  return page.getByTestId("search-genes-submit");
}

/**
 * The unreadable-assembly notice.
 *
 * It is the difference between "the link names a genome version this
 * deployment does not have" and "the link names a genome version". A link
 * that resolves must never show it.
 */
const ASSEMBLY_UNAVAILABLE = "The requested assembly is unavailable; no query was sent.";

/**
 * The source-site preview read for a physical region.
 *
 * The offline server has no such route, and a 404 is an error state that the
 * page reports as such — it must never be presented as "no rows". An empty,
 * validated preview envelope exercises the real success/empty rendering.
 */
async function mockPreviewSites(page: Page): Promise<void> {
  await page.route("**/preview/test-data/mutation-sites?*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        preview: true,
        publication_status: "unpublished",
        coordinate_system: "1-based-inclusive",
        assembly: {
          name: MOCK_PREVIEW_ASSEMBLY.name,
          version: MOCK_PREVIEW_ASSEMBLY.version,
          species: MOCK_PREVIEW_ASSEMBLY.species,
          status: "unpublished",
        },
        annotation_version: "Wm82.a6.v1",
        items: [], total: 0, limit: 1000,
      }),
    });
  });
}

/** The search parameters of the current URL, read exactly. */
function currentParams(page: Page): URLSearchParams {
  return new URL(page.url()).searchParams;
}

/** TanStack may JSON-encode numeric-looking string ids (assembly=%226%22). */
function currentAssemblyParam(page: Page): string | null {
  const raw = currentParams(page).get("assembly");
  if (raw === null) return null;
  try {
    return String(JSON.parse(raw));
  } catch {
    return raw;
  }
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

    // Preview data are pinned to v6, not the default released v4 genome.
    await page.getByTestId("search-genes-assembly").click();
    await page.locator(".ant-select-dropdown:visible .ant-select-item-option")
      .filter({ hasText: MOCK_PREVIEW_ASSEMBLY.name }).first().click();
    await geneIdInput(page).fill("Glyma.01G000100");
    // The submit control stays disabled until the genome-version context is
    // resolved (a request without an assembly would be ambiguous across v4/v5),
    // so wait for the enabled state instead of racing the assemblies request.
    const submit = searchSubmit(page);
    await expect(submit).toBeEnabled();
    // Current flow navigates in-place, retaining q + assembly in a shareable URL.
    await submit.click();
    await expect.poll(() => currentParams(page).get("q")).toBe("Glyma.01G000100");
    // The shared link carries the stable catalogue id of the assembly, not its
    // display name: a name can repeat across genome versions, an id cannot.
    // Read the parameter exactly — a loose "assembly=6" match would also accept
    // "assembly=60".
    expect(currentAssemblyParam(page)).toBe(MOCK_PREVIEW_ASSEMBLY.id);
    expect(["1", "true"]).toContain(currentParams(page).get("run"));
    await expect(page.locator('[role="region"][aria-label="Gene ID search results"]')).toBeVisible();
    await expect(page.getByTestId("search-genes-empty")).toBeVisible();
  });

  test("restores form state from a parameterized URL", async ({ page }) => {
    await gotoReady(page, `${BASE}/search/genes?q=Glyma.01G000100&run=1`);
    await expect(geneIdInput(page)).toHaveValue(/Glyma\.01G000100/);
  });

  test("a legacy assembly-name link still resolves to the same genome version", async ({ page }) => {
    await gotoReady(
      page,
      `${BASE}/search/genes?q=Glyma.01G000100&assembly=${encodeURIComponent(MOCK_PREVIEW_ASSEMBLY.name)}&run=1`,
    );

    // The unique legacy name is resolved to its catalogue row ...
    await expect(page.getByTestId("search-genes-assembly")).toContainText(MOCK_PREVIEW_ASSEMBLY.name);
    // ... and is not reported as an unknown genome version.
    await expect(page.getByText(ASSEMBLY_UNAVAILABLE)).toHaveCount(0);
    // The query therefore runs with the resolved assembly.
    await expect(page.locator('[role="region"][aria-label="Gene ID search results"]')).toBeVisible();
    await expect(page.getByTestId("search-genes-empty")).toBeVisible();
  });

  test("an assembly-id link is accepted and selects the same genome version", async ({ page }) => {
    await gotoReady(
      page,
      `${BASE}/search/genes?q=Glyma.01G000100&assembly=${MOCK_PREVIEW_ASSEMBLY.id}&run=1`,
    );

    await expect(page.getByTestId("search-genes-assembly")).toContainText(MOCK_PREVIEW_ASSEMBLY.name);
    await expect(page.getByText(ASSEMBLY_UNAVAILABLE)).toHaveCount(0);
    await expect(page.locator('[role="region"][aria-label="Gene ID search results"]')).toBeVisible();
    await expect(page.getByTestId("search-genes-empty")).toBeVisible();
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
      if (request.url().includes("/preview/test-data/mutation-sites?")) regionRequests += 1;
    });
    await gotoReady(
      page,
      `${BASE}/search/location?assembly=Wm82.a4.v1&chromosome=chr01&start=5&end=1&run=1`,
    );
    // An inverted range is rejected client-side: no region request is issued.
    await page.waitForTimeout(500);
    expect(regionRequests).toBe(0);
  });

  test("submit issues the source-site interval request for the chosen chromosome", async ({ page }) => {
    const requested: string[] = [];
    // Current flow keeps results on this page; still capture exact network
    // requests, including any future secondary navigation.
    page.context().on("request", (request) => {
      if (request.url().includes("/preview/test-data/mutation-sites?")) requested.push(request.url());
    });
    // Intercept ONLY the current source-site read for this test. An empty,
    // validated preview envelope exercises the real success/empty rendering;
    // a 404 is an error state and must never be presented as zero results.
    await mockPreviewSites(page);
    await gotoReady(page, `${BASE}/search/location`);

    // Source preview coordinates are only valid under this v6 assembly.
    await page.getByTestId("location-assembly").click();
    await page.locator(".ant-select-dropdown:visible .ant-select-item-option")
      .filter({ hasText: MOCK_PREVIEW_ASSEMBLY.name }).first().click();
    // Pick a chromosome so the form validates.
    // antd Select is a div rather than a native <select>, so open it and click
    // the option instead of using `selectOption`.
    await page.getByTestId("location-chromosome").click();
    // antd includes both the option wrapper and its inner label text.
    // Target the clickable option wrapper, avoiding strict-mode duplicates.
    await page.locator(".ant-select-dropdown:visible .ant-select-item-option").filter({ hasText: "chr01" }).first().click();
    await page.getByTestId("location-start").fill("1");
    await page.getByTestId("location-end").fill("2000");
    await expect(page.getByTestId("location-submit")).toBeEnabled();
    await page.getByTestId("location-submit").click();
    await expect.poll(() => currentParams(page).get("chromosome")).toBe("chr01");

    // The shared link carries the stable catalogue id of the assembly, not its
    // display name. Read the parameters exactly — a loose "assembly=6" match
    // would also accept "assembly=60".
    expect(currentAssemblyParam(page)).toBe(MOCK_PREVIEW_ASSEMBLY.id);
    expect(currentParams(page).get("start")).toBe("1");
    expect(currentParams(page).get("end")).toBe("2000");
    expect(["1", "true"]).toContain(currentParams(page).get("run"));

    await expect.poll(() => requested.length).toBeGreaterThan(0);
    const requestParams = new URL(requested[0]).searchParams;
    expect(requestParams.get("chromosome")).toBe("chr01");
    expect(requestParams.get("start")).toBe("1");
    expect(requestParams.get("end")).toBe("2000");
    // The source preview endpoint has no assembly parameter: context belongs
    // in the shareable page URL and is validated before submit.
    // The empty result is reported, not hidden.
    await expect(page.getByTestId("location-empty")).toBeVisible();
  });

  test("a legacy assembly-name link still resolves to the same genome version", async ({ page }) => {
    const requested: string[] = [];
    page.context().on("request", (request) => {
      if (request.url().includes("/preview/test-data/mutation-sites?")) requested.push(request.url());
    });
    await mockPreviewSites(page);
    await gotoReady(
      page,
      `${BASE}/search/location?assembly=${encodeURIComponent(MOCK_PREVIEW_ASSEMBLY.name)}&chromosome=chr01&start=1&end=2000&run=1`,
    );

    // The unique legacy name is resolved to its catalogue row ...
    await expect(page.getByTestId("location-assembly")).toContainText(MOCK_PREVIEW_ASSEMBLY.name);
    // ... and is not reported as an unknown genome version.
    await expect(page.getByText(ASSEMBLY_UNAVAILABLE)).toHaveCount(0);
    // The region query therefore runs against the resolved assembly.
    await expect.poll(() => requested.length).toBeGreaterThan(0);
    expect(new URL(requested[0]).searchParams.get("chromosome")).toBe("chr01");
    await expect(page.getByTestId("location-empty")).toBeVisible();
  });

  test("an assembly-id link is accepted and selects the same genome version", async ({ page }) => {
    const requested: string[] = [];
    page.context().on("request", (request) => {
      if (request.url().includes("/preview/test-data/mutation-sites?")) requested.push(request.url());
    });
    await mockPreviewSites(page);
    await gotoReady(
      page,
      `${BASE}/search/location?assembly=${MOCK_PREVIEW_ASSEMBLY.id}&chromosome=chr01&start=1&end=2000&run=1`,
    );

    await expect(page.getByTestId("location-assembly")).toContainText(MOCK_PREVIEW_ASSEMBLY.name);
    await expect(page.getByText(ASSEMBLY_UNAVAILABLE)).toHaveCount(0);
    await expect.poll(() => requested.length).toBeGreaterThan(0);
    expect(new URL(requested[0]).searchParams.get("chromosome")).toBe("chr01");
    await expect(page.getByTestId("location-empty")).toBeVisible();
  });
});

/**
 * Enabling live-result assertions: point SMOKE_BASE_URL / the static server at
 * an environment with a running API (or extend e2e/static-server.mjs to mock
 * GET /genes/assemblies and GET /genes & /variants/region), then un-skip and
 * assert the six-column result order and JBrowse 2 deep links.
 */
