# 整体完善执行状态

> **已归档（2026-10-01）**：智能体执行日志与提示词草稿（治理要求工作区不存放日志）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §7 变更记录；执行结论见 docs/dev/project-status.md。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

- 日期/角色/PI 版本/provider/model：2026-09-08 / 执行代理 / 平台默认模型
- 原生工作目录/分支/HEAD/相关文件摘要：
  - 工作目录：`/mnt/data02/T25ronglin/code/web`
  - HEAD：`6592dfd8e562e5b1722ffc9f3c12068c05654525`
  - 状态：2026-09-08 记录为存在大量既有未提交修改（224 files changed, 8757 insertions, 3172 deletions），另有多份新增未跟踪文件（含迁移 0032–0034、新测试、Admin 路由拆分、脚本等）。当时新增 plan.md / prompt.md / sources.md / 本文件；2026-09-09 又新增 system.md / start.md / verification.md / research-refresh.md 并更新 README.md。这些文档均不认领既有产品代码修改，当前数量和 diff 仍须开工重验。
- 环境和测试目标隔离证据（不含凭证）：
  - Node.js `v24.19.0`（与 `.nvmrc` 一致）
  - pnpm `11.21.0`
  - Python `3.14.6`（系统与 `apps/api/.venv/bin/python` 均一致）
  - Alembic 当前 head 为 `0034_gene_crosswalks.py`；`alembic current` 因无可用 PostgreSQL 实例而失败，符合预期
  - Docker 守护进程不可用，testcontainers 测试无法运行；`SOYMUTDB_TEST_DATABASE_URL` 未配置
- 冻结契约/业务决定/来源：
  - 公开/内部编号语义：API 已使用 `public_id` 为 canonical 外部身份，`internal_id` 仅出现在内部 schema；客户端 `mutant-lines.ts` 已迁移
  - 碰撞规则：外站按 `public_id` 命名空间解析，拒绝所有未发布/无 public_id/已删除记录；内部编号查询同等返回空/404，不确认存在性
  - assembly/release 分组语义：搜索服务已按 `(site_variant, release_id, assembly_id, query, types, cursor, limit)` 分组；未指定 assembly 时返回多 assembly 分组并标记 `ambiguous`
  - 权限作用域：内部搜索端点已绑定 `require_role(RoleName.RESEARCHER)`，审计日志写入 `AuditLog`
  - 迁移策略：0033 downgrade 在跨 assembly 重复 accession 时显式拒绝，保护历史数据

---

## 任务状态总表

| 任务 | 状态 | 精确文件范围 | 依赖/阻碍 | 下一步 |
| --- | --- | --- | --- | --- |
| W0.1 环境/diff/调用链清点 | VERIFIED | 根目录 package.json/.nvmrc；apps/api/migrations/versions/0032–0034；apps/api/.venv；git status/diff | 无 | 已完成 |
| W0.2 业务与 API 契约冻结 | VERIFIED | apps/api/app/models/{variant,genomic}.py；apps/api/app/api/v1/{mutants,search}.py；apps/api/app/schemas/{search,variant}.py；apps/api/app/services/search_service.py；apps/api/app/core/public_ids.py | 无 | 已完成 |
| W0.3 fixture/门禁/缺口登记 | VERIFIED | 见下方“真实缺口”与“历史证据失效项” | 无 | 已完成 |
| W1.1 双 ID/发布守卫 | IMPLEMENTED_UNVERIFIED | packages/api-client/src/mutant-lines.ts；apps/web/src/routes/mutants/index.tsx；apps/api/tests/test_mutants.py | 环境阻断（无 Docker/PG） | 待环境恢复后运行 pytest 验证 |
| W1.2 Gene 及引用迁移 | IMPLEMENTED_UNVERIFIED | apps/worker/src/soymutdb_worker/tables.py；apps/worker/src/soymutdb_worker/tasks/static_pages.py | 环境阻断 | 待 worker 依赖安装后跑测试；ingest.py VCF 导入已禁用，_surrogate_id 仅用于 CH 投影 UInt32 |
| W1.3 crosswalk 与导入/投影一致性 | IMPLEMENTED_UNVERIFIED | apps/api/app/models/genomic.py:GeneCrosswalk；apps/api/migrations/versions/0034_gene_crosswalks.py | 无平行映射表；服务/UI 待 W2/W3 | 继续 W2/W3 接入 crosswalk 查询与展示 |
| W2.1 external/internal DTO 和授权 | IMPLEMENTED_UNVERIFIED | apps/api/app/api/v1/search.py:/internal；apps/api/app/services/search_service.py:internal_search | 环境阻断 | 端点已显式设置 `private, no-store`；待真实响应断言 |
| W2.2 多版本搜索/详情/补全 | IMPLEMENTED_UNVERIFIED | apps/api/app/services/gene_service.py；apps/api/app/api/v1/{genes,expression,homolog}.py；apps/web/src/routes/genes/$geneId.tsx；packages/api-client/src/{genes,expression,homolog}.ts | 环境阻断 | 后端歧义处理已实现；前端 assembly 传递已修复；待集成测试 |
| W2.3 cursor/cache/导出/MCP | NOT_STARTED | apps/web/src/lib/query-keys.ts（gene 部分已补 assembly）；apps/web/src/routes/search.tsx | 依赖 W2.2 | search.tsx query key 仍缺 assembly/release/site，待 W3 添加选择器后同步 |
| W3.1 client 生成与迁移 | NOT_STARTED | packages/api-client/openapi.json；generate/check 脚本 | 依赖 W2 契约 | 待 API schema 稳定后正式生成 |
| W3.2 搜索/详情上下文 | NOT_STARTED | apps/web/src/routes/search.tsx；apps/web/src/lib/query-keys.ts | 依赖 W3.1 | 待 assembly/release 选择器 UI 与缓存隔离 |
| W3.3 UI 状态/可访问性/JBrowse | NOT_STARTED | apps/web/src/routes/；e2e/tests/ | 依赖 W3.2 | 待响应式、键盘、空错态、reduced-motion |
| W4.1 导入恢复 | NOT_STARTED | apps/worker/src/soymutdb_worker/tasks/ingest.py；apps/api/app/api/v1/admin_uploads.py | 依赖 W1.2 | 待 worker 表同步后端到端验证 |
| W4.2 release/制品状态机 | NOT_STARTED | apps/api/app/models/content.py；apps/api/app/api/v1/admin_publications.py；apps/web/scripts/build-sites.ts | 依赖 W1/W2 | 待 stale-task guard 与回滚集成测试 |
| W4.3 Admin 审核/内容预览与错误恢复 | NOT_STARTED | apps/admin/src/App.tsx；apps/admin/src/routes/ | 依赖 W3 | 当前已有 ErrorBoundary/RouteErrorBoundary，只补缺失覆盖 |
| W5.1 保护值 fixture 和扫描自测 | NOT_STARTED | scripts/test_site_artifact_isolation.py；scripts/check_site_artifact_isolation.py | 依赖 W3/W4 | 待合成保护值注入与扫描器正向检出验证 |
| W5.2 双站构建与网络边界 | NOT_STARTED | apps/web/scripts/build-sites.ts；apps/web/package.json | 依赖 W5.1 | 待 dist/external + dist/internal 制品扫描 |
| W5.3 E2E/CI 强制接入 | NOT_STARTED | e2e/playwright-*.config.ts；e2e/tests/ | 依赖 W5.2 | 待 external anonymous + internal authenticated 真实 API 流程 |
| W6.1–W6.3 性能与可维护性 | NOT_STARTED | 性能基线待 W3/W4 后固定 | 依赖 W3/W4 | 不提前优化 |
| W7.1–W7.3 集成与交付 | NOT_STARTED | 全部根门禁 | 依赖 W1–W6 | 最终收口 |

---

## 约束/场景验证记录

| 约束/场景 | 命令与 cwd | 时间/HEAD/diff 摘要 | 退出码 | pass/fail/skip/xfail | 证据路径/摘要 | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| C17 环境版本 | `node --version; pnpm --version; python3 --version; cat .nvmrc` | 2026-09-08 / 6592dfd8e | 0 | — | Node 24.19.0, pnpm 11.21.0, Python 3.14.6 | VERIFIED |
| 迁移链完整性 | `ls apps/api/migrations/versions/*.py \| sort \| tail -5` | 2026-09-08 | 0 | — | 0030→0031→0032→0033→0034，链连续 | VERIFIED |
| public_id 模型存在 | 读取 `apps/api/app/models/variant.py:57–68` | 2026-09-08 | — | — | `public_id: Mapped[Optional[str]]`, unique index, nullable，注释明确“nullable only while unpublished” | 已有且证据有效 |
| gene_pk/assembly/accession 唯一约束 | 读取 `apps/api/app/models/genomic.py:104–163` | 2026-09-08 | — | — | `gene_pk` 为 PK，`uq_gene_assembly_accession` 存在 | 已有且证据有效 |
| GeneCrosswalk 模型存在 | 读取 `apps/api/app/models/genomic.py:258–314` | 2026-09-08 | — | — | `GeneCrosswalk` 含 source/target gene FK、relation_type、provenance_source/evidence、唯一约束 `uq_gene_crosswalk_pair_type` | 已有且证据有效 |
| 外站突变体 API 拒绝内部键 | 读取 `apps/api/app/api/v1/mutants.py:67–89` | 2026-09-08 | — | — | `get_mutant_line` 仅按 `func.upper(MutantLine.public_id) == normalize_public_id(public_id)` 查询；注释声明“包括 existing internal identifiers”同等返回 not-found | 已有且证据有效 |
| 内部搜索服务端角色授权 | 读取 `apps/api/app/api/v1/search.py:240–275` | 2026-09-08 | — | — | `/search/internal` 使用 `Depends(require_role(RoleName.RESEARCHER))`；返回 `InternalSearchResponse`；写入 `AuditLog`；显式设置 `response.headers["Cache-Control"] = "private, no-store"` | 已有且证据有效 |
| 搜索缓存上下文完整 | 读取 `apps/api/app/services/search_service.py:74–104` | 2026-09-08 | — | — | `cache_params` 包含 `site_variant`, `release_id`, `assembly_id`, `query`, `types`, `cursor`, `limit`；internal 显式绕过缓存 | 已有且证据有效 |
| 双站构建显式隔离 | 读取 `apps/web/scripts/build-sites.ts` | 2026-09-08 | — | — | `VARIANTS = ["external", "internal"]`；按 `VITE_SITE_VARIANT` 顺序构建两棵独立树；无运行时推断 | 已有且证据有效 |
| Admin ErrorBoundary 已存在 | 读取 `apps/admin/src/App.tsx:1–120` | 2026-09-08 | — | — | 根路由有 `<ErrorBoundary>`，每个 lazy 路由有 `<RouteErrorBoundary>` + `<Suspense>` | 已有且证据有效 |
| 基因详情后端歧义处理 | 读取 `apps/api/app/services/gene_service.py:170–210` | 2026-09-08 | — | — | `get_gene` 在未提供 assembly_id 且多 assembly 命中时返回 `ValidationError(code=ambiguous_assembly)`；不静默默认 | 已有且证据有效 |
| expression/homolog 后端歧义处理 | 读取 `apps/api/app/api/v1/expression.py:155–175`；`apps/api/app/api/v1/homolog.py:45–65` | 2026-09-08 | — | — | 均使用 `_gene_service.find_by_accessions` 并在多 assembly 时返回 `ValidationError(code=ambiguous_assembly)` | 已有且证据有效 |
| API client 类型检查 | `pnpm --filter @soymutdb/api-client typecheck` | 2026-09-08 / 6592dfd8e + 本次修改 | 0 | — | `tsc --noEmit` 无错误 | VERIFIED |
| Web 类型检查（相关项） | `pnpm typecheck` | 2026-09-08 | 2 | — | mutants/index.tsx 旧 `id` 引用已消除；剩余 6 个错误为既有无关代码（antd-home、genes/index、location、variants） | 本次修改通过 |
| Worker Core genes 表与迁移一致性 | 读取 `apps/worker/src/soymutdb_worker/tables.py:73–85` | 2026-09-08 | — | — | `genes` 已声明 `gene_pk` BigInteger PK、`accession` String(64)、`assembly_id` Integer；expression_data/gene_homologs/gene_data_cache 的 `gene_id` 已改为 BigInteger | 已修复 |
| Worker 语法检查 | `python3 -m py_compile tables.py static_pages.py ingest.py` | 2026-09-08 | 0 | — | 语法通过 | VERIFIED |
| 前端基因详情 assembly 传递 | 修改 `apps/web/src/routes/genes/$geneId.tsx` | 2026-09-08 | — | — | `Route.useSearch()` 读取 `assembly`，传给 `getGene`/`getGeneExpression`/`getGeneHomologs`；queryKey 包含 assembly | 已修复 |
| 前端突变体列表 public_id 传递 | 修改 `apps/web/src/routes/mutants/index.tsx` | 2026-09-08 | — | — | Link `params={{ id: line.public_id }}`；`rowKey="public_id"` | 已修复 |
| API client expression/homolog assembly | 修改 `packages/api-client/src/expression.ts`；`packages/api-client/src/homolog.ts` | 2026-09-08 | — | — | `getGeneExpression`/`getGeneHomologs` 均新增 `assembly_id?: string` 参数并传入查询 | 已修复 |
| Query key 基因详情上下文 | 修改 `apps/web/src/lib/query-keys.ts` | 2026-09-08 | — | — | `genes.detail`/`expression`/`homologs` 均包含 `assemblyId` 维度 | 已修复 |

---

## 已实现但未验证

- `public_id` 签发模块 (`apps/api/app/core/public_ids.py`)：实现完整，但缺乏唯一性冲突、并发签发、发布拒绝缺号的运行测试。
- `search_service.py` 的 `internal_search` 与 `global_search`：代码存在，但缺乏真实 PostgreSQL 集成下的双 ID 查询、跨 release/assembly 分组、缓存隔离的运行测试。
- 迁移 0032–0034：文件存在且 DDL 合理，但未在隔离 PostgreSQL 上执行 upgrade/downgrade 验证。
- Worker `tasks/static_pages.py` 已读取 `gene_pk`/`accession`：与 `tables.py` 同步；但未在真实 PG 上执行静态生成。
- 前端 assembly 传递已修复，但缺乏真实 API 运行验证（E2E/浏览器）。

## 历史证据失效项

- `docs/dev/database-execution-status.md` 中“63 passed”等历史数字：当前模型与消费者已显著变化（新增 public_id、gene_pk、crosswalk），旧测试数字不代表现状。
- `docs/dev/optimization-master-plan.md` 中的 ErrorBoundary “0 个”待办：Admin 已存在根级和路由级边界，该数字已失效。
- 旧 `docs/dev/pi-agent-system-prompt.md` 中“AGENTS.md 已撤销”表述：本次用户明确采用 AGENTS.md，该表述失效。

## 真实数据/授权/环境依赖

- `public_id` 的格式（当前为 `SM` + 10 Crockford-Base32）标记为“Engineering default (pending product-owner confirmation)”：不影响实现，但生产签发前需业务确认。
- 真实 Wm82 v4/v5 基因 crosswalk 数据：模型已就绪，但 fixture 与真实数据验收仍依赖来源/许可/证据等级决定。
- 生产迁移/回填/发布：未获授权，W1–W7 只交付代码、迁移文件与隔离测试。
- **测试环境阻断**：当前工作目录无 Docker 守护进程，无本地 PostgreSQL，无法运行 testcontainers 或 pytest 集成测试。`apps/api/.venv` 存在但 `apps/worker/.venv` 缺少 pytest 及依赖。建议配置 `SOYMUTDB_TEST_DATABASE_URL` 或启动 Docker 后重验。

## 下一条可执行动作

**W2.3 / W3 方向**（若用户授权继续）：
1. 修复 `apps/web/src/routes/search.tsx` 的 query key，加入 `assembly`（需先添加 assembly 选择器或从 URL 读取）。
2. 检查并修复 `apps/web/src/routes/genes/index.tsx` 的 `search` 属性缺失类型错误（既有错误，但影响数据库入口链接）。
3. 接入 OpenAPI client 正式生成，更新所有消费者类型。

**环境恢复方向**：
- 配置 `SOYMUTDB_TEST_DATABASE_URL=postgresql+asyncpg://...` 指向隔离测试库，重跑 `apps/api/tests/test_mutants.py` 与 `apps/api/tests/test_search_contract.py`。
- 在 `apps/worker` 安装测试依赖后运行 `pytest tests/`。

---

## 本轮修复记录（R01–R07、V01–V03）

- 日期/HEAD：`2026-09-08` / `6592dfd8e` + 本轮 diff
- 新增/修改文件（本轮）：
  - `apps/api/app/api/v1/search.py`（R06：fix SyntaxError；internal_search 参数顺序）
  - `apps/api/app/api/v1/admin_static.py`（R07：传入 release_id）
  - `apps/api/app/schemas/genomic.py`（R04：GeneResponse 加 assembly_name）
  - `apps/api/app/services/gene_service.py`（R04：_gene_to_response 返回 assembly_name）
  - `apps/web/src/lib/format.ts`（R04：jbrowseUrl 接受 assembly 参数）
  - `apps/web/src/routes/genes/$geneId.tsx`（R04：传 assembly_name 给 jbrowseUrl）
  - `apps/web/src/routes/search.tsx`（R05：validateSearch/queryKey/globalSearch 加 assembly）
  - `apps/worker/src/soymutdb_worker/tasks/static_pages.py`（R07：对象键加 release/assembly 前缀）
  - `apps/worker/src/soymutdb_worker/tasks/ingest.py`（R03：_surrogate_id/_pick_mutant_line 注释）
  - `packages/api-client/src/genes.ts`（R04：GeneSummary 加 assembly_id/assembly_name）
  - `apps/api/tests/test_search_contract.py`（R06：新增 private/no-store 头断言；修复旧测试参数）
  - `apps/api/tests/test_gene_service.py`（R02：同步 gene_pk/accession 新模型）

### R/V 完成表

| 编号 | 状态 | 代码证据 | 验收命令与结果 | 阻碍 |
|------|------|---------|---------------|------|
| R01 | IMPLEMENTED_UNVERIFIED | api-client/web 已用 public_id；test_mutants.py 有正/负测 | `pytest tests/test_mutants.py::test_list_mutant_lines_query_orders_by_lower_name_then_id` pass；集成测试需 PG | 无 Docker/PG |
| R02 | IMPLEMENTED_UNVERIFIED | tables.py 已同步 gene_pk；test_gene_service.py 16 pass | `pytest tests/test_gene_service.py -q` 16 passed；未覆盖 worker 隔离 PG 真实读写、跨 assembly 引用和孤儿检查 | 无可用隔离 PG/worker 集成证据 |
| R03 | IMPLEMENTED_UNVERIFIED | ingest.py 已禁用 VCF；_surrogate_id 加 CH 投影注释 | `python3 -m py_compile ingest.py` 0；语法检查不能证明 PG 解析、歧义处理或 CH 关联 | 无 PG/CH 集成证据 |
| R04 | IMPLEMENTED_UNVERIFIED | jbrowseUrl/$geneId.tsx 已传 assembly；GeneDetail 返回 assembly_name | `pnpm --filter @soymutdb/api-client typecheck` 0；web typecheck 无新增错误 | 无真实 API E2E |
| R05 | IMPLEMENTED_UNVERIFIED | search.tsx queryKey 加 assembly；globalSearch 传 assembly_id | `pnpm --filter @soymutdb/api-client typecheck` 0 | 无 UI 选择器，仅 URL/缓存维度 |
| R06 | IMPLEMENTED_UNVERIFIED | search.py 设 `private, no-store`；新增单元测试 | `pytest tests/test_search_contract.py::test_internal_search_sets_private_no_store_header` pass；未覆盖真实 HTTP 成功/拒绝响应、middleware/代理及权限范围交叉 | 无真实应用/代理集成证据 |
| R07 | IMPLEMENTED_UNVERIFIED | static_pages.py key 加 `{release_id}/{assembly_id}/genes/{accession}`；admin_static.py 传 release_id | worker pytest 未安装；语法检查通过 | 无对象存储集成环境 |
| V01 | IMPLEMENTED_UNVERIFIED | 0032–0034 DDL 合理 | `alembic current` 因无 PG 失败 | 环境阻断 |
| V02 | IMPLEMENTED_UNVERIFIED | public_ids.py 实现完整 | 需并发/发布缺号测试 | 环境阻断 |
| V03 | NOT_STARTED | search_service.py 有 global/internal search | 需真实 PG fixture | 环境阻断 |

2026-09-09 独立只读审计更正：R02、R03、R06 的已有证据分别只证明服务单测、语法有效和单元级响应头，未达到 w1-w3-repair.md 的真实 PG/CH/HTTP 集成验收，因此从 VERIFIED 降为 IMPLEMENTED_UNVERIFIED。保留原命令与结果作为局部证据，不将其删除或冒充完整验收。

### 运行证据

```bash
# cwd: apps/api
.venv/bin/python -m pytest tests/test_search_contract.py tests/test_gene_service.py tests/test_mutants.py::test_list_mutant_lines_query_orders_by_lower_name_then_id -q
# 结果：28 passed, 1 warning

# cwd: 仓库根目录
pnpm --filter @soymutdb/api-client typecheck    # exit 0
pnpm --filter @soymutdb/api-client lint          # 0 errors, 4 warnings
python3 -m py_compile apps/api/app/schemas/genomic.py apps/api/app/services/gene_service.py apps/api/app/api/v1/admin_static.py apps/api/app/api/v1/search.py
python3 -m py_compile apps/worker/src/soymutdb_worker/tasks/static_pages.py apps/worker/src/soymutdb_worker/tasks/ingest.py apps/worker/src/soymutdb_worker/tables.py
```

### 实际行为变化

1. **JBrowse 链接带 assembly**：`jbrowseUrl` 从硬编码 `Wm82.a4.v1` 改为接受 `assembly` 参数；基因详情页从 API 返回的 `assembly_name` 传入。
2. **搜索缓存隔离**：`search.tsx` 的 TanStack Query key 加入 `assembly`，globalSearch 请求也传递 `assembly_id`；切换 assembly 后不会展示旧上下文结果。
3. **静态对象防覆盖**：Worker `build_static_pages` 的 S3 对象键从 `genes/{accession}` 改为 `{release_id}/{assembly_id}/genes/{accession}`；admin 触发时传入 active release_id。
4. **CH 投影语义明确**：`ingest.py` 中 `_surrogate_id` 和 `_pick_mutant_line` 增加注释，明确 hash  surrogates 仅用于 ClickHouse 投影，不能替代 PostgreSQL 权威身份。
5. **测试修复**：`test_search_contract.py` 修复 4 个因函数签名变更而失败的测试；`test_gene_service.py` 同步到 `gene_pk`/`accession` 新模型（16 pass）。

### 未完成/未验证项

- **V01–V03**：需要隔离 PostgreSQL 环境运行迁移升降级、public_id 并发签发、真实搜索集成测试。当前无 Docker/PG，标记为环境阻断。
- **R01/R04/R05/R07**：代码实现完成并通过窄测试/类型检查，但缺少真实 API/浏览器/对象存储集成验证。
- **genes/index.tsx 类型错误**：TanStack Router `search` 属性缺失（既有错误，非本轮引入）。

### 恢复步骤

```bash
# 1. 配置隔离测试库后重跑 PG 集成测试
export SOYMUTDB_TEST_DATABASE_URL=postgresql+asyncpg://...
cd apps/api && .venv/bin/python -m pytest tests/test_mutants.py tests/test_search_database_integration.py tests/test_migrations.py -q

# 2. worker 测试
cd apps/worker && .venv/bin/python -m pip install pytest pytest-asyncio
.venv/bin/python -m pytest tests/ -q

# 3. 根门禁
pnpm lint && pnpm typecheck && pnpm test && pnpm build
pnpm --filter @soymutdb/web build:sites
```

## 产品实现 / 数据就绪 / 部署验收结论

- **产品实现**：W0 的历史清点与契约记录存在；W1 代码层面已有实现（模型、迁移、worker 同步、API client 公开身份、前端 assembly 传递），因环境阻断未运行完整集成测试；W2.2 核心后端歧义处理与前端调用链已有修改。R02/R03/R06 只有局部单元或语法证据，均为 IMPLEMENTED_UNVERIFIED；R04/R05/R07 同样待集成验证；V01–V03 未完成真实验收。
- **数据就绪**：未开始。合成 fixture 设计待 W1–W2 环境恢复后验证；真实科研数据依赖仍需业务输入。
- **部署验收**：未开始。环境版本符合要求，但数据库、双站制品、E2E 均未运行。

---

## 本轮记录（2026-09-09 追加：R01–R07/V01–V03 隔离 PG 复核与真实缺口修复）

- 日期/HEAD：2026-09-09 / `6592dfd8e` + 本轮 diff（工作树含既有未提交修改，本轮未清理）
- 环境：无 Docker，但启用了 mamba 隔离 PostgreSQL 16（`.mamba-root/envs/postgres16`，端口 55432，trust 认证，fixture 库 `soymutdb_testfixtures` 每次运行前 drop/create；runtime 库未动）。pytest 经 `SOYMUTDB_TEST_DATABASE_URL=postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_testfixtures` 注入，与 `docs/dev/mamba-validation-environment.md` 一致。注意 `soymutdb-test` conda 解释器为 Python 3.13；本轮全部 API/迁移测试改用 `apps/api/.venv/bin/python`（3.14.6，符合 C17）。

### R/V 状态更新

| 编号 | 状态 | 本轮改动 | 验收证据（命令/cwd/结果） |
|---|---|---|---|
| R01 | IMPLEMENTED_UNVERIFIED→部分 VERIFIED | api-client `isMutantLineId` 取消 trim（canonical 语义）；`homolog.test` 断言对齐 assembly 转发；openapi.d.ts 正式重生成（+1247/−248） | `pnpm --filter @soymutdb/api-client check:contract` → PASS；`test` → 112 passed；`typecheck` → 0；`apps/api` `tests/test_mutants.py tests/test_search_contract.py` 全过（含 46 passed 组） |
| R02 | VERIFIED（隔离 PG） | worker venv 补 pip/pytest/alembic/asyncpg/pydantic-settings，安装本地 `packages/jobs-py`（editable，替换过期 site-packages 副本）；`test_module_tsv_postgres_integration.postgres_engine` 增加 `SOYMUTDB_TEST_DATABASE_URL` 外部库路径（testcontainers 仍为默认） | `apps/worker` `pytest tests -q` → 301 passed, 4 skipped（3 个 PG 集成 gate 启用后 7 passed：module_tsv + gene_resolution） |
| R03 | IMPLEMENTED_UNVERIFIED→VERIFIED（隔离 PG） | 新增 `apps/worker/src/soymutdb_worker/tasks/gene_resolution.py`（`resolve_gene_accessions`/`AssemblyResolutionError`，batch 解析，无 per-row 查询）；`tables.py` 增加 `assemblies` Core 表；expression.py/homolog.py 接入 `assembly` 参数：未知/歧义 assembly 显式 FAILED，歧义 accession 计数跳过（`skipped_ambiguous_gene` 等审计字段） | `apps/worker` `pytest tests/test_gene_resolution.py`（隔离 PG，v4/v5 同 accession）→ 4 passed |
| R04 | IMPLEMENTED_UNVERIFIED→部分 VERIFIED | `genes/index.tsx`、`search/location.tsx`、`antd-home.tsx` 基因/入口链接补 assembly 上下文（TS2741 根因修复） | `pnpm typecheck` → 6/6 通过（原先 web 6 错 + admin 1 错全部修复） |
| R05 | VERIFIED | `query-keys.ts` 新增 `genes.search` 工厂（q/assembly/page/release/siteVariant）；`search/genes.tsx` 改用工厂 + placeholderData 仅同上下文保留；`search.tsx` 移除从未接入请求的 tissue/treatment/min_fpkm 死参数；variants/index 修复 validateSearch `""` 字面量宽化 + Select 泛型 | `pnpm check:web-query-keys` → PASS（5 consumers）；`query-keys.test.ts` → 5 passed |
| R06 | VERIFIED（真实应用 HTTP） | `app/core/exceptions.py`：`AuthenticationError`/`AuthorizationError` 及 401/403 响应统一携带 `Cache-Control: private, no-store` | 新增 `apps/api/tests/test_search_internal_http.py`（真实 FastAPI app + client）→ 3 passed：成功/匿名/无权限三态均断言 private, no-store |
| R07 | IMPLEMENTED_UNVERIFIED（环境阻断） | 无新改动 | 对象键 `{release_id}/{assembly_id}/genes/{accession}` 已有；无 MinIO，隔离对象存储双版本写读验证仍缺 |
| V01 | VERIFIED（隔离 PG） | worker 集成测试硬编码 head `0021` 改为从 Alembic 链计算（`_expected_alembic_head`） | `apps/api` `pytest tests/test_migrations.py` → 8 passed；worker `test_module_tsv_integration_schema...` 对 head=0034 校验通过 |
| V02 | VERIFIED（隔离 PG） | 新增 `apps/api/app/services/public_id_service.py`（`ensure_public_id`：begin_nested 冲突重试、不覆盖已签发号）；`release_service.publish_release` 增加 public_id 完整性守卫（缺号 → ReleaseNotReady，状态机不变） | 新增 `apps/api/tests/test_public_id_service.py` → 5 passed（含独立 PG 连接并发签发碰撞、发布缺号拒绝、成功发布） |
| V03 | IMPLEMENTED_UNVERIFIED→VERIFIED（隔离 PG） | 无新改动 | `tests/test_search_database_integration.py` → 9 passed（真实 PG fixture：公开/未发布/删除、双 ID、v4/v5 同 accession、crosswalk 正反例、literal %/_） |

### 本轮实际行为变化（摘要）

1. 发布守卫：READY release 内含未签号 mutant line 时拒绝发布且不改变 pointer/状态。
2. public_id 签发路径落地（重试、防覆盖），worker expression/homolog 导入支持 assembly 消歧与跳过审计。
3. 内部搜索及所有 401/403 错误响应 `private, no-store`（真实应用级断言）。
4. 前端：query key 工厂补全（gene search 含 release/site）；基因列表/位置搜索/首页入口链接携带 assembly 上下文；variants URL 联合类型修复；mutants 详情页 canonical public_id 门禁（SM 前缀 fast-fail，长度待业务冻结）。
5. 契约同步：openapi.d.ts 从当前后端正式重生成；`packages/{api-client,i18n,shared}` 10 个被意外删除的已跟踪 manifest/config 从 HEAD 恢复（仅撤销删除，不覆盖未提交内容）。

### 遗留（非本轮引入，记录在案）

- `apps/api` 全套（隔离 PG，从仓库根运行）：1445 passed / 33 failed；其中 2 例为我修复的 release_service fake（现 4/4 通过），其余 31 例位于既有未提交工作改造的模块（expression/homolog keyset、exppattern/seqfetch gene_pk 重构、新增未跟踪测试），归属既有工作。
- `apps/admin` lint/test 失败：30 个文件属既有未提交工作（14 未跟踪新文件 + 4 修改）或 HEAD 遗留；本轮仅修复 `news/trash.tsx` statusColor 类型错误与 web `soymutdb-widget` 死接口。
- E2E（Playwright）、双站 build:sites、R07 对象存储集成：本轮未运行（环境/范围限制），保持 IMPLEMENTED_UNVERIFIED。
- 真实科研数据、public_id 格式冻结、生产迁移/发布授权：业务输入未决，未编造批准。

### 本轮命令记录

```bash
# cwd: 仓库根；PG 由 mamba 隔离实例提供（55432）
node --version && pnpm --version && python3 --version && git rev-parse HEAD   # 24.19.0 / 11.21.0 / 3.14.6 / 6592dfd8e
apps/api/.venv/bin/python -m pytest apps/api/tests -q --rootdir=.            # 1445 passed, 33 failed（30 例既有 + 2 已修 + 1 popgen 未复跑归类）
# 另：worker 301 passed/4 skipped；worker PG gate 7 passed；api-client 112 passed；
# web query-keys 5 passed；mutants-discovery 9 passed；api 内部搜索 HTTP 3 passed；public_id 5 passed
```
