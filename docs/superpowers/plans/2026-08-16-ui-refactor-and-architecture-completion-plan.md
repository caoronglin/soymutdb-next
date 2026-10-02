# UI 重构与整体架构完成计划

> **已归档（2026-10-01）**：已被现行计划取代的历史实施计划。继任：`docs/aegis/plans/` 与 `docs/aegis/INDEX.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

> 日期：2026-08-16
> 状态：方案（回答：UI 设计重构好了吗？整体架构设计完成了吗？）
> 依据：
> - `docs/superpowers/specs/2026-08-14-public-web-layout-alignment-design.md`
> - `docs/superpowers/plans/2026-08-14-phase-2/3/4-*.md`
> - `docs/design/full-stack-upgrade-2026-08.md`
> - `docs/design/multispecies-portal-product-architecture-design.md`

---

## 1. 两个问题的直接回答

| 问题 | 结论 | 证据 |
|---|---|---|
| 整体架构设计完成了吗 | **设计层已完成，实现层未完成** | 架构/规格/四阶段计划文档齐备；但 Phase 2/3/4 的代码与迁移尚未创建 |
| UI 设计重构好了吗 | **未完成** | 设计稿与规格已批准，但公共 Web 仍是 PPTX V2 布局（HomeHero/HomeStatsBar、旧导航、旧搜索表单/列序、GBrowse 术语） |

---

## 2. 整体架构完成度矩阵

### 2.1 设计文档（✅ 已完成）

- 顶层目标与边界：`full-stack-upgrade-2026-08.md`（批准基线）
- 产品/信息架构/路线：`multispecies-portal-product-architecture-design.md`
- 公共 Web 七页布局：`2026-08-14-public-web-layout-alignment-design.md`（批准）
- 数据发布/搜索 IA：`2026-08-13-data-publishing-and-search-ia-design.md`
- 分阶段实施计划：Phase 1–4 四份 plan 文档

### 2.2 实现完成度（截至 2026-08-16）

| 层 | 设计 | 实现 | 缺口 |
|---|---|---|---|
| 数据发布状态机（Release/Import） | ✅ | ✅ 基本完成 | DB 集成测试、真实发布验证 |
| Outbox / 任务契约 | ✅ | ✅ 已修复 | 需要真实 broker 验证 |
| Module TSV 导入 | ✅ | ⚠️ 主体完成 | migration 未在真实 PG 验证；服务/worker 集成测试 |
| Admin 页面构建器 | ✅ | ❌ 未开始 | `page_builder` 模型/registry/API/编辑器全部缺失 |
| 不可变多目标静态发布 | ✅ | ❌ 未开始 | publication 模型、manifest、三 adapter、release-aware snapshot 缺失 |
| 公共 Web 布局渲染器 | ✅ | ❌ 未开始 | `apps/web/src/page-builder/` 不存在；首页/搜索/BLAST/导航未改 |
| 无 Docker 部署 | ✅ | ⚠️ 工具已补 | conda env/data-init/services 脚本已建，未真实服务器验证 |

---

## 3. UI 设计重构现状（逐项核对）

批准规格要求 vs 当前代码：

| 规格要求 | 当前代码 | 状态 |
|---|---|---|
| 首页：新闻 2:3 网格 + 3–6 图轮播 + 5 个任务入口 + CMS 内容 | 仍是 `HomeHero` + `HomeStatsBar` + 旧轮播/双栏 | ❌ |
| 导航顺序：Home / Search / Tools / Latest News / Contact | Home / Search / Tools / Contact(`/help`) / News | ❌ |
| Gene ID：URL 参数 `q/assembly/run`，submit 新 tab，列序 Assembly→Chromosome→Position→Mutation→Gene→JBrowse 2 | 仅 `?q=`；同 tab；列序 Gene 开头，GBrowse 术语 | ❌ |
| Location：URL 参数 `assembly/chromosome/start/end/run`，新 tab | 无 URL 恢复；同 tab | ❌ |
| BLAST：入口直达 `/blast` 完整表单 | `/search/blast` 是中间卡片 | ❌ |
| 全站 `JBrowse 2` 术语 | 大量 `Gbrowse/GBrowse` 文案与 action | ❌ |
| PageDefinition 驱动 + 静态 fallback | 无 bootstrap/hydration | ❌ |
| 响应式/无障碍验证 | 无新 Playwright 覆盖 | ❌ |

**结论：UI 设计重构处于 0% 实现状态，需按 Phase 4 执行。**

---

## 4. 执行方案

### 4.1 推荐顺序（UI 与架构可以并行，但要有契约先行）

```text
A. UI 布局先行（Phase 4 的静态渲染部分）
   ├─ 不改后端，先按批准规格重构首页/导航/搜索/BLAST/JBrowse 术语
   ├─ 用 seed JSON 代替 PageDefinition（临时 bootstrap）
   └─ 后端 PageBuilder 就绪后再切换到真实 definition

B. 后端构建器与发布链（Phase 2 → Phase 3）
   ├─ PageDefinition + 安全组件 registry + Admin API
   ├─ 不可变制品 + manifest + 三 adapter
   └─ release-aware snapshot 与 release 绑定

C. 汇合（Phase 4 后半 + Phase 5）
   ├─ 公共渲染器消费 PageDefinition
   ├─ SSG bootstrap release 固定
   └─ 端到端验收/回滚演练
```

### 4.2 UI 重构任务（Phase 4，建议先做）

- [ ] `apps/web/src/page-builder/registry.tsx`：穷举 `COMPONENT_RENDERERS`，未知 key 开发态报错、生产构建前拒绝
- [ ] 导航重构：`site-header.tsx` 移除硬编码 `NAV_ITEMS`；顺序 Home/Search/Tools/Latest News/Contact；保留不可变 fallback
- [ ] 首页重构：删除 `HomeHero`/`HomeStatsBar` 渲染；实现 `lg:grid-cols-[2fr_3fr]` 新闻+轮播、5 工具入口（Gene ID / Physical Location / JBrowse 2 / BLAST / Primer Design）、CMS 内容
- [ ] Gene ID 搜索：route search 增加 `q/assembly/run`；URL 恢复并只执行一次；submit 用 `window.open(..., "_blank", "noopener")`；列序改为 Assembly→Chromosome→Position→Mutation→Gene ID→JBrowse 2
- [ ] Location 搜索：route search 增加 `assembly/chromosome/start/end/run`；校验 `start>=1`、`end>=start`；同六列序与 JBrowse 2 action
- [ ] BLAST 入口：默认/工具入口改 `/blast`；`/search/blast` 兼容重定向；结果列与 Gene/JBrowse 2 交叉链接
- [ ] 全站术语：`Gbrowse/GBrowse` → `JBrowse 2`（含 i18n、注释、按钮、aria-label）
- [ ] 响应式/无障碍：1440/900/390 三档；焦点可见、键盘可操作、表格横向滚动、无页面横向溢出
- [ ] 验收：`pnpm --filter @soymutdb/web test -- --run`、`typecheck`、`lint`、`build`；新增/更新 Playwright homepage/search/genes/accessibility

### 4.3 架构补齐任务（Phase 2 + Phase 3）

**Phase 2：Admin 页面构建器**
- [ ] 模型 + 迁移 `0016_page_builder.py`
- [ ] 服务端组件 registry（16 类安全组件，拒绝 JS/任意 HTML/模板）
- [ ] Admin API：draft / preview / version / publish-request
- [ ] 共享 DTO `packages/shared/src/page-builder.ts`
- [ ] Admin 三栏编辑器 + TSV 上传控件
- [ ] seed 五导航 + 七页定义

**Phase 3：不可变多目标静态发布**
- [ ] 模型 + 迁移 `0017_static_publications.py`
- [ ] release-aware snapshot / cache key
- [ ] fresh-tree SSG + `manifest.json` + `validate-static-tree.ts`
- [ ] 统一转义/URL 白名单（`ssg-content.ts`）
- [ ] target lease + stale-job 防护
- [ ] local / GitHub Pages / Cloudflare Pages adapter
- [ ] `X-SoyMutDB-Release` release 绑定
- [ ] smoke / rollback 测试

### 4.4 汇合与验收（Phase 5）

- [ ] 上传非法 TSV → 零泄漏
- [ ] 上传合法 `genes` TSV → import ready → publish-request → 构建 → 校验 → 发布 → smoke
- [ ] 同 target 并发发布 stale-job 防护
- [ ] 三目标 manifest 等价
- [ ] 回滚演练
- [ ] 契约收敛 + 文档更新

---

## 5. 工期与里程碑建议

| 里程碑 | 内容 | 预计 |
|---|---|---|
| M1 | UI 布局先行（不改后端）：首页/导航/搜索/BLAST/术语/响应式 | 3–4 天 |
| M2 | PageBuilder 后端 + Admin 编辑器 | 3–4 天 |
| M3 | 静态发布链 + 三 adapter | 4–5 天 |
| M4 | 渲染器接入真实 definition + release 绑定 | 2–3 天 |
| M5 | 端到端验收/回滚/文档 | 2–3 天 |

---

## 6. 风险

- UI 先行如果使用临时 seed JSON，需要保证后续切换真实 PageDefinition 时**不引入第二种渲染路径**；临时 seed 必须与 DTO 同构。
- 现有 `apps/web` typecheck 存在历史错误（blast/genes/search API 类型漂移），UI 重构前需先隔离基线，避免把历史失败混入本次验收。
- Phase 3 的 GitHub Pages workflow 当前有未提交的 demo 改动，必须与发布 adapter 的 workflow 决策合并，防止双轨。
