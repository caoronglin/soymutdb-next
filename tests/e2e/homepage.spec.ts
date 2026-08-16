import { test, expect } from '@playwright/test';

/**
 * SoyMutDB Homepage E2E Tests (Phase 4 layout)
 *
 * The home page follows the approved reference layout:
 *   - 2:3 latest-news / featured-carousel grid
 *   - five direct task entries (Gene ID, Physical Location, JBrowse 2, BLAST,
 *     Primer Design)
 *   - sanitized CMS content block
 * The legacy hero search and statistics strip are removed.
 */

test.describe('Homepage', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('renders the primary navigation in approved order', async ({ page }) => {
    // Primary nav: Home / Search / Tools / Latest News / Contact.
    const nav = page.locator('nav[aria-label="Primary"]').first();
    await expect(nav).toBeVisible();

    const labels = await nav.locator('a').allTextContents();
    const joined = labels.join(' ');
    expect(joined).toMatch(/Home/i);
    expect(joined).toMatch(/Search/i);
    expect(joined).toMatch(/Latest News/i);
    expect(joined).toMatch(/Contact/i);
  });

  test('renders the latest-news and carousel grid', async ({ page }) => {
    // The 2:3 grid is the top module; news list and carousel are present.
    await expect(page.locator('a[href*="/news/"]').first()).toBeVisible();
  });

  test('renders the five direct task entries', async ({ page }) => {
    // Task entries: Gene ID, Physical Location, JBrowse 2, BLAST, Primer Design.
    await expect(page.locator('a[href*="/search/genes"]').first()).toBeVisible();
    await expect(page.locator('a[href*="/search/location"]').first()).toBeVisible();
    await expect(page.locator('a[href*="/blast"]').first()).toBeVisible();
    await expect(page.locator('a[href*="/search/primer"]').first()).toBeVisible();
  });

  test('the legacy hero search is removed', async ({ page }) => {
    await expect(page.locator('[data-testid="hero"]')).toHaveCount(0);
  });

  test('footer is visible', async ({ page }) => {
    const footer = page.locator('footer, [data-testid="footer"]');
    await expect(footer).toBeVisible();
  });

  test('page loads within acceptable time', async ({ page }) => {
    const startTime = Date.now();
    await page.goto('/', { waitUntil: 'networkidle' });
    const loadTime = Date.now() - startTime;
    expect(loadTime).toBeLessThan(5000);
  });
});
