# OPT-10 / OPT-11 — 实体详情页 E2E + 内部站 E2E（子代理 E）

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../../ARCHIVE.md)。

- 仓库：`/mnt/data02/T25ronglin/code/web`
- 日期：2026-09-26
- 来源：`docs/dev/ablation/2026-09-26/OPTIMIZATION-CHECKLIST.md`（OPT-10 = G4/G5；OPT-11 = G6）
- 证据分级：**E1 = 真实运行**（Playwright 离线制品 + mock API，exit code 与计数见 §3）
- 并发前提：本目录存在另一并发会话，其已产出 `e2e/playwright-admin-console.config.ts`、`e2e/playwright-portal-embed.config.ts`、`e2e/tests/admin-console.spec.ts`、`e2e/tests/portal-browser-embed.spec.ts`、`e2e/tests/helpers.ts` 的 `trackErrors`、`e2e/static-server.mjs` 的 `GENES_JBROWSE_FIXTURE`、以及 `e2e/tests/entity-detail.spec.ts`/`e2e/playwright-entity-detail.config.ts`、`e2e/tests/internal-site.spec.ts`/`e2e/playwright-internal.config.ts` 的骨架。
  本工作**保留**上述文件与语义，并在其上补齐离线可运行性；未 `git checkout/reset/stash`，未提交。

---

## 1. 目标

1. **OPT-10a（G4）**：新增/扩展实体详情页 spec：搜索命中 → 打开详情，断言 `id` / `assembly` / `release` 上下文一致，沿用既有离线同源 mock 风格。
2. **OPT-10b（G5）**：删除 `genes.spec.ts` 中“JBrowse 2 深链”用例的**无条件 `test.skip`**，让它在离线真实通过（断言深链 URL 契约 + 深链进入 `/browser` 后 locus 进入 shell iframe `src`）。
3. **OPT-11（G6）**：新增 `e2e/playwright-internal.config.ts` + internal spec，覆盖**登录 → internal_id 检索 → 详情**，指向 base 为 `/` 的 internal 制品；复用既有 serving 配方（`e2e/static-server.mjs`）。

---

## 2. 改动（file:line）

| 文件:行 | 改动 |
| --- | --- |
| `e2e/tests/helpers.ts:70-369` | 新增确定性离线段：`MOCK_ASSEMBLY/MOCK_GENE_ID/MOCK_MUTANT_PUBLIC_ID/MOCK_MUTANT_INTERNAL_ID/MOCK_VARIANT_ID`、`CapturedApiRequest`、`mockEntityApis(page)`。按 **pathname/hostname** 分发（兼容 public 子路径与 internal 绝对 origin），对跨域请求补 CORS/OPTIONS 预检；记录每个请求的 assembly 作用域参数与 `X-SoyMutDB-Release` 头，供一致性断言。保留并发会话的 `trackErrors`。 |
| `e2e/tests/genes.spec.ts:46-79` | 移除无条件 `test.skip`；深链用例改为 `mockEntityApis` 注入一行基因结果，断言 `href=/browser?assembly=Wm82.a4.v1&loc=chr01:100-200`，随后进入 `/browser` 断言 `browser-locus-input` 与 iframe `src` 携带同一 assembly+locus。另将“无行”断言由错误的 `search-gene-row` 收窄为真实 `configurable-row`。 |
| `e2e/tests/entity-detail.spec.ts:36-55,112,152,204` | OPT-10a：详情 spec 支持离线默认目标（`http://localhost:4176/soymutdb-next/`）；离线时三处注入 `mockEntityApis`。覆盖 mutant(public_id)/variant(compare)/gene(assembly+坐标+JBrowse 链接) 三个详情页的上下文一致性与“URL 不含 private internal 标识”。 |
| `e2e/playwright-entity-detail.config.ts:26-71` | 新增离线默认 base（4176，`/soymutdb-next`）+ `webServer`（复用 `static-server.mjs` 配方）；显式 `PORTAL_BASE_URL` 时行为不变（不启本地 server）。 |
| `e2e/playwright-internal.config.ts` (新增内容) `:20-60` | **OPT-11 新 config**：默认 base `http://localhost:4175/`（internal 制品挂根路径），`webServer` 运行 `node static-server.mjs ../apps/web/dist/internal 4175 /`；显式 `INTERNAL_BASE_URL` 时指向真实部署。 |
| `e2e/tests/internal-site.spec.ts:175-234` | **OPT-11 新用例**：`/login?redirect=/search` 真实提交（POST `/auth/login`，跨域 mock 带 CORS）→ 断言落到根相对 `/search` → 以 internal_id 深链检索 → 断言请求 `query=INT-MUT-000001` 且结果 `data-url=/mutants/SMDB-00001`、结果文本含 internal_id → 进入 detail 断言按 public_id 渲染。保留既有 2 个 base-path/策略用例。 |
| `e2e/static-server.mjs:366-380` | SPA fallback 修正：仅 `/assets/*` 与 `/api/*` 返回真实 404；不再把 `/genes/<id>`、`/mutants/<id>` 等**详情路由**误判为 API 路径而 404（否则离线详情页永远拿不到 `index.html`）。原 `API_PATH_RE` 保留并注释说明。 |

---

## 3. 验证（E1：命令 + 退出码 + 真实计数）

环境：Node v24.19.0；`e2e/node_modules/.bin/playwright` 已存在；浏览器缓存 `~/.cache/ms-playwright`；无需 Docker/后端/网络。

### BEFORE（来自 `artifact-e2e.md`）

| 场景 | 计数 | 退出码 |
| --- | --- | --- |
| `playwright-public.config.ts` 公开全套 | **29 passed / 2 skipped** | 0（见 artifact-e2e §3.2 E2E-01a） |
| 把 public 套件指向 internal 制品 | **8 failed / 1 passed**，`No route for /soymutdb-next/login`（E2E-02，§4.4） | 1 |
| 详情页覆盖 | 13 个 spec 无任何 detail 路由（GAP） | — |

### AFTER（本次真实运行）

```bash
cd e2e && ./node_modules/.bin/playwright test -c playwright-public.config.ts
#   1 skipped
#   30 passed (23.3s)
# PUBLIC_EXIT=0

cd e2e && ./node_modules/.bin/playwright test -c playwright-internal.config.ts
#   3 passed (5.5s)
# INTERNAL_EXIT=0

cd e2e && ./node_modules/.bin/playwright test -c playwright-entity-detail.config.ts
#   3 passed (6.9s)
# ENTITY_EXIT=0
```

| 场景 | BEFORE | AFTER | 变化 |
| --- | --- | --- | --- |
| public 全套 | 29 passed / 2 skipped / exit 0 | **30 passed / 1 skipped / exit 0** | +1 真实通过；skip 由 2→1（JBrowse 深链解除） |
| internal（专属 config） | 无 config；public 套件硬跑 8 failed/1 passed | **3 passed / 0 skipped / exit 0** | G6 关闭 |
| 详情页 | 0 spec 命中 detail 路由 | **entity-detail 3 passed（离线 mock）** | G4 关闭 |

public 计数未回归（≥30 passed，无新 skip）；internal 无 skip（不自欺）。

---

## 4. 未验证 / 已知边界

1. **internal 站“双 id 展示/复制”UI（OPT-05，子代理 C 未落地）**：`packages/api-client/src/search.ts` 目前无 `internalSearch`，`apps/web/src/views/SearchView.vue` 未 `isInternal` 分支；`apps/web/dist/internal` 内也搜不到 `search/internal`。因此本 spec 的 internal 检索走**当前通用 `/search` 契约**（请求按 `query=` 传 internal_id），`mockEntityApis` 同时 mock 了 `/search/internal` 与 `mutants/genes` 双 id 形状，待 C 落地重建 internal 制品后即可追加“双 id 可见/`copy-internal-id`”断言。**未验证：dual-id UI 的 E2E。**
2. **omnibox 表单提交在制品上不生效**：`SearchView.vue` 对 antdv `Input` 用 `v-model`（antdv 需要 `v-model:value`），`fill` 后组件 ref 仍为空，点击 submit 不会推送 `q`。故 internal 用例用 **URL 深链** `?q=<internal_id>`（这也是文档化的“URL 搜索状态”契约）触发检索；表单路径本身未通过。**未验证：omnibox 表单提交。**（根因在 `apps/web`，非 e2e 文件，未改。）
3. **JBrowse shell 本体**：离线 `VITE_JBROWSE_BASE_URL` 未配置（回退 `/jbrowse`，`static-server` 不服务该子应用），故深链只断言 **shell iframe 的 `src` 契约**（`assembly`+`locus`），不断言 iframe 内 shell 的 `browser-ready`。真实 shell 的接收需部署栈（`playwright-jbrowse.config.ts` 覆盖，另见 artifact-e2e E2E-01b 5 passed）。
4. **entity-detail 的“真实 release 数据”路径**：离线为静态 mock，不能证明真实 provenance；设置 `PORTAL_BASE_URL` 指向部署后走真实数据（此时不启本地 server、不装 mock）。
5. **internal 制品依赖**：`apps/web/dist/internal` 需存在（`CI= SOYMUTDB_INTERNAL_SITE_URL=... pnpm --filter @soymutdb/web build:sites` 或既有产物）。本环境该目录已存在（base `/`）。
6. 偶发：连续运行配置间若 4176 端口尚在退出，首次可能因 webServer 启动竞态失败一次；重跑通过（已 2/2 复跑稳定）。

---

## 5. 回滚点

| 回滚 | 操作 |
| --- | --- |
| 仅回滚 G5 深链 | 还原 `e2e/tests/genes.spec.ts` 的 `test.skip` 分支（其余用例不依赖 `mockEntityApis`） |
| 回滚 OPT-10a 离线化 | 删 `entity-detail.config.ts` 的 `webServer`/`OFFLINE_BASE` 与 spec 的三行 `if (OFFLINE) await mockEntityApis(page);`，恢复“无 base 即 skip” |
| 回滚 OPT-11 | 删 `e2e/playwright-internal.config.ts` 与 `tests/internal-site.spec.ts` 新增用例（及未跟踪文件）；恢复 `package.json` 两条 `test:internal*` 脚本 |
| 回滚 SPA fallback | 把 `static-server.mjs:376` 条件改回 `pathname.startsWith("/assets/") || API_PATH_RE.test(pathname)` |
| 完全回滚共享 helper | 移除 `helpers.ts`：70-369（保留 1-68 的 `waitForAppReady/gotoReady/trackErrors`） |

所有改动均在 e2e 文件内，无生产源码改动、无提交。
