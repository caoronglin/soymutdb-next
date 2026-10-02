# 给 PI 的执行任务：SoyMutDB 整体完善

> **已归档（2026-10-01）**：智能体执行日志与提示词草稿（治理要求工作区不存放日志）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §7 变更记录；执行结论见 docs/dev/project-status.md。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

你负责执行 SoyMutDB 的整体完善方案。使用中文沟通；以现有代码、权威契约和可复现测试证据交付。默认单实例，不自行派发额外智能体。

工作目录必须是实际仓库根目录。先读取：

1. 根 AGENTS.md 与本次任务所适用子目录的 AGENTS.md。
2. docs/dev/pi-overall-2026-09-08/plan.md 全文。
3. docs/dev/database-core-contract.md 的目标行为和测试矩阵。
4. docs/dev/pi-agent-hard-constraints.md 的 H01–H12。
5. 本包 execution-status.md（若存在）；本包 sources.md 和 docs/dev/architecture-and-deployment.md 按当前阶段查阅。

本次用户明确采用仓库 AGENTS.md 约束。旧 docs/dev/pi-agent-system-prompt.md 与 database-execution-status.md 中“AGENTS.md 已撤销”的历史表述不适用；不要将其加载成替代系统提示。运行平台的权限和指令优先级继续生效，本文件不授予额外系统权限。

目标是可检索、版本明确、可追溯的生物信息学数据库。维持 PostgreSQL 权威、ClickHouse 分析投影、MinIO 对象、Redis 可丢弃缓存/队列的分工。保持 React/Vite/AntD/FastAPI/Celery/pnpm/Turbo，不进行无关框架重写。

先执行 W0：核对实际 HEAD/未提交改动与归属、Node/pnpm/Python、迁移 head、模型和消费者、真实 API/client/测试入口。不要照旧状态文档重建已存在的 public_id、gene_pk、GeneCrosswalk 或错误边界。记录“已有且证据有效 / 已有待验证 / 实际缺口 / 缺少业务输入”。首次创建本包 execution-status.md，不覆盖旧证据。

冻结公开/内部编号语义、碰撞规则、API 路径字段、assembly/release 分组语义、权限作用域和迁移策略。技术内的可逆决定自主完成；编号签发、历史科研数据回填、内部业务字段是否公开、数据许可等无法查证时列具体输入，只暂停相关动作，继续独立任务。

若用户指定单个阶段，只执行该阶段及必要验证；否则按 W0→W1→W2→W3→W4→W5→W6→W7 推进依赖已满足的工作，不在计划或骨架处宣布完成。W8 为独立后续范围。

硬要求：

- public_id 独立稳定唯一，发布前非空；外站不接受内部键定位、不返回内部编号、私有或未发布记录，也不确认内部编号是否存在。
- 内站内部查询必须服务端 RBAC/数据范围授权，不能只要求登录或隐藏 UI。
- v4/v5 是不同身份/坐标命名空间，无版本查询分组或消歧，不静默默认。跨版本关系只取有 provenance 的显式映射。
- assembly/release 贯穿搜索→详情→序列/表达/变异→JBrowse/导出。缓存和 cursor 绑定完整查询上下文；内部授权范围另隔离或禁缓存。
- external/internal 显式构建，制品/origin/CORS/SW/cache 分开；内部 private/no-store。扫描必须使用实际注入输入的合成保护值，并先验证扫描器能检出污染。
- 复用现有状态机、outbox/幂等/审计、不可变制品、stale-task guard；不能以 UI 成功提示代替权威状态。
- OpenAPI 正式生成 client，更新所有消费者；不手改生成物冒充契约完成。
- 使用 AntD facade/token/i18n；数据库入口、结构化列表和详情优先；完成响应式、键盘、空错态、reduced-motion 验收。
- 不删除/skip/xfail 关键测试、降低断言、吞错、返回假数据或修改忽略规则来制造绿色；不把 mock、语法解析或历史日志当真实集成通过。
- 不覆盖无关 diff，不清空工作区，不擅自提交/推送/生产发布。迁移文件与隔离测试可实施，生产迁移/回填/正式发布需另有明确授权。
- fixture 仅用合成数据；检查测试数据库清理行为和隔离目标后再运行写入。日志/提示词不含真实凭证或未公开科研数据。

每个原子任务先建立能捕捉缺口的回归场景，最小修复后跑窄测试，再执行该阶段和最终集成门禁。旧实现正确且证据有效时复用，避免重复重构。精确命令以当前仓库脚本为准，计划中的命令不是已运行结果。

每个原子任务完成、阶段结束和上下文压缩前，更新 execution-status.md：文件、契约、HEAD/diff 摘要、命令/cwd/时间/退出码/真实计数、证据、阻碍和下一步。状态仅用 NOT_STARTED / IN_PROGRESS / BLOCKED / IMPLEMENTED_UNVERIFIED / VERIFIED；关键验收未运行时不能 VERIFIED。

环境问题要与断言失败区分；同因失败先调查根因，不重复无效命令。持续做已授权且输入齐全的工作；若所有剩余任务都依赖缺失输入，明确具体输入、受阻任务、已尝试方法与恢复动作。

最终交付：完成范围和文件、行为变化、真实验证结果、未完成/未验证/外部依赖、可复现命令和下一步。分开报告产品实现、真实科研数据、部署验收。测试通过不等于已获得发布授权；关键门禁未过时明确不能发布。
