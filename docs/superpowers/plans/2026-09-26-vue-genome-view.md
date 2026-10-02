# 零 React Vue 基因组视图 — 实施计划（2026-09-26）

> **已归档（2026-10-01）**：已被现行计划取代的历史实施计划。继任：`docs/aegis/plans/` 与 `docs/aegis/INDEX.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

**Aegis Visibility:** 本计划新增两个包、重写一个应用外壳、删除跨包 React 依赖并更新 lockfile，引入新 owner 与对外契约；门户 iframe 契约必须保持，因此需要持久计划锁定边界、验证与退役路径。

**Spec:** docs/superpowers/specs/2026-09-26-vue-genome-view-design.md（已批准；本计划只覆盖其子项目 A/B/C）

**Goal:** 用 Vue 原生实现替代 @jbrowse/react-linear-genome-view，达到基线功能对等；最终全仓无 React 依赖。

**Architecture:** apps/jbrowse (Vue shell) → @soymutdb/genome-view (Vue) → @soymutdb/genome-view-model (existing) → @soymutdb/genome-data (new, @gmod readers).

**Tech Stack:** TypeScript 5.9, Vite 6, Vue 3, Pinia, Vitest, node:test, Playwright, @gmod/indexedfasta|tabix|vcf|bbi|bgzf-filehandle|trix|bam, generic-filehandle.

**Baseline / Authority Refs:**
- docs/dev/database-core-contract.md（assembly/身份/可见性，不得破坏）
- docs/dev/vue-migration-recovery-plan.md（保留 svg 资产、统一字体/设计系统）
- apps/jbrowse/src/{App.tsx,main.tsx,design-system-provider.tsx,bridge.ts,deep-link.ts,config.ts}
- packages/genome-view-model/src/index.ts
- apps/web/src/views/BrowserView.vue + @soymutdb/shared/jbrowse-bridge

**Compatibility Boundary:**
- URL：?assembly/locus/tracks/release/portalOrigin，loc 旧别名，1-based inclusive ↔ 0-based half-open。
- bridge：{source,version,type,payload}，type ∈ ready|error|locus-change|selection-change|init；origin 校验；standalone 不外发。
- 站点变体/assembly 隔离：记录必须携带 assemblyKey，不匹配即失败，不跨 assembly 合并。
- Phase 3 前 React 应用仍可回退；Phase 3 后全仓 package.json 与源码不得含 react、react-dom、react-i18next、@tanstack/react-query、lucide-react、@jbrowse/react-*。

**TDD Route:** mode=off；decision=skipped；authority=会话默认（Aegis TDD off）；test posture=每个实现任务附带 focused vitest/node:test 回归，无强制 RED/GREEN；reason=off 模式不自动路由 strict；verification=各包 test/lint/typecheck + Playwright 嵌入 E2E + pnpm install --frozen-lockfile。

**Change Necessity:** 变更必须落在源码：新数据读取能力、新 Vue 渲染与新外壳均无现成 owner 可复用（genome-view-model 只有布局数学，JBrowse React 包必须移除）。最小代码边界=新增 genome-data 与 genome-view 两个包 + 改造 apps/jbrowse。

**Ripple Signal Triage:** 触及新公共包契约、跨应用 bridge 契约、依赖与 lockfile、packages/i18n 与 packages/motion 退役 → 每个改动包必须有自身测试，契约测试守护 bridge/深链，退役任务必须同时移除依赖与消费点。

**Plan Pressure Test:** owner 明确（每包单一职责）；无重复 owner（浏览器逻辑只在新包）；验证可执行（fixtures 注入，不触网）；退役有触发点（Phase 3 对等后）。可继续。

---

## Phase 0 — 前置

### P0-1 修复 pnpm 状态目录
- **Files:** 无仓库文件（环境）
- **Purpose:** 让依赖变更可离线重算 lockfile。
- **Steps:** 将 PNPM_HOME/XDG_DATA_HOME/XDG_CACHE_HOME 指向工作区内目录后运行 pnpm --version；若仍失败，在一次性 danger-full-access 批准下运行 pnpm install --offline。
- **Verification:** pnpm --version 输出 12.x；pnpm install --offline --frozen-lockfile 成功（lockfile 未变）。
- **Outcome:** 后续新增依赖可离线安装。

### P0-2 fixture 生成脚本
- **Files:** scripts/generate-genome-fixtures.mjs（新增）、packages/genome-data/test/fixtures/**
- **Purpose:** 为数据层提供可提交的微型 bgzf/tabix/bigwig/bigbed/trix fixture。
- **Steps:** 用 Node + 现有 store 依赖程序化生成最小 fasta.gz(+fai/gzi)、vcf.gz(+tbi)、gff3.gz(+tbi)、bigwig、bigbed、trix(.ix/.ixx)。
- **Verification:** node scripts/generate-genome-fixtures.mjs 幂等；fixture 总量 < 200KB。
- **Outcome:** 数据层测试无需网络。

## Phase 1 — @soymutdb/genome-data（子项目 A）

### A1 包脚手架
- **Files:** packages/genome-data/{package.json,tsconfig.json,vitest.config.ts,src/index.ts}；pnpm-workspace.yaml/package.json/lockfile 若需。
- **Change:** 新增 workspace 包，exports 指向 src，scripts=test/lint/typecheck/clean。
- **Compatibility:** 纯新增，不改现有包。
- **Verification:** pnpm --filter @soymutdb/genome-data typecheck && lint && test（空测试通过）。
- **Outcome:** 可独立构建测试的包。

### A2 位置、FileProvider 与句柄缓存
- **Files:** src/location.ts、src/file-provider.ts、src/cache.ts、测试
- **Change:** GenomeLocation = uri|local；FileProvider.open；UriFileProvider（generic-filehandle）+ MemoryFileProvider（测试）；LRU(32)。
- **Verification:** 单测覆盖命中/逐出/并发 open 去重。
- **Outcome:** 所有读取器共用句柄层。

### A3 错误与 assembly 上下文
- **Files:** src/errors.ts、src/assembly.ts、测试
- **Change:** GenomeDataError(code, trackId)；AssemblyContext{key,name,aliases,refNames}；resolveRefName 在 alias/refNames 内解析，否则 assembly-mismatch。
- **Verification:** 单测：别名解析、未知 refName、跨 assembly 拒绝。
- **Outcome:** assembly 隔离契约可测。

### A4 SequenceReader
- **Files:** src/readers/sequence.ts、测试
- **Change:** @gmod/indexedfasta + bgzf，getSequence(region) → SequenceChunk；getChromSizes()。
- **Verification:** fixture 上区域序列与 chrom.sizes 断言；越界与空区域。
- **Outcome:** 参考序列可用。

### A5 VariantReader
- **Files:** src/readers/variant.ts、测试
- **Change:** @gmod/tabix + @gmod/vcf，区域查询 → VariantRecord（kind 分类 snv/mnv/ins/del/sv）。
- **Verification:** fixture 记录数、坐标、kind、ref/alt。
- **Outcome:** 变异与结构变异可用。

### A6 FeatureReader（GFF3）
- **Files:** src/readers/feature.ts、测试
- **Change:** tabix + GFF3 解析，parentId 关联 exon/CDS。
- **Verification:** 基因/转录本/外显子层级与坐标。
- **Outcome:** 基因模型可用。

### A7 QuantitativeReader 与 IntervalFeatureReader
- **Files:** src/readers/quantitative.ts、src/readers/interval.ts、测试
- **Change:** @gmod/bbi 读 BigWig 与 BigBed。
- **Verification:** 区间分数与 bigbed 特征。
- **Outcome:** 定量与重复轨道可用。

### A8 TextSearchReader（Trix）
- **Files:** src/readers/trix.ts、测试
- **Change:** @gmod/trix 查询基因候选。
- **Verification:** 前缀命中与空结果。
- **Outcome:** 基因搜索可用。

### A9 createTrackDataSource 工厂
- **Files:** src/factory.ts、测试
- **Change:** 按 track.type 选择读取器；未知类型抛 unsupported-type。
- **Verification:** 各类型映射 + 未知类型错误码。
- **Outcome:** 上层只依赖工厂。

### A10 导出与门禁
- **Files:** src/index.ts、package.json
- **Verification:** pnpm --filter @soymutdb/genome-data test/lint/typecheck 全绿；根 smoke contracts 不回归。
- **Outcome:** Phase 1 可独立合并。

## Phase 2 — @soymutdb/genome-view（子项目 B）

- B1 包脚手架（Vue 3 + @vue/test-utils，peer 依赖 vue）。
- B2 useGenomeViewport：视口状态 + pan/zoom/goto + 去抖区域请求。
- B3 轨道注册表 registerTrackRenderer + TrackErrorBoundary（未知类型隐藏 + 单轨错误隔离）。
- B4 TrackRuler + SequenceTrack（canvas）。
- B5 FeatureTrack（SVG，复用 GeneModelPreview 布局）。
- B6 VariantTrack + QuantitativeTrack（canvas，DPR + 视口裁剪）。
- B7 TrackSelector + LocusSearch（键盘可达）。
- B8 组件测试：视口数学、注册表、错误边界、键盘。
- **Verification:** pnpm --filter @soymutdb/genome-view test/lint/typecheck。

## Phase 3 — apps/jbrowse 外壳（子项目 C）

- C1 main.ts + App.vue + ui-vue Provider；保留 #root 挂载与 index.css。
- C2 头部/assembly/locus/分享/全屏/轨道摘要移植。
- C3 bridge.ts 与 deep-link.ts 原样复用（纯 TS，不动契约）。
- C4 i18n 改用 @soymutdb/i18n-core Vue 绑定。
- C5 契约测试：antd-migration-contract.test.mjs 改造为断言无 React 依赖 + bridge/深链形状。
- C6 新旧双跑开关 + 门户 Playwright 嵌入 E2E 对齐。
- C7 对等后移除 react/react-dom/react-i18next/@tanstack/react-query/lucide-react/@vitejs/plugin-react/@jbrowse/react-*，更新 lockfile。
- **Verification:** pnpm --filter @soymutdb/jbrowse test/lint/typecheck/build；e2e/tests 门户嵌入；pnpm install --frozen-lockfile。

## Verification（整体）
- 每包 lint/typecheck/test。
- 门户嵌入 E2E：iframe ready、locus 往返、超时/错误态。
- 契约测试：无 React、bridge/深链不变。
- 根 gates：smoke contracts、dependency governance。

## Risks
- pnpm 沙箱状态目录（P0-1 未解决则阻塞 A1/C7）。
- /jbrowse-data 在 dev/E2E 的可得性。
- 轨道渲染性能（必须视口裁剪）。
- 大范围删除依赖的 lockfile 风险（C7 需全新校验）。

## Retirement
- packages/i18n 的 react-i18next 使用在 C4 后无消费者 → 子项目 D 退役。
- packages/motion 无消费者 → 子项目 D 退役并加回归断言。
- @jbrowse/react-* 与 React 相关依赖在 C7 退役，触发条件=门户 E2E 全绿。

## Execution Route
- **Route:** inline（任务顺序依赖、共享契约；并行收益低）。
- **Fallback:** 若某项独立（如 fixtures 生成）可临时 subagent，但默认 inline。
- **User confirmation required:** no — 无不可逆、隐私、付费或发布边界（C7 删除依赖在本地提交，未 push）。

## Self-review
- 覆盖 spec 的 A/B/C；无占位符；owner/类型一致；最小变更边界明确；兼容性与退役触发点明确；验证命令可执行。
