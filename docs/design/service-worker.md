# Service Worker 静态资源缓存（apps/web）

> 实现：`apps/web/public/sw.js`（模板）→ 构建期 `apps/web/scripts/gen-sw.js` 注入 → `dist/sw.js`
> 注册：`apps/web/src/react-app.tsx`（production + 开关，window load 后延迟注册）
> 参考：MDN [Service Worker API](https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API)、[Cache API](https://developer.mozilla.org/en-US/docs/Web/API/Cache)

## 1. 目标与边界

- 静态资源（Umi/Webpack content-hash 产物）**离线可用、秒开复用**：首次访问后，JS/CSS/字体不再依赖网络。
- SSG HTML 页（index + 10 内容页 + 51 个 sample 页）**离线可读**：network-first，断网回退缓存。
- API 请求**绝不缓存**（认证、动态数据）。
- SW 是渐进增强：注册失败、SW 脚本错误、缓存配额满都静默降级，不阻断应用。

## 2. 缓存策略（fetch 分层）

对每个请求按顺序匹配，命中即止：

| # | 请求特征 | 策略 | 缓存 | 说明 |
|---|----------|------|------|------|
| 0 | 非 GET（POST 等） | network only | — | 登录、上传、搜索等一律放行 |
| 0 | 跨域（origin ≠ self） | network only | — | 生产 API 源、CF 分析 beacon、JBrowse 资源 |
| 1 | `/api/` 路径 | network only | — | dev 下 `/api` 走 Umi proxy，生产走跨域源（被上一条覆盖） |
| 2 | `/assets/*.{hash}.*` 或旧版 `*-{hash}.*`（8+ 位 hash） | **cache-first** | 当前 site variant 的 static cache | 内容 immutable，命中即返回；未命中网络 + 回填 |
| 3 | `mode === "navigate"` | **network-first** | `soymutdb-runtime` | 在线永远拿最新 HTML；离线回退该页缓存 → 兜底首页 |
| 4 | 其他静态资源（非 hash 字体、favicon、samples 等） | **stale-while-revalidate** | `soymutdb-runtime` | 命中先返回，后台静默刷新；未命中等网络 |

hash 判定正则：`/\/assets\/[^/]+[._-][A-Za-z0-9_-]{8,}(?:\.async)?\.[a-z0-9]+$/`（同时接受 Umi 点号 hash 和旧版连字符 hash）。

## 3. 生命周期

- **install**：打开 `soymutdb-static-v{CACHE_VERSION}`，逐条 `cache.add()` 预缓存 `__PRECACHE_MANIFEST__` 清单（`Promise.allSettled` 容错：单个文件 404/失败不阻塞激活），随后 `skipWaiting()` 立即接管。
- **activate**：删除所有 `soymutdb-static-v*` 中非当前版本者（版本轮换），随后 `clients.claim()` 控制所有已打开页面。
- **版本轮换与站点隔离**：`CACHE_VERSION = siteVariant + 构建时间戳 + precache 清单内容 sha256 前 8 位`。静态与运行时缓存都按变体命名；查找只在当前变体的 cache 内执行，不使用 `caches.match()` 跨缓存查询。

## 4. 构建集成（apps/web/scripts/gen-sw.js）

构建链（`apps/web/package.json`）：

```
Umi Max build (external/internal) → static routes → CSP finalizer → optional gzip → gen-sw → release manifest
```

gen-sw.js 职责：

1. 递归扫描当前变体 `dist/{external,internal}` 下 content-hashed bundles（排除 `.gz`/`.map`）→ precache 清单（**相对路径**）。
2. 计算 `CACHE_VERSION`（时间戳 + 清单 hash）。
3. 读取 `public/sw.js` 模板，替换 `__PRECACHE_MANIFEST__` / `__CACHE_VERSION__` → 写 `dist/sw.js`。
4. 同步重生成 `dist/sw.js.gz`（gzip-compress 在更早步骤运行，其产物是未替换占位符的模板版本；规则与 gzip-compress 一致：≥1KB 且压缩变小）。

约束：

- **sw.js 不参与 precache**；SSG HTML 由策略 3（network-first）处理。
- 清单用相对路径，SW 内以 `registration.scope` 为基准解析；Umi `base`/`publicPath` 按变体显式配置，SW 作用域随部署前缀隔离。

## 5. 注册条件（react-app.tsx）

```ts
if (import.meta.env.PROD && import.meta.env.VITE_SW_ENABLED !== "false") {
    window.addEventListener("load", () => { /* register */ });
}
```

- 仅**生产构建**注册（dev 不注册，避免开发缓存干扰）。
- `VITE_SW_ENABLED=false` 可禁用（.env / CI 环境变量）。
- 延迟到 `window load` 后，避免与首屏渲染竞争。
- 注册 URL：以 Umi 注入的 `BASE_URL` 拼接 `sw.js`；external 与 internal artifact 使用各自独立的 base path。
- 注册/更新失败静默 catch。

## 6. CSP

`worker-src 'self' blob:` 已加入三处（必须保持同步，浏览器取交集）：

- `apps/web/config/config.ts`（Umi index 的初始 meta CSP）
- `apps/web/public/_headers`（Umi 复制至每个变体 artifact）
- `apps/web/scripts/csp.ts`（静态路由生成后同步各 HTML CSP）

`'self'` 放行同源 sw.js；`blob:` 为未来 blob worker 预留（现有 lazy Web Worker 走独立文件，不受影响）。

## 7. 验证

```bash
node --check apps/web/dist/sw.js                       # SW 语法
grep -c "__PRECACHE_MANIFEST__" apps/web/dist/sw.js    # 0 → 已替换（无残留占位符）
node -e "..."                                          # manifest 条目数与 dist/assets 实际文件数一致
```

浏览器实测（上线后）：DevTools → Application → Service Workers 显示 activated & running；Network 面板二次访问 hash 资源命中 `(from ServiceWorker)`；DevTools → Network → Offline 下刷新页面仍可打开已访问页面。
