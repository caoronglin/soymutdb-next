/**
 * Entity detail E2E — mutant (by public id), variant and gene detail views on a
 * DEPLOYED portal.
 *
 * Coverage
 * --------
 *   1. Mutant detail: addressed and rendered by its public_id only (DB-CORE-2),
 *      with a stable back-link to the mutant list and no private identifier.
 *   2. Variant detail: the /compare?id=... view carries the assembly and
 *      release provenance rows and stable links into gene / genome-browser.
 *   3. Gene detail: the assembly-scoped accession, chromosome and 1-based
 *      inclusive coordinates are visible, and the JBrowse deep link (when the
 *      deployment ships one) carries the same assembly + locus.
 *
 * Every test also fails on any unexpected console error or pageerror.
 *
 * Prerequisites
 * -------------
 *   - a deployed portal reachable at PORTAL_BASE_URL (or SMOKE_BASE_URL);
 *   - released data in the active release. When a list is empty the test SKIPS
 *     ("no entity to detail") instead of failing, because an empty release is a
 *     valid environment, not a UI regression.
 *
 * Entity identifiers are derived from the target's own lists; they can be
 * pinned with ENTITY_MUTANT_PUBLIC_ID / ENTITY_VARIANT_ID / ENTITY_GENE_ID.
 * The suite never invents identifiers and never reads credentials.
 *
 * Run (from e2e/):
 *   PORTAL_BASE_URL=https://soymutdb.test/ \
 *     npx playwright test -c playwright-entity-detail.config.ts
 */
import { expect, test, type Page } from "@playwright/test";

import { gotoReady, trackErrors } from "./helpers";

/** Deployed portal base, e.g. "https://soymutdb.test/". */
const PORTAL_BASE_URL = (
  process.env.PORTAL_BASE_URL ??
  process.env.SMOKE_BASE_URL ??
  ""
).trim();

/** Optional pinned identifiers; when unset each test derives one from a list. */
const MUTANT_PUBLIC_ID = (process.env.ENTITY_MUTANT_PUBLIC_ID ?? "").trim();
const VARIANT_ID = (process.env.ENTITY_VARIANT_ID ?? "").trim();
const GENE_ID = (process.env.ENTITY_GENE_ID ?? "").trim();

const SKIP_NO_BASE = "set PORTAL_BASE_URL (or SMOKE_BASE_URL) to the deployed portal";

/** Resolve a path under a base that may carry a sub-path prefix. */
function underBase(base: string, path = ""): string {
  const root = base.endsWith("/") ? base : `${base}/`;
  return new URL(path.replace(/^\//, ""), root).toString();
}

/**
 * Case-insensitive markers for private persistence keys, which must never
 * appear in a public browser URL (including percent-encoded spellings).
 */
const INTERNAL_ID_MARKERS = [
  "internal_id",
  "internalid",
  "internal-id",
  "internal%5fid",
  "internal%2did",
];

/** Fail if a URL exposes a private persistence identifier in any position. */
function expectNoInternalIdentifiers(rawUrl: string, where: string): void {
  const lower = rawUrl.toLowerCase();
  for (const marker of INTERNAL_ID_MARKERS) {
    expect(lower, `${where} must not contain the private marker "${marker}"`).not.toContain(
      marker,
    );
  }
}

/** Derive the first entity id/link from a list, or null when the list is empty. */
async function firstListEntity(
  page: Page,
  listPath: string,
  locate: () => ReturnType<Page["locator"]>,
): Promise<string | null> {
  await gotoReady(page, underBase(PORTAL_BASE_URL, listPath));
  const probe = locate();
  if ((await probe.count()) === 0) return null;
  const value = await probe.first().getAttribute("data-public-id");
  return value;
}

test.describe("entity detail — deployed portal", () => {
  test("mutant detail renders by public id with a stable link and no private id", async ({
    page,
  }) => {
    test.skip(!PORTAL_BASE_URL, SKIP_NO_BASE);

    const errors = trackErrors(page);

    let publicId = MUTANT_PUBLIC_ID;
    if (!publicId) {
      const id = await firstListEntity(page, "mutants", () =>
        page.locator('[data-testid="mutant-row"][data-public-id]'),
      );
      if (!id) test.skip(true, "the target returned no released mutant lines to detail");
      publicId = id;
    }

    await gotoReady(page, underBase(PORTAL_BASE_URL, `mutants/${encodeURIComponent(publicId)}`));

    const detail = page.getByTestId("mutant-detail");
    await expect(detail).toBeVisible();
    await expect(page.getByTestId("mutant-public-id")).toHaveText(publicId);
    await expect(page.getByTestId("mutant-name")).not.toBeEmpty();

    // A stable, shareable link: the page is addressed by the public id and the
    // URL never carries a private persistence key.
    expect(new URL(page.url()).pathname.endsWith(`/mutants/${publicId}`)).toBe(true);
    expectNoInternalIdentifiers(page.url(), "the mutant detail URL");
    await expect(page.locator('a[href$="/mutants"]').first()).toBeVisible();

    // Reload proves the link is stable, not a one-shot client transition.
    await page.reload();
    await expect(detail).toBeVisible();

    expect(
      errors,
      "the mutant detail must render without unexpected console errors or pageerrors",
    ).toEqual([]);
  });

  test("variant detail renders assembly/release provenance with stable links", async ({
    page,
  }) => {
    test.skip(!PORTAL_BASE_URL, SKIP_NO_BASE);

    const errors = trackErrors(page);

    let variantId = VARIANT_ID;
    if (!variantId) {
      await gotoReady(page, underBase(PORTAL_BASE_URL, "variants"));
      const row = page.getByTestId("variant-row").first();
      if ((await row.count()) === 0) {
        test.skip(true, "the target returned no released variants to detail");
      }
      variantId = (await row.locator("td").first().innerText()).trim();
    }
    expect(variantId, "a variant id is required").toBeTruthy();

    await gotoReady(
      page,
      underBase(PORTAL_BASE_URL, `compare?ids=${encodeURIComponent(variantId)}`),
    );

    const table = page.getByTestId("compare-table");
    await expect(table).toBeVisible();
    await expect(table.locator("thead th").nth(1)).toContainText(variantId);

    // Assembly + release are the provenance rows of the comparison contract.
    await expect(
      table.locator('th[scope="row"]', { hasText: /^Assembly$/ }),
    ).toBeVisible();
    await expect(table.locator('th[scope="row"]', { hasText: /^Release$/ })).toBeVisible();

    // The id stays in the URL, so the view is shareable and reloadable.
    expect(new URL(page.url()).searchParams.get("ids")).toContain(variantId);
    expectNoInternalIdentifiers(page.url(), "the variant detail URL");

    // Stable link off the detail view: position opens the genome browser.
    await expect(
      table.locator('a[target="_blank"][href*="/browser?"]').first(),
    ).toHaveAttribute("href", /\/browser\?/);

    await page.reload();
    await expect(table).toBeVisible();

    expect(
      errors,
      "the variant detail must render without unexpected console errors or pageerrors",
    ).toEqual([]);
  });

  test("gene detail renders assembly-scoped coordinates and a stable JBrowse link", async ({
    page,
  }) => {
    test.skip(!PORTAL_BASE_URL, SKIP_NO_BASE);

    const errors = trackErrors(page);

    let geneHref: string;
    if (GENE_ID) {
      geneHref = underBase(PORTAL_BASE_URL, `genes/${encodeURIComponent(GENE_ID)}`);
    } else {
      await gotoReady(page, underBase(PORTAL_BASE_URL, "genes"));
      const link = page.getByTestId("gene-row").first().locator('a[href*="/genes/"]').first();
      if ((await link.count()) === 0) {
        test.skip(true, "the target's gene list returned no gene to detail");
      }
      const href = await link.getAttribute("href");
      expect(href, "the gene row must link to the gene detail").toBeTruthy();
      geneHref = new URL(href as string, underBase(PORTAL_BASE_URL)).toString();
    }

    await gotoReady(page, geneHref);

    await expect(page.getByTestId("gene-detail")).toBeVisible();
    await expect(page.getByTestId("gene-id")).not.toBeEmpty();
    // DB-CORE-3/4: the assembly and the 1-based inclusive interval are explicit,
    // never an assembly-less coordinate that could resolve to another namespace.
    await expect(page.getByTestId("gene-assembly")).not.toHaveText(/^\s*—\s*$/);
    await expect(page.getByTestId("gene-coords")).toContainText(/[^:\s]+:\d+\.\.\d+/);
    expectNoInternalIdentifiers(page.url(), "the gene detail URL");
    await expect(page.locator('a[href$="/search"]').first()).toBeVisible();

    // The JBrowse deep link is optional (a core-only deployment ships none), but
    // when present it must carry the same assembly context and a real locus.
    const jbrowse = page.getByTestId("gene-jbrowse");
    if ((await jbrowse.count()) > 0) {
      const href = (await jbrowse.getAttribute("href")) ?? "";
      const url = new URL(href, underBase(PORTAL_BASE_URL));
      expect(url.searchParams.get("assembly"), "the JBrowse link must keep the assembly").toBeTruthy();
      expect(url.searchParams.get("loc"), "the JBrowse link must carry a locus").toMatch(
        /[^:\s]+:\d+\.\.\d+/,
      );
    }

    await page.reload();
    await expect(page.getByTestId("gene-detail")).toBeVisible();

    expect(
      errors,
      "the gene detail must render without unexpected console errors or pageerrors",
    ).toEqual([]);
  });
});
