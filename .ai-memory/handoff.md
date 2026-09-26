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

