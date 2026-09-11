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
  overlaps: Array<{ first: string; second: string; area: number; ratio: number }>;
  overflowing: Array<{ tag: string; id: string; className: string; left: number; right: number; width: number }>;
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
      return style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0" && style.pointerEvents !== "none" && rect.width > 0 && rect.height > 0;
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
    const ignored = (element: HTMLElement) =>
      element.hasAttribute("data-layout-overlap-ok") ||
      element.getAttribute("aria-hidden") === "true" ||
      /^(increase|decrease) value$/i.test(element.getAttribute("aria-label") ?? "") ||
      ["absolute", "fixed", "sticky"].includes(getComputedStyle(element).position);
    const label = (element: HTMLElement) =>
      `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ""} ${(element.innerText || element.getAttribute("aria-label") || "").trim()}`.slice(0, 100);
    const overlapViolations: Array<{ first: string; second: string; area: number; ratio: number }> = [];
    const candidates = Array.from(document.querySelectorAll<HTMLElement>(
      "header, main, footer, nav, section, article, form, [role=region], [data-layout-zone], .card-lift",
    )).filter((element) => visible(element) && !ignored(element));
    const recordOverlap = (first: HTMLElement, second: HTMLElement, threshold: number) => {
      if (first.contains(second) || second.contains(first)) return;
      const a = first.getBoundingClientRect();
      const b = second.getBoundingClientRect();
      const area = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) *
        Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
      const smaller = Math.min(a.width * a.height, b.width * b.height);
      const ratio = smaller > 0 ? area / smaller : 0;
      if (area > 8 && ratio > threshold) {
        overlapViolations.push({ first: label(first), second: label(second), area: Math.round(area), ratio: Number(ratio.toFixed(3)) });
      }
    };
    for (let i = 0; i < candidates.length; i += 1) {
      for (let j = i + 1; j < candidates.length; j += 1) {
        if (candidates[i].parentElement === candidates[j].parentElement) recordOverlap(candidates[i], candidates[j], 0.15);
      }
    }
    const controls = Array.from(document.querySelectorAll<HTMLElement>("a, button, input, select, textarea, [role=button]"))
      .filter((element) => visible(element) && !ignored(element));
    for (let i = 0; i < controls.length; i += 1) {
      for (let j = i + 1; j < controls.length; j += 1) recordOverlap(controls[i], controls[j], 0.25);
    }
    const overflowing = Array.from(document.querySelectorAll<HTMLElement>("body *"))
      .filter(visible)
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName.toLowerCase(),
          id: element.id,
          className: typeof element.className === "string" ? element.className.slice(0, 120) : "",
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          width: Math.round(rect.width),
        };
      })
      .filter((item) => item.left < -1 || item.right > document.documentElement.clientWidth + 1)
      .slice(0, 20);
    const overlaps = overlapViolations.slice(0, 20);
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
      overlaps,
      overflowing,
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
      expect(metric.document.scrollWidth, `${route.path} has page-level horizontal overflow at ${viewport.name}: ${JSON.stringify(metric.overflowing)}`).toBeLessThanOrEqual(metric.document.clientWidth + 1);
      expect(metric.visible.main, `${route.path} has no visible main content at ${viewport.name}`).toBeTruthy();
      expect(metric.visible.bodyTextLength, `${route.path} rendered an empty page at ${viewport.name}`).toBeGreaterThan(30);
      expect(metric.overlaps, `${route.path} has unintentional component/control overlap at ${viewport.name}: ${JSON.stringify(metric.overlaps)}`).toEqual([]);
    });
  }
}
