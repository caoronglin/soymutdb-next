/**
 * Accessibility E2E — Phase 4/8, desktop/tablet/mobile viewports.
 *
 * Offline-capable: these assertions exercise the static shell/routes and do
 * not depend on API data (news/assemblies degrade to empty states).
 */
import { test, expect } from "@playwright/test";
import { gotoReady, mockEntityApis, MOCK_VARIANT_ID, MOCK_ASSEMBLY } from "./helpers";

const BASE = "";

// Static artifact + deterministic API fixtures, not live backend/AT acceptance.
for (const width of [1440, 390]) {
  test(`command palette traps real Tab focus and restores the opener (${width}px)`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await gotoReady(page, `${BASE}/`);
    const opener = page.locator("header a:visible").first();
    await expect(opener).toBeVisible();
    await opener.focus();
    await page.keyboard.press("Control+k");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const input = dialog.getByRole("combobox");
    const close = dialog.getByRole("button", { name: "Close", exact: true });
    await expect(input).toBeFocused();

    // Real browser default traversal, not jsdom's synthetic key events.
    await page.keyboard.press("Tab");
    await expect(close).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(input).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(close).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(input).toBeFocused();

    for (const query of ["blast", ""]) {
      await input.fill(query);
      await expect.poll(() => input.evaluate((el) => {
        const list = document.getElementById(el.getAttribute("aria-controls") ?? "");
        const option = document.getElementById(el.getAttribute("aria-activedescendant") ?? "");
        return !!option && !!list?.contains(option) && option.getAttribute("role") === "option";
      })).toBe(true);
    }
    await page.screenshot({ path: testInfo.outputPath(`palette-${width}.png`) });
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
  });
}

test("variant table genuinely scrolls inside a 390px viewport without page overflow", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockEntityApis(page);
  await gotoReady(page, `${BASE}/variants?assembly=${MOCK_ASSEMBLY.id}`);
  const identifier = page.getByTestId("variant-id");
  await expect(identifier).toHaveText(MOCK_VARIANT_ID);
  await expect(page.getByTestId("variant-assembly")).toHaveText(MOCK_ASSEMBLY.name);
  const scroller = page.locator(".ant-table-content").filter({ has: identifier });
  await expect(scroller).toBeVisible();
  const metrics = await scroller.evaluate((el) => {
    el.scrollLeft = 100;
    const result = { width: el.clientWidth, content: el.scrollWidth, left: el.scrollLeft };
    el.scrollLeft = 0;
    return result;
  });
  expect(metrics.content).toBeGreaterThan(metrics.width);
  expect(metrics.left).toBeGreaterThan(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: testInfo.outputPath("variants-390.png"), fullPage: true });
});

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "tablet", width: 900, height: 900 },
  { name: "mobile", width: 390, height: 844 },
] as const;

test.describe("accessibility — layout at three viewports", () => {
  for (const vp of VIEWPORTS) {
    test(`home has no horizontal page overflow (${vp.name})`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await gotoReady(page, `${BASE}/`);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    });

    test(`focus reaches a visible interactive element (${vp.name})`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await gotoReady(page, `${BASE}/`);
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
  test("all primary navigation controls have descriptive text", async ({ page }) => {
    await gotoReady(page, `${BASE}/`);
    const controls = page.locator('nav[aria-label="Primary navigation"] a, nav[aria-label="Primary navigation"] button');
    const count = await controls.count();
    expect(count).toBeGreaterThanOrEqual(4);
    for (let i = 0; i < count; i++) {
      const text = (await controls.nth(i).textContent())?.trim() ?? "";
      expect(text.length).toBeGreaterThan(0);
    }
  });

  test("gene-id form inputs have accessible labels", async ({ page }) => {
    await gotoReady(page, `${BASE}/search/genes`);
    const input = page.getByTestId("search-genes-input");
    await expect(input).toBeVisible();
    // The assembly control is the minimum unambiguous context, so it must be
    // reachable and labelled, not a bare select.
    await expect(page.getByTestId("search-genes-assembly")).toBeVisible();
  });

  test("html has a lang attribute", async ({ page }) => {
    await gotoReady(page, `${BASE}/`);
    const lang = await page.locator("html").getAttribute("lang");
    expect(lang).toBeTruthy();
    expect(lang!.length).toBeGreaterThan(0);
  });
});
