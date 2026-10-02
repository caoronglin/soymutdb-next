# Aegis Records Index

Registry for durable Aegis records. Governance: [BASELINE-GOVERNANCE.md](BASELINE-GOVERNANCE.md).
Register new records here rather than duplicating them, and mark superseded records instead of deleting them.
Repository-wide document entry point: [docs/README.md](../README.md); superseded documents: [docs/ARCHIVE.md](../ARCHIVE.md).

## Start here

1. [Current baseline (2026-10-01)](baseline/2026-10-01-react-only-baseline.md) — the dual baseline to read before non-trivial changes.
2. [Current project status](../dev/project-status.md) — what is green, what is red, and which numbers were actually measured.
3. [Integration view of every design and plan](../3.9升级优化文档.md) — where the pieces line up and where they conflict.

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

## Plans

| Plan | Slice | Status |
| --- | --- | --- |
| [P0 public mutant discovery](plans/2026-08-31-mutant-discovery-p0.md) | Task 1–3 | 无完成自述 |
| [Administrator news recycle bin and permanent purge](plans/2026-08-31-news-recycle-bin-purge.md) | Task 1–5 | 已交付 |
| [News revisions and Beijing-time scheduling](plans/2026-08-31-news-revisions-scheduling.md) | Task 1–6 | 仅 Task 1 的 schema 子集落地 |
| [React + Ant Design Pro v6 replatform](plans/2026-09-27-react-pro-v6-replatform.md) | W1–W4 | 栈迁移完成，Pro 组件体系未落地 |
| [Public portal UI quality remediation](plans/2026-09-28-portal-ui-quality-remediation.md) | Task 1–5 | 部分完成；可见文案守卫仍为红 |
| [Admin-editable footer, search, typography](plans/2026-09-28-admin-editable-footer-search-font.md) | Task 0–5 | Task 1 部分完成，Task 2–5 未开始 |
| [Admin Pro v6 migration (official sub-page pattern)](plans/2026-10-01-admin-pro-migration.md) | A1–A6 | 待执行；A5 可并行 |

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