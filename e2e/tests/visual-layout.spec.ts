import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

// Playwright evaluates this module separately per worker/retry. Pass a stable
// VISUAL_RUN_ID from the npm script so all 15 screenshots share one evidence folder.
const RUN_ID = process.env.VISUAL_RUN_ID ?? "manual";
const ARTIFACT_DIR = resolve(import.meta.dirname, "..", "visual-artifacts", RUN_ID);
mkdirSync(ARTIFACT_DIR, { recursive: true });

const viewports = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "tablet", width: 1024, height: 768 },
  { name: "mobile", width: 390, height: 844 },
] as const;

const routes = [
  { name: "home", path: "/" },
  { name: "gene-search", path: "/search/genes" },
  { name: "location-search", path: "/search/location" },
  { name: "jbrowse", path: "/search/gbrowse" },
  { name: "blast", path: "/blast" },
] as const;

type Metric = {
  route: string;
  viewport: string;
  url: string;
  document: { scrollWidth: number; clientWidth: number; scrollHeight: number };
  visible: { main: boolean; heading: boolean; bodyTextLength: number };
  interactives: { count: number; undersized: Array<{ tag: string; text: string; width: number; height: number }> };
  screenshot: string;
};
const metrics: Metric[] = [];

function safeName(value: string) {
  return value.replace(/^\/+|\/+$/g, "").replace(/[^a-z0-9]+/gi, "-") || "home";
}

async function collect(page: Page, route: string, viewport: string, screenshot: string): Promise<Metric> {
  return page.evaluate(({ route, viewport, screenshot }) => {
    const visible = (element: Element | null) => {
      if (!element) return false;
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    };
    const interactive = Array.from(document.querySelectorAll<HTMLElement>("a, button, input, select, textarea, [role=button]"))
      .filter(visible)
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName.toLowerCase(),
          text: (element.innerText || element.getAttribute("aria-label") || element.getAttribute("placeholder") || "").trim().slice(0, 80),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        };
      });
    return {
      route,
      viewport,
      url: location.href,
      document: {
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
        scrollHeight: document.documentElement.scrollHeight,
      },
      visible: {
        main: visible(document.querySelector("#root, main, [data-testid=antd-home]")),
        heading: visible(document.querySelector("h1, h2, h3")),
        bodyTextLength: (document.body.innerText || "").trim().length,
      },
      interactives: {
        count: interactive.length,
        undersized: interactive.filter((item) => item.width < 24 || item.height < 24).slice(0, 20),
      },
      screenshot,
    };
  }, { route, viewport, screenshot });
}

test.afterAll(() => {
  writeFileSync(resolve(ARTIFACT_DIR, "report.json"), `${JSON.stringify({ runId: RUN_ID, generatedAt: new Date().toISOString(), metrics }, null, 2)}\n`);
});

for (const route of routes) {
  for (const viewport of viewports) {
    test(`${route.name} — ${viewport.name}`, async ({ page, baseURL }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto(new URL(route.path.replace(/^\//, ""), baseURL).toString(), { waitUntil: "networkidle" });
      await page.waitForTimeout(500);
      await expect(page.locator("#root")).not.toBeEmpty();
      const imageName = `${safeName(route.name)}--${viewport.name}.png`;
      await page.screenshot({ path: resolve(ARTIFACT_DIR, imageName), fullPage: true });
      const metric = await collect(page, route.path, viewport.name, imageName);
      metrics.push(metric);
      expect(metric.document.scrollWidth, `${route.path} has page-level horizontal overflow at ${viewport.name}`).toBeLessThanOrEqual(metric.document.clientWidth + 1);
      expect(metric.visible.main, `${route.path} has no visible main content at ${viewport.name}`).toBeTruthy();
      expect(metric.visible.bodyTextLength, `${route.path} rendered an empty page at ${viewport.name}`).toBeGreaterThan(30);
    });
  }
}
