# 归档文档登记表

- 归档日期：`2026-10-01`（共 **138** 份）
- 2026-10-02 补登：`.validation/docopt-2026-10-02/` 下的 2026-10-02 优化/消融设计草稿（总设计、功能消融、升级发现、数据库、认证与企业微信、UI 审计）**不进入本登记表**——它们位于 `.gitignore` 排除的目录，从未作为仓库文档发布，且已被独立审计降级。审计结论：[`dev/design-audit-2026-10-02.md`](dev/design-audit-2026-10-02.md)。
- 现行文档入口：[`README.md`](README.md)
- 判定依据：每份文档自己的状态声明、现行文档/基线/索引的引用图、以及 `scripts/` 等门禁是否引用它
- **归档 ≠ 删除**：原文保留，每份顶部加了归档横幅并指向继任者。删除会切断审计链，
  而本项目多条契约要求变更可见且有继任者。

## 归档准则

满足以下任一条即归档：

1. **已被取代**：主题被现行 spec / 基线 / 状态视图覆盖；
2. **描述的框架已退役**：如 Vue 迁移期文档，而 Vue 已完全退役；
3. **过程记录**：逐轮战役日志、验收战役记录、智能体执行日志与提示词草稿——结论已进入现状视图，
   且 `docs/aegis/README.md` 明确要求工作区不存放日志；
4. **无人引用且无操作价值**：不被 README、基线、索引或任何 `scripts/` 门禁引用。

不归档的三类：ADR（决策不随时间失效）、运维手册（`ops/` 下描述现行操作）、用户与 Wiki 指南。


## 分组清单

### 2026-08 设计波次与旧基线快照

继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md；门户布局以 `docs/superpowers/specs/2026-08-14-public-web-layout-alignment-design.md` 为准

共 14 份：

- [`ci-cd-baseline.md`](ci-cd-baseline.md)
- [`2026-09-28-initial-baseline.md`](aegis/baseline/2026-09-28-initial-baseline.md)
- [`audit-remediation-plan-2026-08-19.md`](design/audit-remediation-plan-2026-08-19.md)
- [`consolidation-admin-governance-security-2026-09.md`](design/consolidation-admin-governance-security-2026-09.md)
- [`desktop-toolbox-spike-boundary.md`](design/desktop-toolbox-spike-boundary.md)
- [`full-stack-upgrade-2026-08.md`](design/full-stack-upgrade-2026-08.md)
- [`full-stack-upgrade-plan-2026-08.md`](design/full-stack-upgrade-plan-2026-08.md)
- [`multispecies-portal-product-architecture-design.md`](design/multispecies-portal-product-architecture-design.md)
- [`requirements-2026-08.md`](design/requirements-2026-08.md)
- [`seo-geo-wave0-implementation-design.md`](design/seo-geo-wave0-implementation-design.md)
- [`static-content-richtext-2026-08.md`](design/static-content-richtext-2026-08.md)
- [`ui-simplify-2026-08.md`](design/ui-simplify-2026-08.md)
- [`upgrade-2026-08.md`](design/upgrade-2026-08.md)
- [`upgrade-plan.md`](design/upgrade-plan.md)

### 智能体执行日志与提示词草稿（治理要求工作区不存放日志）

继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §7 变更记录；执行结论见 docs/dev/project-status.md

共 25 份：

- [`THREAD.md`](agent-state/THREAD.md)
- [`a0-assertion-triage.md`](agent-state/a0-assertion-triage.md)
- [`a0-debt-cleanup.md`](agent-state/a0-debt-cleanup.md)
- [`a0-fix-summary.md`](agent-state/a0-fix-summary.md)
- [`execution-acceptance.md`](agent-state/execution-acceptance.md)
- [`execution-baseline-web-typecheck.md`](agent-state/execution-baseline-web-typecheck.md)
- [`execution-baseline.md`](agent-state/execution-baseline.md)
- [`import-hardening-verification.md`](agent-state/import-hardening-verification.md)
- [`multiformat-import-verification.md`](agent-state/multiformat-import-verification.md)
- [`pi-agent-refactor-prompt-2026-09-23.md`](dev/pi-agent-refactor-prompt-2026-09-23.md)
- [`pi-next-prompt-paste-2026-09-10.md`](dev/pi-next-prompt-paste-2026-09-10.md)
- [`pi-next-tasks-2026-09-10.md`](dev/pi-next-tasks-2026-09-10.md)
- [`pi-website-deployment-handoff.md`](dev/pi-website-deployment-handoff.md)
- [`README.md`](dev/pi-overall-2026-09-08/README.md)
- [`execution-status.md`](dev/pi-overall-2026-09-08/execution-status.md)
- [`plan.md`](dev/pi-overall-2026-09-08/plan.md)
- [`prompt.md`](dev/pi-overall-2026-09-08/prompt.md)
- [`research-refresh.md`](dev/pi-overall-2026-09-08/research-refresh.md)
- [`sources.md`](dev/pi-overall-2026-09-08/sources.md)
- [`start.md`](dev/pi-overall-2026-09-08/start.md)
- [`system.md`](dev/pi-overall-2026-09-08/system.md)
- [`verification.md`](dev/pi-overall-2026-09-08/verification.md)
- [`w1-w3-repair.md`](dev/pi-overall-2026-09-08/w1-w3-repair.md)
- [`execute-multispecies-portal-update.md`](superpowers/prompts/execute-multispecies-portal-update.md)
- [`plan-multispecies-portal-iteration.md`](superpowers/prompts/plan-multispecies-portal-iteration.md)

### 一次性任务笔记与旧状态视图（结论已进入现状视图与计划）

继任：docs/dev/project-status.md；任务级进度见 `docs/aegis/plans/`

共 14 份：

- [`a04-search-keyset-continuation.md`](dev/a04-search-keyset-continuation.md)
- [`a09-import-studio-resume-flow.md`](dev/a09-import-studio-resume-flow.md)
- [`a10-static-page-migration-apply-governance.md`](dev/a10-static-page-migration-apply-governance.md)
- [`a15-retry-boundary.md`](dev/a15-retry-boundary.md)
- [`a17-user-lookup-audit.md`](dev/a17-user-lookup-audit.md)
- [`admin-architecture.md`](dev/admin-architecture.md)
- [`content-template-plan.md`](dev/content-template-plan.md)
- [`database-execution-status.md`](dev/database-execution-status.md)
- [`deployment-status.md`](dev/deployment-status.md)
- [`desktop-client-plan.md`](dev/desktop-client-plan.md)
- [`enrichment-annotation-import.md`](dev/enrichment-annotation-import.md)
- [`minimal-search-validation.md`](dev/minimal-search-validation.md)
- [`rust-rewrite-and-architecture-evaluation.md`](dev/rust-rewrite-and-architecture-evaluation.md)
- [`s1-cross-site-auth-spike.md`](dev/s1-cross-site-auth-spike.md)

### 优化 / 消融战役的逐轮记录（结论已并入现状与基线）

继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫

共 37 份：

- [`genome-browser-ablation-report.md`](dev/genome-browser-ablation-report.md)
- [`genome-view-visual-parity.md`](dev/genome-view-visual-parity.md)
- [`optimization-master-plan.md`](dev/optimization-master-plan.md)
- [`optimization-plan.md`](dev/optimization-plan.md)
- [`performance-optimization-plan.md`](dev/performance-optimization-plan.md)
- [`pi-agent-ablation-audit-execution-2026-09-26.md`](dev/pi-agent-ablation-audit-execution-2026-09-26.md)
- [`platform-optimization-plan.md`](dev/platform-optimization-plan.md)
- [`OPTIMIZATION-CHECKLIST.md`](dev/ablation/2026-09-26/OPTIMIZATION-CHECKLIST.md)
- [`OPTIMIZATION-REPORT.md`](dev/ablation/2026-09-26/OPTIMIZATION-REPORT.md)
- [`PLAN.md`](dev/ablation/2026-09-26/PLAN.md)
- [`README.md`](dev/ablation/2026-09-26/README.md)
- [`artifact-e2e.md`](dev/ablation/2026-09-26/artifact-e2e.md)
- [`assembly.md`](dev/ablation/2026-09-26/assembly.md)
- [`cache-site.md`](dev/ablation/2026-09-26/cache-site.md)
- [`frontend.md`](dev/ablation/2026-09-26/frontend.md)
- [`identity.md`](dev/ablation/2026-09-26/identity.md)
- [`opt-a-crossversion.md`](dev/ablation/2026-09-26/opt-a-crossversion.md)
- [`opt-b-federated-cache.md`](dev/ablation/2026-09-26/opt-b-federated-cache.md)
- [`opt-c-internal-ui.md`](dev/ablation/2026-09-26/opt-c-internal-ui.md)
- [`opt-d-artifact-guards.md`](dev/ablation/2026-09-26/opt-d-artifact-guards.md)
- [`opt-e-e2e.md`](dev/ablation/2026-09-26/opt-e-e2e.md)
- [`pipeline.md`](dev/ablation/2026-09-26/pipeline.md)
- [`OPT2-CHECKLIST.md`](dev/opt2/OPT2-CHECKLIST.md)
- [`OPT2-REPORT.md`](dev/opt2/OPT2-REPORT.md)
- [`opt2-a-api-search.md`](dev/opt2/opt2-a-api-search.md)
- [`opt2-b-e2e.md`](dev/opt2/opt2-b-e2e.md)
- [`opt2-c-regression-suite.md`](dev/opt2/opt2-c-regression-suite.md)
- [`opt2-d-service-worker.md`](dev/opt2/opt2-d-service-worker.md)
- [`opt2-e-researcher-gate.md`](dev/opt2/opt2-e-researcher-gate.md)
- [`OPT3-REPORT.md`](dev/opt3/OPT3-REPORT.md)
- [`opt3-m-route-motion.md`](dev/opt3/opt3-m-route-motion.md)
- [`opt3-n-notifications.md`](dev/opt3/opt3-n-notifications.md)
- [`OPT4-REPORT.md`](dev/opt4/OPT4-REPORT.md)
- [`opt4-site-content.md`](dev/opt4/opt4-site-content.md)
- [`OPT5-REPORT.md`](dev/opt5/OPT5-REPORT.md)
- [`opt5-a-pages.md`](dev/opt5/opt5-a-pages.md)
- [`opt5-b-help-search.md`](dev/opt5/opt5-b-help-search.md)

### Vue / React 迁移期文档（Vue 已退役，React 为唯一生产路径）

继任：docs/dev/project-status.md

共 9 份：

- [`antd-migration-guide.md`](dev/antd-migration-guide.md)
- [`react-migration-progress-2026-09-27.md`](dev/react-migration-progress-2026-09-27.md)
- [`vue-migration-feature-gaps.md`](dev/vue-migration-feature-gaps.md)
- [`vue-migration-recovery-plan.md`](dev/vue-migration-recovery-plan.md)
- [`vue-migration-recovery-status.md`](dev/vue-migration-recovery-status.md)
- [`webui-removal-spec.md`](dev/webui-removal-spec.md)
- [`README.md`](dev/vue-parity/README.md)
- [`functional-gap-audit.md`](dev/vue-parity/functional-gap-audit.md)
- [`2026-09-26-vue-genome-view-design.md`](superpowers/specs/2026-09-26-vue-genome-view-design.md)

### 一次性的基础模式验收战役记录（操作手册仍在 ops/）

继任：`docs/ops/README.md` 及其下的现行运维手册；部署事实见 `docs/dev/project-status.md`

共 13 份：

- [`baseline-acceptance-matrix.md`](ops/baseline-acceptance-matrix.md)
- [`baseline-change-boundary.md`](ops/baseline-change-boundary.md)
- [`baseline-defect-ledger.md`](ops/baseline-defect-ledger.md)
- [`baseline-mode-no-docker-cicd-plan.md`](ops/baseline-mode-no-docker-cicd-plan.md)
- [`gate-a-decision-brief-2026-09-20.md`](ops/gate-a-decision-brief-2026-09-20.md)
- [`phase-0-fact-baseline-2026-09-20.md`](ops/phase-0-fact-baseline-2026-09-20.md)
- [`pptx-layout-acceptance-checklist.md`](ops/pptx-layout-acceptance-checklist.md)
- [`pptx-layout-spec.md`](ops/pptx-layout-spec.md)
- [`antd6-final-smoke-20260825.md`](ops/evidence/antd6-final-smoke-20260825.md)
- [`visual-layout-final-20260825T005920Z.md`](ops/evidence/visual-layout-final-20260825T005920Z.md)
- [`visual-layout-final-20260825T011833Z.md`](ops/evidence/visual-layout-final-20260825T011833Z.md)
- [`visual-layout-t49-20260824T150817Z.md`](ops/evidence/visual-layout-t49-20260824T150817Z.md)
- [`README.md`](ops/evidence/route-b/README.md)

### 早期调研笔记（结论已进入基线与设计）

继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §1.1 需求来源

共 3 份：

- [`2026-07-19-technology-stack-and-comparable-projects-research.md`](research/2026-07-19-technology-stack-and-comparable-projects-research.md)
- [`2026-08-17-system-gap-and-expansion-audit.md`](research/2026-08-17-system-gap-and-expansion-audit.md)
- [`2026-08-19-ui-seo-geo-completion-audit.md`](research/2026-08-19-ui-seo-geo-completion-audit.md)

### 已被现行计划取代的历史实施计划

继任：`docs/aegis/plans/` 与 `docs/aegis/INDEX.md`

共 23 份：

- [`2026-07-11-multispecies-static-portal-roadmap.md`](superpowers/plans/2026-07-11-multispecies-static-portal-roadmap.md)
- [`2026-07-19-a0-factual-reconciliation-implementation-plan.md`](superpowers/plans/2026-07-19-a0-factual-reconciliation-implementation-plan.md)
- [`2026-07-19-a1-control-plane-safety-implementation-plan.md`](superpowers/plans/2026-07-19-a1-control-plane-safety-implementation-plan.md)
- [`2026-07-19-b-dual-species-ontology-data-implementation-plan.md`](superpowers/plans/2026-07-19-b-dual-species-ontology-data-implementation-plan.md)
- [`2026-07-19-c-deterministic-publication-implementation-plan.md`](superpowers/plans/2026-07-19-c-deterministic-publication-implementation-plan.md)
- [`2026-07-19-d-isolated-dual-search-implementation-plan.md`](superpowers/plans/2026-07-19-d-isolated-dual-search-implementation-plan.md)
- [`2026-07-19-e-scientific-public-admin-ux-implementation-plan.md`](superpowers/plans/2026-07-19-e-scientific-public-admin-ux-implementation-plan.md)
- [`2026-07-19-f-verification-ocr-cleanup-implementation-plan.md`](superpowers/plans/2026-07-19-f-verification-ocr-cleanup-implementation-plan.md)
- [`2026-07-19-ontology-control-plane-master-execution-plan.md`](superpowers/plans/2026-07-19-ontology-control-plane-master-execution-plan.md)
- [`2026-08-13-data-publishing-release-core-plan.md`](superpowers/plans/2026-08-13-data-publishing-release-core-plan.md)
- [`2026-08-13-deployment-cleanup-docs-plan.md`](superpowers/plans/2026-08-13-deployment-cleanup-docs-plan.md)
- [`2026-08-13-search-admin-ui-plan.md`](superpowers/plans/2026-08-13-search-admin-ui-plan.md)
- [`2026-08-14-phase-1-module-tsv-import-foundation.md`](superpowers/plans/2026-08-14-phase-1-module-tsv-import-foundation.md)
- [`2026-08-14-phase-2-admin-page-builder.md`](superpowers/plans/2026-08-14-phase-2-admin-page-builder.md)
- [`2026-08-14-phase-3-static-multitarget-publication.md`](superpowers/plans/2026-08-14-phase-3-static-multitarget-publication.md)
- [`2026-08-14-phase-4-public-web-layout-renderer.md`](superpowers/plans/2026-08-14-phase-4-public-web-layout-renderer.md)
- [`2026-08-16-soymutdb-next-completion-master-plan.md`](superpowers/plans/2026-08-16-soymutdb-next-completion-master-plan.md)
- [`2026-08-16-ui-refactor-and-architecture-completion-plan.md`](superpowers/plans/2026-08-16-ui-refactor-and-architecture-completion-plan.md)
- [`2026-08-17-multiformat-import-production-hardening-plan.md`](superpowers/plans/2026-08-17-multiformat-import-production-hardening-plan.md)
- [`2026-09-20-phase-0-fact-baseline-plan.md`](superpowers/plans/2026-09-20-phase-0-fact-baseline-plan.md)
- [`2026-09-20-phase-1-p0-correctness-plan.md`](superpowers/plans/2026-09-20-phase-1-p0-correctness-plan.md)
- [`2026-09-20-phase-2-import-protocol-plan.md`](superpowers/plans/2026-09-20-phase-2-import-protocol-plan.md)
- [`2026-09-26-vue-genome-view.md`](superpowers/plans/2026-09-26-vue-genome-view.md)

## 撤销归档

若某份归档文档被证明仍是现状依据：删掉它的归档横幅，并把它加回 [`README.md`](README.md) 的入口表。
本表是清单，不是判决；判据是「是否仍被引用、是否仍描述现实」，不是「日期够不够新」。
