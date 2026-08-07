# Ontology PostgreSQL Control Plane Master Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` (or an equivalent bounded task-by-task execution workflow) for every implementation phase. This document is the orchestration plan; the seven child plans remain the source of truth for code-level TDD steps.

**Goal:** 在用户已确认、Oracle Gate 1 已批准的 ontology/PostgreSQL control-plane 设计上，按可审计依赖、互不重叠的写入车道和逐阶段 Oracle 复核，协调 A0→F 的实施、验证、回滚和证据收口。Oracle Gate 2 必须先批准或修订本主计划；在 Gate 2 通过前不得开始任何产品实现、数据库迁移、依赖变更或部署修改。

**Architecture:** 受限 Admin 控制面 → FastAPI 模块化单体 → PostgreSQL 权威治理/审批/manifest/审计账本 → 冻结输入的 Worker/SSG/Search Builder → 不可变对象制品与静态优先公共门户；Internal Search 与 External Search 物理、语义、缓存、错误和版本隔离。Redis 只作缓存、锁、限流、进度和受控去重，不能成为科学事实、发布真相或永久审计权威。

**Tech Stack:** 保留现有 FastAPI、SQLAlchemy、Alembic、PostgreSQL、Celery/Redis、React/Vite/Tailwind/TanStack/Radix、TypeScript Worker、MinIO/S3/POSIX-compatible artifact provider、Nginx/CDN、JBrowse 和现有测试工具。不得捆绑 Node、Vite、FastAPI、PostgreSQL、Redis、Celery 或其它版本升级；不得无测量增加搜索集群、图数据库、微服务或新控制面服务。

---

## 0. 计划性质、授权和协调状态

本文件是**主编排/委派计划**，不是产品实现授权，也不是七份子计划的替代品。子计划是代码级文件清单、TDD 红—绿—重构步骤、窄验证命令和具体回滚边界的唯一来源；本文件只规定顺序、阶段门、写入所有权、调度和跨计划证据。

已批准/协调依据：

- 设计规范：[`docs/superpowers/specs/2026-07-15-ontology-postgresql-control-plane-design.md`](../specs/2026-07-15-ontology-postgresql-control-plane-design.md)
- 技术研究：[`docs/research/2026-07-19-technology-stack-and-comparable-projects-research.md`](../../research/2026-07-19-technology-stack-and-comparable-projects-research.md)
- Deepwork 协调状态：[`.slim/deepwork/ontology-postgresql-refactor.md`](../../../.slim/deepwork/ontology-postgresql-refactor.md)
- 子计划：A0、A1、B、C、D、E、F，见下方 DAG 和链接。

当前工作目录**不是 Git repository**。因此本计划不要求 worktree、branch、commit、merge、push 或 PR；也不执行任何自动 Git 动作。若未来变为 Git repository，任何 implementation mutation 在 repo/user policy 允许的前提下，必须先使用隔离 worktree；仍不得自动提交或推送，除非用户另行明确授权。未授权的生产迁移、生产写入切换、部署变更和依赖升级均停止。

所有新第一方函数、变量、类型、组件、服务、脚本和测试夹具使用 `rl_` 前缀；框架入口、迁移文件名、第三方 API、配置键、既有公共接口和数据库协议名遵循其既有约定。非显然的授权、版本转换、迁移安全、范围隔离和性能取舍添加简短中文 why-comment。公共端 static-first；不直连公共 DB；PostgreSQL 为 authority；Redis 非 authority；两个搜索系统严格隔离；Admin 只能选择服务端登记的 ID，不接受任意路径、URI、Shell、secret、连接串或环境变量；credentialed CI 不运行不可信 OCR/PR checkout。

所有适用阶段必须在 `skills/` 声明新增本地 skill；skill 声明属于实施阶段相应 ownership，不在本主计划文档任务中提前创建。F 计划明确要求 `skills/ontology-postgresql-control-plane/README.md`，其余阶段若实际引入 repository-local skill，须在该阶段入口证据中声明并在退出包中列出。

## 1. 七份子计划和依赖 DAG

### 1.1 子计划索引

1. [A0 factual reconciliation](2026-07-19-a0-factual-reconciliation-implementation-plan.md)
2. [A1 control-plane safety](2026-07-19-a1-control-plane-safety-implementation-plan.md)
3. [B dual-species ontology/data](2026-07-19-b-dual-species-ontology-data-implementation-plan.md)
4. [C deterministic publication](2026-07-19-c-deterministic-publication-implementation-plan.md)
5. [D isolated dual search](2026-07-19-d-isolated-dual-search-implementation-plan.md)
6. [E scientific public/Admin UX](2026-07-19-e-scientific-public-admin-ux-implementation-plan.md)
7. [F verification/OCR/cleanup](2026-07-19-f-verification-ocr-cleanup-implementation-plan.md)

### 1.2 固定 DAG

```text
A0 factual reconciliation
  → A1 control-plane safety
    → B-pre-ADR
      → B ontology/data foundation
        → C deterministic publication/promotion
          → D isolated dual search
            → E scientific public/Admin UX
              → F verification/OCR/cleanup/final evidence
```

`B-pre-ADR` 是 Plan B 内的**命名闸门**，不是可独立跳过的第八份计划。它必须在 B 的生产/expand migration 之前完成，并冻结双物种 walking skeleton、对象存储/provider 观察、RPO/RTO、压缩/规模数据和 D 所需的初始静态搜索上限。D 和 E 均不能因为 B 的部分代码已存在而提前开始：D 必须等待 C 的 artifact/projection/promotion 边界与 B-pre-ADR 搜索 cap；E 必须等待 A0、A1、B、C、D 全部通过。F 等待全部 A0–E。

同一阶段内禁止重叠 writer lane。可并行的 lane 只能是 read-only reconnaissance、质量检查、设计 handoff、测试审阅和证据整理；所有会修改实现代码、迁移、契约或共享导出面的 lane 必须顺序执行，或拥有严格不相交目录并由唯一 owner 复核。

## 2. Oracle Gate 2：实施前总闸

### 2.1 Gate 2 必须收到的 review packet

- 本主计划和七份子计划的确切路径、版本/mtime、链接可达性。
- DAG、B-pre-ADR 的位置、C/D/E/F 的前置关系和每阶段停止条件。
- 每阶段 writer ownership matrix；证明没有同阶段共享文件重叠写入。
- 当前非 Git 状态和未来 Git repository 时的隔离 worktree policy；无自动 Git 行动声明。
- A0 的 observational boundary、A1 的 deny-first safety boundary、B 的 expand-only/双物种边界、C/D 的验收分工、E 的 designer intent handoff、F 的 focused-to-broad 收口边界。
- `rl_`、中文 why-comment、PostgreSQL authority、Redis non-authority、static-first、双搜索隔离、registered Admin inputs、public projection allowlist、OCR trust boundary 等共享约束清单。
- Phase 2 readiness checklist 的逐项状态：`PASS`、`BLOCKED`、`NOT APPLICABLE`，每项带 owner、evidence path、digest 和下一动作。
- 风险登记表、触发器、停止响应和恢复/forward-fix 策略。
- 预定的 evidence index 格式和每阶段 Oracle input/output contract。

### 2.2 Oracle Gate 2 的精确输入/输出

**输入必须是：** 本主计划、七份 child plans、批准 spec、研究 report、Deepwork state、当前工作树状态（只读）、Phase 2 readiness checklist 和 ownership matrix。不得只凭口头摘要或“文档看起来完整”批准。

**Oracle 输出必须是机器可引用的书面 verdict：** `APPROVE`、`APPROVE_WITH_REQUIRED_EDITS` 或 `BLOCK`；逐项列出 DAG/ownership/validation/rollback/authority/安全/证据问题，引用文件与章节；对每个 finding 给出 `keep`、`simplify`、`fix-before-implementation` 或 `defer-with-ADR`；明确是否授权进入 A0 writer dispatch。只有 `APPROVE`，或所有 `APPROVE_WITH_REQUIRED_EDITS` 已由 bounded documentation writer 修复并再次获得 `APPROVE`，才可开始 A0。Oracle 不得以“计划已写完”替代实现证据；Gate 2 通过记录本身必须进入 Deepwork state。

## 3. Phase 2 readiness checklist（精确入口清单）

未来 orchestrator 在 dispatch A0 前必须逐项记录以下结果；任何 `BLOCKED` 都不得进入 implementation：

1. **文件完整性：** 七个 child plan 和本 master plan 均存在，路径精确，链接可读；无 secret、token、credential 或用户粘贴的 secret。
2. **设计授权：** spec 明确记录用户“确认设计”、Oracle Gate 1 最终通过；未把 Gate 1 误写成 implementation authorization。
3. **Gate 2：** Oracle 已对 master plan 给出最终 `APPROVE`，所有 required edits 已复核；Oracle 输入/output 和时间/证据 digest 已登记。
4. **DAG：** A0→A1→B-pre-ADR→B→C→D→E→F 顺序被调度器加载；B-pre-ADR 被标记为 Plan B 的硬 gate；没有 downstream job 可绕过前置状态。
5. **工作树安全：** 当前 `git rev-parse --is-inside-work-tree` 事实记录为非 Git；不要求 worktree/branch/commit。若状态改变，下一次 mutation 前已有隔离 worktree 计划和用户/repo policy 检查。
6. **写入所有权：** A0–F 每阶段的目录/文件 ownership 已登记；共享 API/client/index/style 导出面有唯一 writer；read-only/quality/design lanes 没有写权限。
7. **A0 入口：** A0 writer 只获 observational reconciliation、测试 fixture、工具和指定 evidence 区域；尚未授权新业务模型、新 migration、生产写入或 publication。
8. **共享约束：** `rl_`、中文 why-comments、PostgreSQL authority、Redis non-authority、static-first、双搜索隔离、无 arbitrary Admin infra inputs、无 direct public DB access、无新 cluster/microservice/version upgrade 默认策略已加载。
9. **安全和秘密：** credentialed CI/OCR 仅可对受信任 checkout；不可信输入不得在 credentialed job 执行；任何 artifact/evidence 只允许脱敏 digest、路径和结果。
10. **技能声明：** 当前阶段实际要使用的 repository-local skills 已在 `skills/` 计划中声明；若无新增 skill，记录 `none`，不可凭空宣称已使用。
11. **验证工具：** A0 的 Python/PostgreSQL/Alembic/Testcontainers/backup 工具可用性已记录；不可用项标记 conditional skip，不可伪造 pass。
12. **协调状态：** `.slim/deepwork/ontology-postgresql-refactor.md` 已记录“主计划 Gate 2 前禁止实现”；未来每个 terminal phase 都必须更新该文件。
13. **用户边界：** 未授权 commit、push、deploy、upgrade、production migration、production cutover；任何需求扩张需停线并形成 ADR/新 review。
14. **Oracle 调度：** 每 phase 都有明确 Oracle input/output packet 模板，且没有“documentation claim alone”作为 exit evidence。

## 4. 阶段编排、所有权和 Oracle contracts

以下每个 phase 的目录是**具体允许写入区域**，按 role 而不是实际 agent ID 指定。实现者仍必须逐项遵守对应 child plan 的更细文件 ownership；未列出的文件默认为 read-only。

### Phase A0 — 事实、契约与迁移闸门

**Child plan：** [A0](2026-07-19-a0-factual-reconciliation-implementation-plan.md)。

**入口 evidence：** Gate 2 `APPROVE`；当前非 Git 状态；设计/研究/Deepwork 链接；A0 只能做 observational reconciliation；无生产 DB write、无新业务 migration、无版本升级。

**写入 ownership：**

- reconciliation/tools writer：`tools/a0/`、`docs/reconciliation/a0-*`、`artifacts/a0/`（只写脱敏事实/命令输出）。
- migration-test writer：`apps/api/tests/a0/`，可按 child plan 增加独立 migration-backed fixture；不得修改生产模型或既有 migration。
- contract-evidence writer：A0 指定的 OpenAPI/client/Admin/Worker evidence 文件区域；不得修改 `packages/api-client` 或 Admin 产品实现。
- quality/read-only lane：读取 `apps/api/`、`migrations/`、Compose、deploy、Worker、Web、Admin，输出 review findings；不得写上述实现区域。

同阶段不允许两个 writer 修改同一 script、fixture、report 或 evidence manifest；reconciliation report 和 evidence emitter 由单一 owner 顺序写入。

**mandatory validation evidence：** README/API/Worker/Node runtime reconciliation；Alembic head/current/revision graph；实际 schema、ORM metadata、OpenAPI/client/Admin/Worker map；`upgrade → 可逆部分 downgrade → upgrade`；空库重建；backup/restore；legacy Release 逐条分类；unresolved JSONL；所有日志/manifest 脱敏。`Base.metadata.create_all()` 只能是对照，不能是迁移 pass。

**exit criteria：** 实际 schema/revision/ORM 差异逐项解释或进入 unresolved；wiring path mismatch 有证据；consumer map 齐全；迁移和恢复 rehearsal 可重放；缺证据的旧 Release 未被升级为 PublicationRelease；无 package-upgrade mandate。

**rollback/stop：** 任何生产连接、生产写入、生产 migration、新领域表、secret 输出、ORM-only 被当 deployed fact、失败被吞掉或 `create_all()` 被当迁移验证，立即停止；删除/销毁仅限 disposable DB/artifact，保留 logs/digest/unresolved。不得用新 migration 掩盖事实差异；回到 A0 reconciliation。

**Oracle input：** A0 evidence index、runtime/wiring report、schema/ORM/OpenAPI report、legacy classification、unresolved JSONL、Alembic logs、schema signatures、backup/restore digest、focused test results、所有阻断项及处理状态。

**Oracle output：** `PASS_TO_A1` 或 `BLOCK_A0`；逐项确认“事实而非推断”“迁移 rehearsal 而非 create_all”“旧 Release evidence gate”“无升级授权”；列出必须修复的 evidence/可读性/简化问题。所有 actionable finding 在进入 A1 前修复并重跑受影响窄测。

### Phase A1 — 控制面安全骨架

**Child plan：** [A1](2026-07-19-a1-control-plane-safety-implementation-plan.md)。

**入口 evidence：** A0 Oracle `PASS_TO_A1`；无未解释阻断事实；A0 consumer/wiring/recovery package 已归档。

**写入 ownership：**

- API control-plane writer：`apps/api/app/control_plane/`、A1 允许的 `apps/api/app/models/control_plane.py`、`apps/api/app/schemas/control_plane.py`、`apps/api/app/workers/rl_control_plane_relay.py`、A1 tests。
- Worker registry writer：`apps/worker/src/soymutdb_worker/control_plane_registry.py`、`apps/worker/src/soymutdb_worker/tasks/control_plane.py`、对应 tests。
- client/Admin safety writer：`packages/api-client/src/control-plane.ts`、其 test；`apps/admin/src/lib/control-plane-api.ts`、capability/legacy/reauth components/routes 和对应 tests。
- quality lane：只读检查旧 RoleName/auth/AuditLog/legacy routes、contract/E2E/concurrency evidence；不得写 B–F 目录。

同阶段 API、Worker、client/Admin 可在不共享文件的前提下并行；共享 OpenAPI export、router registration、client index 和 auth context 由单一 integration writer 顺序合并。不得并行修改同一 router、共享 index 或数据库 migration。

**mandatory validation evidence：** deny-first capability matrix；typed command canonical digest、registered IDs、idempotency conflict；approval binding、quorum、expiry、职责分离；三条独立 append-only histories；audit/task outbox 同事务且语义分离；ledger hash chain/retention/hold；relay/task registry；reauth/break-glass 默认关闭；Admin truthful 403/disabled/legacy；API/Worker/client/Admin/E2E/concurrency focused tests。

**exit criteria：** A1 不制造 dataset/publication/artifact success；失败、拒绝、超时、投递失败均有 failure audit；Redis/Celery/UI 不能制造 success；旧接口兼容但无新 capability 时 truthful 403/disabled；无任意 path/URI/shell/secret 输入。

**rollback/stop：** 发现旧 AuditLog 被当新 ledger、180-day cleanup 触及高风险证据、UI 隐藏替代后端授权、Redis lock 被当正确性、未来对象被伪造、普通 update/delete 可改历史，立即停止并回滚 A1-only disposable schema/feature projection；已产生的新事实优先 append correction/forward-fix，不覆盖历史。回到 A0/A1 contract。

**Oracle input：** A0 PASS；A1 capability/command/approval/history/outbox/ledger/registry/reauth evidence；migration/recovery evidence；API schema/client diff；permission/concurrency/E2E results；Admin affordance screenshots/trace；`rl_`/why-comment scan。

**Oracle output：** `PASS_TO_B_PRE_ADR` 或 `BLOCK_A1`；必须明确三历史、两个 outbox、Redis non-authority、deny-first、break-glass 和 truthful Admin 是否闭合，并输出 `keep/simplify/fix-before-next-phase/defer-with-ADR`。修复 findings 后只重跑受影响 focused tests，再重新提交。

### Phase B-pre-ADR — Plan B 内的双物种 walking skeleton 与容量边界闸

**Child plan：** [B](2026-07-19-b-dual-species-ontology-data-implementation-plan.md)，仅执行其 B-pre-ADR 部分。

**入口 evidence：** A0 和 A1 Oracle PASS；第二物种 fixture-selection decision 有 Data Steward/Reviewer 签字；controlled/disposable 环境已准备；不得写生产 schema。

**写入 ownership：**

- data-plane fixture writer：`apps/api/tests/fixtures/rl_dual_species/`、B walking-skeleton tests、controlled evidence/artifact prefix。
- bounded service/worker writer：仅 B child plan 指定的 `rl_scope_service.py`、`rl_dataset_service.py`、`rl_legacy_adapter.py` 和已核实注册路径的受控 import seam；不得写生产 migration、ClickHouse 主表或 public pointer。
- benchmark/provider observation writer：B-pre-ADR evidence/benchmark 输出区域；只记录真实规模、provider capabilities、RPO/RTO、ClickHouse proof 和搜索 cap。
- read-only/quality/design lane：审阅物种选择、许可证、scope、legacy dual-read、ClickHouse query 和静态/search fallback；不得改 fixture/service。

同阶段 fixture、service、benchmark writer 不得共享同一 fixture 或 evidence manifest；walking skeleton integration writer 最后顺序整合。

**mandatory validation evidence：** 大豆+第二物种 TaxID/name/assembly/source/license；Species→AssemblyScope→scientific object→DatasetRelease→ObjectVersion→manifest→raw artifact→最小页面/search/download；跨物种 identity 不碰撞；legacy dual-read differences/unresolved；ClickHouse non-destructive scope proof；raw/compressed/decompressed bytes、object/doc/shard counts、Worker memory/load/query P50/P95、provider read-after-write/CAS/Range/CORS、RPO/RTO；固定 `max_shards`、`max_documents`、timeout、limit、memory ceiling 和 fallback。

**exit criteria：** 两物种 walking skeleton 完整通过；cap 已由 measured evidence 冻结；provider/ClickHouse boundary 有结论；必要 ADR 输入已登记但没有擅自升级/换引擎；B migration gate 明确 `PASS` 或 `BLOCKED`。

**rollback/stop：** 第二物种被伪造为改 species 字符串、scope mismatch 被 resolved、license unknown 进入 public manifest、ClickHouse 需要 destructive DDL、搜索超 cap 却无 bounded fallback、生产 schema 被修改，立即销毁 controlled DB/prefix/proof DB（保留证据）并停止；任何新 runtime/engine 进入 ADR，不在 B-pre-ADR 直接采用。

**Oracle input：** A0/A1 PASS；fixture decision；双物种 walking-skeleton logs/digests；scope/legacy/unresolved report；ClickHouse proof；provider capability matrix；capacity benchmark；RPO/RTO/cache/recovery observations；搜索 cap proposal。

**Oracle output：** `PASS_TO_B` 或 `BLOCK_B_PRE_ADR`；明确第二物种、初始 search ceilings、provider/RPO/RTO、ClickHouse non-destructive boundary 和 representation policy 是否被接受；任何超 cap 或新 runtime 需求必须输出独立 ADR 要求。

### Phase B — 领域兼容层与 ontology closure

**Child plan：** [B](2026-07-19-b-dual-species-ontology-data-implementation-plan.md)。

**入口 evidence：** A0、A1、B-pre-ADR Oracle PASS；A0 确认的 Alembic head/schema/wiring；B migration 有 expand-only 允许边界；双物种和 cap evidence 可追溯。

**写入 ownership：**

- domain model/migration writer：`apps/api/app/models/rl_*.py`、B 指定 services、经 A0 确认的 `apps/api/migrations/versions/` 新 expand revision、B migration tests。
- ontology/import writer：`rl_ontology.py`、`rl_assertion.py`、`rl_import.py`、ontology/import/diagnostic tests 和已核实 Worker task registry seam。
- compatibility/ClickHouse writer：`rl_legacy.py`、legacy adapter、受控 scope-binding proof 和 tests；不得改旧 PK、variant_facts 主排序/分区或做全量 rewrite。
- read-only/quality lane：审核 scope/identity/closure/license/diagnostics/PO decision；不得写模型/migration。

同阶段 migration writer、ontology writer、legacy writer 不可同时编辑 `models/__init__`、router registry、migration head 或共享 fixtures；按 child-plan TDD 顺序串行整合。

**mandatory validation evidence：** expand migration 的真实 Alembic upgrade/downgrade/re-upgrade；Species/Assembly/ScientificObject identity（Transcript parent scope）；DatasetRelease/ObjectVersion/ChangeSet/manifest；legacy mapping unresolved；NCBI Taxonomy、GO、SO、RO、ECO release-set closure、dependencies、TaxID/ECO mapping、license；asserted-only、qualifier/negation/relation boundary、diagnostics/retry/cancel；PO deferred decision；ClickHouse scope proof；双物种真实/受控小样本。

**exit criteria：** 新表/约束/服务在 A0 事实基础上 expand-only；旧 Gene/Transcript/Release/Variant compatibility 保留；缺依赖/许可/映射项阻断 public approval 且保留原始证据；没有 destructive PK/cutover/ClickHouse rewrite/full phenotype/inference。

**rollback/stop：** migration 需要 drop/rename/PK replacement、生产 consumer 依赖未验证结构、跨 scope 静默合并、未知 license/TaxID/ECO 被接受、inferred fact 进入 public、worker task 注册无法证明，立即停止。无消费者时仅按已验证 downgrade 移除 expand 结构；有新事实时采用 withdrawn/change-set/forward-fix，不删除历史。

**Oracle input：** B-pre-ADR PASS；migration/schema tests；双物种 domain/ontology/legacy/diagnostic/license evidence；closure digest；ClickHouse proof；deferred list；A0/A1 compatibility diff。

**Oracle output：** `PASS_TO_C` 或 `BLOCK_B`；必须逐项确认 identity/scope/closure/license/asserted-only/legacy/ClickHouse 和 expand-only，明确未授权的 production cutover、PO/full inference、destructive rewrite。修复后仅重跑受影响 domain gate。

### Phase C — 确定性 publication、artifact 和 promotion saga

**Child plan：** [C](2026-07-19-c-deterministic-publication-implementation-plan.md)。

**入口 evidence：** A0/A1/B 及 B-pre-ADR Oracle PASS；provider、RPO/RTO、cache/recovery window、搜索输入边界已固定；不能读取 live mutable rows 代替 FrozenInputSnapshot。

**写入 ownership：**

- API publication writer：`apps/api/app/publication/`、publication models/repositories/services/contracts/projection/provider/saga/smoke/reconcile、C tests。
- Worker/build writer：`apps/worker/src/soymutdb_worker/tasks/publication*.py`、对应 utils seam/tests；只能引用 registered IDs 和 frozen snapshot。
- web/build writer：`apps/web/scripts/ssg-build.ts`、publication/search build contract files/tests；不得改变 D consumer UX。
- infra route writer：`infra/nginx/conf.d/default.conf` 及 C 指定 immutable route/config evidence；不得修改部署拓扑或升级。
- read-only/quality/design lane：provider fault injection、projection leakage、determinism、saga/recovery review；不得写 D/E UI。

同阶段 publication API、Worker、SSG、Nginx 允许不相交目录并行；manifest schema、task registry、router/index 和 shared API contract 只有唯一 integration writer 修改。

**mandatory validation evidence：** frozen input/revision digest determinism；registered immutable artifacts；每类公开 artifact 的 `rl_public_projection_schema` allowlist 为 primary boundary；scan defense-in-depth；common validation；conditional JBrowse/download capability profiles；manifest-last/ready marker；provider capability/CAS/fencing；outbox relay/idempotency；Prepare DB → External CAS → Finalize DB；CAS 后 verifying、classified smoke、fenced compensation/unknown；orphan/reference/hold/recovery-window/grace-period reconcile；retention/DR；三条 history 独立。

**exit criteria：** 同一冻结输入产生同一 manifest/artifact digests；旧 active 不被失败制品覆盖；CAS 与 Finalize 证据一致；CAS 后失败不宣称旧 pointer 未变；C 只验收构建制品和公开边界，不声称 D consumer UX、E UI 已完成。

**rollback/stop：** 任意 live latest read、任意 path/secret/URI input、artifact overwrite、manifest before artifacts、Redis/Celery success 当 commit、CAS 后 smoke 失败却无 compensation/unknown、orphan cleanup 未检查引用/hold、C 越界实现 D/E，立即冻结 promotion；失败制品隔离；按 saga/attempt/reconcile/forward-fix 恢复，不改旧历史。

**Oracle input：** B PASS；deterministic build repeat evidence；projection schema/negative scan；artifact/provider/capability matrix；outbox/task contract；CAS/fencing fault matrix；saga histories；smoke/reconcile/orphan/retention/DR logs；C/D acceptance boundary statement。

**Oracle output：** `PASS_TO_D` 或 `BLOCK_C`；必须明确 artifact readiness、public allowlist、provider capability、CAS/fencing/unknown/compensation、C/D 分工和是否有新 ADR 触发；所有 findings 修复并重跑受影响 narrow tests。

### Phase D — 隔离双搜索与科学 UX 垂直切片

**Child plan：** [D](2026-07-19-d-isolated-dual-search-implementation-plan.md)。

**入口 evidence：** C Oracle PASS；B-pre-ADR 固定 search caps；A0/A1/B contracts；不得用 live ORM 作为 Internal authority。

**写入 ownership：**

- API Internal Search writer：`apps/api/app/search/internal/`、`apps/api/app/api/v1/search_internal.py`、对应 schemas/tests。
- API External Search writer：`apps/api/app/search/external/`、`search_external.py`、external schemas/tests；不共享 Internal provider/cache/error objects。
- web Worker/client writer：`apps/web/src/workers/search.worker.ts`、`apps/web/src/lib/search-worker-client.ts`、search manifest consumer seam/tests；不得发送完整 dataset 到主线程。
- API client writer：`packages/api-client/src/search-internal.ts`、`search-external.ts`、兼容 exports/tests；shared public envelope 仅由 contract owner 顺序更新。
- static directory/build writer：D 指定 `apps/web/scripts/` search shard/directory contract；只消费 C artifact。
- read-only/quality lane：隔离性、cursor、leakage、fallback、性能、无 JS/JBrowse consumer review；不得写 API service 或 Worker。

Internal/External writer lanes 可在严格分离目录并行；任何 shared `search.ts` compatibility export、schema index、router registration、error envelope 或 cache naming 只能由单一 integration writer 顺序修改。

**mandatory validation evidence：** Internal 只读 manifest-backed bounded shards；固定 rank tiers/tie-break；签名 cursor 绑定 manifest/scope/query/filter/sort/limit/provider；scope ledger/provenance/allowlist；Worker→Internal API→static directory fallback；无主线程全量过滤；External allowlist adapter、独立 cache/rate/timeout/circuit/provenance/error；外部失败不影响 Internal；历史 manifest/hash/capability/字段泄漏/无 JS/JBrowse exact error tests。

**exit criteria：** 两个系统不共享结果、错误、缓存、比较资格、版本语义或 provider registry；D 不重复宣称 C 的 allowlist/scan/provider build validation；bounded error 和 static fallback 可复现。

**rollback/stop：** Internal 访问 live ORM、External 接受任意 URL/adapter/header、共享 cache/error、cursor 跨 manifest 可解释、Worker 失败退回全量主线程过滤、外部超时影响本地结果或引入未测搜索引擎，立即关闭新 consumer route/feature projection，保留 C artifacts，回到 D contract；新引擎需求形成 measured ADR。

**Oracle input：** C PASS 和 manifest/capability evidence；B-pre-ADR cap；Internal/External route/schema/service/client diff；cursor/fallback/field-leakage/isolation/performance/no-JS tests；D 与 C boundary checklist。

**Oracle output：** `PASS_TO_E` 或 `BLOCK_D`；逐项确认双搜索物理/语义隔离、bounded limits、cursor invalidation、fallback、public projection和 external failure containment；禁止以页面截图或旧 search PASS 替代 contract evidence。

### Phase E — Scientific Field Manual 公共端与受治理 Admin UX

**Child plan：** [E](2026-07-19-e-scientific-public-admin-ux-implementation-plan.md)。

**入口 evidence：** A0–D Oracle PASS；designer handoff 的 layout/tokens/responsive/focus/screenshots；D contracts 和 C projection 可消费；不得在 E 创建 authority、search、publication、permission 或 migration。

**写入 ownership：**

- shared-ui owner：`packages/ui/src/components/rl-*.tsx`、`packages/ui/src/lib/rl-*.ts`、`packages/ui/src/index.ts`、`packages/ui/src/styles.css`。
- public-shell owner：E 指定 `apps/web/src/components/rl-*.tsx`、`apps/web/src/lib/rl-*.ts`、root/header/footer。
- public-research owner：E 指定 search/detail/compare/download/browser routes、`rl-public-*` components/libs。
- admin-workspace owner：E 指定 `apps/admin/src/components/rl-*.tsx`、`rl-*.ts`、五个 workspace routes/sidebar/root。
- quality/evidence owner：Stories、web/admin tests、`tests/e2e/rl-phase-e-*.spec.ts`、a11y/visual evidence；不得改产品实现。

以上 lane 可按目录并行，但同一 shared export、route registration、tokens/style 或 fixture 只有唯一 owner；designer lane 只提供 handoff/review，不直接写工程实现，工程不得以个人审美替换 handoff。

**mandatory validation evidence：** scope ledger 显式 applicability；compact/expanded/historical ontology term；provenance summary/expanded/export 同一 snapshot；release-pinned JBrowse exact capability failures；Internal/External sections隔离；truthful capability/403/disabled/reauth/legacy；review-evidence matrix 和三条 history timeline；diagnostic workspace；双物种端到端发布/回滚；keyboard/read screen/reduced motion/mobile/44px public/36px admin/no-JS/visual screenshots。

**exit criteria：** UI 只消费已发布 projection 和 typed control-plane contract；没有按钮文案冒充能力；Scientific Field Manual / Research Instrument 设计意图保留；E 失败可只回滚 UI projection，不改 authority/history/search/publication。

**rollback/stop：** UI 直连 DB/live draft、Admin 任意 HTML/path/Shell/secret、隐藏代替授权、JBrowse 猜测其它 release、全 ontology tree/inference UI、营销式随机指标/装饰动画、视觉实现偏离 handoff，立即回滚 E-only projection/route，保留 A0–D authority，修复 contract/design evidence 后再审。

**Oracle input：** A0–D PASS；designer handoff/diff/screenshots；E component/API/route/e2e/a11y/no-JS/visual evidence；第二物种发布/rollback trace；projection leakage and capability/403 trace。

**Oracle output：** `PASS_TO_F` 或 `BLOCK_E`；逐项标记 `keep/simplify/fix-before-F/defer-with-ADR`，特别检查 designer intent、权限真实性、C/D 不重复、scope/provenance/JBrowse 语义和可访问性；修复后重跑受影响 UI/contract tests。

### Phase F — 基准、验证、OCR、清理与最终证据

**Child plan：** [F](2026-07-19-f-verification-ocr-cleanup-implementation-plan.md)。

**入口 evidence：** A0–E 全部 Oracle PASS、用户确认记录、完整 evidence index、B-pre-ADR caps、designer handoff、可执行环境；缺一项 F 标为未开始。

**写入 ownership：**

- verification/benchmark writer：F 指定测试、load/stress、a11y/no-JS/JBrowse、DR/rollback、SBOM/license/projection evidence 区域；不得修改被测 authority 以让报告通过。
- OCR/review evidence writer：`artifacts/ocr-*.json` 或 CI artifact 区域；只有 Git repository、完整历史、受控 provider credentials、官方 CLI 和受信任 checkout 同时满足时运行；当前非 Git 状态不得伪造 OCR。
- cleanup writer：只生成 dry-run/reference candidate 清单，经过人工确认后按 F 计划删除明确无引用生成物；不得删除 docs、设计/研究/计划、lockfile/config/source、audit/legal hold、active/rollback artifacts、backup 或 unknown。
- quality/read-only lane：Oracle readability/simplification、科学审查、证据交叉检查；不得修改 A0–E implementation ownership。

F 内 benchmark、OCR、cleanup 可并行只读/报告生成；任何源代码修复必须由对应前阶段 owner 顺序执行，F writer 不得跨 lane 直接改 authority。

**mandatory validation evidence：** focused-to-broad migration/contracts/permission/state/outbox/projection/provider/search/JBrowse/a11y/no-JS；双物种全链路同 digest/rollback；冻结 caps 下 P50/P95、memory、TTFB、Worker、external timeout、JBrowse、restore；SBOM/license；conditional OCR JSON；reference-based cleanup dry-run/人工确认/删除后 reachability；backup/object/CDN/search/JBrowse/Admin DR；Oracle simplification/readability。

**exit criteria：** A0–E evidence 完整；focused 无阻断后才 broad；caps 没有静默扩大；unknown/cleanup/recovery 语义真实；OCR 诚实标记；没有新 cluster/microservice/upgrade；最终 Oracle 无 blocking finding。

**rollback/stop：** 前置证据缺失、broad gate 掩盖 focused failure、超 cap 通过无 ADR、OCR 在不可信 checkout/无 provider 执行、cleanup 无引用证明、DR digest 不一致或发现 authority 被报告/截图替代，立即停止；恢复清单/回滚副本，禁止继续清理或发布；源代码问题回到原 phase owner。

**Oracle input：** A0–E PASS packets；focused/broad/performance/DR/SBOM/license/projection/OCR/cleanup evidence；命令、环境、lockfile/manifest/commit-or-ref（若有）、digest、失败分类和修复引用。

**Oracle output：** `CLOSE_PHASE_2` 或 `BLOCK_F`；输出逐文件 `keep/simplify/fix-before-close/defer-with-ADR`，确认无 secret、无假 OCR、无引用破坏、无新 authority 和无未测扩容；blocking finding 修复后重跑受影响 focused gate 和 broad smoke。

## 5. 未来 orchestrator 的调度协议

1. **Gate-first dispatch：** 只在 phase gate 有 Oracle PASS、用户/策略要求的确认和 evidence digest 后，dispatch bounded writer；不得把 read-only research、计划文字或旧报告的“完成”当 implementation evidence。
2. **Bounded ownership：** 每个 job 必须带 phase、role、允许写入路径、禁止路径、输入 evidence、窄验证命令、停止条件、回滚方式和 expected terminal state。不同 writer 不得共享写入 lane。
3. **Hook-driven completion：** 等待 hook-driven completion；reconcile 所有 terminal jobs（pass/fail/cancel/timeout/unknown），再更新 scheduler board。不得以 worker 返回、Celery queued、Redis key、UI toast 或未验证通知推断成功。
4. **Narrow before broad：** 先运行 child plan 列出的单元/contract/migration/permission/state test，再扩大到 phase suite、E2E、load、DR；focused 失败必须停止并分类，不能用 broad pass 掩盖。
5. **Deepwork state：** 每个 phase gate 后更新 `.slim/deepwork/ontology-postgresql-refactor.md`：state、phase、task ownership、evidence paths/digests、Oracle verdict、remaining risks、rollback/stop outcome。不得写 secret 或实际 agent ID 作为 authority。
6. **Oracle loop：** 每 phase 提交 exact Oracle packet；Oracle actionable findings 必须修复，重跑受影响 narrow gate，再提交复核；未完成不得推进下游。
7. **设计意图：** E 阶段必须保留 Scientific Field Manual / Research Instrument handoff；若实现便利与 designer intent 冲突，暂停并记录 design decision，不由工程师静默改视觉方向。
8. **authority discipline：** PostgreSQL 保存科学/治理/审批/manifest/pointer ledger；Redis 只协调；artifact、manifest、ready marker、CAS/fencing 和三条 histories 各有独立证据；External Search 不写本地 facts；Worker/JBrowse/search index 不承担授权或 provenance authority。
9. **变更控制：** 任何新搜索 cluster、graph DB、microservice、runtime/dependency version、schema contract/drop、生产 cutover、PO/full inference、ClickHouse rewrite，均停止并建立 measured ADR、兼容矩阵、收益/SLO、迁移与回滚证据，再请求新的 Oracle/user review。
10. **技能与秘密：** 适用 phase 先声明 `skills/` 内本地 skill；credentialed CI 只对受信任 checkout 运行 OCR；所有日志/JSON/截图脱敏。当前非 Git workspace 不运行或伪造 Alibaba OCR。
11. **无自动 Git：** 不初始化 Git、不创建 branch/worktree（当前不需要）、不 commit、merge、push、PR。若 repo 状态改变，mutation 前使用隔离 worktree，仍需用户明确授权 Git action。

## 6. 共享风险登记表

| 风险/触发器 | 影响 | 立即停止响应 | 恢复/再入条件 |
|---|---|---|---|
| ORM、Alembic、deployed schema 或 Compose wiring 不一致未解释 | 迁移/运行时破坏 | 停止所有新 migration/write；回 A0 | reconciliation、unresolved owner、真实 rehearsal 通过 |
| 以 `create_all()` 或旧报告替代 Alembic/恢复证据 | 假迁移通过 | 标记 BLOCKED，删除假 pass | disposable upgrade/downgrade/upgrade、空库、backup/restore 证据 |
| 生产 schema/write/cutover 在 gate 前发生 | 不可逆事实污染 | 立即冻结发布、保留审计、人工 incident resolution | Oracle 明确恢复/forward-fix 与用户再授权 |
| 任意 Admin path/URL/Shell/secret/DB input | RCE/数据泄漏 | 禁用 command；写 failure audit；不执行输入 | registered ID + typed command + capability/approval contract |
| Redis/Celery/UI 被当 authority | 错误成功/重复发布 | 冻结 promotion/task success claim | PostgreSQL/outbox/lease/fencing/CAS evidence |
| 跨 species/namespace/assembly identity 静默合并 | 科学事实错误 | 停止导入/manifest；进入 unresolved | scope-aware constraint、dual-read diff、人工 resolution |
| closure/license/ECO/TaxID 缺失却进入 public | 合规/科学错误 | 阻断 public approval，保留 raw/diagnostic | immutable closure/license evidence + review |
| B-pre-ADR cap 超限或需换引擎 | 性能/泄漏/运维风险 | bounded error/fallback；不扩容 | measured ADR、兼容测试、回滚证据、Oracle批准 |
| artifact overwrite、manifest/pointer/ready divergence | 不可复现/错误版本 | 隔离制品、冻结 promotion、reconcile | immutable path、manifest-last、CAS/fencing、saga evidence |
| CAS 后 smoke 失败无 compensation/unknown | 用户暴露错误版本 | 标记 verifying/unknown，冻结后续 promotion | fenced compensation 或人工 resolution，保留原 attempt |
| Internal/External 搜索共享 cache/error/result 或 Internal live ORM | 语义污染/故障级联 | 禁用受影响 route/provider | 独立 routes/services/cache/provenance、cursor/fallback tests |
| E UI 声称不存在能力或直连 DB/draft | 操作员误操作 | 回滚 UI projection，显示 truthful disabled/403 | backend contract、capability/approval/visual/a11y evidence |
| credentialed OCR 执行不可信 checkout或无官方条件 | secret/execution 风险 | 立即不运行/撤销 job；不采纳结果 | trusted CI、完整历史、provider/CLI、脱敏 JSON |
| cleanup candidate 有未知引用/hold/recovery window | 丢失回滚/审计 | 永不删除，标 unknown | reference scan、grace period、人工确认、删除后复验 |

## 7. Master evidence index 格式

每个 phase 生成一个 machine-readable index（路径由该 phase child plan 或 CI artifact policy 确定），并在 `.slim/deepwork/ontology-postgresql-refactor.md` 中引用。推荐 JSON 结构：

```json
{
  "phase": "A0",
  "plan": "docs/superpowers/plans/2026-07-19-a0-factual-reconciliation-implementation-plan.md",
  "gate": "oracle_gate_2_or_phase_gate",
  "status": "PASS|BLOCKED|NOT_STARTED",
  "owner_role": "role-name",
  "writer_scope": ["tools/a0/", "apps/api/tests/a0/"],
  "inputs": [
    {"path": "...", "sha256": "sha256:...", "kind": "spec|evidence|fixture"}
  ],
  "commands": [
    {"command": "redacted command", "result": "pass|fail|skip", "reason": "..."}
  ],
  "artifacts": [
    {"path": "...", "sha256": "sha256:...", "scope": "...", "sensitive_values_present": false}
  ],
  "tests": [
    {"name": "...", "scope": "narrow|broad", "result": "pass|fail|skip"}
  ],
  "rollback": {"triggered": false, "procedure": "...", "evidence": "..."},
  "oracle_input": ["..."],
  "oracle_output": {"verdict": "...", "findings": [], "reviewed_at": "..."},
  "open_risks": ["..."],
  "secrets_or_tokens_recorded": false
}
```

规则：命令可脱敏但不能删除其语义；记录 environment/lockfile/ref 只在安全时；不保存 password、token、cookie、presigned URL、完整敏感请求或 provider credential；skip 必须有精确 prerequisite reason；`PASS` 必须引用可重放 evidence，不得只引用 screenshot、OCR 或文档 claim。

## 8. Oracle Gate 2 review packet checklist（再次执行版）

提交前 orchestrator 必须勾验：

- [ ] 本文件只创建一个 docs 文件，链接七份 child plans、spec、research、Deepwork state。
- [ ] writing-plans header 含 feature name、required subskill、Goal、Architecture、Tech Stack。
- [ ] 明确 orchestration 性质、child plans source of truth、无自动 Git actions。
- [ ] DAG 精确为 A0→A1→B-pre-ADR→B→C→D→E→F，并解释 B-pre-ADR 属于 B；D/E/F boundary 无提前并行写入。
- [ ] 每 phase 均有 entry evidence、按 role 的 permitted writer region、parallel-safe read-only/quality/design lane、no-overlap rule、mandatory validation、exit、rollback/stop、Oracle exact input/output。
- [ ] 当前 workspace 非 Git；未来 Git 时 isolated worktree policy 已写；没有强制 branch/commit。
- [ ] shared constraints 全部逐项出现：`rl_`、中文 why-comments、static-first、two isolated searches、PostgreSQL authority、Redis non-authority、无 measured ADR 不加 cluster/microservice/upgrade、registered Admin inputs、无 public DB、credentialed CI 不跑 untrusted OCR。
- [ ] Phase 2 readiness checklist 可逐项落 `PASS/BLOCKED/N/A`，含 owner/evidence/digest。
- [ ] risk register 有 trigger、stop response、re-entry/rollback。
- [ ] evidence index 有 JSON 格式、secret redaction、narrow/broad、Oracle fields。
- [ ] scheduler instructions 要求 bounded dispatch、hook completion/reconcile、narrow before broad、Deepwork updates、每 phase Oracle、修 findings、保留 designer intent、禁止 documentation-only progress。
- [ ] 实际 self-review 已逐份检查七 child plans，并记录结果而非使用 placeholder。

Gate 2 verdict 只能在上述 checklist、Oracle packet 和 child-plan cross-check 全部有证据后给出。未通过时，主计划状态为 `BLOCKED_ON_ORACLE_GATE_2`，不得 dispatch A0。

## 9. 七份子计划交叉自审结果（实际结果）

本主计划已逐份阅读并交叉检查七份 child plans，结果如下：

- **A0：无遗漏。** 保留 runtime/migration wiring、实际 Alembic/schema/ORM/OpenAPI/client/Admin/Worker reconciliation、legacy Release evidence、unresolved queue、真实 upgrade→downgrade→upgrade、backup/restore、`create_all()` 非验收和无升级授权；A0 被置于所有 implementation 之前。
- **A1：无矛盾。** 保留 A0 hard block、deny-first capability、typed command/digest/idempotency、registered inputs、三条独立 histories、audit/task outbox、relay/registry、reauth/break-glass、truthful Admin 403/disabled；未把未来 dataset/publication/artifact 当 A1 成功事实。
- **B：无遗漏。** 明确把 B-pre-ADR 作为 B 内命名 gate；保留双物种 walking skeleton、scope-aware identity、expand-only migration、legacy dual-read/unresolved、NCBI/GO/SO/RO/ECO closure、asserted-only、license/diagnostics、PO deferred 和 ClickHouse non-destructive proof；没有提前允许 PK replacement、生产 cutover、full inference 或 ClickHouse rewrite。
- **C：无矛盾。** 保留冻结输入、immutable revision/artifact registry、`rl_public_projection_schema` primary allowlist、scan defense-in-depth、conditional capability profiles、manifest-last/ready marker、outbox relay、Prepare→CAS→Finalize、fencing、verifying、compensation/unknown、orphan/reference protection、独立 histories；明确 C 不宣称 D/E consumer UX。
- **D：无遗漏。** 保留 C validated artifacts 与 B-pre-ADR caps 的双前置；Internal/External route/service/cache/error/provenance/provider 隔离；固定 rank tiers、signed cursor、scope/digest envelope、Worker→API→static directory fallback、无主线程全量过滤、无新 search cluster；明确不重复 C 的 build validation。
- **E：无遗漏。** 保留 A0–D Oracle gates、designer handoff 和 Scientific Field Manual / Research Instrument intent；ownership 分为 shared UI、public shell、public research、Admin workspace、quality；覆盖 scope ledger、ontology term、provenance/citation、JBrowse capability failure、review matrix、三 histories、diagnostics、a11y/no-JS/mobile；没有把 UI 变成 authority。
- **F：无矛盾。** 保留 A0–E 全部前置、focused-to-broad、冻结 caps、真实双物种/发布/回滚/DR、SBOM/license/projection、conditional OCR、trusted credentialed CI、reference-based cleanup、final Oracle simplification/readability；明确当前非 Git 不执行/伪造 OCR，且 cleanup 不碰 docs、audit、legal hold、active/rollback 或 unknown。

**交叉冲突检查结果：** 未发现阶段顺序冲突、D/E 提前并行写入、共享 writer lane 未命名、C/D 验收重复、B-pre-ADR 被误列为独立实现阶段、placeholder agent ID、secret 复制、自动 Git 行动或把文档声明当证据的遗漏。发现的所有不确定运行时/provider/第二物种/RPO-RTO/容量事项均保留为前置 evidence 或 measured ADR 输入，没有在主计划中擅自填写结论。自审结论：**主计划可提交 Oracle Gate 2；在 Oracle `APPROVE` 前不得开始实现。**
