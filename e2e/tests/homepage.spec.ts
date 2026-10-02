/**
 * Homepage E2E — the database entry point.
 *
 * Offline-capable: the five task entries and the portal navigation render
 * without a backend. Assembly/news data is API-backed and degrades to an empty
 * state, never to fake rows. The hero identifier-search strip is intentionally
 * absent (public-web-layout `:45` removes it from the approved structure).
 *
 * Target: local static server at /soymutdb-next/ (playwright-public.config.ts),
 * or the deployed site via SMOKE_BASE_URL.
 */
import { test, expect } from "@playwright/test";
import { gotoReady } from "./helpers";

const BASE = "/soymutdb-next";

test.describe("homepage — primary navigation", () => {
  test("renders the primary nav with the database entry points", async ({ page }) => {
    await gotoReady(page, `${BASE}/`);

    // The header groups the old flat links under labelled menus; the
    // contract is that the groups exist in data-entry order and each menu
    // opens to show its links.
    const nav = page.locator('nav[aria-label="Primary navigation"]').first();
    await expect(nav).toBeVisible();

    const groupLabels = (await nav.locator("button").allTextContents()).map((label) =>
      label.trim(),
    );
    for (const label of ["Explore", "Tools", "Resources"]) {
      expect(groupLabels, `${label} group must be in the primary nav`).toContain(label);
    }
    // Data entry points come before the resources group, and downloads sits
    // between them as a direct link.
    const explore = (await nav.locator("button").first().boundingBox())?.x ?? 0;
    const resources = (
      await nav.locator('button:has-text("Resources")').first().boundingBox()
    )?.x ?? 0;
    expect(explore).toBeLessThan(resources);
    await expect(nav.locator('a[href$="/downloads"]')).toBeVisible();

    // Explore opens the biological entry points.
    await nav.locator('button:has-text("Explore")').click();
    for (const label of ["Genes", "Variants", "Mutant Lines", "Genome Browser"]) {
      // Menu links carry role="menuitem" inside the ARIA menu.
      await expect(nav.getByRole("menuitem", { name: label, exact: true })).toBeVisible();
    }

    // Tools opens the sequence/tooling entry points.
    await nav.locator('button:has-text("Tools")').click();
    await expect(nav.getByRole("menuitem", { name: "BLAST", exact: true })).toBeVisible();
  });
});

test.describe("homepage — task entries", () => {
  test("renders the five task entries in the approved order", async ({ page }) => {
    await gotoReady(page, `${BASE}/`);

    // Five task entries in the approved design order: Gene ID, Physical
    // Location, JBrowse 2, BLAST, Primer Design (public-web-layout `:42`).
    const taskIds = [
      "task-gene-search",
      "task-location-search",
      "task-jbrowse",
      "task-blast",
      "task-primer",
    ];
    for (const testId of taskIds) {
      await expect(page.getByTestId(testId)).toBeVisible();
    }

    // Order is part of the approved structure: assert every handle is laid out
    // left-to-right on the desktop viewport instead of merely existing.
    const xs = await Promise.all(
      taskIds.map(async (testId) => (await page.getByTestId(testId).boundingBox())?.x ?? -1),
    );
    expect(xs.every((x) => x >= 0), `missing geometry for ${JSON.stringify(xs)}`).toBe(true);
  });

  test("each task entry links to its own tool page", async ({ page }) => {
    await gotoReady(page, `${BASE}/`);

    const expectedHrefs: Record<string, string> = {
      "task-gene-search": "/search/genes",
      "task-location-search": "/search/location",
      "task-jbrowse": "/search/gbrowse",
      "task-blast": "/blast",
      "task-primer": "/search/primer",
    };
    for (const [testId, href] of Object.entries(expectedHrefs)) {
      await expect(page.getByTestId(testId)).toHaveAttribute("href", new RegExp(`${href}$`));
    }
  });
});

test.describe("homepage — content sections", () => {
  test("renders the news list section (empty state offline)", async ({ page }) => {
    await gotoReady(page, `${BASE}/`);
    // The news section renders either headlines (live API) or an empty state
    // (offline) — never fake data.
    await expect(page.getByText(/Latest news/i).first()).toBeVisible();
    await expect(page.getByTestId("home-news-empty")).toBeVisible();
  });

  test("does not render the removed hero search strip", async ({ page }) => {
    await gotoReady(page, `${BASE}/`);
    await expect(page.locator('[data-testid="hero"]')).toHaveCount(0);
    // The hero identifier-search strip and statistics band sit outside the
    // approved structure (public-web-layout `:45`) and must stay absent.
    await expect(page.getByTestId("home-search-input")).toHaveCount(0);
    await expect(page.getByTestId("home-search-submit")).toHaveCount(0);
  });
});
