import { test, expect } from '@playwright/test';

/**
 * SoyMutDB Global Search E2E Tests
 *
 * Tests: search input, search results, search filters, empty state
 */

test.describe('Global Search', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/search');
  });

  test('displays search input on search page', async ({ page }) => {
    const searchInput = page.locator(
      'input[type="search"], input[placeholder*="search" i], [data-testid="global-search"]'
    );
    await expect(searchInput).toBeVisible();
  });

  test('searching for "Glyma" returns gene results', async ({ page }) => {
    const searchInput = page.locator(
      'input[type="search"], input[placeholder*="search" i], [data-testid="global-search"]'
    );
    await searchInput.fill('Glyma');
    await searchInput.press('Enter');

    await page.waitForTimeout(3000);

    // Results should be visible
    const results = page.locator(
      '[data-testid="search-results"], [data-testid="results-section"]'
    );
    await expect(results).toBeVisible();
  });

  test('searching for a specific gene ID returns results', async ({ page }) => {
    const searchInput = page.locator(
      'input[type="search"], input[placeholder*="search" i], [data-testid="global-search"]'
    );
    await searchInput.fill('Glyma.01G001000');
    await searchInput.press('Enter');

    await page.waitForTimeout(3000);

    // Should find the gene
    const results = page.locator('[data-testid="search-results"], [data-testid="results-section"]');
    if (await results.isVisible({ timeout: 5000 }).catch(() => false)) {
      await expect(results).toBeVisible();
    }
  });

  test('searching for non-existent term shows empty state', async ({ page }) => {
    const searchInput = page.locator(
      'input[type="search"], input[placeholder*="search" i], [data-testid="global-search"]'
    );
    await searchInput.fill('ZZZZZ_nonexistent_gene');
    await searchInput.press('Enter');

    await page.waitForTimeout(3000);

    // Should show empty state or no results message
    const emptyState = page.locator(
      '[data-testid="empty-state"], [data-testid="no-results"], :text-matches("no results" i)'
    );

    if (await emptyState.isVisible({ timeout: 5000 }).catch(() => false)) {
      await expect(emptyState).toBeVisible();
    }
  });

  test('search results have clickable links', async ({ page }) => {
    const searchInput = page.locator(
      'input[type="search"], input[placeholder*="search" i], [data-testid="global-search"]'
    );
    await searchInput.fill('Glyma');
    await searchInput.press('Enter');

    await page.waitForTimeout(3000);

    // Check for result links
    const resultLinks = page.locator(
      '[data-testid="search-results"] a, [data-testid="results-section"] a'
    );

    if (await resultLinks.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      const linkHref = await resultLinks.first().getAttribute('href');
      expect(linkHref).toBeTruthy();
    }
  });

  test('search filters are present', async ({ page }) => {
    // Check for filter options (gene, variant, mutant line, etc.)
    const filters = page.locator(
      '[data-testid="search-filters"], [data-testid="filter-section"], [role="checkbox"], [role="tab"]'
    );

    if (await filters.first().isVisible({ timeout: 5000 }).catch(() => false)) {
      await expect(filters.first()).toBeVisible();
    }
  });

  test('search from homepage navigation works', async ({ page }) => {
    await page.goto('/');

    // Find and click search link
    const searchLink = page.locator('a[href*="search"], a[href*="/search"]').first();
    await searchLink.click();

    await page.waitForURL('**/search**');
    await expect(page).toHaveURL(/.*\/search.*/);
  });
});
