import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);
const data = await page.evaluate(() => {
  function rect(sel) { const e=document.querySelector(sel); if(!e) return null; const r=e.getBoundingClientRect(); return {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height),text:(e.innerText||'').slice(0,80).replace(/\n/g,' | ')}; }
  const all=[];
  for (const sel of ['[data-testid="antd-home"]','main','header','nav','.ant-carousel','.ant-list','.ant-card','h1','h3','input','button']) {
    document.querySelectorAll(sel).forEach((e,i)=>{ if(i<8){ const r=e.getBoundingClientRect(); all.push({sel:i, x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height), text:(e.innerText||e.getAttribute('aria-label')||'').slice(0,60)}); } });
  }
  return { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth, all };
});
console.log(JSON.stringify(data,null,2));
await browser.close();
