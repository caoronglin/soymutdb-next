import { test, expect } from "@playwright/test";

// Disposable smoke for the local minimal-mode deployment.
// Requires: API uvicorn on 127.0.0.1:8010 and vite dev on 127.0.0.1:5173
// (VITE_DEPLOYMENT_MODE=minimal VITE_SEARCH_TEST_PREVIEW=true).
// Both search routes submit by opening the parameterized URL in a new tab.

test("local preview deployment: gene + location search render real data", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error" && !msg.text().includes("frame-ancestors")) {
      errors.push(`console: ${msg.text()}`);
    }
  });

  const banner = page.getByTestId("test-data-preview-banner");

  // ---- gene ID search ----
  await page.goto("./search/genes", { waitUntil: "networkidle" });
  await expect(banner).toContainText("测试预览 · 未发布数据");
  await expect(banner).toContainText("Gmax_880_v6.0");
  await expect(banner).toContainText("Wm82.a6.v1");

  await page.getByPlaceholder(/每行一个基因 ID/).fill("Glyma.01G000100.Wm82.a6.v1");
  const [genesTab] = await Promise.all([
    page.waitForEvent("popup"),
    page.getByRole("button", { name: "搜索" }).click(),
  ]);
  await genesTab.waitForLoadState("networkidle");
  await expect(genesTab.locator("main")).toContainText("Glyma.01G000100.Wm82.a6.v1");
  await expect(genesTab.locator("main")).toContainText("Gm01:78,503-103,594");
  await expect(genesTab.locator("main")).toContainText("1–1 of 1");

  // ---- physical location search ----
  await page.goto("./search/location", { waitUntil: "networkidle" });
  await expect(banner).toContainText("测试预览 · 未发布数据");

  await page.getByRole("combobox").first().click();
  await page.keyboard.type("Gm01");
  await page.keyboard.press("Enter");
  await page.getByLabel("起始位点").fill("98256");
  await page.getByLabel("终止位点").fill("98256");
  const [locationTab] = await Promise.all([
    page.waitForEvent("popup"),
    page.getByRole("button", { name: "搜索" }).click(),
  ]);
  await locationTab.waitForLoadState("networkidle");
  await expect(locationTab.locator("main")).toContainText("SOYTE1M-Gm01-98256");
  await expect(locationTab.locator("main")).toContainText("Glyma.01G000100.Wm82.a6.v1");
  await expect(locationTab.locator("main")).toContainText("Gm01:98,256");

  expect(errors).toEqual([]);
});
