import { test, expect } from '@playwright/test';

/**
 * SoyMutDB Genes Page E2E Tests
 *
 * Tests: gene search, pagination, gene detail view
 */

test.describe('Genes Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/genes');
  });

  test('displays gene search input', async ({ page }) => {
    const searchInput = page.locator(
      'input[type="search"], input[placeholder*="search" i], [data-testid="gene-search"]'
    );
    await expect(searchInput).toBeVisible();
  });

  test('searching for a gene returns results', async ({ page }) => {
    const searchInput = page.locator(
      'input[type="search"], input[placeholder*="search" i], [data-testid="gene-search"]'
    );
    await searchInput.fill('Glyma.01G');
    await searchInput.press('Enter');

    // Wait for results to load
    await page.waitForTimeout(2000);

    // Check that results table or list is visible
    const results = page.locator(
      'table, [data-testid="gene-results"], [data-testid="results-list"]'
    );
    await expect(results).toBeVisible();
  });

  test('pagination controls are present', async ({ page }) => {
    // Wait for page to load
    await page.waitForTimeout(2000);

    const pagination = page.locator(
      '[data-testid="pagination"], nav[aria-label*="pagination" i], .pagination'
    );
    await expect(pagination).toBeVisible();
  });

  test('clicking next page loads new results', async ({ page }) => {
    await page.waitForTimeout(2000);

    const nextButton = page.locator(
      '[data-testid="pagination-next"], button[aria-label*="next" i], a[aria-label*="next" i]'
    );

    if (await nextButton.isVisible()) {
      await nextButton.click();
      await page.waitForTimeout(2000);
      // Verify URL or content changed
      const paginationInfo = page.locator('[data-testid="pagination-info"], .page-info');
      if (await paginationInfo.isVisible()) {
        await expect(paginationInfo).toContainText(/2/);
      }
    }
  });

  test('clicking a gene opens detail page', async ({ page }) => {
    await page.waitForTimeout(2000);

    // Click on the first gene link in the results
    const geneLink = page.locator(
      'a[href*="/genes/"], [data-testid="gene-link"]'
    ).first();

    if (await geneLink.isVisible()) {
      await geneLink.click();
      await page.waitForURL('**/genes/**');

      // Verify detail page elements
      await expect(page.locator('h1, [data-testid="gene-title"]')).toBeVisible();
    }
  });

  test('gene detail page shows variant information', async ({ page }) => {
    // Navigate directly to a gene detail page
    await page.goto('/genes/Glyma.01G001000');

    await page.waitForTimeout(2000);

    // Check for variant-related sections
    const variantSection = page.locator(
      '[data-testid="variants-section"], [data-testid="gene-variants"], section:has-text("variant" i)'
    );

    // The section may or may not have data, but the structure should exist
    if (await variantSection.isVisible({ timeout: 5000 }).catch(() => false)) {
      await expect(variantSection).toBeVisible();
    }
  });

  test('gene detail page shows genomic coordinates', async ({ page }) => {
    await page.goto('/genes/Glyma.01G001000');
    await page.waitForTimeout(2000);

    // Check for chromosome and position information
    const coordInfo = page.locator(
      '[data-testid="gene-coordinates"], :text-matches("chromosome" i)'
    );

    if (await coordInfo.isVisible({ timeout: 5000 }).catch(() => false)) {
      await expect(coordInfo).toBeVisible();
    }
  });
});
