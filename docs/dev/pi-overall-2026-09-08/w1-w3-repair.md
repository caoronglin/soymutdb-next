# PI 接续任务：W1–W3 真实缺口修复与验证

> **已归档（2026-10-01）**：智能体执行日志与提示词草稿（治理要求工作区不存放日志）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §7 变更记录；执行结论见 docs/dev/project-status.md。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

本文件将用户重复粘贴的清单去重，形成一次实施任务。沿用本包 prompt.md、plan.md、仓库 AGENTS.md、database-core-contract.md 和 H01–H12。本文件是交给 PI 的修复指令，不是修复完成报告。

## 范围与执行方式

继续已有 W0，不重复输出整体规划。先读本目录 execution-status.md（若存在），核对当前工作树和冻结契约；只补缺失的基线/契约记录，然后实施下面 R01–R07。已修复项验证后复用，不照历史行号重做。

本轮范围为 W1–W3 加上其直接依赖的静态对象隔离验证/修复。R07 原归 W5，本次提前处理这一具体依赖，不扩展为整个 W4–W7。默认单实例，保留既有未提交修改；不进行生产写入、回填、迁移或发布。

R01–R05 是用户确认的缺口线索，实施前重验代码；R06–R07 是待验证行为，不先宣判缺陷。下述“无运行证据”仅表示本次尚未拿到有效结果，不等于仓库没有相应测试文件。

## 修复清单与通过条件

| 编号 | 归属与位置 | 实施要求 | 必须通过 |
| --- | --- | --- | --- |
| R01 | W3.1；packages/api-client/src/mutant-lines.ts 及 Web 调用方 | 公开身份迁移到 public_id；核对当前 API 路径、参数和 DTO；从权威 OpenAPI 重新生成生成部分，同步手写客户端封装、详情/表型/相关操作，禁止改生成物冒充生成 | 合法非数字 public_id 可列表→详情→相关数据；现存/不存在 internal_id 不泄漏或确认存在性；OpenAPI/client contract、类型检查和相关回归 |
| R02 | W1.2；apps/worker/src/soymutdb_worker/tables.py | Core genes 与迁移后的 ORM 对齐：gene_pk/accession/assembly_id；expression_data/gene_homologs/gene_data_cache 的引用类型同步。核对全部 Core 查询/insert/upsert 消费者和约束，不只改声明 | 隔离 PG 执行 worker 真实查询/写入及 static_pages 数据查询；v4/v5 同 accession 可共存且关联不串；无缺列/类型错误/孤儿引用 |
| R03 | W1.3；apps/worker/src/soymutdb_worker/tasks/ingest.py | 先核对 CH gene surrogate 字段语义；从 PG 按 assembly + accession 解析 gene_pk。不得继续以 hash 冒充权威身份；未知/歧义引用明确报错或进入可审计隔离状态，不能静默写错误关联。批量解析避免逐变异查库 | 同 accession 跨 assembly 解析到各自 PG gene_pk；未知/歧义处理可验证；导入到 CH 再查询关联一致；检查样本身份解析是否存在同类问题，相关改动单独记录 |
| R04 | W3.2；apps/web/src/routes/genes/$geneId.tsx 及 genes client/API | assembly/release 从路由经 client 实际传给 getGene/getGeneExpression/getGeneHomologs 及序列/变异/JBrowse 消费者；若 API 尚不支持先在 W2 修契约。未知/不匹配上下文不回落默认 | 同名 v4/v5 详情、表达、homolog 与 JBrowse 的真实请求/返回上下文一致；无版本按冻结契约消歧；不能只验证 URL 字符串 |
| R05 | W3.2/W3.3；apps/web/src/lib/query-keys.ts、routes/search.tsx | query-key 工厂包括 site_variant/release/assembly 及 query/types/filters/sort/cursor 等实际影响集合的条件；内部按授权作用域隔离并在退出/撤权时清理。不要把联邦 sources/external 切换误当 site_variant | 同 query 跨站点、release、assembly、内部 A/B 用户交替请求不串数据；上下文切换后旧 placeholderData 不被作为新上下文结果呈现；分页状态重置 |
| R06 | W2.1/W2.3；internal_search 路由和 middleware | 先请求完整应用检查成功及拒绝响应的 Cache-Control，并检查 middleware。若缺失，再在唯一合适层补 private, no-store，避免重复/冲突头；不只改注释 | 真实应用 HTTP 响应头断言；匿名/普通登录/内部授权范围交叉测试；确认中间件或代理不会把内部响应改为公开缓存 |
| R07 | W1/W3 的静态数据依赖，提前自 W5；tasks/static_pages.py 及对象读写消费者 | 核对实际 bucket/prefix/key 和 release/assembly 的作用域；同 accession 双版本写入读取验证。若会覆盖，设计含 release/assembly 的对象命名空间并同步生产者、manifest、下载/API/SSG 消费者及旧对象兼容策略；不只改上传字符串 | 隔离对象存储中两个 release/assembly 的同名 accession 均可读取正确内容且互不覆盖；未发布对象不能经公开 URL/制品泄漏；旧歧义键不得静默回落 |

建议顺序：基线刷新 → R02 → R03 → W2 API 身份/版本/授权与 R06 → R01 → R04/R05 → R07 → 全部验收。R07 调查可提前进行；API/client 生成后如上游 schema 再改，重生成并重验。

## 三组必须补齐的运行证据

### V01：迁移 0032–0034

- 先核对实际 Alembic 文件和 head，不硬编码历史 revision 为当前 head，不重复新增同用途迁移。
- 在经确认隔离的 PostgreSQL 测试库，验证旧 schema 到目标 schema 的升级，包含已有数据、外键引用、public_id 和跨 assembly 基因。
- 验证可恢复的降级与再次升级；如旧 schema 无法表达跨 assembly 同 accession，测试明确拒绝及备份恢复/前滚策略，不能删除冲突科研数据以强行降级。
- 分别记录每次迁移命令、目标版本、退出码、数据/约束断言和恢复结果。

### V02：public_id 签发与发布

- 沿用已冻结的编号格式和签发策略；缺少业务输入时明确该依赖，不自行改公开号语义。
- 用独立 PG 连接/事务验证并发签发，不用单事务 savepoint 冒充并发；验证唯一约束以及实际重试或明确冲突响应。
- 故意注入候选编号碰撞，验证已签发编号不被覆盖/重分配；发布缺号必须失败且不改变 release/发布状态。
- 保留合法公开号正测与内部编号负测，禁止“一律返回空”或“禁止数字查询”换取通过。

### V03：真实 PostgreSQL 搜索集成

- fixture 至少含公开/未公开/删除记录、独立 public_id/internal_id、两个 release、v4/v5 同 accession、内部 A/B 不同权限范围，以及可信/无证据 crosswalk。
- 内部两种 ID 在授权范围内定位同一实体；外部仅公开身份可查，匿名内部查询不确认存在性。
- 指定与未指定 assembly/release 的行为符合冻结契约；不能固定 active release 隐藏另一个 assembly。
- 使用真实缓存后端或现有隔离缓存集成环境交替请求各作用域，验证服务端缓存和绑定 cursor；前端 query-key 单测不能替代服务端证明。

## 门禁与交付

复用已有测试，补缺失回归；精确命令先检查当前脚本和 fixture 清理规则。本包 plan.md §7 的窄测试、client generate/check:contract、根 lint/typecheck/test/build、双站 build、artifact 负测与真实 API E2E 均按改动范围执行；Python API/worker/迁移须各自有效运行。R07 额外运行真实隔离对象存储集成。

每个 R/V 项在本包 execution-status.md 记录：状态、修改文件、HEAD/diff 摘要、命令/cwd/时间/退出码、pass/fail/skip/xfail 计数、证据位置、依赖和下一步。延续既有 W 阶段状态，不覆盖旧日志。R01–R07 及 V01–V03 全部适用验收通过才可宣称本轮修复完成。

没有 PG/缓存/对象存储等环境时，明确哪些行为仅实现未验证并继续无依赖工作。关键行为未运行、失败、skip 或 xfail 都不能 VERIFIED。最终分别报告“修复完成”“验证通过”“待外部输入”，不能把本轮收尾当整个 W0–W7 完成或生产可发布。
