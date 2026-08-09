/**
 * SoyMutDB Service Worker — 静态资源缓存
 *
 * 构建期由 apps/web/scripts/gen-sw.js 处理（构建链最后一步）：
 *   CACHE_VERSION 常量     → 缓存版本号（构建时间戳 + precache 清单内容 hash）
 *   PRECACHE_MANIFEST 常量 → precache 文件清单（dist/assets 下全部构建产物，相对路径）
 *   两处均为占位符替换，最终产物见 dist/sw.js
 *
 * 缓存策略分层（详见 docs/design/service-worker.md）：
 *   1. /api/ 请求              → network only（绝不拦截）
 *   2. assets 下 hash 文件      → cache-first（内容 immutable，命中即返回）
 *   3. 导航请求 (mode=navigate) → network-first，离线回退缓存 / 兜底首页（SSG 页离线可用）
 *   4. 其他静态资源             → stale-while-revalidate（先缓存后刷新）
 *
 * 部署注意：站点托管在 gh-pages 子路径（如 https://caoronglin.github.io/soymutdb-next/）
 * 且 vite 未配置 base，因此所有路径均以 registration.scope 为基准动态解析，
 * 不依赖 vite base 配置。跨域请求（生产 API 源、CF 分析 beacon 等）一律放行。
 */
"use strict";

/* ============================ 构建期注入 ============================ */
const CACHE_VERSION = "__CACHE_VERSION__";
const PRECACHE_MANIFEST = __PRECACHE_MANIFEST__;

/* ============================ 缓存名 ============================ */
// 静态缓存随版本号整体轮换（hash 资源 immutable，旧版本在 activate 时删除）
const PRECACHE_CACHE = `soymutdb-static-v${CACHE_VERSION}`;
// 运行时缓存（导航 HTML / 非 hash 静态资源），跨版本保留，内容逐项刷新
const RUNTIME_CACHE = "soymutdb-runtime";

/* ============================ 生命周期 ============================ */

// install：预缓存全部构建产物。逐条容错 —— 单个文件 404 / 网络失败
// 不阻塞整个 SW 激活（旧版本文件在 gh-pages 上可能已被清理）。
self.addEventListener("install", (event) => {
    event.waitUntil(
        caches
            .open(PRECACHE_CACHE)
            .then((cache) =>
                Promise.allSettled(
                    PRECACHE_MANIFEST.map((rel) => cache.add(rel).catch(() => {})),
                ),
            )
            // 立即接管（不等旧 SW 控制的页面全部关闭）
            .then(() => self.skipWaiting()),
    );
});

// activate：清理旧版本静态缓存 + 立即控制所有已打开的客户端。
self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches
            .keys()
            .then((keys) =>
                Promise.all(
                    keys
                        .filter((k) => k.startsWith("soymutdb-static-v") && k !== PRECACHE_CACHE)
                        .map((k) => caches.delete(k)),
                ),
            )
            .then(() => self.clients.claim()),
    );
});

/* ============================ fetch 策略 ============================ */

// Vite 产物形如 /assets/index-D3f4x7a9.js / /assets/antd-9zY2kLm1.css ——
// 文件名内含 8+ 位内容 hash，immutable，可安全 cache-first。
const HASHED_ASSET_RE = /\/assets\/[^/]+-[A-Za-z0-9_-]{8,}\.[a-z0-9]+$/;

/** 相对路径（相对 SW scope，即部署前缀）→ 完整 URL。 */
function scopeUrl(rel) {
    return new URL(rel, self.registration.scope).href;
}

/** 缓存写入容错（配额满 / opaque 响应等失败不影响主流程）。 */
async function cachePut(cacheName, request, response) {
    try {
        const cache = await caches.open(cacheName);
        await cache.put(request, response);
    } catch {
        /* ignore — cache is best-effort */
    }
}

/** 策略 2：cache-first —— hash 资源命中即返回；未命中走网络并回填缓存。 */
async function cacheFirst(request) {
    const cached = await caches.match(request);
    if (cached) return cached;
    const response = await fetch(request);
    if (response.ok) {
        await cachePut(PRECACHE_CACHE, request, response.clone());
    }
    return response;
}

/** 策略 3：network-first —— 在线优先（HTML 永远最新）；离线回退缓存，兜底首页。 */
async function networkFirst(request) {
    try {
        const response = await fetch(request);
        if (response.ok) {
            await cachePut(RUNTIME_CACHE, request, response.clone());
        }
        return response;
    } catch {
        // 离线：先试该请求自身缓存，再试 scope 根页（index.html / SSG 入口）
        const cached = await caches.match(request);
        if (cached) return cached;
        const root = await caches.match(scopeUrl("./index.html"));
        if (root) return root;
        const scopeRoot = await caches.match(new URL(self.registration.scope).href);
        if (scopeRoot) return scopeRoot;
        return Response.error();
    }
}

/** 策略 4：stale-while-revalidate —— 命中先返回，后台刷新；未命中等网络。 */
async function staleWhileRevalidate(request) {
    const cache = await caches.open(RUNTIME_CACHE);
    const cached = await cache.match(request);
    const refresh = fetch(request)
        .then(async (response) => {
            if (response.ok) {
                await cachePut(RUNTIME_CACHE, request, response.clone());
            }
            return response;
        })
        .catch(() => undefined);
    if (cached) {
        // 命中：立即返回缓存，后台静默刷新（不阻塞响应）
        void refresh;
        return cached;
    }
    return (await refresh) ?? Response.error();
}

self.addEventListener("fetch", (event) => {
    const { request } = event;
    // 只处理 GET；POST 等（登录、上传）一律放行
    if (request.method !== "GET") return;

    const url = new URL(request.url);

    // 跨域请求（生产 API 源、CF 分析 beacon、JBrowse iframe 资源等）一律不拦截
    if (url.origin !== self.location.origin) return;

    const { pathname } = url;

    // 策略 1：API 请求 network only（dev 下 /api 走 vite proxy，生产走跨域源）
    if (pathname.includes("/api/")) return;

    // 策略 2：assets 下 hash 文件 → cache-first
    if (HASHED_ASSET_RE.test(pathname)) {
        event.respondWith(cacheFirst(request));
        return;
    }

    // 策略 3：导航请求（SSG HTML 页）→ network-first，离线回退缓存
    if (request.mode === "navigate") {
        event.respondWith(networkFirst(request));
        return;
    }

    // 策略 4：其他静态资源（非 hash 字体、favicon、samples 等）→ SWR
    event.respondWith(staleWhileRevalidate(request));
});
