# SoyMutDB — Cloudflare Pages 静态部署

> ## ⚠️ 非主路径（已放弃，仅保留参考）
>
> 前端静态托管已改用 **GitHub Pages**（`.github/workflows/pages.yml` → gh-pages 分支，站点
> https://caoronglin.github.io/soymutdb-next/），本文档所述 Cloudflare Pages 方案**未启用**。
> 保留仅为历史参考；其中 CSP/`_headers` 占位符、preview 隔离等约束对任何静态托管仍适用。
> 当前部署架构见 **docs/design/deployment-architecture.md**。
> 当前主入口已迁移至 **[开发者架构与部署](../docs/dev/architecture-and-deployment.md)**；本文仅作历史参考。
>
> ---

> 本文档描述将三个前端应用（`apps/web`、`apps/jbrowse`、`apps/admin`）作为**纯静态站点**部署到 Cloudflare Pages 的完整流程。
> **Cloudflare 只承载静态前端 dist**；API 与数据面保留自管后端（docker-compose）。不使用 Workers / Functions / KV / D1 / Queues。

---

## 1. 架构总览

```
                         ┌──────────────────────────────────────────────┐
  浏览器 ──► Cloudflare Pages（静态 dist，无 Functions）                 │
  │         ├─ soymutdb-web     (apps/web/dist)     门户（SSG + SPA）    │
  │         ├─ soymutdb-jbrowse (apps/jbrowse/dist) JBrowse 2 基因组浏览器 │
  │         └─ soymutdb-admin   (apps/admin/dist)   管理端（可选）        │
  │                                                                      │
  │         HTTPS  + _headers（安全头/CSP/缓存）+ _redirects（SPA fallback）
  │                                                                      │
  └───────────────► 自管后端（docker-compose，独立 API 域名）             │
                    ├─ API:      https://api.<domain>   （/api/v1/*, /jbrowse-data/*）
                    ├─ 数据库 / 对象存储 / 任务队列（不在本文档范围）
                    └─ CORS 白名单: SOYMUTDB_CORS_ORIGINS（精确 origin，拒绝 *）
```

**既定约束**

- `VITE_CDN_ENABLED=false`：所有第三方库（Fontsource 字体、echarts、gsap 等）本地打包，CSP 才能保持 `script-src 'self'` 收紧。
- 生产 build 的 `VITE_API_BASE_URL` 指向**独立的生产 API 域名**。
- Preview build 的 `VITE_API_BASE_URL` **只能指向 staging API，禁止连生产**。
- 认证依赖 HttpOnly refresh cookie（`Path=/api/v1/auth`、`Secure`）。带凭据的 CORS 不支持通配 origin —— 后端 `SOYMUTDB_CORS_ORIGINS` 必须**精确列出**每个允许的前端 origin（生产域名 + 固定 preview/staging origin），`*` 会被拒绝。
- 本仓库中 `_headers` / `_redirects` 是**静态文件**，生产与 preview 共享同一份 —— preview 联调时需要临时把 CSP 占位符换成 staging origin（见 §7）。

---

## 2. 仓库内已有的部署配置

| 文件 | 作用 |
| --- | --- |
| `apps/{web,jbrowse,admin}/public/_headers` | Cloudflare Pages 自定义响应头（安全头、CSP、缓存策略） |
| `apps/{web,jbrowse,admin}/public/_redirects` | SPA fallback `/* /index.html 200` |
| `apps/{web,jbrowse,admin}/.env.example` | 各应用 build 期环境变量说明（生产 / preview 两组） |
| `apps/web/index.html`、`apps/web/scripts/base-template.ts` | 门户 `<meta>` CSP（与 `_headers` 的 CSP 保持同一份内容） |

Vite 构建无需改动：三个应用均使用默认 `base: '/'`（Pages 自定义域名部署在根路径）与默认 `public/` 目录（`_headers`/`_redirects` 会自动复制进 `dist/`）。

### 2.1 缓存策略（`_headers`）

| 路径 | Cache-Control | 说明 |
| --- | --- | --- |
| `/assets/*` | `public, max-age=31536000, immutable` | Vite 产物带内容 hash，可永久缓存 1 年 |
| `/`、`/*.html` | `public, max-age=0, must-revalidate` | HTML 始终重新校验（与 Pages 默认行为一致，显式声明） |
| 其他（SSG 无扩展名路径等） | Pages 默认 `public, max-age=0, must-revalidate` | `/*` 规则故意不写 Cache-Control，避免与 `/assets/*` 规则合并成逗号拼接的非法值 |

### 2.2 安全头（`/*` 全局规则）

```text
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()
Strict-Transport-Security: max-age=31536000
Content-Security-Policy: <见下>
```

- **HSTS 不含 `includeSubDomains`**：API/staging 等兄弟子域不由 Cloudflare 托管，避免强制它们走 HTTPS 造成浏览器拒连。
- Pages 对 preview URL 自动附加 `X-Robots-Tag: noindex`，无需处理。

### 2.3 CSP 摘要（占位符见 §8 替换清单）

| 应用 | CSP 要点 |
| --- | --- |
| web | `script-src 'self' 'unsafe-inline'`（SSG 页含内联 bootstrap/主题脚本）；`style-src 'self' 'unsafe-inline'`（Vite 内联样式）；`img-src 'self' data: https:`；`connect-src 'self' https://api.example.com`；`frame-src 'self' https://jbrowse.example.com`（/browse 页 iframe 嵌入 jbrowse） |
| jbrowse | `script-src 'self'`（纯 Vite SPA，无内联脚本）；`worker-src 'self' blob:`；`img-src 'self' data: blob: https:`；`connect-src 'self' https://api.example.com`；`frame-ancestors 'self' https://portal.example.com https://admin.example.com`（允许门户/管理端嵌入） |
| admin | `script-src 'self'`；`connect-src 'self' https://api.example.com`；`frame-ancestors 'none'`（禁止被嵌入，与 nginx `X-Frame-Options: DENY` 一致） |

> **meta CSP 与 header CSP 同时生效（取交集）**：门户的 `<meta>` CSP（`index.html` 与 SSG 模板 `base-template.ts`）已与 `_headers` 保持同一份文本。修改其中一处必须同步另一处；只改 header 而漏改 meta，`frame-src`/`connect-src` 会被 meta 的 `default-src 'self'` 截断，iframe 嵌入 jbrowse 将静默失败。
>
> 若未来重新启用 `VITE_CDN_ENABLED=true`，需同时在两处 `script-src` 中加入 CDN 域名。

### 2.4 SPA fallback（`_redirects`）

每个应用末尾一行：`/* /index.html 200`。

- Pages 优先服务**真实静态文件**：门户的 SSG 产物（`index` + 10 个内容页 + 51 个样品详情页 + `sitemap.xml`）以无扩展名路径（如 `/about`）被真实 HTML 命中，`/assets/*` hash 文件同理 —— 均不会被 fallback 吞掉（与 Pages 无顶层 `404.html` 时的内建 SPA 行为一致；已写入部署后 curl 验证清单）。
- 未命中任何文件的路径（TanStack Router 客户端路由、jbrowse 深链等）回落到 `index.html`。
- 注意：Pages 的 `_headers` 匹配基于**请求路径**，因此 SSG 无扩展名路径走 `/*` 规则（安全头 + Pages 默认 no-cache），无需逐一列举。

---

## 3. 前置条件

1. Cloudflare 账号；门户 / jbrowse / admin 的生产域名解析到 Pages（`*.example.com` 建议用独立子域：`www`、`jbrowse`、`admin`）。
2. 自管后端已上线：生产 API 域名与 staging API 域名均已配置 HTTPS（refresh cookie 为 `Secure`）。
3. 后端 CORS 白名单：生产 `SOYMUTDB_CORS_ORIGINS` 含生产前端 origin；staging `SOYMUTDB_CORS_ORIGINS` 含 staging/preview 前端 origin。
4. 仓库环境：pnpm 10（`packageManager: pnpm@10.0.0`），Node ≥ 20（建议 22）。

---

## 4. 创建 Pages 项目（每个应用一个）

| 项目名（建议） | 应用 | 必选 |
| --- | --- | --- |
| `soymutdb-web` | `apps/web` | ✅ |
| `soymutdb-jbrowse` | `apps/jbrowse` | ✅ |
| `soymutdb-admin` | `apps/admin` | ⭕ 可选（也可仅保留自管 nginx 部署） |

创建步骤（Cloudflare Dashboard → Workers & Pages → Create → Pages → Connect to Git）：

1. 连接仓库，选择分支（生产分支建议 `main`）。
2. **Production branch**：`main`；Preview 自动对 PR/分支生效。
3. **Root directory**：留空（仓库根，pnpm workspace 需要根 lockfile）。
4. **Build command**（见下表）；**Build output directory**：`apps/<app>/dist`。
5. **Environment variables**：按 §5 配置。
6. 建议额外设置 `NODE_VERSION=22`（或 20），并在 build command 中先 `corepack enable`（仓库声明了 `packageManager: pnpm@10.0.0`，corepack 会按其锁定 pnpm 版本）。

| 项目 | Build command | 输出目录 |
| --- | --- | --- |
| web | `corepack enable && pnpm install --frozen-lockfile && pnpm --filter @soymutdb/web build` | `apps/web/dist` |
| jbrowse | `corepack enable && pnpm install --frozen-lockfile && pnpm --filter @soymutdb/jbrowse build` | `apps/jbrowse/dist` |
| admin | `corepack enable && pnpm install --frozen-lockfile && pnpm --filter @soymutdb/admin build:web` | `apps/admin/dist` |

> web 的 build 会运行 SSG 脚本（`ssg-build` / `generate-samples`），构建机连不上 API 时自动回退到内嵌数据（构建不失败，但页面内容为回退数据）。想让生产 SSG 页面拿到最新布局/数据，可另设 build 期变量 `SOYMUTDB_API_URL`（staging/生产 API 均可，仅构建期访问，非 secret）与可选 `SOYMUTDB_SITE_URL`。构建机访问不到内网 API 时保持默认回退即可。

---

## 5. 环境变量表

所有 `VITE_*` 均为 **build 期**变量，会打进产物；**严禁放置任何 secret**。

### 5.1 `apps/web`（门户）

| 变量 | 生产 build | Preview build | 说明 |
| --- | --- | --- | --- |
| `VITE_API_BASE_URL` | `https://api.example.com` ✅替换 | `https://api-staging.example.com`（**禁止生产**） | API 源；须在对应后端 `SOYMUTDB_CORS_ORIGINS` 白名单内 |
| `VITE_CDN_ENABLED` | `false` | `false` | 保持 false，CSP 才能收紧 |
| `VITE_JBROWSE_URL` | `https://jbrowse.example.com` ✅替换 | staging jbrowse origin | /browse 页 iframe 地址；须在门户 CSP `frame-src` 内 |
| `VITE_CLOUDFLARE_ANALYTICS_TOKEN` | 可选，建议设置 | 可选（预览也可统计） | Cloudflare Web Analytics beacon token（见 §5.5） |

可选：`VITE_DEMO_MODE=false`。

### 5.5 Cloudflare Web Analytics（门户访问统计，beacon 方式）

门户（`apps/web`）的访问统计通过 **Cloudflare Web Analytics 免费 JS beacon** 实现：构建时若设置了 `VITE_CLOUDFLARE_ANALYTICS_TOKEN`，vite 的 `transformIndexHtml` 会把 `index.html` 中的占位符替换为一行静态 `<script>`（`https://static.cloudflareinsights.com/beacon.min.js` + `data-cf-beacon`），同时放宽 `<meta>` CSP 放行 beacon 域名。

- **纯静态、合规**：beacon 是浏览器端静态 JS，不需要 Workers / Functions / KV / D1 —— 与"Cloudflare 只做静态托管"的既定约束一致；隐私优先、无 cookie。
- **静态托管也能用**：不需要把域名代理进 Cloudflare（gh-pages 等纯静态托管同样适用）。
- **未设置 token 时构建零影响**：占位符被移除、CSP 保持原样，产物与启用前行为一致。

配置步骤：

1. **创建 Web Analytics 站点**：Cloudflare Dashboard → Analytics & Logs → Web Analytics → **Add a site**，选择门户域名（如 `www.example.com`）。无需修改 DNS/代理。
2. **复制 token**：创建后打开站点的安装代码片段，从 `data-cf-beacon` 中复制 token（十六进制短字符串）。
3. **设置 Pages 环境变量**：`soymutdb-web` 项目 → **Settings → Environment variables** → 添加 `VITE_CLOUDFLARE_ANALYTICS_TOKEN`（Production 与 Preview 均设置）。变量值保存后不可回读。
4. **重新部署**：触发一次新的生产部署，token 才会写入构建出的 `index.html`。
5. **验证**：见 §6.5。

**CSP 同步要求**（meta 与 `_headers` 取交集）：

- `apps/web/public/_headers` 的 CSP 已**静态**放行 `https://static.cloudflareinsights.com`（`script-src`）与 `https://cloudflareinsights.com`（`connect-src`）——无 token 时页面不加载 beacon，放行本身无副作用。
- `apps/web/index.html` 的 `<meta>` CSP 与 SSG 模板（`scripts/base-template.ts`）均由构建逻辑在**有 token 时**动态放宽（与 `_headers` 保持同一份文本）。两者交集在启用/未启用 beacon 时均成立，勿只改一处。
- **SSG 页面同样计入统计**：`ssg-build.ts` 会用 base-template 覆盖 Vite 生成的 `dist/index.html`，因此 beacon 注入逻辑同时存在于 Vite `transformIndexHtml`（dev / 纯 vite build）与 `base-template.ts`（SSG 产物，最终发布版）——两者读取同一个 `VITE_CLOUDFLARE_ANALYTICS_TOKEN`，产出相同标记。所有 SSG 页（`/about` 等）与 SPA 入口 `index.html` 均携带 beacon。

### 5.2 `apps/jbrowse`（基因组浏览器）

| 变量 | 生产 build | Preview build | 说明 |
| --- | --- | --- | --- |
| `VITE_API_BASE_URL` | `https://api.example.com` ✅替换 | `https://api-staging.example.com`（**禁止生产**） | API 源（认证/会话） |
| `VITE_JBROWSE_DATA_URL` | `https://api.example.com/jbrowse-data` ✅替换 | staging 数据面 | 数据平面（FASTA/轨道文件）；默认相对路径 `/jbrowse-data`，Cloudflare 上必须显式配置为绝对 URL |

### 5.3 `apps/admin`（管理端，可选）

| 变量 | 生产 build | Preview build | 说明 |
| --- | --- | --- | --- |
| `VITE_API_BASE_URL` | `https://api.example.com` ✅替换 | `https://api-staging.example.com`（**禁止生产**） | API 源；Tauri 桌面版未设置时回退 `http://127.0.0.1:8000`，与 Cloudflare web 版无关 |

### 5.4 后端（不归本仓库前端管理，仅提醒）

- `SOYMUTDB_CORS_ORIGINS`：精确 origin 列表，**不含 `*`**；生产与 staging 各自维护。
- 登录后前端会使用带凭据请求 + HttpOnly refresh cookie，因此 preview 域名（形如 `https://<hash>.<project>.pages.dev`）必须**显式加入 staging 后端白名单**才能登录联调；任意新建的临时 preview 默认拿不到生产认证（这是既定安全行为）。

---

## 6. 部署后验证清单

### 6.1 缓存头

```bash
# hash 资源 → immutable，1 年
curl -sI https://www.example.com/assets/<hash>.js | grep -i cache-control
# 期望: Cache-Control: public, max-age=31536000, immutable

# HTML → no-cache / must-revalidate
curl -sI https://www.example.com/ | grep -i cache-control
# 期望: Cache-Control: public, max-age=0, must-revalidate

# SSG 真实页面（无扩展名路径）→ 同样 no-cache
curl -sI https://www.example.com/about | grep -i cache-control
```

### 6.2 真实文件优先于 SPA fallback

```bash
# SSG 页面必须返回真实 HTML（内容含 SSG 标题），而不是 index.html 兜底
curl -s https://www.example.com/about | grep -o "<title>[^<]*</title>"
curl -s https://www.example.com/samples/SMDB-00001 | grep -o "<title>[^<]*</title>"

# 未知路径 → index.html 兜底（SPA 路由可用）
curl -s https://www.example.com/browse/unknown-route | grep -o "<title>[^<]*</title>"
```

### 6.3 CSP 不阻断应用自身资源

```bash
# 响应头含 CSP 且 connect-src 为 self + API 域名
curl -sI https://www.example.com/ | grep -i content-security-policy

# 浏览器控制台无 CSP violation（重点检查）：
#   - 门户 /browse 页能加载 jbrowse iframe（frame-src）
#   - 页面字体（Fontsource 本地 woff2）加载正常
#   - echarts 懒加载 chunk（/assets/*.js）加载正常
#   - 搜索 worker（/assets/*.worker*.js，script-src 'self'）正常
```

### 6.4 Preview 只连 staging

```bash
# 在 preview URL 的浏览器控制台确认请求指向 staging API 域名；
# 确认后端日志中 preview origin 命中 staging SOYMUTDB_CORS_ORIGINS。
# 用 staging 账号登录成功 = CORS + cookie 链路通。
```

### 6.5 Web Analytics beacon 验证

```bash
# 本地构建验证（无 token → 不注入）：
grep -c "cloudflareinsights" apps/web/dist/index.html || echo "无 token 未注入（预期）"

# 本地构建验证（有 token → 注入）：
VITE_CLOUDFLARE_ANALYTICS_TOKEN=testtoken pnpm --filter @soymutdb/web build
grep -c "cloudflareinsights\|testtoken" apps/web/dist/index.html   # 应 ≥1
```

线上验证：

1. 打开门户 → 查看网页源代码（Ctrl/Cmd+U）→ 搜索 `cloudflareinsights`：能找到即表示当前部署已注入 beacon。
2. Cloudflare Dashboard → Web Analytics：部署后短时间内出现该站点流量即表示 beacon 生效（数据延迟数分钟属正常）。
3. 浏览器控制台无 CSP violation：beacon 加载不报 `Refused to load the script`（CSP 放行与 `_headers`/`<meta>` 交集相关，见 §5.5）。

---

## 7. Preview 部署注意事项

- **构建期变量**：在 Pages Dashboard → Settings → Environment variables 中按 **Production / Preview** 两组分别配置（Preview 组为 staging 值）。
- **CSP 占位符**：`_headers` 与门户 `<meta>` CSP 是仓库内静态文本，生产与 preview 共享。preview 联调时，把其中 `connect-src` / `frame-src` / `frame-ancestors` 的占位域名**临时**替换为 staging 域名（提交到 preview 分支），联调完成后改回。生产部署前必须确认占位符已替换为生产域名。
- **生产认证隔离**：preview 域名不在生产 `SOYMUTDB_CORS_ORIGINS` 内，无法在生产 API 上登录 —— 这是既定安全行为，不要为 preview 放开生产白名单。
- 若需要多套固定 preview 域名（如 `staging.<project>.pages.dev`），可配置 **Branch deployment controls / custom branch alias**，并把该固定域名加入 staging 后端白名单。

---

## 8. 上线前占位符替换清单（遗留项）

| 位置 | 占位符 | 替换为 |
| --- | --- | --- |
| `apps/web/public/_headers`（CSP `connect-src`） | `https://api.example.com` | 生产 API origin |
| `apps/web/public/_headers`（CSP `frame-src`） | `https://jbrowse.example.com` | jbrowse 生产 origin |
| `apps/web/index.html`（meta CSP） | 同上两处 | 同上 |
| `apps/web/scripts/base-template.ts`（SSG 模板 meta CSP） | 同上两处 | 同上 |
| `apps/jbrowse/public/_headers`（CSP `connect-src`） | `https://api.example.com` | 生产 API origin |
| `apps/jbrowse/public/_headers`（CSP `frame-ancestors`） | `https://portal.example.com` / `https://admin.example.com` | 门户 / 管理端生产 origin |
| `apps/admin/public/_headers`（CSP `connect-src`） | `https://api.example.com` | 生产 API origin |
| 各应用 `.env.example` / Pages Dashboard | `https://api.example.com` 等 | 真实生产 / staging 域名（Dashboard 中配置） |

> 占位符域名若未替换即上线：CSP 只多放行一个不存在的域名，不会放行真实 API —— 表现为 API 请求被 CSP 拦截（安全失败），不会静默放行。

---

## 9. 回滚与排障

- **回滚**：Dashboard → Deployments → 选择历史部署 → **Rollback to this deployment**（Pages 原生支持，立即生效）。
- **缓存未更新**：新部署后仍看到旧内容 → 该自定义域名的 **Caching → Purge Everything**（Pages 项目文件每次部署都会刷新 CDN 缓存；仅当给自定义域名配置了额外 Cache Rules 时才可能出现陈旧内容）。
- **CSP 拦截**：浏览器控制台报 `Refused to connect/frame/script ...` → 检查 §8 占位符是否替换、meta 与 header 两处 CSP 是否一致（取交集，缺一即收紧）。
- **登录失败（403/预检失败）**：确认前端 origin 精确命中后端 `SOYMUTDB_CORS_ORIGINS`（带凭据 CORS 不接受 `*`）；preview 域名是否已加入 staging 白名单。
- **构建失败**：确认 `corepack enable` 在前、`pnpm install --frozen-lockfile` 使用仓库根 lockfile（Root directory 留空）；Node 版本用 `NODE_VERSION` 固定。

---

## 10. 非目标（明确不做）

- 不使用 Cloudflare Workers / Pages Functions / KV / D1 / Queues / R2 —— 一切动态能力保留在自管后端。
- 不在 `VITE_*` 变量中存放任何 secret。
- Preview 不连接生产 API / 数据库。
- 不在此文档范围内修改后端 CORS、认证 cookie 或 docker-compose 部署。
