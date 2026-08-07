import { test, expect } from '@playwright/test';

/**
 * SoyMutDB Homepage E2E Tests
 *
 * Tests: Hero section, statistics display, navigation menu
 */

test.describe('Homepage', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('displays hero section with title', async ({ page }) => {
    const hero = page.locator('[data-testid="hero"]');
    await expect(hero).toBeVisible();
    await expect(hero).toContainText(/SoyMutDB/i);
  });

  test('displays statistics summary cards', async ({ page }) => {
    const stats = page.locator('[data-testid="stats-summary"]');
    await expect(stats).toBeVisible();

    // Check for variant count stat
    const variantStat = page.locator('[data-testid="stat-variants"]');
    await expect(variantStat).toBeVisible();

    // Check for gene count stat
    const geneStat = page.locator('[data-testid="stat-genes"]');
    await expect(geneStat).toBeVisible();

    // Check for mutant line count stat
    const mutantStat = page.locator('[data-testid="stat-mutants"]');
    await expect(mutantStat).toBeVisible();
  });

  test('displays navigation menu with key links', async ({ page }) => {
    const nav = page.locator('nav, [data-testid="navigation"]');
    await expect(nav).toBeVisible();

    // Check for key navigation links
    await expect(page.locator('a[href*="genes"], a[href*="/genes"]')).toBeVisible();
    await expect(page.locator('a[href*="variants"], a[href*="/variants"]')).toBeVisible();
    await expect(page.locator('a[href*="search"], a[href*="/search"]')).toBeVisible();
    await expect(page.locator('a[href*="browser"], a[href*="/browser"]')).toBeVisible();
  });

  test('navigation to genes page works', async ({ page }) => {
    await page.locator('a[href*="genes"], a[href*="/genes"]').first().click();
    await page.waitForURL('**/genes**');
    await expect(page).toHaveURL(/.*\/genes.*/);
  });

  test('navigation to search page works', async ({ page }) => {
    await page.locator('a[href*="search"], a[href*="/search"]').first().click();
    await page.waitForURL('**/search**');
    await expect(page).toHaveURL(/.*\/search.*/);
  });

  test('footer is visible', async ({ page }) => {
    const footer = page.locator('footer, [data-testid="footer"]');
    await expect(footer).toBeVisible();
  });

  test('page loads within acceptable time', async ({ page }) => {
    const startTime = Date.now();
    await page.goto('/', { waitUntil: 'networkidle' });
    const loadTime = Date.now() - startTime;
    // Page should load within 5 seconds
    expect(loadTime).toBeLessThan(5000);
  });
});
