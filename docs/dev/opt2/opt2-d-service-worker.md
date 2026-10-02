# OPT2-07 — 门户注册 Service Worker（D）

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

- 状态：**已完成**（单元测试 + 类型 + lint + 生产构建 + 真实浏览器实测全部通过）
- 责任人：D
- 依据：`docs/dev/opt2/OPT2-CHECKLIST.md` OPT2-07；`docs/dev/vue-parity/README.md` §5
- 涉及文件（仅本人所有权内）：
  - 新建 `apps/web/src/lib/service-worker.ts`
  - 新建 `apps/web/src/lib/service-worker.test.ts`
  - 修改 `apps/web/src/main.ts`（挂载后注册）
  - 修改 `apps/web/public/sw.js`（模板：API 守卫收紧，见 §3）

## 1. 缺口（改前）

构建链**已经**产出 `apps/web/dist/sw.js`（`apps/web/scripts/gen-sw.js` 注入 `__CACHE_VERSION__` / `__PRECACHE_MANIFEST__` 占位符），但全仓库没有任何 `register()` 调用（`git grep -n "serviceWorker\\|sw.js" apps/web/src` 在改前无命中，只有 `dist/` 产物与 `docs/design/service-worker.md` 的设计描述）。因此 SW 永不安装、永不激活：离线可用 / hash 资源二次加载复用 / 版本轮换整套策略都是死代码。

`docs/design/service-worker.md` §5 甚至已写出「应该长什么样」的注册代码，但从未落到 `main.ts`。

## 2. 实现（`apps/web/src/lib/service-worker.ts`）

`export async function registerServiceWorker(options?): Promise<ServiceWorkerRegistration | undefined>`

| 需求 | 实现 |
| --- | --- |
| 仅生产注册 | `enabled` 默认 `import.meta.env.PROD && !(VITE_SW_ENABLED=false)`；dev 直接 `return undefined`，避免 HMR 与缓存互斗 |
| 尊重子路径部署 | `resolveScriptUrl(base)` 把 `sw.js` 拼到 `import.meta.env.BASE_URL` 后（缺尾斜杠会补），**不硬编码 `/sw.js`**；scope 交给浏览器按脚本路径推导 |
| 能力守卫 | `navigator?.serviceWorker` 不存在 → 静默返回；`location.protocol` 非 http/https → 静默返回 |
| 失败只 warn | `try/catch` 包住 `register()`，仅 `console.warn("[service-worker] registration failed", err)`，**从不 reject** |
| 克制的更新行为 | 不注册 `load` 监听、不在导航时调 `registration.update()`；返回注册句柄供将来做「有新版本」提示 |
| 可测性 | `enabled` / `base` / `nav` / `loc` 全部可注入（`import.meta.env.PROD` 在 vitest 下不可改写） |

`apps/web/src/main.ts`：在 `app.mount("#app")` 与 `dataset.appReady = "true"` 之后 `void registerServiceWorker();`（不 await，SW 永不阻塞应用就绪），并附注释说明「为什么生产 only、为什么与 base 相关、为什么失败可吞」。构建产物中确认该调用点存在：

```
...Xs.mount("#app");document.documentElement.dataset.appReady="true";qd();
```

契约说明：`OPT2-CHECKLIST.md` §2 写的是 `(): void`，任务书允许「或注册句柄」，故返回 `Promise<ServiceWorkerRegistration | undefined>`（更利于将来更新提示）；调用方 `void` 使用，行为不变。

## 3. `public/sw.js` 缓存分层逐条核对

逐条核对模板（改后行号见 `apps/web/public/sw.js`）：

| # | 分层 | 核对结论 |
| --- | --- | --- |
| 0 | 非 GET 直接放行 | ✅ `if (request.method !== "GET") return;`（L139） |
| 0 | 跨域直接放行 | ✅ `if (url.origin !== self.location.origin) return;`（L144）——生产 API 多为独立 origin，先被这条覆盖 |
| 1 | `/api/` network-only（永不拦截） | ⚠️→✅ 见下 |
| 2 | `/assets/*-<8+hash>.<ext>` cache-first | ✅ `HASHED_ASSET_RE` 命中 → `cacheFirst()`（L152-155），命中即返回、未命中网络+回填 |
| 3 | 导航 `mode === "navigate"` network-first + 离线兜底 | ✅ `networkFirst()`（L165-168）：离线依次回退「该页缓存 → scope/index.html → scope 根 → `Response.error()`」 |
| 4 | 其他静态资源 SWR | ✅ `staleWhileRevalidate()`（L171） |

### 3.1 `/api/*` 是否会被缓存 —— 结论与修复

**原判**：字面量 `/api/*` 确实**不会**被缓存（`pathname.includes("/api/")` 命中后 `return`，不调 `respondWith`）。所有实际构建配置都覆盖到：gh-pages 子路径 `/soymutdb-next/api/v1/...`、`scripts/build-pages-artifact.sh` 的同源 `${SITE_ORIGIN}${PAGES_BASE_PATH}api/v1`、`scripts/dev-local-preview.sh` 的 `${PORTAL_ORIGIN}/api/v1`。

**但存在一处真实（潜在）漏判**：守卫用 `includes("/api/")`，**漏掉裸 `/api`**（无尾斜杠）——恰是 `VITE_API_BASE_URL` 合法的最小形态。命中漏判后请求掉进策略 4 `staleWhileRevalidate`，被写进共享的 `soymutdb-runtime`。内部站 `/api/v1/site/*?variant=internal` 是 `private, no-store`（`deploy/cloudflare.md` 第 16 行），被 `cache.put` 落盘后 `no-store` 语义即失效 → 登出 / 切换身份命中旧私有数据。

**已修模板**（`apps/web/public/sw.js` L146-154），改为按完整路径段判定，并补充隐私理由注释：

```js
if (/(?:^|\/)api(?:\/|$)/.test(pathname)) return;
```

新旧谓词差异（穷举真实路径，仅裸 `/api` 翻转，无回归）：

```
DIFF old=false new=true  /api
DIFF old=false new=true  /soymutdb-next/api
same old=true  new=true  /api/v1/search
same old=true  new=true  /soymutdb-next/api/v1/search
same old=false new=false /myapi/x
same old=false new=false /x/apiary
same old=false new=false /data/content.json
```

未改 `apps/web/scripts/gen-sw.js` 的产物契约（占位符、清单、版本号生成方式全部不变）。

## 4. 测试清单与验证证据（全部实跑）

| 命令 | 退出码 | 关键输出 |
| --- | --- | --- |
| `pnpm --filter @soymutdb/web exec vitest run src/lib/service-worker.test.ts` | `0` | `Test Files 1 passed (1)` / `Tests 9 passed (9)` |
| `pnpm --filter @soymutdb/web test` | `0` | `Test Files 44 passed (44)` / `Tests 194 passed (194)`（改前基线 `42 / 180`，只增不减） |
| `pnpm --filter @soymutdb/web typecheck` | `0` | `vue-tsc --noEmit`，0 错误 |
| `pnpm --filter @soymutdb/web lint` | `0` | `eslint src`，0 错误 |
| `VITE_API_BASE_URL=… VITE_JBROWSE_BASE_URL=… pnpm --filter @soymutdb/web build` | `0` | `[gen-sw] wrote …/dist/sw.js (7.6 KB)`；`grep -c "__CACHE_VERSION__" dist/sw.js` = `0`；`node --check dist/sw.js` OK |

新增 9 条单测（`// @vitest-environment jsdom`，`vi.stubGlobal` / `vi.stubEnv`）：dev(`enabled:false`) 不注册；生产 + `base=/soymutdb-next/` 断言 `register("/soymutdb-next/sw.js")`（用 global `navigator` 默认路径）；`base=/` → `/sw.js`；base 缺尾斜杠归一化；`register` reject → resolve `undefined` 且 `console.warn`；无 `navigator.serviceWorker` 不抛错；`file:` 协议不注册；默认 `enabled` 认 `PROD`；`VITE_SW_ENABLED=false` 关闭。

> 注：基线 `42/180` 与任务书写的 `37/165` 不同，是因为并发会话（OPT2-08 E 等）已并行加了测试；本人增量恰为 `+1 file / +9 tests`。

## 5. 真实浏览器实测（Playwright + `vite preview` :4173）

`pnpm --filter @soymutdb/web preview`（带 `VITE_API_BASE_URL`/`VITE_JBROWSE_BASE_URL`），Playwright chromium `--single-process`（沙箱线程受限时需要）：

```json
{
  "secure": true, "hasContainer": true, "count": 1,
  "scopes": ["http://127.0.0.1:4173/"],
  "active": ["activated"],
  "controller": "http://127.0.0.1:4173/sw.js"
}
```

二次加载（受 SW 控制）后探测缓存与离线：

```json
{
  "controller": "http://127.0.0.1:4173/sw.js",
  "caches": {
    "soymutdb-static-vexternal-20260926154259-0d1220dd": ["/assets/index-BPHWq0VK.js", "…其余 7 个 hash 资源"],
    "soymutdb-runtime": ["/", "/fonts/harmonyos/HarmonyOS-Sans-SC-Regular.woff2", "…"]
  },
  "afterProbe": ["…", "/not-a-real-route-probe"],
  "offlineReloadRendered": true
}
```

要点：
- precache 缓存含 8 个 hash 资源（cache-first 分层生效）；runtime 缓存含导航 HTML 与非 hash 字体（network-first / SWR 生效）。
- 探测 `fetch("/api/v1/probe")` **和** `fetch("/api/probe")` 后，**两者都不在任何缓存里**（network-only 生效；裸 `/api` 正是本次收紧的部分）。
- 同一轮里 `/not-a-real-route-probe` **有**进缓存，证明「API 没进缓存」不是「什么都没缓存」。
- `context.setOffline(true)` 后 `reload()` 仍渲染到 `dataset.appReady === "true"`，且 controller 仍在 → 离线兜底可用。

## 6. 未验证 / 残余

- 未在 **gh-pages 子路径真实部署**（`https://…/soymutdb-next/`）下验证 scope 推导：单测覆盖了 URL 拼接（`/soymutdb-next/sw.js`），但真实 origin 下的 scope/CSP 交互未跑。
- 未验证 **SW 版本轮换**（新版本 install → activate 删旧缓存）：需连续两次真实部署。
- 未验证 Chromium 之外的内核（Firefox/Safari）。
- 观察（未修，超出本项所有权范围）：`RUNTIME_CACHE = "soymutdb-runtime"` 不带 `SITE_VARIANT`，而 activate 的清理过滤是 `startsWith("soymutdb-static-v")`。若 external/internal 两站被部署到**同一 origin**（不同子路径），两个 SW 会互相删除对方的 precache（缓存名版本号里已含 variant，但删除过滤是前缀匹配，`gen-sw.js` 的注释「never collide」在清理阶段不成立）。当前文档部署（独立 origin / 独立 Pages 项目）不触发。
- 观察：`docs/design/service-worker.md` §5 描述的是「`window load` 后注册 + `VITE_SW_ENABLED` 开关」；实现改为「mount 后注册（同样非阻塞）+ `VITE_SW_ENABLED` 开关」。`VITE_SW_ENABLED` 仍未写进 `apps/web/src/vite-env.d.ts`（该文件不在本项所有权内），当前靠 vite/client 的索引签名兜住类型。
