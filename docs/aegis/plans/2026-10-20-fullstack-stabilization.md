# SoyMutDB 增量稳定性实施计划

## 目标、架构与技术栈

按已确认设计 `docs/superpowers/specs/2026-10-20-fullstack-stabilization-design.md` 修复真实断链，保留 React/Umi/Ant Design + FastAPI/PostgreSQL + Celery 与共享客户端。使用 `mm/MiniMax-M3.1-Flash` 子代理，主代理负责集成、复核和 Git。基线 PR #26 不再混入修复。

## 基线与边界

TaskStartSnapshot：`baseline/workspace-20261020` 的 `57e2bcdee3bab3435578997dba85cf26c3b985bc`；修复分支 `fix/fullstack-stabilization-20261020`。设计提交 `01fc163`。开始实现时无既有业务脏改动。

必读：`AGENTS.md`、`.ai-memory/LOCAL-RUN-ENV.md`、`docs/dev/database-core-contract.md`、`docs/ops/dependency-governance.md` 及涉及依赖的 ADR。核心契约旧文档中 ClickHouse 描述已过期，按更具体 AGENTS.md/native-postgres-cutover.md 执行 PostgreSQL 权威规则，不回退架构。

必要性：链接生产者/消费者丢失 release、分页字段无人消费和 API/Worker 键空间不一致属于运行时代码错误，单改说明或配置不能恢复功能。最小修复位于原所有者，不引入第二套 transport、任务框架或存储。

TDD Route：mode=off，decision=skipped，authority=会话配置；不强制 test-first，仍要求复现/回归及负向安全测试。

ArchitectureReviewRequired：跨模块公开身份/导出/新增 API 改动需要独立复核；普通上下文传递保留既有所有者即可。执行前对审计结论逐项核实，审计严重度和建议不是事实或实现指令。

## 执行任务

### 1. 浏览器上下文链路

写范围：`apps/web/src/routes/blast.tsx` 及相关测试、必要时同类 gene/gbrowse 链接；`apps/jbrowse/src/App.tsx` 及既有 node:test 契约测试。

- 核实 BLAST 作业是否有固有 release；优先使用作业真实上下文，不能把旧作业结果冒充当前发布。
- 可信 release 随链接传递；未知时禁用并提示，不移除 `/browser` 的 fail-closed 门禁。
- JBrowse assemblies 与 config 显式传同一 release；避免修改全局 transport pin 造成组件状态与请求竞态。
- 验证：门户窄 Vitest、JBrowse node:test、两应用 typecheck/lint；覆盖 release A/B 切换、缺上下文、无坐标。

### 2. 变异公开筛选与导出边界

写范围待复现后确定：`apps/api/app/api/v1/variants.py`、`schemas/variant.py`、`services/variant_repository.py`、`postgres_variant_service.py`、Worker `tasks/export.py` 及相关测试/共享契约。

- 验证 public_id 解析后的 PostgreSQL 自增键是否错误绑定到历史 hash surrogate。
- 使用权威实体关联，保留 release/公开可见性；不能用内部 ID 猜测或哈希推导 public_id。
- 导出请求拒绝客户端内部键，公开过滤在 API 侧授权解析后交给 Worker；保留旧接口的合规行为。
- 验证：隔离 PostgreSQL 下主键刻意不等于 hash 的真实回归，跨 release/未发布/内部 ID 负例，Worker SQL 和 OpenAPI/client 验证。

### 3. 全局搜索分页/类型过滤

写范围：`apps/web/src/routes/search.tsx`、相关测试和需要的中英文资源。

- 消费已有 next_cursor/has_more，提供 URL 驱动的翻页和过滤；参数变更清游标，保留 assembly/release。
- 内部目录不伪造分页；历史深链无法回退时提供回首页而非错误上一页。
- 回归覆盖 next/prev、多页、尾页、筛选重置、发布切换、internal 分支和错误恢复。

### 4. 株系检索/分页与预览链接

- 核实 `/mutants` 的现有字段、响应及上下文；兼容增加 q 与分页（如改变响应形状则另确认），旧 mutagen 仍精确过滤。参数及通配符字面值、release、可见性在 PostgreSQL 负例中验证。
- 新闻预览显式门户 origin；相对/缺配置不能把 token 发往管理端或猜测的站点。补部署输入传递契约、UI 可恢复错误和绝对 URL 测试。

### 5. 作业/下载/MCP 扩展

已核实没有通用 job 表/结果读取路由可复用：现有 jobs.py 仅 SSE，outbox 只拥有投递状态，不应承载执行结果，Celery Redis 为可丢弃。用户已单独批准最小扩展：新增 PostgreSQL variant_exports 记录 owner/状态/产物/到期时间，保留 POST 响应兼容，增加状态与下载 GET；仅本人或管理员可读，产物保留沿用现有7天，下载 URL 短时现签。复用现有 JobPayload/JobStatus 与 Worker claim 模式，不建通用任务框架。首批不增加自动执行重试、人工 retry 新端点或 MCP 导出写工具（审计建议的额外接口未纳入该批准）。覆盖提交/任务成功失败/状态/下载全链、迁移往返和授权负例；不能把不可猜 UUID 当授权。

核实 retry 预算是否表示执行重试；禁止全异常自动重试掩盖确定性错误或造成重复科学计算/副作用。按任务幂等性与瞬时故障分类选择修复，保留明确的最终失败和用户恢复入口。MCP 复用现有结果/download API，不把对象 key 当可访问 URL。

补充确认（2026-10-22）：用户批准“重投遇到过期 running 时安全失败、不接管重算”。保留活跃租约去重，过期后以状态/观察时间戳保护的 UPDATE 置 failed；旧执行晚到成功不得覆盖 failed。此规则由重投触发，不承诺无重投时自动清理 running；可能仍在执行的原进程及未发布对象沿用既有运维/保留策略，用户通过重新提交新导出恢复。不新增接口、表结构或自动重试。

### 6. 依赖迭代与交付

- 只读查询当前声明、锁图、上游可用版本/安全公告/peer 与现有 ADR；列出兼容候选及需推迟的大版本。
- 主代理独占 manifest/lock 写入和安装，安装不得与子代理测试并行。只升级经过验证的一批；更新锁并跑 frozen check、治理契约、相关单测/typecheck/build。
- 每批子代理实现后先审契约符合性，再审代码质量，主代理独立验证并按精确路径提交。
- 最终提供用户可见结果、精确测试计数、未覆盖项与风险。单测/构建不冒充浏览器验收；不自动合并/发布。

## 退役与复杂度

优先在原文件就地修复，移除同一批引入的失效分支，不增加泛化 fallback。既有合规参数为兼容保留；新 API 若必要应通过原客户端/契约生成链。没有证据的审计发现保留为待复现，不为关闭清单造实现。
