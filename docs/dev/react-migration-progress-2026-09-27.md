# React 前端迁移进度总结（2026-09-27）

## 摘要

SoyMutDB 前端正从 Vue 切换到 **React 19 + Umi Max 4 + Ant Design 6 + ProComponents v3**。Web、Admin、JBrowse 已建立 React/Umi 入口和主要页面骨架，Web 双站构建与主要交付脚本也已接线，并已通过受限生产构建与单元测试；但共享 genome-view、后台发布/SSG 链路、部分后端公开边界和 E2E 对等尚未完成。本文件记录的是**迁移进展，不是发布验收报告**。

迁移规格：[`../superpowers/specs/2026-09-27-react-pro-v6-replatform-design.md`](../superpowers/specs/2026-09-27-react-pro-v6-replatform-design.md)。执行清单与逐次记录见 `.ai-memory/20260927/_plan.md`、`.ai-memory/20260927/daily.md`。

## 已完成的迁移工作

### React 应用与共享组件

- Web、Admin、JBrowse 已改用 Umi Max 配置和 React 入口；React 路由、应用 wrapper、主题及查询客户端已接线。
- 新建 `packages/ui-react`，统一共享 React、Ant Design/ProComponents facade 和品牌 tokens。
- `packages/charts` 已转换为 React/ECharts facade；应用内已有多批 React 页面及组件。
- Admin 增加 Releases、Instances、Brand 等 React 页面；旧 Widget/Page Builder 路由按现有 ADR 保持说明页或重定向，而不是假装仍可用。
- Admin 内容页支持旧 `/content/pages/:pageId` 深链，通过 `?edit=` 拉取页面并打开编辑表单。
- JBrowse 应用已有 React 壳、JBrowse React 视图、assembly 配置及 bridge/deep-link 代码。

### 双站、构建与发布接线

- Web 构建按 `external`、`internal` 分开生成 `apps/web/dist/{external,internal}`，变体、API、JBrowse origin 和 base path 由明确构建环境选择。
- Pages artifact 与 Web 公共 Docker 镜像只复制 `dist/external`，避免把 internal 子树放进公开制品。
- 静态路由、CSP finalizer、可选 gzip、Service Worker、release manifest 和预览/冒烟脚本已适配 Umi 输出布局。
- Admin CSP 保留 `frame-ancestors 'none'`；JBrowse artifact 脚本负责产物头部及 inline-script hash 接线。
- Web Service Worker 改为只在当前变体的 Cache 对象内查找资源，避免全局 cache 查询跨变体命中；哈希匹配兼容 Umi 点号命名，并复用 base-aware 注册 helper。
- `scripts/check-bundle-size.sh` 已从 Vue/Vite chunk 名改为 Umi/Webpack 命名分组、入口脚本和 gzip 大小检查；实际预算仍待构建数据复核。

### 依赖与文档

- React/Umi/Ant Design/ProComponents workspace catalog 与应用依赖已接线。
- 为仍留在工作区的旧 Vue 测试保留了 Vitest/Vue test-only dev dependencies；Vitest 配置也识别 TSX。当前旧测试主要覆盖 Vue 实现，不能替代 React 页面回归测试。
- `pnpm-lock.yaml` 已通过两次 lockfile-only 重算。
- README、部署、Admin 架构、Service Worker、依赖治理及设计系统文档已更新，标明当前 React/Umi 路径和未验收状态。

## 尚未完成

1. **共享 genome-view 未迁移（但已证明与 React 产物无关）**：`packages/genome-view`（Vue 组件包）唯一的消费方是**已退役**的 Vue JBrowse 入口 `apps/jbrowse/src/App.vue` / `main.ts`；本轮新增的 `vue-retirement-contract.test.mjs` 从 `src/umi-entry.tsx` 遍历 import 闭包，断言其中既无 `.vue`、也无 `@soymutdb/genome-view`/`vue`/`vue-router`/`pinia`（`@soymutdb/genome-view-model` 是框架中立的共享模型包，明确允许）。React 侧仍直接用 `@jbrowse/react-linear-genome-view`，共享 React genome-view 包是否需要新建仍是开放决策。
2. **Vue 清除未完成，但“React 入口不得触达 Vue”已成为**门禁**：旧 Vue views、router、组件和测试仍在工作区，`packages/ui-vue` 与 Vue catalog 也暂留；但 `scripts/check-react-entry-graph.mjs` 会遍历三个 app 各自**实际发布**的 `umi-entry.tsx` import 闭包（web 95 / admin 22 / jbrowse 9 个模块），断言其中无 `.vue`、无 `@soymutdb/genome-view`/`vue`/`vue-router`/`pinia`（`@soymutdb/genome-view-model` 为共享模型包，明确放行），并已接入 `scripts/verify-frontend-artifacts.sh`。因此“混合源码”不再等于“边界不确定”；整体 Vue 依赖仍未清零。
3. **后台发布链路（release/SSG）已接通到“可发布真实产物”，但仍未做真实存储/站点联调**：请求端有「release 必须存在且已发布、page version 必须已发布」门禁；请求可带 `build_artifact_url`（http/https/file），该字段随 outbox kwargs 传给 worker；worker 会把它**安全地**物化为 `build_dir`（限流下载、按内容识别 tar、拒绝路径穿越/链接/设备节点、拒绝非目录非 tar），再交给 `build_static_tree`。缺 `build_artifact_url` 时不是“合成占位页”，而是 `MissingBuildOutput` → `failed`。仍未验证的部分：真实对象存储下载、真实 Pages/Cloudflare 上线与 release manifest。生产发布维持 **No-Go**。
4. **后端发布边界仍有存量缺口**：`/seed-requests` 的 `gene_ids` 仍是自由文本（已显式文档化，不做 release 解析）。expression、homolog、BLAST database/job、worker 导出、stats、SRA/widget、downloads、seed inventory/request、publications 定位符、publication 请求门禁已收敛（见下表）。
5. **E2E 未实际执行**：`e2e/tests/jbrowse-browser.spec.ts` 已改写为 React AntD combobox + bridge/context test id，但该套件是部署态门禁（需要 `JBROWSE_BASE_URL`/`PORTAL_BASE_URL` 指向真实构建与已 seed 的已发布 release）。当前环境没有部署栈，所有用例报 SKIPPED，因此**尚未作为验收证据**。
6. **peer 兼容性已复核，结论是“不由本次迁移处理”**：`pnpm peers check` 报 **12 条**未满足 peer，全部来自第三方传递依赖，可归为三类：
   - **Umi/webpack 生态的 React-18 时代依赖**（`react-redux@8`、`react-intl@3`、`react-helmet-async@1.3`、`@ahooksjs/use-request`、`use-sync-external-store` 要 React ≤18 / `@types/react` ≤18，而本仓是 React 19；`@utoo/pack`、`css-loader`、`less-loader`、`sass-loader`、`fork-ts-checker-webpack-plugin`、`html-webpack-plugin`、`@umijs/react-refresh-webpack-plugin` 要各自的 webpack/less/postcss 版本；`dva-*` 要 `dva`/`dva-core`）。这是 `@umijs/max@4.7.20` 自身依赖树的结果，不是本仓声明错误。
   - **缺失的构建期可选 peer**：`styled-jsx`、`webpack`、`prettier`（`prettier-plugin-organize-imports`）。
   - **`vue-router@5.3.1` 要 `vite ^7.3.0 || ^8.0.0`**（当前 vite 6.4.3）。这是唯一有真实版本边界信号的一条，但它只服务**正在退役的 Vue 路径**，正确解法是随 Vue 退役一起移除，而不是为了它做一次跨大版本的 Vite 升级。

   `pnpm peers check` 不是本仓的门禁；门禁是 lint / typecheck / 单测 / 受限构建 / 包大小，且均已通过。用 `pnpm.overrides` 强行满足这些 peer 会掩盖真实不兼容，因此**刻意不做**。

### 本轮已修复的迁移缺口

| 缺口 | 修复位置 | 守卫 |
| --- | --- | --- |
| React Mutant list 不显示 `public_id` | `apps/web/src/routes/mutants/index.tsx`（可见列 + `data-public-id`，`rowKey="public_id"`） | `apps/web/src/regression/public-id-boundary.test.ts`（Vue 侧）+ `packages/api-client/src/mutant-lines.test.ts` |
| detail 页局部 ID 正则、错误地用 public ID 查数值 variant | `apps/web/src/routes/mutants/$id.tsx`（改用 `isMutantLineId`，删除非法 variant 查询） | 同上 |
| `/browser` 无 context 时静默落到 `Wm82.a4.v1` | `apps/web/src/routes/browser.tsx`（`browserContextMissing` 缺失 assembly/release 时渲染中性态，不再猜版本） | `apps/web/src/regression/react-context-and-boundary.test.tsx` |
| `jbrowseUrl()` / `genome-browser-widget` 的 localhost 与隐式 v4 回退 | `apps/web/src/lib/format.ts`、`genome-browser-widget.tsx`、`chromosome-hero.tsx` | 同上 |
| JBrowse 用 assembly **name** 查 `/tracks/jbrowse-config`，跨 release 混轨 | `apps/api/app/api/v1/tracks.py` + `track_service.py`（要求 `assembly_id` + 已发布 `ReleaseContext`）+ `apps/jbrowse/src/App.tsx`（先用 release 域的 `/genes/assemblies` 解析 canonical `assembly_id`） | `apps/api/tests/test_p0_access_control.py` |
| `buildAssembly()` 把未知 v5 克隆成 v4 序列 | `apps/jbrowse/src/App.tsx`（配置缺失/不完整即 unavailable，不回退） | `apps/jbrowse/antd-migration-contract.test.mjs` |
| gene 列表/详情 `variant_count` 恒为 0（React 列与详情统计无意义） | `apps/api/app/services/gene_service.py`（按 release + assembly 聚合） | `apps/api/tests/test_ablation_gene_scope_and_projection.py` |
| gene 列表 `sort_by`/`sort_dir` 被丢弃 | `apps/api/app/schemas/genomic.py`（白名单校验）、`genes.py`、`gene_service.py` | 同上 |
| transcript/exon 把自增主键当 `id` 返回给匿名调用方 | `apps/api/app/services/gene_service.py`（`_public_transcript_id`） | 同上 |
| public page-definition 详情泄露 `id`/`page_id`/`edited_by`/时间戳 | `apps/api/app/api/v1/page_definitions.py` + `page_builder/schemas.py`（`PublicPageDefinitionResponse`） | `apps/api/tests/test_page_definition_public.py`（**Docker 阻塞，见下**） |
| guide 页 Markdown 链接可注入 `javascript:` | `apps/web/src/routes/guide.tsx`（仅 http/https + 同源相对/hash） | `apps/web/src/routes/guide.test.tsx` |
| 认证态响应无 `Cache-Control`/`Vary`（代理可跨用户复用） | notifications / blast / analyses / gwas / jobs(SSE) / tracks 路由 | 各路由窄测 + `test_p0_access_control.py` |
| `/auth/register` 忽略 `feature_registration_enabled`、login 未校验 Origin | `apps/api/app/api/v1/auth.py` | `apps/api/tests/test_auth_sessions.py`（36 passed） |
| `react-hooks/*` 规则未注册，现有 disable 注释报“rule not found” | `eslint.config.js` + 新增 `eslint-plugin-react-hooks` devDependency（只启用 `rules-of-hooks`/`exhaustive-deps`） | `pnpm lint` |
| `/content/snapshot` 声明了 `variant` 却没有传给 service，internal 构建拿到 external 内容 | `apps/api/app/api/v1/content.py`（转发 `variant` + 变体化 cache key/headers）、`content_snapshot_service.py`（变体命名空间 + legacy 回退） | `apps/api/tests/test_ablation_content_snapshot_variant.py` |
| snapshot 的 `about.content_*` 与已发布静态页正文未净化 | `apps/api/app/services/content_snapshot_service.py`（读取时 `sanitize_rich_html`，与 `/site/about` 对齐） | 同上 |
| React vendor chunk 把 react-router/@tanstack router 混进 `react` 分组，105KB 超预算且无法区分回归来源 | `apps/web/config/config.ts`（新增 `router` cache group）+ `scripts/check-bundle-size.sh`（独立 `ROUTER_MAX_KB` 预算） | `bash scripts/check-bundle-size.sh apps/web/dist/external/assets` |
| expression 全部端点未接 `ReleaseContext`；库可跨 release 列出、v4 库可挂到 v5 基因、cursor 是裸 `ExpressionData.id`、payload 带库主键 | `apps/api/app/api/v1/expression.py`（release+assembly 双重限定、签名 cursor、`public_id`/`library_public_id`）、`packages/api-client/src/expression.ts` | `apps/api/tests/test_ablation_expression_release_scope.py` |
| homolog 两个端点未接 `ReleaseContext`；无 `gene_id` 的 search 会列出所有 release；cursor/payload 是 `GeneHomolog.id`；client 的 `species` 参数服务端不识别 | `apps/api/app/api/v1/homolog.py`、`gene_service.py`（共享 `resolve_released_gene`）、`packages/api-client/src/homolog.ts` | `apps/api/tests/test_ablation_homolog_release_scope.py` |
| worker 导出把 `gene_surrogate_id`/`mutant_line_surrogate_id` 写进每个 VCF/TSV/CSV/JSON/BED 产物；`MAX_RECORDS_EXPORT` 声明未使用 | `apps/worker/src/soymutdb_worker/tasks/export.py`（公共定位符 + release/assembly provenance + 预算硬门禁 + 按列名取值） | `apps/worker/tests/test_export_public_artifact.py` |
| BLAST `/databases` 列出所有 active 行、`_resolve_database` 无 release 谓词、默认兜底取任意 `Assembly.is_default`、job/outbox 无 provenance | `apps/api/app/api/v1/blast.py`、`blast_service.py`（列表/解析/兜底全部 release 限定，outbox 与响应带 release+assembly provenance）、`schemas/blast.py` | `apps/api/tests/test_ablation_blast_release_scope.py` |
| `/stats/dashboard` 统计全表、匿名泄露账号总数、单一全局缓存键 | `apps/api/app/api/v1/stats.py`（按 release 的 assemblies/mutants/phenotypes 统计，`total_users=0`，缓存键带 release）、`clickhouse_service.py`（CH 聚合绑定 `release_key`） | `apps/api/tests/test_ablation_stats_release_scope.py` |
| `/stats/variant-types`、`/stats/density` 不传 release 给 ClickHouse，跨 release 混算 | `apps/api/app/api/v1/stats.py` + `clickhouse_service.py`（`release_key` 绑定参数） | 同上 |
| `/stats/summary/*`、`/stats/mutagens` 接受任意 `release_id`（含 draft），不传就不过滤 | `apps/api/app/api/v1/stats.py`（改为无条件按已发布 release 过滤） | 同上 + `apps/api/tests/test_stats_contract.py` |
| `/stats/releases` 默认列出所有 release（含 draft/rolled-back） | `apps/api/app/api/v1/stats.py`（仅 `status=active` 且已发布） | 同上 |
| SRA `/run/{acc}` 用 fixture 冒充任意 accession、网络失败编造 `"unknown"` stub；widget 把 demo 记录的 `Run` 改成请求的 accession | `apps/api/app/api/v1/sra.py`（失败返回 503、fixture 仅 demo 模式且限本身 accession）、`widgets/data_sources/sra.py`（`run=None` + `fetch_error`）、`widgets/templates/sra_run.html`（显式 unavailable 分支）、`core/config.py`（新增 `demo_fixtures_enabled`） | `apps/api/tests/test_ablation_sra_no_fabrication.py` |
| `sra_run` widget 用 stdlib logger 传 structlog 关键字参数，任何抓取失败都会抛 `TypeError` | `apps/api/app/widgets/data_sources/sra.py` | 同上 |
| stats client 发送服务端已不再读取的 `release_id`，并暴露 5 个服务端不存在的端点方法 | `packages/api-client/src/stats.ts`（移除无效参数与死方法）、`apps/web/src/lib/query-options.ts` | `packages/api-client` + web 单测/typecheck |
| variants 公共 `?mutant_line_id=` 直接绑到 ClickHouse `mutant_line_surrogate_id`（UInt32），公共 id 匹配不到、数值 id 却被接受 | `apps/api/app/api/v1/variants.py`（`mutant_line_public_id` 先做形状校验→在已发布 release 内解析为内部键；数值/内部值返回 422）、`schemas/variant.py`、`core/public_ids.py`（示例宽度与 `_BODY_LENGTH` 对齐） | `apps/api/tests/test_ablation_variant_public_filter.py` |
| variants client/React 路由仍用内部键名 `mutant_line_id` 作为公共过滤器 | `packages/api-client/src/variants.ts`、`packages/query-keys/src/index.ts`、`apps/web/src/routes/variants/index.tsx`、`lib/query-options.ts`、Vue 侧请求映射 | web/query-keys/api-client 单测 + typecheck |
| `/content/downloads` 列出所有行（含 draft 与未绑定 release）；`/downloads/{id}/url` 只按主键查、presign 失败回退裸 `s3://`、任意 scheme 直接返回 | `apps/api/app/api/v1/content.py`（release 限定、`s3://` 预签失败 fail-closed 503、scheme 白名单、`private, no-store`） | `apps/api/tests/test_ablation_content_downloads_scope.py` |
| 前端 `downloads`/`search` 把服务端 URL 直接交给 `window.open`/`href` | `apps/web/src/lib/url-safety.ts`（共享 `safeExternalUrl`）、`routes/downloads.tsx`、`routes/search.tsx` | `apps/web/src/regression/url-safety.test.ts` |
| `/seeds/inventory` 列出全部行、按主键寻址，响应回传内部 `mutant_line_id`；`POST /seeds/requests` 接受数值内部键 | `apps/api/app/api/v1/seeds.py`（release 限定 + 公共 lot 标签寻址）、`services/seed_service.py`、`schemas/seed.py` | `apps/api/tests/test_ablation_seed_public_boundary.py` |
| `publication.request` 接受任意正数 `release_id`，从不校验 release 状态或 page version | `apps/api/app/services/publication_service.py`（release 必须存在且 `published`；page version 必须 `published`；门禁在分配 lease 之前） | `apps/api/tests/test_ablation_publication_release_gate.py` |
| `/seed-requests` 的 `gene_ids` 语义含糊（看似 release 解析实则自由文本） | `apps/api/app/schemas/seed_request.py`（显式文档化自由文本语义与原因） | `apps/api/tests/test_seed_requests.py` |
| `/content/publications` 以数值持久化 ID 作为公共定位符（响应带 `id`、detail 接受整数） | `apps/api/app/api/v1/content.py`（改为 DOI 寻址，非 DOI 直接 404 且不查库）、`schemas/content.py`（新增仅管理端可用的 `AdminPublication*` DTO 承载主键）、`services/content_snapshot_service.py`、`packages/api-client/src/publications.ts` + `admin-publications.ts`、`apps/web/src/routes/publications.tsx`、`apps/admin/src/routes/publications.tsx` | `apps/api/tests/test_ablation_content_publication_locator.py` |
| worker 在无 SSG 链路时合成单页 `index.html`，于是“发布成功”实际部署空站点 | `apps/worker/src/soymutdb_worker/tasks/static_publish_impl.py`（`build_static_tree` 必填 `build_dir`，缺失/非目录/缺 `index.html` 即 `MissingBuildOutput` → `failed`，无合成回退；新增 `MissingBuildOutput`） | `apps/worker/tests/test_static_publish.py` |
| `GithubPagesAdapter.stage()` 返回空 `metadata`，`promote()` 却要读 `publication_id`/`artifact_url`，dispatch 出空输入 | `apps/worker/src/soymutdb_worker/publication/github_pages.py`（stage 落 metadata；缺 artifact URL 模板即拒绝 dispatch）、`publication/__init__.py`（接线 `GITHUB_PAGES_ARTIFACT_URL_TEMPLATE`） | `apps/worker/tests/test_ablation_publication_staging.py` |
| `should_promote()` 只在 stage 前检查一次，部署期间的更新请求会被旧产物覆盖 | `static_publish_impl.py`（promote 前紧邻再检查一次，命中即 `superseded` 且不 promote） | 同上 |
| Cloudflare `_upload` 只 POST 绝对路径字符串 + hash，远端无法据此上传任何文件 | `publication/cloudflare_pages.py`（改为 multipart 发送文件字节，文件为空即拒绝）、`publication/http.py`（新增 `post_multipart`/`_encode_multipart`） | 同上 |
| outbox 完全没有把 SSG 产物信息交给 worker（请求端无法指定构建产物） | `apps/api/app/schemas/publication.py`（新增 `build_artifact_url`，仅允许 http/https/file）、`api/v1/admin_publication.py`、`services/publication_service.py`（随 kwargs 与审计 `new_value` 传递） | `apps/api/tests/test_ablation_publication_release_gate.py` |
| worker 无法获取远端构建产物（此前唯一输入是可选 snapshot） | `apps/worker/src/soymutdb_worker/tasks/static_publish_impl.py`（`materialize_artifact`：限流下载 `MAX_ARTIFACT_BYTES`、`tarfile.is_tarfile` 按内容识别、`_safe_extract` 拒绝穿越/绝对路径/符号链接/硬链接/设备节点、`file://` 与本地目录支持） | `apps/worker/tests/test_ablation_publication_artifact_transport.py` |
| 发布请求的构建产物引用只存在于 outbox payload，发布审计里只有 digest、无法指认源产物 | `apps/api/migrations/versions/0043_publication_build_artifact.py`（新增可空 `static_publications.build_artifact_url`，与既有 `artifact_url`（输出）语义区分）、`models/publication.py`、`schemas/publication.py`、`services/publication_service.py` | `apps/api/tests/test_publication_build_artifact_migration.py`（离线 upgrade/downgrade SQL + ORM 不漂移） |
| `scripts/test_ci_job_contracts.py` 两条契约测试停留在**迁移前**形态，长期红：`allowedHosts` 断言要求 Umi 明确拒绝的顶层 `devServer` 键；i18n 断言要求 `src/test/mocks.ts` 不存在（迁移的解法恰恰是集中提供一个**正确**的 double） | `scripts/test_ci_job_contracts.py`（allowedHosts 改为断言 `chainWebpack`/`memo.devServer` 形态，并**加强**为「`"all"` 只能出现在显式 opt-in 分支内」；i18n 改为断言无 per-render `t`、沿共享 adapter 追到 `i18n-core`、并正向断言 `stableT` 的 identity/interpolation 语义） | `python3 scripts/test_ci_job_contracts.py`（60 passed） |
| 退役的 Vue 入口 / `packages/genome-view` 可能被 React 侧无意重新引入，且只会在运行时暴露 | `scripts/react-entry-graph.mjs`（共享遍历实现）、`scripts/check-react-entry-graph.mjs`（三 app 门禁，含 graph size 下限以暴露「遍历过早停止」）、`apps/jbrowse/vue-retirement-contract.test.mjs` | `scripts/check-react-entry-graph.test.mjs`（8 passed，含负向对照） |
| JBrowse E2E 断言仍指向已退役的 Vue 原生 `<select>` / `genome-ruler` | `e2e/tests/jbrowse-browser.spec.ts` 重写为 React AntD combobox + bridge/context test id；`browser.tsx` / JBrowse `App.tsx` 增加稳定 test id | `e2e/tests/jbrowse-browser.spec.ts`（部署态才执行） |

## 验证记录与限制

### 本轮已执行并通过

- **JBrowse 契约**：**40 passed**（含 `vue-retirement-contract.test.mjs` 5 passed，已并入包内 `test` 脚本）。
- **Vue-retirement 门禁**：`node scripts/check-react-entry-graph.mjs` → `web 95 / admin 22 / jbrowse 9` 模块全部 PASS；`node --test scripts/check-react-entry-graph.test.mjs` → **8 passed**，其中一条是**负向对照**（从 `apps/jbrowse/src/App.vue` 起步时能检出 4 个 `.vue` 与 `vue`/`@soymutdb/genome-view` 导入），证明该门禁不是空转。
- **仓库契约测试（Python）**：`test_ci_job_contracts.py` **60 passed**（修复两条长期红的迁移前契约，见下表）、`test_deployment_workflows.py`、`test_dockerfile_contracts.py`、`test_platform_delivery_contracts.py`、`test_production_compose_contract.py`、`python3 -m unittest scripts.test_site_artifact_isolation`（11 passed）全部通过。
- **Web 单元测试**：`apps/web` → **58 files / 316 tests passed**（含本轮新增 `src/regression/url-safety.test.ts`，以及此前的 `react-context-and-boundary.test.tsx`、`guide.test.tsx`；清空 vitest 缓存后连跑多次稳定）。Admin **22 files / 98 tests passed**；JBrowse 契约 **35 passed**。
- **query-keys 单元测试**：`packages/query-keys` → **11 tests passed**（assembly 目录/chromosomes 现在按 release + site 分键；gene 搜索键补齐 chromosome/biotype/page_size/sort）。
- **worker 测试**：`apps/worker` → **376 passed / 24 skipped**（本轮新增 `tests/test_ablation_publication_staging.py` 11、`tests/test_ablation_publication_artifact_transport.py` 14，`tests/test_static_publish.py` 扩充到 6；此前有 `tests/test_export_public_artifact.py` 10）。
- **api-client 测试**：`packages/api-client` → **27 files / 149 tests passed**。
- **包大小预算（真实产物）**：拆分 `router` cache group 后，`external` 与 `internal` 两个变体的 `entry/react/router/ui/query/charts` 与逐 chunk 预算**全部 PASS**（react 68KB/100KB、router 38KB/100KB、charts 338KB/370KB、entry 200KB/750KB）。
- **TypeScript**：`apps/web`、`apps/admin`、`apps/jbrowse` 三个 `tsc --noEmit` 全部通过。移除 `/search` 的 `as any` 后暴露出两个真实类型缺陷并已修复：`site-header` 向 `/search` 传了路由从不读取的 `tissue/treatment/min_fpkm`；`search.tsx` 把 `string[]` 直接当 `SearchResultType[]` 用（现在按白名单收窄）。
- **ESLint**：注册 `react-hooks` 插件并补齐 `.mjs` 的 Node globals 后，`apps/*/src`、`apps/*/config`、`packages/*`、`e2e/tests` 为 **0 error**（仅剩 4 条测试文件里的 `any` 警告，配置刻意降级为 warning）。顺带清掉 `e2e/tests` 里两处真实缺陷（未使用的 `captureWindowOpen`、`openedUrl` 的无效初始化）。
- **受限生产构建**（`GOMAXPROCS=1 ESBUILD_WORKERS=1`，显式 `VITE_DEPLOYMENT_MODE/VITE_SITE_VARIANT/VITE_API_BASE_URL/VITE_JBROWSE_BASE_URL/VITE_SOYMUTDB_RELEASE_ID`）：`apps/web`、`apps/admin`、`apps/jbrowse` 的 `max build` 均 exit 0 并产出 `dist/`。
- **Web 双站构建**：`apps/web` `tsx scripts/build-sites.ts` exit 0，产出 `dist/{external,internal}`，27 个静态文档 ×2 变体，CSP finalizer 与 `gen-sw` 均执行。
- **制品抽查**：`dist/external/_headers` 的 `connect-src` 为构建注入的 `https://api.soymutdb.test`，`dist/internal/_headers` 为 `https://api.internal.soymutdb.test`（变体隔离生效；文中另一处 `<the API origin …>` 位于 `#` 注释内，非生效头）。Service Worker `CACHE_VERSION` 分别为 `external-…` / `internal-…`，未跨变体。
- **后端窄测（无需 Docker）**：`test_p0_access_control.py`、`test_release_bound_queries.py`、`test_ablation_gene_scope_and_projection.py`、`test_ablation_content_snapshot_variant.py`、`test_ablation_cache_site.py`、`test_ablation_expression_release_scope.py`、`test_ablation_homolog_release_scope.py`、`test_ablation_blast_release_scope.py`、`test_blast_database_select.py`、`test_blast_outbox.py`、`test_blast_validation.py`、`test_homolog_cursor_contract.py`、`test_ablation_stats_release_scope.py`、`test_ablation_sra_no_fabrication.py`、`test_stats_contract.py`、`test_cache.py`、`test_widget_registry.py`、`test_clickhouse_capability_503.py`、`test_openapi_contract.py`、`test_ablation_variant_public_filter.py`、`test_ablation_seed_public_boundary.py`、`test_ablation_content_downloads_scope.py`、`test_ablation_publication_release_gate.py`、`test_content_snapshot.py`、`test_content_snapshot_cache.py`、`test_ablation_content_publication_locator.py`、`test_static_publications.py`、`test_seed_requests.py`、`test_search.py`、`test_search_contract.py`、`test_auth_sessions.py` 合并运行 **382 passed**（另有 11 条 testcontainers 用例因 Docker 缺失报 ERROR）。`pytest apps/api/tests --collect-only` 对整套 1823 个用例收集成功、无导入错误；整包直接跑会因 testcontainers 连接重试而超时，因此以「无 Docker 子集 + 全量收集」两项组合作为后端证据。本轮改动过的 Python（含 worker）文件逐个 `ruff check` 全部通过。若把 `apps/api/app/api/v1/`、`services/`、`schemas/` **目录整体**交给 ruff，会报 84 条**既有** E501/UP037 存量告警（不属于本轮改动，也不在本轮修复范围内）——引用证据时请只针对改动文件，否则会把存量债算到本次迁移上。

构建环境为必需项而非回退项：缺少 `VITE_API_BASE_URL` 时 `requireDeploymentOrigin` 直接让配置加载失败（`API origin is required for production deployment`）。这是预期的 fail-closed 行为，上面的构建都显式传入了部署上下文。

### 本轮未执行 / 被阻塞

- **PostgreSQL/Docker 消融守卫未运行**：`apps/api/tests/test_ablation_identity_public_boundary.py`、`test_ablation_assembly_scope_and_crossversion.py`、`test_page_definition_public.py` 等依赖 testcontainers 的用例在当前环境报 `docker.errors.DockerException: Error while fetching server API version … No such file or directory`（没有 Docker Unix socket）。这些守卫是 **SKIPPED，不是 PASS**；它们必须在有 Docker 的环境重跑后才能作为公开边界证据。
- **发布链路验收未运行**：Pages/Docker 发布、release manifest（`standard` 模式按设计跳过）、`scripts/verify-frontend-artifacts.sh` / `verify-site-variant-artifacts.sh` 全流程均未执行。Playwright JBrowse E2E 已显式无部署变量运行，**6 skipped**（这是预期的缺前置，不算通过）；真实 `JBROWSE_BASE_URL` / `PORTAL_BASE_URL` 下的 6 个部署态测试仍未执行。
- **发布链路未做真实存储/站点联调**：传输、安全物化与产物引用落库（迁移 0043，已用离线 SQL 验证 upgrade/downgrade）都已完成并有单测，但没有对真实对象存储或真实 Pages/Cloudflare 目标跑过端到端发布，也没有产出 release manifest。**因此仍不能算通过**：迁移只在离线 SQL 层验证过，没有在真实 PostgreSQL 上跑 upgrade/downgrade。
- 因此本文件仍**不是发布验收报告**；生产发布维持 **No-Go**。

### 复现方式（本轮全部证据）

```bash
# 单元/契约测试
(cd apps/web && node_modules/.bin/vitest run)                 # 58 files / 316 passed
(cd apps/admin && node_modules/.bin/vitest run)               # 22 files / 98 passed
(cd packages/api-client && node_modules/.bin/vitest run)      # 27 files / 149 passed
(cd packages/query-keys && node_modules/.bin/vitest run)      # 11 passed
(cd apps/jbrowse && node --test antd-migration-contract.test.mjs \
  bridge-contract.test.mjs locus-search.test.mjs vue-retirement-contract.test.mjs)  # 40 passed
(cd apps/worker && ../api/.venv/bin/python -m pytest tests -q)  # 376 passed / 24 skipped

# 后端（无需 Docker）
apps/api/.venv/bin/python -m pytest \
  apps/api/tests/test_p0_access_control.py \
  apps/api/tests/test_release_bound_queries.py \
  apps/api/tests/test_ablation_gene_scope_and_projection.py \
  apps/api/tests/test_ablation_content_snapshot_variant.py \
  apps/api/tests/test_ablation_content_downloads_scope.py \
  apps/api/tests/test_ablation_content_publication_locator.py \
  apps/api/tests/test_ablation_publication_release_gate.py \
  apps/api/tests/test_publication_build_artifact_migration.py \
  apps/api/tests/test_ablation_expression_release_scope.py \
  apps/api/tests/test_ablation_homolog_release_scope.py \
  apps/api/tests/test_ablation_blast_release_scope.py \
  apps/api/tests/test_ablation_stats_release_scope.py \
  apps/api/tests/test_ablation_sra_no_fabrication.py \
  apps/api/tests/test_ablation_variant_public_filter.py \
  apps/api/tests/test_ablation_seed_public_boundary.py \
  apps/api/tests/test_ablation_cache_site.py \
  apps/api/tests/test_stats_contract.py apps/api/tests/test_cache.py \
  apps/api/tests/test_content_snapshot.py apps/api/tests/test_static_publications.py \
  apps/api/tests/test_seed_requests.py apps/api/tests/test_openapi_contract.py -q
apps/api/.venv/bin/python -m pytest apps/api/tests --collect-only -q   # 1823 collected

# 仓库契约 / 边界门禁
node scripts/check-react-entry-graph.mjs          # web 95 / admin 22 / jbrowse 9 模块，全 PASS
node --test scripts/check-react-entry-graph.test.mjs                  # 8 passed（含负向对照）
python3 scripts/test_ci_job_contracts.py                             # 60 passed
python3 -m unittest scripts.test_site_artifact_isolation             # 11 passed

# 静态检查
./node_modules/.bin/tsc -p apps/web/tsconfig.json --noEmit   # 另 admin/jbrowse/5 个包同
GOMAXPROCS=1 ./node_modules/.bin/eslint apps/web/src apps/admin/src apps/jbrowse/src packages e2e/tests
apps/api/.venv/bin/ruff check <本轮改动过的 py 文件>

# 受限生产构建（必须显式传部署上下文，否则 fail-closed）
(cd apps/web && GOMAXPROCS=1 ESBUILD_WORKERS=1 VITE_DEPLOYMENT_MODE=standard \
  VITE_SITE_VARIANT=external VITE_API_BASE_URL=https://api.soymutdb.test \
  VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test VITE_SOYMUTDB_RELEASE_ID=2026.09 \
  ./node_modules/.bin/tsx scripts/build-sites.ts)
bash scripts/check-bundle-size.sh apps/web/dist/external/assets   # OK
```

**未纳入上述命令、因此不算通过的项**：所有 testcontainers/Docker 消融守卫、在真实 PostgreSQL 上跑迁移 0043、真实对象存储+Pages/Cloudflare 的端到端发布与 release manifest、Playwright E2E。

## 后续实施顺序建议

1. 补齐后台发布链路：publication outbox 携带 SSG 构建输入、worker 真实执行 SSG、GitHub/Cloudflare adapter 的 artifact metadata 与 multipart 上传，并让 request 端校验 release/page version 的权威状态。
2. 发布链路已从“假成功”推进到“可发布真实产物但未联调”：请求携带并落库 `build_artifact_url`（迁移 0043），worker 安全物化并拒绝空产物，adapter 已修 metadata 与真实字节上传。下一步是在真实 PostgreSQL 上跑迁移，并接一个真实 SSG 产物存储与目标站做端到端联调（并补 release manifest 证据）。
3. 在有 Docker 的环境重跑 PostgreSQL 消融守卫并记录真实计数，替换当前的 SKIPPED 说明。
4. 把 `e2e/tests/jbrowse-browser.spec.ts` 等 Vue 断言改写为 React AntD/JBrowse 选择器，补齐 React 路由级回归（搜索边界、mutant public ID、assembly 歧义、variants 导出、基因 v5 详情与 JBrowse deep link）。
5. 决定 `packages/genome-view` 的 React 实现边界；完成共享 UI、图表和基因组视图包的 React 消费关系。
6. 以上验收通过后，再按 W5 清理 Vue runtime、plugin、组件、旧 tests/config 和无用依赖；清理前不得宣称迁移完成。

## 工作区保护

实施期间保留已有非前端修改与未知文件；没有整体 reset、checkout 或 clean。后端目录存在的修改属于既有工作区状态，本轮只做了与迁移验收直接相关的公开边界/发布范围修复。
