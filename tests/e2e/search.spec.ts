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
    const searchInput = page.getByRole('searchbox');
    await expect(searchInput).toBeVisible();
  });

  test('searching for "Glyma" returns gene results', async ({ page }) => {
    const searchInput = page.getByRole('searchbox');
    await searchInput.fill('Glyma');
    await searchInput.press('Enter');

    const results = page.getByTestId('search-results').first();
    await expect(results).toBeVisible();
  });

  test('searching for a specific gene ID returns results', async ({ page }) => {
    const searchInput = page.getByRole('searchbox');
    await searchInput.fill('Glyma.01G001000');
    await searchInput.press('Enter');

    await expect(page.getByTestId('search-results').first()).toBeVisible();
  });

  test('searching for non-existent term shows empty state', async ({ page }) => {
    const searchInput = page.getByRole('searchbox');
    await searchInput.fill('ZZZZZ_nonexistent_gene');
    await searchInput.press('Enter');

    await expect(page.getByText('No matches')).toBeVisible();
  });

  test('search results have clickable links', async ({ page }) => {
    const searchInput = page.getByRole('searchbox');
    await searchInput.fill('Glyma');
    await searchInput.press('Enter');

    const result = page.getByTestId('search-result-row').first();
    await expect(result).toBeVisible();
    await expect(result).toHaveAttribute('data-url', /^\/search\//);
    await expect(result).not.toHaveAttribute('data-url', /\/api\/v1/);
  });

  test('search filters are present', async ({ page }) => {
    // Check for filter options (gene, variant, mutant line, etc.)
    await expect(page.getByTestId('external-source-toggle')).toBeVisible();
  });

  test('query and external source are URL state', async ({ page }) => {
    await page.getByRole('searchbox').fill('Glyma');
    await page.getByTestId('external-source-toggle').check();
    await page.getByRole('searchbox').press('Enter');

    await expect(page).toHaveURL(/q=Glyma/);
    await expect(page).toHaveURL(/external=1/);
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
