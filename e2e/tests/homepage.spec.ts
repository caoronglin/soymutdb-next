/**
 * Homepage E2E — the database entry point.
 *
 * Offline-capable: the identifier search, the five task entries and the portal
 * navigation render without a backend. Assembly/news data is API-backed and
 * degrades to an empty state, never to fake rows.
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

    // The Vue header groups the old flat links under labelled menus; the
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

test.describe("homepage — identifier search and task entries", () => {
  test("shows the identifier search above the task entries", async ({ page }) => {
    await gotoReady(page, `${BASE}/`);

    await expect(page.getByTestId("home-search-input")).toBeVisible();
    await expect(page.getByTestId("home-search-submit")).toBeVisible();

    // Five task entries: Gene ID, Physical Location, JBrowse 2, BLAST, Primer.
    const entries = page.locator('[data-testid="task-entries"] > li > *');
    await expect(entries).toHaveCount(5);
    for (const testId of [
      "task-gene-search",
      "task-location-search",
      "task-jbrowse",
      "task-blast",
      "task-primer",
    ]) {
      await expect(page.getByTestId(testId)).toBeVisible();
    }
  });

  test("routes the identifier search into the global search view", async ({ page }) => {
    await gotoReady(page, `${BASE}/`);
    await page.getByTestId("home-search-input").fill("Glyma.01G000100");
    await page.getByTestId("home-search-submit").click();

    await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("Glyma.01G000100");
    expect(new URL(page.url()).pathname).toBe("/soymutdb-next/search");
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

  test("does not render a hero that displaces the database entry points", async ({ page }) => {
    await gotoReady(page, `${BASE}/`);
    await expect(page.locator('[data-testid="hero"]')).toHaveCount(0);
    await expect(page.getByTestId("home-search-input")).toBeVisible();
  });
});
