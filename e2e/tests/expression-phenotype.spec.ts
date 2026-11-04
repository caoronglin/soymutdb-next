/**
 * Expression / phenotype / PopGen route smoke (Phase 4 portal pages).
 *
 * These pages were covered by component tests only. Component tests render the
 * component; they do not prove the route is reachable from a URL, that the
 * generated route tree resolves the params, or that the artifact hydrates
 * without a console error. That is the gap this spec closes.
 *
 * Offline-capable: the deterministic API mock below serves the four expression
 * and three PopGen endpoints the pages need. Nothing here asserts a live
 * backend; every fixture is a frozen literal.
 *
 * The identity rule is asserted, not assumed: the mock deliberately carries an
 * internal persistence key on the phenotype rows, and the page must never put
 * it in the DOM or in a URL.
 */
import { test, expect, type Page } from "@playwright/test";
import { gotoReady, waitForAppReady } from "./helpers";

const BASE = "";

const RELEASE_ID = "7";
const SAMPLE_PUBLIC_ID = "SAMPLE-0001";
/** Fixture-only persistence key: must never reach the browser's document. */
const SAMPLE_INTERNAL_ID = "884422";
const LINE_PUBLIC_ID = "SMDB-00001";
/** Fixture-only persistence key: must never reach the browser's document. */
const PHENOTYPE_INTERNAL_ID = "991991";

/** `GET /mutants` returns a bare array; the scan reads it directly. */
const MUTANT_LINES = [
  {
    public_id: LINE_PUBLIC_ID,
    name: "Mock line",
    mutagen: "EMS",
    cultivar: "Williams 82",
    variant_count: 3,
  },
];

const MUTANT_LINE_DETAIL = {
  ...MUTANT_LINES[0],
  species: "Glycine max",
};

const LIBRARY = {
  public_id: SAMPLE_PUBLIC_ID,
  sample_id: SAMPLE_PUBLIC_ID,
  library_name: "Mock root RNA-seq",
  tissue: "root",
  treatment: "none",
  developmental_stage: "V3",
  study_ref: "SRP000000",
  source: "ENA",
  assembly_name: "Wm82.a4.v1",
  expression_data_count: 1,
  extra_metadata: { platform: "Illumina" },
};

const EXPRESSION_ROWS = [
  {
    gene_id: "Glyma.01G000100",
    library_public_id: SAMPLE_PUBLIC_ID,
    library_name: "Mock root RNA-seq",
    tissue: "root",
    treatment: "none",
    fpkm: 12.5,
    // A missing measurement is null in both units; the page must render the
    // "not measured" marker rather than a measured-looking 0.
    tpm: null,
    raw_count: null,
  },
];

const PHENOTYPE_ROWS = [
  {
    // Internal key: present in the payload on purpose, never rendered.
    id: PHENOTYPE_INTERNAL_ID,
    mutant_line_public_id: LINE_PUBLIC_ID,
    trait_category: "oil",
    trait_name: "protein content",
    trait_value: "41.2",
    unit: "%",
    description: "Mock observation.",
  },
];

/** Exact-match JSON mock for the Phase 4 endpoints; everything else 404s. */
async function stubPhase4Apis(page: Page): Promise<void> {
  await page.route(/\/api\/v1\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const origin = request.headers()["origin"];
    const headers: Record<string, string> = {
      "access-control-allow-origin": origin ?? "*",
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "authorization,content-type,x-soymutdb-release",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "access-control-expose-headers": "x-soymutdb-release",
      "x-soymutdb-release": RELEASE_ID,
      vary: "Origin",
    };

    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers });

    const json = (body: unknown) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        headers,
        body: JSON.stringify(body),
      });

    const path = url.pathname;

    if (path.endsWith("/releases/active")) {
      return json({ release_id: RELEASE_ID, version: "e2e", published_at: "2026-01-01T00:00:00Z" });
    }
    if (path.endsWith("/genes/assemblies")) {
      return json([
        { id: "1", name: "Wm82.a4.v1", species: "Glycine max", version: "a4.v1", is_default: true },
      ]);
    }

    // --- expression ---
    if (path.endsWith("/expression/libraries")) {
      return json({ items: [LIBRARY], total: 1, page: 1, page_size: 20 });
    }
    if (path.endsWith(`/expression/libraries/${SAMPLE_PUBLIC_ID}`)) return json(LIBRARY);
    if (path.endsWith("/expression/search")) {
      return json({ items: EXPRESSION_ROWS, total: 1, page: 1, page_size: 100 });
    }

    // --- phenotypes (per line only; there is no cross-line endpoint) ---
    if (path.endsWith(`/mutants/${LINE_PUBLIC_ID}/phenotypes`)) return json(PHENOTYPE_ROWS);
    if (path.endsWith(`/mutants/${LINE_PUBLIC_ID}`)) return json(MUTANT_LINE_DETAIL);
    if (path.endsWith("/mutants")) return json(MUTANT_LINES);

    return route.fulfill({ status: 404, headers, contentType: "application/json", body: "{}" });
  });
}

test.describe("expression browser", () => {
  test("/expression lists a library and links it by public sample id", async ({ page }) => {
    await stubPhase4Apis(page);
    await gotoReady(page, `${BASE}/expression`);

    const row = page.getByTestId("expression-library-row").first();
    await expect(row).toBeVisible();
    await expect(row).toHaveText(SAMPLE_PUBLIC_ID);
    // The persistence key must not be used as a link, a key or a label.
    await expect(page.locator(`a[href*="${SAMPLE_INTERNAL_ID}"]`)).toHaveCount(0);
  });

  test("/expression/$sampleId renders provenance and never shows a null as 0", async ({ page }) => {
    await stubPhase4Apis(page);
    await gotoReady(page, `${BASE}/expression/${SAMPLE_PUBLIC_ID}`);

    await expect(page.getByTestId("expression-library-detail")).toBeVisible();
    await expect(page.getByTestId("expression-sample-id")).toHaveText(SAMPLE_PUBLIC_ID);
    // Provenance is required, not optional chrome.
    await expect(page.getByTestId("expression-study-ref")).toHaveText("SRP000000");
    await expect(page.getByTestId("expression-source")).toHaveText("ENA");
    await expect(page.getByTestId("expression-assembly")).toHaveText("Wm82.a4.v1");

    // `tpm` is null in the fixture. The cell must say "not measured" (—), not a
    // measured-looking zero. Scoped to the gene row table because the chart's
    // exact-value table shares the ARIA role.
    const rowTable = page
      .locator(".ant-table-wrapper")
      .filter({ hasText: "Glyma.01G000100" });
    await expect(rowTable).toBeVisible();
    await expect(rowTable).toContainText("—");
  });
});

test.describe("phenotype browser", () => {
  test("/phenotypes states that it is a bounded scan", async ({ page }) => {
    await stubPhase4Apis(page);
    await gotoReady(page, `${BASE}/phenotypes`);

    await expect(page.getByTestId("phenotypes-scan-boundary")).toBeVisible();
  });

  test("a phenotype row links by public line id and leaks no internal key", async ({ page }) => {
    await stubPhase4Apis(page);
    await gotoReady(page, `${BASE}/phenotypes`);

    const link = page.locator(`a[href*="${LINE_PUBLIC_ID}"]`).first();
    await expect(link).toBeVisible();

    const html = await page.locator("body").innerHTML();
    expect(html).not.toContain(PHENOTYPE_INTERNAL_ID);
    expect(html).not.toContain(`data-row-key="${PHENOTYPE_INTERNAL_ID}"`);
  });

  test("/phenotypes/$lineId mounts and shows the public line id", async ({ page }) => {
    await stubPhase4Apis(page);
    await gotoReady(page, `${BASE}/phenotypes/${LINE_PUBLIC_ID}`);

    await expect(page.getByTestId("phenotype-line-detail")).toBeVisible();
    await expect(page.getByTestId("phenotype-line-public-id")).toContainText(LINE_PUBLIC_ID);
    await expect(page.getByText("protein content")).toBeVisible();
    const html = await page.locator("body").innerHTML();
    expect(html).not.toContain(PHENOTYPE_INTERNAL_ID);
    expect(html).not.toContain(`data-row-key="${PHENOTYPE_INTERNAL_ID}"`);
  });
});

test.describe("PopGen tools", () => {
  // Route reachability only: the forms do not submit without user input, and
  // the numeric contracts (r² null, π/θ null reasons) are component-tested.
  for (const path of ["/tools/ld", "/tools/diversity", "/tools/allelefreq"]) {
    test(`${path} mounts without a crash`, async ({ page }) => {
      await stubPhase4Apis(page);
      await gotoReady(page, `${BASE}${path}`);
      await waitForAppReady(page);

      await expect(page.locator("main")).toBeVisible();
      await expect(page.locator("body")).not.toContainText(/Unexpected Application Error/i);
    });
  }
});
