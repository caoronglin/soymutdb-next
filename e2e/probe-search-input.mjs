/* Scratch evidence probe for OPT2-04.
 *
 * Documents why the SearchView form's antdv `Input` cannot drive the search by
 * DOM events alone, and that the header omnibox (a native `<input v-model>`)
 * can. Run with the internal artifact served at http://localhost:4175/:
 *
 *   node static-server.mjs "$PWD/../apps/web/dist/internal" 4175 / &
 *   node probe-search-input.mjs
 */
import { chromium } from "playwright";

const BASE = "http://localhost:4175/";
const INTERNAL_ID = "INT-MUT-000001";
const PUBLIC_ID = "SMDB-00001";

const browser = await chromium.launch();
const context = await browser.newContext({ locale: "en-US", viewport: { width: 1440, height: 900 } });
const page = await context.newPage();

const searchRequests = [];
await page.route(/.*/, async (route) => {
  const req = route.request();
  const url = new URL(req.url());
  const origin = req.headers()["origin"];
  const cors = {
    "access-control-allow-origin": origin ?? "*",
    "access-control-allow-credentials": "true",
    "access-control-allow-headers": "authorization,content-type,x-soymutdb-release",
    "access-control-allow-methods": "GET,POST,OPTIONS",
  };
  if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
  if (url.pathname.startsWith("/api/") || url.hostname === "api.internal.soymutdb.test") {
    if (/\/search(\/internal)?$/.test(url.pathname)) {
      searchRequests.push(`${req.method()} ${url.pathname}${url.search}`);
    }
    const json = (b, s = 200) =>
      route.fulfill({ status: s, contentType: "application/json", headers: cors, body: JSON.stringify(b) });
    if (url.pathname.endsWith("/auth/login")) return json({ access_token: "t", expires_in: 900 });
    if (url.pathname.endsWith("/genes/assemblies")) return json([{ id: "1", name: "Wm82.a4.v1", version: "a4.v1", is_default: true }]);
    if (/\/genes\/assemblies\/[^/]+\/chromosomes$/.test(url.pathname)) return json([{ id: "1", assembly_id: "1", name: "chr01", length: 100000, order: 0 }]);
    if (/\/table-views\//.test(url.pathname)) return json({ kind: "mutant_lines", columns: [], actions: {} });
    if (url.pathname.endsWith("/news/featured")) return json({ featured: [], carousel: [] });
    if (url.pathname.endsWith("/news")) return json({ items: [], total: 0 });
    if (/\/mutants\/[^/]+\/phenotypes$/.test(url.pathname)) return json([]);
    if (/\/mutants\/[^/]+$/.test(url.pathname)) return json({ public_id: PUBLIC_ID, name: "Mock mutant line 1", species: "Glycine max", mutagen: "EMS", cultivar: "Williams 82", variant_count: 3, is_public: true });
    if (url.pathname.endsWith("/search/internal")) {
      return json({
        query: url.searchParams.get("query") ?? "",
        mutants: [{ entity_type: "mutant_line", public_id: PUBLIC_ID, internal_id: INTERNAL_ID, name: "Mock mutant line 1", matched_field: "internal_id", match_type: "exact", is_public: true, release_id: 7, url: `/mutants/${PUBLIC_ID}` }],
        genes: [], total_count: 1,
      });
    }
    if (url.pathname.endsWith("/search")) {
      return json({ query: url.searchParams.get("query") ?? "", results: [{ type: "mutant_line", id: PUBLIC_ID, name: `Mock mutant line 1 (${INTERNAL_ID})`, url: `/mutants/${PUBLIC_ID}`, assembly: "Wm82.a4.v1", release_id: 7 }], by_type: { mutant_line: 1 }, cursor: null, next_cursor: null, has_more: false, total_count: 1 });
    }
    return json({}, 404);
  }
  return route.fallback();
});

async function ready() {
  await page.waitForFunction(() => document.documentElement.dataset.appReady === "true", null, { timeout: 15000 });
}

await page.goto(`${BASE}login?redirect=%2Fsearch`);
await ready();
await page.getByTestId("login-email").fill("researcher@example.org");
await page.getByTestId("login-password").fill("correct-horse-battery-staple");
await page.getByTestId("login-submit").click();
await page.waitForURL(/\/search$/);
await ready();

const formInput = page.getByTestId("search-input");
console.log("== SearchView form field: " + await formInput.first().evaluate((n) => n.tagName + "." + n.className.split(" ").slice(0, 2).join(".")));

async function probe(label, action, submitVia) {
  await page.goto(`${BASE}search`);
  await ready();
  const el = page.getByTestId("search-input");
  await el.waitFor();
  const before = searchRequests.length;
  await action(el);
  console.log(`[${label}] inputValue=${JSON.stringify(await el.inputValue())} domValue=${JSON.stringify(await el.evaluate((n) => n.value))}`);
  if (submitVia === "enter") await el.press("Enter");
  else await page.getByTestId("search-submit").click();
  await page.waitForTimeout(1200);
  console.log(`[${label}] URL=${page.url()} rows=${await page.getByTestId("search-result-row").count()} searchApiCalls=${searchRequests.length - before}`);
}

await probe("fill", (el) => el.fill(INTERNAL_ID), "click");
await probe("pressSequentially", async (el) => { await el.click(); await el.pressSequentially(INTERNAL_ID, { delay: 15 }); }, "click");
await probe("pressSequentially+Enter", async (el) => { await el.click(); await el.pressSequentially(INTERNAL_ID, { delay: 15 }); }, "enter");
await probe("fill+input-event", async (el) => { await el.fill(INTERNAL_ID); await el.evaluate((n) => n.dispatchEvent(new Event("input", { bubbles: true }))); }, "click");
await probe("fill+input+change", async (el) => {
  await el.fill(INTERNAL_ID);
  await el.evaluate((n) => { n.dispatchEvent(new Event("input", { bubbles: true })); n.dispatchEvent(new Event("change", { bubbles: true })); });
}, "click");

console.log("\n== Header omnibox (native <input v-model>)");
await page.goto(`${BASE}search`);
await ready();
const omni = page.getByTestId("portal-search-input");
await omni.click();
await omni.pressSequentially(INTERNAL_ID, { delay: 15 });
console.log("[omnibox] inputValue=", JSON.stringify(await omni.inputValue()));
const before = searchRequests.length;
await page.getByTestId("portal-search-submit").click();
await page.waitForTimeout(1500);
console.log(`[omnibox] URL=${page.url()} resultRows=${await page.getByTestId("search-result-row").count()} internalRows=${await page.getByTestId("search-internal-row").count()} searchApiCalls=${searchRequests.length - before}`);
console.log("[omnibox] search-input value after navigation:", JSON.stringify(await formInput.inputValue()));
console.log("[omnibox] search requests:", searchRequests.slice(before).join(" | "));

await browser.close();
