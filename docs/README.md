# SoyMutDB 文档总入口

> 2026-10-01 整理：把 233 份文档收敛成「**当前只看这些**」+「其余已归档」。
> 归档清单见 [`ARCHIVE.md`](ARCHIVE.md)。归档文件仍保留原文与历史价值，但**不得作为现状引用**。

## 1. 现在该读哪几份

| 想知道 | 读这份 |
| --- | --- |
| 现在到底是什么状态（门禁数字、红灯、缺口） | [`dev/project-status.md`](dev/project-status.md) |
| 改代码前的双基线、需求判据、七维复审 | [`aegis/baseline/2026-10-01-react-only-baseline.md`](aegis/baseline/2026-10-01-react-only-baseline.md) |
| 全部设计与计划的整合视图与待决项 | [`3.9升级优化文档.md`](3.9升级优化文档.md) |
| 2026-10-02 优化/消融设计草稿的审计结论与执行前修订项 | [`dev/design-audit-2026-10-02.md`](dev/design-audit-2026-10-02.md) |
| 审计后全局优化的硬性约束、施工顺序与阶段验收 | [`aegis/plans/2026-10-02-audited-optimization-execution.md`](aegis/plans/2026-10-02-audited-optimization-execution.md) |
| 在新对话开始实施的完整提示词 | [`dev/execute-audited-optimization-prompt.md`](dev/execute-audited-optimization-prompt.md) |
| 生物信息学核心契约（身份、assembly、双站、缓存、测试矩阵） | [`dev/database-core-contract.md`](dev/database-core-contract.md) |
| 架构、状态机、接口契约、CI 与部署 | [`dev/architecture-and-deployment.md`](dev/architecture-and-deployment.md) |
| 数据导入、Release 与恢复的操作手册 | [`ops/README.md`](ops/README.md) |
| 交付流水线怎么跑（CNB 主链路） | [`ops/ci-cd.md`](ops/ci-cd.md) |
| 跨应用总览、API 与端口、部署运维、多实例信任 | [`wiki/README.md`](wiki/README.md) |

## 2. 现行设计（按领域）

| 领域 | 文档 |
| --- | --- |
| 门户信息架构、搜索工具页、结果列顺序 | [`superpowers/specs/2026-08-14-public-web-layout-alignment-design.md`](superpowers/specs/2026-08-14-public-web-layout-alignment-design.md) |
| 导入状态机、发布/回滚、搜索契约 | [`superpowers/specs/2026-08-13-data-publishing-and-search-ia-design.md`](superpowers/specs/2026-08-13-data-publishing-and-search-ia-design.md) |
| 产品与架构基线、身份/双站契约（frozen） | [`superpowers/specs/2026-09-14-soymutdb-baseline-development-design.md`](superpowers/specs/2026-09-14-soymutdb-baseline-development-design.md) |
| 前端统一到 React 19 + Umi Max + antd 6 + ProComponents | [`superpowers/specs/2026-09-27-react-pro-v6-replatform-design.md`](superpowers/specs/2026-09-27-react-pro-v6-replatform-design.md) |
| 门户 UI 整改与可见文案守卫 | [`superpowers/specs/2026-09-28-portal-ui-quality-remediation-design.md`](superpowers/specs/2026-09-28-portal-ui-quality-remediation-design.md) |
| 页脚可编辑、搜索控件、字体与性能门禁 | [`superpowers/specs/2026-09-28-admin-editable-footer-search-font-design.md`](superpowers/specs/2026-09-28-admin-editable-footer-search-font-design.md) |
| 管理后台对齐官方 Pro sub-page 实例 | [`superpowers/specs/2026-10-01-admin-pro-migration-design.md`](superpowers/specs/2026-10-01-admin-pro-migration-design.md) |
| 多物种门户（远期） | [`superpowers/specs/2026-07-12-multispecies-portal-design-spec.md`](superpowers/specs/2026-07-12-multispecies-portal-design-spec.md) |
| 本体 PostgreSQL 控制平面（中远期） | [`superpowers/specs/2026-07-15-ontology-postgresql-control-plane-design.md`](superpowers/specs/2026-07-15-ontology-postgresql-control-plane-design.md) |

## 3. 现行计划

统一在 [`aegis/INDEX.md`](aegis/INDEX.md) 登记（含状态与所属领域）：

- [DIAMOND / Biopython / pyDEG / Rust 审计与实施](aegis/plans/2026-10-05-blast-diamond-and-enrichment-rust.md) — 核实旧报告、修复比对与统计缺陷；比对链路已收敛为 DIAMOND `blastp` 单一引擎；Python 数值核合成基准约 2.14 倍提速，后端根门禁通过；M0–M7 覆盖 Biopython、Rust 真实负载门禁及 pyDEG 环境/作业/切流回滚；M0 真实注释数据仍缺；2026-10-08 撤回“无导入实现”，M0-1 收敛到既有 API draft-only/不可变快照链，补 dry-run、字节摘要和行数核对并退役重复 worker owner；切片 60 通过，根门禁见计划。profiler 区分数据库回放与真实负载，fixture 中位数不降低 Rust ≥20% 完整路径 p95 门槛；生产迁移待执行。

- [`aegis/plans/2026-10-01-admin-pro-migration.md`](aegis/plans/2026-10-01-admin-pro-migration.md) — 管理后台 Pro 迁移 A1–A6（待执行，A5 可并行）
- [`aegis/plans/2026-10-02-audited-optimization-execution.md`](aegis/plans/2026-10-02-audited-optimization-execution.md) — 审计后总方案（H-01–H-18、W0–W7；**W0–W4 已完成，W6 仅框架**；阶段证据见 [rebaseline](aegis/baseline/2026-10-02-w0-rebaseline.md) §8–§9）
- [`aegis/plans/2026-09-28-admin-editable-footer-search-font.md`](aegis/plans/2026-09-28-admin-editable-footer-search-font.md) — 页脚/搜索/字体 Task 0–5（Task 1 部分完成）
- [`aegis/plans/2026-09-28-portal-ui-quality-remediation.md`](aegis/plans/2026-09-28-portal-ui-quality-remediation.md) — 门户 UI 整改（部分完成；**可见文案守卫已清零**，窄屏/焦点已在真实浏览器验证）
- [`aegis/plans/2026-09-27-react-pro-v6-replatform.md`](aegis/plans/2026-09-27-react-pro-v6-replatform.md) — 前端栈迁移（已完成栈，Pro 组件体系未落地）
- [`aegis/plans/2026-08-31-*.md`](aegis/plans/) — 新闻回收站、修订排程、突变体发现 P0

## 4. 决策记录（ADR，不随时间失效）

[`adr/`](adr/)：平台交付契约、antd 包体预算、Kind/K8s 验证、模块化数据行角色、导入幂等与可见性、
`total_count` 语义、支持的部署架构、弃用 antd pilot 路由、退役 Page Builder/Widgets。

## 5. 其余目录怎么读

| 目录 | 说明 |
| --- | --- |
| [`dev/`](dev/) | 开发者入口（[`dev/README.md`](dev/README.md)）、架构与部署、核心契约、智能体运行手册（`pi-agent-runbook.md` 等） |
| [`ops/`](ops/) | 运维与 Admin 手册：生产就绪、数据导入与发布、备份恢复、依赖治理、通知、慢查询日志 |
| [`wiki/`](wiki/) | 面向人的总览：应用状态、API/端口、部署运维、多实例信任 |
| [`user/`](user/) | 科研用户指南 |
| [`design/`](design/) | 架构与依赖图（含标注为历史参考的部署架构） |
| [`aegis/`](aegis/) | 治理工作区：基线、计划、工作记录、方法包工件 |
| `superpowers/plans/`、`superpowers/specs/` | 历史实施计划（已归档）与现行设计 |
| `agent-state/`、`research/`、`dev/ablation/`、`dev/opt2..5/` | 执行日志与逐轮报告（已归档） |

## 6. 维护规则

1. 结论变了就**改现行文档并更新归档横幅**，不要新开一份同主题文档；
2. 新文档必须登记进 [`aegis/INDEX.md`](aegis/INDEX.md)，并在本页入口表里给出「回答什么问题」；
3. 被取代的文档**移到归档**（加横幅 + 登记到 [`ARCHIVE.md`](ARCHIVE.md)），**不要直接删除**——删除会切断审计链，
   而本项目的多条契约要求「变更可见、有继任者」；
4. **性能/安全类结论必须标注证据等级**：`单次计时`、`查询计划`、`单测通过` 都不等于 `端到端已验证`；缺证据就写「未验证」，不得把方向性判断写成量化结论（依据：[`dev/design-audit-2026-10-02.md`](dev/design-audit-2026-10-02.md) D-08 / D-10）；
5. **间接调用即已接线**：判断「某守卫/脚本是否在 CI 中」必须沿 `job → 共享脚本 → 守卫` 逐跳核对，只搜 job 文件会得出「零调用方」的错误结论（同上 D-01）；
6. 文档与代码冲突时，先判定谁是错的：代码错就修代码并在文档标注日期，文档错就改文档。
   **不允许文档单方面描述未发生的事**（这条是本项目吃过亏的：状态文档曾长期写着「三端均为 Vue 3」）。