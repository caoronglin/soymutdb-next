# Vue 迁移恢复 — Gate 0 核验与首轮执行记录（2026-09-26）


> 当前总体状态（部署/门禁/缺口单一视图）：`docs/dev/project-status.md`。
> 配套方案：`docs/dev/vue-migration-recovery-plan.md`（本轮未改动该文件）。
> 本记录只陈述已实测的事实；未验证项统一保留在文末缺口清单，并标注 `未开始` / `待复核`。
> 本记录不宣称迁移完成，也不宣称端口已切换。

## 1. Gate 0：保留改动核验

### 1.1 审计时点的工作树分类

审计命令：`git status --porcelain=v1`、`git log --oneline -5`、`git diff --stat`。

| 区域 | 文件 | 核验前状态 | 本轮处理 | 核验后状态 |
| --- | --- | --- | --- | --- |
| 管理端 | `router/index.ts` 引用 `SpeciesInstancesView.vue`、`SiteBrandSettingsView.vue` | 半成品：两个文件不存在，`vue-tsc` 报 TS2307 ×2 | 补齐两个页面、i18n 字典、11 个视图测试、设置页入口 | 已通过构建/测试，待浏览器验证 |
| 管理端 | `AdminLayout.vue`、`style.css`、`SettingsView.vue` | 半成品：i18n 导航/响应式侧栏/`@theme` 已改但未集成 | 未改动主体；在构建产物中验证 `@theme` 类与 CSP 重写 | 已通过构建验证 |
| 公共站 | `App.vue`、`PortalHeader.vue` | 半成品：品牌接口已存在但无人消费 | 新增 `lib/branding.ts`，接线页眉、文档标题、favicon | 已通过测试/双站构建 |
| 公共站 | `LoginView.vue` | 半成品且**阻断生产构建**：`<script setup>` 内 `export` | 拆出 `lib/redirect.ts`（`safeRedirect`）并补 4 个测试 | 已通过构建/测试 |
| 公共站 | `HomeView.vue`、`query-options.ts`、`style.css`、`HomeView.test.ts` | 半成品：实体入口/状态分支已改且有测试 | 未改动；测试通过 | 待按新闻状态矩阵复核 |
| 后端 | `site_brand_service.py`、`species_instance_health_service.py`、迁移 `0040`、`settings_registry.py`、`site.py`、`admin_settings.py`、`admin_table_views.py`、schemas | 半成品：代码齐但无测试、未跑迁移 | 新增 18 个测试；真实 PostgreSQL 升降级验证 | 已通过后端全量门禁 |
| 客户端 | `packages/api-client/src/site.ts`、`table-views.ts` (+ 两个未跟踪测试) | 待验 | 未改动；纳入工作区测试 | 已通过 |
| 未跟踪资产 | `apps/web/public/fonts/`、方案文档 | 用户要求保留 | 未触碰 | 保留 |

### 1.2 审计发现的可复现缺陷（修复前）

```bash
pnpm --filter @soymutdb/admin typecheck
# src/router/index.ts(37,68): error TS2307: Cannot find module '../views/SpeciesInstancesView.vue'
# src/router/index.ts(39,78): error TS2307: Cannot find module '../views/SiteBrandSettingsView.vue'

pnpm --filter @soymutdb/web build   # (external env)
# [vite:vue] [@vue/compiler-sfc] <script setup> cannot contain ES module exports.
#   -> apps/web/src/views/LoginView.vue
```

两个 Vue 产物在切换时丢失的 `@theme` 语义色映射已由保留的改动恢复，本轮在**构建产物**中确认（见 3.2）。

## 2. 本轮落地的修复

### 2.1 P0：管理端缺失页面与路由契约

- 新增 `apps/admin/src/views/SpeciesInstancesView.vue`
  - 实例登记 CRUD + 连接探活；本地实例禁止删除；远端实例显示 `registration_only` 提示；只有合法 HTTP(S) URL 才渲染门户链接；保存/删除/探活各有成功与失败状态。
  - 不代理远端写操作；页面没有静态假数据。
- 新增 `apps/admin/src/views/SiteBrandSettingsView.vue`
  - 外网/内网两个变体独立编辑；乐观版本提交；409 显示冲突并回读最新值；图标走已验证媒体 URL（清空发送显式 `null`）。
- `SettingsView.vue` 增加品牌设置入口；`router/index.ts` 的两个动态 import 现在都有实现。
- i18n：`packages/i18n-core/src/locales/{en,zh}/common.json` 增补 `admin.instances.*`、`admin.brand.*` 运行所需 key；中英 key 集合完全对等（各 1227）。
- 测试：`SpeciesInstancesView.test.ts`（6）、`SiteBrandSettingsView.test.ts`（5）。

### 2.2 P0：公共站生产构建阻断

- `LoginView.vue` 的 `safeRedirect` 移入 `apps/web/src/lib/redirect.ts`；新增 `redirect.test.ts`（4）：同站路径、绝对/协议相对 URL、反斜杠/控制字符、缺失值。
- `apps/web/src/lib/redirect.ts` 用字符码检查替代 `\u0000-\u001f` 正则，避免 `no-control-regex` lint 失败。

### 2.3 C（品牌链）：公共站运行时品牌

- 新增 `apps/web/src/lib/branding.ts`：`resolveBrandName`（按语言取值、缺失语言回退、默认 `SoyMutDB`）+ `useSiteBranding`（按显式 site variant 查询）。
- `App.vue`：品牌到达后更新文档标题与 favicon；读取失败保持构建期默认，不清空站点身份。
- `PortalHeader.vue`：页眉名称与图标来自品牌快照，图标缺失时回退内置 SVG。
- 测试：`PortalHeader.test.ts`（4）。

### 2.4 后端保留改动的回归测试

- 新增 `apps/api/tests/test_site_brand_and_instance_health.py`（18）：
  - 迁移 `0040` 离线 SQL：升级列/约束、降级先删约束再删列、不含生物/凭据字段。
  - 实例 URL 契约：远端必须 HTTPS、拒绝凭据/查询/路径、`site_url` 别名一致性。
  - 探活白名单解析与 staleness 语义。
  - 品牌：变体隔离、版本冲突、图标必须为 READY 光栅上传、名称拒绝标记与空白。
  - 探活：本地实例不发起网络请求、禁用实例不探测、无白名单 `unconfigured`、白名单后被探活并持久化状态。
  - 公开边界：外部品牌返回 `public` 缓存；匿名读内网品牌 401 且不泄露值；带 viewer 身份返回 `private, no-store` + `Vary: Authorization`。

## 3. 验证证据（命令与结果）

### 3.1 前端

```bash
PATH=/usr/local/bin:$PATH GOMAXPROCS=2 RAYON_NUM_THREADS=1 pnpm turbo run typecheck --concurrency=1
# Tasks: 12 successful, 12 total
PATH=/usr/local/bin:$PATH GOMAXPROCS=2 RAYON_NUM_THREADS=1 pnpm turbo run lint --concurrency=1
# Tasks: 12 successful, 12 total (api-client 4 warnings, 0 errors)
PATH=/usr/local/bin:$PATH GOMAXPROCS=2 RAYON_NUM_THREADS=1 pnpm turbo run test --concurrency=1
# 11 tasks; api-client 120, web 84, admin 19, shared 49, … 全部通过
# 品牌接线后复跑 web：23 files / 88 tests passed
PATH=/usr/local/bin:$PATH GOMAXPROCS=2 pnpm turbo run lint typecheck --concurrency=1
# Tasks: 24 successful, 24 total
```

管理端与公共站生产构建：

```bash
VITE_API_BASE_URL=http://localhost:8010/api/v1 pnpm --filter @soymutdb/admin build   # exit 0
CI= VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
  VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test \
  SOYMUTDB_INTERNAL_SITE_URL=https://internal.soymutdb.invalid \
  GOMAXPROCS=2 pnpm --filter @soymutdb/web build:sites                                 # exit 0
python3 scripts/check_site_artifact_isolation.py \
  --external-root apps/web/dist/external --internal-root apps/web/dist/internal \
  --sentinel 'noindex, nofollow, noarchive'                                            # OK
bash scripts/smoke.sh --profile static --static-dir apps/web/dist/external             # PASS
bash scripts/smoke.sh --profile static --static-dir apps/web/dist/internal             # PASS
bash scripts/smoke.sh --profile static --static-dir apps/admin/dist                    # PASS
```

### 3.2 CSS 语义色（P0）

```bash
grep -o '\.bg-background\|\.text-foreground\|\.bg-primary\|\.text-muted-foreground\|\.border-border\|\.bg-card' \
  apps/web/dist/assets/index-*.css apps/admin/dist/assets/index-*.css
# 两个应用的构建 CSS 均包含全部目标类
```

### 3.3 后端与迁移

```bash
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_testfixtures' \
  bash scripts/verify-backend-tests.sh
# architecture guard passed
# API pytest: 1604 passed
# worker pytest: 357 passed, 1 skipped
# backend verification passed

# 迁移 0040 真实 PostgreSQL 升降级（soymutdb_validation @ 55432）
alembic upgrade head      # 0037 -> 0038 -> 0039 -> 0040；版本=0040，4/4 列存在
alembic downgrade 0039    # 版本=0039，4/4 列删除
alembic upgrade head      # 版本=0040
```

### 3.4 其它契约

```bash
bash scripts/smoke.sh --profile contracts   # 232 passed + 10 environment-bound；SMOKE PASS
python3 scripts/check_page_registry.py     # 19 component keys synchronized
python3 scripts/check_web_query_keys.py    # 9 assembly consumers
python3 scripts/check_admin_content_architecture.py  # 27 source files
python3 -m unittest scripts.test_site_artifact_isolation -v  # 6 tests OK
```

## 4. 与方案的差距（未完成 / 待复核）

| 方案条目 | 状态 | 说明 |
| --- | --- | --- |
| P0 管理端/公共站 React→Vue 功能矩阵（admin 约 34→11 路由） | 未开始 | 本轮只补齐方案点名的两个已引用路由；其余旧路由/入口映射尚未建立 |
| P0 部署态 CSS/CSP/缓存/子路径浏览器验证 | 待复核 | 本机产物与静态 smoke 已过；真实部署入口、Service Worker、CSP 响应头需浏览器实测 |
| P0 assembly 选择与深链（v4/v5 稳定 ID） | 待复核 | 本轮未审计；需按 `database-core-contract.md` 矩阵补证 |
| P0 中英文逐页文案扫描 | 部分 | key 对等（各 1227）已验证；逐页渲染与 Antdv 文案扫描未做 |
| P1 首页新闻 loading/error/empty/success 状态机 | 待复核 | `HomeView` 改动与测试在，但未按 200 空/500/超时/部分源失败矩阵验证 |
| P1 登录独立布局、子路径回跳、无 URL 结果不可点 | 部分 | 独立布局与 `safeRedirect` 已有测试；无 URL 结果与键盘路径未专项验证 |
| P1 管理端 favicon、dashboard/导入/新闻能力 | 待复核 | 未开始恢复；favicon 404 未复现验证 |
| P1 静态预览/部署 API base 与 CORS | 待复核 | 未执行 |
| D 多实例远端写操作 | 按设计关闭 | 已实现并有测试的只有登记、探活（allowlist）与门户跳转；远端写保持关闭 |
| E 默认 API 端口 8010 | 未开始 | 现状仍为 8000（compose/Dockerfile/nginx/k8s/conda/windows/监控/脚本/文档/MCP 默认值）；需按方案逐链路核对，禁止盲替换 |
| F `docs/wiki/` 与目录清理 | 未开始 | 未创建 wiki；未做清理（保留字体与历史证据） |
| C 构建期品牌写入静态 HTML/manifest | 未开始 | 本轮只做运行时；静态标题仍为构建期 `SoyMutDB` |

尚未在实际部署中复现的项目继续标注“待复核”，不以推测下结论。

## 5. 本机环境注意事项

- Node：仓库 pin `24.19.0`；本机 shell 默认 miniforge Node v26 违反 `engines`，构建/typecheck 使用 `PATH=/usr/local/bin:$PATH`（v24.12.0）。
- 沙箱线程上限会让 esbuild 的 Go runtime `EAGAIN`：构建须 `GOMAXPROCS=2 RAYON_NUM_THREADS=1`；turbo 任务图须 `--concurrency=1`。
- 无 Docker：testcontainers 路径不可用；用 Mamba PostgreSQL 55432（`docs/dev/mamba-validation-environment.md`）与 `SOYMUTDB_TEST_DATABASE_URL`。
- 契约 smoke 需要 pytest 的 Python：`SOYMUTDB_SMOKE_PYTHON=$PWD/apps/api/.venv/bin/python bash scripts/smoke.sh --profile contracts`。

## 6. 第二轮执行记录（assembly / i18n / 端口 / 旧深链 / Wiki）

第 6 节记录的行目取代第 4 节对应行。

### 6.1 assembly 身份（P0）

- 新增 `apps/web/src/lib/assembly-selection.ts`：URL 参数优先按稳定 `id` 解析；唯一名称可解析；
  v4/v5 同名报「歧义」；未知参数报错，不再静默回退默认组装。
- `apps/web/src/lib/query-options.ts`：区域/列表请求在边界把 id 解析为 label，缓存键保留 `id`；
  `variantsQueryOptions` 新增 `variantType`/`mutantLineId`/`cursor`，`queryKeys.variants.list` 同步扩展。
- 视图：`VariantsView` 重写（assembly 下拉按 id、显示 name+version、过滤/游标分页/URL 深链/i18n）；
  `SearchLocationView`、`SearchGenesView` 增加未知/歧义错误与名称→id URL 规范化。
- 测试：`assembly-selection.test.ts` 6；`VariantsView.test.ts` 8；`SearchLocationView.test.ts` 4；
  `SearchGenesView.test.ts` 3；`query-keys` 10。
- 后端缺口（计划中）：`/variants`、`/variants/region` 仍按 assembly label 过滤；需要
  `assembly_id` 入参与 ClickHouse `assembly_key` 规范化（涉及投影标签，待有真实数据后定标）。

### 6.2 i18n（P0）

- 修复 i18next 占位符缺陷：字典混用 `{var}` 与 `{{var}}`，i18next 只解析 `{{var}}`，
  导致所有单花括号文案原样显示（如 `{count} results`）。en/zh 各 19 处统一为 `{{var}}`；
  `i18n-core` 测试拒绝单花括号写法，`apps/web/src/lib/i18n.test.ts` 断言两种语言的插值结果。
- `SearchView`、`DownloadsView` 完成 i18n；新增 `admin.legacyUnavailable.*`、`search.sourceStatus*`、
  `downloads.*` 等 key，两语言 key 集合保持对等。
- 新增可见文案预算门禁 `scripts/check_visible_i18n.py` + `scripts/visible-i18n-baseline.json`
  （31 文件 / 225 串，计数只降不升，self-test 已接入 contracts smoke 与 frontend artifacts）。
- 剩余 backlog 最大文件：GeneView 35、EnrichmentView 34、SeqFetchView 27、ExpPatternView 26、
  MutantDetailView 17、ToolsView 11、NewsListView 9。

### 6.3 管理端 favicon（P1）

- 新增 `apps/admin/public/favicon.svg` 与 `apps/admin/index.html` 的 `<link rel="icon">`；
  新增门禁 `scripts/check_app_shell_assets.py`（源树 + 已存在产物 + self-test），已接入
  `verify-frontend-artifacts.sh` 与 contracts smoke。

### 6.4 默认 API 端口 8010（硬约束）

- 更新 39 个文件：公共站/管理端/JBrowse Vite 开发默认、compose（dev/prod）、Dockerfile、
  nginx 与 Cloudflare Tunnel upstream、kind-smoke、Prometheus、systemd、Windows PowerShell、
  Conda 文档与脚本、本地预览脚本、Makefile/README、k6 load tests、MCP Server 默认与测试、
  运维/架构文档，以及两份契约测试（k8s、cloudflare tunnel）。
- 逐条判断后保留的历史夹具：`.github/workflows/baseline-validation.yml`（显式自包端口）、
  `deploy/conda/verify-baseline.sh`（18000 smoke 端口）、`.slim/**`、
  `docs/design/upgrade-2026-08.md`、`apps/api/tests/a0/**`。
- 验证：`smoke.sh --profile contracts` 232 + 10 通过；compose api `expose: 8010`、healthcheck 8010；
  MCP `API_BASE` 实测为 `http://localhost:8010`。

### 6.5 管理端旧深链（P0 功能矩阵的第一步）

- 重定向到已恢复入口：`/settings/site → /settings/brand`、
  `/settings/security → /settings?section=security`、`/news/new → /news?new=1`、
  `/news/trash → /news?status=archived`、`/news/:id → /news?edit=<id>`；
  `SettingsView` 支持 `?section=`，`NewsAdminView` 支持 `?status=`/`?edit=`/`?new=`。
- 尚未恢复的 19 条旧路径落到 `LegacyUnavailableView`（写明路径、标记计划中、不读写数据）。
- 测试：`apps/admin/src/router/legacy-routes.test.ts` 3；`NewsAdminView.test.ts` 3。
- 仍未恢复（计划中）：Page Builder、内容页/资源目录、Widgets/Layout、导入向导与任务详情、
  设置分区页面（appearance/integrations/localization/advanced）。

### 6.6 Wiki 与文档（F）

- 新增 `docs/wiki/`：`README.md`（索引）、`architecture.md`、`applications.md`、
  `api-and-ports.md`、`deployment-and-ops.md`、`multi-instance.md`；README「文档入口」已链接。
- 端口与路由表从 compose、Vite 配置与 `router.py` 核对；未实现项均标注「计划中」。

## 7. 第三轮：真实浏览器门禁与首页崩溃修复（P0/P1）

### 7.1 公共站浏览器 E2E（本地离线，子路径）

```bash
CI= GOMAXPROCS=2 VITE_DEPLOYMENT_MODE=demo \
  VITE_BASE_URL=/soymutdb-next/ \
  VITE_API_BASE_URL=http://localhost:4173/soymutdb-next/api/v1 \
  VITE_JBROWSE_BASE_URL=http://localhost:4173/soymutdb-next/jbrowse/ \
  pnpm --filter @soymutdb/web build
cd e2e && npx playwright test -c playwright-public.config.ts
# 29 passed, 2 skipped（依赖后端）
```

覆盖：首页（导航分组、标识符搜索、任务入口、新闻空态、无 hero 挤占）、搜索
（Gene ID / Physical Location 表单与请求）、基因列表、可访问性（3 视口无横向溢出、
键盘焦点、导航与表单可访问名称、`html lang`）、登录（窄屏可见性与安全回跳）、BLAST、Primer。
这同时验证了子路径 base、CSP meta、动态 import 与真实 Chromium 布局。

`e2e/playwright-admin-production.config.ts`：管理端产物登录门禁 3/3 通过。

### 7.2 修复：首页新闻信封错误导致整页崩溃（P1→P0）

- 现象：离线 mock 对 `/news/featured` 返回 `{items:[],total:0}`（缺少 `featured`），
  `HomeView` 的 `news` 计算属性执行 `featured.slice` 抛 TypeError，Vue 渲染中断，整页空白；
  首次 E2E 因此 9 项失败。
- 修复：
  - `featuredNewsQueryOptions` 校验响应 envelope，缺少 `featured` 数组时抛错，
    页面渲染显式错误态而不是伪装成空结果；
  - `HomeView` 计算属性对 `featured` 再做可选链兜底，任何调用方都不会因缺字段崩溃；
  - `e2e/static-server.mjs` 返回正确的 `{featured:[],carousel:[]}` 空信封；
  - E2E 断言首页新闻空态可见（`home-news-empty`）。
- 同步（E2E 契约对齐当前 Vue UI）：主导航 `aria-label="Primary navigation"`、分组菜单
  `role="menuitem"`；`playwright-public.config.ts` 固定 `locale: en-US`（组件本身支持中英，
  断言是英文文案，浏览器区域不可影响门禁确定性）。

### 7.3 现状

- 公共站浏览器门禁：29 passed / 2 skipped；管理端产物登录门禁 3/3。
- favicon 资产门禁在源树与产物上通过；可见文案预算 31 文件 / 225 串，未上升。
- 仍未执行：已部署 demo 站的在线 smoke（需要网络）、视觉回归基线比对（React 截图仅作参考）。


## 8. 第四轮：i18n backlog 清理（P0）

- 扫描器升级：`scripts/check_visible_i18n.py` 改为 token 级判定（科学名/缩写/含数字标识
  可用白名单，句子与标签必须来自字典），并支持 `--self-test` / `--update-baseline`。
- 完成翻译的页面：`SeqFetchView`、`ExpPatternView`、`EnrichmentView`、`GeneView`、
  `MutantDetailView`、`MutantsListView`、`ToolsView`、`NewsListView`、`NewsDetailView`、
  `GeneModelPreview`、`ConfigurableTable`、`PortalFooter`、`PortalHeader`、`BlastView`、
  `BrowserView`、`GenesListView`、`GuideView`、`NotFoundView`、`PrimerView`、
  `PublicationsView`、`SearchGenesView`、`SearchLocationView`、`VariantsView`；
  管理端 `AdminLayout`、`AuditView`、`FeaturesView`、`ImportsView`、`MediaView`、
  `NewsAdminView`、`PublicationsAdminView`、`SettingsView` 的 aria/列头/状态/表单标签。
- 新增字典 key：`tools.seqfetch.*`、`tools.exppattern.*`、`tools.enrichment.*`、
  `genes.*`、`mutantLines.*`、`news.*`、`common.*`（pagination/noRouteFor/backToHome 等）、
  `admin.*`；`tools.seqfetch.countLabel` 增加 `_one`/`_other` 复数形式；两语言 key 保持对等。
- 可见文案预算：**225 串 / 31 文件 → 6 串 / 1 文件**（剩余为 `TableTemplatesView` 的
  物种与 scope 数据值，属明确白名单项）。
- 验证：web 27 文件 / 106 测试、admin 6 文件 / 25 测试、lint+typecheck 24 任务全部通过；
  测试中固定 `setLanguage("en")`，避免浏览器/文件顺序影响语言断言。


## 9. 第五轮：本地优先的实例上下文与远端连接器（D 节阶段 1）

原则：**远端连接器先实现但不启动**，先把本地站点的开发与管理闭环做完整。

- 新增 `apps/admin/src/stores/instance-context.ts`：当前实例选择保存在模块内存（与管理员会话
  同为会话级状态），默认 local；不使用 web storage，`check_admin_content_architecture.py` 通过。
- 新增 `apps/admin/src/lib/instance-context.ts`：从实例注册表解析当前目标；选中项不存在时
  回退 local；`isRemote` 标记。
- 新增 `apps/admin/src/lib/instance-connector.ts`：local/remote 统一只读接口
  （`probeHealth` + 写策略）；`writePolicy=local_managed|registration_only`；
  `administer()` 在默认与置位 `VITE_REMOTE_INSTANCES_ENABLED=true` 两种情况下都抛
  `RemoteAdministrationDisabledError`——标志只表示就绪，不开放未审计通道。
- 新增 `InstanceContextBadge.vue` 并接入 `AdminLayout`：每个管理页面显示
  「目标实例 · 发布版本 · API 服务器」，远端目标带 registration-only 标记。
- `/instances` 支持「设为当前目标」；页面固定显示当前目标与「API 请求始终发往本控制台自己的
  API」不变式；远端目标显示管理未启动提示。
- 测试：`instance-context.test.ts` 3、`instance-connector.test.ts` 5、
  `InstanceContextBadge.test.ts` 3、`SpeciesInstancesView.test.ts` 7（新增选择用例），
  管理端合计 9 文件 / 37 测试通过。
- 验证：每包 `lint/typecheck/test` 共 36 项顺序执行全部 PASS（36/36）；管理端构建通过；
  `check_admin_content_architecture.py` 通过。注：本沙箱 cgroup pid 计费异常
  （`pids.current` 远超 `pids.max`）导致 `turbo run` 的 spawn 偶发 EAGAIN，
  属环境问题，逐包执行可完整验证。
- 迁移 `0041`：seed 本地实例（幂等 `INSERT ... WHERE NOT EXISTS`；降级只删除未被编辑的 seed）。
  真实 PostgreSQL 验证：upgrade 后 local 行存在；downgrade 删除未编辑 seed；重新 upgrade 再次 seed；
  管理员改名的行在 downgrade 时保留、upgrade 后不被覆盖。离线 SQL 测试 2 个。
- 仍未启动：远程管理代理、服务间凭据、远端写操作、双实例集成测试。

## 10. 全面部署记录（无 Docker 形态，2026-09-26）

### 10.1 环境矩阵与降级说明

| 组件 | 状态 | 端口 |
| --- | --- | --- |
| PostgreSQL（Mamba 16, 55432） | ✅ 部署库 `soymutdb_deploy`（迁移到 0042） | 55432 |
| API（uvicorn） | ✅ 127.0.0.1:8010；`ready` = degraded（PG 正常） | 8010 |
| 公共站 external | ✅ 静态产物 + 同源 `/api/v1` 代理 | 8090 |
| 公共站 internal | ✅ 独立产物 + `noindex, nofollow, noarchive` | 8094 |
| 管理端 | ✅ 登录 + 实例上下文 + 管理 API | 8091 |
| JBrowse 2 | ✅ `--dist`/`/jbrowse/` 同源服务 | 经 8090/8094 |
| Redis / ClickHouse / MinIO | ❌ 本机无二进制、无 Docker → 相应能力降级/503；不得计为通过 | — |

### 10.2 部署期间发现并修复的 P0 缺陷：迁移链落后于模型

- 现象：全新迁移库上 `GET /api/v1/news/featured` 500，`UndefinedColumnError: news_articles.title_en`。
- 根因：测试用 `Base.metadata.create_all`，模型演进（39 列 + `content_versions` 表）没有对应迁移；
  迁移链产出的 schema 与模型不一致，只有真实部署能暴露。
- 修复：迁移 `0042_reconcile_model_schema`：
  - `news_articles`/`static_pages` 双语列从 legacy `title`/`content` 回填后置 NOT NULL；
  - `blast_databases.file_path ← db_path`、`track_categories.display_order ← sort_order`、
    `seed_requests.requester_* ← recipient_*`、`purpose ← research_purpose` 回填后置 NOT NULL；
  - `publications.is_featured`、`tracks.status/is_deleted` 带 server_default 置 NOT NULL；
  - 无历史来源的列（`tracks.file_format/file_url`、`seed_inventory.seed_lot/quantity_grams`、
    `seed_requests.mutant_line_id`）保持 nullable：不伪造历史数据，新行仍由 ORM 强制；
  - 新建 `content_versions`（FK `static_pages`、索引）。
- 验证：
  - 带历史数据的 scratch 库：回填正确（title/content、sort_order、db_path）；
    `downgrade 0041` 精确移除新增列/表；再 `upgrade head` 后 **模型/迁移漂移 = NONE**；
  - 部署库应用 0042 后 `news/featured` 200、news 列表 200；
  - 离线 SQL 升降级契约测试 2 个（API 全套 1608 passed）。

### 10.3 验证证据

- 页面：`8090/`、`8094/`、`8091/login` 均 200；CSP `connect-src` 分别指向各自 origin
  （8090/8094/8091）；internal 带 `noindex, nofollow, noarchive`；external 无 noindex；
  `check_site_artifact_isolation.py` OK；favicon 200 ×3；`/jbrowse/` 及 `assets` 200。
- 代理与数据：三个 origin 的 `/api/v1/health/live` 200；`/site/branding` 200；
  品牌写入（PATCH）→ 经 8090 公共读取生效 → 回滚恢复；
  `GET /admin/species-instances` 列出 seed 的 local 实例；本地探活 healthy 且不联网。
- 真实浏览器（Playwright，en-US 1440×900）：
  - external：app-ready、主导航、标识符搜索、运行时品牌、新闻空态均正常；
  - internal：`noindex` 与 app shell 正常；
  - admin：`deploy_admin` 登录 → dashboard 徽标 `Local SoyMutDB (local) · Release active ·
    Server localhost:8010`；`/instances` 当前目标为 Local SoyMutDB；
  - 控制台仅剩：meta `frame-ancestors` 提示（浏览器行为，部署态由 header 生效）与
    无发布数据导致的 503（预期降级）。
- 仓库门禁：`acceptance.sh --profile runtime` PASS（迁移 + 真实 uvicorn 8765 + health + search）；
  `verify-backend-tests.sh` API **1608** + worker **357**；contracts 232+10。
- 管理账号：`deploy_admin`（administrator），密码已随机轮换，保存在
  `/tmp/soymutdb-deploy/credentials.txt`（600，不进入仓库）。

### 10.4 启停

```bash
# 日志与凭据：/tmp/soymutdb-deploy/{api,portal-ext,portal-int,admin}.log、credentials.txt
# 服务 PID：ss -ltnp | grep -E ':(8010|8090|8091|8094)'
# 停止：按上述 PID kill；重启见 docs/wiki/deployment-and-ops.md「无 Docker 本机部署」
```
