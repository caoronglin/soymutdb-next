# Aegis Records Index

Registry for durable Aegis records. Governance: [BASELINE-GOVERNANCE.md](BASELINE-GOVERNANCE.md).
Register new records here rather than duplicating them, and mark superseded records instead of deleting them.
Repository-wide document entry point: [docs/README.md](../README.md); superseded documents: [docs/ARCHIVE.md](../ARCHIVE.md).

## Start here

**2026-10-20 增量稳定性修复**：[实施计划](plans/2026-10-20-fullstack-stabilization.md) · [批准设计](../superpowers/specs/2026-10-20-fullstack-stabilization-design.md) · [当前检查点](work/2026-10-20-fullstack-stabilization/20-checkpoint.md)。基线为 Draft PR #26 / `57e2bcd`；修复进行中，不代表全线验收通过。

**2026-10-17 追加验收记录**：[非 Docker 验收与脱敏证据](../dev/native-validation-20261017.md)。涵盖客户端零路由债务、前端 1083 tests、真实导出链、原生 PG/S3 灾备和历史回填演练。以下旧计划的状态描述保留其原日期语境，当前实测结论优先查阅该报告与项目状态；不据此将未复核的计划全部结项。生产回填与切换、异地灾备尚未验收，Docker 运行按用户要求排除。

**2026-10-18 文档对账**：Admin Pro 组件、Import Studio、命令面板、原生 PG 变异事实等已在当前工作树实现。本索引只把有代码/测试证据的状态行改为已落地，未重跑的门禁数字仍引用 2026-10-17 报告；对账记录见下方 Record log。

1. [Current baseline (2026-10-01)](baseline/2026-10-01-react-only-baseline.md) — the dual baseline to read before non-trivial changes.
2. [Current project status](../dev/project-status.md) — what is green, what is red, and which numbers were actually measured.
3. [Integration view of every design and plan](../3.9升级优化文档.md) — where the pieces line up and where they conflict.
4. [2026-10-02 design-draft audit](../dev/design-audit-2026-10-02.md) — evidence-grade corrections to the 2026-10-02 optimization/ablation drafts; read before executing them.
5. [Audited optimization execution plan](plans/2026-10-02-audited-optimization-execution.md) — 18 hard constraints, W0–W7 scope and acceptance gates. **W0–W4 complete** (incl. runtime release switch, additive `/auth/me` capability field, and the visible-copy guard at zero files), **W6 harness has been run locally against PostgreSQL** (2026-10-05, synthetic 200k rows; the 49% ratio swing means **no performance conclusion**, and it is not wired into CI — see [W6 A/B harness](baseline/2026-10-05-w6-ab-harness.md)); **W5 offline contracts and local policy have landed (no outbound calls; see `apps/worker/src/soymutdb_worker/wecom/README.md` for the unconfirmed list), W7 not started**. Progress table in §3.9; per-stage evidence and a consolidated current state in the [2026-10-02 rebaseline](baseline/2026-10-02-w0-rebaseline.md) §8–§9.
6. [New-conversation execution prompt](../dev/execute-audited-optimization-prompt.md) — complete and compact handoff instructions for starting implementation.

## Baselines

- **[CURRENT]** [SoyMutDB baseline 2026-10-01, after the React-only consolidation](baseline/2026-10-01-react-only-baseline.md)
  — product/requirement baseline with executable acceptance criteria, architecture/runtime boundary baseline,
  measured gate values, a §5-format check report, and a §6 seven-dimension review.
- **[HISTORICAL]** [SoyMutDB initial dual-baseline snapshot](baseline/2026-09-28-initial-baseline.md)
  — kept as evidence; superseded by the current baseline above.

## Approved designs

| Design | Area | Status |
| --- | --- | --- |
| [Public web layout alignment](../superpowers/specs/2026-08-14-public-web-layout-alignment-design.md) | 门户信息架构、搜索工具页、结果列顺序 | Approved (2026-09-29 修订) |
| [Data publishing and search IA](../superpowers/specs/2026-08-13-data-publishing-and-search-ia-design.md) | 导入状态机、发布/回滚、搜索契约 | Approved 2026-08-13 |
| [Baseline development design](../superpowers/specs/2026-09-14-soymutdb-baseline-development-design.md) | 产品与架构基线、身份/双站契约 | frozen 2026-09-14 |
| [React + Ant Design Pro v6 replatform](../superpowers/specs/2026-09-27-react-pro-v6-replatform-design.md) | 前端统一到 React 19 + Umi Max + antd 6 + ProComponents v3 | 已落地（2026-10-18 复核：ProTable/ProDescriptions/ProCard 在用，裸 `Table` 0；见 `apps/admin/src/regression/pro-table-migration.test.ts`） |
| [Portal UI localization and layout remediation](../superpowers/specs/2026-09-28-portal-ui-quality-remediation-design.md) | 门户 UI 整改与可见文案守卫 | Approved |
| [Admin-editable footer, search workflow, typography](../superpowers/specs/2026-09-28-admin-editable-footer-search-font-design.md) | 页脚可编辑、搜索控件、字体门禁 | 范围与默认值已批准 |
| [Admin Pro v6 migration (official sub-page pattern)](../superpowers/specs/2026-10-01-admin-pro-migration-design.md) | 管理后台对齐官方 `ant-design-pro` sub-page 实例 | A1–A5 已落地；A6 性能对照未验证（2026-10-18 复核） |
| [Multispecies portal design](../superpowers/specs/2026-07-12-multispecies-portal-design-spec.md) | 多物种门户 IA | 无状态字段 |
| [Ontology PostgreSQL control plane](../superpowers/specs/2026-07-15-ontology-postgresql-control-plane-design.md) | 本体控制平面 | 待实施计划审核 |
| [Vue genome view design](../superpowers/specs/2026-09-26-vue-genome-view-design.md) | — | **整份作废**，仅作历史审计；其前端描述与现状相反 |

## Design proposals awaiting approval

| Plan | Scope | Status |
| --- | --- | --- |
| [Caoslab × SoyMutDB visual-system and architecture plan](../design/caoslab-visual-architecture-plan-2026-10-09.md) | Research-informed visuals, asset provenance, admin smoke, Windows deployment, code audit cleanup | **PROPOSED / DOCUMENTATION_ONLY**; no assets or implementation |
| [PI / Subagent execution prompt](../agents/caoslab-visual-agent-prompt.md) | Scoped subagent contracts and evidence-driven exit gates | **PROPOSED / DOCUMENTATION_ONLY** |

## Unregistered working drafts (not authority)

The 2026-10-02 optimization / ablation design drafts (total design, functional ablation, database, auth + WeCom, UI audit)
live under `.validation/docopt-2026-10-02/`, which is excluded by `.gitignore`.
They are retained as historical evidence only. Their conclusions are superseded by
[the corrected audit](../dev/design-audit-2026-10-02.md) and the
[execution plan](plans/2026-10-02-audited-optimization-execution.md); do not execute the old drafts as written.

## Plans

| Plan | Slice | Status |
| --- | --- | --- |
| [P0 public mutant discovery](plans/2026-08-31-mutant-discovery-p0.md) | Task 1–3 | 无完成自述 |
| [Administrator news recycle bin and permanent purge](plans/2026-08-31-news-recycle-bin-purge.md) | Task 1–5 | 已交付 |
| [News revisions and Beijing-time scheduling](plans/2026-08-31-news-revisions-scheduling.md) | Task 1–6 | 仅 Task 1 的 schema 子集落地 |
| [React + Ant Design Pro v6 replatform](plans/2026-09-27-react-pro-v6-replatform.md) | W1–W4 | 栈迁移完成，Pro 组件体系已落地（裸 `Table` 0；`apps/admin/src/components/data-table.tsx:2` 用 `ProTable`；`apps/admin/src/regression/pro-table-migration.test.ts` 守门） |
| [Public portal UI quality remediation](plans/2026-09-28-portal-ui-quality-remediation.md) | Task 1–5 | 部分完成；**可见文案守卫已于 2026-10-02 清零（exit 0 / 0 文件）** |
| [Admin-editable footer, search, typography](plans/2026-09-28-admin-editable-footer-search-font.md) | Task 0–5 | Task 1 部分完成，Task 2–5 未开始 |
| [Admin Pro v6 migration (official sub-page pattern)](plans/2026-10-01-admin-pro-migration.md) | A1–A6 | A1–A5 已实施；A6 性能对照未验证。2026-10-18 复核：裸 `Table` 0、`ProDescriptions`/`ProCard` 在用、251 个 i18n 键已补齐（`apps/admin/src/components/data-table.tsx:2`、`apps/admin/src/regression/pro-table-migration.test.ts`、[Admin 外壳验收](../dev/admin-console-overhaul-20261010.md)） |
| [DIAMOND / Biopython / pyDEG / Rust 审计与实施](plans/2026-10-05-blast-diamond-and-enrichment-rust.md) | 比对链路、数值核与分析库接入 | DIAMOND `blastp` 单一引擎；Python 核优化与缓存/同源缺陷修复保留。2026-10-08 纠正“无导入实现”：退役重复 worker 写入器，收敛到既有 API draft-only/不可变快照链，补 dry-run、字节摘要及幂等行数校验。切片 60 通过；根门禁结果见计划。profiler 明确 database replay、校正 annotated-input `n` 并断言 calculation parity。fixture 中位数不能推翻 p95 门槛，Rust ≥20% 完整路径验收保留。真实上游文件及 Rust/pyDEG 生产接入仍缺 |
| [Audited global optimization](plans/2026-10-02-audited-optimization-execution.md) | H-01–H-18 / W0–W7 | **W0–W4 已完成**（运行时 release 切换、`/auth/me.effective_roles`、可见文案守卫 0 文件、真实浏览器 10/10）；W6 框架就位、本机实跑 exit 0（但比值 49% 波动，**无性能结论**）；W5 离线合同与本地策略已落地（**无出站调用**，未确认清单见 wecom/README.md）；W7 未开始（受阻于部署目标确认） |

## Work records

- [Portal quality and feature improvements](work/2026-09-28-portal-quality-improvements/) — intent, checkpoint, evidence, reflection, and the Aegis method-pack artifacts (`*-draft.json`, `gate-input-pack.json`, `proof-bundle.md`).
- [SoyMutDB optimization](work/2026-08-31-soymutdb-optimization/) — news lifecycle, desktop spike readiness, mutant core roadmap.

## Record log

| Date | Kind | Record | Note |
| --- | --- | --- | --- |
| 2026-08-31 | work | `docs/aegis/work/2026-08-31-soymutdb-optimization/*` | News lifecycle designs and mutant roadmap |
| 2026-09-27 | plan | `docs/aegis/plans/2026-09-27-react-pro-v6-replatform.md` | React + Pro v6 execution plan |
| 2026-09-28 | work | `docs/aegis/work/2026-09-28-portal-quality-improvements/*` | Portal quality intent, checkpoint, evidence, reflection |
| 2026-09-28 | artifact | `…/task-intent-draft.json`, `baseline-read-set-hint.json`, `baseline-usage-draft.json` | Aegis method-pack drafts |
| 2026-09-28 | artifact | `…/impact-statement-draft.json`, `todo-checkpoint-draft.json`, `drift-check-draft.json` | Aegis method-pack drafts |
| 2026-09-28 | plan | `docs/aegis/plans/2026-09-28-admin-editable-footer-search-font.md` | Admin footer, public search, typography |
| 2026-09-29 | artifact | `…/resume-state-hint.json`, `gate-input-pack.json`, `proof-bundle.md` | Resume state, gate inputs, proof bundle |
| 2026-10-01 | baseline | `docs/aegis/baseline/2026-10-01-react-only-baseline.md` | Current dual baseline; supersedes the 2026-09-28 snapshot |
| 2026-10-01 | plan | `docs/aegis/plans/2026-10-01-admin-pro-migration.md` | Admin migration to the official sub-page pattern |
| 2026-10-01 | work | `.ai-memory/20261001/daily.md` | Contract realignment, admin migration docs, three new guards |
| 2026-10-02 | audit | `docs/dev/design-audit-2026-10-02.md` | 10 findings on the 2026-10-02 design drafts; D-01/D-08/D-10 withdraw prior claims (CI wiring, 100x speedup, 9/9 ablation) |
| 2026-10-02 | fix | `AGENTS.md` | pnpm pin 11.21.0 -> 12.5.1 to match `package.json` / `.cnb.yml` |
| 2026-10-06 | fix | `plans/2026-10-05-blast-diamond-and-enrichment-rust.md` | 比对链路收敛为 DIAMOND `blastp` 单一引擎；A 段路由表、回滚方式与重跑命令同步更新 |
| 2026-10-18 | doc | `docs/dev/optimization-master-plan.md`、`docs/dev/project-status.md`、`.ai-memory/handoff.md`、`docs/dev/{native-postgres-cutover,a04-search-keyset-continuation,README}.md`、`docs/aegis/INDEX.md` | 状态对账：按当前代码/CI 证据更新已实现的 A-09/A-13/A-17/A-19 等状态；历史“已知红灯”逐行标注关闭证据；W6 改为“已本机跑过、无性能结论、未入 CI” |
