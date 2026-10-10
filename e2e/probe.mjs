import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 1000 } });
await p.goto("http://100.77.182.76:8081/", { waitUntil: "domcontentloaded", timeout: 60000 });
await p.waitForTimeout(3500);
await p.locator('input[type="text"], input[autocomplete="username"]').first().fill("admin");
await p.locator('input[type="password"]').first().fill("LocalDev!2026");
await p.locator('button[type="submit"], button:has-text("Sign in")').first().click();
await p.waitForTimeout(9000);

console.log("=== body 顶层结构 ===");
console.log(await p.evaluate(() => {
  const walk = (el, d = 0) => {
    if (d > 3) return [];
    return [...el.children].flatMap((c) => [
      "  ".repeat(d) + `<${c.tagName.toLowerCase()} class="${(c.className || "").toString().slice(0, 58)}">`,
      ...walk(c, d + 1),
    ]);
  };
  return walk(document.body).join("\n");
}));
console.log("\n=== 侧边栏候选 ===");
console.log(await p.evaluate(() => {
  const links = [...document.querySelectorAll("a")].filter((a) => a.getAttribute("href")?.startsWith("/"));
  const first = links[0];
  return JSON.stringify({
    totalNavLinks: links.length,
    firstHref: first?.getAttribute("href"),
    firstParentChain: (() => { let e = first, out = []; while (e && out.length < 6) { out.push(`${e.tagName.toLowerCase()}.${(e.className||"").toString().split(" ")[0]}`); e = e.parentElement; } return out; })(),
    navElements: document.querySelectorAll("nav").length,
    asideElements: document.querySelectorAll("aside").length,
  }, null, 2);
}));
await b.close();
