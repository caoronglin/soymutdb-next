/**
 * Accessibility E2E — Phase 4/8, desktop/tablet/mobile viewports.
 *
 * Offline-capable: these assertions exercise the static shell/routes and do
 * not depend on API data (news/assemblies degrade to empty states).
 */
import { test, expect } from "@playwright/test";

const BASE = "/soymutdb-next";

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "tablet", width: 900, height: 900 },
  { name: "mobile", width: 390, height: 844 },
] as const;

test.describe("accessibility — layout at three viewports", () => {
  for (const vp of VIEWPORTS) {
    test(`home has no horizontal page overflow (${vp.name})`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(`${BASE}/`);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    });

    test(`focus reaches a visible interactive element (${vp.name})`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(`${BASE}/`);
      // Tab through the skip link and header until focus lands on a visible
      // interactive element (link/button/input).
      let reached = false;
      for (let i = 0; i < 10; i++) {
        await page.keyboard.press("Tab");
        const info = await page.evaluate(() => {
          const el = document.activeElement as HTMLElement | null;
          return el
            ? { tag: el.tagName.toLowerCase(), visible: el.offsetParent !== null }
            : { tag: "", visible: false };
        });
        if ((info.tag === "a" || info.tag === "button" || info.tag === "input") && info.visible) {
          reached = true;
          break;
        }
      }
      expect(reached).toBe(true);
    });
  }
});

test.describe("accessibility — navigation and forms", () => {
  test("all primary navigation links have descriptive text", async ({ page }) => {
    await page.goto(`${BASE}/`);
    const links = page.locator('nav[aria-label="Primary"] a');
    const count = await links.count();
    expect(count).toBeGreaterThanOrEqual(5);
    for (let i = 0; i < count; i++) {
      const text = (await links.nth(i).textContent())?.trim() ?? "";
      expect(text.length).toBeGreaterThan(0);
    }
  });

  test("gene-id form inputs have accessible labels", async ({ page }) => {
    await page.goto(`${BASE}/search/genes`);
    const input = page.getByLabel(/gene id/i);
    await expect(input).toBeVisible();
  });

  test("html has a lang attribute", async ({ page }) => {
    await page.goto(`${BASE}/`);
    const lang = await page.locator("html").getAttribute("lang");
    expect(lang).toBeTruthy();
    expect(lang!.length).toBeGreaterThan(0);
  });
});
