# SoyMutDB 全面优化实施计划

> **面向执行者：** 本计划按任务逐条执行，每个任务含 Files / Steps / Verify / Accept 四段。
> 执行前必须先读 `AGENTS.md` 与 `docs/dev/database-core-contract.md`（数据契约不可破坏）。
> **不要**在任务外做无关重构；**不要**提交、暂存或回滚他人已有改动。
>
> **依据：** 2026-09-14 全量审查（Skills: `systematic-debugging` / `ui-ux-pro-max-zh-1.0.0` /
> `design-master-2.1.2` / `web-perf` / `receiving-code-review`）。
> 所有问题均已按 `systematic-debugging` 四阶段验证到根因，并已用 `receiving-code-review`
> 剔除工具误报（详见 §1.5）。
>
> **本版修订（v2，审核后重写）：** 修正了 v1 中会阻断执行的设计缺陷 ——
> 产物生命周期与验证顺序（§2.3）、CSP 注入时序与单一来源（T5）、CSP 契约自相矛盾（§4.0）、
> 门禁先于修复的倒置顺序（§2.2）、systemd 变量语法（T4）、Service Worker 隔离不完整（T12）、
> 安全审查规则被削弱（T28）、对比度修复方向错误（T15）、bundle 门禁 glob 与实际产物不符（T24）、
> 字体策略方向错误（T26）、验证矩阵命令错误（§5）。
>
> **v3（执行中自纠）：** 执行 T14 时实测推翻了 v2 自己的一个结论 —— D-5 被写成
> 「`precompress.sh` 中断 web 镜像构建」（高），但脚本用的是 `find … -exec … \;`，
> 而 POSIX 下只有 `-exec … +` 才传播命令失败（实测 `\;` → rc=0，`+` → rc=1）。
> 真实缺陷是**陈旧 `.gz` 未被刷新**（中），不是构建中断。D-5 已改写、严重度已降级，
> 代码注释与测试文档字符串同步纠正。**凡结论均以实测为准，不以推理为准。**
>
> **v3 执行中又发现并修正的验证命令错误（均已实测）：**
>
> | 命令 | 问题 | 实测结果 |
> |---|---|---|
> | `STATIC_DIR=… bash scripts/smoke.sh --profile static` | `smoke.sh:51` 把 `STATIC_DIR` 重置为空，环境变量**被忽略** | 用 `STATIC_DIR=/nonexistent` 仍然 `static smoke passed for apps/web/dist` → **假通过**。必须用 `--static-dir <dir>` |
> | `pnpm --filter @soymutdb/web build:sites` | 需要部署 origin，否则 vite 配置直接报 `API origin is required` | 已补上三个变量（§2.3 约束 3） |
> | `pnpm --filter @soymutdb/admin build:web` | admin 无此脚本名（`build:web` 只是 `build` 的别名，但 T11 的验证写的是 `build`） | 统一用 `build` |
> | T13 的 `jsdomWindow.localStorage` 修法 | vitest 把 `window` 别名到 `globalThis`，读回仍是 `undefined`；写入会把 getter 换成 `undefined` 数据属性，**比不改更糟** | 改为动态 `import("jsdom")` 新建 window 取真实 `Storage` |
> | T2 的 `CSP_CONTENT` 使用方式 | 最终化器不能从 `_headers` 的**静态默认值**推导（那会丢掉 API/JBrowse origin） | 已实测发现并修正：必须从 `CSP_CONTENT` 推导 |
> | V5 要求 `dist/{external,internal}` 同时存在 | 与 V12 的 `pnpm build` 冲突（实测 `vite build` 会删掉整个 `dist/`，包括两个变体目录） | `check_artifact_headers.py` 默认**与顺序无关**；双变体存在性用 `--require-dual`（仅在双构建之后调用） |
> | V9 严格扫描 demo 构建 | 实测严格模式在当前 demo 产物上 **exit 1**（`samples/SMDB-*.html` 含演示标记） | demo 必须用 `--allow-demo` |
>
> **基线（本计划开始前实测，Node 24.19.0）：**
> - `bash scripts/verify-frontend-artifacts.sh` → **EXIT=0**
> - `bash scripts/smoke.sh --profile contracts` → **216 passed**（另有 10 项 environment-bound contract）
> - `bash scripts/smoke.sh --profile static` → **PASS**
> - `pnpm --filter @soymutdb/web build:sites` → **EXIT=0**（external + internal 双产物；
>   需 `VITE_DEPLOYMENT_MODE=demo` + `VITE_API_BASE_URL` + `VITE_JBROWSE_BASE_URL`，见 §2.3）
> - Web 单测 36 files / 180 tests 全通过；API 非数据库单测 39 passed
> - 24 项 API 测试与 worker 集成测试需 Docker/PostgreSQL（本机 Docker daemon 不可用）
> - **Node 必须使用 `.nvmrc` 的 24.19.0**；系统 Node 26 会导致 1 项测试假失败（见 T13）

---

## 0. 目标与非目标

### 目标

1. **安全边界收口**：修复 nginx 安全头静默丢失、门户托管层安全头缺失、CSP 内联脚本弱化、代理信任边界。
2. **部署加固**：日志轮转、容器加固、资源限制、CORS 收敛，使生产拓扑具备可长期运行的运维属性。
3. **缺陷修复**：Admin 字体 404、JBrowse `_headers` 占位符、Service Worker 缓存命名、Node 版本韧性、
   `precompress.sh` 不刷新陈旧 `.gz`（并修正了 v2 对此项严重度的误判）。
4. **UI/UX 优化**：WCAG AA 对比度达标、图表可访问、触摸目标、焦点/键盘、空错加载态一致性、动效规范。
5. **性能优化**：静态资源长缓存、Bundle 预算扩展（含实际 chunk 命名）、Service Worker 预缓存瘦身、
   双产物资源时序基线、字体负载治理。
6. **门禁固化**：所有新规则落入共享脚本（`scripts/ci-job-steps.sh` / `scripts/verify-frontend-artifacts.sh` /
   `scripts/smoke.sh`），**禁止**写入 `.cnb.yml` 或 `.github/workflows/*`
   （`scripts/test_ci_job_contracts.py` 会判失败）。

### 非目标

- 不重构数据库模型、不改变 `public_id` / `internal_id` 契约、不引入新的权威存储。
- 不替换 Ant Design / Tailwind / ECharts 技术栈。
- 不做业务功能新增（本次只做质量与体验优化）。
- 不修改发布流水线的分层结构（verifier 无 registry 凭据、publisher 不重建）。
- **不削弱安全扫描换取 CI 绿灯**（T28 明确禁止）。

---

## 1. 问题证据索引

### 1.1 安全（Security）

| ID | 严重度 | 位置 | 现象（已验证） |
|---|---|---|---|
| S-1 | **高** | `infra/nginx/conf.d/default.conf` L53/124/156/233/275/288 | `add_header` 在 location 层**覆盖**服务级安全头 → CSP/HSTS/XFO/nosniff/Referrer-Policy 在 `/api/`、`/data/`、`/samples/`、`/track.gif`、静态资源全部丢失 |
| S-2 | **高** | `infra/docker/web-nginx.conf` L32/45/55/65、`infra/docker/admin-nginx.conf` L32/43/53、`apps/jbrowse/nginx.conf` L24/33 | 同上。三者的 `location /`（SPA HTML）与资产 location 均只剩 `Cache-Control`，**X-Frame-Options / CSP 完全缺失**；而 meta CSP 的 `frame-ancestors` 按规范被浏览器忽略 → 无防点击劫持（admin 尤其严重） |
| S-3 | **高** | `apps/web/public/_headers` **不存在** | `vite.config.ts:29,47`、`base-template.ts:263`、`deploy/cloudflare.md:73,239,344`、`docs/design/deployment-architecture.md:276` 均引用该文件；实测 `apps/web/dist/external/` 只有 `_redirects`。门户无 HSTS/nosniff/Referrer-Policy/防 framing，`/assets/*` 无长缓存 |
| S-4 | **高** | `deploy/scripts/conda-services.sh:66`、`conda-deploy.sh:182`、`deploy/conda/README.md:79,99,140` | `--forwarded-allow-ips=*` + uvicorn `_TrustedHosts.get_trusted_client_host` 对 `always_trust` 返回 `x_forwarded_for_hosts[0]`（最左=客户端可控），nginx 用 `$proxy_add_x_forwarded_for` 追加 → IP 伪造，影响限流、审计、分析去重 |
| S-5 | 中 | 反射点实测 4 处：`infra/nginx/conf.d/default.conf:65`（`/track.gif`）、`:246`（`/data/`）、`infra/nginx/cloudflare-tunnel.conf:96`（`/jbrowse-data/`）、`:111`（`/data/`） | 反射 `$http_origin` + `Cache-Control: public, max-age=86400, immutable`，全仓无 `Vary: Origin`（共享缓存可把 A 站响应交给 B 站）。注意 `/jbrowse-data/` **只存在于 `cloudflare-tunnel.conf`**，`default.conf` 中无该 location |
| S-6 | 中 | `apps/jbrowse/dist/_headers`（构建产物实测） | CSP 仍是 `https://api.example.com` / `https://portal.example.com` / `https://admin.example.com` 占位符，**无构建期注入**（admin 有 Vite 插件注入并在缺失时抛错，jbrowse 没有）→ Cloudflare Pages 上 JBrowse 的 API 与 embed 全被 CSP 拦截 |
| S-7 | 中 | `infra/nginx/conf.d/default.conf:34`、`apps/web/index.html:21`、`base-template.ts`、`vite.config.ts:66` | `script-src 'self' 'unsafe-inline'`（G-1 已登记，未整改）。SSG 产物实际含 4 类内联脚本：theme-init / widget-loader / redirect / i18n-ready |
| S-8 | 低 | `infra/nginx/nginx.conf:99` | `map $http_x_request_id $request_id_to_forward { default $http_x_request_id; }` 未校验格式 → 日志注入面 |
| S-9 | 低 | `infra/nginx/conf.d/default.conf:44`、`web-nginx.conf:16`、`admin-nginx.conf:16` | `X-XSS-Protection: 1; mode=block` 已废弃（G-7 已登记） |
| S-10 | 低 | `infra/nginx/conf.d/security-headers.conf`（v1 计划命名） | `conf.d/*.conf` 被 `nginx.conf` 的 `include /etc/nginx/conf.d/*.conf;` 自动加载 → 片段会被当成 server 块解析而启动失败；且 v1 的备用 `nginx -t` 命令用 `-v infra/nginx:/etc/nginx` 遮蔽镜像自带 `mime.types`，校验结果不可信 |

### 1.2 部署（Deployment）

| ID | 严重度 | 位置 | 现象 |
|---|---|---|---|
| D-1 | 中 | `docker-compose.yml` 全文 | **零 `logging:` 配置**，无 `daemon.json` → Docker 默认 `json-file` 无上限，nginx/API/worker 高频 stdout 会撑满生产磁盘 |
| D-2 | 中 | `docker-compose.yml:585`（nginx 服务） | 无 `read_only` / `cap_drop` / `no-new-privileges` / `user`，而同文件的 `tunnel-origin`（L620+）三项全有 → 加固标准不一致。加固前必须先解决**只读根文件系统下的可写路径**：`infra/nginx/nginx.conf` 写 `/var/log/nginx/*.log`（无 `/var/log` 挂载 → 只读即启动失败）、默认 `pid /var/run/nginx.pid`、`client_body_temp_path /var/cache/nginx/client_temp`；且 `listen 80` 在 `cap_drop: ALL` + uid 101 下无法绑定（<1024 需 `CAP_NET_BIND_SERVICE`） |
| D-3 | 低 | `docker-compose.yml:106,132,162,181,198` | 数据服务（postgres/clickhouse/redis/minio）无 `mem_limit`，应用服务有 |
| D-4 | 低 | `apps/web/dist/**/*.gz` | `.gz` 预压缩文件仅容器 nginx 的 `gzip_static` 使用；Cloudflare Pages / GitHub Pages 路径下不生效，产物体积近乎翻倍 |
| D-5 | 中 | `infra/docker/precompress.sh` | `gzip -k` **拒绝覆盖**已存在的 `.gz`（`gzip: a.js.gz already exists; not overwritten`）并保留**旧压缩体** → 源文件变更后 nginx `gzip_static` 仍会送出陈旧的 `.gz`。字体最严重：`.woff`/`.woff2`/`.ttf` **只由本脚本压缩**，构建链不覆盖。

**⚠️ v2 曾把此项误判为「中断镜像构建」（严重度「高」）—— 已实测推翻：** 脚本用的是 `find … -exec … \;`，而 **只有 `-exec … +` 才传播命令失败**（实测：`-exec false \;` → rc=0；`-exec false +` → rc=1）。v2 的探针误用了 `+`，因而把「警告」误读成「构建中断」。真实缺陷是**陈旧产物**，不是构建失败 |

### 1.3 缺陷（Bugs）

| ID | 严重度 | 位置 | 现象（已验证） |
|---|---|---|---|
| B-1 | **高** | `apps/admin/src/index.css:2-3` | CSS `@import "@fontsource/jetbrains-mono/latin-400.css"` 的 `url(./files/...)` 未被 Vite 解析：`apps/admin/dist/assets/index-*.css` 引用 `./files/jetbrains-mono-latin-400-normal.woff2`，而 `apps/admin/dist/assets/files/` **不存在** → 管理端等宽字体 404。web 端已修同类问题（`apps/web/src/index.css:99` 注释说明需改 JS import） |
| B-2 | 中 | `apps/web/public/sw.js:26,28,87,106,118` | `PRECACHE_CACHE`/`RUNTIME_CACHE` 未按站点变体命名（违反 AGENTS.md「service-worker namespaces 必须分离」）；`soymutdb-runtime` 无版本轮换、activate 只清理 `soymutdb-static-v*` → 运行时缓存永不回收；且 `caches.match(request)` **不带 cacheName**，会跨所有 cache（含另一站点变体的缓存）匹配 |
| B-3 | 低 | `apps/web/src/lib/__tests__/view-transitions.test.ts` | Node 25+ 内置实验性 `localStorage` 全局遮蔽 jsdom → `localStorage` 为 `undefined`，`afterEach(() => localStorage.clear())` 抛 `TypeError`；Node 24.19.0 下通过。**实测（Node 26.8.1）**：`globalThis` **自有属性** `localStorage` 是 `configurable: true` 的 getter，未提供 `--localstorage-file` 时返回 `undefined` 并告警 → vitest 的 jsdom 全局安装会跳过已存在的键。`apps/web/vitest.config.ts` 当前**没有** `setupFiles` |
| B-4 | 低 | `apps/api/app/services/module_import_service.py:34` | 查出某 release 全部 `module_tsv` DataSet 后在 Python 侧过滤 `validation_evidence["module_key"]`，未在 SQL 过滤；且「首个匹配」无 `ORDER BY` → 语义不确定 |
| B-5 | 中 | `apps/web/scripts/gen-sw.js:70-75` | 无条件生成 `sw.js.gz`，不受 `.gz` 策略开关控制；`apps/web/scripts/gzip-compress.ts` 同样无条件执行（T14 需一并处理，否则 D-4 的开关形同虚设） |

### 1.4 性能与工程卫生

| ID | 严重度 | 位置 | 现象 |
|---|---|---|---|
| P-1 | 中 | 托管层 | `/assets/*` 无 `immutable`（依赖 S-3 修复）；gh-pages 默认 `max-age=600` |
| P-2 | 中 | `apps/web/public/sw.js:28`、`gen-sw.js:48` | SW 预缓存 `dist/assets` **全部**产物（实测 external 变体 28 个文件 / 约 **6.0 MB 原始 JS**），包含 `echarts-*.js`(1.04 MB)、`antd-*.js`(0.95 MB)、`mammoth.browser-*.js`(0.50 MB)、`cytoscape.esm-*.js`(0.44 MB)、`pdf-*.js`(0.33 MB) → 首访即下载全部懒加载大包，抵消代码分割收益 |
| P-3 | 中 | `scripts/check-bundle-size.sh` | 仅覆盖 `antd` / `index` / `pro`。且 glob 与实际产物不符：实际为 `cytoscape.esm-*.js`、`mammoth.browser-*.js`、PDF worker 为 `*.mjs`、highlight.js 被打进 `common-*.js` → 任何新增 glob 都会静默走 `SKIP`（假通过） |
| P-4 | 低 | `e2e/tests/web-artifact-performance.spec.ts`、`playwright-web-performance.config.ts` | 只测单一产物（`apps/web/dist`，且硬编码 `artifactRoot`），未覆盖 external/internal 双产物；配置文件本身也未参数化 |
| P-5 | 低 | `pnpm lint`（workspace） | **实测 0 errors / 90 warnings**：`@soymutdb/web` 37、`@soymutdb/admin` 53、`@soymutdb/jbrowse` 0。v1/v2 只算了 web 的 37，把 admin 的 53 条漏在门禁之外 —— 而 V2 要求的是 **workspace** 清零。web 的 37 条分布在约 20 个文件（非 v1 所列 2 个）：`components/file-viewer/*`、`genome-browser-widget.tsx`、`site-header.tsx`、`soymutdb-widget.ts`、`track-viewer.tsx`、`routes/{blast,browser,genes,mutants,search,search/*,tools/*}`。其中 `browser.tsx:152`「Cannot access refs during render」与 `soymutdb-widget.ts:420` `no-console` 属真实缺陷类 |
| P-6 | 中 | `apps/web/public/fonts/harmonyos/`、`apps/admin/public/fonts/harmonyos/`、`apps/jbrowse/public/fonts/harmonyos/` | 每份 3 个 CJK woff2 共 **12.8 MB**。`apps/web` 的 CSS **已不再引用**该字体（`index.css:861-863` 注释：系统 CJK 栈，避免首屏多兆字节下载），但 `public/` 文件仍被复制进两个产物 → 每个 web 产物白带 12.8 MB 死负载（实测 `dist/external/fonts/harmonyos/*`）。admin/jbrowse 仍引用，其字体在每个页面都是关键链末端 |
| P-7 | 低 | 文档 | `deploy/cloudflare.md:73,239,344`、`docs/design/deployment-architecture.md:276`、`apps/web/vite.config.ts:29,47`、`base-template.ts:263` 与仓库实际状态漂移 |

### 1.5 已被 `receiving-code-review` 剔除的误报（**不要**修业务代码）

| 工具报告 | 数量 | 核验结论 |
|---|---|---|
| `SEC-SECRET` critical | 2 | 测试夹具口令（`login.test.tsx:72,101`），非真实凭据 |
| `SEC-XSS` high | 3 | `code-viewer` 用 hljs（输出已转义）；`markdown-viewer`/`markdown-mode` 已 DOMPurify |
| `PERF-N1` high | 11 | 全部为「遍历查询结果」被正则误判（如 `search/cache.py:31` 是哈希循环、`features.py:131` 是 dict 推导） |

> 误报处理见 T28（**只改进规则精度，不放宽判定**），不修改业务代码。

### 1.6 UI/UX（Accessibility / Design）

| ID | 严重度 | 位置 | 实测对比度（OKLCH→sRGB→WCAG 公式计算） |
|---|---|---|---|
| U-1 | 中 | `apps/web/src/index.css:80-81` | **暗色** `destructive-foreground` on `destructive` = **3.57:1** ❌（AA 需 4.5:1） |
| U-2 | 中 | `index.css:39` + `renderer.tsx:522`、`relationship-graph.tsx:219` | **亮色** `text-destructive` on `destructive/10` 叠加底 = **3.99:1** ❌。实测修正：`/15` = 3.69（**更差**），`/6` = 4.25（仍不达标），只有 `/2` = 4.53 才达标（但色块不可见）→ **唯一可行解是拆 token**（见 T15） |
| U-3 | 中 | `index.css:39` | 亮色 `text-destructive` on `muted` = 4.38:1 ❌ / 暗色 on `card` = 4.49:1 ⚠️（临界）。**暗色矛盾已数值证明**：填充面需 L ≤ 0.56（0.56→4.58）而文本需 L ≥ 0.66（0.66→card 5.28），无法用单一 token 同时满足 |
| U-4 | 中 | `index.css:44-50` | **亮色图表/图形色**（WCAG 1.4.11 非文本图形需 ≥3:1）实测：`chart-2` 2.88、`chart-3` **2.02**、`chart-4` **1.51**、`impact-moderate` **2.51** ❌；**已达标不需改**：`chart-1` 4.44、`chart-5` 6.58、`impact-high` 4.67、`impact-low` 3.79、`impact-modifier` 3.51。暗色全部达标（5.4–12.6:1） |
| U-5 | 低 | `site-header.tsx` 移动抽屉 / AntD 默认按钮 | 触摸目标按 `ui-ux-pro-max` 应为 44×44，AntD middle 默认 32px |
| U-6 | 低 | 全站 | 空态/错误态/加载态缺少统一组件契约；`aria-live` 仅 11 处 |
| U-7 | 低 | `index.css:849-859`（`prefers-reduced-data`） | 只覆盖 `.shimmer`/`.dna-bg`/`.card-lift`/`.text-gradient-animated`，未覆盖 `transition-[width]` 进度条与 view-transition 动效（与 T21 相关） |

> 达标项（**保持**）：焦点环 `:focus-visible`、skip-link、`prefers-reduced-motion`、
> z-index 尺度（10/20/40/50）、无 emoji 图标、表格 `aria-sort`/`scope`、
> `documentElement.lang` 随 i18n 更新、`useECharts` 已按 theme 失效重建。

### 1.7 与既有登记项的关系

`docs/ops/production-security-checklist.md` 已登记 G-1（CSP unsafe-inline）、G-4（静态边界归属）、
G-7（安全头冗余）。本计划 **T5 收口 G-1**、**T2/T3 收口 G-4 的静态边界部分**、**T9 收口 G-7**。
执行后需在该清单 §4 标注完成状态与证据链接。

---

## 2. 执行总览

### 2.1 任务图

```
P0 安全边界 ─┬─ T1 nginx 安全头继承（4 个 conf + .inc 片段）
             ├─ T2 门户 _headers + 构建期 CSP 单一来源 ──┬── T23 缓存策略
             ├─ T3 JBrowse _headers 注入               │
             ├─ T4 代理信任边界                        │
             └─ T5 CSP 内联脚本收口（依赖 T2 的最终化器）
P1 部署加固 ─┬─ T6 日志轮转  T7 nginx 容器加固  T8 CORS 收敛  T9 头收敛  T10 资源限制
P2 缺陷修复 ─┬─ T11 Admin 字体  T12 SW 隔离  T13 Node 韧性  T14 .gz 策略 + precompress 刷新陈旧件
P3 UI/UX ────┬─ T15 对比度  T16 图表色板  T17 对比度门禁  T18 触摸目标
             ├─ T19 焦点/键盘  T20 状态一致性  T21 动效  T22 微文案（前端映射）
P4 性能 ─────┬─ T23 缓存（依赖 T2）  T24 预算扩展（含真实 glob）  T25 双产物基线
             └─ T26 字体负载（删除死负载 + admin/jbrowse 治理）
P5 卫生 ─────┬─ T27 lint  T28 审查降噪（不放宽）  T29 文档同步  T30 SQL 过滤
P6 门禁 ─────┴─ T31 门禁脚本接入共享脚本  T32 回归断言归属核验  T33 全量验证与证据
```

### 2.2 执行顺序（**测试先行**）

**核心规则：每个修复任务的回归断言与修复在同一个任务内提交。** T31/T32 只做「汇总核验」，
不承担「首次创建断言」的职责 —— 否则修复任务无法自证，且门禁会在旧代码上先红。

```
阶段 A（无依赖，可并行）
  T4 代理信任边界（含功能性负向测试）
  T6 日志轮转 / T10 资源限制（Compose 加固，含契约测试）
  T11 Admin 字体 / T13 Node 韧性
  T14 .gz 策略 + precompress 刷新陈旧件（含回归测试）
  T27 lint 清零（分批，每批附行为回归）
  T28 审查规则降噪（先跑基线，再改规则）
  T29 文档同步（其余任务落地后复跑）

阶段 B（安全头/CSP 链，必须按序）
  T1（4 个 nginx conf + .inc + 静态门禁）
    → T2（门户 _headers + 最终化器 + CSP 单一来源）
      → T3（JBrowse 注入，复用同一共享模块）
        → T5（内联脚本收口：先外置/删除，再 hash）
          → T23（缓存策略依赖 T2 的 _headers）

阶段 C（UI/UX）
  T17（门禁先写，允许先红）→ T15（按门禁修）
    → T16（图表色板 + 冗余编码）→ T17 复跑转绿
  T18 → T19 → T20 → T21 → T22

阶段 D（性能）
  T24（预算扩展，依赖真实 chunk 名）→ T25（双产物基线，依赖 T24 的产物布局）
  T26（字体负载；删除死负载可独立先行）

阶段 E（收口）
  T30（SQL 过滤，需 PostgreSQL）
  T31（把阶段 A–D 已写好的断言/脚本接入共享脚本）
  T32（逐条核验断言归属与回滚变红）
  T33（全量验证矩阵）
```

### 2.3 产物生命周期（**v1 的验证顺序缺陷已修正**）

`apps/web` 的构建链是 `vite build → ssg-* → embed-page-definitions → gzip → gen-sw → release-manifest`，
`build:sites` 只是把同一链在 `dist/external|internal` 下跑两遍。由此产生三条硬约束：

1. **`vite build`（根 `outDir`）会清空整个 `apps/web/dist/`，包括 `dist/external|internal`。**
   实测：先跑 `build:sites` 得到双产物，再跑一次 `pnpm --filter @soymutdb/web build`，
   `dist/external` 与 `dist/internal` **直接消失**。因此双产物检查必须排在所有全应用构建**之后**，
   否则读到的是不存在或上一次的树。
2. **`build:sites` 不构建 JBrowse**（只有 `build-pages-artifact.sh` 会）。T3 的验证必须显式构建
   `@soymutdb/jbrowse`，或直接跑 `scripts/build-pages-artifact.sh`。
3. **`build:sites` 需要部署 origin 环境变量**（否则 vite 配置直接报
   `API origin is required for production deployment` 并 exit 1）。实测最小可用调用：
   ```bash
   VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
   VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test \
     pnpm --filter @soymutdb/web build:sites
   ```
   与 `scripts/verify-frontend-artifacts.sh` 的 `SOYMUTDB_CI_DEMO_*` 默认值一致。
   （v2 的 V5 与各任务 Verify 漏了这三个变量，直接跑会失败 —— 已修正。）

**标准验证顺序（§5 采用）：**

```
1  pnpm install --frozen-lockfile
2  pnpm lint / pnpm typecheck / pnpm test           # workspace 全量
3  bash scripts/verify-frontend-artifacts.sh        # 内部会重建根 dist 并跑 bundle/artifact 门禁
4  VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
     VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test \
     pnpm --filter @soymutdb/web build:sites          # 干净双产物（需上述三个变量）
5  bash scripts/smoke.sh --profile static --static-dir apps/web/dist/external
   bash scripts/smoke.sh --profile static --static-dir apps/web/dist/internal
6  bash scripts/check-production-artifact.sh apps/web/dist/external --allow-demo   # demo 构建
   （严格模式仅对真实 release API 构建执行，见 T29）
7  e2e：public / performance（双变体）/ production（需真实部署）
8  bash scripts/smoke.sh --profile contracts
9  bash scripts/verify-backend-tests.sh             # 需 PostgreSQL
```

### 2.4 依赖约束

- T5 必须在 T2 的**构建期最终化器**之后（hash 必须基于最终 HTML，见 T5）。
- T23 必须在 T2 之后（`_headers` 载体存在）。
- T15 依赖 T17 的门禁先写好（允许先红）；T17 转绿依赖 T15/T16。
- T25 依赖 T24（预算与产物布局稳定）。
- T31 必须在所有修复任务之后；T32 逐条核验。
- T1/T2 改动 `infra/nginx` 与 `apps/web/public` → 契约测试在**同一任务**内更新（T1/T2 自带断言），
  T32 只做汇总核验。
- **禁止**新增第 4 个独立检查脚本去替代已有共享脚本职责；T31 只做接线。

---

## 3. 文件所有权映射

### 新建

| 文件 | 用途 |
|---|---|
| `infra/nginx/conf.d/security-headers.inc` | 可 `include` 的安全头片段（server 级 + location 级复用），T1 的唯一来源。**必须用 `.inc`**：`nginx.conf` 的 `include /etc/nginx/conf.d/*.conf;` 会自动加载 `.conf`，片段会被当成 server 块解析并导致启动失败（S-10） |
| `infra/nginx/conf.d/security-headers-admin.inc` | admin 专用片段（`DENY`/`no-referrer`/`script-src 'self'`）。必须是独立文件：nginx 会发出同一层级的**每一个**同名 `add_header`，「include 后覆盖」会送出重复的 XFO/CSP |
| `packages/shared/src/build/csp.ts` | CSP 组合/解析/比较的共享实现（`composeCsp` / `parseCsp` / `directivesEqual`），供 web 与 jbrowse 的构建期脚本使用，T2/T3/T31 |
| `apps/web/public/_headers` | 门户 Cloudflare Pages 响应头（安全头 + 缓存 + **保守默认 CSP**，由最终化器替换为精确策略），T2 |
| `apps/web/scripts/finalize-csp.ts` | **构建链最终化器**：扫描最终 HTML 的内联脚本 → 计算 hash → 重写每页 meta CSP → 重写 `dist/_headers` 的 CSP 行；fail-closed，T2/T5 |
| `apps/jbrowse/scripts/inject-headers-origins.ts` | 构建期把 API/数据/门户/管理端 origin 注入 `dist/_headers`（复用 `packages/shared/src/build/csp.ts`），T3 |
| `apps/web/src/components/empty-state.tsx` | 统一空/错/加载态（T20） |
| `scripts/check_nginx_security_headers.py` | 静态断言 4 个 nginx conf 中每个含 `add_header` 的 location 都 include 片段或内联全部安全头；反射 Origin 必须伴随 `Vary`；全仓无 `X-XSS-Protection`，T1/T8/T9（**下划线命名，全仓统一**） |
| `scripts/check_contrast_tokens.py` | 解析 `index.css` token → 计算 WCAG 对比度 → 断言阈值（含 alpha 合成），T17/T31 |
| `scripts/check_artifact_headers.py` | 断言 `dist/{external,internal}`、`apps/{admin,jbrowse}/dist` 的 `_headers` 存在、无占位符、CSP 与最终 meta 同源且无 `__` 残留，T2/T3/T31 |
| `docs/ops/static-hosting-security.md` | gh-pages（无 `_headers`）与 Cloudflare Pages 的安全边界差异与生产切换门禁，T29 |

### 修改（关键）

| 文件 | 任务 |
|---|---|
| `infra/nginx/conf.d/default.conf`、`infra/nginx/nginx.conf` | T1, T7, T8, T9 |
| `infra/docker/web-nginx.conf`、`infra/docker/admin-nginx.conf`、`apps/jbrowse/nginx.conf` | T1, T9 |
| `infra/docker/Dockerfile.web`、`infra/docker/Dockerfile.admin`、`apps/jbrowse/Dockerfile` | T1（COPY `.inc`）, T14 |
| `infra/docker/precompress.sh` | T14（刷新陈旧 `.gz`，D-5） |
| `apps/web/scripts/base-template.ts`、`apps/web/src/lib/deployment.ts`、`apps/web/vite.config.ts`、`apps/web/index.html` | T2, T5, T29 |
| `apps/web/package.json`、`apps/web/scripts/build-sites.ts` | T2, T5, T14（构建链顺序） |
| `apps/jbrowse/vite.config.ts`、`apps/jbrowse/public/_headers`、`scripts/build-pages-artifact.sh` | T3 |
| `deploy/scripts/conda-services.sh`、`deploy/scripts/conda-deploy.sh`、`deploy/conda/README.md` | T4 |
| `docker-compose.yml`、`deploy/.env.example`、`docs/ops/production-build.md` | T6, T7, T10 |
| `apps/admin/src/index.css`、`apps/admin/src/main.tsx` | T11 |
| `apps/web/public/sw.js`、`apps/web/scripts/gen-sw.js` | T12, T14 |
| `apps/web/vitest.config.ts`、`apps/web/src/test/setup.ts` | T13 |
| `apps/web/src/index.css`、`apps/web/src/lib/use-echarts.ts` | T15, T16 |
| `apps/web/src/components/site-header.tsx`、`data-table.tsx`、`routes/**` | T18–T22 |
| `scripts/check-bundle-size.sh` | T24 |
| `e2e/playwright-web-performance.config.ts`、`e2e/tests/web-artifact-performance.spec.ts`、`e2e/static-server.mjs`、`e2e/package.json` | T25 |
| `apps/web/public/fonts/harmonyos/**`（删除）、`apps/admin/src/index.css`、`apps/jbrowse/src/index.css` | T26 |
| `tools/code-review/review.py` | T28 |
| `apps/api/app/services/module_import_service.py` | T30 |
| `scripts/verify-frontend-artifacts.sh`、`scripts/smoke.sh`、`scripts/ci-job-steps.sh` | T31 |
| `scripts/test_production_compose_contract.py`、`test_development_compose_contract.py`、`test_platform_delivery_contracts.py`、`test_site_artifact_isolation.py`、`test_dockerfile_contracts.py` | T1/T2/T3/T4/T6/T7/T12/T14/T26（断言）+ T32（汇总核验） |
| `docs/ops/production-security-checklist.md`、`deploy/cloudflare.md`、`docs/design/deployment-architecture.md` | T29 |

> **工作区安全边界：** `docker-compose.yml`、`deploy/.env.example`、`scripts/compose-local.sh`、
> `scripts/start-cloud-dev.sh`、`docs/adr/0001-*.md`、`docs/ops/*.md`、`scripts/compose_loader.py`、
> `scripts/dependency_governance.py`、`scripts/setup-workspace.sh` 等文件当前**已有未提交改动**。
> 执行者必须**先读当前内容，以最小补丁逐段合并**，禁止整文件替换、禁止 `git checkout`/`git restore`。
> 不执行任何 git 写操作（无 commit / 无 stash / 无 add）。

---

## 4. 任务清单

### 4.0 规范基线：CSP 的单一来源与按表面区分（**执行前必读**）

v1 计划自相矛盾（T1 的 nginx 字面量缺 `object-src`/`worker-src`，T2/T5/T31 却要求逐字一致）。
本版确立以下规范，后续所有任务以此为准：

**单一来源（TS 侧）：** `apps/web/src/lib/deployment.ts` 的 `buildCsp()` 已是门户 meta CSP 的生成器，
顺序为 `default-src, script-src, style-src, img-src, font-src, connect-src, frame-src, base-uri,
form-action, frame-ancestors, object-src, worker-src`。本计划：
1. 把组合/解析/比较逻辑抽到 `packages/shared/src/build/csp.ts`（`composeCsp`、`parseCsp`、
   `directivesEqual`），`buildCsp()` 改为基于 `composeCsp` 实现（**行为不变**，既有测试必须继续通过）。
2. `apps/web/scripts/finalize-csp.ts` 与 `apps/jbrowse/scripts/inject-headers-origins.ts` 用同一模块
   生成各自的最终策略文本。
3. **nginx 的 CSP 是字面量**（nginx 无法读 TS），因此 T31 的门禁按**指令类别**比较，而不是「全文逐字」：

| 指令 | nginx（dev/自管） | 门户 `_headers` / meta（Pages） | 比较规则 |
|---|---|---|---|
| `default-src`、`style-src`、`img-src`、`font-src`、`base-uri`、`form-action`、`frame-ancestors`、`object-src`、`worker-src` | 字面量 | 生成 | **必须逐字一致** |
| `script-src` | `'self' 'unsafe-inline'`（dev 保留，见 T5 第 5 步） | `'self'` + 逐页 hash（+ beacon origin） | **明确允许不同**，差异必须与本文档一致 |
| `connect-src` | `'self' https:`（dev 需代理任意 staging origin） | `'self'` + 精确 API origin（+ beacon） | **明确允许不同** |
| `frame-src` | `'self'` | `'self'` + 精确 JBrowse origin | **明确允许不同** |

4. **按表面区分**：门户 HTML、JBrowse HTML、admin HTML、API/数据响应**不共用一份策略**。
   `/api/`、`/data/`、`/track.gif` 等非 HTML 响应**不需要 CSP**，只需 `nosniff` + 缓存 + CORS 规则；
   T1 的片段会被这些 location include，因此片段内的 CSP 必须是「对非 HTML 无副作用」的宽松策略
   （即 dev 字面量），并在片段头部注释说明「生产 HTML 不由此路径提供」。
5. `media-src` 不进入规范策略：门户无 `<video>`/`<audio>`，`buildCsp()` 亦无该指令
   → **从 nginx 字面量中删除 `media-src`**，使指令集与生成侧一致。

---

### P0 — 安全边界（上线阻断）

---

#### T1 · 修复 nginx `add_header` 继承导致的安全头丢失  ✅ **已执行**

**根因（systematic-debugging Phase 1–2）：** nginx 规定 `add_header` 仅在当前层级**没有**任何
`add_header` 时才继承上层；`conf.d/default.conf` 的 6 个 location、`web-nginx.conf` 的 4 个、
`admin-nginx.conf` 的 3 个、`apps/jbrowse/nginx.conf` 的 2 个各自声明了 `add_header`，
因此服务级安全头被整体丢弃。`/pages/` 的注释已证明团队知晓该规则，只是未推广到其余 location。

**Files:**
- Create: `infra/nginx/conf.d/security-headers.inc`
- Create: `infra/nginx/conf.d/security-headers-admin.inc`
- Modify: `infra/nginx/conf.d/default.conf`、`infra/nginx/nginx.conf`、`infra/nginx/cloudflare-tunnel.conf`
- Modify: `infra/docker/web-nginx.conf`、`infra/docker/admin-nginx.conf`、`apps/jbrowse/nginx.conf`
- Modify: `infra/docker/Dockerfile.web`、`infra/docker/Dockerfile.admin`、`apps/jbrowse/Dockerfile`
- Create: `scripts/check_nginx_security_headers.py`（断言在本任务内完成，T31 只接线）

**Steps:**

- [ ] 1. 新建 `infra/nginx/conf.d/security-headers.inc`（**`.inc` 扩展名是强制的**，见 S-10）。
      内容为可在 server 与 location 两级 `include` 的 `add_header` 组，**与 §4.0 规范一致**
      （注意：**无 `media-src`**，**有 `object-src`/`worker-src`**）：
      ```nginx
      # 供 server 级与「自带 add_header 的 location」共同 include。
      # nginx 的 add_header 只在当前层级无 add_header 时继承上层，
      # 因此每个声明了 add_header 的 location 都必须显式 include 本片段。
      #
      # 本片段的 CSP 是 DEV / 自管 nginx 路径专用字面量：
      #   - 生产门户/JBrowse 的 HTML 由 Cloudflare Pages / gh-pages 提供，
      #     其策略由构建期生成（apps/web/scripts/finalize-csp.ts），不经过 nginx；
      #   - 本路径仅在本地/开发 compose 与自管 nginx 中服务 HTML，
      #     因此保留 script-src 'unsafe-inline'（见 docs/ops/static-hosting-security.md）；
      #   - /api/、/data/、/track.gif 等非 HTML 响应 include 本片段无副作用。
      # 与生成侧逐字一致的指令：default-src/style-src/img-src/font-src/
      # base-uri/form-action/frame-ancestors/object-src/worker-src。
      add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https:; frame-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'; object-src 'none'; worker-src 'self' blob:" always;
      add_header Strict-Transport-Security $hsts_header_value always;
      add_header X-Frame-Options "SAMEORIGIN" always;
      add_header X-Content-Type-Options "nosniff" always;
      add_header Referrer-Policy "strict-origin-when-cross-origin" always;
      add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
      ```
- [ ] 2. `$hsts_header_value` 由 `infra/nginx/nginx.conf:106` 的 `map` 提供（`map` 定义在 http 块，
      server/location 均可引用）。**不要**在片段内再定义 `map`。
- [ ] 3. `infra/nginx/conf.d/default.conf`：删除 L34/37/40/41/42/43/44 的服务级 `add_header`，
      改为在 `server {}` 内首部 `include /etc/nginx/conf.d/security-headers.inc;`。
- [ ] 4. 在以下**每个**含 `add_header` 的 location 内追加同一 `include`（放在该 location 的
      `add_header` 之后，共 7 处，行号已实测）：`= /track.gif`(L53)、`^~ /samples/`(L124)、
      `^~ /api/`(L156)、`^~ /data/`(L233)、哈希资源正则(L275)、静态资源正则(L288)、
      **命名 location `@ratelimit`(L349)**（`error_page 429 = @ratelimit` 返回 JSON 错误体，
      其 `add_header Content-Type` 同样会截断继承 → 429 响应丢掉 nosniff/CSP）。
      `location = /50x.html` 无 `add_header`，正常继承，**不要**动。
      **不要**动 `/health`、`/metrics`、`/admin/`、`/pages/`、`/api/v1/blast/`、`/api/v1/auth/`、
      `/browser/`、`/soymutdb-*`、`/mcp`、`location /`（它们无 `add_header`，正常继承）。
- [ ] 5. `infra/docker/web-nginx.conf`：同样 `include /etc/nginx/conf.d/security-headers.inc;`，
      在 L32 哈希资源、L45 `/samples/`、L55 静态资源、**L65 `location /`（最关键：SPA HTML）**
      四处补齐。`location /` 必须至少含 XFO/CSP/nosniff/Referrer-Policy/HSTS。
- [ ] 6. `infra/docker/admin-nginx.conf` 与 `apps/jbrowse/nginx.conf` 用同一片段修复
      （admin 的 `location /` 当前只剩 `Cache-Control`，是本次最高危的一处）。admin 若需
      `frame-ancestors 'none'`，**不要**改片段，而是在 admin 的 location 内覆盖 CSP
      （后声明的 `add_header` 同名指令会覆盖片段值）并加注释说明。
- [ ] 7. 三个 Dockerfile 各加一行 `COPY`，否则容器内 `include` 会因文件缺失而启动失败：
      ```dockerfile
      COPY infra/nginx/conf.d/security-headers.inc /etc/nginx/conf.d/security-headers.inc
      ```
      （jbrowse 的构建上下文是仓库根，路径同上。）
- [ ] 8. **不重复实现断言：** Dockerfile 是否 COPY 了片段、片段是否全 6 头、变量是否已定义
      这三类断言统一放在 `scripts/check_nginx_security_headers.py`（本任务内完成），
      **不**在 `test_dockerfile_contracts.py` 里再写一份（T32 禁止同一断言多处实现）。
- [ ] 9. **两个片段，而非「include 后覆盖」**（执行中发现，必须如此）：
      nginx 会发出同一层级里看到的**每一个**同名 `add_header`。admin 需要更严的
      `DENY`/`no-referrer`/`script-src 'self'`，若先 include 门户片段再覆盖，会送出
      **两个 X-Frame-Options 和两个 CSP**（重复 CSP 是取交集，重复 XFO 是未定义行为）。
      因此 admin 用独立的 `security-headers-admin.inc`，两者声明相同的 6 个头名。
- [ ] 10. **容器配置必须自己定义 `$hsts_header_value`**（执行中发现）：片段引用该变量，
      而容器用的是镜像自带的 `nginx.conf`，里面**没有**主代理的 `map`。未定义变量不是警告而是
      `nginx: [emerg] unknown variable` **启动失败**。容器侧以 `$http_x_forwarded_proto` 为键
      （TLS 在上游终结），取值保持容器原有策略（不带 `preload`）。
- [ ] 11. **`cloudflare-tunnel.conf` 也属本任务范围**（执行中发现，v2 只把它列入 T8）：
      它的 `/api/`、`/jbrowse-data/`、`/data/` 三个 location 各自带 `add_header`，
      把服务级的 nosniff/Referrer-Policy/Permissions-Policy 全部丢掉。因该文件是
      容器的**整个 nginx.conf**（镜像内无 `conf.d/*.inc`），采用**内联**而非 include。
- [ ] 9. **本任务内**先实现 `scripts/check_nginx_security_headers.py` 的核心断言（每个含
      `add_header` 的 location 必须 include 片段或内联全部安全头），使本任务可自证；
      T31 只负责把它接入共享脚本。

**Verify:**
```bash
python3 scripts/check_nginx_security_headers.py
# 语法校验：不要用 -v 覆盖 /etc/nginx（会遮蔽镜像自带 mime.types，见 S-10）
docker run --rm \
  -v "$PWD/infra/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
  -v "$PWD/infra/nginx/conf.d:/etc/nginx/conf.d:ro" \
  nginx:1.27-alpine nginx -t
# 容器配置（web/admin/jbrowse）在镜像构建时由 build-release-image.sh 的 nginx -t 冒烟覆盖
python3 -m pytest scripts/test_dockerfile_contracts.py scripts/test_development_compose_contract.py -q
bash scripts/smoke.sh --profile contracts
```

**⚠️ 本机不可验证项（实测）：** 开发机**既无 nginx 也无 docker**（`command -v nginx` /
`docker info` 均不可用），所以 `nginx -t` 在本环境**无法执行**。替代证据：
`scripts/check_nginx_security_headers.py` 对 6 个配置 / 37 个 location 做静态校验，
并用**9 个变异测试**逐一证明它会变红（丢掉一个 location 的 include、删掉容器的 HSTS map、
重新加回 `X-XSS-Protection`、恢复反射 Origin、把片段改名为 `.conf`、去掉 `worker-src`、
删掉 Dockerfile 的 COPY、COPY 到错误目标）。**真实 `nginx -t` 必须在 CI 的镜像构建里补验**，
并作为 PR 的未验证项声明。

**Accept:**
- 6 个 nginx conf 中每个含 `add_header` 的 location 都能静态证明安全头来源（include 片段或内联）；
  `check_nginx_security_headers.py` 通过，且已用 9 个变异测试证明其会变红。
- 两个片段均声明全 6 个头名；与生成侧在 §4.0 表格「必须逐字一致」的 9 条指令上相同。
- 每个 nginx 镜像的 Dockerfile 都 COPY 了它所 include 的片段。
- `nginx -t` 在 CI 镜像构建中补验（本机无 nginx/docker，已声明为未验证项）。

---

#### T2 · 恢复门户 `_headers` 并建立构建期 CSP 单一来源  ✅ **已执行**

**根因：** `apps/web/public/_headers` 在某次「gh-pages 不解释该格式」的清理中被删除，
但代码与文档四处仍依赖它，且 `deploy/cloudflare.md` 声明 Cloudflare Pages 为可选生产托管
→ 门户在 Pages 上无任何 HTTP 安全头与长缓存。admin 有可复制的正确实现，但它**只补 origin、
不生成策略**，正是 S-6 漂移的来源。

**Files:**
- Create: `packages/shared/src/build/csp.ts`
- Create: `apps/web/public/_headers`
- Create: `apps/web/scripts/finalize-csp.ts`
- Modify: `apps/web/src/lib/deployment.ts`（`buildCsp` 基于 `composeCsp` 重写，行为不变）
- Modify: `apps/web/package.json`、`apps/web/scripts/build-sites.ts`（构建链顺序）
- Modify: `scripts/test_site_artifact_isolation.py`（新增断言）

**Steps:**

- [ ] 1. 新建 `packages/shared/src/build/csp.ts`，导出 `composeCsp(directives)`、
      `parseCsp(text)`、`directivesEqual(a, b, {only, ignore})`。在 `packages/shared/package.json`
      增加子路径导出 `"./build/csp"`（Node 侧构建脚本使用，**不进入浏览器包**）。
- [ ] 2. `apps/web/src/lib/deployment.ts` 的 `buildCsp()` 改为调用 `composeCsp`，**输出必须与
      当前逐字一致**（顺序与内容都不变）→ 既有 `deployment` 测试必须继续通过，不得修改期望值。
- [ ] 3. 创建 `apps/web/public/_headers`，包含：
      - 安全头：`Strict-Transport-Security`、`X-Content-Type-Options: nosniff`、
        `X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: strict-origin-when-cross-origin`、
        `Permissions-Policy: geolocation=(), microphone=(), camera=()`、
        `Cross-Origin-Opener-Policy: same-origin`（门户不需要被跨源 opener 引用）。
      - **一条保守的 CSP 默认行**（不依赖占位符，见第 6 步）：`Content-Security-Policy: default-src 'self'`
      - 缓存规则三档：`/assets/*` → `public, max-age=31536000, immutable`；
        `/` 与 `/*.html` → `public, max-age=0, must-revalidate`；`/*` 规则**不写** Cache-Control
        （避免与 `/assets/*` 逗号合并）。
      - **不写** `frame-ancestors 'none'`（门户需被自身 iframe）。
- [ ] 4. 新建 `apps/web/scripts/finalize-csp.ts`：读取 `dist/**/*.html`，对每页计算其内联脚本
      hash（见 T5），并用 `composeCsp` 生成最终策略，然后：
      - 重写该页 `<meta http-equiv="Content-Security-Policy" content="…">`；
      - 重写 `dist/_headers` 中**那一条** `Content-Security-Policy:` 行为全站并集策略。
      **fail-closed**：`dist/_headers` 缺失、或找不到可替换的 CSP 行 → 抛错退出。
- [ ] 5. **构建链顺序（关键，修正 v1 的时序错误）：** 最终化器必须在**所有** HTML 生成步骤
      **之后**、压缩/清单**之前**。把 `apps/web/package.json` 的 `build` 与
      `build-sites.ts` 的步骤序列改为：
      ```
      vite build
        → ssg-build.ts → generate-samples.ts → fetch-content-snapshot.ts
        → ssg-content.ts → embed-page-definitions.ts
        → finalize-csp.ts        # ← 新增：基于最终 HTML 计算 hash 并写入 meta + _headers
        → gzip-compress.ts       # 压缩必须晚于最终化（否则 .gz 里是旧 CSP）
        → gen-sw.js
        → release-manifest.ts    # 清单必须最后（哈希覆盖最终字节）
      ```
      在 `build-sites.ts` 的 `run(...)` 列表同一位置插入 `finalize-csp.ts`，两个变体都执行
      （`SOYMUTDB_DIST_DIR` 已指向 `dist/external|internal`）。
- [ ] 6. **为什么不用占位符**（v1 的验证缺陷已修正）：Vite 会把 `public/` 原样复制进 `dist/`，
      所以「删掉 `dist/_headers` 再构建会失败」不成立（会被重新复制），而带 `__CSP_POLICY__`
      占位符的 `_headers` 一旦被部分构建（如只跑 `build:ui`）发布出去，就会**发出一条无效的 CSP
      响应头**。因此源文件写**保守但有效的** `default-src 'self'`，最终化器把它替换为精确策略：
      部分构建 = 更严的策略（可能拦 API），而不是无效头。门禁断言最终产物中该行等于生成策略。
- [ ] 7. `scripts/check_artifact_headers.py`（T31 接线，本任务内先实现断言）：
      `_headers` 存在、无 `example.com|localhost|__` 残留、CSP 行与最终 meta 策略同源。
- [ ] 8. **同一任务内**在 `scripts/test_site_artifact_isolation.py` 增加断言：`external` 与
      `internal` 的 `_headers` 分别存在，且 `connect-src`/`frame-src` 与各自构建 origin 一致。

**Verify:**
```bash
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test \
  pnpm --filter @soymutdb/web build:sites

# 1) 两个变体都有 _headers，且 CSP 行是生成策略（不是保守默认，也不是占位符）
grep -c "Content-Security-Policy:" apps/web/dist/external/_headers   # ≥1
! grep -qE "__|example\.com|localhost" apps/web/dist/external/_headers
! grep -q "Content-Security-Policy: default-src 'self'\$" apps/web/dist/external/_headers

# 2) 缓存三档
grep -q "immutable" apps/web/dist/external/_headers
grep -q "frame-ancestors 'self'" apps/web/dist/external/_headers

# 3) origin 注入正确（先确认变量非空，避免 v1 的空变量恒真）
test -n "${VITE_API_BASE_URL:?构建时导出}"
grep -q "${VITE_API_BASE_URL}" apps/web/dist/external/_headers
test -n "${VITE_JBROWSE_BASE_URL:?构建时导出}"
grep -q "${VITE_JBROWSE_BASE_URL}" apps/web/dist/external/_headers

# 4) fail-closed 证明：让最终化器看不到 _headers 时必须报错
#    （用一次性临时目录，不改仓库文件）
SOYMUTDB_DIST_DIR=/tmp/csp-fail-probe pnpm --filter @soymutdb/web exec tsx scripts/finalize-csp.ts \
  && exit 1 || echo "fail-closed OK"

# 5) 单测与产物隔离
pnpm --filter @soymutdb/web test
python3 -m pytest scripts/test_site_artifact_isolation.py -q
bash scripts/check-production-artifact.sh apps/web/dist --allow-demo
```

**执行中发现（v3 补记）：**
- 最终化器**不能**从 `_headers` 里已有的 CSP 推导新策略。它从 `CSP_CONTENT`（模板同一字符串）
  推导；`_headers` 只用于定位那一行并证明它存在。第一版从文件值推导，结果 API/JBrowse origin
  永远进不去（实测 `grep -q https://api.soymutdb.test` 失败）——因为文件里的值是
  finalize 之前的保守默认（仅同源）。
- `buildCsp()` 改写为基于 `composeCsp` 后，输出与原实现**逐字一致**（8/8 组合实测）。
- `node:crypto` 不能出现在 `packages/shared/src/build/csp.ts`：该模块经
  `src/lib/deployment.ts` 被**浏览器包**引用，Vite 会报
  `"createHash" is not exported by "__vite-browser-external"`。故拆出 Node-only 的
  `./build/csp-hash`。

**Accept（已核实）：**
- 两个变体产物均含 `_headers`，CSP 由 `buildCsp`/`composeCsp` 生成，`connect-src`/`frame-src`
  为真实构建 origin，无占位符残留。
- 最终化器在 `_headers` 缺失、CSP 行缺失、无 HTML、dist 缺失时**均 exit 1**（四组探针实测）。
- `buildCsp` 重写后既有测试零改动通过（13 tests），且与旧实现逐字一致。

---

#### T3 · 修复 JBrowse `_headers` 占位符未注入  ✅ **已执行**

**根因：** `apps/jbrowse/public/_headers` 硬编码 `https://api.example.com` /
`https://portal.example.com` / `https://admin.example.com`，`apps/jbrowse/vite.config.ts`
**没有**注入插件（admin 有）→ 实测产物仍为占位符，Pages 上 API 与 embed 全被 CSP 拦截。

**Files:**
- Create: `apps/jbrowse/scripts/inject-headers-origins.ts`
- Modify: `apps/jbrowse/vite.config.ts`、`apps/jbrowse/public/_headers`
- Modify: `scripts/build-pages-artifact.sh`（导出新变量）
- Modify: `scripts/test_site_artifact_isolation.py`（断言）

**Steps:**

- [ ] 1. 复用 T2 的 `packages/shared/src/build/csp.ts`（**不要**复制一份实现），
      在 `apps/jbrowse/scripts/inject-headers-origins.ts` 中用 `composeCsp` 生成 JBrowse 策略并
      替换 `_headers` 中的 CSP 行；**fail-closed**（文件缺失或无可替换行 → 抛错）。
- [ ] 2. JBrowse 需要 4 个来源，全部来自环境变量并校验为合法 HTTPS origin：
      `connect-src` = `'self'` + `VITE_API_BASE_URL` + **`VITE_JBROWSE_DATA_URL`**
      （数据平面 origin，v1 遗漏，缺它则 track 数据被 CSP 拦截）；
      `frame-ancestors` = `SOYMUTDB_PORTAL_ORIGIN` + `SOYMUTDB_ADMIN_ORIGIN`；
      `img-src`/`font-src` 保持 `'self' data:`。
- [ ] 3. 在 `apps/jbrowse/vite.config.ts` 注册（`closeBundle` 或 `apply: "build"`）。
      **生产模式缺失任一 origin 必须抛错**；demo 模式允许 `*.invalid`/`.test` 占位
      （与 `requireDeploymentOrigin` 的既有策略一致）。
- [ ] 4. `scripts/build-pages-artifact.sh` 的 JBrowse 构建段当前只导出 `VITE_JBROWSE_BASE_URL`；
      补上 `VITE_API_BASE_URL`、`VITE_JBROWSE_DATA_URL`（已有默认 `${PAGES_BASE_PATH}jbrowse-data`）、
      `SOYMUTDB_PORTAL_ORIGIN`、`SOYMUTDB_ADMIN_ORIGIN`（demo 用 `${SITE_ORIGIN}` 与
      `${SITE_ORIGIN}${PAGES_BASE_PATH}admin/`）。
- [ ] 5. **同一任务内**在 `scripts/test_site_artifact_isolation.py` 增加断言：
      `pages-dist/soymutdb-jbrowse/_headers` 无 `example.com`，且含真实 API 与数据 origin。

**Verify:**
```bash
# build-pages-artifact.sh 会同时构建 web + jbrowse（v1 误用 build:sites 覆盖 T3，已修正）
bash scripts/build-pages-artifact.sh
! grep -q "example.com" pages-dist/soymutdb-jbrowse/_headers
grep -q "Content-Security-Policy:" pages-dist/soymutdb-jbrowse/_headers
bash scripts/verify-pages-artifact.sh pages-dist
python3 -m pytest scripts/test_site_artifact_isolation.py -q
```

**执行中发现（v3 补记）：**
- `VITE_JBROWSE_DATA_URL` **通常是相对路径**（`build-pages-artifact.sh` 传
  `${PAGES_BASE_PATH}jbrowse-data`）。把它当 origin 校验会直接报错。正确语义：相对引用 =
  同源 = `'self'` 已覆盖，**不加任何源**；只有绝对 URL 才注入 `connect-src`。
- 注入模块**不能带 `#!`**：Vite 用 esbuild 打包 `vite.config.ts` 时会内联其 import，
  内联模块里的 hashbang 是语法错误（实测 `Syntax error "!"`）。
- 源 `_headers` 不得出现占位域名（连注释也不行）—— 否则占位符扫描会把**源文件**也判红。

**Accept（已核实）：** `apps/jbrowse/dist/_headers` 无任何占位域名；
`connect-src` 含 API origin，`frame-ancestors` 含门户 + 管理端 origin；
原策略中的 `worker-src 'self' blob:`、`img-src … blob:` 被完整保留（按指令映射重建，不套模板）。

---

#### T4 · 收紧 conda 部署的代理信任边界

**根因：** `--forwarded-allow-ips=*` 使 uvicorn 对 `X-Forwarded-For` 取**最左**值，而 nginx
用 `$proxy_add_x_forwarded_for`（追加客户端原值）→ `request.client.host` 可伪造。
docker compose 路径已正确（`172.30.252.0/28,172.30.253.0/28`），conda 路径未对齐。

**Files:**
- Modify: `deploy/scripts/conda-services.sh:66`
- Modify: `deploy/scripts/conda-deploy.sh:182`
- Modify: `deploy/conda/README.md:79,99,140`
- Modify: `scripts/test_platform_delivery_contracts.py`（断言）

**Steps:**

- [ ] 1. **systemd 语法修正（v1 的写法无效）：** systemd `ExecStart` **不做** shell 参数展开，
      `${VAR:-default}` 会被原样传给 uvicorn。正确做法是把默认值写进 `Environment=`，
      `ExecStart` 只引用 `${VAR}`：
      ```ini
      Environment=SOYMUTDB_FORWARDED_ALLOW_IPS=127.0.0.1
      ExecStart=/opt/conda/envs/soymutdb/bin/uvicorn app.main:app \
        --forwarded-allow-ips=${SOYMUTDB_FORWARDED_ALLOW_IPS}
      ```
      若使用 `EnvironmentFile=`，该文件**必须是纯 `KEY=VALUE` 字面量**（不得含 shell 插值）。
      `conda-services.sh` 生成的 unit 与 `conda-deploy.sh:182` 的直接调用都要改。
- [ ] 2. 默认值 `127.0.0.1`（仅信任本机 nginx）。若 nginx 不在本机，运维必须显式覆盖为
      nginx 的实际网段。
- [ ] 3. 三处 `--forwarded-allow-ips=*` 全部移除；`deploy/conda/README.md` 增加「反向代理信任边界」
      小节：说明 `127.0.0.1` 的含义、何时改为网段、以及「API 端口直接暴露公网 = 放弃限流与审计真实性」。
- [ ] 4. **同一任务内**在 `scripts/test_platform_delivery_contracts.py` 增加断言：
      `deploy/` 下不得出现 `forwarded-allow-ips=*`，**也不得出现 `0.0.0.0/0`**
      （v1 只禁 `*`，等价危险写法会漏网）。
- [ ] 5. **功能性负向测试（v1 缺失，仅 grep 不足以证明安全）：** 在
      `apps/api/tests/test_client_ip_trust.py` 增加用例：用 `TestClient` 构造
      `X-Forwarded-For: 1.2.3.4`，在 `SOYMUTDB_FORWARDED_ALLOW_IPS` 为默认值时断言
      `request.client.host` **不等于** `1.2.3.4`（即不信任外部注入链），且限流键不随该头变化。

**Verify:**
```bash
! grep -rn "forwarded-allow-ips=\*" deploy/
! grep -rn "forwarded-allow-ips=0.0.0.0/0" deploy/
grep -n "SOYMUTDB_FORWARDED_ALLOW_IPS" deploy/scripts/conda-services.sh   # 必须出现
python3 -m pytest scripts/test_platform_delivery_contracts.py -q
cd apps/api && .venv/bin/python -m pytest tests -q -k "client_ip or forwarded"
```

**Accept:** 全仓无 `forwarded-allow-ips=*` 与 `0.0.0.0/0`；unit 文件用 `Environment=` 字面量 +
`${VAR}` 引用；伪造 XFF 的负向测试通过。

---

#### T5 · CSP 内联脚本收口（G-1）  ✅ **已执行**

**根因：** SSG 产物含 4 类内联脚本，因此必须保留 `'unsafe-inline'`。静态托管无法用 nonce，
**只能走 hash**。本任务把 CSP 从「允许任意内联脚本」收敛为「允许这 N 个已知脚本」。

**v1 的时序缺陷（已修正）：** Vite 的 `closeBundle` 早于 SSG/内容改写，拿不到最终 HTML。
本版把 hash 计算放进 T2 建立的**构建链最终化器**（`finalize-csp.ts`），它在所有 HTML 生成步骤之后运行。

**v1 的第二个缺陷（已修正）：** 「提取所有无 `src` 的 `<script>`」会把 `application/ld+json` 与
`application/json`（`#rl-bootstrap`）也算进去 → hash 列表无谓膨胀。**只对可执行内联脚本**计算 hash
（即 `type` 缺失或为 `text/javascript`/`module`）。

**Files:**
- Modify: `apps/web/scripts/finalize-csp.ts`（hash 计算与写入）
- Modify: `apps/web/scripts/base-template.ts`（外置/删除非必要内联脚本）
- Modify: `apps/web/scripts/ssg-build.ts`（删除 i18n-ready 死代码）
- Modify: `packages/shared/src/build/csp.ts`（`collectInlineScriptHashes`）
- Modify: `docs/ops/static-hosting-security.md`（记录两条路径差异）

**Steps:**

- [ ] 1. **优先外置，而不是无脑 hash**（v1 只做 hash，未减少内联面）。按内联脚本分类处置：

      | 内联脚本 | 位置 | 处置 |
      |---|---|---|
      | `THEME_INIT_SCRIPT` | `base-template.ts:131` | **保留内联 + hash**。它在 `<head>` 同步执行以防 FOUC，外置会引入关键路径请求 |
      | `WIDGET_LOADER_SNIPPET` | `base-template.ts:148` | **保留内联 + hash**（无模块环境的渐进增强，见第 2 步的收窄） |
      | redirect 脚本 | `base-template.ts:462` | **保留内联 + hash**（独立兼容页，已有 `<meta refresh>` 兜底） |
      | i18n-ready | `ssg-build.ts:211` | **删除**：`window.__soymutdb.i18nReady` 全仓**只写不读**（`rg i18nReady` 仅命中定义处），是死代码 → 直接移除该 `bodyScripts` 传参 |
- [ ] 2. 复核 `WIDGET_LOADER_SNIPPET` 是否仍必要：`apps/web/src/lib/widget-loader.ts` 是 SPA 使用的真实模块。
      若确认无模块环境不构成支持的客户端，则**整段删除**（进一步缩小内联面）。若保留，在注释中写明
      支持场景，并在 `packages/i18n` 文案中保持无 JS 提示一致。
- [ ] 3. 在 `packages/shared/src/build/csp.ts` 实现 `collectInlineScriptHashes(html)`：
      仅匹配 `<script>` 中**无 `src`** 且 `type` 为可执行类型的块；对**脚本文本本身**（不含标签、
      不做 HTML 实体解码之外的处理）计算 `sha256-<base64>`，与浏览器一致。
- [ ] 4. `finalize-csp.ts` 用它生成每页 meta CSP 的 `script-src`（**去掉 `'unsafe-inline'`**，
      保留 beacon origin 当 `VITE_CLOUDFLARE_ANALYTICS_TOKEN` 存在时），并把**全站并集**写入
      `dist/_headers`（HTTP 头覆盖整站，故取并集；meta 保持按页精确）。
- [ ] 5. `style-src 'unsafe-inline'` **保留**（Tailwind/AntD cssinjs 运行时注入样式）。
- [ ] 6. **两条路径的差异写入注释与文档**（这是有意为之，不是遗漏）：
      - `apps/web/public/_headers`（Pages/gh-pages 生产路径）→ `script-src` 仅 hash，无 `'unsafe-inline'`；
      - `infra/nginx/conf.d/security-headers.inc`（dev/自管路径）→ 保留 `'unsafe-inline'`，
        片段头部已注明「dev-only，生产 HTML 不由此路径提供」；
      - T31 门禁按 §4.0 表格比较：9 条指令逐字一致，`script-src`/`connect-src`/`frame-src`
        明确允许不同且差异必须与文档一致。
- [ ] 7. **灰度：** 先合并步骤 1–5（meta + `_headers`），观察一个发布周期无 CSP violation 后，
      再执行 T29 的文档与清单标注。
- [ ] 8. **同一任务内**在 `scripts/check_artifact_headers.py` 增加断言：每个页面 meta 的
      `script-src` hash 集合必须是 `_headers` hash 集合的**子集**（防漏注入）；
      `_headers` 的 `script-src` 不得含 `'unsafe-inline'`。

**Verify:**
```bash
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test \
  pnpm --filter @soymutdb/web build:sites

# 1) 无 unsafe-inline（script-src）
! grep -qE "script-src[^;]*'unsafe-inline'" apps/web/dist/external/_headers
! grep -qE "script-src[^;]*'unsafe-inline'" apps/web/dist/external/index.html
grep -q "sha256-" apps/web/dist/external/_headers
grep -q "sha256-" apps/web/dist/external/index.html

# 2) style-src 仍保留（AntD/Tailwind 运行时样式）
grep -qE "style-src[^;]*'unsafe-inline'" apps/web/dist/external/_headers

# 3) JSON/JSON-LD 未进入 hash 列表（防止膨胀）
python3 - <<'PY'
import re, pathlib
h = pathlib.Path("apps/web/dist/external/_headers").read_text()
csp = re.search(r"Content-Security-Policy:([^\n]+)", h).group(1)
hashes = set(re.findall(r"sha256-[A-Za-z0-9+/=]+", csp))
assert len(hashes) <= 8, f"hash 数量异常（{len(hashes)}），检查是否把 application/json 也算进去了"
print("hash count:", len(hashes))
PY

# 4) 浏览器侧无 CSP violation（本地静态服务器）
cd e2e && npx playwright test -c playwright-public.config.ts homepage.spec.ts

# 5) 单测（base-template 期望值需同步更新，属预期改动）
pnpm --filter @soymutdb/web test
```

**执行中结果（v3 补记）：**
- 已删除两段内联脚本：`ssg-build.ts` 的 i18n-ready（`window.__soymutdb.i18nReady` 全仓只写不读）
  与 `base-template.ts` 的 inline widget loader（`build.target=es2022` 保证模块支持；
  `src/lib/widget-loader.ts` 是唯一会跑的加载器；它写的 `widgetCache` 全局无人读）。
- 实测内联可执行脚本从每页 3 段降为 **2 类**：theme-init（35 页）+ redirect（2 页）；
  `_headers` 的 hash 并集 = **2**（远低于 8 的上限）。
- 页面 meta 的 hash 集合是 `_headers` 并集的**子集**（实测 35 页 0 违规）——
  redirect 页**故意不带 meta**，其 hash 只进 `_headers`。

**Accept（已核实）：** `script-src` 无 `'unsafe-inline'`（`_headers` 与 meta 皆是）；
`style-src 'unsafe-inline'` 保留；主题初始化/重定向正常；hash 数 = 2 ≤ 8。

---

### P1 — 部署加固

---

#### T6 · Compose 日志轮转

**Files:** `docker-compose.yml`、`deploy/.env.example`、`docs/ops/production-build.md`、
`scripts/test_production_compose_contract.py`

- [ ] 1. 顶部 anchor：
      ```yaml
      x-logging: &default-logging
        driver: json-file
        options:
          max-size: ${LOG_MAX_SIZE:-50m}
          max-file: ${LOG_MAX_FILE:-5}
      ```
- [ ] 2. 每个**长驻**服务加 `logging: *default-logging`（postgres/clickhouse/redis/redis-celery/
      minio/nginx/api/worker-*/beat/mcp-server/jbrowse/prometheus/grafana/alertmanager/node-exporter/
      postgres-exporter/redis-exporter/tunnel-origin/cloudflared）。一次性服务
      （`migrate`、`migrate-clickhouse`、`minio-init`）可省，**但必须在注释中说明理由**。
- [ ] 3. `deploy/.env.example` 增加 `LOG_MAX_SIZE` / `LOG_MAX_FILE` 注释项。
- [ ] 4. `docs/ops/production-build.md` 增加「磁盘与日志治理」小节（默认值、调优建议、
      以及 nginx 已改为 stdout 的说明，见 T7）。
- [ ] 5. **同一任务内**在 `scripts/test_production_compose_contract.py` 增加断言：
      每个长驻服务都有 `logging.options.max-size`。

**Verify:**
```bash
bash scripts/ci-job-steps.sh run compose-acceptance   # 需 CI fixture 环境变量，见 §5 V16
python3 -m pytest scripts/test_production_compose_contract.py -q
```

**Accept:** 无长驻服务使用无限日志；契约测试新增断言在回滚时变红。

---

#### T7 · nginx 主代理容器加固

**Files:** `docker-compose.yml:585`（nginx 服务）、`infra/nginx/nginx.conf`、
`infra/nginx/conf.d/default.conf`、`scripts/test_production_compose_contract.py`

**根因补充（v1 遗漏，会导致加固后启动失败）：** 只读根文件系统下 nginx 需要可写路径，
且 `cap_drop: ALL` + uid 101 无法绑定 80 端口。

- [ ] 1. `infra/nginx/nginx.conf`：对齐 `cloudflare-tunnel.conf` 已验证的写法
      （**照抄其模式，不要自创**）：
      ```nginx
      pid /tmp/nginx.pid;
      # …
      access_log /dev/stdout main;
      error_log  /dev/stderr warn;
      # …
      client_body_temp_path /tmp/client_temp;
      proxy_temp_path       /tmp/proxy_temp;
      ```
      否则只读根下 nginx 打不开 `/var/log/nginx/*.log` 与 `/var/cache/nginx/client_temp` → 启动失败。
- [ ] 2. `infra/nginx/conf.d/default.conf`：`listen 80;` → `listen 8080;`
      （非 root + `cap_drop: ALL` 不能绑定 <1024）。
- [ ] 3. `docker-compose.yml` 的 nginx 服务对齐 `tunnel-origin` 的加固集，并更新端口与健康检查：
      ```yaml
      ports:
        - "127.0.0.1:8080:8080"
      user: "101:101"
      read_only: true
      cap_drop: [ ALL ]
      security_opt:
        - no-new-privileges:true
      tmpfs:
        - /tmp
        - /var/cache/nginx
      healthcheck:
        test: [ "CMD", "wget", "--spider", "-q", "http://localhost:8080/health" ]
      ```
      （`/tmp` 已承载 pid 与临时目录；`/var/cache/nginx` 仍挂 tmpfs 作为兜底。）
- [ ] 4. 增加 `pids_limit` 与 `mem_limit`（`NGINX_MEMORY_LIMIT` / `NGINX_PIDS_LIMIT`）。
- [ ] 5. **同一任务内**在 `scripts/test_production_compose_contract.py` 增加断言：
      nginx 服务有 `read_only`/`cap_drop`/`no-new-privileges`/`user`/`tmpfs`，
      且 `ports` 与 `listen` 端口一致（8080）。
- [ ] 6. **Docker 可用时**必须实际起容器验证（不能只做 `config --quiet`）：
      `docker compose --profile core up -d nginx` 后确认容器 `healthy` 且
      `docker compose exec nginx nginx -t` 通过。

**Verify:**
```bash
COMPOSE_PROFILES=core docker compose -f docker-compose.yml config --quiet
python3 -m pytest scripts/test_production_compose_contract.py -q
# Docker 可用时（必须执行，否则在 PR 标注为未验证）
docker compose --profile core up -d nginx
docker compose ps nginx --format '{{.Health}}'   # 期望 healthy
docker compose exec nginx nginx -t
```

**Accept:** nginx 容器以非 root 运行、只读根文件系统、健康检查通过；
日志走 stdout/stderr（与 T6 的日志轮转一致）。

---

#### T8 · `/data/` CORS 收敛

**Files:** `infra/nginx/conf.d/default.conf:246-250`、`infra/nginx/cloudflare-tunnel.conf`

- [ ] 1. **改为固定 `Access-Control-Allow-Origin: *`，删除 `$http_origin` 反射**
      （v1 把「补 `Vary`」作为并列选项，但反射 + 共享缓存本身就是风险源，且这些端点
      **无凭据、无敏感数据**）。**实测共 4 处**，逐个替换：
      - `infra/nginx/conf.d/default.conf:65`（`/track.gif`）、`:246`（`/data/`）；
      - `infra/nginx/cloudflare-tunnel.conf:96`（`/jbrowse-data/`）、`:111`（`/data/`）。
      理由：`/data/`、`/jbrowse-data/` 是公开基因组数据、无凭据；`/track.gif` 是 `<img>` 像素，
      不带凭据（`base-template.ts` 的 `<img>` 无 `crossorigin` 属性）→ `*` 安全。
- [ ] 2. 反射删除后 `Vary: Origin` 不再必需；但**门禁规则保留**（防止未来重新引入反射）。
- [ ] 3. 在 `docs/ops/production-security-checklist.md` G-7 记录处置结论（含「为何不用反射」）。
- [ ] 4. **同一任务内**在 `scripts/check_nginx_security_headers.py` 增加断言：
      任何 `$http_origin` 反射必须伴随 `Vary`；且这三个端点不得再出现 `$http_origin`。

**Verify:**
```bash
! grep -rn 'Access-Control-Allow-Origin "\$http_origin"' infra/
grep -c 'Access-Control-Allow-Origin "\*"' infra/nginx/conf.d/default.conf    # ≥2（track.gif + /data/）
grep -c 'Access-Control-Allow-Origin "\*"' infra/nginx/cloudflare-tunnel.conf # ≥2（/jbrowse-data/ + /data/）
python3 scripts/check_nginx_security_headers.py
```

**Accept:** 三处端点使用固定 `*`，全仓无反射 Origin。

---

#### T9 · 请求 ID 校验 + 移除废弃安全头

**Files:** `infra/nginx/nginx.conf:99`、`infra/nginx/conf.d/default.conf:44`、
`infra/docker/web-nginx.conf:16`、`infra/docker/admin-nginx.conf:16`

- [ ] 1. `map` 增加格式校验：仅接受 `^[A-Za-z0-9._-]{1,64}$`，否则回落 `$request_id`：
      ```nginx
      map $http_x_request_id $request_id_to_forward {
          default          $request_id;
          ~^[A-Za-z0-9._-]{1,64}$  $http_x_request_id;
      }
      ```
- [ ] 2. 移除三处 `X-XSS-Protection`（CSP 已覆盖；该头已废弃）。
- [ ] 3. **同一任务内**在 `scripts/check_nginx_security_headers.py` 增加断言：
      全仓无 `X-XSS-Protection`；`$request_id_to_forward` 的 `map` 含格式正则。

**Verify:**
```bash
grep -rc "X-XSS-Protection" infra/ | grep -v ':0' && exit 1 || true
grep -n "A-Za-z0-9._-" infra/nginx/nginx.conf
python3 scripts/check_nginx_security_headers.py
bash scripts/smoke.sh --profile contracts
```

**Accept:** 全仓无 `X-XSS-Protection`；请求 ID 只接受白名单字符，否则回落服务端生成值。

---

#### T10 · 数据服务资源限制

**Files:** `docker-compose.yml:106,132,162,181,198`、`deploy/.env.example`、
`scripts/test_production_compose_contract.py`

- [ ] 1. 为 postgres/clickhouse/redis/redis-celery/minio 增加 `mem_limit` 与 `cpus`，
      默认值走环境变量（`POSTGRES_MEMORY_LIMIT` 等）。
- [ ] 2. 在文件顶部注释维护「资源预算」表（与既有「PostgreSQL 连接预算」并列），
      说明各服务的默认值与扩容时的连带影响（尤其 PostgreSQL 的 `max_connections`）。
- [ ] 3. `deploy/.env.example` 同步变量说明。
- [ ] 4. **同一任务内**在 `scripts/test_production_compose_contract.py` 增加断言：
      5 个数据服务都有 `mem_limit`。

**Verify:**
```bash
COMPOSE_PROFILES=core docker compose -f docker-compose.yml config --quiet
python3 -m pytest scripts/test_production_compose_contract.py -q
```

**Accept:** 数据服务均有上限；契约测试新增断言在回滚时变红。

---

### P2 — 缺陷修复

---

#### T11 · 修复 Admin JetBrains Mono 字体 404  ✅ **已执行**

**根因（Phase 1–3 已验证）：** CSS `@import` 引入的 fontsource CSS 中的相对 `url(./files/…)`
未被 Vite 解析改写，且文件未被 emit；web 端已用「JS import」修复并在注释中记录原因。

**Files:** `apps/admin/src/index.css:2-3`、`apps/admin/src/main.tsx`

- [ ] 1. 删除 `apps/admin/src/index.css` 的两行 `@import "@fontsource/jetbrains-mono/…"`。
- [ ] 2. 在 `apps/admin/src/main.tsx`（`import "./index.css";` **之前**）加入：
      ```ts
      import "@fontsource/jetbrains-mono/latin-400.css";
      import "@fontsource/jetbrains-mono/latin-500.css";
      ```
- [ ] 3. 在 `index.css` 原位置保留注释说明「为何必须走 JS import」（防止回归）。
- [ ] 4. 在 `apps/admin/src/index.css` 的 `@font-face` 处补 `unicode-range` 说明（与 T26 衔接）。

**Verify:**
```bash
pnpm --filter @soymutdb/admin build          # 注意：admin 的构建脚本名是 build，不是 build:web
ls apps/admin/dist/assets/ | grep -c "jetbrains-mono"          # ≥2（woff + woff2）
! grep -q "files/jetbrains" apps/admin/dist/assets/*.css       # 无未解析相对路径
pnpm --filter @soymutdb/admin test
```

**Accept:** 产物含字体文件且 CSS 引用为 hashed 绝对路径（不是 `./files/...`）。

---

#### T12 · Service Worker 站点变体隔离与轮换

**根因：** 缓存名不含站点变体（违反 AGENTS.md「service-worker namespaces 必须分离」）；
`RUNTIME_CACHE` 无版本、activate 不清理；且 `caches.match(request)` **不带 cacheName**，
会跨 cache（含另一变体）匹配。

**v1 的两处错误（已修正）：** ① 只给 `RUNTIME_CACHE` 加变体，`PRECACHE_CACHE` 仍无变体；
② activate「删除非当前变体的缓存」会**主动破坏另一变体**的离线能力 —— 隔离不等于互相清理。

**Files:** `apps/web/public/sw.js`、`apps/web/scripts/gen-sw.js`、
`scripts/test_site_artifact_isolation.py`

- [ ] 1. `gen-sw.js` 注入 `__SITE_VARIANT__`（读 `SOYMUTDB_SITE_VARIANT`/`VITE_SITE_VARIANT`，
      非法值直接抛错），**两个缓存都带变体与版本**：
      ```js
      const PRECACHE_CACHE = `soymutdb-static-${SITE_VARIANT}-v${CACHE_VERSION}`;
      const RUNTIME_CACHE  = `soymutdb-runtime-${SITE_VARIANT}-v${CACHE_VERSION}`;
      ```
- [ ] 2. `activate` 只清理**本变体**的旧版本，**绝不**删除另一变体：
      ```js
      keys.filter((k) =>
        (k.startsWith(`soymutdb-static-${SITE_VARIANT}-`) && k !== PRECACHE_CACHE) ||
        (k.startsWith(`soymutdb-runtime-${SITE_VARIANT}-`) && k !== RUNTIME_CACHE))
      ```
- [ ] 3. **一次性迁移**旧的、无作用域的名称（`soymutdb-static-v*`、`soymutdb-runtime`）：
      它们是历史遗留且**无法归属**任何变体，删除是安全且必要的；在代码注释中写明这一点
      （与第 2 步「不删另一变体」并不矛盾：迁移只针对无变体前缀的旧名字，且只执行一次）。
- [ ] 4. `cacheFirst`/`navigateFirst` 的 `caches.match(request)` 改为
      `caches.match(request, { cacheName: … })`，**禁止跨 cache 匹配**。
- [ ] 5. 为运行时缓存增加容量上限（导航条目 ≤ 30，超出按插入序淘汰），避免无界增长。
- [ ] 6. **同一任务内**在 `scripts/test_site_artifact_isolation.py` 增加负向用例：
      external 产物的 `sw.js` 不含 internal 变体的缓存命名空间，反之亦然；
      且两者的 `PRECACHE_CACHE`/`RUNTIME_CACHE` 字面量互不相同。

**Verify:**
```bash
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test \
  pnpm --filter @soymutdb/web build:sites
grep -o "soymutdb-static-[a-z]*-v[0-9a-zA-Z-]*" apps/web/dist/external/sw.js | sort -u
grep -o "soymutdb-runtime-[a-z]*-v[0-9a-zA-Z-]*" apps/web/dist/external/sw.js | sort -u
grep -o "soymutdb-runtime-[a-z]*-v[0-9a-zA-Z-]*" apps/web/dist/internal/sw.js | sort -u   # 变体不同
! grep -q "soymutdb-runtime\"\|soymutdb-runtime'" apps/web/dist/external/sw.js             # 无无变体旧名
python3 -m pytest scripts/test_site_artifact_isolation.py -q
```

**Accept:** 两个变体的静态与运行时缓存命名空间互不相同；activate 只清理本变体旧版本；
`caches.match` 均带 `cacheName`；隔离负向测试通过。

---

#### T13 · Node 版本韧性（测试层）  ✅ **已执行**

**根因：** Node 25+ 引入内置 `localStorage` 全局（需 `--localstorage-file`）。**实测（Node 26.8.1）：**
`Object.getOwnPropertyDescriptor(globalThis, "localStorage")` → `{ configurable: true, enumerable: false, get: fn }`，
未提供 `--localstorage-file` 时该 getter 返回 `undefined` 并输出
`ExperimentalWarning: localStorage is not available because --localstorage-file was not provided`。
vitest 的 jsdom 环境安装全局时会**跳过已存在于 `globalThis` 的键** → `localStorage` 保持 `undefined`，
`afterEach(() => localStorage.clear())` 抛 `TypeError`。项目 pin Node 24，但开发机/CI 镜像漂移时会得到假失败。

**⚠️ v2 规定的修法不可行（执行时实测推翻）：** v2 写的是
`Object.defineProperty(globalThis, "localStorage", { value: jsdomWindow.localStorage })`。
但 vitest 的 jsdom 环境把 window 别名到了全局对象本身：

```
typeof globalThis.window                    // "object"
globalThis.window === globalThis            // true
globalThis.document.defaultView === globalThis // true
```

于是 `window.localStorage` 读回的仍是那个被遮蔽的 `undefined`，写入后只会把 Node 的 getter
换成值为 `undefined` 的数据属性（实测：描述符从 `hasGet:true` 变成 `hasValue:true`）——**比不改还糟**。
全局上**不存在**可达的 jsdom Storage。

**实际可行的修法（已实测）：** 在 setup 中用**动态 `import("jsdom")` 新建一个 window**，
从它取出真正的 `Storage`（`constructor.name === "Storage"`，`length`/`key()`/`clear()` 均正常）。
jsdom 已是 apps/web 的 devDependency（SSG 脚本在用），动态导入使 `environment: node` 的测试
完全不付这个开销。`sessionStorage` **不需要** shim：实测 Node 26 上它是可用的内存 `Storage`。

**Files:** `apps/web/src/test/setup.ts`（新建）、`apps/web/vitest.config.ts`、`docs/dev/`

- [ ] 1. 新建 `apps/web/src/test/setup.ts`（**只在 DOM 环境且全局缺失时生效**）：
      ```ts
      const g = globalThis as { document?: unknown; localStorage?: unknown };
      if (typeof g.document !== "undefined" && typeof g.localStorage === "undefined") {
        // 不能用 window.localStorage（window === globalThis，读回仍是 undefined）。
        // 动态 import 使 node 环境的测试不加载 jsdom。
        const { JSDOM } = await import("jsdom");
        const { localStorage } = new JSDOM("", { url: "http://localhost/" }).window;
        Object.defineProperty(globalThis, "localStorage", { value: localStorage, configurable: true });
      }
      ```
      注意：jsdom 对不透明 origin 不提供 Web Storage，所以 `url` 必须显式给出。
      文件头需写明**已实测的**事实（含「为何不能用 window.localStorage」的测量结果）。
- [ ] 2. `apps/web/vitest.config.ts` 的 `test` 增加 `setupFiles: ["./src/test/setup.ts"]`
      （**当前没有 setupFiles**，v1 未指明这一点）。
- [ ] 3. `docs/dev/` 记录该兼容层的存在与移除条件（Node 稳定后 / vitest 修复后）。

**Verify:**
```bash
# Node 24（.nvmrc）
PATH=/tmp/node24/bin:$PATH node --version && PATH=/tmp/node24/bin:$PATH pnpm --filter @soymutdb/web test
# Node 26（漂移韧性）—— 已实测：修复前 1 failed，修复后 36 files / 180 tests 全过
N26=/media/rlcao/Data/software/bin; PATH=$N26:$PATH node --version && \
  PATH=$N26:$PATH pnpm --filter @soymutdb/web test
```

**Accept:** 两个 Node 大版本下测试结果一致（36 files / 180 tests 通过）。

---

#### T14 · `.gz` 产物策略 + `precompress.sh` 刷新陈旧件（D-5）  ✅ **已执行**

**根因 A（D-5，中）：** `precompress.sh` 用 `find … -exec gzip -k -9 {} \;`。
`gzip -k` **拒绝覆盖**已存在的 `.gz`（实测 `gzip: a.js.gz already exists; not overwritten`），
于是**保留旧压缩体**：源文件变更后，nginx `gzip_static` 会继续送出陈旧的 `.gz`。
字体最严重 —— `.woff`/`.woff2`/`.ttf` **只由本脚本压缩**，构建链完全不覆盖。

**⚠️ 严重度修正（v2 误判，已实测推翻）：** v2 把此项写成「`gzip -k` exit 2 + `find -exec … +` 非零 +
`set -e` → 中断 web 镜像构建」（严重度「高」）。这是**错的**：脚本用的是 `\;` 而非 `+`，
而 POSIX 下 **`-exec … \;` 永远为真**，不传播命令失败。实测：`-exec false \;` → rc=0，
`-exec false +` → rc=1。v2 的探针误用 `+`，把警告误读成构建失败。
**结论：这是陈旧产物缺陷（中），不是构建中断（高）。** 修复仍然必要，但优先级和风险描述必须纠正。

**根因 B（D-4）：** `.gz` 预压缩文件仅容器 nginx 的 `gzip_static` 使用，
Pages/gh-pages 路径下不生效却让产物体积近乎翻倍。

**Files:** `infra/docker/precompress.sh`、`apps/web/scripts/gzip-compress.ts`、
`apps/web/scripts/gen-sw.js`、`apps/web/package.json`、`apps/web/scripts/build-sites.ts`、
`scripts/build-static-apps.sh`、`infra/docker/Dockerfile.web`、`infra/docker/Dockerfile.admin`、
`docs/ops/production-build.md`、`scripts/test_dockerfile_contracts.py`

- [ ] 1. **修 D-5：** `precompress.sh` 改为「陈旧则重压，最新则跳过」：
      ```sh
      find "$target_dir" -type f \( … \) -exec sh -c '
        for f do
          [ -e "$f.gz" ] && [ "$f.gz" -nt "$f" ] || gzip -9 -f -k "$f"
        done
      ' sh {} +
      ```
      （`-f` 保证覆盖陈旧 `.gz`；`-nt` 保证已是最新时不重压。两者都保留，缺一不可。）
- [ ] 2. 决策：**`.gz` 仅在容器路径生成**。`gzip-compress.ts` 受 `SOYMUTDB_EMIT_GZ=1` 控制；
      `build:sites`（Pages/gh-pages 路径）**不设置**该变量；容器路径
      （`Dockerfile.web`/`Dockerfile.admin`、`build-static-apps.sh`）设置 `SOYMUTDB_EMIT_GZ=1`。
- [ ] 3. `gen-sw.js` 同样受该开关控制（v1 遗漏）：`sw.js.gz` 只在 `SOYMUTDB_EMIT_GZ=1` 时生成，
      否则删除遗留的 `sw.js.gz`（防止旧文件被 `gzip_static` 错误命中）。
- [ ] 4. 容器路径保留双重压缩（构建链 + `precompress.sh`）是**有意为之**：构建链覆盖 HTML/JS/CSS，
      `precompress.sh` 额外覆盖 `.woff2`/`.ttf`（`gzip-compress.ts` 不含字体扩展名）。
      在 `precompress.sh` 注释中写明这一分工与幂等要求。
- [ ] 5. `docs/ops/production-build.md` 记录决策、影响（产物体积 vs 容器 `gzip_static`）
      与 `SOYMUTDB_EMIT_GZ` 的适用范围。
- [ ] 6. **同一任务内**在 `scripts/test_dockerfile_contracts.py` 增加回归测试
      `test_precompress_refreshes_stale_archives`：在临时目录构造源文件 + 人为做旧的 `.gz`，
      运行脚本后断言 `.gz` **已刷新为最新内容**；并断言重复运行 exit 0。
      **已实测回滚变红**：旧脚本 `refreshes stale .gz ? False`，新脚本 `True`。

**Verify:**
```bash
# 1) 陈旧件刷新回归（D-5）
python3 -m pytest scripts/test_dockerfile_contracts.py -q

# 2) Pages 路径无 .gz
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test \
  pnpm --filter @soymutdb/web build:sites
! find apps/web/dist/external -name '*.gz' | grep -q .
du -sh apps/web/dist/external            # 与 v1 基线对比应显著下降

# 3) 容器路径仍生成 .gz（且 gzip_static 未受影响）
SOYMUTDB_EMIT_GZ=1 pnpm --filter @soymutdb/web build
find apps/web/dist -name '*.gz' | head
grep -c "gzip_static" infra/docker/web-nginx.conf    # 仍为 2
```

**Accept:** `precompress.sh` 在源文件变更后刷新 `.gz`，重复运行 exit 0；
Pages 路径产物无 `.gz`；容器路径仍产出 `.gz` 且 `gzip_static` 保持开启；
回归测试在回滚到旧脚本时变红（已实测）。

---

### P3 — UI/UX 优化

> 依据：`ui-ux-pro-max-zh-1.0.0`（优先级 1 无障碍 / 2 触摸交互 / 5 字体与颜色 / 6 动画）
> 与 `design-master-2.1.2`（`ui-ux-data/ux-guidelines.csv`、`design-tokens-spec.md`、`theme-switching.md`）。

---

#### T15 · 修复 destructive 系对比度（WCAG AA）

**v1 的两处错误（已用本仓库 OKLCH→sRGB→WCAG 计算器实测修正）：**
1. v1 建议把 `bg-destructive/10` 改为 `bg-destructive/15`。实测（亮色，`--destructive: oklch(0.58 0.22 27)`）：
   `/10` = 3.99、`/15` = **3.69**、`/6` = **4.25** —— **提高或小幅降低不透明度都不达标**，
   只有降到 `/2`（4.53）才勉强达标，但那已看不出是色块。
2. v1 给出的替代值也不达标：暗色 `--destructive: oklch(0.58 …)` 实测 **4.21**（非 ≈4.6）；
   暗色 `--destructive-foreground: oklch(0.16 …)` 实测 **4.81**（非 ≈6.5，且该方向上限约 5.1）。

**根因（systematic-debugging Phase 2，已数值证明）：** **单一 `--destructive` token 在暗色下无法
同时满足两个角色** ——

| 角色 | 需求 | 实测 |
|---|---|---|
| 填充面（`bg-destructive` + 白字） | 与 `--destructive-foreground` ≥4.5 | L ≤ **0.56**（0.56→4.58；0.58→4.21；0.62→3.57） |
| 文本（`text-destructive` 在 `--card`/`--muted` 上） | 与底色 ≥4.5 | L ≥ **0.66**（0.66→card 5.28 / muted 4.87；0.62→card 4.49 ❌） |

两者矛盾（≤0.56 vs ≥0.66）→ **必须拆成两个 token**。亮色下单一 token 可行（L=0.52 同时满足两个角色）。

**Files:** `apps/web/src/index.css:39-40,80-81`、`apps/web/src/page-builder/renderer.tsx:522`、
`apps/web/src/components/ontology/relationship-graph.tsx:219`、以及 16 个文件中 31 处 `text-destructive`

- [ ] 1. **亮色：** `--destructive: oklch(0.58 0.22 27)` → **`oklch(0.52 0.22 27)`**。实测：
      on `--card` 6.02、on `--muted` 5.51、on 自身 `/10` 叠加底 5.01、白字 on 它 5.82 —— **两个角色都达标**。
- [ ] 2. **暗色：拆 token（已验证值）**
      ```css
      /* [data-theme="dark"], .dark */
      --destructive: oklch(0.56 0.22 27);            /* 填充面：白字 4.58:1 */
      --destructive-emphasis: oklch(0.72 0.20 27);   /* 文本：on card 6.35 / on muted 5.86 / on /10 tint 6.09 */
      ```
      亮色同步声明 `--destructive-emphasis: oklch(0.52 0.22 27);`（= 与 `--destructive` 同值），
      使 `text-destructive-emphasis` 在两个主题下均可用。
- [ ] 3. 在 `@theme` 增加映射 `--color-destructive-emphasis: var(--destructive-emphasis);`
      （与现有 `--color-destructive` 并列）。
- [ ] 4. **迁移文本角色：** 把 16 个文件 / 31 处 `text-destructive` 改为 `text-destructive-emphasis`；
      `bg-destructive`(5 处) / `border-destructive`(4 处) **保持**用 `--destructive`（它们是面/边框角色）。
      用 `grep -rnE "text-destructive([\"' ]|$)" apps/web/src --include='*.tsx'` 确认零残留。
      **注意：不能用 `\b` 边界** —— 实测 `text-destructive\b` **会**匹配 `text-destructive-emphasis`
      （`-` 是非单词字符，`\b` 在此成立），会导致误报。
- [ ] 5. 若坚持不拆 token，则**唯一可行方案**是把叠加不透明度降到 `/2`（4.53:1）
      —— 不推荐（色块不可见），且仍无法修复暗色 `text-destructive` on `card`（4.49 ❌）。
- [ ] 6. 在 `index.css` 注释中写明：`--destructive` 是**面**色，`--destructive-emphasis` 是**文本**色，
      两者不得混用；数值由 `scripts/check_contrast_tokens.py` 推导。

**Verify:**
```bash
python3 scripts/check_contrast_tokens.py            # T17 门禁，含 alpha 合成
python3 scripts/check_contrast_tokens.py --json > /tmp/contrast.json
! grep -rnE "text-destructive([\"' ]|$)" apps/web/src --include='*.tsx'   # 零残留（不能用 \b）
pnpm --filter @soymutdb/web test
```

**Accept:** 亮/暗两主题下 `foreground` 类对 ≥4.5:1；`destructive-foreground` on `destructive` ≥4.5:1；
`text-destructive-emphasis` 在所有底色（card/muted/`/10` tint）上 ≥4.5:1；`border-destructive/40` ≥3:1。

---

#### T16 · 亮色图表色板对比度（WCAG 1.4.11）

**实测不达标（亮色，4 个）：** `chart-2` 2.88、`chart-3` **2.02**、`chart-4` **1.51**、
`impact-moderate` **2.51**（需 ≥3:1）。**已达标、不要动**：`chart-1` 4.44、`chart-5` 6.58、
`impact-high` 4.67、`impact-low` 3.79、`impact-modifier` 3.51。暗色全部达标（5.4–12.6:1）。

**v1 的建议不达标（已实测修正）：** v1 建议「保留 chart-1/5，加深 chart-2/3/4」并给出
`0.58/0.62/0.66` 的亮度斜坡 —— 实测 **3.96 / 3.40 / 2.94**，最后一个仍 <3。
原因：亮色下要达 ≥3:1 需 L ≤ 约 0.64（C≈0.08），可用亮度区间窄，
**单靠亮度斜坡做 5 级区分不可行**，必须用色相分离。

**Files:** `apps/web/src/index.css:41-50`、`apps/web/src/lib/use-echarts.ts:45-54`

- [ ] 1. **已实测达标的候选色板**（两个主题下均 ≥3:1，且 `chart-*` 内部最小色相差 43°）：

      | token | 值 | 亮色 vs `--background` | 暗色 vs `--background` |
      |---|---|---|---|
      | `--chart-1` | `oklch(0.52 0.14 152)` | 5.02 | 3.79 |
      | `--chart-2` | `oklch(0.56 0.13 195)` | 4.06 | 4.69 |
      | `--chart-3` | `oklch(0.60 0.13 250)` | 3.84 | 4.96 |
      | `--chart-4` | `oklch(0.58 0.15 320)` | 4.51 | 4.22 |
      | `--chart-5` | `oklch(0.55 0.15 45)` | 5.04 | 3.78 |
      | `--impact-moderate` | `oklch(0.62 0.17 60)` | 3.72 | 5.12 |

      `--impact-high` / `--impact-low` / `--impact-modifier` **保持原值**（实测亮色 4.67 / 3.79 / 3.51，已达标）。
      暗色若要同步新亮色值也可（实测均 ≥3.78），但**非必需**；若保留暗色原值，必须保留其独立验证。

      色相分离：152 / 195 / 250 / 320 / 45 → 相邻差 43° / 55° / 70° / 85°（均 ≥30°）。
      若执行者选择其它值，**必须**满足「每色 ≥3:1（两主题）+ `chart-*` 内相邻 Δh ≥30° 或 ΔL ≥0.10」，
      并由 T17 门禁验证（不得只凭目测）。
- [ ] 2. 依据 `ui-ux-pro-max` 的 `chart-color-guidance` 补充**非颜色冗余编码**：
      `series.symbol` / `lineStyle.type` / `label.show`，使色盲用户可区分（WCAG 1.4.1）。
      注意色相分离（尤其绿/红）对红绿色盲不足够，冗余编码是**必需项**，不是可选项。
- [ ] 3. `use-echarts.ts` 的 fallback 字面量必须与 `index.css` 新值一致（否则 SSR/首帧取旧色）；
      两处若重复定义，改为从单一常量导出。
- [ ] 4. `--impact-*` 当前在代码中只用作**图表/图例圆点**（非文本图形），实测未发现
      「徽标底色 + 浅色文字」用法。若未来引入该用法，必须单独验证 `*-foreground` 方向
      （实测亮色 `impact-moderate`/`impact-low`/`impact-modifier` 作为底色时白字仅 2.49/3.76/3.48 ❌）；
      T17 的断言清单已预留该方向（默认关闭，`--include-surface-pairs` 开启）。

**Verify:**
```bash
python3 scripts/check_contrast_tokens.py --include-chart
pnpm --filter @soymutdb/web test
# 视觉对比（需要 dist + 浏览器）
cd e2e && npx playwright test -c playwright-visual.config.ts
```

**Accept:** 亮色 4 个不达标色（`chart-2/3/4`、`impact-moderate`）修复后全部 ≥3:1（暗色同）；
`chart-*` 内部满足色相/亮度分离；图表存在颜色以外的区分维度。

---

#### T17 · 对比度自动化门禁（**先写门禁，允许先红**）

**Files:** Create `scripts/check_contrast_tokens.py`

- [ ] 1. 解析 `apps/web/src/index.css` 的 `:root` 与 `[data-theme="dark"], .dark` 块，
      提取全部 `--*: oklch(...)`（含 `/ alpha` 形式）。
- [ ] 2. 实现 OKLCH→sRGB→相对亮度→对比度（纯标准库，不引入依赖），并实现
      **alpha 合成**（`destructive/10` 叠加到 `background`/`muted`/`card` 之上再比较）。
- [ ] 3. 断言清单（可配置，默认全开）：
      - `foreground`/`muted-foreground`/`card-foreground`/`secondary-foreground`/`accent-foreground`
        on 各自底色 ≥4.5:1
      - `primary-foreground` on `primary`、`destructive-foreground` on `destructive` ≥4.5:1
      - **`destructive-emphasis` on `card`/`muted`/`destructive/6`、`/10`、`/15` 叠加底 ≥4.5:1**
        （三种不透明度都检查，防止「改一处漏一处」）
      - **禁止 `text-destructive` 残留**：若 `--destructive` 在任一主题的 `card`/`muted` 上 <4.5:1，
        则断言源码中不得存在 `text-destructive`（只能用于 `bg-`/`border-`）—— 把「拆 token」
        从「实现细节」变成「门禁事实」
      - `chart-*`、`impact-*` on `background` ≥3:1（`--include-chart`），并断言 `chart-*` 内部
        相邻 Δh ≥30° 或 ΔL ≥0.10
      - `--include-surface-pairs`（默认关）：检查 `*-foreground` on `impact-*` 方向（当前代码未使用）
- [ ] 4. 支持 `--json` 输出供 PR 附证据；**文件名统一为 `check_contrast_tokens.py`**
      （v1 在文档中混用 `check-contrast-tokens.py`，已统一）。
- [ ] 5. **校准证据（强制）：** 门禁实现后，先用**修复前**的 token 跑一次，输出必须
      复现本计划的实测值（`destructive-foreground` on dark destructive = 3.57、`chart-3` = 2.02、
      `chart-4` = 1.51、`impact-moderate` = 2.51、亮色 `text-destructive` on `/10` = 3.99）。
      若数值不一致，说明转换公式有误，**必须先修门禁再修 token**（否则修完仍不知道是否达标）。
- [ ] 5. **执行顺序要求：** 本任务先于 T15/T16 完成，且此时门禁**必须为红**
      （记录红色输出作为 Phase 4 证据）。

**Verify:**
```bash
python3 scripts/check_contrast_tokens.py --include-chart; echo "exit=$?"
# 期望：此阶段 exit=1（未修复）；T15/T16 完成后 exit=0
# 校准：修复前的输出必须复现 3.57 / 2.02 / 1.51 / 2.51 / 3.99 这几个值
python3 scripts/check_contrast_tokens.py --include-chart --json | head -40
```

**Accept:** 门禁在未修复时**必须为红**（先写测试再修，符合 systematic-debugging Phase 4）；
修复后为绿；`--json` 可产出证据。

---

#### T18 · 触摸目标 44×44

**Files:** `apps/web/src/components/site-header.tsx`（移动抽屉与图标按钮）、
`apps/web/src/components/data-table.tsx`、`apps/web/src/routes/**` 表单

- [ ] 1. 按 `ux-guidelines.csv` 的 `touch-target-size`（44×44，High）与 `touch-spacing`（≥8px）：
      移动端抽屉条目、图标按钮（搜索/主题/语言/动画）加 `min-h-11 min-w-11`。
- [ ] 2. AntD `Button` 在移动断点使用 `size="large"` 或显式 `style={{ minHeight: 44 }}`。
- [ ] 3. 表格移动视图（`data-table.tsx` 的紧凑 `<ul>`）条目加 `min-h-11`。
- [ ] 4. **同一任务内**在 `e2e/tests/accessibility.spec.ts` 增加断言（该文件属 `playwright-public.config.ts`）。

**Verify:**
```bash
# 注意：默认 playwright.config.ts 只跑 online-smoke.spec.ts，必须指定 public 配置
cd e2e && npx playwright test -c playwright-public.config.ts accessibility.spec.ts
```

**Accept:** 390×844 视口下无 <44px 的可点击目标（豁免项在测试中显式列出理由）。

---

#### T19 · 焦点 / 键盘 / 动态内容播报回归

**Files:** `e2e/tests/accessibility.spec.ts`、`apps/web/src/routes/**`

- [ ] 1. 扩展 `accessibility.spec.ts`：对首页、搜索页、突变体详情页、工具表单页断言
      「Tab 序列与视觉顺序一致」「每个可聚焦元素有可见焦点环（`outline`/`ring` 非 none）」。
- [ ] 2. 按 `web-interface.csv` 的 `aria-live` 要求：为异步结果区（搜索结果计数、上传进度、
      分析任务状态）补 `aria-live="polite"`，错误用 `role="alert"`。
- [ ] 3. 图标按钮补 `aria-label`（现状 8+ 处已有，补齐剩余）。

**Verify:**
```bash
cd e2e && npx playwright test -c playwright-public.config.ts accessibility.spec.ts
```

**Accept:** 三个视口 × 四个页面全部通过；无「焦点不可见」失败。

---

#### T20 · 空态 / 错误态 / 加载态一致性

**Files:** Create `apps/web/src/components/empty-state.tsx`；改造 `routes/**`、`components/**` 中的内联态

- [ ] 1. 抽取统一组件：`EmptyState` / `ErrorState` / `LoadingState`（骨架屏），
      统一图标（AntD 图标，非 emoji）、标题、描述、可选动作、`role`（`status`/`alert`）。
- [ ] 2. 按 `ux-guidelines.csv` 的 `loading-states`（High）与 `content-jumping`（High）：
      异步区域预留占位高度，避免布局位移（CLS）。
- [ ] 3. 替换各路由中手写的「暂无数据」「加载失败」为统一组件；
      **`file-viewer` 内部的 `ErrorState` 保持独立**（它绑定 viewer 局部状态，强行统一会引入耦合），
      但必须复用同一视觉规格（在组件注释中说明这一例外）。
- [ ] 4. **同一任务内**在 `e2e/tests/web-artifact-performance.spec.ts` 增加 CLS 断言（见 T25 的指标采集）。

**Verify:**
```bash
pnpm --filter @soymutdb/web typecheck && pnpm --filter @soymutdb/web test
cd e2e && npm run test:web-performance     # T25 完成后；含 CLS 断言
```

**Accept:** 无重复实现（file-viewer 例外已注明理由）；CLS 不劣化。

---

#### T21 · 动效规范审计

**Files:** `apps/web/src/index.css`（reduced-motion / reduced-data）、`apps/web/src/lib/motion-policy.ts`、
`apps/web/src/components/**`

- [ ] 1. 按 `ux-guidelines.csv`：微交互时长 150–300ms（`duration-timing`），
      仅动画 `transform`/`opacity`（`transform-performance`），单视图动效元素 ≤2（`excessive-motion`）。
- [ ] 2. 审计 `transition: width/height/top/left` 用法。**明确豁免并加注释**（不是全部删除）：
      - `routes/analyses/fastp.tsx:217`、`routes/analyses/scanpy.tsx:227` 的
        `transition-[width]` 是**进度条**，宽度即语义值，改用 transform 会破坏 `role="progressbar"`
        的可读宽度与 `aria-valuenow` 一致性 → **保留**，并在注释中说明豁免理由；
      - `index.css:381` 的 `.skip-link { transition: top }` 是焦点出现动画，`top` 从 `-100%` 到 `1rem`；
        改用 `transform: translateY()` 可避免布局属性动画 → **改**。
- [ ] 3. 确认 `prefers-reduced-motion` 覆盖所有 `motion/` 组件（含 ECharts 动画已受 `intensity` 控制）；
      补 `prefers-reduced-data` 对 view-transition 与进度条的覆盖（U-7）。
- [ ] 4. **同一任务内**在 `e2e/tests/accessibility.spec.ts` 增加 `reducedMotion: 'reduce'` 上下文的用例。

**Verify:**
```bash
# 只允许已注释豁免的命中
grep -rn "transition.*\(width\|height\|top\|left\)" apps/web/src --include='*.tsx' --include='*.css'
cd e2e && npx playwright test -c playwright-public.config.ts accessibility.spec.ts
```

**Accept:** 无「未注释的」布局属性动画；进度条豁免有注释与理由；reduced-motion 下无动效。

---

#### T22 · 微文案与 i18n 可操作性（**前端映射，不改 API 契约**）

**v1 的问题（已修正）：** v1 直接改 `apps/api/app/**` 的错误消息文本，会破坏稳定的错误码契约、
影响客户端分支判断，并可能触发 `test_contract_visibility.py` 的可见性断言。
**正确做法：API 保持稳定错误码与结构化 detail，前端把错误码映射为「发生了什么 + 怎么办」。**

**Files:** `packages/i18n/src/locales/*`、`apps/web/src/lib/`（错误映射）、`apps/web/src/routes/**`

- [ ] 1. 在 web 侧建立错误码 → 文案映射（例如 `apps/web/src/lib/error-messages.ts`）：
      输入 API 的结构化错误（`code`/`detail`），输出可操作文案；未识别的错误码回落到通用文案
      **并保留原始 code 便于排查**。
- [ ] 2. 按 `ux-guidelines.csv` 的 `error-feedback`（High）与 `error-placement`：
      文案为「发生了什么 + 怎么办」句式，而非裸错误码。
- [ ] 3. `pnpm --filter @soymutdb/i18n check:locale-keys` 保持零缺口；新增文案中英同步。
- [ ] 4. 表单错误下方就近展示，且首个错误自动聚焦（`inline-errors`）。
- [ ] 5. **同一任务内**增加负向测试：断言错误响应体仍只含公开字段
      （不泄漏 `internal_id`），并断言映射函数对未知 code 不会抛异常。

**Verify:**
```bash
pnpm --filter @soymutdb/i18n check:locale-keys
pnpm --filter @soymutdb/web test
cd e2e && npx playwright test -c playwright-public.config.ts public-login.spec.ts
```

**Accept:** i18n 零缺口；错误可操作且就近、可聚焦；API 契约与错误码未变更；
未知错误码有回落路径且不抛异常。

---

### P4 — 性能

---

#### T23 · 静态资源缓存策略（依赖 T2）

**Files:** `apps/web/public/_headers`（T2 产物）、`docs/ops/static-hosting-security.md`

- [ ] 1. `/assets/*` → `public, max-age=31536000, immutable`（Cloudflare Pages 路径）。
- [ ] 2. HTML → `public, max-age=0, must-revalidate`。
- [ ] 3. gh-pages 路径（无 `_headers`）无法设置长缓存：在文档中明确该差异，
      并说明 Service Worker 的 precache（cache-first）是重复访问的补偿手段（**注意 T24 会缩小
      precache 范围，文档必须同步说明「补偿范围仅限应用壳」**）。
- [ ] 4. 生产切换到 Cloudflare Pages 时，把「`_headers` 已生效」列为 Go/No-Go 检查项。

**Verify:**
```bash
grep -q "immutable" apps/web/dist/external/_headers
# 部署后（需真实主机）
# curl -sI https://<host>/assets/<hashed>.js | grep -i cache-control
```

**Accept:** hashed 资源返回 `immutable`；文档记录 gh-pages 差距与 SW 补偿的真实范围。

---

#### T24 · Bundle 预算扩展（**修正 glob 与静默 SKIP**）

**v1 的问题（已修正）：** 实际产物名为 `cytoscape.esm-*.js`、`mammoth.browser-*.js`、
PDF worker 为 `*.mjs`、highlight.js **被打进 `common-*.js`**（无独立 chunk）。
v1 的 glob 全部匹配不到 → 门禁静默 `SKIP` = 假通过。

**Files:** `scripts/check-bundle-size.sh`

- [ ] 1. 按**实测产物名**增加重 chunk 预算（阈值 = 当前实测 gzip + 15% 余量，写入脚本头部注释）：

      | glob（实际） | 实测原始大小 |
      |---|---|
      | `echarts-*.js` | 1.04 MB |
      | `antd-*.js` | 0.95 MB |
      | `mammoth.browser-*.js` | 0.50 MB |
      | `cytoscape.esm-*.js` | 0.44 MB |
      | `pdf-*.js` | 0.33 MB |
      | `common-*.js` | 0.16 MB（**highlight.js 在此**） |
      | `pdf.worker.min-*.mjs` | —（单独列出，避免与 `.js` 混计） |
- [ ] 2. **消除静默 SKIP：** 把 chunk 分为
      - `required`（必须存在，缺失即 FAIL）：`index-*`、`antd-*`、`react-*`、`router-*`、`common-*`；
      - `heavy-optional`（存在即计预算，缺失默认 **FAIL**，仅当调用方显式设置
        `SOYMUTDB_ALLOW_MISSING_HEAVY_CHUNKS=1` 时打印 SKIP 并说明原因，供 minimal 部署使用）。
- [ ] 3. 增加「总 JS gzip 体积」预算，防止碎片化规避单 chunk 门禁。
- [ ] 4. `DIST_DIR` 默认值改为 `apps/web/dist/assets`，并支持显式传入
      `apps/web/dist/external/assets`（T25 双产物调用）。
- [ ] 5. **同一任务内**增加自测：
      - `--self-test` 构造「完整 required 布局 + 一个超大 chunk」，断言脚本 **FAIL**；
      - 空目录 / 缺 required chunk 也必须 **FAIL**（而非 v1 的静默 SKIP）。

**Verify:**
```bash
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test \
  pnpm --filter @soymutdb/web build:sites
bash scripts/check-bundle-size.sh apps/web/dist/external/assets
bash scripts/check-bundle-size.sh apps/web/dist/internal/assets
bash scripts/check-bundle-size.sh apps/web/dist/assets        # verify-frontend-artifacts 的调用路径

# 自测 1：required chunk 缺失必须失败（新规则；空目录也应当 FAIL，而不是 SKIP）
mkdir -p /tmp/bundle-probe/assets
bash scripts/check-bundle-size.sh /tmp/bundle-probe/assets && exit 1 || echo "required 缺失正确失败"

# 自测 2：超限必须失败（由脚本内 --self-test 构造「完整布局 + 超大 chunk」）
bash scripts/check-bundle-size.sh --self-test
```

**Accept:** 所有实测重 chunk 都被计入预算；缺失 required chunk 即 FAIL；
`heavy-optional` 的 SKIP 需要显式开关；总 JS 预算生效。

---

#### T25 · 双产物资源时序基线

**v1 的问题（已修正）：** v1 只改 spec，但 `playwright-web-performance.config.ts` 的 `baseURL`
与 `static-server.mjs` 参数、以及 spec 内**硬编码的 `artifactRoot`** 都未参数化 → 无法测第二个变体。

**Files:** `e2e/playwright-web-performance.config.ts`、`e2e/tests/web-artifact-performance.spec.ts`、
`e2e/static-server.mjs`、`e2e/package.json`

- [ ] 1. 参数化 `playwright-web-performance.config.ts`：
      `SOYMUTDB_PERF_DIST`（默认 `../apps/web/dist/external`）、`SOYMUTDB_PERF_BASE_PATH`（默认 `/`）、
      `SOYMUTDB_PERF_PORT`（默认 4175），并把它传给 `static-server.mjs`。
- [ ] 2. spec 内的 `artifactRoot` 改为读同一环境变量（**消除硬编码 `apps/web/dist`**）。
- [ ] 3. 报告按变体输出到 `test-results-web-performance/performance-report-<variant>.json`，
      避免两次运行互相覆盖。
- [ ] 4. 采集指标：`FCP`/`LCP`（`PerformanceObserver` + `buffered: true`）、`CLS`、TBT 代理
      （`longtask` 总时长）与 `initialScriptTransferBytes`；**每次运行取 3 次导航的中位数**，
      以降低 CI 抖动（`web-perf` 方法学，以 Resource Timing 代替 Chrome DevTools MCP）。
- [ ] 5. `e2e/package.json` 增加
      `test:web-performance:external` 与 `test:web-performance:internal`（保留原 `test:web-performance`
      作为 external 别名），并更新 `docs/` 基线值与回归阈值。
- [ ] 6. 阈值必须宽松到本地 Chromium 稳定通过（记录实测值与余量），并对超限给出明确失败信息。

**Verify:**
```bash
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test \
  pnpm --filter @soymutdb/web build:sites
cd e2e && npm run test:web-performance:external
cd e2e && npm run test:web-performance:internal
ls test-results-web-performance/performance-report-*.json
```

**Accept:** 两个产物各自产出基线报告（含 LCP/CLS/TBT 代理）；阈值超出即失败；
报告可对比且不互相覆盖。

---

#### T26 · 字体负载治理（**方向修正**）

**v1 的方向错误（已修正）：** v1 要求「首屏关键字体（Inter latin-400/600）加 preload」。
实测 web **没有** Inter/Fraunces Web 字体（`index.css:115-117` 用系统 CJK 栈 + JetBrains Mono），
`discoverAssets()` 的 `fontPreloads` 正则匹配 Inter/Fraunces/JetBrains，实际只匹配到 JetBrains。
为不存在的字体加 preload 是无效改动。**真正的负载是 HarmonyOS：每份 12.8 MB。**

**Files:** `apps/web/public/fonts/harmonyos/**`（删除）、`apps/admin/src/index.css`、
`apps/jbrowse/src/index.css`、`scripts/check-bundle-size.sh`、`docs/`

- [ ] 1. **删除 web 的死负载（可独立先行）：** `apps/web/public/fonts/harmonyos/` 三个 woff2
      共 12.8 MB，web CSS 已不引用（`index.css:861-863` 注释明确说明改用系统 CJK 栈）。
      删除前用 `rg "HarmonyOS-Sans|fonts/harmonyos" apps/web` 证明 web 无引用，
      在 `index.css` 原注释处补一句「字体文件已从 public 移除，勿再添加」。
- [ ] 2. **同一任务内**在 `scripts/check-bundle-size.sh` 增加断言：
      `apps/web/dist/**/fonts/harmonyos` 不得存在（防止有人把文件加回来）。
- [ ] 3. **admin / jbrowse 的治理（评估 + 记录，不承诺无工具的子集化）：**
      - 确认 `font-display: swap` 已存在（是）；
      - 为 3 个 `@font-face` 补 `unicode-range`，使拉丁字符不触发 4.2 MB CJK 字体下载；
      - **子集化需要 `fonttools`（`pyftsubset`），不在现有 CI 依赖内** → 本任务只**记录决策**：
        在 `docs/dev/performance-optimization-plan.md` 写明「未子集化」的现状、测量方法、
        以及若实施必须提交再生成脚本与字体 provenance（不静默推迟）。
- [ ] 4. `apps/web/scripts/base-template.ts` 的 `discoverAssets()` 字体正则收窄到实际存在的字体
      （移除 Inter/Fraunces 死分支），避免未来误 preload 不存在的文件。
- [ ] 5. 保留 JetBrains Mono 的 2 个 preload（当前真实使用且体积小）。

**Verify:**
```bash
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test \
  pnpm --filter @soymutdb/web build:sites
! find apps/web/dist/external -path '*fonts/harmonyos*' | grep -q .
du -sh apps/web/dist/external               # 对比基线应下降约 12.8 MB
bash scripts/check-bundle-size.sh apps/web/dist/external/assets
pnpm --filter @soymutdb/admin build && du -sh apps/admin/dist
```

**Accept:** web 产物不含 HarmonyOS 死负载（−12.8 MB/变体）；
admin/jbrowse 的 `unicode-range` 生效且子集化决策有书面记录；无「为不存在字体加 preload」。

---

### P5 — 工程卫生

---

#### T27 · 清零 lint warnings（**分批 + 行为回归**）

**v1/v2 的问题（已修正）：** v1 只列了 2 个文件，v2 只算了 web 的 37 条。**实测 workspace 为
0 errors / 90 warnings**：web 37、admin 53、jbrowse 0。V2 要求的是 workspace 清零，所以 admin 的 53 条
也在范围内（否则门禁永远不可能变绿）。

**Files（web，按批次）:**
- 批次 1 — 真实缺陷类：`apps/web/src/routes/browser.tsx:152`（Cannot access refs during render）、
  `apps/web/src/components/soymutdb-widget.ts:41`（无效 disable）、`:420`（`no-console`）
- 批次 2 — effect 内同步 `setState`：`file-viewer/{code-viewer,docx-viewer,file-preview-dialog,
  markdown-viewer,pdf-viewer}.tsx`、`genome-browser-widget.tsx:265`、`site-header.tsx:158`、
  `track-viewer.tsx:254`、`routes/{blast,browser,genes/index,mutants/index,search}.tsx`、
  `routes/search/{gbrowse,location,primer}.tsx`、`routes/tools/seqfetch.tsx`
- 批次 3 — `useMemo`/`useEffect` 依赖不稳定：`routes/genes/$geneId.tsx:77`、
  `routes/search/{gbrowse,location,primer}.tsx`、`routes/tools/enrichment.tsx:229`
- 批次 4 — 其它：`search.tsx:35`（`any`）、`enrichment.tsx:780`（无效 disable）、
  `genome-browser-widget.tsx:271`（missing dep）、`file-preview-dialog.tsx:185`（missing dep）

- [ ] 1. **批次 1 优先**（真实缺陷）：`browser.tsx` 的 render 期 ref 访问改为
      `useEffect`/`useLayoutEffect` 中读取，或改用 `useState` 保存所需值。
- [ ] 2. **每批必须附行为回归测试**（不是只改 lint）：
      - 批次 1：`browser.tsx` 的渲染/交互测试（若缺失则补）；
      - 批次 2：`seqfetch` 的 assembly 初始化改为派生状态
        （`const assembly = selected ?? def?.name`）或事件驱动，并补「切换 dataset 时 assembly 正确」
        的测试；file-viewer 各 viewer 的加载态测试；
      - 批次 3：`enrichment.tsx` 的 `terms` 包进 `useMemo` 并补「相同输入不重复请求」的测试
        （对照 `apps/web/src/test/mocks.ts` 中关于 `t` 身份稳定的教训）。
- [ ] 3. 逐条处理剩余 warnings；**不**使用全局 `eslint-disable` 兜底；
      确需抑制的必须在**同一行**写明理由。
- [ ] 4. **同时处理 `@soymutdb/admin` 的 53 条 warnings**（实测计数）：先按规则分组
      （`react-hooks/set-state-in-effect`、依赖不稳定、无效 disable 等），同样**每批附行为回归**；
      `@soymutdb/jbrowse` 实测 0 条，只需在验证中确认仍为 0。
      最后用 `pnpm lint`（workspace）确认 0/0。

**Verify:**
```bash
PATH=/tmp/node24/bin:$PATH pnpm --filter @soymutdb/web lint     # 期望 0 problems
PATH=/tmp/node24/bin:$PATH pnpm --filter @soymutdb/admin lint   # 期望 0 problems（基线 53）
PATH=/tmp/node24/bin:$PATH pnpm --filter @soymutdb/jbrowse lint # 期望 0 problems（基线 0）
PATH=/tmp/node24/bin:$PATH pnpm lint                            # workspace 整体 0/0
pnpm --filter @soymutdb/web test                                # 180 passed（含新增回归）
pnpm --filter @soymutdb/admin test                              # 127 passed
pnpm typecheck
```

**Accept:** `pnpm lint`（workspace）输出 0 errors 0 warnings；每批附行为回归测试且全绿。

---

#### T28 · 代码审查规则降噪（**禁止削弱判定**）

**v1 的三处安全回归（已修正）：**
1. 「排除 `**/__tests__/**`、`*.test.*`、`fixtures/`」→ 会漏掉**误提交的真实密钥**（测试文件同样禁止提交真实凭据）；
2. 「同一文件出现 `DOMPurify.sanitize` 即降级」→ 无法证明**该 sink 使用了已清洗的值**（清洗了 A、插入 B 是真实漏洞模式）；
3. 「`policy.createHTML` 视为已有清洗」→ **错**：`trustedTypes.createPolicy('x', { createHTML: s => s })`
   只是 Trusted Types 包装（`base-template.ts:160-162` 正是这种直通实现），**不是清洗器**。

**Files:** `tools/code-review/review.py`

- [ ] 1. `SEC-SECRET`：**不排除任何目录**。改为
      - 对高熵/真实凭据模式（长随机串、`sk-`/`ghp_`/`AKIA` 等）始终报 high；
      - 对**明确的测试夹具**（如 `password: "test-password"`、`PASSWORD=ci-...`）用
        **行内 allowlist 注释**（`// review:allow SEC-SECRET <reason>`）或
        **规则级 + 精确路径 + 理由**的 allowlist 文件，且每条都要有 reason 字段；
      - 目标：**0 个未审阅 high**，而不是「high ≤ 2」。
- [ ] 2. `SEC-XSS`：改为**数据流邻近**判定 —— 仅当 sink（`innerHTML`/`dangerouslySetInnerHTML`/
      `insertAdjacentHTML`/`document.write`）的**同一表达式或紧邻语句**中存在清洗调用时才降级为 info，
      并输出「已就近清洗」的判定依据。**不得**把 `policy.createHTML` 当作清洗器。
- [ ] 3. `PERF-N1`：仅在循环体内**直接**出现 `await session.execute`/`session.get`/`session.scalar`
      时报告；排除 dict/list 推导与 `sorted()` 迭代。
- [ ] 4. 增加 `--baseline tools/code-review/baseline.json` 支持：既有历史问题不阻断增量审查，
      但**baseline 中的条目必须逐条带 reason**，且 baseline 更新需在 PR 中显式说明。
- [ ] 5. **同一任务内**增加规则回归测试：用固定样例断言
      - 真实形态的密钥仍报 high；
      - 「清洗了 A、插入 B」仍报 high；
      - `createHTML: s => s` **不**导致降级；
      - `search/cache.py:31`、`features.py:131` 不再命中。

**Verify:**
```bash
python3 tools/code-review/review.py --project apps --output /tmp/rev
python3 -m pytest tools/code-review/tests -q 2>/dev/null || python3 tools/code-review/review.py --self-test
# 断言：critical=0 且 high 全部有 reason 或已就近清洗依据（0 个未审阅）
```

**Accept:** 误报清零且**判定未被削弱**；真实问题仍被捕获；
`search/cache.py:31`、`features.py:131` 不再命中；规则回归测试通过。

---

#### T29 · 文档漂移修正

**Files:** `deploy/cloudflare.md`、`docs/design/deployment-architecture.md`、
`apps/web/vite.config.ts:29,47`、`apps/web/scripts/base-template.ts:263`、
`docs/ops/production-security-checklist.md`、Create `docs/ops/static-hosting-security.md`

- [ ] 1. 修正所有「`apps/web/public/_headers` 存在」的表述（T2 后已成立，需核对描述与实际一致，
      特别是「CSP 文本逐字一致」的旧说法要改为 §4.0 的**按指令类别比较**规则）。
- [ ] 2. 新建 `docs/ops/static-hosting-security.md`：并列 gh-pages（无 `_headers`，安全头不可控）
      与 Cloudflare Pages（`_headers` 生效）的差异表，给出生产切换的 Go/No-Go 清单；
      并写明**两条 CSP 路径**（生成侧 vs nginx dev 字面量）的差异与理由。
- [ ] 3. `docs/ops/production-security-checklist.md` §4：G-1 标注「T5 已处置 + 证据」、
      G-4 标注「静态边界已由 T2/T3 收口」、G-7 标注「T8/T9 已处置」。
- [ ] 4. 修正 `vite.config.ts` / `base-template.ts` 中关于 `_headers` 的注释为当前事实。
- [ ] 5. **严格扫描的适用范围要写清**（v1 的 V9 会误报）：`check-production-artifact.sh` 的严格模式
      只适用于真实 release API 构建；demo/offline 构建必须用 `--allow-demo`。
      实测：当前 `apps/web/dist`（demo）严格模式 **exit 1**（`samples/SMDB-*.html` 含演示标记），
      `--allow-demo` 才 exit 0。

**Verify:**
```bash
grep -rn "public/_headers" docs/ apps/web/{vite.config.ts,scripts/base-template.ts}
bash scripts/check-production-artifact.sh apps/web/dist --allow-demo     # demo 构建
# 严格模式只在真实 release API 构建后执行（见 §5 V9）
```

**Accept:** 文档与仓库实际一致；严格扫描的适用范围在文档中明确；
`--allow-demo` 在 demo 构建上通过。

---

#### T30 · `module_import_service` SQL 侧过滤 + 确定性排序

**Files:** `apps/api/app/services/module_import_service.py:34`

- [ ] 1. 把 Python 侧过滤改为 SQL 过滤：
      `DataSet.validation_evidence["module_key"].astext == module_key`
      （SQLAlchemy JSONB `.astext`；确认导入路径，`sqlalchemy[asyncio]>=2.0.36` 已支持）。
- [ ] 2. **确定性排序（v1 遗漏）：** 「首个匹配」当前无 `ORDER BY`，语义不确定。
      定义稳定排序（建议 `order_by(DataSet.created_at.desc(), DataSet.id.desc())`）并在 docstring
      写明「返回最新一个匹配的 module 数据集」，避免行顺序依赖。
- [ ] 3. 评估索引：若该查询在 release 内被频繁调用，考虑对
      `(release_id, (validation_evidence->>'module_key'))` 建表达式索引；本任务只**评估并记录**
      结论（含 `EXPLAIN` 证据），不强制新增迁移。
- [ ] 4. **同一任务内**增加回归测试：同 release 下多个 `module_tsv` 数据集时，
      只返回目标 module；并断言两次调用结果一致（排序确定性）。

**Verify:**
```bash
cd apps/api && .venv/bin/python -m pytest tests -q -k module_import
# 需 PostgreSQL（Docker 不可用时在 PR 标注，并由 T33 在 CI 补验）
```

**Accept:** 行为不变（返回目标 module 数据集）、查询不拉取全量、排序确定；
回归测试覆盖多数据集与重复调用。

---

### P6 — 门禁与回归

---

#### T31 · 门禁接入共享脚本（**只做接线，不得写入 workflow**）

**前提：** 三个检查脚本的**核心断言已在 T1/T2/T3/T8/T9/T12/T14/T17/T26 内实现并自证**。
本任务只负责「接入共享脚本 + 确认无重复实现」。

**Files:** `scripts/check_nginx_security_headers.py`、`scripts/check_contrast_tokens.py`、
`scripts/check_artifact_headers.py`、`scripts/verify-frontend-artifacts.sh`、
`scripts/smoke.sh`、`scripts/ci-job-steps.sh`

- [ ] 1. `check_nginx_security_headers.py`（**已在 T1 内实现，此处只接线**）：
      - 6 个 nginx conf 中每个含 `add_header` 的 location，必须 include 片段或内联声明
        **其外层已声明的**安全头（规则以「外层实际声明集」为准，而非固定 6 项 —— 数据面代理
        只需保持 `nosniff`，HTML 面才需全 6 项）；
      - 片段变量必须在**同一 nginx 实例**内被 `map`/`set` 定义（否则 `nginx: [emerg] unknown variable`）；
      - 片段必须是 `.inc`；每个片段必须声明全 6 个头名；CSP 指令集需与生成侧对齐（无 `media-src`）；
      - 全仓无 `X-XSS-Protection`；无反射 `$http_origin`；
      - 每个 nginx 镜像 Dockerfile 必须 COPY 它所 include 的片段。
- [ ] 2. `check_artifact_headers.py` 最终断言集：
      - `apps/web/dist/{external,internal}/_headers` 必须存在；
      - `apps/{admin,jbrowse}/dist/_headers` 必须存在；
      - 不得含 `example.com` / `localhost` / `__` 占位符残留；
      - `_headers` 的 CSP 与最终 HTML meta CSP：除 `script-src`/`connect-src`/`frame-src` 外
        的指令逐字一致；
      - 每个页面 meta 的 `script-src` hash 集合是 `_headers` hash 集合的子集；
      - `_headers` 的 `script-src` 不得含 `'unsafe-inline'`；
      - `apps/web/dist/**/fonts/harmonyos` 不得存在（T26）。
- [ ] 3. `check_contrast_tokens.py` 接入 `verify-frontend-artifacts.sh`（在 typecheck 之后、
      page-registry 检查之前）。
- [ ] 4. `check_nginx_security_headers.py` 接入 `smoke.sh --profile contracts`（无依赖检查）；
      `check_artifact_headers.py` 接入 `verify-frontend-artifacts.sh`（产物归属前端）。
- [ ] 5. `scripts/test_ci_job_contracts.py` 若要求列出新增脚本，按既有 `JOBS` 结构同步
      （**只改共享脚本**）。
- [ ] 6. **禁止**修改 `.cnb.yml` / `.github/workflows/*` 的逻辑；如需新 job，只改
      `scripts/ci-job-steps.sh` 的 `JOBS` 与函数体。

**Verify:**
```bash
python3 -m pytest scripts/test_ci_job_contracts.py -q
bash scripts/smoke.sh --profile contracts
bash scripts/verify-frontend-artifacts.sh
git diff --stat -- .cnb.yml .github/workflows   # 必须为空
```

**Accept:** 三个门禁在对应共享脚本中执行；`.cnb.yml` 与 `.github/workflows/*` diff 为空。

---

#### T32 · 回归断言归属核验（**逐条验证回滚变红**）

**Files:** `scripts/test_production_compose_contract.py`、`test_development_compose_contract.py`、
`test_platform_delivery_contracts.py`、`test_site_artifact_isolation.py`、`test_dockerfile_contracts.py`

- [ ] 1. 核验断言清单（每条都必须已由对应任务在同一 PR 内添加）：

      | 断言 | 归属任务 | 回滚时应变红 |
      |---|---|---|
      | 每个长驻服务有 `logging.options.max-size` | T6 | 是 |
      | nginx 服务有 `read_only`/`cap_drop`/`no-new-privileges`/`user`/`tmpfs` 且端口与 `listen` 一致 | T7 | 是 |
      | 5 个数据服务有 `mem_limit` | T10 | 是 |
      | `deploy/` 下无 `forwarded-allow-ips=*` 与 `0.0.0.0/0` | T4 | 是 |
      | 伪造 XFF 不影响 `request.client.host`（功能性） | T4 | 是 |
      | 每个 HTML nginx 镜像 Dockerfile COPY 了 `.inc` 片段 | T1 | 是 |
      | `web-nginx.conf`/`admin-nginx.conf`/`jbrowse/nginx.conf` 的 `location /` 含 XFO/CSP | T1 | 是 |
      | external/internal 的 `_headers` 各自存在且 origin 正确 | T2 | 是 |
      | jbrowse `_headers` 无 `example.com` 且含 API + 数据 origin | T3 | 是 |
      | external 产物不含 internal 的 SW 缓存命名空间（负向泄漏） | T12 | 是 |
      | `precompress.sh` 刷新陈旧 `.gz` 且重复运行 exit 0 | T14 | 是（已实测） |
      | web 产物不含 `fonts/harmonyos` | T26 | 是 |
      | 对比度门禁在回滚 T15/T16 后变红 | T17 | 是 |

- [ ] 2. 对**高风险条目**（T1/T4/T7/T12/T14）实际做一次「临时回滚 → 断言变红 → 恢复」的验证，
      并在 PR 中记录命令与输出（**不得**把回滚提交到仓库）。
- [ ] 3. 确认无「同一断言在多个脚本中重复实现」（重复即漂移源）。

**Verify:**
```bash
python3 -m pytest \
  scripts/test_production_compose_contract.py \
  scripts/test_development_compose_contract.py \
  scripts/test_platform_delivery_contracts.py \
  scripts/test_site_artifact_isolation.py \
  scripts/test_dockerfile_contracts.py -q
```

**Accept:** 全部通过；高风险条目已实际验证「回滚变红」并留有证据。

---

#### T33 · 全量验证与交付证据

- [ ] 1. 按 §2.3 的**标准验证顺序**跑完整门禁（Node 24.19.0），记录命令与 pass/fail 计数。
- [ ] 2. 双站点构建 + 隔离校验 + demo 严格扫描用 `--allow-demo`；
      真实 release 构建另跑严格模式。
- [ ] 3. API/worker 测试用 `scripts/verify-backend-tests.sh`（需 PostgreSQL）。
      **Docker/PostgreSQL 不可用时必须在 PR 显式标注为未验证项**，
      并按 AGENTS.md 由 CI 的 PostgreSQL 环境补验（**不得**以「本机不可用」作为合并完成的证据）。
- [ ] 4. 在 PR 描述中列出：改动文件、新增门禁、回滚方式、未验证项及原因。

---

## 5. 验证矩阵

**执行顺序（必须按 §2.3）：** 全应用门禁 → 干净双产物 → 分变体静态检查 → e2e → contracts → backend。

**V-ID 执行序列：** `V1 → V2 → V3 → V4 → V4b → V12 → V5 → V6 → V10 → V11 → V9 → V7 → V8 → V13 → V14 → V16 → V18 → V15 → V17 → V19`
（表格编号只是标识，**不是执行顺序**；`V12` 内部的 `pnpm build` 会重建根 `dist/`，所以必须在 `V5/V11` 之前跑完。）

| # | 命令 | 期望 | 覆盖 |
|---|---|---|---|
| V1 | `pnpm install --frozen-lockfile` | exit 0 | 依赖 |
| V2 | `pnpm lint` | 0 errors **0 warnings**（workspace） | T27 |
| V3 | `pnpm typecheck` | 全 package successful | 全量 |
| V4 | `pnpm test` | 全 workspace 通过（Node 24；V4b 见下） | 全量 |
| V4b | Node 26 下 `pnpm --filter @soymutdb/web test` | 与 Node 24 结果一致 | T13 |
| V5 | `VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test pnpm --filter @soymutdb/web build:sites` | exit 0，双产物，无 `.gz` | T2/T5/T12/T14/T26 |
| V6 | `bash scripts/build-pages-artifact.sh` + `bash scripts/verify-pages-artifact.sh pages-dist` | exit 0，jbrowse `_headers` 无占位符 | T3 |
| V7 | `python3 scripts/check_contrast_tokens.py --include-chart` | exit 0 | T15/T16/T17 |
| V8 | `python3 scripts/check_nginx_security_headers.py` | exit 0 | T1/T8/T9 |
| V9 | `bash scripts/check-production-artifact.sh apps/web/dist/external --allow-demo` | OK（demo 构建） | T2/T29 |
| V9b | `bash scripts/check-production-artifact.sh apps/web/dist` | 仅在**真实 release API 构建**后执行，期望 OK | T29 |
| V10 | `bash scripts/check-bundle-size.sh apps/web/dist/external/assets`（internal 同） | exit 0，无静默 SKIP | T24 |
| V11 | `bash scripts/smoke.sh --profile static --static-dir apps/web/dist/external`（internal 同） | PASS（实测：必须用 `--static-dir`，环境变量形式会被脚本第 51 行的 `STATIC_DIR=""` 覆盖 → 实际校验根 `dist/`，是**假通过**） | 产物 |
| V12 | `bash scripts/verify-frontend-artifacts.sh` | exit 0 | 全前端门禁 + T31 |
| V13 | `cd e2e && npx playwright test -c playwright-public.config.ts` | 全通过（含 T18/T19/T21/T22 断言） | T18–T22 |
| V14 | `cd e2e && npm run test:web-performance:external` / `:internal` | 两份基线报告产出且达标 | T25 |
| V15 | `cd e2e && PRODUCTION_BASE_URL=<real> npx playwright test -c playwright-production.config.ts` | 全通过（**需真实部署**，否则标注未验证） | 发布门禁 |
| V16 | `bash scripts/smoke.sh --profile contracts` | 216+ passed | T1/T4/T6/T7/T31/T32 |
| V17 | `bash scripts/verify-backend-tests.sh` | 全通过（**需 PostgreSQL**） | T30 |
| V18 | `python3 -m pytest scripts/test_ci_job_contracts.py -q` | 通过（workflow 无新逻辑） | T31 |
| V19 | CI fixture 环境下 `bash scripts/ci-job-steps.sh run compose-acceptance` | 通过（各 profile） | T6/T7/T10 |

**V19 的前置条件（v1 的 `docker compose config --quiet` 直接跑会因缺少必填变量失败）：**
`docker-compose.yml` 使用 `${*_IMAGE_REF:?…}` 与 `${POSTGRES_PASSWORD:?…}` 等 fail-fast 引用，
必须按 `.github/workflows/ci.yml` 的 compose-acceptance 步骤提供 fixture 环境变量
（`API_IMAGE_REF`/`WORKER_IMAGE_REF`/`MCP_IMAGE_REF`/`JBROWSE_IMAGE_REF` 的 `@sha256:` 占位、
`POSTGRES_PASSWORD`/`CLICKHOUSE_PASSWORD`/`REDIS_PASSWORD`/`MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`/
`SOYMUTDB_MCP_API_TOKEN`/`GRAFANA_PASSWORD`），**或**直接调用已封装的
`scripts/ci-job-steps.sh run compose-acceptance`（它遍历 6 个 profile 组合）。

**Node 版本要求：** V2–V5、V12–V14 必须使用 `.nvmrc` 的 **24.19.0**；
V4b 用 Node 26 验证 T13 的韧性。

**环境受限项的处理：** V15（真实部署）、V17（PostgreSQL）、镜像构建相关（Docker）
在本机不可用时必须标注为未验证，由 CI 补验；**不得**计入「已完成」。

---

## 6. 风险与回滚

| 风险 | 触发条件 | 缓解 / 回滚 |
|---|---|---|
| T1 片段被当成 server 块自动加载 | 命名为 `.conf` | 强制 `.inc`；`nginx -t` 前置校验；片段只含 `add_header` |
| T1 容器内缺片段 | Dockerfile 未 COPY | 同任务内 `test_dockerfile_contracts.py` 断言；镜像构建期 `nginx -t` 冒烟 |
| T2 最终化器阻断构建 | origin 缺失 / `_headers` 缺失 | fail-closed 是**预期行为**；CI 已导出 demo origin；本地用 `SOYMUTDB_CI_DEMO_*`；回滚 = 从构建链移除该步骤（CSP 退回保守默认，仍有效） |
| T2 部分构建发布保守 CSP | 只跑 `build:ui` | 保守策略是**有效但更严**的头（不是无效占位符）；门禁断言最终策略等于生成策略；文档标注 `build:ui` 不是发布路径 |
| T5 hash 化导致首屏白屏 | hash 计算与浏览器规范化不一致 | 只 hash 可执行脚本（排除 JSON/JSON-LD）；保留 `style-src 'unsafe-inline'`；E2E 监听 CSP violation；分两步灰度；回滚 = 恢复 `'unsafe-inline'` |
| T5 hash 列表膨胀 | 把 `application/json` 也算进去 | 门禁断言 hash 数 ≤ 8；解析器只取可执行类型 |
| T7 只读根导致 nginx 起不来 | 日志/pid/临时目录不可写 | 照抄 `cloudflare-tunnel.conf` 已验证写法（stdout/stderr + `/tmp`）；tmpfs 兜底；必须实际 `up -d` 验证 healthy |
| T7 非 root 绑 80 失败 | `cap_drop: ALL` | `listen 8080` + compose 端口同步；契约测试断言端口一致 |
| T12 缓存迁移击穿 | 老 SW 无法清理新命名 | activate 只清本变体旧版本 + 一次性清无变体旧名；`skipWaiting`/`clients.claim` 已存在；负向隔离测试 |
| T14 `.gz` 陈旧导致 nginx 送出过期内容 | 源变更而 `.gz` 未刷新 | `-nt` 守卫 + 回归测试（实测旧脚本 False / 新脚本 True）；Docker 构建冒烟 |
| T15/T16 色板调整影响品牌视觉 | token 变化 | 改动限定在 `chart-*`/`impact-*`/`destructive-*`；`visual-layout.spec.ts` 截图对比；单 commit 可回滚 |
| T24 门禁误杀 minimal 部署 | heavy chunk 缺失 | `SOYMUTDB_ALLOW_MISSING_HEAVY_CHUNKS=1` 显式开关 + 打印原因；required 列表只含稳定 chunk |
| T25 阈值在 CI 抖动 | 性能噪声 | 3 次导航取中位数；阈值 = 实测 + 余量并写入文档；失败信息含实测值 |
| T26 删除字体影响 web 视觉 | 误判引用 | 删除前 `rg` 证明无引用；`index.css` 注释；产物断言；admin/jbrowse 不受影响 |
| T28 规则改动削弱安全 | 放宽判定 | 规则回归测试含「真实密钥仍报 high」「createHTML 直通不降级」；baseline 条目必须带 reason |
| T6/T7/T10 Compose 变更影响既有生产栈 | 只读/限制导致启动失败 | 先在本地 `compose-local.sh up` 验证；CI 的 compose-acceptance 覆盖 6 个 profile |
| T31 新门禁在旧代码上先红 | 门禁先于修复 | 核心断言与修复同任务提交；T31 只接线；T32 验证回滚变红 |

**通用回滚：** 每个任务独立 commit（执行者不自行 commit，由负责人按任务粒度提交），
回滚单任务不影响其他任务；`infra/nginx`、`docker-compose.yml`、`apps/web/public/_headers`、
`apps/web/scripts/finalize-csp.ts`、`infra/docker/precompress.sh` 为高风险文件，需在 PR 中单独列出 diff。

---

## 7. 完成定义（DoD）

- [ ] §1.1/1.2/1.3/1.4/1.6 全部问题有对应任务且状态为「已修复」或「已记录为接受风险（含理由与 owner）」
- [ ] §1.5 误报**未被**修改业务代码（仅改进工具规则，且未放宽判定）
- [ ] §5 验证矩阵 V1–V19 全绿（环境受限项需显式标注并给出 CI 补验路径）
- [ ] 新增门禁全部位于共享脚本；`.cnb.yml` 与 `.github/workflows/*` 无逻辑增量
- [ ] 每个修复任务的回归断言与修复在**同一任务**内提交（T32 逐条核验回滚变红）
- [ ] 门户生产路径（`_headers` + 最终 meta）无 `script-src 'unsafe-inline'`；
      nginx dev 路径的保留有显式注释与文档说明；两条路径的差异与 §4.0 表格一致
- [ ] 全仓无 `forwarded-allow-ips=*` 与 `0.0.0.0/0`；伪造 XFF 的功能性负向测试通过
- [ ] 无使用无上限日志驱动的长驻服务；nginx 以非 root + 只读根运行且健康
- [ ] `precompress.sh` 在源变更后刷新 `.gz`（回归测试实测旧脚本变红、新脚本变绿）
- [ ] 所有对比度断言 ≥ WCAG AA（文本 4.5:1 / 图形 3:1），含 alpha 叠加场景
- [ ] SW 的静态与运行时缓存均按站点变体隔离，`caches.match` 均带 `cacheName`
- [ ] web 产物无 HarmonyOS 死负载；无「为不存在字体加 preload」
- [ ] `docs/ops/production-security-checklist.md` 的 G-1/G-4/G-7 标注处置状态与证据
- [ ] PR 描述含：命令、pass/fail 计数、迁移/环境变量/部署影响、回滚方式、未验证项与 CI 补验路径

---

## 附：Skills 使用说明（供后续维护者）

| Skill | 在本计划中的作用 |
|---|---|
| `systematic-debugging` | 每个问题均走「读错误→复现→查变更→多组件取证→追数据流」，根因写在任务开头；T17 遵循「先写失败门禁再修」的 Phase 4 顺序；T14 的 D-5 由实测 `gzip` 退出码 + `-exec \;` vs `+` 的退出码传播差异定位 |
| `ui-ux-pro-max-zh-1.0.0` | 提供 8 类优先级规则（无障碍→触摸→性能→布局→字体颜色→动画→风格→图表）；T15–T22 逐条对应 `ux-guidelines.csv` 的 High/Medium 项 |
| `design-master-2.1.2` | `references/scripts/search.py` 生成设计系统基线；`ui-ux-data/ux-guidelines.csv` 提供 60+ 可执行准则；`design-tokens-spec.md` 指导 token 分层；`theme-switching.md` 提供亮/暗/高对比三态参考（高对比态可作后续扩展） |
| `web-perf` | T23–T26 采用其 Phase 1–5 流程（trace→CWV→网络→a11y→代码库）；因无 Chrome DevTools MCP，改用 Playwright Resource Timing + PerformanceObserver 采集，取 3 次中位数 |
| `receiving-code-review` | §1.5 对工具输出逐条核验（技术正确性优先于「看起来合理」）；T28 把核验结论固化为规则改进，**但拒绝任何以放宽判定换绿的做法** |

> 复现设计基线：
> `python3 /home/rlcao/文档/cherry/Data/Skills/design-master-2.1.2/references/scripts/search.py "bioinformatics scientific database research platform data portal" --design-system -p "SoyMutDB" -f markdown`
