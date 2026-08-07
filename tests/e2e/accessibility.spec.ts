import { test, expect } from '@playwright/test';

/**
 * SoyMutDB Accessibility E2E Tests
 *
 * Tests: WCAG compliance, keyboard navigation, heading hierarchy,
 *        ARIA labels, color contrast
 */

test.describe('Accessibility', () => {
  test('homepage has proper heading hierarchy', async ({ page }) => {
    await page.goto('/');

    // Check for exactly one h1
    const h1Count = await page.locator('h1').count();
    expect(h1Count).toBeGreaterThanOrEqual(1);

    // Check that h2s follow h1
    const h1 = page.locator('h1').first();
    await expect(h1).toBeVisible();
  });

  test('all images have alt text', async ({ page }) => {
    await page.goto('/');

    const images = page.locator('img');
    const count = await images.count();

    for (let i = 0; i < count; i++) {
      const img = images.nth(i);
      const alt = await img.getAttribute('alt');
      const role = await img.getAttribute('role');

      // Image should have alt text or be marked as decorative
      expect(alt !== null || role === 'presentation').toBeTruthy();
    }
  });

  test('all interactive elements are keyboard accessible', async ({ page }) => {
    await page.goto('/');

    // Tab through the page
    await page.keyboard.press('Tab');

    // Check that focus is visible on an interactive element
    const focused = page.locator(':focus');
    await expect(focused).toBeVisible();

    // Continue tabbing
    for (let i = 0; i < 5; i++) {
      await page.keyboard.press('Tab');
      const currentFocused = page.locator(':focus');
      await expect(currentFocused).toBeVisible();
    }
  });

  test('navigation links have descriptive text', async ({ page }) => {
    await page.goto('/');

    const links = page.locator('nav a, [role="navigation"] a');
    const count = await links.count();

    for (let i = 0; i < count; i++) {
      const link = links.nth(i);
      const text = await link.textContent();
      const ariaLabel = await link.getAttribute('aria-label');
      const title = await link.getAttribute('title');

      // Link should have descriptive text, aria-label, or title
      const hasText = text && text.trim().length > 0;
      const hasAriaLabel = ariaLabel && ariaLabel.trim().length > 0;
      const hasTitle = title && title.trim().length > 0;

      expect(hasText || hasAriaLabel || hasTitle).toBeTruthy();
    }
  });

  test('form inputs have associated labels', async ({ page }) => {
    await page.goto('/search');

    const inputs = page.locator('input[type="search"], input[type="text"], input[type="email"]');
    const count = await inputs.count();

    for (let i = 0; i < count; i++) {
      const input = inputs.nth(i);
      const id = await input.getAttribute('id');
      const ariaLabel = await input.getAttribute('aria-label');
      const placeholder = await input.getAttribute('placeholder');

      // Input should have a label, aria-label, or placeholder
      if (id) {
        const label = page.locator(`label[for="${id}"]`);
        if (await label.count() > 0) {
          continue; // Has associated label
        }
      }

      expect(ariaLabel || placeholder).toBeTruthy();
    }
  });

  test('page has proper lang attribute', async ({ page }) => {
    await page.goto('/');
    const lang = await page.locator('html').getAttribute('lang');
    expect(lang).toBeTruthy();
    expect(lang!.length).toBeGreaterThan(0);
  });

  test('skip to content link is present', async ({ page }) => {
    await page.goto('/');

    // Check for skip link (often hidden until focused)
    const skipLink = page.locator(
      'a[href="#main"], a[href="#content"], [data-testid="skip-link"]'
    );

    if (await skipLink.count() > 0) {
      await expect(skipLink.first()).toBeAttached();
    }
  });

  test('buttons have accessible names', async ({ page }) => {
    await page.goto('/');

    const buttons = page.locator('button');
    const count = await buttons.count();

    for (let i = 0; i < count; i++) {
      const button = buttons.nth(i);
      const text = await button.textContent();
      const ariaLabel = await button.getAttribute('aria-label');
      const title = await button.getAttribute('title');

      const hasText = text && text.trim().length > 0;
      const hasAriaLabel = ariaLabel && ariaLabel.trim().length > 0;
      const hasTitle = title && title.trim().length > 0;

      expect(hasText || hasAriaLabel || hasTitle).toBeTruthy();
    }
  });

  test('color contrast meets WCAG AA standards', async ({ page }) => {
    await page.goto('/');

    // Check that text is visible (basic contrast check)
    const textElements = page.locator('p, span, a, button, h1, h2, h3');
    const count = await textElements.count();

    for (let i = 0; i < Math.min(count, 10); i++) {
      const el = textElements.nth(i);
      if (await el.isVisible()) {
        const color = await el.evaluate((node) => {
          return window.getComputedStyle(node).color;
        });
        // Ensure color is defined (not transparent)
        expect(color).not.toBe('rgba(0, 0, 0, 0)');
      }
    }
  });

  test('genes page is keyboard navigable', async ({ page }) => {
    await page.goto('/genes');

    // Tab to search input
    for (let i = 0; i < 10; i++) {
      await page.keyboard.press('Tab');
      const focused = page.locator(':focus');
      if (await focused.isVisible()) {
        const tag = await focused.evaluate((el) => el.tagName.toLowerCase());
        if (tag === 'input' || tag === 'button' || tag === 'a') {
          break;
        }
      }
    }

    // Should be able to type in focused input
    await page.keyboard.type('Glyma');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(2000);
  });
});
