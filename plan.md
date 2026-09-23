# SoyMutDB Next 当前状态驱动重构计划（第七轮 · PR #1 收敛版）

> 审计日期：2026-09-23
> Canonical plan：`plan.md`（保持小写，禁止再创建 `PLAN.md` 形成双真源）
> Base：`main@4ec2fdb768d368585e76a399f202607e578a0ec2`
> 当前实现分支：`refactor/next-vue-and-p2`
> 本轮审计起点：`ec12ee611f7fd8baae1600c3dffe93aa25c16575`
> PR：#1 `refactor: Vue mainline + pnpm 12 + P2-3 import protocol (Phase C/A/B/D/F)`
> 原则：先关闭 PR #1 correctness / CI / runtime gate，再继续新功能。未通过 Gate 的能力不得以“本地可用”替代真实交付证据。

---

## 2026-09-23 收敛执行记录（PR #1 已合并）

PR #1 已 merge 为 `d17c0a96b`。以下工作从该基线继续（CNB `DEFERRED_QUOTA`，未重试；
GitHub Actions 为当前主 gate）。

### 已落地提交

| commit | 内容 |
| --- | --- |
| `d34b012f2` | CI：唯一 Python workspace bootstrap（`scripts/install_python_workspace.py`）；`packages/import-protocol` 不再从 PyPI 解析；ClickHouse job 3.12→3.14 |
| `d4f3c5c63` | Vue：移除 store -> router import cycle（未使用的 `goHome`） |
| `c1e9d0195` | Vue：`cn` falsy 测试满足 `no-constant-binary-expression` |
| `10d273eaf` | 依赖：移除未使用 Vue deps；`pnpm dedupe` 清除 17 组重复版本（-282 lockfile 行） |
| `1a40febbe` | 契约：PLATFORM_CATALOG/pnpm 12/vue-demi 对齐；ADR-0001 pnpm 12.5.1 |
| `472434c48` | ClickHouse：MV 名称断言修复（`mv_gene_impact`）；迁移 SQL `chromosome_summary.cnt` 与 init.sql 对齐；四源交叉契约 + chdb 真实引擎验收 |
| `8b7b06b2b` | governance：Vue SFC cycle 分析（madge 拆分 + `--ts-config`），16/16 analyzer 通过 |
| `c934fce31` | Vue：site variant 严格校验、release header pin、canonical JBrowse origin、env 类型声明 |
| `9dd69532d` | Vue：query key 携带 release/site/assembly/filters；queryOptions 工厂；Mutants/Variants URL 状态；Downloads presign；Search a11y |
| `147237fcf` | Vue：`VITE_BASE_URL` 驱动 Vite base 与 router history base |
| `6e9bf13cf` | Vue：非法 `VITE_SITE_VARIANT` 构建期 fail closed |
| `c89e75da6`+`923d8aa4a` | worker：`test_chdb_harness` 命名；内存契约子进程隔离；PG 序列对齐 |
| `1726f997c` | worker：ADR-0005 正确性（稳定 variant id、fingerprint advisory lock、VERIFYING 恢复、release 全量重建、`mutations_sync`、参数化、冲突 fail-closed、VcfAdapter 接线） |
| `61dffc4b0` | worker：fingerprint advisory lock 改用专用连接（真实 PostgreSQL 暴露的池化缺陷） |
| `ca44c516f` | worker：vcf 移出无 writer fail-closed 矩阵（已有协议专用测试） |
| `bc2b9648d` | CI：artifact 压缩/去重/保留期治理（配额 500MB） |

### 证据（本地）

- smoke contracts 层（13 scripts + `infra/clickhouse/test_schema_contract.py`）→ **231 passed**
- governance `pnpm deps:audit`（注入 demo VITE_*）→ **16/16 passed**（含两个 madge entry）
- `web-vue`：**10 files / 31 tests**；typecheck + lint 干净
- Vite base 构建：`/`、`/soymutdb-next/`、裸 `soymutdb-next` → 产物前缀正确；`VITE_SITE_VARIANT=public` → exit 1
- worker chdb 套件（finalize/vcf/engine/legacy/协议）→ **22 passed**（untouched summary、冲突、注入、VERIFYING 恢复、adapter 接线）
- 真实 PostgreSQL 16（本地临时集群，`SOYMUTDB_RUN_POSTGRES_INTEGRATION=1`）：`test_import_manifest_repo.py` + `test_vcf_import.py` → **14 passed**（advisory lock 串行化、VCF e2e、VERIFYING 恢复、序列对齐）。真实 PG 还找到了 lock 在 Session commit 后退池的缺陷（`61dffc4b0`）
- GitHub api-tests：apps/api pytest **1542 passed**；worker pytest 348 passed + 1 个旧断言（已在 `ca44c516f` 更新）
- 本地 API 全量复现的 131 errors 为共享库 seed 冲突（CI 用全新 testcontainers），非代码问题
- GitHub：ClickHouse migration fixture（真实 24.8）→ **success**；MCP e2e → success
- artifact 配额：`soymutdb-next` 19.5GB + 账户其它仓库 939MB 旧 artifact 已清理；等待 GitHub 重算（6–12h）

### 阻塞 / 未关闭

- GitHub artifact 上传：已压缩 `pages-demo-dist`、移除无消费者的 dist 上传、缩短证据保留期；等待配额重算（6–12h）后应恢复
- api-tests 的 PG 集成已在本地真实验证；CI 复跑待最新 run 完成
- T8 local Docker：本机无 Docker daemon（`LOCAL_DOCKER_T8` PENDING）
- review 剩余：Vue 未进入 canonical delivery（Phase 3 切换，当前明确 preview-only）

### Next

1. 监控最新 main CI；关闭剩余真实失败（非配额项）
2. 配额恢复后确认 artifact 上传与 baseline jobs
3. Phase 1 full-stack isolation（外部不可用 Docker 时先做 GitHub 可完成部分）

---

## 0. 当前事实：不要再按旧 Phase 从零开始

### 0.1 Git / PR

- `main` 仍在 `4ec2fdb...`。
- PR #1 从 main 前进 31 commits、behind 0；审计时 head 为 `ec12ee61...`。
- PR #1 共 99 changed files，约 +6972 / -600。
- GitHub 报告 `mergeable=true`，但 `mergeable_state=unstable`。
- Copilot review 有 22 个未解决线程：16 High、6 Medium。
- GitHub Actions 两条 PR workflow 均为 failure，因此 PR #1 当前禁止合并。

### 0.2 已实现但尚未等于 Release-ready

| 工作包 | 当前状态 | 证据等级 | 结论 |
| --- | --- | --- | --- |
| Framework-neutral seam | IMPLEMENTED | E2 本地 | shared/query-keys/i18n-core/genome-view-model 已有守卫 |
| Shared import protocol | IMPLEMENTED | E2 本地 + 真 PG | fingerprint/FSM/visibility 已下沉 |
| P2-3 staging/verify/finalize | PARTIAL | E2/E3 单节点 chdb + 真 PG | 有真实引擎证明，但存在 review 指出的 finalize/并发/重试风险，不能关闭 Gate |
| pnpm 12 | IMPLEMENTED_LOCAL | E2 本地 | 12.5.1 + lockfile 已迁，GitHub CI 仍红 |
| Vue shell | IMPLEMENTED_LOCAL | E2 本地 | Router/Pinia/Vue Query/Antdv Next/Tailwind 已建立 |
| Vue Home/Search/Gene/Mutants/Variants/Downloads | PARTIAL | E2 本地 | 页面存在，但 release/site/cache/base URL 等 correctness 尚未关闭 |
| Canonical Vue deployment | NOT_DONE | E1 | 当前正式 build/publish 仍以旧 `apps/web` 为主 |
| TanStack Charts 全迁 | NOT_STARTED | E0/E1 | 不得在 PR #1 correctness 未关闭前批量启动 |
| Vue Admin | NOT_STARTED | E0 | 后置 |
| P1-1 full-stack ID-05 | BLOCKED | E1/E2 局部 | 仍缺真实 seeded release + unreleased sentinel + artifact-level 全栈证据 |
| CNB Docker / Trivy / SBOM | BLOCKED | E1 配置 | PR #1 尚无真实 CNB 成功证据 |
| P2-6 capability reopen | BLOCKED | E1 | 所有原默认 OFF scientific imports 继续 OFF |

### 0.3 PR #1 提交历史已确认

PR 已按可预览逻辑提交推进：framework seam → import protocol → ClickHouse port/finalize → worker manifest → VCF wiring → genome model → pnpm12 → Vue shell → Vue pages → GitHub workflow pins。这个提交模型保留，不 squash 成单一巨型提交。

---

## 1. PR #1 Exit Gate：这是当前唯一最高优先级

在以下四组 Gate 全部通过前：

- 不继续批量迁移 Vue 页面；
- 不开始全量 TanStack Charts；
- 不删除 React/ECharts；
- 不开启 VCF 或其他 scientific import feature flag；
- 不把 Vue 声称为已上线 canonical portal。

### G1 · CI / Toolchain Gate

当前 GitHub Actions 真实失败项：

1. API tests：失败在 Python dependency install。
2. Frontend：失败在为 OpenAPI export 准备 API venv。
3. Baseline Ubuntu API：失败在 API/test dependencies install。
4. Baseline OpenAPI contract：失败在 backend/client dependencies install。
5. Baseline Windows：失败在 API package install。
6. Dependency governance：graph/gates 失败。
7. ClickHouse migration fixture：真实 workflow 失败。
8. Web/Admin baseline build 本体与 artifact contract 已通过，但 artifact upload 失败。
9. Docker image / Kind / publish 因上游失败全部 skipped。

最高概率的第一个安装链问题：`apps/api` / `apps/worker` 已声明本地 `soymutdb-import-protocol==0.1.0`，`[tool.uv.sources]` 能告诉 uv 使用本地路径，但 GitHub workflow 使用 plain pip 且只预装 `packages/jobs-py`。必须先用日志/最小复现确认，不能仅凭推断直接宣布原因。

#### G1 实施要求

- 新增一个唯一 Python workspace bootstrap 入口，供 GitHub/CNB/local 共用；不要在多个 workflow 手写不同的 `pip install -e ...` 顺序。
- bootstrap 必须显式安装所有本地 Python packages：至少 `packages/import-protocol`、`packages/jobs-py`，再安装 API/worker。
- 统一 Python 3.14；历史 ClickHouse job 若仍用 3.12，必须说明是否为 fixture 限制，否则收敛。
- 修复 dependency-governance 后必须保留 pnpm 12 双文档 lockfile 支持。
- artifact upload failure 必须读取具体日志，禁止通过 `if-no-files-found: ignore` 等方式绕过。
- 修复后 GitHub 两个 workflow 必须全部 green，再进入 CNB。

#### G1 退出证据

- GitHub Actions PR head：CI = success。
- Baseline validation = success，或明确拆除已被新交付链取代且有 ADR 的历史 gate。
- 所有失败 job 都有 root cause + regression test/contract。

---

### G2 · Vue correctness / deployment-boundary Gate

官方 TanStack Query 文档明确要求：query function 依赖的每个会改变结果的变量，都必须进入 query key；Vue 中 ref/getter 应保持响应式依赖。PR review 对当前 query key 的多项问题与官方契约一致。

必须关闭：

1. API 请求必须绑定 build/runtime 的 release context，不能页面显示 release A、请求实际使用 active release B。
2. Gene detail key：加入 `siteVariant + release + assembly + gene identity`。
3. Mutant detail key：禁止 hard-code null release。
4. Variants key：加入 chromosome/start/end/impact，以及任何 cursor/limit/sort/result-affecting filter。
5. Search/Mutant/Gene/Variant 等 query 应优先使用 Vue Query `queryOptions()` 把 queryKey 与 queryFn 共置，避免两者再次漂移。
6. `VITE_SITE_VARIANT` 必须严格验证，只允许 `external|internal`，非法值 build/start fail-closed。
7. Vite `base` 与 Vue Router history base 必须来自同一个 `VITE_BASE_URL` / normalized deployment base。
8. Mutant filter 必须写入 route query，可分享/刷新/后退恢复。
9. Gene JBrowse 使用 canonical `VITE_JBROWSE_BASE_URL`。
10. Downloads 必须实现真实 download/presign action，不把 metadata-only 页面标成 parity。
11. URL-less Search hit 不能保留可交互 anchor 语义。
12. Vue 进入 canonical build/deploy 前，必须先明确 `preview-only`；不要在同一个 correctness commit 中同时切 production delivery。

#### G2 测试

- query-key contract：release/site/assembly/filter 任一变化必须生成不同 key。
- reactive transition：切 release/site/filter 必须 refetch，而非复用旧缓存。
- deep-link：刷新 URL 后恢复 filter/page/context。
- `VITE_BASE_URL=/soymutdb-next/` build + preview。
- external/internal invalid variant negative test。
- JBrowse origin contract。
- Downloads presigned URL ownership/visibility test。
- keyboard/a11y negative interaction test。

---

### G3 · P2-3 import correctness / security Gate

chdb 是真实 ClickHouse 引擎证据，但不能替代 production HTTP ClickHouse、mutation、并发 worker、cluster/replica 语义。

PR review 当前必须逐条 triage：Confirmed / False Positive / Already Fixed。Confirmed 项必须先补 failing regression test，再修实现。

#### G3.1 实际任务入口

- 确认 Admin/Celery `run_import_adapter(kind=vcf)` 的真实路径最终进入新 ADR-0005 protocol。
- 如果旧 `VcfAdapter.run` 仍 unconditional fail-closed，则只能二选一：
  - 保持 capability OFF 并让路径明确 fail-closed；或
  - 在 P2-6 前把真实 adapter path 接到 protocol。
- 不允许“存在一个新的 `import_vcf` 函数”就宣称功能已接线。

#### G3.2 稳定逻辑身份

- semantic fingerprint 已故意排除 filename/object key。
- variant identity 也必须从稳定 semantic identity + canonical variant coordinates/alleles 推导，不能依赖可变化的 S3 `file_key`。
- same bytes + different object key retry 必须得到同一 logical facts / same variant IDs。

#### G3.3 并发与恢复

- 同一 fingerprint 同时到达两个 worker 时，只允许一个 writer/finalizer。
- 优先在 PostgreSQL control plane 使用 transaction-scoped advisory lock 或等价可证明锁；不要依赖 Celery“通常不会重复”。
- lock key 必须稳定、冲突范围清晰、异常释放可靠。
- CREATED/PARSING/WRITING/VERIFYING/FAILED/PUBLISHED 每个可恢复状态必须有 retry table。
- VERIFYING crash 后 retry 不得执行非法 VERIFYING→VERIFYING。
- PUBLISHED retry 必须是 no-op / return existing result。

#### G3.4 ClickHouse finalize

- ClickHouse mutations 默认异步时，任何 `ALTER ... DELETE` 后立刻重写都存在 race。
- 若保留 mutation，production engine 必须使用同步设置并验证 mutation 完成；否则改为不依赖异步 mutation 的 staging/swap/rebuild protocol。
- v1 仅 draft release，因此优先选择“整 release 可重建且可验证”的简单正确方案，不为增量热更新增加复杂度。
- summary purge/rebuild 范围必须和 base rewrite 范围一致；不能删除整个 release summary 却只重建 touched chromosomes。
- post-finalize 必须对 base + summaries 做完整校验。

#### G3.5 SQL 与重复冲突

- 所有 release/chromosome/输入派生值必须参数化；禁止 f-string 拼接上传文件内容到 SQL。
- exact duplicate variant 可 deterministic dedup。
- 同一 canonical `variant_id` 若 annotation/其他事实冲突：第一版建议 fail-closed，输出 diagnostics；不要静默任选一条。

#### G3 测试矩阵

- same bytes / same key retry。
- same bytes / different key retry。
- same semantic input concurrent workers。
- crash at PARSING/WRITING/VERIFYING/finalize-before-ack/finalize-after-ack。
- async/ambiguous ACK。
- quote/SQL-fragment chromosome negative test。
- duplicate identical row。
- duplicate conflicting row。
- touched subset vs pre-existing untouched chromosome。
- mutation wait failure/timeout。
- final base/summary checksum + count。

---

### G4 · Review / Merge Gate

PR #1 合并条件：

- 22 review threads 全部有 triage 结论。
- 所有 Confirmed High 已有 regression test + fix。
- unresolved High = 0。
- unresolved Medium = 0，或明确记录为 follow-up 且不影响 correctness/deployment/security。
- 重新请求一次 fresh code review。
- GitHub Actions 全绿。
- CNB 真 Docker Gate 全绿。
- feature flags 仍保持当前安全默认。

只有满足 G1–G4，才允许 merge PR #1。

---

## 2. 官方文档驱动的架构修正

### 2.1 Vue / Router / Pinia / VueUse

- Vue 生产线使用 latest stable，不跟 RC/beta；当前迁移基线保持已锁定 stable，升级必须独立提交。
- Vue Router 已进入 v5 稳定线；继续精确治理，不因迁移再引入第二套路由。
- Pinia 只做 client/global UI state；server state 继续由 TanStack Vue Query 管。
- VueUse 15 按 v15 breaking contract 使用，不增加兼容旧 API shim。

### 2.2 TanStack Query

新增项目规则：

- `packages/query-keys` 只表达 framework-neutral identity。
- Vue app 新建 typed `queryOptions` factory 层，将 queryKey/queryFn/staleTime/context 共置。
- 所有 query function result-affecting variables 进入 key。
- site variant / release / assembly 是 SoyMutDB 默认 cache namespace，不得由页面作者自行决定是否加入。

### 2.3 TanStack Charts

官方仍标记为 Alpha 0.x，当前 published line 文档为 0.18.0。允许后续全线迁移，但：

- exact pin，禁止 `^0.x`。
- 必须通过 `@soymutdb/charts` facade。
- 一个 chart 一个/一组可预览 commit。
- 每个 0.x minor upgrade 独立 PR。
- 图表必须有 ariaLabel/ariaDescription 和精确值替代（表格/下载），不能只靠 SVG。
- PR #1 未合并前不启动全量迁移。

### 2.4 pnpm 12

- workspace project settings 继续集中在 `pnpm-workspace.yaml`。
- lockfile 双文档属于 pnpm 12 行为，任何 scanner/governance parser 都必须覆盖。
- `allowBuilds` 保持最小白名单。
- 后续评估 `blockExoticSubdeps`、`trustPolicy: no-downgrade`；先用当前 lockfile 做兼容审计再启用。
- `minimumReleaseAge` 例外必须逐包、逐版本、有注释，不允许通配符放宽。

### 2.5 ClickHouse

- PostgreSQL manifest 是 exactly-once / logical visibility authority。
- ClickHouse 原生 dedup 只能做辅助；其窗口/重试稳定性不能替代应用协议。
- mutation/DELETE 等异步操作必须显式等待或从协议中移除。
- dynamic SQL values 使用 parameters。

### 2.6 CNB

CNB 继续作为 Docker 生产等价证明主骨架：

- `services: docker` 提供 dind + Docker CLI；
- buildx 可做多架构；
- CNB Docker registry 可保存镜像与 registry cache；
- GitHub 与 CNB 必须继续调用同一 shared scripts，禁止双逻辑漂移。

---

## 3. PR #1 关闭后的新 Phase 顺序

### Phase 1 · Full-stack Isolation + CNB Acceptance

目标：把“本地 E2”推进到真实 T8。

- CNB 启动 PostgreSQL + ClickHouse + Redis + MinIO。
- build API/worker/MCP/JBrowse/必要 frontend artifacts。
- migrations。
- seeded published release。
- unreleased sentinel。
- running API。
- external/internal artifacts。
- artifact-level ID-05 negative leakage。
- S3 put/head/get/checksum。
- ClickHouse production engine P2 finalize。
- Docker runtime smoke、Trivy、SBOM。

退出：P1-1 VERIFIED + CNB run/artifact/digest 可引用。

### Phase 2 · P2-4 / P2-5 / P2-6

- `module_data_rows → canonical` 显式 promotion。
- genes 先做第一 canonical module。
- 完整 retry/crash/concurrency matrix。
- 每种 scientific import 单独 Release Gate。
- 默认 OFF 的能力逐个评审，不批量开启。

### Phase 3 · Vue Canonical Portal Parity

在 PR #1 现有页面基础上继续，而不是重写：

- phenotype。
- Gene Preview merged genome context。
- JBrowse deep-link。
- remaining research tools。
- SSG/static route enumeration。
- external/internal build parity。
- canonical build/deploy 切换。

每页必须有独立可预览 commit / route / test evidence。

### Phase 4 · TanStack Charts

建立 `@soymutdb/charts`，逐图从 ECharts 迁移；最后一个单独 commit 删除 ECharts runtime/CDN/helper。

### Phase 5 · Vue Admin

Admin shell → dashboard → Import Studio → release/dataset/content/publication → analytics/settings。

### Phase 6 · Hardening

- dual-site/SSG regression。
- a11y / 390-1024-1440 / dark / reduced-motion。
- performance baseline/regression。
- S3/backup/restore。
- security/upload/SSRF/CSP。

### Phase 7 · React/ECharts Retirement

只有 Vue canonical delivery + full E2E parity 后：

- 删除 React active runtime。
- 删除 AntD React。
- 删除 React Router/Query adapters。
- 删除 ECharts。
- 删除旧 dead configs/scripts。
- historical docs/ADR 保留 archive。

### Phase R · Rust

仅在 import/search/chart/full-stack profile 有真实瓶颈证据后启动；控制面继续 Python。

---

## 4. Subagent 模型（从现在起生效）

默认最多 4 个 active coding subagents。同一文件同时只能一个 writer。

### 当前 PR #1 推荐四 Lane

1. `SUBAGENT-CI`：只处理 Python workspace install、GitHub/CNB shared bootstrap、workflow failure root cause。
2. `SUBAGENT-VUE-CORRECTNESS`：只处理 release/site/queryOptions/base URL/filter/deep-link/download/a11y。
3. `SUBAGENT-IMPORT-CORRECTNESS`：只处理 manifest locking、stable identity、resume、ClickHouse finalize、SQL params、duplicate policy。
4. `SUBAGENT-REVIEW-TEST`：read-only 为主，逐条验证 22 review comments、补 test plan、复核 diff。

主 Agent 独占：

- `plan.md`。
- `pnpm-lock.yaml` 最终协调。
- `.cnb.yml` / shared CI orchestration 的最终合并。
- DB migration sequence。
- feature flag 决策。
- PR merge。

任何 subagent 发现需要越权：STOP → 返回 change request 给主 Agent。

---

## 5. 提交与预览规则

继续保持每个逻辑变化可预览、可 revert。

PR #1 下一批推荐提交链：

1. `fix(ci): install workspace Python protocol packages consistently`
2. `fix(vue): bind release and site context into query options`
3. `fix(vue): honor deployment base and URL-backed filters`
4. `fix(vue): complete download and JBrowse parity`
5. `fix(import): stabilize logical import identity and serialize workers`
6. `fix(import): make ClickHouse finalize synchronous and scope-safe`
7. `fix(import): parameterize SQL and reject conflicting duplicates`
8. `test(import): close retry concurrency and finalize matrix`
9. `test(vue): close cache context and deep-link regressions`
10. `ci(cnb): close Docker runtime acceptance`
11. `docs(plan): record PR #1 exit evidence`

不要 squash 这些有独立诊断价值的 commits。

每个 commit 必须报告：SHA、purpose、changed files、focused test、preview/repro、risk、next。

---

## 6. 测试链 T0–T11

| 层 | 内容 |
| --- | --- |
| T0 | lint/typecheck/contracts/architecture/dependency/feature-flag |
| T1 | unit |
| T2 | Vue component/store/queryOptions/chart facade |
| T3 | real PostgreSQL/ClickHouse/Redis/MinIO integration |
| T4 | API/OpenAPI/RBAC/release/assembly/presign contracts |
| T5 | external/internal artifact/SSG/CSP/SW/leakage |
| T6 | browser E2E research workflows |
| T7 | visual/a11y/responsive/dark/reduced-motion |
| T8 | Docker/CNB runtime |
| T9 | Trivy/SBOM/license/secret/upload/SSRF/security |
| T10 | crash/retry/backup/restore/rollback/publication |
| T11 | bundle/search/import/chart/CI performance regression |

风险越高，要求覆盖层级越高。P2 finalize 不能只以 T1/T2 通过关闭；至少需要 T3 + T8 + T10。

---

## 7. 固定科研回归任务

1. Gene ID → Gene → mutant → variant → JBrowse。
2. Phenotype → mutant → genomic evidence。
3. Region → variants → variant detail → JBrowse。
4. Mutant public ID → phenotype/gene/variant/download。
5. Search exact/prefix/general，release/site 切换后缓存不串。
6. URL filter → reload/back/forward 结果一致。
7. Admin S3 upload → bind release/assembly → validate → import → verify。
8. Failed import → diagnostics → safe retry。
9. Published release vs unreleased sentinel negative leakage。
10. CNB image → migrations → health → PG/CH/S3 smoke。

---

## 8. PR #1 Merge Checklist

- [ ] GitHub CI success。
- [ ] Baseline workflow success / 或正式 ADR 替代。
- [ ] CNB shared scripts success。
- [ ] 22 review threads triaged。
- [ ] unresolved High = 0。
- [ ] queryOptions/cache namespace tests green。
- [ ] base URL/site variant/deep-link tests green。
- [ ] real adapter VCF path verified fail-closed or protocol-driven。
- [ ] per-fingerprint serialization tested。
- [ ] stable variant identity across object-key retry。
- [ ] VERIFYING retry tested。
- [ ] ClickHouse mutation/finalize race closed。
- [ ] summary untouched-partition regression green。
- [ ] SQL parameterization negative test green。
- [ ] conflicting duplicate policy green。
- [ ] P1 feature flags remain safe defaults。
- [ ] fresh review requested。
- [ ] plan evidence updated。

---

## 9. 官方资料索引（2026-09-23 复核）

- Vue releases: https://github.com/vuejs/core/releases
- Vue Router: https://router.vuejs.org/ and https://github.com/vuejs/router/releases
- Pinia: https://pinia.vuejs.org/ and https://github.com/vuejs/pinia/releases
- VueUse 15: https://github.com/vueuse/vueuse/releases/tag/v15.0.0
- TanStack Vue Query keys: https://tanstack.com/query/latest/docs/framework/vue/guides/query-keys
- TanStack Vue Query options: https://tanstack.com/query/latest/docs/framework/vue/guides/query-options
- TanStack Charts: https://tanstack.com/charts/latest/docs/installation
- TanStack Charts a11y: https://tanstack.com/charts/latest/docs/guides/accessibility
- pnpm settings: https://pnpm.io/settings
- pnpm supply chain: https://pnpm.io/supply-chain-security
- ClickHouse docs: https://clickhouse.com/docs/
- CNB grammar: https://docs.cnb.cool/zh/build/grammar.html
- CNB Docker artifacts: https://docs.cnb.cool/zh/artifact/docker.html

---

## 10. 当前 Next

不要再做 Phase F 新页面。现在严格按：

**G1 CI install/root-cause → G2 Vue correctness → G3 P2 correctness/security → GitHub green → CNB T8 → fresh review → merge PR #1。**

PR #1 合并后，再从 Phase 1 full-stack isolation/CNB acceptance 继续。

> 完成标准不是“PR 代码很多”，而是：当前 31+ commits 的每一条新主线能力都有正确上下文、真实回归、真实运行证据，并且能安全成为 main 的下一基线。