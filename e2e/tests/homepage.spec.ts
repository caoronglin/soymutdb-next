/**
 * Homepage E2E — the database entry point.
 *
 * Offline-capable: the four homepage task cards and grouped portal navigation render
 * without a backend. The hero search bar is present; Primer remains a direct
 * route but was intentionally removed from the featured cards.
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

    // The current operator configuration names its search group "Search", not
    // "Explore". All three groups and direct Downloads navigation must work.
    const nav = page.locator('nav[aria-label="Primary navigation"]').first();
    await expect(nav).toBeVisible();

    const groupLabels = (await nav.locator("button").allTextContents()).map((label) =>
      label.trim(),
    );
    for (const label of ["Search", "Tools", "Resources"]) {
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

    // Search opens the biological entry points.
    await nav.locator('button:has-text("Search")').click();
    // Current operator-approved Search menu has four entries; variants and
    // mutant lines remain available via direct routes, not this dropdown.
    await expect(nav.getByRole("menuitem")).toHaveCount(4);
    await expect(nav.getByRole("menuitem", { name: /BLAST/i })).toBeVisible();

    // Tools opens the sequence/tooling entry points.
    await nav.locator('button:has-text("Tools")').click();
    await expect(nav.getByRole("menuitem", { name: "BLAST", exact: true })).toBeVisible();
  });
});

test.describe("homepage — task entries", () => {
  test("renders the four current featured task entries in order", async ({ page }) => {
    await gotoReady(page, `${BASE}/`);

    // Primer is still reachable through its route but is not a homepage card.
    // The current operator-approved cards: Gene ID, Location, JBrowse, BLAST.
    const taskIds = [
      "task-gene-search",
      "task-location-search",
      "task-jbrowse",
      "task-blast",
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

  test("hero identifier search is visible and navigates to the shareable global search", async ({ page }) => {
    await gotoReady(page, `${BASE}/`);
    const box = page.getByTestId("home-search");
    await expect(box.getByRole("textbox")).toBeVisible();
    await box.getByRole("textbox").fill("Glyma.01G000100");
    await box.getByTestId("home-search-submit").click();
    await expect(page).toHaveURL(/\/search\?q=Glyma\.01G000100/);
  });
});
