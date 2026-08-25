import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);
const info = await page.evaluate(() => {
  const txt = document.body.innerText;
  const h1 = [...document.querySelectorAll('h1')].map(e => e.innerText);
  const h2 = [...document.querySelectorAll('h2')].map(e => e.innerText.slice(0,120));
  const buttons = [...document.querySelectorAll('button,a')].slice(0,30).map(e => (e.innerText||e.textContent||'').trim()).filter(Boolean);
  const navLinks = [...document.querySelectorAll('nav a')].map(e => e.innerText.trim()).filter(Boolean);
  const imgs = [...document.querySelectorAll('img')].map(e => e.getAttribute('src')||e.getAttribute('alt')).filter(Boolean);
  const rootStyle = getComputedStyle(document.body);
  const heroExists = !!document.querySelector('[class*="hero"], [class*="Hero"]');
  return {
    title: document.title,
    bodyText: txt.slice(0, 2000),
    h1, h2, buttons, navLinks, imgs, heroExists,
    bodyBg: rootStyle.backgroundColor,
    bodyFontSize: rootStyle.fontSize,
    bodyColor: rootStyle.color,
  };
});
console.log(JSON.stringify(info, null, 2));
await browser.close();
