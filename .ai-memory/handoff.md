# Handoff 检查点 — 2026-09-26（多 Wave 执行后）

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
