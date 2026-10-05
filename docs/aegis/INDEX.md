# Aegis Records Index

Registry for durable Aegis records. Governance: [BASELINE-GOVERNANCE.md](BASELINE-GOVERNANCE.md).
Register new records here rather than duplicating them, and mark superseded records instead of deleting them.
Repository-wide document entry point: [docs/README.md](../README.md); superseded documents: [docs/ARCHIVE.md](../ARCHIVE.md).

## Start here

1. [Current baseline (2026-10-01)](baseline/2026-10-01-react-only-baseline.md) — the dual baseline to read before non-trivial changes.
2. [Current project status](../dev/project-status.md) — what is green, what is red, and which numbers were actually measured.
3. [Integration view of every design and plan](../3.9升级优化文档.md) — where the pieces line up and where they conflict.
4. [2026-10-02 design-draft audit](../dev/design-audit-2026-10-02.md) — evidence-grade corrections to the 2026-10-02 optimization/ablation drafts; read before executing them.
5. [Audited optimization execution plan](plans/2026-10-02-audited-optimization-execution.md) — 18 hard constraints, W0–W7 scope and acceptance gates. **W0–W4 complete** (incl. runtime release switch, additive `/auth/me` capability field, and the visible-copy guard at zero files), **W6 harness ready but never run against a live database**; W5 and W7 not started. Progress table in §3.9; per-stage evidence and a consolidated current state in the [2026-10-02 rebaseline](baseline/2026-10-02-w0-rebaseline.md) §8–§9.
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
| [React + Ant Design Pro v6 replatform](../superpowers/specs/2026-09-27-react-pro-v6-replatform-design.md) | 前端统一到 React 19 + Umi Max + antd 6 + ProComponents v3 | 实施中 |
| [Portal UI localization and layout remediation](../superpowers/specs/2026-09-28-portal-ui-quality-remediation-design.md) | 门户 UI 整改与可见文案守卫 | Approved |
| [Admin-editable footer, search workflow, typography](../superpowers/specs/2026-09-28-admin-editable-footer-search-font-design.md) | 页脚可编辑、搜索控件、字体门禁 | 范围与默认值已批准 |
| [Admin Pro v6 migration (official sub-page pattern)](../superpowers/specs/2026-10-01-admin-pro-migration-design.md) | 管理后台对齐官方 `ant-design-pro` sub-page 实例 | 方向已批准，逐页实施中 |
| [Multispecies portal design](../superpowers/specs/2026-07-12-multispecies-portal-design-spec.md) | 多物种门户 IA | 无状态字段 |
| [Ontology PostgreSQL control plane](../superpowers/specs/2026-07-15-ontology-postgresql-control-plane-design.md) | 本体控制平面 | 待实施计划审核 |
| [Vue genome view design](../superpowers/specs/2026-09-26-vue-genome-view-design.md) | — | **整份作废**，仅作历史审计；其前端描述与现状相反 |

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
| [React + Ant Design Pro v6 replatform](plans/2026-09-27-react-pro-v6-replatform.md) | W1–W4 | 栈迁移完成，Pro 组件体系未落地 |
| [Public portal UI quality remediation](plans/2026-09-28-portal-ui-quality-remediation.md) | Task 1–5 | 部分完成；**可见文案守卫已于 2026-10-02 清零（exit 0 / 0 文件）** |
| [Admin-editable footer, search, typography](plans/2026-09-28-admin-editable-footer-search-font.md) | Task 0–5 | Task 1 部分完成，Task 2–5 未开始 |
| [Admin Pro v6 migration (official sub-page pattern)](plans/2026-10-01-admin-pro-migration.md) | A1–A6 | 待执行；A5 可并行。**实测缺口比计划记的更重**：8 个页面用裸 `Table`（非 6），`ProDescriptions`/`ProCard` 仍 0 处 |
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