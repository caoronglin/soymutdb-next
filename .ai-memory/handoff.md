# Handoff 检查点 — 2026-10-02 收尾（审计后优化：W0–W4 完成，W6 框架就位）

## 已完成（带证据，全部实跑）

| 阶段 | 结果 | 关键证据 |
| --- | --- | --- |
| W0 基线 | ✅ | 推翻旧结论 3 条；推翻「无浏览器」1 条 |
| W1 守卫 | ✅ | 6 守卫 exit 0；守卫缺陷修 2 处 + 负例 |
| W2 assembly | ✅ | 10 消费点；运行时 release 切换（新增端点 + 订阅 + 精确失效）；消融 ×2 |
| W3 会话权限 | ✅ | 五态状态机；匿名零个人请求；并发 401 修复；`effective_roles` |
| W4 UI/UX | ✅ | i18n 守卫 **39 → 0 文件**；真实浏览器 **10/10**；rowKey 4/4；多行 alt 已覆盖 |
| W6 框架 | 🔶 | `db_ab_experiment.py` + 37 tests；消融 ×3；**未跑实测，无性能结论** |

提交（全部已推 `origin/main`）：`160b42e69` `79509b7ec` `e211764f5` `e494b1cb2` `d721dc118`

## 相关文件

新增（本轮）：`scripts/db_ab_experiment.py`、`scripts/test_db_ab_experiment.py`、
`scripts/test_web_query_keys_guard.py`、`scripts/test_visible_i18n_react_guard.mjs`、
`e2e/verify-a11y-and-layout.mjs`、`apps/web/src/components/data-table.test.tsx`、
`apps/web/src/lib/{session-context.tsx,session.test.ts,use-current-user.test.ts,
assemblies-query-options.test.ts,release-scope.tsx,release-scope.test.tsx,analyses-i18n.test.ts}`、
`apps/web/src/components/analyses/researcher-gate.test.tsx`、
`apps/api/tests/{test_me_capabilities.py,test_active_release_endpoint.py}`、
`packages/api-client/src/auth-concurrency.test.ts`

## 未完成 / 阻塞

- **`cnb` 远端未推送**（cnb.cool 无凭据）。`origin` 已同步到 `d721dc118`。
- **无 psql / pgcli / Docker** → 数据库实测未跑，**无任何性能结论**。
- **`ant` CLI 缺失** → antd 门面/别名扫描盲区未补。
- **无真实后端** → 会话/权限/发布切换端到端未验证。
- **全量 `eslint src` SIGABRT（134）**；**`git diff --check` 因 CRLF 报 2**（真实尾随空格=0）。
- **W5 / W7 未开始** —— 受阻于产品确认与部署目标。
- **协作风险**：同一工作树有并发会话（本轮核实为只读，但曾致构建 SIGABRT）。

---

## 已完成（带证据）

### Wave 0 基线
HEAD `7bf002a29`；149 项未提交改动 + 41 untracked 保留未动。环境：PG 55432 在线、chdb 4.4.0、Python 3.14.6、pnpm 12.5.1、Node 26.8.2（≠pin）。

### Wave 1 公开边界（P0-01/02/04）
三入口按 active published release 过滤；suggest fail-closed；internal search 支持 internal id。
证据：`pytest tests --ignore=tests/a0` = 1277 passed；contracts smoke 全绿。

### Wave 2 assembly 与 VCF（P0-03/P1-01/P1-02/P1-03）
- P0-03 全集判歧义 + api-client/SearchView 分组与版本/release/来源展示。
- P1-01 `compute_variant_id` 纳入 assembly；finalize carry 保留非本次导入 assembly 的同染色体旧行（chdb 端到端用例）。
- P1-02 zygosity 读选中样本。
- P1-03 生产 `variant_facts_staging` DDL + schema 契约。
证据：worker 337 passed（24 skipped）；SearchView/VariantsView 等 web 111 passed；ClickHouse schema 契约 8 passed。

### Wave 3 公共站（P1-04/P1-05）
- P1-04 `queryKeys.variants.list` 纳入 cursor（query-keys 10 passed）。
- P1-05 SearchView 翻页控件 + VariantsView All-assemblies 版本列（web 111 passed；vue-tsc 通过）。

### Wave 4 管理端（P1-07 完成；P1-06 部分）
- P1-07 `WriteTargetNote` 明确本地写入目标、远端 registration-only 警告。
- P1-06 `/imports/new` 创建 + `/imports/:taskId` 详情/重试/取消 + 旧深链断言恢复。
证据：admin vitest 43 passed；vue-tsc 通过。

### Wave 5（P0-06a 已满足；P1-08 部分）
- 核实 HEAD 已把双站隔离脚本接入 CNB `frontend_run` 与 GitHub frontend job。
- JBrowse 生产 gate 改为 frame 缺失即失败。
- contracts smoke：234 passed + 10 environment-bound。

## 未完成
- **P0-06(b)**：CNB 无 Kind 门禁等价，release 未 await Kind；需真实 CI + 故障注入验证。
- **P1-08 剩余**：把 public/admin/JBrowse E2E 接入共享 CI job；需目标部署实测 CSP/缓存/SW/子路径。
- **P1-06 剩余**：导入 studio 上传/校验/提交 UI；真实 Dashboard 指标（dashboard-stats 既有 schema 漂移）。
- **P2 全部**：News 双语/预览/排序、品牌媒体闭环、`/table-views` 别名、FASTA/GFF3/BLAST/CSV adapter、staging TTL、Web 性能测量、baseline-validation 内联逻辑、AGENTS.md pnpm 漂移。
- **§6 发布判定**：external/internal 双站制品、真实部署、G10/G12 仍 No-Go。

## 阻塞
- 无 CNB/GitHub CI 执行环境；无 Kind/Docker；无 MinIO。
- `tests/a0` 收集失败 `ModuleNotFoundError: tools`（既存）。
- Node 26.8.2：vitest/vue-tsc 需 `RAYON_NUM_THREADS=1`。
- 生产发布维持 **No-Go**。

## 本轮改动文件（核心）
- API：`mutants.py`、`search.py`、`search_service.py`、`schemas/search.py`、`schemas/variant.py`、`services/variant_service.py`
- Worker：`tasks/ingest.py`、`tasks/variant_finalize.py`、`scripts/seed_release_data.py`
- ClickHouse：`infra/clickhouse/init.sql`、`upgrade_variant_facts_schema.sql`、`test_schema_contract.py`
- 前端/客户端：`packages/api-client/src/{search,variants,admin-imports}.ts`、`packages/query-keys/src/index.ts`、`apps/web/src/{lib/query-options,views/SearchView,views/VariantsView}.vue`、`apps/admin/src/{views/ImportDetailView,ImportCreateView,ImportsView,NewsAdminView}.vue`、`apps/admin/src/components/WriteTargetNote.vue`、`apps/admin/src/router/index.ts`、i18n locales
- E2E：`e2e/tests/production-gate.spec.ts`
- 测试：见各 Wave daily 记录

## 消融检验结果（2026-09-26，排除 CNB/GitHub）

| 场景 | 状态 | 证据 |
| --- | --- | --- |
| ID-01 | ✅ | `test_external_mutant_search_uses_public_id_only` |
| ID-02 | ✅ | `test_internal_persistence_key_is_not_a_public_locator`（HTTP 404，无存在性 oracle） |
| ID-03 | ✅ | `test_search_internal_http`：匿名 401 / 低权 403 + private,no-store |
| ID-04 | ✅ | `test_internal_search_returns_both_identities_and_matched_field`（public_id/internal_id/name） |
| ID-05 | ✅ | `verify-site-variant-artifacts.sh` 构建 external/internal 并扫描；external 零内部哨兵；isolation 单测 6 passed |
| ASM-01/02/03 | ✅ | `test_v4_v5_same_accession_coexist_and_are_labelled`、`test_unscoped_ambiguity_is_judged_over_full_match_set` |
| **ASM-04** | ❌ 缺口 | 探针：v4 exact 命中存在但 `match_type` 无 `cross-version`；`GeneCrosswalk` 未被搜索服务读取（`ASM04_CROSS_VERSION_HITS 0`） |
| ASM-05 | ✅ | `test_similar_genes_without_crosswalk_stay_unrelated` |
| CTX-01/02/03 | ✅ | 新增 `test_global_search_cache_isolates_site_variant_release_and_assembly` + `test_internal_global_search_bypasses_the_shared_cache` |
| ClickHouse 空库 | ✅ | `test_clickhouse_production_ddl`：生产 init.sql 31/31 语句加载，stage→verify→finalize 通过 |
| ClickHouse 升级库 | ✅ | `test_legacy_clickhouse_migration`：legacy fixture→upgrade 幂等；`variant_facts_legacy` 保留作回滚 |
| UI-01 | ✅ | `Mutants.test.ts`：list/detail 仅 public_id |
| **UI-02** | ❌ 缺口 | 无 internal 搜索 UI 组件 |
| E2E-01/02 | ⏸ 未跑 | 需已部署栈 + 浏览器 + seed 数据 + JBrowse |

**新确认缺口（需产品口径）**：ASM-04（跨版本显式关联需要 `SearchResultItem` 增加关联字段并回填 `match_type=cross-version`）、UI-02（内部搜索界面）。二者均 P1，不阻断 P0，但审计 §6 要求关闭。

## 打包流程优化（2026-09-26）

**改动**：`scripts/verify-frontend-artifacts.sh` 不再第三次构建 web，改 `turbo run build --filter='!@soymutdb/web'` + `build:sites`；web 检查指向 `dist/external`；`scripts/verify-site-variant-artifacts.sh` 支持 `SOYMUTDB_SITE_VARIANTS_PREBUILT=1` 复用；`scripts/ci-job-steps.sh` 与 `.github/workflows/ci.yml` 双站步骤置该标记；`scripts/check_app_shell_assets.py` 变体收敛为 (`dist/external`,`dist/internal`)。

**验证**：build:sites、isolation 复用断言、production-artifact / bundle-budget(`dist/external/assets`) / app-shell(含 self-test) / artifact-headers / visible-i18n、`test_ci_job_contracts` 58 passed、contracts smoke — 全绿。

**未验证**：完整 `verify-frontend-artifacts.sh` 端到端（本机 turbo 线程耗尽，需 CI）。**发布制品未改**：`build-pages-artifact.sh`/`build-sites.ts` 未动，`pages-dist` 字节不变。

**环境**：本机 `pnpm build`(turbo) 因 cgroup 线程限制崩溃（`failed to create new OS thread`），直连 vite 需 `GOMAXPROCS=1 RAYON_NUM_THREADS=1`；判为环境问题，未写入仓库。

## 核心功能部署（JBrowse 可选，2026-09-26）

**改动**：`VITE_JBROWSE_ENABLED` 构建门（`deployment.ts`）；`PortalHeader` 隐藏 `/browser`；路由把 `/browser`、`/gbrowse` 解析到新增 `FeatureUnavailableView`；`GeneView` 隐藏 JBrowse 链接；`build-pages-artifact.sh` 支持 `SOYMUTDB_JBROWSE_ENABLED=0`（跳过 jbrowse + 写 `.no-jbrowse`），`verify-pages-artifact.sh`/`stage-pages-publication.sh` 仅在标记存在时接受缺失；`docs/ops/core-only-deployment.md`。

**compose**：`core` profile 本就不含 jbrowse/blast/analyses/mcp；nginx 因 `extra_hosts` 可启动。

**验证**：web vitest 115、vue-tsc、i18n parity、core-only pages 制品 verify、contracts smoke 全绿；以 flag off 构建产物无 `/browser` 导航、含 FeatureUnavailableView。

**未验证**：完整 `build-pages-artifact.sh` 端到端（`setup-workspace.sh` corepack EACCES 属本机环境）；以等价手工步骤验证制品逻辑。

## 2026-09-26 晚 — 零 React Vue 基因组视图 Wave（协调者 + 4 子代理）

### 已完成（带证据）
- packages/genome-data：@gmod 读取器 + factory + 离线 fixtures（BGZF/tabix/Trix/chrom.sizes）；87 tests、tsc、eslint 全绿（81cf09c6a）。
- packages/genome-view：viewport composable、track registry、错误边界、ruler/selector/search、SVG 特征/变异/定量/序列轨道、纯布局核心、数据连接的 TrackRenderer；53 tests、vue-tsc、eslint 全绿（1c3f7568c…f2b0e822d）。
- packages/genome-view-model：viewport/zoom/clip/ticks（1-based inclusive）；23 tests（9c7d35da6）。
- bridge 契约加固：消息类型白名单 + 禁止调用方伪造 source/version；jbrowse 21、shared 49、web 120 全绿（5d7d7cf3b）。
- 功能矩阵 docs/dev/vue-migration-feature-gaps.md：78 行（53 implemented / 9 missing / 10 retired / 6 待复核）。

### 未完成（下一步）
1. Phase 3：apps/jbrowse 外壳改 Vue（main.ts/App.vue/provider + GenomeBrowser + 复用 bridge.ts/deep-link.ts），需加 vue/@vitejs/plugin-vue 依赖并重算 lockfile；iframe 契约逐字节保留。
2. D/E：退役 packages/motion 与 packages/i18n React 适配器；移除 react/react-dom/react-i18next/@tanstack/react-query/lucide-react/@jbrowse/react-*/@vitejs/plugin-react；重算 lockfile。
3. F：功能矩阵 9 项 missing（管理端导入 studio、真实 Dashboard 指标、新闻双语编辑/预览/回收站等）。
4. 门户 E2E 对新浏览器对齐；/jbrowse-data 在 dev/E2E 的可得性。

### 约束与踩坑
- pnpm 状态目录（~/.local/share/pnpm）在 workspace-write 下只读：运行 pnpm 需一次性 danger-full-access 提权。
- @gmod 无离线 BigWig/BigBed writer：二者仅归一化单测，字节级 span 断言需外部生成器。
- 坐标：genome-data 为 0-based half-open，genome-view-model 为 1-based inclusive，换算只在深链/桥接边界。


## [20:45] 完成: 零 React 全线迁移（外壳 + 视觉对等 + 消融 + 退役）

- **jbrowse Vue 外壳**（子代理 6841671c，协调者复跑）：App.vue/AppHeader/AppFooter/Loading/Error + main.ts + i18n.ts；复刻 React 布局与 Tailwind 类；GenomeBrowser + /tracks/jbrowse-config + UriFileProvider；bridge/深链契约保留。提交 aee71825f。
- **视觉对等**（子代理 7754f972）：10 组件 token 对齐 + docs/dev/genome-view-visual-parity.md。提交 ad92b3678。
- **消融**（子代理 9b83eb1f）：11 场景 + docs/dev/genome-browser-ablation-report.md；发现 abort 缺陷 → 协调者修复（b608c16db、ffc4e7e1c），现 11 PASS/0 FAIL/0 GAP。
- **React 退役**（f5250e584）：删除 packages/motion、packages/i18n；jbrowse 仅 vue/genome-* 依赖；移除 React catalog/overrides、eslint-plugin-react-hooks；Dockerfile/CI/治理契约改指 i18n-core。
- **验证**: pnpm --frozen-lockfile OK；python contracts 125 passed；framework-neutral clean；jbrowse vue-tsc + vite build + 24 node:test；genome-data 87、genome-view 70 tests 全绿。
- **残留**: pnpm-lock 仍含 @tanstack/charts 的 react/react-dom/react-is 可选 peer 解析（无第一方 import）；干净重算 lockfile 需联网（pnpm 自校验平台二进制），已记录。


## [21:15] 清理: 残留 React 代码与配置 + Dockerfile 修复

- **代码/配置清理**（2c00c87f1）：`apps/jbrowse/tsconfig.json` 去掉 `jsx: react-jsx`→`preserve`；`apps/jbrowse/src/config.ts` 删除无消费者的 `buildJBrowseTheme`、`TRACK_CATEGORIES`/`TrackCategory` 与 default export（`buildJBrowseConfig`/`buildTrixAdapter` 保留，后者被内部调用）；`default-renderers.ts` 删除未用的 `trackRenderers` 聚合与四个失效 import；`knip.json` 删除全部 React/tiptap/router/testing-library 死条目；`docs/wiki/applications.md` 34→35；`e2e/README.md` React→Vue。
- **Dockerfile 修复**（7fbaf9157）：`apps/jbrowse/Dockerfile` 仍在 COPY 已删除的 `packages/i18n`/`packages/motion`（镜像必失败）→ 改为复制当前工作区包（i18n-core/query-keys/charts/ui-vue/genome-view-model/genome-data/genome-view）。
- **契约收紧**：`test_platform_delivery_contracts.py` 的「禁止 copy packages/ui」断言原为子串匹配，会误伤合法的 `packages/ui-vue`；改为匹配 `packages/ui/`。
- **验证**: jbrowse vue-tsc+vite build+24 node:test；genome-view vue-tsc+70 tests+eslint；python contracts **125 passed**；第一方 React import 0。
- **未完成（本轮尝试失败）**: 重算 lockfile 以清除 `@tanstack/charts` 的可选 React peer（react/react-dom/react-is，35 行）。离线重算被 pnpm 自校验平台二进制阻断；在线重算（registry 200 可达）在提权审批等待中超过 wall-clock。命令：在可联网环境执行 `pnpm install`（建议先加 `autoInstallPeers: false`）后 `pnpm install --frozen-lockfile`。
- **仍缺的守卫**: `packages/motion/motion-policy-contract.test.mjs` 随包删除，其「禁 gsap/lenis」不变量未替代。


## [21:35] 完成: 4 个收尾子代理全部合并

- **bf7aa7b62** 恢复 motion 守卫 + 文档对账（Agent 3）：`scripts/test_motion_policy.py` 接入 smoke contracts；`applications.md` 14→15 路由、`/imports` 行；`plan.md` 追加 2026-09-26 更正。
- **5e06276c4** Vue JBrowse E2E（Agent 4）：`e2e/tests/jbrowse-browser.spec.ts` + `playwright-jbrowse.config.ts`；离线真实运行 **4 passed / 1 skipped**。
- **0ec59f674** 浏览器收尾（Agent 2）：`AssemblyRefNameLoader` 从 .fai 填充完整 `refNames`；基因 ID 搜索（API 优先 + assembly-scoped Trix）；LocusSearch 状态反馈。genome-data **98**、genome-view **73**、jbrowse **33** tests。
- **a6b8c1353** 管理端路由对等（Agent 1）：9 条 legacy 路由 → 真实/显式不可用；新增 `StaticPagesView`/`ContentLegacyMigrationView`/`AnalyticsSettingsView`、`adminContentApi`/`getAdminAnalyticsSummary`；admin **63**、api-client **129** tests；visible-i18n OK；locale parity OK。

- **合并后全量复核**：smoke contracts **PASS**；admin-content-architecture / web-query-keys / page-registry 均 OK；admin build OK；第一方 React import 0。
- **功能矩阵**：`docs/dev/vue-migration-feature-gaps.md` 更新为 global 62 implemented / 1 documented-unavailable / 0 missing / 9 retired / 6 待复核；admin 功能路由 15→19。
- **仍未完成**：lockfile 的 `@tanstack/charts` 可选 React peer（需提权 pnpm install）；live 部署态验证（CSS/CSP/SW/子路径、P0-06b Kind、P1-08 CI E2E、G10/G12）；BigWig/BigBed 离线 fixture；AlignmentsTrack；真实 Dashboard 指标/新闻预览回收站。


## [21:40] 完成: lockfile React peer 彻底清除（联网重算）

- **背景**: 之前离线重算被 pnpm 自校验阻断、在线重算在提权审批等待中超过 wall-clock。改为**后台提权作业**后 42.5s 完成。
- **改动**: `pnpm-workspace.yaml` 加 `autoInstallPeers: false`；删除并联网重算 `pnpm-lock.yaml`。`react`/`react-dom`/`react-is` 已从安装图与 node_modules 移除；lockfile 中剩余 19 处 “react” 仅为 `@tanstack/charts` 自身的可选 peer 声明与 Vue 的 `@vue/reactivity` 名称。
- **副作用**: 全量重解析在 semver 范围内顺带升级了根 dev 工具：eslint 10.9→10.11、turbo 2.10.11→2.11.4、globals 17.11→17.12、typescript-eslint 8.67→8.70.1。
- **验证**: `pnpm install --frozen-lockfile` OK；smoke contracts PASS；根 eslint 全仓 sweep 0 error；逐包测试全绿——web 120、admin 63、jbrowse 33、api-client 129、shared 49、genome-data 98、genome-view 73、genome-view-model 23、charts 2、query-keys 10、ui-vue 4、i18n-core 7（合计约 711）。
- **提交**: 5808f0391。


## [22:15] 完成: 依赖治理审计 16/16（含线上重算 lockfile）

- **清除 React peer（联网）**: `pnpm-workspace.yaml` 加 `autoInstallPeers: false`，后台提权作业联网重算 lockfile（42.5s）→ `react`/`react-dom`/`react-is` 从安装图与 node_modules 移除（提交 5808f0391）。副作用：根 dev 工具在 semver 内升级（eslint 10.11 / turbo 2.11.4 / globals 17.12 / typescript-eslint 8.70.1）。
- **审计首轮失败 → 修复**: knip 报 3 个未用直接依赖；pnpm dedupe 检查失败；`genome-view-model` 存在 `index.ts ↔ viewport.ts` 循环（我引入）。修复：错误类抽到 `errors.ts` 破环；删除 `genome-view` 的 `@soymutdb/genome-view-model`、`genome-data` 的 `@gmod/bgzf-filehandle`（经 indexedfasta 传递）、`apps/jbrowse` 的 `@vue/test-utils`；`pnpm dedupe`。
- **验证**: `dependency governance: passed` **16/16**（knip、deptry×3、duplicate-versions、cycles×4、licenses×4、audit×4）；genome-view 73、genome-data 98、jbrowse 33 tests + tsc 干净；smoke contracts PASS。提交 177d36ccc。
- **并行注意**: 另一 worker 正在写 `apps/api/tests/test_ablation_*`、`apps/web/src/ablation/`、`docs/dev/ablation/2026-09-26/`（mtime 21:58–22:13，引用 HEAD 8e78116fd）。这些不是本会话产出，保持 untracked、未纳入提交。
- **仍缺**: live 部署态验证（CSS/CSP/SW/子路径、P0-06b Kind、P1-08 CI E2E、G10/G12）；BigWig/BigBed 离线 fixture；AlignmentsTrack；真实 Dashboard 指标/新闻预览回收站。


## [22:20] 全项目消融实验战役（协调者 + 6 子代理 @ nwafu/DeepSeek-V4.1-Flash）

**产出**：`docs/dev/ablation/2026-09-26/`（PLAN.md + README.md 汇总 + 6 份分报告），51 场景 → GUARD-ACTIVE 43 / GUARD-INERT 5 / GAP 6。

**6 个 GAP（全部 P1，均有复现命令）**：
1. ASM-04 跨版本 crosswalk 未接线 — `apps/api/app/services/search_service.py:28` 未 import `GeneCrosswalk`，`MatchType.CROSS_VERSION` 零生产者；增删 crosswalk 行搜索结果无差异。
2. UI-02 internal 双 id 前端缺失 — `packages/api-client/src/search.ts:5-17`、`apps/web/src/views/SearchView.vue:290-302`；后端契约已在 `generated/openapi.d.ts`。
3. 联邦搜索缓存键缺 release/assembly/site_variant — `apps/api/app/search/cache.py:26-34`，调用点 `search/aggregator.py:69`、`api/v1/search.py:183`。
4. E2E 无实体详情页 spec。
5. E2E JBrowse 深链无条件 `test.skip` — `e2e/tests/genes.spec.ts:55`。
6. E2E 内部站无 config/spec — 挂 internal 制品跑公开套件 8 failed/1 passed（`No route for /soymutdb-next/login`，internal base 为 `/`）。

**INERT/覆盖缺口**：external/index.html 缺失不被拦；哨兵集合过窄（`internal.soymutdb.invalid` 可放行）；空目录名哨兵不查；`not.toContain("internal_id")` 弱断言。

**协调者证据**：契约锚点 36 passed（abl_coord）；W1 13 passed；W2 6 passed + GAP 支 1 failed；W3 47+9 passed；W4 18 passed；W5 harness 4/4 GUARD-ACTIVE + CH DDL 12 passed/1 skipped；W6 双站扫描 exit 0 + isolation 单测 6 OK。生产源码零持久改动。

**复现基础设施**：PostgreSQL 16 后台作业 @127.0.0.1:55432（每个工作流独立库 abl_<domain>）；`.validation/ablation/` 下为 scratch harness 与日志；pnpm 在沙箱需 `PNPM_HOME/XDG_*` 指向工作区（`.validation/ablation/artifact/pnpmenv.sh`）。

## [22:36] Vue 迁移收尾：对齐/文档/E2E/搜索完整性 + 独立复核（协调者 + 10 子代理 @ nwafu/DeepSeek-V4.1-Flash）

**提交（10）**：
- `0fae5ceb6` genome-data BAM 对齐读取器 + 真实 BAM/BAI/BigWig fixture
- `64631e6d0` 文档对齐 Vue-only（门户 35 路由 / 管理端 19 功能路由；motion、i18n 记为已移除）
- `202ae7f92` e2e：admin console + portal embed
- `4959405d1` web：门户 JBrowse iframe 桥加固（canonical origin、ready 握手、双 id 卫生）
- `5b32032aa` admin：真实 Dashboard 指标 + 新闻双语预览/软删回收站 + i18n（含 browser.chromosome）
- `11cc6de91` genome-view：BAM 对齐端到端渲染 + jbrowse BamAdapter 轨道（默认不加载）
- `2836aa4de` e2e：实体详情、JBrowse 深链真实断言、内部站 config/spec
- `362e7a30b` web：搜索双身份按站点变体渲染（public_id/internal_id）
- `f5a144f6a` api：搜索缓存键绑定完整生物作用域 + cross_version 链接
- `df16b12c3` genome-data：reader open 缓存失败后可重试（OpenCache）

**验证**：全量第一方测试 **698 passed**（web 147、admin 82、api-client 137、genome-data 121、genome-view 80、gvm 23、shared 49、charts 2、query-keys 10、ui-vue 4、i18n-core 7、jbrowse node:test 36）；第一方 React import 0、manifest `react` 0。依赖治理 **16/16 passed** —— 必须 `source .validation/ablation/artifact/pnpmenv.sh` 并设 `VITE_API_BASE_URL` 及 `UV_CACHE_DIR`/`UV_TOOL_DIR`/`UV_TOOL_BIN_DIR`/`UV_PYTHON_INSTALL_DIR` 指向工作区，否则 knip/deptry/pip-audit 因 `~/.cache`、`~/.local/share/uv` 只读而误报失败。

**重要发现并修复**：全部 reader 曾用 `??=` 缓存 open promise，open 失败被永久缓存，导致 TrackRenderer 的 Retry 对“文件缺失/不可达”永远无效；`OpenCache` 在拒绝时仅在 `pending` 仍指向同一 promise 时清空，8 处缓存点全部替换并逐 reader 加重试测试。

**并发**：另一 workstream（消融/优化）同时改 `packages/api-client/src/search.ts`、`apps/api/app/{search,services}`、`apps/web/src/ablation/**`、`scripts/*isolation*`、`docs/dev/ablation/**`。已协调让本会话子代理让出 api-client 搜索文件；其已完成且经 tsc/测试验证的部分随 `362e7a30b`/`f5a144f6a` 带入。该 stream 在提交后仍在继续修改上述区域。

**仍缺/未验证**：live 部署态验证（CSS/CSP/SW/子路径、P0-06b、P1-08 CI E2E、G10/G12）；实体详情/内部站的 live 双 origin 断言；SearchView 到 `internalSearch` 的运行时接线（搜索仍走公开 `/search`，internal_id 暂无数据来源）；BigBed 离线 fixture（interval 重试测试内嵌 906B bigBed 绕过）。

## [23:05] 消融 GAP 优化 Wave（5 子代理）

**关闭 11/11**：G1 跨版本 crosswalk → `SearchResultItem.cross_version` + `CrossVersionLink`（`search_service._resolve_cross_version_links`，双向、release 作用域、不加结果行）；G2 → `internalSearch()` + 内站双 id UI/复制控件；G3 → `SearchCache.make_key` 纳入 site_variant/release/assembly/filters（全 None 字节等同旧键）；I3/I5/I4 → 制品守卫三项；G4/G5/G6 → entity-detail spec、JBrowse 深链解 skip、internal 站 config+spec。

**复核证据**：A 47 passed、B 64 passed、C 29 passed、D 11 tests OK、E 30/1 skip+3+3 均 exit 0、消融回归 43 passed、广域 API 155 passed、build/scan/verify exit 0。

**未提交（有被并发会话覆盖风险）**：`apps/api/app/{services/search_service.py,schemas?..}`、`app/search/cache.py`、`app/api/v1/search.py`、`apps/web/src/views/SearchView.vue`、`scripts/*` 三个、`e2e/*` 六个 + 新增测试/报告。`packages/api-client/src/search.ts` 已被并发会话提交（362e7a30b）。**建议尽快提交定稿。**


## [00:30] 交付: Vue/React 视觉与功能对等修复（协调者 + 6 子代理 @ nwafu）

**用户诉求**: 「Vue 的 UI 和 React 还是不一样、很多功能用不了、样式和布局没有同步、很丑」。

**8 条根因（均有实测证据，详见 `docs/dev/vue-parity/README.md`）**
R1 dev `/api` 代理指向未启动的 8010（端口 8000 是别的项目）；R2 查询客户端退回 TanStack 默认（staleTime 0 / 重试 3）；R3 首页丢了 AntD 组件层与 WebGL2 流体渐变 Hero；R4 11 条路由完全没有页眉/导航/页脚（React 把 shell 放根路由，Vue 改成每 view 自己包）；R5 i18n 缺 20+ 被引用 key（`/help` 直接显示 `help.title`）；R6 `ui-vue` 把 `colorPrimary` 设成 oklch → tinycolor 解析失败，全站 antd 主按钮近黑色；R7 无错误边界且 router 全量静态 import → 任一文件报错即整站白屏；R8 `trendAreaChart` 日期字符串绑 `scaleLinear` → `/analytics` 整页崩溃。

**已修**: 上述 8 条全部修复；另补暗色主题接线（`lib/theme.ts` + PortalLayout ConfigProvider 同源）、⌘K 命令面板（移植 React）、会话恢复/登出回跳/遗留令牌清理、i18n 字典收口（zh/en 各 1650 key 完全对等）、visible-i18n 门禁白名单、管理端 44 路由对等（+3924/−2565）。

**验证（全部实跑）**: web typecheck 0 错误 · lint 0 · **37 files / 165 tests** · build exit 0；admin typecheck/lint/build exit 0 · **22 files / 98 tests**；charts 4 · ui-vue 5 · i18n-core 7 tests；visible-i18n OK；Playwright 33 路由 **missingShell=0**、首页 `canvas=4`/31 链接（与线上 React 一致）、暗色切换、⌘K 面板、`/analytics` 不崩。

**本地数据**: PostgreSQL 16 @127.0.0.1:55432（`.validation/postgres16`）；`soymutdb_performance` 已迁 alembic head 0042（25 万基因），并补 published release + `active_release.release_id` + `assemblies.release_id`；API 后台作业跑在 8010（日志 `.validation/vue-parity/api.log`）。ClickHouse 未起 → `/api/v1/variants` 503 属设计上的 fail-closed。

**仍未完成（审计 P1/P2）**: 门户 service worker 未注册；通知中心无客户端；`/analyses` 缺研究者门禁；`/search/suggest` 无消费者；`dist/` 直接发布缺 `404.html`；`/antd-pilot` 路由缺失；motion/view-transition；管理端后端聚合端点（`/releases/current`、dashboard storage_growth、审计聚合/导出、导入上传/校验、媒体上传）。**未验证**: 详情页成功态真机渲染、live 部署态（CSS/CSP/SW/子路径）、BigWig/BigBed 离线 fixture。

**并发风险**: 另一 workstream 同时改 `apps/api/**`、`apps/web/src/views/SearchView.vue`、`scripts/*isolation*`、`e2e/*` 与本文件；SearchView 是双写者，本轮改动均为局部 edit 且保留其 OPT-05/06 逻辑与全部 testid。**建议尽快把本轮改动提交定稿。**


## [01:15] 交付: OPT2 第二轮优化（协调者 + 5 子代理 @ nwafu/DeepSeek-V4.1-Flash）

**清单/报告**: `docs/dev/opt2/OPT2-CHECKLIST.md`（8 项）、`docs/dev/opt2/OPT2-REPORT.md`（总表 + 复跑矩阵 + 未验证项 + 回滚点）、5 份分报告 `opt2-{a..e}-*.md`。

**8/8 完成**: 联邦搜索真 HTTP 层、release 作用域串味修复（端点原本没有 release_id 参数）、触达文件 ruff 清零、internal E2E 真实输入、verifier 单命令、消融草稿→`apps/web/src/regression/`、Service Worker 注册、研究者门禁。

**协调者新发现并修复（不在清单，按影响排序）**
1. **P0 空绑定**：`antdv-next@1.5.4` 的 `Input` 只有 `value/update:value`（类型面 `modelValue` 计数 0）。`SearchView.vue:312`、`MutantsListView.vue:85` 的裸 `v-model` 使**全局搜索框与诱变剂筛选框打字不进状态**（用户「功能很多用不了」的直接来源）。已改 `v-model:value`，浏览器实测通过。
2. **7 个测试 stub 说谎**（声明 `modelValue`）→ 165 个绿灯测试放过了上面的 P0。已改为真实契约，并加静态守卫 `src/regression/antdv-input-binding.test.ts`。
3. **`check:contract` 此前已是红灯**（generated client 落后 576 行）→ `generate:api-client` 重生成后 EXIT=0；备份 `.validation/opt2/contract-backup/`。
4. **SW 命名空间未随变体分离**（DB-CORE-5）→ 构建期注入 `__SW_NAMESPACE__`，运行时缓存与清理前缀按变体；新增 `src/regression/service-worker-namespace.test.ts`。
5. **撤回两条假警报**：`dist/404.html`（nginx `try_files` + Cloudflare Pages 内置兜底**要求**顶层无 404.html）、`/search/suggest`（React 基线亦零消费者）。

**复跑证据（全部 exit 0）**: api-client 26/139 · web 46/201 · admin 22/98 · charts 4 · ui-vue 5 · i18n-core 7 · API 消融+优化 61 · 联邦契约 42 · internal E2E 3 passed · `verify-site-variant-artifacts.sh`（无 PREBUILT）EXIT=0 · `check:contract` EXIT=0 · web+admin typecheck/lint 0 · visible-i18n OK · `dist/{external,internal}/sw.js` 命名为 `external`/`internal`。

**未验证**: 真 Redis / 真外网 provider（本机无 redis-server）；SW 子路径与版本轮换、Firefox/Safari；真实研究者 JWT 会话（用路由拦截 + 10 角色单测替代）；匿名深链 `/analyses` 落 `/login`（与 React 一致，空态只对已认证非研究者可见）。**有意偏离 React**: `isResearcher` 按服务端授权表放宽（React 的 `{researcher,administrator}` 会误拒 curator/data_manager）。

**操作顺序约束**: `pnpm --filter @soymutdb/web build` 的 `emptyOutDir` 会清空 `dist/{external,internal}` → internal E2E 报 ENOENT。正确顺序：先普通 build，**最后**跑双站 verifier。

**未提交**: 三轮（消融 / 优化 / OPT2）改动都在工作树（`git status` 数百项），`SearchView.vue`、`scripts/*`、`e2e/*` 有被并发会话覆盖的历史，**建议尽快提交定稿**。


## [01:50] 交付: OPT3 第三轮（协调者 + 2 子代理 @ nwafu）—— React 对等收口

**报告**: `docs/dev/opt3/OPT3-REPORT.md` + `opt3-n-notifications.md` / `opt3-m-route-motion.md`。

**本轮完成**
1. **通知中心**（React `notification-bell.tsx` 对等）：api-client 三个函数 + `useNotifications` + `PortalNotificationBell.vue` + 页眉接线；仅登录可见、30s 轮询、未读优先、类型图标、相对时间、跳转先标记已读、全部已读、完整 a11y；匿名零请求。Playwright **21/21** 断言通过。
2. **路由动效**：`lib/motion.ts`（令牌驱动、纯策略可测）+ `RevealOnMount.vue` + `installRouteMotion`（View Transitions，降级安全）+ PortalLayout keyed 包装。**发现** PortalLayout 每路由重建使内部 `<Transition>` 惰性，故改用 keyed RevealOnMount。reduced 下完全静止。
3. **E2E 假警报根因**：重定向 `XDG_CACHE_HOME` 后 Playwright 找不到浏览器 → 整套 3 条同时 launch 失败。修法 `PLAYWRIGHT_BROWSERS_PATH=$HOME/.cache/ms-playwright`，已写入 `e2e/README.md` 与 `.validation/opt3/verify.sh`。
4. **`/antd-pilot` 记为有意退役**（React 无导航入口、无 spec，属迁移试点页）。

**复跑证据（全 exit 0）**: web 50/251 · api-client 27/146 · admin 22/98 · charts 4 · ui-vue 5 · i18n-core 7 · typecheck/lint 0 · visible-i18n OK · motion guard OK · build OK · 33 路由 missingShell=0 · 双站 verifier EXIT=0 · internal E2E 3 passed · SW 命名空间 external/internal · i18n zh/en 各 1656 key 对等。

**仍开：最后一项实质缺口 = CMS 内容（审计 GAP-03/04）**。实测 `GET /api/v1/site/content?variant=external` 返回 **131 键、值全是英文注册默认值**；"服务端值胜出"的接法会把中文门户 Hero/工具卡文案整体变英文（React `useSiteContent` 契约即有此隐患，不应照抄）。两条设计需拍板：① 接口加 `only_overrides=true`（推荐，加法式契约变更 + 重生成 `generated/openapi.d.ts`，流程已跑通）② 前端镜像 84 键默认值表并加漂移守卫。另需产品决策：PageDefinition 整页渲染器是否恢复，否则应像 `/antd-pilot` 一样明确记为有意退役（ADR-0009 同类处理）。

**未提交**: 四轮（消融 / 优化 / OPT2 / OPT3）改动全在工作树，建议尽快定稿提交。


## [03:25] 交付: OPT4 第四轮 —— CMS 内容能力 + P0 匿名跳转修复（goal round 2）

**报告**: `docs/dev/opt4/OPT4-REPORT.md` + `opt4-site-content.md`。

**本轮完成**
1. **接口（加法式）** `GET /api/v1/site/content?only_overrides=true` → 只返回有存储行的键。动机：该接口原本对每个注册键都返回**英文注册默认值**（131 键），双语门户若"服务端值胜出"会把中文文案顶成英文。测试 5 例（真实 PG+ASGI），API 回归 87 passed。
2. **客户端** `getSiteContent(variant,{ onlyOverrides })`；契约重生成后 `check:contract` EXIT=0；api-client 149 passed。
3. **门户接线（子代理）** `useSiteContent()` + HomeView(hero.*/tool.*) + PortalHeader(nav.*) 共 35 键，`覆盖值 ?? 当前语言 i18n`；web 52 files/272 tests、typecheck/lint/build 全绿；浏览器断言含"无覆盖时中文不变"。
4. **GAP-03 收口** PageDefinition 只取 `resource_cards` 一个节点（**事实更正**：不是整页渲染器，React `routes/index.tsx` 用 `findResourceCards(definition.root)`）；新增 `lib/page-definition.ts` + `components/home/ResourceCardsNode.vue`；真实种子数据端到端渲染 CMS 卡带，404 回退内置带。
5. **P0 修复**：匿名访问任何页面会被硬跳 `/login`（OPT3 铃铛让共享页眉每页都探 `/auth/me` → 401 → refresh 401 → emitLogout → onAuthLogout）。修法：`useCurrentUser` 探针**会话门控**（main.ts 在 restoreSession 成功后置真、LoginView 登录成功置真）；匿名零探测。**验证盲区同步修复**：路由审计等待 600ms→2500ms。

**复跑证据（全 exit 0）**: API 87 · api-client 149 · web 52/272 · admin 98 · typecheck/lint 0 · visible-i18n OK · motion guard OK · build OK（27 documents）· 33 路由 missingShell=0 且无异常跳转 · 双站 verifier EXIT=0 · internal E2E 3 passed · SW 命名空间 external/internal。

**仍开（goal 继续 active）**: 剩余 **96 个 `content.*` 键**未接线（React 在 header + 12 路由消费；机制已就绪，属增量覆盖，清单在 `opt4-site-content.md`）；管理端后端聚合端点；live 部署态；真 Redis；SW 子路径/跨浏览器；详情页成功态。五轮改动仍全部未提交，**建议尽快定稿**。


## [05:45] 交付: OPT5 第五轮 —— content.* 接线收口（goal round 3）

**报告**: `docs/dev/opt5/OPT5-REPORT.md` + `opt5-a-pages.md` / `opt5-b-help-search.md`。

**结果**：React 真正消费过的注册 `content.*` 键**全部接线**（唯一例外 `blast.hitGeneId`，需重排 Blast 命中表列集）。覆盖率脚本 `.validation/opt5/content-coverage.py` 可复跑：**131 注册 / 105 已接 / 25 个 React 从未引用（非缺口）/ ACTION=1**。
- 接线：Blast 12、Downloads 2、GenesList 2、Variants 2、Help 15（FAQ `faq{i}`↔`q{i}` 一基映射）、Guide 2、SearchGenes 15、SearchLocation 15；HomeView `hero.image`（安全过滤 + 3 测试）。
- i18n：补 `help.q6.q/.a`、`search.genes.resultsRetry`、`search.location.resultsRetry`（此前无覆盖会显示原始 key）→ zh/en 各 1660 key 对等、0 引用缺失。

**协调者纠正（含我自己的错）**
1. **我的键表是错的**：提取正则只匹配小写，漏掉 47 个 camelCase 键 → 注册键实为 **131**（不是 84），Blast/Search 多键被错误列为"跳过"。已重新定界并叫回子代理补完；提取固化脚本。
2. Blast 第 5 列（渲染 `bit_score`）被标成 `blast.hitGeneId` → 改回 `t("blast.hitScore")`；GuideView h1 被换成 `nav.guide` 并丢掉 API 标题 → 恢复 `<h1>{page.title_en}`，`nav.guide` 回到 React 的徽标位。
3. 子代理发现的真 bug（保留）：`BlastView` 模板 ref 未解包 → 命中表永不渲染；改 `toValue(...)`。

**验证（全 exit 0）**: web 55 files/304 tests · typecheck 0 · lint 0 · visible-i18n OK · build OK · api-client 149 · admin 98 · 浏览器 4 处覆盖值渲染正确且无覆盖时中文不变 · 双站 verifier EXIT=0 · internal E2E 3 passed。

**下一轮（唯一剩余 frontend parity 项）**：Blast 命中表列集与 React 不同 → `blast.hitGeneId` 无可落列。默认方案：**新增第 6 列「基因ID」，用已有 `hit.subject_id` 链到 `/search/genes?q=`**（纯加法，不删 Vue 现有 score/alignment 列，无需产品决策）。

**仍未提交**：五轮改动全在工作树（180+ 项）——**强烈建议先定稿提交再继续**。


## [06:15] 交付: goal round 4 —— frontend parity 收口（最后一条差异闭合）

**改动**：`apps/web/src/views/BlastView.vue` 加法式补齐 React 命中表的两列 —— 「基因ID」（`blast.hitGeneId`，`compactGeneId(subject_id,18)` → `/search/genes?q=…&run=true`）与「JBrowse 2」（`subject_id:start..end` + `assemblyForJob` 反查的 assembly）；Vue 原有 score/alignment 列保留。测试 `BlastView.test.ts` 同步（6 passed）。

**覆盖率**：`.validation/opt5/content-coverage.py` → **131 注册 / 106 已接 / ACTION=0**。React 真正消费过的注册 `content.*` 键 **100% 已接线**；剩余 25 个是 React 从未引用的键（非对等缺口）。

**复跑（全 exit 0）**：web 55 files / 304 tests · typecheck 0 · lint 0 · visible-i18n OK · build OK · api-client 149 · admin 98 · charts 4 · ui-vue 5 · i18n-core 7 · 双站 verifier EXIT=0 · internal E2E 3 passed · 浏览器实测新列 href 与覆盖文案正确。

**目标判定**：objective 的「视觉/布局退化修复 + 补齐 React 已消费的不可用功能 + 以基线源码验收 + typecheck/test/build 验证」均已达成并留证。剩余项全部**不属于前端对等**：React 的 assembly/输入序列ID 两列（可选增强）、25 个 React 未消费的已注册键、管理端后端聚合端点（后端自有）、真 Redis/live 部署/SW 子路径等环境验证、以及 **5 轮未提交改动（建议先定稿提交）**。

## [2026-09-29] 交付: Vue 完全退役 + 两项查询收口 + 文档对齐

**背景**：用户指令「去除 VUE 技术路线，VUE 已经被放弃了」「目前制作好这两个功能（基因ID、物理位置），其他功能保留入口」「按设计文档执行」。

**改动**
- **Vue 完全退役**：删除 231 个文件 —— 106 个 `.vue`、Vue 入口与运行时源码（`main.ts`/`App.vue`/`router/index.ts`/`views/`/`stores/`/Vue 版 `lib/*.ts`/Vue 版 `regression/*.test.ts`）、`packages/ui-vue`、`packages/genome-view`；清理 `apps/{web,admin}` 的 Vue devDependencies、`pnpm-workspace.yaml` 的 catalog 条目 + `allowBuilds.vue-demi` + `minimumReleaseAgeExclude` 的 vue-query、锁文件条目。按设计 D3 保留框架无关的 `packages/genome-view-model`、`packages/genome-data`、`packages/charts`。新建 `scripts/check-vue-retirement.mjs`（源码/manifest/catalog/锁文件四面）并接入 `verify-frontend-artifacts.sh`；`check-react-entry-graph.test.mjs` 负对照改为合成 fixture。
- **两项查询收口**：新建 `apps/web/src/lib/search-assembly.ts`（深链 assembly 不可判定时不回退默认版本）+ 安全整数坐标校验 + JBrowse 深链携带 `release`；`genes.tsx`/`location.tsx` 结果表 assembly 列改用提交快照。回归 `search-assembly.test.ts`、`routes/search/tool-pages.test.tsx`（7 tests）。
- **首页对齐设计**：移除 hero 搜索区（`public-web-layout:45`，此前文档声称已移除但代码仍渲染 `role="search"`）、入口顺序改为 Gene ID/Physical Location/JBrowse 2/BLAST/Primer Design、前两项为箭头主入口其余保留卡片、双语守卫 3 处 `defaultValue` 修复。
- **文档修订**：`docs/3.9升级优化文档.md` 7 处（§2 Vue 退役与覆盖缺口、§2 模块数、§4.1 顺序与 hero、§4.2 两条 assembly 契约、§9 第 10 条门禁、§10 `W5`→`W4` 与 i18n 范围 5→36、§13 registry 滞后）。

**验证（全 exit 0）**：三端 `typecheck`；web 19 files/81 tests；admin 3 files/19 tests；`check-react-entry-graph.mjs` PASS（web 96 / admin 21 / jbrowse 9）；`check-vue-retirement.mjs` PASS；`test_platform_delivery_contracts.py` 37 passed；`scripts.test_site_artifact_isolation` 11 passed；双语守卫 antd-home 转绿（全仓 37→36）。

**未完成/阻塞**
- 制品重建受 `apps/web/scripts/build-sites.ts:48` 裸 `pnpm` 阻碍（PATH 中 pnpm 为 v11.24.0 且报 `unable to open database file`）；**已用 PATH shim（`#!/bin/sh\nexec corepack pnpm "$@"`）绕过并成功重建双站制品**。`max build` 单独执行缺 variant 环境变量，必须经 `build-sites.ts`。
- registry 滞后：`.npmrc` 指向 npmmirror（`@tanstack/react-query` 最新 5.99.2），重新解析锁文件须覆盖 `--registry=https://registry.npmjs.org/`。
- **e2e 实测：4 passed / 9 failed → 25 passed / 5 failed / 1 skipped**（全 suite）。关键根因是 **api-client 在 workspace 包内拿不到注入的 `VITE_API_BASE_URL`，回落到相对 `/api/v1`**，请求落到 origin 根后被 `static-server.mjs` 的路径守卫 404；已在 static-server 增加 API 路径归一化。同时实现侧补齐了 e2e 期望却从未存在的 testid（判据：`git show HEAD:apps/web/src/routes/search/genes.tsx | grep -c data-testid` = 0）。**剩余 5 项**：`genes.spec.ts:46`（深链未携带 release → `/browser` 判缺上下文）、`search.spec.ts:82`（antd Select 点击超时）、`public-login.spec.ts` 3 项。
- **构建需限制并发**：`build-sites.ts` 在本机会偶发 `failed to create new OS thread (errno=11)`（线程耗尽），需 `GOMAXPROCS=2 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=2`（PLAN.md:40 已记录同类）。e2e 制品构建命令：`SOYMUTDB_EXTERNAL_BASE_URL=/soymutdb-next SOYMUTDB_EXTERNAL_API_URL=http://localhost:4173/soymutdb-next/api/v1 SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED=true SOYMUTDB_RELEASE_ID=7`。
- **`csp.ts`/`config.ts` 的 http origin 判定已统一**（原 `csp.ts` 只认 `NODE_ENV=development`），这是文档 §13 记录的构建链不一致。
- 契约覆盖缺口（随 Vue 退役）：admin 会话、web 动效可访问性、web 页面定义 href 安全校验在 React 侧无等价测试。
- 15 个 API 测试依赖 testcontainers — 无 Docker，SKIPPED（不等于 PASS）。

## [2026-10-01] 定稿: 真实情况核对 + admin Pro 迁移设计/计划 + 前端守卫

**详见 `.ai-memory/20261001/daily.md`。要点**

- 修 6 处长期契约漂移：API `test_expression`（release fail-closed 后未更新，6 failed）、`test_gwas_api`（路由签名）、`conftest`（角色种子幂等）、
  `test_ablation_sra_no_fabrication`（漏挂 `offline` fixture → 实际联网，「只在断网时才生效的消融」）、`query-keys` 测试（federated）、`charts` 回退态 a11y。
- 新增 3 个前端守卫：内容管理 URL 真源功能测试、导航可达性消融（Vue 退役时丢失）、antd 门面导出完整性消融（补 `@ant-design/cli usage` 不解析门面层的盲区）。
  admin 单测 3/19 → 6/41。
- 按官方 `ant-design-pro` `table-list`（预览 `/admin/sub-page`）写 `docs/superpowers/specs/2026-10-01-admin-pro-migration-design.md` +
  `docs/aegis/plans/2026-10-01-admin-pro-migration.md`（A1–A6），登记进 `docs/aegis/INDEX.md`。
- 纠正旧口径：不是「11 页裸 Table、ProTable 0 处」，而是 4 页已在 ProTable 适配器上、6 页仍是裸 `Table`；`ProDescriptions`/`ProCard` 全仓 0 处。
- `docs/dev/project-status.md` 重写为 2026-10-01 实跑版本（原版还写着「三端均为 Vue 3」）。
- 红/未验证：`check_visible_i18n_react.mjs` exit 1（39 文件）；API 全量 pytest 本机 OOM（EXIT=137 @ ~47
## [2026-10-01] 定稿: 真实情况核对 + admin Pro 迁移设计/计划 + 前端守卫

**详见 `.ai-memory/20261001/daily.md`。要点**

- 修 6 处长期契约漂移：API `test_expression`（release fail-closed 后未更新，6 failed）、`test_gwas_api`（路由签名）、`conftest`（角色种子幂等）、
  `test_ablation_sra_no_fabrication`（漏挂 `offline` fixture，实际联网，"只在断网时才生效的消融"）、`query-keys` 测试（federated）、`charts` 回退态 a11y。
- 新增 3 个前端守卫：内容管理 URL 真源功能测试、导航可达性消融（Vue 退役时丢失）、antd 门面导出完整性消融（补 `@ant-design/cli usage` 不解析门面层的盲区）。
  admin 单测 3/19 -> 6/41。
- 按官方 `ant-design-pro` `table-list`（预览 `/admin/sub-page`）写 `docs/superpowers/specs/2026-10-01-admin-pro-migration-design.md` +
  `docs/aegis/plans/2026-10-01-admin-pro-migration.md`（A1-A6），登记进 `docs/aegis/INDEX.md`。
- 纠正旧口径：不是「11 页裸 Table、ProTable 0 处」，而是 4 页已在 ProTable 适配器上、6 页仍是裸 `Table`；`ProDescriptions`/`ProCard` 全仓 0 处。
- `docs/dev/project-status.md` 重写为 2026-10-01 实跑版本（原版还写着「三端均为 Vue 3」）。
- 红/未验证：`check_visible_i18n_react.mjs` exit 1（39 文件）；API 全量 pytest 本机 OOM（EXIT=137 @ 约 47%）无全量数字；无 Docker -> testcontainers SKIPPED。
- 复跑：web 20/99 · admin 6/41 · api-client 27/150 · jbrowse 40 · genome-view 43 · genome-data 121 · gvm 23 · shared 49 · charts 5 · query-keys 11 ·
  i18n-core 10 · `pytest scripts` 275 passed/1 skipped · API 消融 149 passed · admin lint+typecheck exit 0。
