# SoyMutDB Next 项目更新执行提示词

> **已归档（2026-10-01）**：智能体执行日志与提示词草稿（治理要求工作区不存放日志）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §7 变更记录；执行结论见 docs/dev/project-status.md。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

将以下提示词完整复制给负责实施的智能体。方括号中的内容由任务发起人填写。

```text
你是 SoyMutDB Next 的实施智能体。你的任务是执行：

【任务名称】完整功能优化与架构升级
【执行模式】端到端执行；按本提示词的 Phase 0–8 逐阶段推进
【本次范围】公开门户、管理控制面、API/Worker/Rust 边界、数据发布、静态搜索、打包发布、UI/UX、测试、清理和文档
【验收目标】建立可治理的多物种静态科研门户：管理员可配置公开内容与模块，站点搜索快速可解释，所有发布可打包、追溯和回滚，且各层通过质量验证

## 0. 必读文件与唯一设计依据

先阅读并遵守以下文件，后者用于处理冲突时优先级更高：

1. `docs/superpowers/specs/2026-07-12-multispecies-portal-design-spec.md`
2. `docs/superpowers/plans/2026-07-11-multispecies-static-portal-roadmap.md`
3. `README.md`
4. `docs/design/architecture.md`
5. 目标目录及其父目录中的 `AGENTS.md`
6. 根目录 `skills/` 下与本任务匹配的 `SKILL.md`

开始前输出：本次目标、范围外内容、依赖的上一 Phase 验收证据、风险、回滚方式，以及预计修改的文件。若缺少上一 Phase 的验收证据，立即停止并说明阻塞原因。

本次是完整升级任务，不得只输出分析、单一页面、单个框架或局部代码。必须完成下文 Phase 0–8 所要求的审计、设计、实现、验证、清理和交付；任何阶段发现高风险问题时先修复该阶段问题，再进入下一阶段。

## 1. Skills 强制规则

只能使用仓库根目录 `skills/` 下的 skills。先检查 `skills/`，再读取每个实际使用的 `skills/<名称>/SKILL.md`。

本任务至少按需要选择并显式声明以下仓库内 skills：

- 架构/任务拆解：`skills/feature-planning/SKILL.md`
- Vite 与构建：`skills/vite/SKILL.md`
- pnpm / monorepo：`skills/pnpm/SKILL.md`、`skills/turborepo/SKILL.md`
- 前端/交互：`skills/frontend-design/SKILL.md`、`skills/react-best-practices/SKILL.md`
- 测试：`skills/test-driven-development/SKILL.md`、`skills/playwright-skill/SKILL.md`、`skills/webapp-testing/SKILL.md`
- 代码审查/验证：`skills/code-reviewer/SKILL.md`、`skills/verification-before-completion/SKILL.md`
- 重构和清理：`skills/code-refactor/SKILL.md`

按任务类型额外选用相关 skill，例如：

- API / 数据库：`skills/fullstack-dev/SKILL.md`、`skills/sql-expert/SKILL.md`
- 可访问性与 UI 检查：`skills/web-design-guidelines/SKILL.md`
- 复杂前端状态：`skills/composition-patterns/SKILL.md`
- 多智能体拆分：`skills/subagent-driven-development/SKILL.md`

交付报告中必须逐条写明“实际使用的 skill 名称 + 完整相对路径 + 用途”。不得使用、创建、复制、修改或提交 `skills/` 目录外的 skill；不得提交默认忽略的 `skills/` 内容。仓库中当前未发现知乎命名 skill；如需技术栈调研，必须记录此缺口，以官方文档、官方 Release、官方仓库和标准组织资料替代，不得谎称调用了知乎 skill。

## 2. 架构与产品硬边界

- 公开端是静态优先的 `apps/web`；公开页面不得直连数据库。
- 管理端 `apps/admin` 是受限控制面，必须保持 localhost / 内网边界。管理员可通过受审 API 与后台任务管理草稿、数据候选和发布，不得直接覆写生产数据库或公开静态文件。
- 不提前拆分微服务。优先保持模块化单体、明确模块契约和后台任务；只有性能、索引体积、构建时长或 SLO 数据证明瓶颈后才提出服务拆分。
- `dataset_release_id` 是科研数据快照；`publication_release_id` 是门户发布快照。二者严禁混用。页面、导航、站点地图、下载、静态实体页与搜索索引必须使用同一 `publication_release_id`。
- 科研对象、缓存、索引、下载和 canonical URL 必须使用合法作用域：`global`、`species`、`assembly`、`dataset`。不得给全局内容伪造物种、组装或数据发布外键。
- 新功能必须可扩展到多个物种。禁止复制大豆专用页面、路由和业务逻辑；物种专属数据放在适配器或扩展属性。
- 管理员配置只能引用注册模块和 JSON Schema；禁止管理员注入任意 JavaScript、模板表达式、内联 CSS 或未净化 HTML。
- 默认把动态 Widget 变为构建期内容。若科研模块必须运行时读取，请求、响应、缓存键与 HTML 元数据必须携带 `publication_release_id` 和对应 `dataset_release_id`；版本缺失时显示降级状态，严禁回退到“最新数据”。

## 3. 实施与代码规范

- 先写或更新测试，再完成最小实现；每个任务保持范围小、可回滚、可独立验证。
- 所有**新增自有**函数、变量、模块、类型、组件、服务、脚本与测试夹具统一使用 `rl_` 前缀。
- 下列名称不得为满足前缀而修改：第三方 API、框架约定、环境变量、数据库已有列、配置键、路由协议、测试框架钩子、已有公共接口或已有导出。
- 为新增业务规则、权限判断、版本转换、数据清理边界、兼容逻辑和非直观性能处理写简洁中文注释，解释“为什么”。不要为显而易见的语法写注释。
- 新 UI 必须保持科学数据阅读优先：物种、组装、数据发布、来源和引用信息始终可见；颜色不能作为唯一状态语义；尊重 `prefers-reduced-motion`；移动端不依赖 hover。
- 静态搜索必须明确区分本地已发布数据与 NCBI/UniProt/Ensembl 等外部来源。浏览器不得直连外部来源；外部查询只能经 API 适配器，并受限流、缓存、超时、净化与 circuit breaker 保护。
- 清理无用模块、死代码、重复配置、构建物或索引前，先完成引用分析、影响清单、验证与回滚确认。只删除本任务产生且确认无引用的内容；不得默认运行 `pnpm clean` 或 `make clean-all`。绝不删除 lockfile、有效制品、当前发布快照、`.env` 以外的用户配置或其他任务产物。

## 4. 打包、制品与发布衔接

实现必须保持此链路完整：

已审核配置和固定数据输入
→ dataset release 验证
→ 冻结 `PublicationManifest` / `publication_release_id`
→ Web SSG、搜索索引、Admin、API、Worker、Rust 分别构建
→ 测试、SBOM、SHA-256、OCR 证据
→ `artifacts/manifest.json`
→ 预览环境验证
→ 原子发布或回滚

每个构建制品必须可追溯到 Git commit、输入 lockfile 哈希、构建工具版本、SHA-256 和适用的 `publication_release_id`。发布器只能使用通过验证的 `artifacts/manifest.json`，不能直接发布工作区文件。失败制品必须隔离，不能覆盖公开版本。

## 5. 必须验证的内容

仅运行与本次修改边界匹配的命令，并在报告中说明未运行项及理由：

```bash
# Web / SSG
pnpm --filter @soymutdb/web lint
pnpm --filter @soymutdb/web typecheck
pnpm --filter @soymutdb/web test
pnpm build:web

# Admin
pnpm --filter @soymutdb/admin lint
pnpm --filter @soymutdb/admin typecheck
pnpm build:admin

# API
cd apps/api && pytest -v && ruff check . && mypy .

# Worker
cd apps/worker && pytest -v && ruff check . && mypy .

# 基础设施与确定性仓库审查
make build-docker
pnpm review
```

若涉及迁移，只能在 disposable 或 staging 数据库中进行。先断言 `APP_ENV=staging`、数据库主机不是生产地址且备份已完成；执行 upgrade → downgrade → upgrade、备份恢复和双读差异检查。禁止直接执行裸 `make migrate`；生产迁移只能由独立受审发布流程完成。

若涉及管理权限、审核、重新认证、冷静期或发布确认，必须新增并运行 Admin 测试：覆盖能力驱动的路由/控件可见性、服务端逐能力 allow/deny、提交者/审核者/发布者隔离、单管理员例外和异常路径。UI 隐藏不等于授权保护。

若涉及公开端发布，必须使用本次构建的静态产物：启动固定端口静态服务、验证页面 manifest 的 `publication_release_id` 与待验收快照一致，然后运行：

```bash
npx playwright test --config=tests/e2e/playwright.config.ts
```

覆盖键盘、可访问性、移动视口、禁用 JavaScript、Worker 失败、离线索引和模块显隐一致性。不得复用未知的 `localhost:8080` 服务。

## 6. Alibaba Open Code Review 强制门禁

固定使用官方 `@alibaba-group/open-code-review@1.7.7`。凭据只来自密钥管理：`OCR_LLM_URL`、`OCR_LLM_TOKEN`、`OCR_LLM_MODEL`，必要时 `OCR_USE_ANTHROPIC`。禁止将密钥写入仓库、日志或报告。

在完整 Git 历史、存在 `origin/main` 的环境中运行：

```bash
mkdir -p artifacts/ocr
export OCR_NO_UPDATE=1
pnpm dlx @alibaba-group/open-code-review@1.7.7 version
pnpm dlx @alibaba-group/open-code-review@1.7.7 llm test

BASE_SHA="$(git merge-base origin/main HEAD)"
HEAD_SHA="$(git rev-parse HEAD)"
pnpm dlx @alibaba-group/open-code-review@1.7.7 review \
  --from "$BASE_SHA" \
  --to "$HEAD_SHA" \
  --format json \
  --audience agent \
  > artifacts/ocr/review.json.tmp \
  && mv artifacts/ocr/review.json.tmp artifacts/ocr/review.json
```

CI 必须使用 `fetch-depth: 0`。未提交工作区变更则使用固定版本的 `review --format json` 并输出 `artifacts/ocr/worktree-review.json`。OCR 命令失败、JSON 无法解析和“无问题”必须分开报告。

以下边界变更除 diff review 外，必须运行对应 scan 并输出 JSON：

```bash
pnpm dlx @alibaba-group/open-code-review@1.7.7 scan --path apps/api --format json > artifacts/ocr/api-scan.json.tmp && mv artifacts/ocr/api-scan.json.tmp artifacts/ocr/api-scan.json
pnpm dlx @alibaba-group/open-code-review@1.7.7 scan --path apps/web --format json > artifacts/ocr/web-scan.json.tmp && mv artifacts/ocr/web-scan.json.tmp artifacts/ocr/web-scan.json
pnpm dlx @alibaba-group/open-code-review@1.7.7 scan --path apps/admin --format json > artifacts/ocr/admin-scan.json.tmp && mv artifacts/ocr/admin-scan.json.tmp artifacts/ocr/admin-scan.json
pnpm dlx @alibaba-group/open-code-review@1.7.7 scan --path infra --format json > artifacts/ocr/infra-scan.json.tmp && mv artifacts/ocr/infra-scan.json.tmp artifacts/ocr/infra-scan.json
```

关闭本次变更引入的所有阻断级和高风险问题。既有问题与误报必须附带定位证据、责任人、期限或正式驳回记录。OCR 不能替代构建、测试、安全、性能、可访问性和科研数据人工审核。带 OCR 凭据的 CI 仅审查 diff，不执行不可信 PR 的代码。

## 7. 必须执行的端到端工作流

### Phase 0：仓库审计、基线与工作清单

1. 读取根清单、锁文件、Turbo/Makefile、Docker/Nginx、现有设计文档、所有目标目录的 `AGENTS.md`，再定位 Web、Admin、API、Worker 和 Rust 的真实入口。
2. 建立基线清单：现有功能、路由、管理员能力、数据模型、硬编码大豆语义、动态 Widget、搜索数据流、构建产物、测试覆盖、死代码候选、重复配置和过期依赖。
3. 运行不修改数据的基线检查：对应 lint/typecheck/test/build、`pnpm review`，以及 `ocr scan`。将已存在的失败与本次引入问题分开记录。
4. 输出并保存升级任务分解：每项任务必须写明目标、修改边界、依赖、测试、回滚和验收标准。不要在没有清单和基线的情况下开始重构。

**完成条件：** 已有可追溯的基线、风险清单、阶段任务表和明确的不可修改边界。

### Phase 1：统一领域与发布基础

1. 建立或完善多物种核心模型：`Species → Assembly → DatasetRelease → Gene/Variant/Line/Annotation/Evidence`。
2. 实现不可变公开标识和 canonical URL；旧大豆短路由只能在唯一匹配时重定向，否则提供可解释的迁移页面。
3. 严格分离 `dataset_release_id` 与 `publication_release_id`；为旧 `Release` 和既有对象建立兼容映射，避免一次性破坏既有 API。
4. 建立能力权限而非隐式角色层级；实现服务端 allow/deny、重新认证、审核/发布职责隔离、单管理员例外及追加式审计 outbox。
5. 为领域迁移和权限迁移写测试，运行 staging 升级/降级、备份恢复和大豆双读差异检查。

**完成条件：** 大豆现有功能未回归；Auditor 没有写权限；数据标识、权限和审计可以安全支撑后续发布与多物种功能。

### Phase 2：发布快照、打包与回滚体系

1. 实现 `PublicationManifest` 与原子 `publication_release_id` 指针，冻结内容、模块、导航、数据版本、索引和下载文件。
2. 建立 Web SSG、静态搜索索引、Admin、API、Worker、Rust 的独立且可复现构建流程。
3. 每次构建输出 `artifacts/manifest.json`、SBOM、制品 SHA-256、输入 lockfile 哈希、构建工具版本、Git commit 和适用发布版本。
4. 构建预览环境验证、失败制品隔离、Nginx/CDN 原子切换和按完整制品清单回滚。禁止混搭不同快照的 HTML、索引、下载或服务版本。
5. 清理旧构建链中无引用且已确认过期的脚本、目录和重复配置；先做引用分析与回滚检查。

**完成条件：** 可从固定输入重复构建；预览只消费已验证制品；回滚演练恢复同一完整快照。

### Phase 3：管理员控制面与内容编排

1. 完善 Admin 的 Overview、Catalogue、Data Operations、Public Experience、Quality & Publishing、Governance 工作区。
2. 让管理员可管理物种、组装、数据发布、页面、多语言内容、SEO、导航、注册模块、模块排序、显示/隐藏、时间窗口和无数据替代说明。
3. 将模块配置限制为 JSON Schema；禁止任意 HTML、模板、脚本和样式注入。实现全局/物种/组装/数据发布范围化 `ModuleAvailability` 与确定性冲突规则。
4. 完成草稿、影响分析、私有预览、审核、发布、审计、回滚流程。关闭模块时必须同步更新导航、首页、站点地图、搜索筛选和深链处理。
5. 编写 Admin 和 API 集成测试，验证 RBAC、越权拒绝、提交者/审核者/发布者隔离、模块显隐、审计事件和失败恢复。

**完成条件：** 管理员无需写代码即可安全编排公开体验；未审核内容无法公开；模块状态在同一发布快照内一致。

### Phase 4：公开门户 UI/UX 与多物种体验

1. 将所有公开页面升级为“物种 + 组装 + 数据发布版本”可见、可切换、可分享的科学上下文。
2. 实现/优化物种目录、物种主页、基因/变异/材料浏览、详情页、下载、浏览器入口、帮助和引用信息；不为第二物种复制页面实现。
3. 统一设计 `rl_species_context_bar`、`rl_species_switcher`、`rl_module_availability_guard`、`rl_scientific_breadcrumbs`、`rl_search_scope_control` 与 `rl_comparison_basket` 等组件，保持科学阅读优先。
4. 完成桌面、平板、手机适配；处理无数据、未发布、下线、跨物种、跨组装和低带宽状态；键盘与屏幕阅读器可完整操作。
5. 移除或替换大豆硬编码文案、默认染色体常量和不能扩展的页面分支；保留兼容入口并避免死链。

**完成条件：** 大豆和第二物种使用同一页面、组件和导航模型；物种/组装/发布信息在搜索、详情、下载和引用中一致可见。

### Phase 5：静态搜索与外部检索

1. 从已发布数据构建按物种、实体类型和语言分片的 `SearchManifest`；索引必须有 schema、发布版本、内容哈希、压缩/未压缩大小、内存估算和记录数。
2. 在 Web Worker 中实现 ID、别名、标题和描述搜索，支持 Unicode 规范化、稳定排序、去重、取消、分页和失败状态。
3. 默认仅加载当前物种索引；首次无上下文访问不下载科研索引；全物种检索按需加载分片。Worker 不可用时遵守索引大小、记录数和内存阈值，否则转到预生成目录。
4. 把 NCBI/UniProt/Ensembl 放在独立“外部来源”区域；只通过 FastAPI 适配器访问，处理缓存、限流、超时、净化、CSP/CORS、隐私日志和 circuit breaker。
5. 建立索引字段白名单、敏感信息扫描、离线/低网络降级、缓存更新和旧索引清理机制。

**完成条件：** 用户明确知道搜索范围、数据来源、索引版本与降级状态；本地静态数据与外部结果绝不混淆；移动端搜索不阻塞主线程。

### Phase 6：第二物种真实发布与数据质量

1. 选择许可、来源和规模均明确的第二物种；建立 Species、Assembly、DatasetRelease、导入适配器、数据质量验证和来源/引用信息。
2. 生成第二物种静态页、搜索索引、下载、浏览器配置和发布快照。
3. 验证跨物种隔离：不得依据相同名称或坐标自动关联；比较只通过带证据的同源关系；缓存、URL、索引和下载不冲突。
4. 与大豆并行验证核心页面、搜索、统计、打包、发布和回滚；消除任何复制实现。

**完成条件：** 至少两个物种已通过同一数据模型、控制面、SSG、搜索和发布流水线正式发布。

### Phase 7：技术栈更新、性能和可靠性优化

1. 从官方文档、官方 Release、官方仓库、标准组织和同行评议资料建立技术雷达；没有仓库内知乎 skill 时如实记录，不得伪造调用。
2. 对每个候选升级评估稳定版本、兼容性、维护状态、收益、迁移成本、供应链风险、性能影响、试点结果与回滚方案；只采用当前稳定且有明确收益的技术。
3. 优化 SSG 体积、资源压缩、缓存、索引分片、Worker、图片/字体、渲染路径、数据库查询、Redis 缓存、后台任务和 Rust 热路径；所有优化以测量数据为前提。
4. 为性能、可靠性、可访问性和安全建立预算、监控、告警、健康检查和运行手册。

**完成条件：** 性能优化有前后指标；技术升级有 ADR 和回滚；不因追逐最新版破坏可复现构建或兼容性。

### Phase 8：清理、全量回归与交付

1. 删除已确认无引用的死代码、旧页面分支、重复配置、废弃依赖、过期构建脚本、无效测试夹具、临时文件和无引用索引；每项删除前后都验证引用和行为。
2. 运行全量相关测试、构建、静态发布验收、可访问性/移动端验证、OCR review/scan、依赖/制品检查和回滚演练。
3. 更新项目架构文档、运行手册、升级记录、迁移说明、管理员使用说明和已知限制；所有新增文档保持与实现一致。
4. 输出最终变更报告、制品清单、测试证据、OCR 报告、性能对比、清理清单、发布步骤、回滚步骤和未决风险。

**完成条件：** 所有功能、架构、UX、打包、清理和验证证据完整；不存在未解释的高风险问题；其他智能体可依据交付物继续维护。

## 8. 最终交付格式

完成后严格按下列结构报告：

1. **完成内容**：按功能和文件列出变更。
2. **架构衔接**：说明本次如何保持 dataset release、publication release、构建制品与发布/回滚的一致性。
3. **使用的 Skills**：每项为“名称 — `skills/<名称>/SKILL.md` — 用途”。
4. **验证证据**：每条命令、结果、跳过原因；包含 OCR JSON 文件路径与风险处理结果。
5. **制品与发布影响**：`artifacts/manifest.json`、哈希、SBOM、受影响 `publication_release_id`、预览与回滚步骤。
6. **清理确认**：删除目标、引用分析结果、验证结果；明确未删除 lockfile、依赖、当前发布制品或其他任务产物。
7. **未决风险**：风险、影响、责任人、截止时间、建议的下一步。
8. **Phase 完成矩阵**：Phase 0–8 的状态、交付物路径、验收证据、阻塞项。
9. **优化结果**：功能改进、UI/UX 改进、架构改进、构建/制品改进、性能前后对比、删除内容列表。

没有实际验证证据时，不得声称任务完成。
```
