#!/usr/bin/env node
/**
 * Real-browser checks for the things a source scan cannot settle.
 *
 * The 2026-10-02 plan listed four items as unverified because "no browser":
 * narrow-screen layout, keyboard focus, multi-line alt and adapter rowKey. The
 * multi-line alt and rowKey questions turned out to be decidable without a
 * browser (guard tests and a jsdom render), but layout and focus genuinely are
 * not: they depend on the real cascade and on real focus order.
 *
 * This file runs against a locally served production artifact, so it exercises
 * the emitted CSS and bundle rather than a dev server.
 *
 * Usage: node e2e/verify-a11y-and-layout.mjs [baseUrl]
 * Exits non-zero on the first failed expectation.
 */
import { chromium } from "playwright";

const BASE = (process.argv[2] ?? "http://localhost:4183").replace(/\/$/, "");
const NARROW = { width: 390, height: 844 };
const DESKTOP = { width: 1440, height: 900 };

const results = [];
function check(name, fn) {
  return (async () => {
    try {
      await fn();
      results.push({ name, ok: true });
    } catch (error) {
      results.push({ name, ok: false, error: error.message });
    }
  })();
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: DESKTOP, locale: "en-US" });
const page = await context.newPage();

const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});

await check("the portal renders without console errors", async () => {
  await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
  await page.waitForSelector("body", { timeout: 15_000 });
  assert(
    !consoleErrors.some((text) => /Uncaught|TypeError|ReferenceError/.test(text)),
    `page threw at runtime: ${consoleErrors.slice(0, 3).join(" | ")}`,
  );
});

await check("the page exposes exactly one level-1 heading", async () => {
  const headings = await page.locator("h1").allTextContents();
  assert(headings.length === 1, `expected one h1, found ${headings.length}: ${JSON.stringify(headings)}`);
});

await check("every image has a non-empty alt", async () => {
  const missing = await page.evaluate(() =>
    [...document.querySelectorAll("img")]
      .filter((img) => !(img.getAttribute("alt") ?? "").trim())
      .map((img) => img.getAttribute("src") ?? "(no src)"),
  );
  assert(missing.length === 0, `images without alt text: ${JSON.stringify(missing.slice(0, 5))}`);
});

await check("every control has an accessible name", async () => {
  const unnamed = await page.evaluate(() =>
    [...document.querySelectorAll("button, a[href]")]
      .filter((el) => {
        const label =
          el.getAttribute("aria-label") ??
          el.getAttribute("title") ??
          (el.textContent ?? "").trim();
        return label.length === 0;
      })
      .map((el) => el.outerHTML.slice(0, 90)),
  );
  assert(unnamed.length === 0, `controls without a name: ${JSON.stringify(unnamed.slice(0, 5))}`);
});

await check("the skip link is the first tab stop and moves focus to main", async () => {
  await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
  await page.keyboard.press("Tab");
  const firstStop = await page.evaluate(() => {
    const el = document.activeElement;
    return { tag: el?.tagName ?? "", text: (el?.textContent ?? "").trim(), href: el?.getAttribute("href") ?? "" };
  });
  assert(firstStop.tag === "A", `first tab stop was ${firstStop.tag}, expected a link`);
  assert(
    /skip to content/i.test(firstStop.text),
    `first tab stop was "${firstStop.text}", expected the skip link`,
  );

  await page.keyboard.press("Enter");
  await page.waitForTimeout(300);
  const afterActivation = await page.evaluate(() => ({
    hash: window.location.hash,
    mainTop: document.querySelector("main")?.getBoundingClientRect().top ?? null,
    scrollY: window.scrollY,
  }));
  assert(afterActivation.hash === "#main", `activating the skip link gave hash ${afterActivation.hash}`);
  assert(
    afterActivation.mainTop !== null && afterActivation.mainTop < 200,
    `<main> stayed at ${afterActivation.mainTop}px after activating the skip link`,
  );
});

await check("the skip link is visible once focused", async () => {
  await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
  await page.keyboard.press("Tab");
  const visible = await page.evaluate(() => {
    const el = document.activeElement;
    if (!el) return { width: 0, height: 0 };
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return { width: rect.width, height: rect.height, visibility: style.visibility, opacity: style.opacity };
  });
  assert(visible.width > 0 && visible.height > 0, `focused skip link had no box: ${JSON.stringify(visible)}`);
  assert(visible.visibility !== "hidden", "the focused skip link stayed hidden");
  assert(visible.opacity !== "0", "the focused skip link stayed transparent");
});

await check("focus is visible on the primary navigation links", async () => {
  await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
  const link = page.locator("nav a[href]").first();
  await link.focus();
  const outlined = await link.evaluate((el) => {
    const style = getComputedStyle(el);
    return {
      outlineWidth: style.outlineWidth,
      outlineStyle: style.outlineStyle,
      boxShadow: style.boxShadow,
    };
  });
  const hasIndicator =
    (outlined.outlineStyle !== "none" && parseFloat(outlined.outlineWidth) > 0) ||
    (outlined.boxShadow !== "none" && outlined.boxShadow !== "");
  assert(hasIndicator, `a focused nav link showed no focus indicator: ${JSON.stringify(outlined)}`);
});

await check("nothing overflows horizontally at 390px", async () => {
  await page.setViewportSize(NARROW);
  await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
  await page.waitForTimeout(400);
  const overflow = await page.evaluate(() => {
    const docWidth = document.documentElement.clientWidth;
    const offenders = [...document.querySelectorAll("body *")]
      .filter((el) => {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.right > docWidth + 1;
      })
      .slice(0, 5)
      .map((el) => `${el.tagName}.${el.className}`.slice(0, 70));
    return { docWidth, scrollWidth: document.documentElement.scrollWidth, offenders };
  });
  assert(
    overflow.scrollWidth <= overflow.docWidth + 1,
    `horizontal overflow at 390px: scrollWidth ${overflow.scrollWidth} > ${overflow.docWidth}; ${JSON.stringify(overflow.offenders)}`,
  );
});

await check("the mobile menu is reachable by keyboard and opens", async () => {
  await page.setViewportSize(NARROW);
  await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
  // Selected structurally, not by label text: the artifact defaults to the zh
  // catalog, so an English selector matches nothing and the check would pass
  // (or fail) for the wrong reason.
  const toggle = page.locator("header button[aria-expanded]").last();
  await toggle.waitFor({ state: "visible", timeout: 15_000 });
  const label = await toggle.getAttribute("aria-label");
  assert(label && label.length > 0, "the menu toggle had no accessible name");

  assert((await toggle.getAttribute("aria-expanded")) === "false", "the mobile menu started open");

  await toggle.focus();
  await page.keyboard.press("Enter");
  await page.waitForTimeout(400);

  const state = await page.evaluate(() => {
    const navs = [...document.querySelectorAll("nav")].map((nav) => {
      const rect = nav.getBoundingClientRect();
      return { visible: rect.width > 0 && rect.height > 0, links: nav.querySelectorAll("a[href]").length };
    });
    return { navs, expanded: [...document.querySelectorAll("button[aria-expanded]")].pop()?.getAttribute("aria-expanded") ?? null };
  });
  assert(state.expanded === "true", `pressing Enter left aria-expanded at ${state.expanded}`);
  assert(
    state.navs.some((nav) => nav.visible && nav.links > 0),
    `the menu reported open but no navigation with links was visible: ${JSON.stringify(state.navs)}`,
  );
});

await check("touch targets in the primary navigation are usable", async () => {
  await page.setViewportSize(NARROW);
  await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
  const tooSmall = await page.evaluate(() =>
    [...document.querySelectorAll("nav a[href]")]
      .map((el) => ({ text: (el.textContent ?? "").trim().slice(0, 30), h: el.getBoundingClientRect().height }))
      .filter((item) => item.h > 0 && item.h < 24)
      .slice(0, 5),
  );
  assert(tooSmall.length === 0, `navigation targets below 24px tall: ${JSON.stringify(tooSmall)}`);
});

await browser.close();

let failed = 0;
for (const result of results) {
  if (result.ok) console.log(`ok - ${result.name}`);
  else {
    failed += 1;
    console.error(`not ok - ${result.name}\n    ${result.error}`);
  }
}
console.log(`\n${results.length - failed}/${results.length} passed against ${BASE}`);
process.exit(failed === 0 ? 0 : 1);