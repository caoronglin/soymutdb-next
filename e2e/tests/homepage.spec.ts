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

    const nav = page.locator('nav[aria-label="Primary"]').first();
    await expect(nav).toBeVisible();

    const labels = (await nav.locator("a").allTextContents()).map((label) => label.trim());
    // The nav leads with the data entry points, then the resources.
    const order = ["Explore", "Variants", "Mutant Lines", "Genome Browser", "BLAST", "Tools", "Downloads", "Resources"];
    const positions = order.map((label) => labels.indexOf(label));
    for (const [index, position] of positions.entries()) {
      expect(position, `${order[index]} must be in the primary nav`).toBeGreaterThanOrEqual(0);
    }
    // Data entry points come before the resources group.
    expect(labels.indexOf("BLAST")).toBeLessThan(labels.indexOf("Downloads"));
    expect(labels.indexOf("Tools")).toBeLessThan(labels.indexOf("Resources"));
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
  });

  test("does not render a hero that displaces the database entry points", async ({ page }) => {
    await gotoReady(page, `${BASE}/`);
    await expect(page.locator('[data-testid="hero"]')).toHaveCount(0);
    await expect(page.getByTestId("home-search-input")).toBeVisible();
  });
});
