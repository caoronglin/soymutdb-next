/**
 * Lab Core Web Vitals + runtime-motion evidence for the built public artifact.
 *
 * Complements web-artifact-performance.spec.ts (asset budgets): this spec
 * records paint/LCP/CLS from a cold local Chromium load, counts animation
 * frames with and without `prefers-reduced-motion`, and checks the 390px
 * responsive shell for horizontal overflow. Values are single-run lab data,
 * never production RUM percentiles.
 */
import { expect, test } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

type Vitals = {
  fcpMs: number;
  lcpMs: number;
  cls: number;
  rafFramesPerSecond: number;
};

const reportPath = resolve(
  import.meta.dirname,
  "..",
  "test-results-web-performance",
  "vitals-report.json",
);

const INSTRUMENT = `(() => {
  window.__lcpMs = 0;
  window.__cls = 0;
  window.__rafFrames = 0;
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) window.__lcpMs = entry.startTime;
    }).observe({ type: "largest-contentful-paint", buffered: true });
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) window.__cls += entry.value;
      }
    }).observe({ type: "layout-shift", buffered: true });
  } catch {}
  const original = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = (callback) =>
    original((time) => {
      window.__rafFrames += 1;
      return callback(time);
    });
})();`;

async function loadAndSample(page: import("@playwright/test").Page): Promise<Vitals> {
  await page.addInitScript(INSTRUMENT);
  await page.goto("/", { waitUntil: "load" });
  await expect(page.locator("#root")).toBeAttached();
  // Let lazy home sections and the motion ticker settle.
  await page.waitForTimeout(400);
  await page.evaluate(() => {
    window.__rafFrames = 0;
  });
  await page.waitForTimeout(1_000);
  return page.evaluate(() => {
    const fcp = performance
      .getEntriesByType("paint")
      .find((entry) => entry.name === "first-contentful-paint");
    return {
      fcpMs: Number((fcp?.startTime ?? 0).toFixed(1)),
      lcpMs: Number((window.__lcpMs ?? 0).toFixed(1)),
      cls: Number((window.__cls ?? 0).toFixed(4)),
      rafFramesPerSecond: window.__rafFrames,
    };
  });
}

declare global {
  interface Window {
    __lcpMs: number;
    __cls: number;
    __rafFrames: number;
  }
}

test.describe("built public artifact vitals", () => {
  test.beforeEach(async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    // Exposed for the assertion below without leaking into the spec signature.
    (page as import("@playwright/test").Page & { __errors?: string[] }).__errors = errors;
  });

  test("records LCP/FCP/CLS and keeps the 390px shell overflow-free", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const mobile = await loadAndSample(page);
    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }));
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.innerWidth + 1);
    expect(mobile.fcpMs).toBeGreaterThan(0);
    expect(mobile.lcpMs).toBeGreaterThan(0);
    expect(mobile.lcpMs).toBeLessThanOrEqual(2_500);
    expect(mobile.cls).toBeLessThanOrEqual(0.1);

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: "no-preference" });
    const desktop = await loadAndSample(page);
    expect(desktop.lcpMs).toBeLessThanOrEqual(2_500);
    expect(desktop.cls).toBeLessThanOrEqual(0.1);
    // The shared 30fps ticker drives the WebGL hero; a live page shows frames.
    expect(desktop.rafFramesPerSecond).toBeGreaterThan(10);

    await page.emulateMedia({ reducedMotion: "reduce" });
    const reduced = await loadAndSample(page);
    // Reduced motion renders one static WebGL frame and stops the ticker; the
    // carousel must not keep an animation budget running either.
    expect(reduced.rafFramesPerSecond).toBeLessThanOrEqual(5);
    // The ticker can be idle while Ant Carousel still advances on a CSS timer,
    // so observe a real autoplay interval instead of trusting the RAF count.
    const activeSlide = () => page.locator(".ant-carousel .slick-active").first().innerText();
    const slideBefore = await activeSlide();
    await page.waitForTimeout(5_600);
    const slideStable = (await activeSlide()) === slideBefore;
    expect(slideStable).toBe(true);

    const errors = (page as import("@playwright/test").Page & { __errors?: string[] }).__errors;
    expect(errors).toEqual([]);

    mkdirSync(dirname(reportPath), { recursive: true });
    writeFileSync(
      reportPath,
      JSON.stringify(
        {
          generatedAt: new Date().toISOString(),
          target: "http://127.0.0.1:4178/",
          methodology:
            "Single cold local Chromium load per viewport/motion mode; LCP/CLS from PerformanceObserver, RAF count over a 1s steady-state window. Lab data, not RUM.",
          mobile390: { ...mobile, ...overflow },
          desktop1440: desktop,
          reducedMotion: { ...reduced, slideStable },
        },
        null,
        2,
      ) + "\n",
      "utf8",
    );
  });
});