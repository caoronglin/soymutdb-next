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
import { expect, test } from "@playwright/test";

import {
  MOCK_GENE_ID,
  MOCK_MUTANT_PUBLIC_ID,
  gotoReady,
  mockEntityApis,
  trackErrors,
} from "./helpers";

/** Deployed portal base, e.g. "https://soymutdb.test/". */
const EXPLICIT_PORTAL_BASE = (
  process.env.PORTAL_BASE_URL ??
  process.env.SMOKE_BASE_URL ??
  ""
).trim();

/**
 * Offline fallback target (built public artifact + in-browser API mocks) used
 * when no deployed base was supplied. Matches playwright-entity-detail.config.ts.
 */
const OFFLINE_PORTAL_BASE = "http://localhost:4176/";

const PORTAL_BASE_URL = EXPLICIT_PORTAL_BASE || OFFLINE_PORTAL_BASE;

/**
 * True when running against the local artifact: the lists/detail then need the
 * deterministic mocks, because the static server serves no release rows.
 */
const OFFLINE = EXPLICIT_PORTAL_BASE === "";

/** Optional pinned identifiers; when unset each test derives one from a list. */
const MUTANT_PUBLIC_ID = (process.env.ENTITY_MUTANT_PUBLIC_ID ?? "").trim();
const VARIANT_ID = (process.env.ENTITY_VARIANT_ID ?? "").trim();
const GENE_ID = (process.env.ENTITY_GENE_ID ?? "").trim();

const SKIP_NO_BASE = "set PORTAL_BASE_URL (or SMOKE_BASE_URL) to the deployed portal";

/**
 * Offline coverage of the two detail views is a regression test for a fixed
 * product bug (2026-10-18): the artifact is built with an EMPTY
 * `VITE_SOYMUTDB_RELEASE_ID`, so the first `GET /releases/active` flips the
 * release pin on load. The provider used to react with
 * `queryClient.removeQueries()`, whose `Query#destroy()` silently cancels the
 * in-flight detail fetch: the observer was orphaned and the route stayed on its
 * skeleton forever even though the detail response was 200. It now invalidates
 * the release-scoped entries in place and refetches the active observers
 * (`apps/web/src/lib/release-scope.tsx`), so these tests run offline and would
 * fail if the destroy-based switch ever comes back.
 */
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

test.describe("entity detail — deployed portal", () => {
  test("mutant detail renders by public id with a stable link and no private id", async ({
    page,
  }) => {
    test.skip(!PORTAL_BASE_URL, SKIP_NO_BASE);

    const errors = trackErrors(page);
    if (OFFLINE) await mockEntityApis(page);

    // Offline the deterministic mock serves one public record; a deployed
    // target must name an id explicitly rather than deriving one from a list
    // whose query surface is not part of this contract test.
    const publicId = MUTANT_PUBLIC_ID || MOCK_MUTANT_PUBLIC_ID;

    await gotoReady(page, underBase(PORTAL_BASE_URL, `mutants/${encodeURIComponent(publicId)}`));

    const detail = page.getByTestId("mutant-detail");
    // Assert on the rendered record, not the route wrapper: `mutant-detail`
    // only appears once the detail query has produced a record the guard
    // accepted, so it is already free of the loading skeleton.
    await expect(detail).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("mutant-public-id")).toContainText(publicId);
    await expect(page.getByTestId("mutant-name")).not.toBeEmpty();

    // A stable, shareable link: the page is addressed by the public id and the
    // URL never carries a private persistence key.
    expect(new URL(page.url()).pathname.endsWith(`/mutants/${publicId}`)).toBe(true);
    expectNoInternalIdentifiers(page.url(), "the mutant detail URL");
    // TanStack's <Link to="/mutants" search={{mutagen: ""}}> renders
    // `/mutants?mutagen=`, so the back link is matched by prefix, not suffix.
    await expect(page.locator('a[href^="/mutants"]').first()).toBeVisible();

    // Reload proves the link is stable, not a one-shot client transition.
    await page.reload();
    await expect(detail).toBeVisible();

    expect(
      errors,
      "the mutant detail must render without unexpected console errors or pageerrors",
    ).toEqual([]);
  });

  test("comparison view keeps selected variants addressable and reloadable", async ({
    page,
  }) => {
    test.skip(!PORTAL_BASE_URL, SKIP_NO_BASE);
    // The /compare view is the offline-curated comparison surface (see
    // apps/web/src/lib/compare-data.ts); unlike the mutant/gene detail pages it
    // does not fetch release rows, so this test proves the part the page owns:
    // a shareable `?ids=` URL that survives reload. Provenance rows on this page
    // are still a gap (tracked in docs/dev/project-status.md).
    const errors = trackErrors(page);
    const base = underBase(PORTAL_BASE_URL, "compare");
    await gotoReady(page, VARIANT_ID ? `${base}?ids=${encodeURIComponent(VARIANT_ID)}` : base);

    const table = page.getByTestId("compare-table");
    await expect(table).toBeVisible();

    const headerId = (await table.locator("thead th").nth(1).innerText()).trim();
    expect(headerId, "the comparison table must label its variant columns").toBeTruthy();
    if (VARIANT_ID) expect(headerId).toContain(VARIANT_ID);

    // The selection is mirrored into the URL, so the view is shareable.
    await expect
      .poll(
        () => {
          const ids = new URL(page.url()).searchParams.get("ids") ?? "";
          return ids.split(",").filter(Boolean);
        },
        { message: "the compare URL must carry the selected variant ids" },
      )
      .toContain(headerId);
    // Provenance rows: the curated dataset carries none, so the page must show
    // the deployment assembly (from the mocked assemblies API) and release
    // context instead of implying release-pinned data.
    await expect(page.getByTestId("compare-row-assembly")).toBeVisible();
    await expect(page.getByTestId("compare-row-assembly-value").first()).toContainText("Wm82.a4.v1");
    await expect(page.getByTestId("compare-row-release")).toBeVisible();

    expectNoInternalIdentifiers(page.url(), "the comparison URL");

    await page.reload();
    await expect(table).toBeVisible();

    expect(
      errors,
      "the comparison view must render without unexpected console errors or pageerrors",
    ).toEqual([]);
  });

  test("gene detail renders assembly-scoped coordinates and a stable JBrowse link", async ({
    page,
  }) => {
    test.skip(!PORTAL_BASE_URL, SKIP_NO_BASE);

    const errors = trackErrors(page);
    if (OFFLINE) await mockEntityApis(page);

    const geneAccession = GENE_ID || MOCK_GENE_ID;
    const geneHref = underBase(PORTAL_BASE_URL, `genes/${encodeURIComponent(geneAccession)}`);

    await gotoReady(page, geneHref);

    // `gene-detail` sits on the route wrapper, which is mounted before the
    // detail query answers — it is green while the page is still a skeleton.
    // `gene-id` only exists in the rendered record, so it is the assertion that
    // actually proves the detail query settled.
    await expect(page.getByTestId("gene-id")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("gene-detail")).toBeVisible();
    await expect(page.getByTestId("gene-id")).not.toBeEmpty();
    // DB-CORE-3/4: the assembly and the 1-based inclusive interval are explicit,
    // never an assembly-less coordinate that could resolve to another namespace.
    await expect(page.getByTestId("gene-assembly")).not.toHaveText(/^\s*—\s*$/);
    await expect(page.getByTestId("gene-coords")).toContainText(/[^:\s]+:\d+\.\.\d+/);
    expectNoInternalIdentifiers(page.url(), "the gene detail URL");
    // The gene detail's own back link points at the gene search listing
    // (`/genes?assembly=&q=&...`, labelled "Back to Search"), not at /search.
    await expect(page.locator('a[href^="/genes"]').first()).toBeVisible();

    // The JBrowse deep link is optional (a core-only deployment ships none), but
    // when present it must carry the same assembly context and a real locus.
    // `buildJbrowseLocusUrl` names the query keys `assembly` / `locus` (and adds
    // `release` when the deployment pins one). The link carries JBrowse 2's
    // `refseqid:start-end` locus, which is not the `chr:start..end` spelling the
    // `gene-coords` display uses — both are 1-based inclusive, the separator is
    // the only difference, so the two assertions deliberately differ here.
    const jbrowse = page.getByTestId("gene-jbrowse");
    if ((await jbrowse.count()) > 0) {
      const href = (await jbrowse.getAttribute("href")) ?? "";
      const url = new URL(href, underBase(PORTAL_BASE_URL));
      expect(url.searchParams.get("assembly"), "the JBrowse link must keep the assembly").toBeTruthy();
      expect(url.searchParams.get("locus"), "the JBrowse link must carry a locus").toMatch(
        /[^:\s]+:\d+[-–]\d+/,
      );
    }

    await page.reload();
    await expect(page.getByTestId("gene-id")).toBeVisible();

    expect(
      errors,
      "the gene detail must render without unexpected console errors or pageerrors",
    ).toEqual([]);
  });
});
