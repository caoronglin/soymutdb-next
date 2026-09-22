# SoyMutDB Next 全线重构执行计划（第六轮 · PI-agent 主计划）

> 日期：2026-09-22
> 状态：唯一主执行计划 / 架构约束 / 测试链 / Release Gate
> 重构前冻结基线：bef6db6d737f44cfd8d11aef20739c8b80147eb3
> 冻结归档分支：archive/pre-vue-refactor-2026-09-22-bef6db6
> 数据正确性前置：ADR-0004~0007、P1 isolation、P2 import manifest/idempotency/finalize
> 执行原则：先证据后修改；先契约后重构；每个阶段可回滚；CNB 与 GitHub 调用同一测试脚本；未过 Release Gate 的能力不得开启。

---

# 0. PI-agent 执行协议

PI-agent 每轮只能执行当前 Phase。开始任何 Phase 前必须重新读取当前 main、plan.md、相关 ADR、最近 20 个 commits、当前分支、PR、测试和受影响代码，不得把本计划中的历史状态当成实时事实。

固定执行循环：

1. READ：读取当前代码和官方文档。
2. VERIFY：用 git/search/runtime 验证计划假设。
3. REPRODUCE：先复现当前行为或缺陷。
4. DESIGN：给出最小迁移边界和回滚点。
5. IMPLEMENT：只改当前 Phase 所需范围。
6. FOCUSED TEST：先跑最小相关测试。
7. BROAD REGRESSION：跑本计划定义的回归层。
8. CNB PROOF：需要 Docker/服务证明的变更必须在 CNB 跑真实镜像与运行验证。
9. EVIDENCE：记录 commit、命令、结果、artifact digest、证据等级。
10. UPDATE PLAN：回填完成项、失败项、阻断项和下一步。

证据等级：E0 文档/历史；E1 当前代码确认；E2 可重复测试；E3 生产等价故障/性能验证；E4 staging/production 观察。

严禁把“代码存在”写成“功能已验证”；严禁把本地 mock 绿写成真实 PostgreSQL/ClickHouse/MinIO/CNB 绿。

---

# 1. 冻结基线与归档规则

重构前 React/AntD 主线基线固定为 commit bef6db6d737f44cfd8d11aef20739c8b80147eb3，归档分支 archive/pre-vue-refactor-2026-09-22-bef6db6 已创建，后续不得向该分支继续开发。

仓库当前未配置 GitHub ruleset。真正服务器侧只读冻结应对 archive/** 增加 ruleset：Restrict updates、Restrict deletions、Block force pushes；GitHub 官方 ruleset/branch protection 支持这些能力。当前 GitHub 连接器没有 administration write 能力，因此归档分支已固定 SHA，但规则锁需仓库管理员在 GitHub 设置中完成。

重构基线 Release 包定义：

- source commit = bef6db6d...
- source archive branch = archive/pre-vue-refactor-2026-09-22-bef6db6
- CNB 使用该 commit/tag 构建现有 amd64/arm64 runtime images
- 必须完成 runtime smoke、Trivy、SPDX SBOM、provenance、release manifest、SHA256
- 归档制品不得用重构后的代码重新构建
- 后续任何 regression 都可以和此冻结基线做功能/产物/性能对照

---

# 2. 最终技术主线

前端正式切换到 Vue，React 进入迁移期维护，不再扩新产品功能。

目标基线：

- Node 24
- pnpm 12
- Vue 最新 stable；禁止 RC/beta 作为生产基线
- Vue Router 最新 stable
- Pinia 4
- VueUse 15
- TanStack Vue Query 5
- TanStack Charts 0.x 精确锁定
- Antdv Next 1.x 精确锁定并通过项目 facade 使用
- Tailwind CSS 4
- shadcn-ui/cn，仅采用 cn class merge 工具，不引入完整 shadcn/ui
- Vite
- Vitest + Playwright

当前官方复核结论：

- Vue 当前稳定线为 3.5.x；3.6 仍有 RC，因此生产使用 latest stable。
- Pinia 4 为 ESM-only；Pinia 只负责 client/global UI state。
- VueUse 15 已有 breaking changes，直接按 15.x API 迁移。
- TanStack Vue Query 继续承担 server state/cache/mutation。
- TanStack Router 不作为 Vue 主线，路由迁 Vue Router。
- Antdv Next 1.x 仍可能在 minor 发生 breaking change，因此 exact pin + @soymutdb/ui-vue facade。
- TanStack Charts 当前为 0.x Alpha，因此允许全线迁移，但必须 exact pin + @soymutdb/charts facade + visual/a11y/value regression；升级 0.x minor 必须独立 PR。
- ECharts 只允许迁移期存在，迁移完成后业务代码归零。
- cn 在兼容测试通过后替换 clsx + tailwind-merge。

Cloudflare Workers 明确不属于本次重构决策，不因为之前提供的 Workers 链接调整架构。

---

# 3. S3 / MinIO 决策

撤销“删除对象存储”的路线。保留 S3-compatible 存储语义，MinIO 继续作为自托管/开发默认实现。

原因：当前仓库已确认 S3/MinIO 直接服务于 Admin multipart upload、module import input、GWAS input/output、fastp/scanpy 等分析结果、public uploads、presigned URL、备份恢复、worker 任务和发布数据对象。删除会产生真实功能回归。

本轮只做接口治理，不删除能力：

- 业务层不得扩散 boto3/MinIO 细节；逐步收敛为统一 StorageService。
- PostgreSQL 只存对象元数据、checksum、size、MIME、visibility、release/dataset 关系，不用 Large Object 代替 S3。
- S3 object key、checksum、multipart、presign、backup/restore 继续保留测试。
- MinIO/S3 配置可简化，但不能从 core compose、worker、backup contract 中删除，除非未来另有 ADR。
- 所有上传必须继续做 size、MIME、checksum、key namespace、ownership、path/prefix validation。

---

# 4. 不可突破的硬约束

H1 数据能力 Gate：被 feature flag 关闭的 scientific import 继续关闭。只有 parser + validator + semantic fingerprint + durable manifest + staging + idempotency + verify + finalize + retry/crash/ambiguous ACK + rollback/cleanup + real PG/CH/E2E 证据齐全后，才允许单独评审开启。

H2 ClickHouse visibility：WRITING 阶段不得直接向 portal 正常读取的 final facts 暴露 partial data；base 与 dependent MV/summary 必须一起验证/finalize。

H3 VCF v1：只写 draft release。已发布 release 热替换不属于第一版。

H4 Worker/API：worker 不 import apps/api runtime package；共享纯协议放 packages。

H5 双站：external/internal 必须是独立 artifact、独立 SW/cache/analytics/security domain；external 对 internal_id、unreleased sentinel、private content 零泄漏。

H6 Admin：不提供 root/sudo/Docker daemon/arbitrary shell/arbitrary SQL/database superuser。

H7 S3：保留 S3/MinIO；任何重构不得破坏现有上传、分析、导入、备份恢复语义。

H8 Vue 迁移：对应 Vue 功能未达到 parity 前，不删除 React 实现；但禁止继续新增 React 专用业务功能。

H9 Charts：新图表只能使用 TanStack Charts facade；禁止新增 ECharts。迁移结束后 active code/config 中 ECharts 引用必须为 0。

H10 CNB：涉及 Dockerfile、runtime dependency、Node/Python/Rust toolchain、Compose、数据库或 S3 的变更，必须有 CNB 真实 Docker 构建和运行验证，不能只靠静态 CI。

---

# 5. Phase A — P2 数据正确性先行

这是全线重构期间仍然最高优先级的数据主线，可与前端基础设施 Phase B/C 并行，但不能被 UI 重构取代。

A1 共享 import protocol：fingerprint canonicalization、manifest state、allowed transition、schema/importer/normalization version 下沉共享 package，API/worker contract test 锁定。

A2 真实 ClickHouse inventory：在仓库固定真实版本上执行 SELECT version、SHOW CREATE TABLE variant_facts、system.tables、system.dependencies，保存 DDL/MV/summary evidence。

A3 staging writer：只写 staging；deterministic batch identity；bounded memory；draft release gate。

A4 verify：expected/written rows、checksum、release、assembly、schema/parser/normalization version。

A5 finalize：base + dependent MV/summary 一致；finalize 后二次验证；失败保持不可公开。

A6 failure matrix：same content retry、different filename、different release/assembly、crash before/mid/after write、crash during finalize、ambiguous ACK、duplicate batch、checksum/row mismatch、FAILED retry。

A7 capability reopen：默认保持 OFF；每种 import 单独评审。

---

# 6. Phase B — pnpm 12 与依赖治理

目标：在开始大规模 Vue 重写前先把依赖版本真源固定。

B1 升级 pnpm 11 → 12；同步 packageManager、engines/devEngines、CNB build image、Dockerfiles、GitHub CI、Corepack/安装方式和 lockfile。

B2 pnpm-workspace.yaml 成为 workspace 版本/策略真源：catalogMode strict、catalogPrune、catalog/catalogs、overrides、allowBuilds、workspace:* 内部依赖。

B3 catalog 加入 Vue、Vue Router、Pinia、VueUse、TanStack Vue Query、TanStack Charts、Antdv Next、Tailwind、cn、Vite、Vitest。

B4 快速变化依赖 exact pin：Vue 初始迁移版本、Pinia major、VueUse major、Antdv Next、TanStack Charts。

B5 CI contract：禁止 @soymutdb/* 从 registry 解析；禁止第二套 Vue runtime；禁止 package 私自声明 catalog 外公共版本；frozen lockfile。

B6 供应链：allowBuilds 白名单、依赖审计、license、secret scan、Trivy/SBOM 与 lockfile evidence。

Phase B Gate：本地、GitHub、CNB 三端 pnpm/Node 版本一致；pnpm install --frozen-lockfile 通过；dependency governance 全绿。

---

# 7. Phase C — Framework-neutral seam

在写 Vue 页面前抽出不可绑定框架的公共层：

- packages/api-client
- packages/schemas
- packages/domain
- packages/query-keys
- packages/i18n
- packages/design-tokens
- packages/genome-view-model
- packages/import-protocol / jobs-py 对应 Python contract

这些包不得依赖 react、vue、antd、antdv-next。

Gate：现有 React 应用和新的 Vue test harness 均能消费同一 API/schema/domain package。

---

# 8. Phase D — Vue Shell

D1 建 Vue Web/Admin shell，接入 Vue Router、Pinia、VueUse、TanStack Vue Query、Antdv Next facade、Tailwind 4、cn。

D2 状态分工：TanStack Vue Query = server state；Pinia = auth/theme/locale/motion/release-assembly/admin wizard/client state；component local = ref/computed。

D3 Router：迁移 URL filter/sort/page/release/assembly/deep-link/back-forward/scroll 语义，保留 SSG route enumeration。

D4 Antdv Next：业务只能从 @soymutdb/ui-vue facade 引用。升级上游时 facade contract test 先失败。

D5 cn：先跑 Tailwind4、dark、responsive、arbitrary value、CSS variable、genomic token merge snapshots；通过后才删 clsx/tailwind-merge。

Gate：Vue shell 能构建 external/internal 空壳 artifact，CSP、theme、i18n、routing、query client、error boundary/feedback 基础完成。

---

# 9. Phase E — TanStack Charts 全线迁移

目标：最终删除 ECharts，不保留双生产图表栈。

建议迁移顺序：release trend → chromosome density → impact distribution → expression bar → query latency → storage growth → import throughput → donut → heatmap → enrichment → exppattern → widget health。

每张图必须保存旧 ECharts frozen-baseline fixture，并验证：

- exact input data
- aggregation 与 missing-value policy
- axis/units
- tooltip exact values
- legend/filter
- release/assembly context
- dark/light
- motion/reduced-motion
- 390/1024/1440
- keyboard focus
- aria label/description
- linked data table 或可访问替代
- screenshot/visual regression

TanStack Charts 0.x 升级规则：exact pin；minor 升级独立 PR；先跑 facade contract + 全图 snapshot + Playwright visual，禁止业务代码使用未经 facade 暴露的内部 API。

最终 Gate：git grep 活跃源码/config 不再出现 echarts；删除 use-echarts、ECharts CDN/manual chunk/package/mock/docs active contract。

---

# 10. Phase F — 公共站 Vue 迁移

顺序：Home → Search/Omnibox → Genes → Mutants → Variants → Phenotypes → Downloads/Publications → tools → auth/public utility。

每页必须保持：API request/response 语义、URL search state、release/assembly、loading/empty/error、external/internal capability、i18n、SEO/SSG、keyboard、responsive。

禁止为迁移方便把 server-side filter 改回前端拉全量数据。

Gene Preview 从 primer-workbench 吸收 merged genomic viewport：gene/transcript/exon/CDS/UTR 同坐标轴、overlap row packing、strand、pinned detail、keyboard/focus；用 SoyMutDB release/assembly/public projection 重新实现，不能复制旧业务外壳。

---

# 11. Phase G — Admin Vue 迁移与发布

迁移 dashboard、Import Studio、release、dataset、content、publication、analytics、settings。

Import Studio 必须映射真实 manifest：Source → Context → Validate/Preview → Ingest → Verify → Publish/Complete。

S3 multipart/presign 保留；Vue 迁移不能改变 object-key ownership/checksum contract。

disabled capability 显示原因和 Gate，不提供点了必失败的假按钮。

高风险 release/publish/rollback 继续需要 RBAC、confirmation、reason、audit、idempotency。

---

# 12. Phase H — external/internal、SSG 与发布回归

必须生成独立 external/internal artifact。

回归：

- external HTML/JSON/JS/snapshot/search/SW 中 internal_id = 0
- unreleased sentinel = 0
- internal content = 0
- internal 需要真实 auth/edge protection
- 两站 cache key/service worker/analytics 不共享
- release/assembly deep-link 不静默掉到 active/default
- SSG 页面与 API live page 对同一 release 的核心事实一致

P1-1 只有真实 running API + seeded published release + unreleased sentinel + artifact scan + negative leakage 全绿后才能关闭。

---

# 13. Phase I — S3/MinIO 与数据发布回归

不删除 S3。重构重点是把 storage contract 稳定下来。

覆盖：

- Admin multipart create/sign/complete/abort
- SHA256 server verification
- bucket/key namespace
- user/job/dataset ownership
- public/private URL
- worker read/write
- GWAS input/output
- fastp/scanpy outputs
- module import object input
- backup/restore + version/checksum contract
- MinIO compose health
- failure/retry/cleanup

任何 Vue/API 重构导致这些接口变化，都必须同时迁移 API client、worker、tests、docs，并提供 backward/forward migration 方案。

---

# 14. CNB 作为 Docker 生产等价验收主骨架

官方 CNB 文档确认：.cnb.yml 是 Pipeline-as-Code；services: docker 启用 DinD 与 Docker CLI；CNB 会自动登录当前仓库 Docker 制品库；支持 Docker/buildx、registry cache、多架构 OCI、provenance/SBOM attestation、PR/push/tag 事件、runner CPU、附件制品和 Flow 可视化。

官方参考：

- https://docs.cnb.cool/zh/build/configuration.html
- https://docs.cnb.cool/zh/build/grammar.html
- https://docs.cnb.cool/zh/build/trigger-rule.html
- https://docs.cnb.cool/zh/build/build-env.html
- https://docs.cnb.cool/zh/build/pipeline-cache.html
- https://docs.cnb.cool/zh/artifact/docker.html
- https://docs.cnb.cool/zh/artifact/supported-manifest-types.html
- https://docs.cnb.cool/zh/build/migrate-to-cnb/migrate-from-github-actions.html

现有 .cnb.yml 已采用正确的关键模式，重构时继续复用 scripts/ci-job-steps.sh，禁止另写一套 CNB 专用测试逻辑。

## 14.1 CNB PR Gate

PR 只验证、不发布：

- frontend/type/lint/unit
- API + worker tests
- dependency governance
- contract tests
- external/internal artifact build
- changed Vue pages E2E
- real PostgreSQL integration
- real ClickHouse migration/import tests（相关变更时必须）
- MinIO/S3 integration（storage/import/analysis 相关变更时必须）

PR 是不可信事件，不给生产 registry/signing/publication secret。

## 14.2 CNB main push Gate

至少运行：

- full verification
- real ClickHouse migration
- MCP e2e
- linux/amd64 native image build
- linux/arm64 native image build
- docker run runtime smoke
- image architecture proof
- Trivy blocking scan
- SPDX SBOM
- validated runtime image package
- external/internal artifact verification

## 14.3 CNB Docker 制品

镜像命名使用 CNB_DOCKER_REGISTRY/CNB_REPO_SLUG_LOWERCASE 命名空间；commit SHA 作为不可变 tag；禁止仅依赖 latest。

buildx cache 使用 CNB registry cache；如果 BuildKit 较旧导致 cache manifest 404，按 CNB 官方建议使用 image-manifest=true,oci-mediatypes=true 或升级 BuildKit >=0.21。

## 14.4 CNB Runtime Stack Verification

镜像 build 成功不等于可发布。CNB 必须在 DinD 中对验证镜像执行真实运行链：

1. load/pull validated images。
2. 启动 disposable PostgreSQL、ClickHouse、Redis、MinIO。
3. 执行 migrations。
4. 启动 API/worker/MCP 必要服务。
5. health/live/ready。
6. seed minimal published release + unreleased sentinel。
7. API search/gene/mutant/variant smoke。
8. S3 put/head/get/checksum smoke。
9. ClickHouse read/write/finalize integration。
10. external/internal artifact negative leakage。
11. shutdown and assert no orphan containers/volumes。

所有 runtime smoke 尽量调用 scripts/smoke.sh、scripts/acceptance.sh、scripts/ci-job-steps.sh，不在 .cnb.yml 内重复业务逻辑。

## 14.5 CNB Tag/Release

Tag/release 只消费已经验证的 amd64/arm64 package，不重新 build。最终发布前核对 source revision、platform set、digest、SBOM、provenance、release manifest。

CNB Docker 制品库支持多架构 OCI index 和 buildx provenance/SBOM attestation，可作为 release evidence。

---

# 15. GitHub CI 的角色

GitHub 保留为代码协作与第二执行提供商；CNB 与 GitHub 必须调用同一 job body。

GitHub ruleset 建议：main 要求 PR + required checks；archive/** 限制更新/删除并 block force push。

官方 GitHub 文档确认 branch protection/ruleset 可阻止 force push、删除、限制更新并要求状态检查。

参考：

- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets

---

# 16. 完整测试链

任何 Phase 不能只跑自己的 unit test 后直接合并。按照风险逐层升级。

T0 Static/Contracts：format、lint、typecheck、OpenAPI/client、architecture boundaries、dependency governance、feature flag、migration/schema contracts、CI workflow contracts。

T1 Unit：Vue composables/stores/components、domain/view model、API services、worker parser/protocol、chart facade、storage key/security helpers。

T2 Component：Vue Testing Library/Vitest、Antdv facade、Pinia state、Vue Query mock boundary、TanStack Charts exact values/a11y、file viewer bounded preview。

T3 Real Data Services Integration：PostgreSQL、ClickHouse、Redis、MinIO；migration up、import manifest、staging/finalize、S3 multipart/checksum、Celery task integration。

T4 API Contract：public/internal/admin API；OpenAPI diff；RBAC；release/assembly；404 unpublished；presign ownership；rate limit/error semantics。

T5 Artifact/SSG：external/internal build、SHA256、CSP、SW/cache、sentinel negative leakage、route snapshot、asset integrity。

T6 Browser E2E：Home/Search/Gene/Mutant/Variant/Phenotype/JBrowse、Admin import/publish、auth、keyboard、mobile、back/forward URL state。

T7 Visual/A11y：390/1024/1440、light/dark/reduced-motion、axe、chart keyboard/linked-table、Gene Preview overlap/strand。

T8 Docker Runtime：CNB native image build、docker run smoke、compose stack smoke、migration、health、worker/MCP、S3/CH/PG。

T9 Security/Supply Chain：Trivy vuln/misconfig/secret、SBOM、license、secret scan、CSP、upload/path traversal/SSRF、container non-root/capabilities。

T10 Release/Recovery：backup/restore、rollback、publication exact bytes、release manifest/digest、failure injection、crash/retry/ambiguous ACK。

T11 Performance Regression：bundle budget、route chunks、chart render、search p50/p95/p99、analytics throughput、import rows/s/RSS、CI duration。只有建立 baseline 后才允许声称提升。

---

# 17. 固定回归主任务

每个里程碑至少回归：

1. Gene ID → Gene detail → mutant → variant → JBrowse。
2. Phenotype → mutant → genomic evidence。
3. Region → variants → variant detail → JBrowse。
4. Mutant public_id → phenotype/gene/variant/export。
5. Search exact ID/prefix/general + URL restore。
6. Admin upload S3 → bind release/assembly → validate → import → verify。
7. Failed import → diagnostics → safe retry。
8. Published vs unreleased sentinel isolation。
9. Backup → restore → checksum/data verification。
10. CNB validated image → docker run/compose → live/ready → API/S3/CH smoke。

---

# 18. Phase J — 仓库清理与 React 退役

先 inventory 再删：tracked generated、.tanstack/tmp、dead React hooks/components、ECharts helper/CDN config、旧 AntD facade、过期 docs、重复 CI、未引用 scripts。

删除门：git search 无生产引用；CI/test/docs 已迁；Vue parity 已过；archive baseline 可回查。

最终移除：react、react-dom、@tanstack/react-query、@tanstack/react-router、antd、@ant-design/icons、echarts、clsx、tailwind-merge，以及只服务旧栈的 active config。

历史 ADR/evidence/archive 不因清理删除。

---

# 19. Phase K — Rust

只在 P2 协议和真实性能 baseline 稳定后执行。

优先 kernel：streaming checksum、BGZF、VCF/BCF parse、batch assembly、GFF/GTF、FASTA。

Python 保留 FastAPI/ORM/Celery/RBAC/publication 控制面。

Go/No-Go：correctness parity 100%；真实数据吞吐显著提升；RSS 明显下降；amd64/arm64 CNB build；fuzz/property tests；维护成本可接受。

未达门槛 = NO-GO，不因已写 Rust 而上线。

---

# 20. PI-agent 并行策略

允许并行但必须控制冲突：

Lane DATA：Phase A P2 writer/finalize。
Lane TOOLCHAIN：Phase B pnpm12 + dependency catalog。
Lane FRONTEND-BASE：Phase C/D framework-neutral + Vue shell。
Lane CI：CNB/GitHub contract 与 runtime stack tests。

只有前置稳定后才开启：

Lane UI：Phase E/F charts/public pages。
Lane ADMIN：Phase G。
Lane CLEANUP：Phase J。
Lane RUST：Phase K。

同一路径禁止多个 agent 同时修改。任何 lane 合并 main 前必须 rebase/refresh main 后重跑受影响 Gate。

---

# 21. 每个 PI-agent 任务的最小交付格式

每个任务必须在 plan.md 对应 Phase 下回填：

Completed：具体修改。
Verified：真实命令 → 结果。
Tests：测试数、失败数、跳过原因。
CNB：build/run ID 或明确 BLOCKED。
Artifacts：digest/SHA/SBOM 路径。
Evidence：E0-E4。
Blocked：未完成门禁。
Regression impact：哪些固定主任务已重跑。
Commits：SHA + message。
Next：下一个唯一建议任务。

没有真实 CNB/服务凭据或执行环境时必须写 IMPLEMENTED_UNVERIFIED/BLOCKED，不得写 PASS。

---

# 22. 当前立即执行顺序

1. 在冻结基线不再修改的前提下，完成 baseline release evidence/package。
2. Phase A：P2-3A/P2-3B，继续数据正确性。
3. Phase B：pnpm 12 全仓统一。
4. Phase C：framework-neutral packages。
5. Phase D：Vue shell + Pinia4 + VueUse15 + Vue Query + Antdv Next + cn。
6. 同步加固 CNB runtime stack verification，确保新栈每一步都真实 Docker 可运行。
7. Phase E：TanStack Charts 全线替换 ECharts。
8. Phase F：按页面迁公共 Vue。
9. Phase G：迁 Admin，保持 S3/MinIO 协议。
10. Phase H/I：双站、SSG、S3、发布全回归。
11. Phase J：删除 React/ECharts/旧配置。
12. Phase K：在真实性能证据后迁 Rust kernels。

---

# 23. Definition of Done

全线重构完成必须同时满足：

- Vue 是唯一前端主框架；React active runtime 归零。
- pnpm 12 是 workspace 唯一包管理基线。
- Pinia/VueUse/Vue Query 职责清晰，无重复 server state。
- Antdv Next 通过 facade 使用，升级有 contract gate。
- TanStack Charts 是唯一通用图表引擎；ECharts active code 归零。
- Tailwind 4 + cn 通过兼容测试，clsx/tailwind-merge 可移除。
- S3/MinIO 上传、分析、导入、备份恢复能力无回归。
- P2 import no partial visibility / duplicate facts / unsafe retry。
- external/internal 无数据泄漏。
- Gene Preview 科学坐标/strand/release/assembly 正确。
- Admin import/publication 可恢复、可审计。
- CNB 对 amd64/arm64 真实 build + docker run/stack smoke + Trivy + SBOM 全绿。
- GitHub 与 CNB 不维护两套业务测试逻辑。
- 关键科研路径、视觉、a11y、性能、security、backup/rollback 回归全绿。
- 所有开启的 feature flag 有 Release Gate evidence。

> 最终优先级：数据正确性 > 隔离与安全 > 可回滚发布 > 可运行性 > 维护性 > 性能 > 新功能数量。任何重构若破坏前四项，立即停止并回滚到最近通过全部 Gate 的 commit。

---

# 24. 执行证据日志（Execution Evidence Log）

> 维护者：主执行代理（PI-agent）。每条 = 一个已合并/可预览单元。证据等级 E0 文档 / E1 代码确认 / E2 可重复测试 / E3 生产等价验证 / E4 staging 观察。未运行的门禁如实标注 BLOCKED，不计为通过。
>
> 执行环境限制（本机）：Node 24.19.0 / pnpm 11.21.0 / Python 3.14.6；PostgreSQL :55432 可用；**无 Docker/CNB、无 ClickHouse server、无 pnpm 12**。因此 T8/T9/T10 与真实 CH 集成本环境 BLOCKED。

## 已完成单元

### Phase C · framework-neutral seam
- `test(contracts): guard the framework-neutral seam` — `scripts/check_framework_neutral_packages.py` + unittest（禁止 react/vue/antd 进入中性包）。E2。
- `feat(query-keys): extract framework-neutral query key factory` — 新增 `@soymutdb/query-keys`，`apps/web` 以 re-export shim 消费（7 处调用零改动）。E2（web typecheck + 5 tests）。
- `feat(i18n): extract framework-neutral @soymutdb/i18n-core` — catalog/语言元数据下沉中性包；`@soymutdb/i18n` 变 react-i18next 适配层并 re-export；`check-locale-keys` 保留转发 shim。E2（i18n-core 6 tests、web/admin/jbrowse typecheck、CI locale gate 59 tests、web i18n-runtime）。
- `ci(frontend): enforce the framework-neutral seam in the shared gate` — seam guard 接入 `frontend` job body（CNB/GitHub 共用）。E2（本地确定性通过；**CNB 运行 BLOCKED**）。

### Phase A · shared import protocol（A1）
- `refactor(import): extract shared soymutdb-import-protocol` — fingerprint / manifest 状态机 / 可见性规则下沉为无依赖共享包 `packages/import-protocol`（`soymutdb-import-protocol`）；`apps/api` re-export 保持向后兼容；`apps/worker` 声明依赖（为 P2-3 worker 侧消费 manifest 铺路，符合 H4）。fingerprint 字节与 DB enum 名不变，无数据迁移。E2（contract 15 tests；apps/api import tests + migrations 27 passed vs PG；worker adapters 42 passed；ruff clean）。uv.lock 两端 +11 行、无版本漂移。

### Phase A · ClickHouse engine port + variant finalize protocol（P2-3，部分）
真实 ClickHouse 验收改用 **chdb（嵌入式单节点 ClickHouse 26.7，非 mock）**，作为 `apps/worker[dev]` 依赖；`scripts/verify-backend-tests.sh` 安装该 extra。提交链：
- `feat(import): add ClickHouse engine port + chdb acceptance engine` — `ClickHouseEngine` 端口 + `HttpClickHouseEngine`(生产 clickhouse-connect) / `ChdbEngine`(验收) 。
- `refactor(import-engine): share a single chdb session across acceptance tests` — 会话级 fixture + 每测试唯一 database；端口加 `query_rows`。
- `feat(import): add variant staging/verify/finalize protocol` — 只写 staging(无 MV) → `finalize_release`（先 purge 所有 release 维度 summary 一次 → drop 触及的 base 分区 → 从去重 staging 重写）。E2/E3 等价：`pytest tests/test_clickhouse_engine.py tests/test_variant_finalize.py` → 9 passed（真实引擎）。真实引擎还暴露并修复了一个 finalize 逻辑 bug（按分区逐个 purge 会抹掉同 release 其它分区刚写入的 summary）。

> P2-3 状态：**IN PROGRESS（协议实现 + 真实验证完成；待 CNB/能力重开）**。`import_vcf` 已接入协议并默认 OFF（flag 关→422，P1-2 保持）。已全部在**真实引擎**验证：chdb 13 tests（staging 隔离/双计危害/分区级幂等 finalize/校验门/失败矩阵）+ 真 PG manifest 6 tests + **端到端 `test_vcf_import`**（真 PG manifest+release/assembly 解析 + 真 chdb facts）：PUBLISHED、base=2、summary=2、按 fingerprint 幂等。**剩余**：CNB 分布式/集群 T8 运行验收、`SOYMUTDB_ENABLE_VCF_IMPORT` 能力重开（P2-6，Gate 于真实 CH/CNB 全绿）。

## BLOCKED（需环境凭据/服务，未冒充通过）
- **CNB / 分布式 ClickHouse cluster / T8-T10**：本机无 Docker/CNB；chdb 为单节点嵌入式引擎，可证 staging/finalize/汇总结算语义，但**不覆盖**分布式集群、`Atomic` 数据库引擎、副本去重 token 窗口；真实运行验收需 CNB。
- **Phase B pnpm 12**：本机无 pnpm 12 运行时 → BLOCKED。

## Next（建议）
1. P2-3 收尾：worker 侧 manifest(PG，sync) 生命周期集成（复用 `soymutdb-import-protocol` 契约，不 import API 运行时）→ `import_vcf` 在 flag OFF 下仍 fail-closed，flag 开启才走协议；补崩溃/重试/ambiguous-ACK/checksum-mismatch 矩阵（manifest 真 PG + CH 真实引擎）。
2. P2-4 `module_data_rows → canonical promotion`（纯 PostgreSQL，本机可全验）。