# SoyMutDB 全量优化方案设计与部署计划

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

> 文档版本：1.0 | 生成日期：2025-08-26
> 覆盖范围：前端（web/admin/jbrowse）、后端（api/worker/mcp）、共享包、CI/CD、Docker、Nginx

> **2026-09-26 校正（历史文档）**：本文为迁移前（React 期）计划。`packages/i18n` 与 `packages/motion`
> 已移除。三端曾迁到 Vue 3，Vue 现已完全退役（`scripts/check-vue-retirement.mjs` 断言通过），
> 当前为 React 19 + Umi Max 4；测试清单以当前 `packages/` 与各 `package.json` 为准。

---

## 目录

- [Phase 1 — 生产关键修复（P0）](#phase-1)
- [Phase 2 — 安全与一致性（P1）](#phase-2)
- [Phase 3 — 代码质量与测试覆盖（P2）](#phase-3)
- [Phase 4 — 工程卫生（P3）](#phase-4)
- [部署与回滚策略](#deployment)

---

## Phase 1 — 生产关键修复（P0）

### 1.1 Admin Vite React chunk 匹配修复

**问题**：`apps/admin/vite.config.ts:62` 使用宽泛的 `id.includes("node_modules/react")`，会匹配到 `@ant-design/react-slick`、`react-day-picker` 等依赖 `rc-*` 的包，形成 `react → rc-* → antd → react` 的 ES module 初始化循环，生产环境白屏。

**方案**：将 Web 端已验证的精确正则同步到 Admin：

```diff
 // apps/admin/vite.config.ts:62
-if (id.includes("node_modules/react") || id.includes("node_modules/react-dom")) return "react";
+if (
+    /node_modules\/(react|react-dom|react-is|scheduler|use-sync-external-store)(\/|@)/.test(id)
+) {
+    return "react";
+}
```

**验证**：
1. `pnpm --filter @soymutdb/admin build` 成功
2. 检查 `dist/assets/` 下 react chunk 不包含 `rc-` 或 `@ant-design` 模块
3. 生产预览 `pnpm --filter @soymutdb/admin preview` 加载无白屏

**回滚**：git revert 单文件，无数据迁移。

---

### 1.2 CI Turbo 远程缓存

**问题**：CI 仅有 `cache: pnpm`（npm store 缓存），但 Turbo 任务缓存（`.turbo`）未启用远程或 action cache，每次 PR 全量重建。

**方案 A — GitHub Actions Cache（零成本，推荐）**：

```yaml
# .github/workflows/ci.yml — frontend job
- name: Setup Node 24
  uses: actions/setup-node@v4
  with:
    node-version: 26.13.0
    cache: pnpm

- name: Cache Turbo
  uses: actions/cache@v4
  with:
    path: .turbo
    key: turbo-${{ runner.os }}-${{ github.sha }}
    restore-keys: |
      turbo-${{ runner.os }}-
```

在 `turbo.json` 中确保 `inputs` 覆盖被追踪（默认追踪源文件和环境变量）。

**方案 B — Vercel Remote Cache（跨分支共享，更强）**：

```yaml
env:
  TURBO_API: ${{ secrets.TURBO_API }}
  TURBO_TOKEN: ${{ secrets.TURBO_TOKEN }}
  TURBO_TEAM: ${{ vars.TURBO_TEAM }}
```

在 Vercel Dashboard 创建 token，填入 GitHub Secrets。

**验证**：第二次推送同一代码时 CI 日志显示 `FULL TURBO`（全缓存命中），构建时间下降 50%+。

**回滚**：移除 cache step 即可。

---

## Phase 2 — 安全与一致性（P1）

### 2.1 CSRF 保护统一到 api-client

**问题**：`apps/web/src/lib/api.ts` 有 `secureRequest`（CSRF cookie → header），但 Admin 直接用共享 `http`，mutation 不带 CSRF。

**方案**：

#### 步骤 1：在 api-client 中新增 CSRF 层

```ts
// packages/api-client/src/csrf.ts
const CSRF_COOKIE_NAME = "soymutdb_csrf";
const CSRF_HEADER = "X-CSRF-Token";

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export function attachCsrf(options: RequestOptions, method: string): RequestOptions {
  const unsafe = ["POST", "PUT", "PATCH", "DELETE"];
  if (!unsafe.includes(method.toUpperCase())) return options;
  const csrf = readCookie(CSRF_COOKIE_NAME);
  if (!csrf) return options;
  return { ...options, headers: { ...options.headers, [CSRF_HEADER]: csrf } };
}
```

#### 步骤 2：在 auth.ts 的 `authRequest` 中集成 CSRF

```ts
// packages/api-client/src/auth.ts
import { attachCsrf } from "./csrf";

export async function authRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  return request<T>(path, attachCsrf(options, method));
}
```

#### 步骤 3：Admin 直接使用 `authRequest`

```ts
// apps/admin/src/routes/content.tsx — 替换 http.post → authRequest
import { authRequest } from "@soymutdb/api-client";
await authRequest("/admin/content/pages", { method: "POST", json: payload });
```

#### 步骤 4：删除 web/src/lib/api.ts 的 CSRF 逻辑

Web 端 `secureRequest` 简化为直接调用 `authRequest`（CSRF 已内置）。

#### 测试

```ts
// packages/api-client/src/csrf.test.ts
test("attaches CSRF header on POST", () => {
  document.cookie = "soymutdb_csrf=test-token";
  const result = attachCsrf({ method: "POST" }, "POST");
  expect(result.headers["X-CSRF-Token"]).toBe("test-token");
});

test("skips CSRF on GET", () => {
  const result = attachCsrf({ method: "GET" }, "GET");
  expect(result.headers).toBeUndefined();
});
```

**回滚**：恢复 web/src/lib/api.ts 的 `secureRequest`，Admin 回到 `http`。

---

### 2.2 重试策略集成到传输层

**问题**：`withRetry` 导出但无人调用；仅 401 后重试一次；瞬态 5xx/网络错误无重试。

**方案**：

```ts
// packages/api-client/src/client.ts — 增强 withRetry

export async function withRetry<T>(
  fn: () => Promise<T>,
  maxRetries = 2,
): Promise<T> {
  let lastErr: unknown;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      const retryable = isRetryableError(err);
      if (!retryable || attempt === maxRetries) throw err;
      const delay = getRetryDelay(err, attempt);
      await new Promise((r) => setTimeout(r, delay));
    }
  }
  throw lastErr;
}

function isRetryableError(err: unknown): boolean {
  if (err instanceof ApiError) {
    // 超时、网关错误、服务不可用、过多请求
    return [408, 429, 502, 503, 504].includes(err.status);
  }
  // 网络错误（TypeError: Failed to fetch）
  return err instanceof TypeError;
}

function getRetryDelay(err: unknown, attempt: number): number {
  // 尊重 Retry-After header
  if (err instanceof ApiError && err.details?.retryAfter) {
    return Number(err.details.retryAfter) * 1000;
  }
  // 指数退避 + 抖动：500ms, 1000ms, 2000ms...
  return 500 * 2 ** attempt + Math.random() * 100;
}
```

在 `authRequest` 中为 GET 请求自动包装：

```ts
export async function authRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const isIdempotent = ["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase());
  const exec = () => request<T>(path, attachCsrf(options, method));
  return isIdempotent ? withRetry(exec, 1) : exec();
}
```

> **注意**：POST/PUT/DELETE 默认不重试（非幂等），除非调用方显式声明 `options.idempotent: true`。

**回滚**：`withRetry` 回退为仅超时重试。

---

### 2.3 设计系统去重 — 共享 antd-theme

**问题**：`apps/web/src/lib/antd-theme.ts` 和 `apps/admin/src/lib/antd-theme.ts` 实现相同的 token、字体、locale、motion 策略。

**方案**：

#### 步骤 1：新建 `packages/design-system`

```
packages/design-system/
├── package.json
├── tsconfig.json
├── src/
│   ├── index.ts          # 导出 createAntdTheme, tokens, types
│   ├── antd-theme.ts     # 从 web 迁移，去除 app 特定逻辑
│   ├── tokens.ts         # ANTD_PRIMARY_HEX, ANTD_PRIMARY_OKLCH, ANTD_FONT_FAMILY
│   └── types.ts          # EffectiveMotionMode, ThemeOptions
└── tests/
    └── antd-theme.test.ts
```

#### 步骤 2：共享核心，注入差异

```ts
// packages/design-system/src/antd-theme.ts
export interface ThemeOptions {
  dark?: boolean;
  motion?: EffectiveMotionMode;
  /** App 特定的 locale 解析器 */
  resolveLocale?: (lang: string) => Promise<Locale>;
}

export function createAntdTheme(opts?: ThemeOptions): ThemeConfig {
  const dark = opts?.dark ?? false;
  // ... 共享逻辑（与当前 web 版一致）
}

// App 端只需注入差异
// apps/admin/src/lib/antd-theme.ts
import { createAntdTheme, isAdminDark } from "@soymutdb/design-system";
export { createAntdTheme, isAdminDark };
```

#### 步骤 3：两个 app 的 antd-theme.ts 简化为 re-export

```ts
// apps/web/src/lib/antd-theme.ts（简化后）
export { createAntdTheme, ANTD_PRIMARY_HEX, ANTD_PRIMARY_OKLCH } from "@soymutdb/design-system";
```

**回滚**：恢复两个 app 的独立 antd-theme.ts。

---

## Phase 3 — 代码质量与测试覆盖（P2）

### 3.1 共享工具去重（cn + format）

**方案**：

#### 步骤 1：在 shared 包新增工具模块

```ts
// packages/shared/src/cn.ts
type ClassValue = string | false | null | undefined;
export function cn(...values: ClassValue[]): string {
  return values.filter(Boolean).join(" ");
}

// packages/shared/src/format.ts
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat().format(value);
}
export function formatFileSize(bytes: number | null | undefined): string { /* ... */ }
export function formatPercent(value: number | null | undefined, decimals = 1): string { /* ... */ }
export function truncate(value: string, maxLength: number): string { /* ... */ }
export function formatDate(iso: string | null | undefined): string { /* ... */ }
// 基因组特有格式化留在 app-local（formatPosition, formatMb, jbrowseUrl, compactGeneId）
```

#### 步骤 2：更新 shared 的 exports map

```json
// packages/shared/package.json
{
  "exports": {
    ".": { "types": "./src/index.ts", "import": "./src/index.ts" },
    "./cn": { "types": "./src/cn.ts", "import": "./src/cn.ts" },
    "./format": { "types": "./src/format.ts", "import": "./src/format.ts" }
  }
}
```

```ts
// packages/shared/src/index.ts
export * from "./page-builder";
export * from "./cn";
export * from "./format";
```

#### 步骤 3：两个 app 改为从 shared 导入

```ts
// 替换 apps/web/src/lib/cn.ts 和 apps/admin/src/lib/cn.ts
import { cn } from "@soymutdb/shared";
// 替换 apps/web/src/lib/format.ts 和 apps/admin/src/lib/format.ts 的公共函数
import { formatNumber, formatFileSize } from "@soymutdb/shared";
```

**验证**：`pnpm typecheck && pnpm test` 通过，grep 确认无残留重复文件。

---

### 3.2 测试补全计划

#### packages/shared 测试

```
packages/shared/tests/
├── page-builder.test.ts       # normalizePageDefinition, 递归验证, v1 升级
├── cn.test.ts                  # 边界值：空、false、undefined
└── format.test.ts              # 零、负数、NaN、极大数、Unicode
```

#### packages/i18n 测试

```
packages/i18n/tests/
├── language-detection.test.ts  # navigator.language, localStorage, SSR fallback
├── resource-loading.test.ts    # 按需 import, 缺失 key fallback
└── ssr-safety.test.ts          # window undefined 时不崩溃
```

#### packages/motion 组件测试

```
packages/motion/tests/
├── reveal.test.tsx             # IntersectionObserver mock, unmount cleanup
├── count-up.test.tsx           # requestAnimationFrame, reduced-motion skip
├── magnetic-button.test.tsx    # pointer events, cleanup
└── reduced-motion.test.tsx     # prefers-reduced-motion media query
```

#### 配置 vitest

```ts
// packages/motion/vitest.config.ts
import { defineConfig } from "vitest/config";
export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    globals: true,
  },
});
```

---

### 3.3 Widget 运行时类型安全

**方案**：为 `soymutdb-widget.ts` 的 `any` 断言定义窄类型

```ts
// apps/web/src/components/soymutdb-widget.ts

// 替换 any 的 Trusted Types
interface TrustedTypePolicy {
  createHTML: (s: string, ...args: unknown[]) => string;
  createScript: (s: string, ...args: unknown[]) => string;
}
interface TrustedTypePolicyFactory {
  createPolicy: (name: string, rules: Partial<TrustedTypePolicy>) => TrustedTypePolicy;
}
declare global {
  interface Window {
    trustedTypes?: TrustedTypePolicyFactory;
  }
}

// Navigator.connection
interface NetworkInformation extends EventTarget {
  effectiveType: "slow-2g" | "2g" | "3g" | "4g";
  saveData: boolean;
}
declare global {
  interface Navigator {
    connection?: NetworkInformation;
  }
}

// requestIdleCallback
declare global {
  interface Window {
    requestIdleCallback?: (cb: (deadline: IdleDeadline) => void) => number;
    cancelIdleCallback?: (id: number) => void;
  }
}
```

---

### 3.4 版本统一（vitest + vite catalog）

```yaml
# pnpm-workspace.yaml catalog 新增
catalog:
  react: 19.2.0
  react-dom: 19.2.0
  typescript: 5.9.3
  vite: 6.4.3
  antd: 6.6.1
  vitest: 4.1.9        # ← 统一到 4.x
```

```diff
// apps/web/package.json
-  "vitest": "^3.2.6",
+  "vitest": "catalog:",
-  "vite": "^6.0.0",
+  "vite": "catalog:",

// apps/admin/package.json
-  "vitest": "^4.1.9",
+  "vitest": "catalog:",
-  "vite": "^6.0.0",
+  "vite": "catalog:",

// packages/api-client/package.json
-  "vitest": "^3.0.0",
+  "vitest": "catalog:",
```

运行 `pnpm install` 更新 lockfile。

---

## Phase 4 — 工程卫生（P3）

### 4.1 Nginx 安全头补全

```diff
 // infra/docker/web-nginx.conf
+    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

> 仅在 HTTPS 终端生效（HTTP 下浏览器忽略 HSTS）。

---

### 4.2 .dockerignore 补全

```diff
 // .dockerignore
  node_modules
  **/node_modules
  .venv
  **/dist
  .trash
  .slim
  artifacts
  reports
  **/.cache
  **/coverage
  *.log
  .env
  .env.*
  .ruff_cache
  __pycache__
  .pytest_cache
  .pip
+ .git
+ .github
+ .agent-teams
+ .ai-memory
+ .opencode
+ .codex
+ .turbo
+ docs
+ e2e
+ tests
+ .mypy_cache
+ .pnpm-store
+ .tmp-store
+ ui-r
+ recreations
+ knip.json
+ eslint.config.js
+ AGENTS.md
+ README.md
```

---

### 4.3 ESLint no-console 规则

```diff
 // eslint.config.js rules 块内新增
+            "no-console": ["warn", { allow: ["warn", "error"] }],
```

> 使用 warn 而非 error，避免阻断现有 pipeline；新代码无法悄悄引入 `console.log`。

---

### 4.4 Docker gzip 压缩脚本去重

```bash
# infra/docker/precompress.sh
#!/bin/sh
find "$1" -type f \(
    -name "*.js" -o -name "*.css" -o -name "*.html" -o
    -name "*.svg" -o -name "*.json" -o -name "*.woff" -o
    -name "*.woff2" -o -name "*.ttf"
\) -exec gzip -k -9 {} \;
```

```diff
 // infra/docker/Dockerfile.web / Dockerfile.admin
-RUN find apps/web/dist -type f \( ... \) -exec gzip -k -9 {} \; || true
+COPY infra/docker/precompress.sh /tmp/precompress.sh
+RUN sh /tmp/precompress.sh apps/web/dist
```

---

### 4.5 Knip 配置收窄

```json
// knip.json — 逐步移除宽泛忽略
{
  "ignore": [
    "**/dist/**", "**/coverage/**", "**/generated/**", "**/node_modules/**",
-   "apps/admin/src/components/**",
-   "apps/web/src/components/**"
  ]
}
```

> 为动态入口（widget loader、route codegen）添加 `entry` 配置替代目录忽略。

---

## 部署与回滚策略

### 部署顺序总览

```
Phase 1 (P0)          Phase 2 (P1)           Phase 3 (P2)          Phase 4 (P3)
─────────────────────────────────────────────────────────────────────────────────────
1.1 Admin Vite  ──→  2.1 CSRF 统一  ──→  3.1 工具去重  ──→  4.1 Nginx HSTS
1.2 CI Turbo    ──→  2.2 重试策略    ──→  3.2 测试补全  ──→  4.2 .dockerignore
                    2.3 设计系统    ──→  3.3 类型安全   ──→  4.3 no-console
                                       3.4 版本统一   ──→  4.4 Docker 去重
                                                          4.5 Knip 收窄
```

### 每个 Phase 的部署检查清单

#### Phase 1 — 部署后验证

| 检查项 | 命令 | 期望结果 |
|--------|------|----------|
| Admin 构建成功 | `pnpm --filter @soymutdb/admin build` | exit 0 |
| Admin 无白屏 | `pnpm --filter @soymutdb/admin preview` + 浏览器检查 | 页面正常渲染 |
| React chunk 不含 rc-* | `grep -l "rc-" dist/assets/react-*.js` | 无匹配 |
| CI 缓存命中 | 第二次推送同代码 | `FULL TURBO` 日志 |

#### Phase 2 — 部署后验证

| 检查项 | 命令/操作 | 期望结果 |
|--------|----------|----------|
| Admin POST 带 CSRF | DevTools Network → 请求头有 `X-CSRF-Token` | ✅ |
| Web POST 仍带 CSRF | 同上 | ✅ |
| 重试日志 | 模拟 503 → 查看自动重试 | 2 次重试后失败 |
| 设计系统一致性 | Web/Admin 主题色对比 | ΔE < 1 |

#### Phase 3 — 部署后验证

| 检查项 | 命令 | 期望结果 |
|--------|------|----------|
| vitest 统一 | `pnpm list vitest -r` | 所有包 4.1.9 |
| vite 统一 | `pnpm list vite -r` | 所有 app 6.4.3 |
| 无重复 cn.ts | `find apps -name cn.ts` | 0 结果 |
| shared 测试通过 | `pnpm --filter @soymutdb/shared test` | all pass |
| motion 测试通过 | `pnpm --filter @soymutdb/motion test` | all pass |

#### Phase 4 — 部署后验证

| 检查项 | 命令 | 期望结果 |
|--------|------|----------|
| HSTS 头 | `curl -sI https://soymutdb.org | grep Strict` | `max-age=31536000` |
| Docker context 缩小 | `docker build --no-cache` 日志 | context < 50MB |
| no-console 警告 | `pnpm lint` | 0 error, 可能有 warn |
| Knip 无遗漏 | `pnpm exec knip` | 0 unused exports |

### 回滚矩阵

| Phase | 回滚方法 | 数据影响 | 停机时间 |
|-------|---------|---------|---------|
| 1.1 | `git revert` vite.config.ts | 无 | 0（重新 build） |
| 1.2 | 移除 cache step | 无 | 0 |
| 2.1 | 恢复 web/api.ts，Admin 回 http | 无 | 0 |
| 2.2 | withRetry 回退为仅超时 | 无 | 0 |
| 2.3 | 恢复两个独立 antd-theme.ts | 无 | 0 |
| 3.1-3.4 | `git revert` + `pnpm install` | 无 | 0 |
| 4.1-4.5 | `git revert` 各文件 | 无 | 0 |

> **关键**：所有变更均为代码和配置层面，不涉及数据库迁移或基础设施变更，可随时安全回滚。

### CI/CD 流水线影响

```
当前 CI 流程：
  checkout → pnpm install → pnpm build → test → lint → typecheck → docker build

Phase 1 后：
  checkout → pnpm install → [Turbo cache restore] → pnpm build ⚡ → test → lint → typecheck → docker build

Phase 3 后：
  新增 shared/i18n/motion 测试 job（可与现有 frontend job 并行）
```

### 预期收益

| 指标 | 当前 | 优化后 | 改善 |
|------|------|--------|------|
| CI 构建时间 | ~15-20 min | ~8-12 min | -40% |
| Admin 生产白屏风险 | 存在 | 消除 | 100% |
| 重复代码文件 | ~6 个 | 0 | 100% |
| 测试覆盖（shared/motion） | 0% | >80% | — |
| Docker build context | ~200MB+ | <50MB | -75% |
| 依赖版本不一致 | 3 处 | 0 | 100% |
