# 方案依据与资料核验

> **已归档（2026-10-01）**：智能体执行日志与提示词草稿（治理要求工作区不存放日志）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §7 变更记录；执行结论见 docs/dev/project-status.md。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

核验日期：2026-09-08。此文件记录方案依据，不是产品测试报告。

## 项目阅读与复核

本次派发两路项目阅读（后端/数据/部署；前端/客户端/界面）与一路官方资料收集，均要求只读。主代理负责冲突裁决、设计和最终方案。子代理报告只是线索，关键现状以文件复核为准。

| 文件 | 用途与界限 |
| --- | --- |
| 根 AGENTS.md | 本次用户明确提供的产品/工程硬约束 |
| package.json、apps/web/package.json、packages/api-client/package.json | 技术版本、双站构建、client 生成/contract 入口 |
| apps/api/app/models/variant.py:138–196 | 观察 MutantLine 私有键及 public_id 已存在；不证明迁移或发布已完成 |
| apps/api/app/models/genomic.py:104–174、:258 起 | 观察 gene_pk/accession/assembly 唯一约束与 Crosswalk 模型；不证明引用消费者或映射数据已就绪 |
| docs/dev/database-core-contract.md | normative 行为、fixture 和矩阵；其中历史现状段落需重验 |
| docs/dev/pi-agent-hard-constraints.md | 复用 H01–H12 与真实负测/证据要求 |
| docs/dev/database-execution-handoff.md | 复用核心 T0–T5 的迁移/消费者/验收思路，扩展为本轮 W0–W7 |
| docs/dev/database-execution-status.md | 历史状态和测试记录；与当前模型存在差异，不能直接复用其结论 |
| docs/dev/optimization-master-plan.md、docs/dev/README.md | 既有优化索引和勘误；不重复“导入草稿未写库”“nginx ^~ 路由错误”等已被澄清的误判 |
| docs/dev/architecture-and-deployment.md | 存储权威、发布状态机、不可变制品、CI/部署合同；目标描述与真实部署证明分开 |
| docs/ops/antd6-design-system.md | AntD facade/token/provider、动效/视口/交互尺寸等设计基线 |
| docs/ops/acceptance-current-state.md | 历史真实数据/生产验收依赖；2026-08-23 状态不能当作本轮 live 验证 |

行号是本轮阅读位置，后续修改可能漂移。PI 在 W0 记录新的 HEAD 和相关文件摘要，逐项刷新。

主代理随后抽查确认：worker ingest 仍有 gene hash surrogate；mutant client 仍按数字私有主键定义公共身份；gene detail 只有 URL assembly 校验，实际三个查询未传 assembly；搜索/详情缓存键上下文不足；Admin 根级和路由错误边界已经存在。对应准确位置和首批验收已写入 plan.md §2。

进一步确认 `apps/worker/src/soymutdb_worker/tables.py:73` 的 Core genes 定义缺 gene_pk/accession，而 `tasks/static_pages.py:339` 已访问两列；这是当前工作树的明确静态不一致。静态任务对象键仅见 accession，bucket/prefix 是否提供额外上下文隔离仍需运行链路核验，不能仅凭局部代码断言已覆盖对象。

内部搜索服务端角色依赖和审计已存在，不能再列为“缺少整个内部端点”。其 no-store 是否由 middleware 设置尚未经过真实响应验证，因此本包将其列为行为核验项，不直接宣称线上缺头。联邦搜索 sources 不等于站点 variant，不能由该缓存键简短便推断泄漏。

当前读取 HEAD 为 `6592dfd8e`，工作树存在大量预先修改；本次只新增本目录四份方案文档，没有把这些既有修改认领为本次成果。

## PI 官方资料

PI 按 pi coding agent 理解；官方旧仓库 `badlogic/pi-mono` 当前重定向到 `earendil-works/pi`。此事实不证明本机已安装任何版本。启动前执行 `pi --version`、`pi --help` 并核对 provider 模型清单。

- [Usage / CLI / Context / Trust](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/usage.md)：核验 `-p`、`--append-system-prompt`、会话选择、上下文加载和项目 trust。AGENTS 可被同目录 AGENTS.override.md 替换，因此执行前要检查实际加载项；本包不会创建 override。
- [Coding agent README](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/README.md)：核验 `@file` 输入、`--provider`、`--model`、`--list-models` 和工具配置。保留默认提示，命令行显式模型需使用真实 provider 名称。
- [Models](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md)：自定义 provider 配置参考，具体 endpoint/凭证由运行环境配置；本包不写入认证文件。

实践选择（本项目设计）：默认单实例+阶段状态文件，交互执行或每次 print 一个阶段，依据证据推进；不默认信任项目扩展、不把提示词当沙箱、不靠程序退出码判定完成。此选择是本方案的执行策略，不是 PI 自动提供的完整门禁系统。

## 生物信息学资料

- [Ensembl Genome Assemblies](https://www.ensembl.org/info/genome/genebuild/assembly.html)：assembly 是序列的计算表示；版本/accession 用于区分不同参考序列。页面本轮指向 June 2026 archive。支持把 assembly 身份作为显式数据上下文，而不是将 v4/v5 当显示标签。
- [NCBI Genome assembly report](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/reference-docs/data-reports/genome-assembly/)：assembly report 记录名称、状态、发布日期及来源等元信息，为 provenance 字段提供参考。

本项目“v4↔v5 必须显式 crosswalk、不得按字符串或坐标猜等价”的直接约束来自 AGENTS.md 和 database-core-contract.md；以上资料支持 assembly/provenance 设计背景，不声称它们提供了本项目可直接使用的基因 crosswalk 数据。真实 Wm82 v4/v5 文件、精确 accession、来源版本、许可和映射证据仍须核验。

## 本次验证范围

已做：读取规范/关键代码/已有计划；核验官方文档；制定可执行方案并检查新文档引用。

文档检查结果：4 份 Markdown，3 个本地 Markdown 链接均存在，代码围栏配对和尾随空格检查 0 问题。该检查不验证产品功能。

未做：产品代码修改、依赖安装、数据库写入/迁移、单元/集成/E2E/双站构建、真实数据验证、PI 启动、正式部署。历史测试数字和截图未作为本次通过结果。
