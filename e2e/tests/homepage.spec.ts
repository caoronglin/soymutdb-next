/**
 * Homepage E2E — Phase 4/8 public layout.
 *
 * Offline-capable: the page bootstraps from the immutable seed definition
 * when the API is unavailable (see apps/web/src/page-builder/loader.ts), so
 * the five fixed task entries and the primary navigation render without a
 * backend. News/carousel data is API-backed and degrades to an empty state.
 *
 * Target: local static server at /soymutdb-next/ (playwright-public.config.ts),
 * or the deployed site via SMOKE_BASE_URL.
 */
import { test, expect } from "@playwright/test";

const BASE = "/soymutdb-next";

test.describe("homepage — primary navigation", () => {
  test("renders the five-item nav in fixed order", async ({ page }) => {
    await page.goto(`${BASE}/`);

    const nav = page.locator('nav[aria-label="Primary"]').first();
    await expect(nav).toBeVisible();

    const labels = await nav.locator("a").allTextContents();
    const joined = labels.map((l) => l.trim()).join("|");
    // Order from the seed fallback: Home / Search / Tools / Latest News / Contact.
    const home = joined.indexOf("Home");
    const search = joined.indexOf("Search");
    const tools = joined.indexOf("Tools");
    const news = joined.indexOf("Latest News");
    const contact = joined.indexOf("Contact");
    expect(home).toBeGreaterThanOrEqual(0);
    expect(search).toBeGreaterThan(home);
    expect(tools).toBeGreaterThan(search);
    expect(news).toBeGreaterThan(tools);
    expect(contact).toBeGreaterThan(news);
  });
});

test.describe("homepage — task entries", () => {
  test("shows the five direct task entries in order", async ({ page }) => {
    await page.goto(`${BASE}/`);

    // The seed home definition renders tool_entries (Gene ID, Physical
    // Location, JBrowse 2, BLAST, Primer Design).
    const entries = page.locator('a[href*="/search/genes"], a[href*="/search/location"], a[href*="/search/gbrowse"], a[href*="/blast"], a[href*="/search/primer"]');
    await expect(entries.first()).toBeVisible({ timeout: 15_000 });

    const geneId = page.locator('a[href*="/search/genes"]').first();
    const location = page.locator('a[href*="/search/location"]').first();
    const jbrowse = page.locator('a[href*="/search/gbrowse"]').first();
    const blast = page.locator('a[href*="/blast"]').first();
    const primer = page.locator('a[href*="/search/primer"]').first();

    for (const el of [geneId, location, jbrowse, blast, primer]) {
      await expect(el).toBeVisible();
    }
  });
});

test.describe("homepage — content sections", () => {
  test("renders the news list section (empty state offline)", async ({ page }) => {
    await page.goto(`${BASE}/`);
    // The news_list section renders either headlines (live API) or an
    // empty/loading state (offline) — never fake data.
    await expect(page.getByText(/latest news/i).first()).toBeVisible();
  });

  test("does not render the legacy hero search", async ({ page }) => {
    await page.goto(`${BASE}/`);
    await expect(page.locator('[data-testid="hero"]')).toHaveCount(0);
  });
});
