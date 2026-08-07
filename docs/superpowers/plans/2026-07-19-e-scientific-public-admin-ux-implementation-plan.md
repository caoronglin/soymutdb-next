# Phase E：Scientific Field Manual 公共端与受治理 Admin UX 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` (or `subagent-driven-development`) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This document is an implementation plan, not an implementation authorization.

**Goal:** 在 A0、A1、B、C、D 均完成并通过各自 Oracle phase review 后，实现 Scientific Field Manual / Research Instrument 方向的公共端与管理端用户体验：公开端让研究者在可复现的物种、组装、数据发布和门户发布上下文中发现、理解、比较、下载和打开 JBrowse；Admin 让具备能力的操作员在真实契约、预览、证据和三条历史约束下完成工作。

**Phase gate:** 本计划只能在 A0 factual reconciliation、A1 control-plane safety、B dual-species/ontology/data、C deterministic publication、D isolated dual-search 均有归档通过证据后执行。E 不补做 A0/A1/B/C/D，不创建新的数据权威、搜索权威、发布协议、权限协议或 arbitrary content runtime。

**Design baseline:** `docs/superpowers/specs/2026-07-15-ontology-postgresql-control-plane-design.md` 已确认 Scientific Field Manual / Research Instrument 方向；视觉方差 3/10、动效 2/10、公共密度 6/10、Admin 密度 8/10。保留 React/Vite/Tailwind/TanStack/Radix/Lucide 和现有 `packages/ui`，不迁移框架或图标库。

**Working rules:**

- 新增第一方业务组件、类型、函数、变量、hook、fixture 和测试 helper 均使用 `rl_` 前缀；React/TanStack/Radix/Lucide、现有公共导出、配置键和测试框架钩子保持原名。
- 非显然的 scope、版本、权限、降级、比较资格、缓存/加载边界和发布证据规则必须写简洁中文 why-comment；注释解释为什么，不复述代码。
- Admin 只消费 A1/C 的 typed capability/command/approval/deployment contract；按钮隐藏不是授权，403 必须在服务端事实和 UI 状态中同时表达。
- 公共端只消费 C 生成并由 D 暴露的已发布 manifest-backed projection；不直连数据库、不读取草稿、不把 Worker 或 JBrowse 当作权限/provenance authority。
- 路由视觉实现必须在执行时交给 designer 按本计划和已接受设计交付；工程实现不得以个人审美覆盖设计 handoff。设计 handoff、差异、截图和 review 结果必须归档到 E evidence，而不是在代码中自行发明另一套视觉语言。

## 1. E 的交付边界、依赖与不变量

### 1.1 依赖确认清单

- [ ] A0 证据包已存在：实际 schema/revision、OpenAPI/client/worker reconciliation、迁移 rehearsal、运行时差异、旧数据映射和 rollback evidence；没有 A0 证据时停止。
- [ ] A1 证据包已存在：capability matrix、typed command、逐能力 allow/deny、提交者/审核者/发布者隔离、重新认证、audit/task outbox 和 break-glass 约束；没有 A1 证据时停止。
- [ ] B 证据包已存在：大豆与第二物种 walking skeleton、scope-aware scientific object、dataset/object version、ontology release-set closure、license/diagnostic gate；没有 B 证据时停止。
- [ ] C 证据包已存在：冻结 revision、`PublicationManifest`、public-projection schema、artifact capability profile、ready marker、Prepare → CAS → Finalize、fencing/compensation/unknown、rollback/reconcile；没有 C 证据时停止。
- [ ] D 证据包已存在：Internal Search 与 External Search 独立 contracts、manifest/hash 校验、signed cursor 或 bounded error、Worker → Internal API → static directory fallback、外部 provenance/error isolation；没有 D 证据时停止。
- [ ] designer handoff 已确认公共与 Admin 的 layout、tokens、responsive states、focus behavior 和截图验收方式；没有 handoff 时只能实现语义结构和测试，不得自行替代视觉设计。

### 1.2 E 只负责的输出

1. `packages/ui` 的共享语义 primitives：scope ledger/context switcher/release badge、ontology term、provenance/citation、external/comparability notice、task/diagnostic/accessibility states，以及面向数据表和移动对象卡片的可访问结构。
2. `apps/web` 的 Discover/Explore/Analyze/Resources consumer UX：D contracts 的搜索隔离、详情、比较、下载、JBrowse release-pinned launch 和所有公开状态。
3. `apps/admin` 的五个工作台：工作台、数据发布、站点内容、发布中心、治理；所有 affordance 以 A1/C capability/approval/deployment evidence 为准。
4. Admin 五步骤导入与 `rl_diagnostic_workspace`，以及发布中心 review-evidence matrix 和三条 history timeline 的呈现。
5. E 范围的 unit/component/Story/E2E/accessibility/visual handoff evidence；失败时只回滚 E 的 UI projection，不修改 A0/A1/B/C/D 的 authority 或历史。

### 1.3 明确排除

- [ ] 不做数据库迁移、API authority、搜索引擎/索引生成、publication saga、artifact provider、权限模型或新的后台队列。
- [ ] 不做 marketing hero、卡片网格堆叠、随机指标、count-up、连续滚动、DNA/gradient spectacle、玻璃面板或装饰性动画。
- [ ] 不执行 React/Vite/Tailwind/TanStack/Radix/Lucide migration，不替换现有 icon system，不引入新 authority layer、graph/search cluster、ontology full-tree/inference UI 或 JBrowse provenance store。
- [ ] 不允许 Admin 执行任意 HTML/CSS/JS/template、任意路径、Shell、secret、数据库连接、presigned URL 或未登记 artifact 输入。
- [ ] 不以 UI 隐藏替代服务端拒绝，不绕过审核、重新认证、四眼职责分离、冷静期、audit 或 deployment approval。

## 2. 非重叠 ownership 与文件边界

每项任务只允许其 owner 修改列出的文件；相邻 owner 通过 exported contract、fixture 或 test seam 交接，不交叉编辑对方目录。

| Task | Owner | 允许修改路径 | 交接结果 |
|---|---|---|---|
| E1 shared semantic UI | shared-ui owner | `packages/ui/src/components/rl-*.tsx`, `packages/ui/src/lib/rl-*.ts`, `packages/ui/src/index.ts`, `packages/ui/src/styles.css` | 可独立渲染、键盘可用、状态语义稳定的 primitives 与 Story fixtures |
| E2 public shell/context | public-shell owner | `apps/web/src/components/rl-*.tsx`, `apps/web/src/lib/rl-*.ts`, `apps/web/src/routes/__root.tsx`, `apps/web/src/components/site-header.tsx`, `apps/web/src/components/site-footer.tsx` | 全局 scope ledger/context、导航和 fallback shell |
| E3 public research consumers | public-research owner | `apps/web/src/routes/search.tsx`, `apps/web/src/routes/genes/**`, `apps/web/src/routes/variants/**`, `apps/web/src/routes/compare.tsx`, `apps/web/src/routes/downloads.tsx`, `apps/web/src/routes/browser.tsx`, `apps/web/src/components/rl-public-*.tsx`, `apps/web/src/lib/rl-public-*.ts` | D contract 驱动的搜索、详情、比较、下载、JBrowse UX |
| E4 admin workspaces | admin-workspace owner | `apps/admin/src/components/rl-*.tsx`, `apps/admin/src/lib/rl-*.ts`, `apps/admin/src/routes/index.tsx`, `apps/admin/src/routes/imports.tsx`, `apps/admin/src/routes/releases.tsx`, `apps/admin/src/routes/content.tsx`, `apps/admin/src/routes/audit.tsx`, `apps/admin/src/routes/__root.tsx`, `apps/admin/src/components/admin-sidebar.tsx` | 五个工作台、truthful affordance、导入诊断、发布证据 |
| E5 tests/evidence | quality owner | `packages/ui/src/**/*.stories.*`, `apps/web/src/**/*.test.*`, `apps/admin/src/**/*.test.*`, `tests/e2e/rl-phase-e-*.spec.ts`, `tests/e2e/accessibility.spec.ts` | TDD、Playwright、a11y、responsive、visual handoff evidence |

若现有文件已经承担相同职责，先在该文件内提取 `rl_` 业务语义；不得为规避 ownership 复制第二套路由、表格、搜索或发布组件。

## 3. E1：共享语义 primitives（先测试，后实现）

### 3.1 目标与路径

在 `packages/ui` 中建立语义层，不把产品页面逻辑塞进 shared primitives。推荐文件：

- `packages/ui/src/components/rl-scientific-context-bar.tsx`
- `packages/ui/src/components/rl-context-switcher.tsx`
- `packages/ui/src/components/rl-release-badge.tsx`
- `packages/ui/src/components/rl-scope-ledger.tsx`
- `packages/ui/src/components/rl-ontology-term.tsx`
- `packages/ui/src/components/rl-provenance-citation-panel.tsx`
- `packages/ui/src/components/rl-external-source-notice.tsx`
- `packages/ui/src/components/rl-comparability-notice.tsx`
- `packages/ui/src/components/rl-state.tsx`
- `packages/ui/src/components/rl-data-surface.tsx`
- `packages/ui/src/lib/rl-semantic-types.ts`
- `packages/ui/src/lib/rl-accessibility.ts`

### 3.2 先写的行为测试

- [ ] `rl_scope_ledger` 对 `global/species/assembly/dataset` 显式标出适用层级；不适用层级显示 `not-applicable`，禁止把缺失值填成当前物种/组装/数据版本。
- [ ] `rl_scientific_context_bar` 按 Species → Assembly → Dataset Release 顺序切换，切换前报告会清除的 filters/compare items；URL 优先于 saved preference；publication release 和 manifest digest 可检查。
- [ ] `rl_release_badge` 同时输出文本、图标和非颜色状态；支持 active/preview/historical/deprecated/hidden/unavailable/stale，不能仅依赖色彩。
- [ ] `rl_ontology_term` 有 `compact/expanded/historical` 三种状态：compact 显示 human label、namespace/stable ID、release/lifecycle；expanded 只显示 published release-set 的 bounded path/ancestor summary、source、evidence、license、digest 和 replacement candidates；historical 保留旧 CURIE、旧 release、obsolete/merged/split 原因和链接。
- [ ] `rl_ontology_term` 对 `consider` 只显示人工审核候选，不自动 redirect；`replaced_by` 只按已给定 policy 显示明确替代，不静默改变 canonical URL。why-comment：历史术语的可追溯性比“自动修正”更重要。
- [ ] `rl_provenance_citation_panel` 的 summary/expanded/export 三个视图都来自同一冻结 snapshot，只公开 stable source/version/license/citation、public artifact digest 和 canonical URL；不得出现 internal object ID、bucket/key、internal URI、presigned URL、approval identity、diagnostic 或 credential。
- [ ] `rl_external_source_notice` 将外部来源名称、更新时间、状态、离站提示和不可比较/不可导出资格单独表达；外部失败不改变本地结果区域。
- [ ] `rl_comparability_notice` 对同物种同组装、跨组装、跨物种、缺少 homolog/evidence、不同 dataset release 分别给出 compare eligibility 和解释。
- [ ] `rl_state` 覆盖 loading/skeleton、empty、error/retry、permission/403、stale、preview、deprecated、unavailable 和 maintenance，并提供可测试的 heading/description/action。
- [ ] `rl_data_surface` 在桌面使用 semantic table，窄屏转换为包含关键字段、scope、status、primary action 的 object card；不依赖 hover，不丢失下载/详情入口。

### 3.3 代表性代码契约

```tsx
// packages/ui/src/components/rl-scope-ledger.tsx
export type rl_scope_level = "global" | "species" | "assembly" | "dataset";

export interface rl_scope_ledger_value {
  scope_type: rl_scope_level;
  species: { label: string; slug: string } | null;
  assembly: { label: string; accession: string } | null;
  dataset_release: { label: string; version: string } | null;
  publication_release: { id: string; manifest_digest: string } | null;
  canonical_url: string;
}

export function rl_scope_ledger({ value }: { value: rl_scope_ledger_value }) {
  // 为什么：未适用的范围必须显式可见，避免用户把界面默认值误读为科研上下文。
  return <dl data-scope-type={value.scope_type}>{/* semantic rows */}</dl>;
}
```

```tsx
// packages/ui/src/components/rl-state.tsx
export type rl_surface_state =
  | { kind: "loading"; label: string }
  | { kind: "empty"; title: string; description: string }
  | { kind: "error"; code: string; retry?: () => void }
  | { kind: "permission"; capability: string }
  | { kind: "stale"; expected_release: string; actual_release: string }
  | { kind: "preview"; publication_release: string }
  | { kind: "deprecated"; replacement_url?: string }
  | { kind: "unavailable"; reason: string };
```

所有 exported first-party semantic identifiers 以 `rl_` 开头；文件名可按项目现有 kebab-case 约定命名。Story/fixture 中不得伪造内部 evidence，只使用公开 projection schema 的最小字段。

### 3.4 E1 验收

- [ ] Story 文件覆盖每个 primitive 的 default、long text、historical、missing scope、403、stale、mobile 和 reduced-motion 状态。
- [ ] 键盘测试能进入/退出 switcher、dialog、disclosure、citation export；焦点不丢失；状态变化使用 `role="status"` 或 `aria-live="polite"`，错误不抢占输入焦点。
- [ ] `packages/ui` 的 typecheck、lint、unit/component test 和 Story build 只验证 shared layer，不要求 A1/C/D 未提供的 runtime。

## 4. E2：公共 shell 与科研上下文

### 4.1 实现范围

- [ ] 在 `apps/web/src/components/rl-public-app-shell.tsx` 和 `apps/web/src/components/rl-scientific-context-bar.tsx` 统一页头、skip link、main landmark、breadcrumbs、scope ledger、release badge 和页脚引用入口。
- [ ] 在 `apps/web/src/routes/__root.tsx`、`apps/web/src/components/site-header.tsx` 中将导航分成 Discover、Explore、Analyze、Resources；Search 作为 first-class task。导航项由 C/D 已发布 projection 提供，不能在 E 中硬编码数据可用性。
- [ ] 无物种上下文进入首页或 `/search` 时不下载科研索引，只显示物种目录/选择；用户明确选择 scope 后才加载 D 的对应 shard。
- [ ] context switcher 对目标物种/组装/数据版本的模块可用性、筛选清理、比较篮失效和 canonical URL 变化给出确认；不自动切到“最新”。why-comment：科研链接必须可复现，不能用请求时间替换 URL 中的版本。
- [ ] mobile 将 context bar 压缩为可展开 ledger；桌面保持可检查但不挤压数据表；公共 touch target 至少 44px。

### 4.2 公共状态矩阵

| 状态 | 公共行为 | 禁止行为 |
|---|---|---|
| loading | skeleton 保留标题、scope 和表格列结构 | 不显示随机数字或跳动布局 |
| empty | 说明当前 scope、查询条件和下一步入口 | 不显示空白卡片或假数据 |
| error | error code/简述/retry/静态目录或 help 链接 | 不回退到未发布 live ORM |
| permission/403 | 公开端显示 unavailable 或登录/权限说明（若 contract 允许） | 不泄露 admin capability 名称或内部诊断 |
| stale | 显示 expected/observed publication/dataset digest 与 refresh | 不静默混用旧缓存和新上下文 |
| preview/deprecated | preview 仅在显式预览入口；deprecated 保留可引用页面、noindex/替代链接 | 不把 preview 当 production active |
| unavailable | 精确说明未发布、无数据、维护或 capability 缺失 | 不猜测其他 release 或替代 track |

### 4.3 测试先行

- [ ] 为 `apps/web/src/components/rl-scientific-context-bar.test.tsx` 写 URL precedence、switch confirmation、mobile disclosure、aria-live 和 stale digest tests。
- [ ] 为 `apps/web/src/routes/__root.test.tsx` 写 no-context no-index-load、published-navigation-only、skip-link 和 heading landmark tests。
- [ ] 测试应 mock D manifest-backed response，不 mock 数据库；fixture 标明 `publication_release_id`、`dataset_release_id`、manifest digest 和 scope。

## 5. E3：公共 Discover / Explore / Analyze / Resources consumers

### 5.1 Search：严格消费 D contracts

修改 `apps/web/src/routes/search.tsx`、`apps/web/src/lib/rl-search-consumer.ts`、`apps/web/src/components/rl-search-results.tsx`，保留现有 TanStack Query/Router 和 `packages/api-client`，但只消费 D 已冻结的 Internal/External contracts。

- [ ] Search URL 显式支持 `scope=species|all`、species、assembly、dataset release、query、types、filters、publication release（若保留期允许）。
- [ ] 默认当前物种/语言 shard；`scope=all` 才按需加载更多 shard。显示 index version、manifest digest、当前 scope 和结果来源。
- [ ] Internal results 独立区域，按 D envelope 显示 stable ID、type、species、assembly、dataset、publication、match explanation、canonical URL、provenance 和 compare/export eligibility。
- [ ] External results 独立区域，显示 source、updated time、external state、leave-site notice；外部 timeout/403/503 只改变 external state，不覆盖 internal results。
- [ ] Worker load/hash/schema/config 失败时使用 D 的 Internal API；API/Worker 均不可用时使用静态 directory/index 入口；绝不在主线程全量过滤大型数据集。
- [ ] search result loading 使用非打断 `aria-live`；结果数量变化不抢焦点；输入、scope switch、filter disclosure 完整键盘操作。

代表性 consumer 代码：

```tsx
function rl_search_surface({ query }: { query: rl_internal_search_query }) {
  const rl_internal = useQuery({
    queryKey: ["rl-internal-search", query],
    queryFn: () => rl_internal_search(query),
  });
  const rl_external = useQuery({
    queryKey: ["rl-external-search", query],
    queryFn: () => rl_external_search(query),
    enabled: query.include_external === true,
  });

  // 为什么：外部来源故障不能改变已发布本地结果的可信度和可用性。
  return <rl_search_results internal={rl_internal} external={rl_external} />;
}
```

测试必须断言两套 query/cache key、错误边界和 DOM region 独立，不能仅断言“页面有结果”。

### 5.2 Detail：scope、ontology、provenance

覆盖 `apps/web/src/routes/genes/$geneId.tsx`、`apps/web/src/routes/variants/index.tsx` 及详情入口（按现有 route tree 实际路径调整，但不复制 route 实现）。

- [ ] 详情首屏显示对象身份、物种、组装、dataset release、publication release、canonical URL 和 `rl_scope_ledger`。
- [ ] ontology field 使用 compact term；用户展开时只显示 release-set bounded path、definition/source/evidence/license/digest；historical term 保留旧链接和生命周期。
- [ ] `rl_provenance_citation_panel` summary 首屏可见，expanded 和 export（citation text/BibTeX/RIS，若 D/C contract 提供）使用同一 snapshot。
- [ ] withdrawn/merged/split/deprecated 对象仍显示稳定历史事实和替代链接；不存在或从未发布对象为 404，不猜测目标。
- [ ] 图表/track/分析入口显示可用 scope 和版本，提供文本摘要和下载/表格等非 Canvas 等价内容。

### 5.3 Compare：证据与资格先于操作

覆盖 `apps/web/src/routes/compare.tsx`、`apps/web/src/lib/compare-data.ts` 和 `apps/web/src/components/rl-comparison-basket.tsx`。

- [ ] 比较篮保存 object public IDs 加 scope/dataset/publication evidence，不保存内部 ID 或未发布对象。
- [ ] 加入项或 context switch 时计算 comparability：同 assembly 可直接比较；跨 assembly/物种必须显示 homolog/mapping/evidence；不同 dataset release 显示版本差异；缺少证据时 compare/export disabled。
- [ ] disabled button 有可访问说明和 tooltip/inline reason；不能用按钮消失掩盖 capability/eligibility 失败。
- [ ] 空篮、过期篮、stale publication、跨 scope、部分对象 withdrawn 均有明确状态和清理/回到详情动作。

### 5.4 Downloads / Resources：可引用、可核验

覆盖 `apps/web/src/routes/downloads.tsx`、`apps/web/src/routes/publications.tsx`、`apps/web/src/routes/guide.tsx`、`apps/web/src/routes/help.tsx`。

- [ ] 下载目录按 publication/dataset scope 展示文件名、类型、大小、digest、license、source、生成时间和 capability（download/Range/sidecar 如 contract 声明）。
- [ ] 下载与引用按钮绑定同一 snapshot；stale/missing artifact 显示不可用和 help/retry，不回退到“最新”。
- [ ] 页面无 JS 时仍保留静态目录、下载链接和 citation text；JavaScript 只增强筛选和复制。
- [ ] 内容/模块状态来自 C manifest projection：Hidden 从导航/list 移除但已发布详情保持 200；Deprecated 保持 200、noindex 和替代链接；未发布返回 404 或明确 module unavailable。

### 5.5 JBrowse：release-pinned launch

覆盖 `apps/web/src/routes/browser.tsx`、`apps/web/src/components/track-viewer.tsx`，以及 `apps/jbrowse/src/App.tsx`、`apps/jbrowse/src/config.ts` 的 consumer-facing seam；不改变 JBrowse 为 visualization subsystem 的边界。

- [ ] 浏览器 route canonical URL 必须携带 species、assembly、dataset release、publication release、locus 和 track selection；旧短路由仅按既有兼容规则跳转。
- [ ] iframe/embedded JBrowse 启动前显示 `rl_jbrowse_launch_summary`：scope ledger、manifest digest、config/track version、source/license、当前 locus 和可用 track。
- [ ] C/D artifact capability profile 声明需要 sidecar、Range、CORS、origin 或 digest 时，逐项显示缺失能力；例如 `sidecar missing`、`Range not supported`、`CORS origin rejected`、`manifest digest mismatch`。禁止泛化为“browser unavailable”，禁止切换其他 release。
- [ ] API/JBrowse unavailable 时保留 locus、release、source 和 retry/open-directly；若静态 track summary 可用，先显示精确降级状态；不伪造 synthetic scientific data。
- [ ] `prefers-reduced-motion` 下不做平滑位移；JBrowse heavy view lazy-load，但 loading overlay 不遮蔽 context ledger 的可读信息。

why-comment：JBrowse 只渲染已登记并绑定 manifest 的资源；它不能自行选择最新 assembly、track 或 provenance，否则用户看到的坐标与引用可能来自不同快照。

## 6. E4：Admin 五个 governed workspaces

### 6.1 工作台（Workbench）

路径：`apps/admin/src/routes/index.tsx`、`apps/admin/src/components/admin-header.tsx`、`apps/admin/src/components/admin-sidebar.tsx`。

- [ ] 显示真实待处理队列：待导入诊断、待审核内容/数据、发布阻断、stale/unknown deployment、需要人工 resolution 的 artifact/ontology 问题；所有数字来自 A1/C query，不能随机生成。
- [ ] 每行显示 scope、owner/capability、severity、last updated、evidence digest、next action 和 route；没有后端契约的入口显示 disabled with “not available in current capability contract”，不伪装可用。
- [ ] 403、session expired、stale query、API unavailable 分别有状态；403 不触发无限 retry，不通过前端隐藏规避。
- [ ] Admin 密度 8/10：优先表格、分割线、紧凑 metadata 和任务队列，避免 dashboard card wall；动效只用于 route/loading feedback。

### 6.2 数据发布（Data Publishing）

路径：`apps/admin/src/routes/imports.tsx`、`apps/admin/src/routes/assemblies.tsx`、`apps/admin/src/routes/variants.tsx`、`apps/admin/src/routes/tracks.tsx`、`apps/admin/src/routes/seeds.tsx`，共享 components 在 `apps/admin/src/components/rl-data-publishing-*.tsx`。

#### 五步骤导入

将现有 file-path modal 改为 full-page stepper，但上传、登记、任务 dispatch 仍只使用 A1 registered upload/artifact/object IDs：

1. **Target scientific context**：选择 species、assembly、dataset release candidate、object type；显示 scope contract 和 capability gate。
2. **File detection**：读取已登记 upload session 的 filename/type/size/digest；显示 detected format、encoding、compression、artifact identity；禁止任意 server path。
3. **Field/coordinate mapping**：字段映射、coordinate system、reference assembly、namespace、required/optional fields；不一致立即阻断下一步。
4. **Source/license/citation**：source namespace、license、citation、attribution、provenance evidence；`unknown/pending/restricted` license 不可提交 public candidate。
5. **Quality report/submit**：summary、counts、error/warning/unresolved diagnostics、sample rows、recommended repair、safe cancel、retry、提交后 approval state。

先写 `apps/admin/src/routes/imports.test.tsx`：禁止 arbitrary `file_path`、缺 capability 的 step disabled、scope mismatch 阻断、license gate、cancel idempotency、403、task failure 和 stale progress。实现 `rl_import_stepper`、`rl_import_quality_report`、`rl_diagnostic_workspace` 后再接现有 `http`/TanStack Query。

`rl_diagnostic_workspace` 必须展示 error code、phase、count、sample rows、impact scope、recommended repair、retry/safe cancellation、resolution decision、evidence digest 和历史事件入口；诊断只能追加，不能用新状态覆盖删除旧错误。

why-comment：导入诊断既是操作修复依据也是 release evidence；覆盖式进度会让审核者无法解释一份数据为何被接受。

### 6.3 站点内容（Public Experience）

路径：`apps/admin/src/routes/content.tsx`、`apps/admin/src/routes/layout.tsx`、`apps/admin/src/routes/widgets.tsx`、`apps/admin/src/routes/widgets/$name.tsx`、`apps/admin/src/routes/widget-preview.tsx`、`apps/admin/src/routes/widget-health.tsx`。

- [ ] 将现有 Content/Widgets/Layout/Preview 以工作区分组呈现：页面 route/locale/SEO、registered module、scope、state、schema validation、fallback copy、preview。
- [ ] 只能编辑 registered module 的 validated config；UI 不提供 arbitrary HTML/JS/template/expression/inline CSS 或任意 URI/path 输入。
- [ ] `rl_release_impact_preview` 在提交前列出 navigation、home entry、sitemap、search filter、static route/deep link、desktop/mobile 和 affected publication/dataset scope。
- [ ] Draft/Preview/Published/Hidden/Deprecated 分别显示；没有 C preview/build contract 时 preview action disabled 并说明原因。
- [ ] 页面显示“保存后何时生效”：运行时允许的状态、需重建索引、需静态发布；不得声称保存即 production 生效。
- [ ] content 403/field validation/stale revision/preview unavailable 各有可操作说明；提交者不能自己审核自己的高风险变更，UI 按 A1 returned capability/transition 事实展示。

### 6.4 发布中心（Publication Center）

路径：`apps/admin/src/routes/releases.tsx`、`apps/admin/src/components/rl-publication-evidence-matrix.tsx`、`apps/admin/src/components/rl-history-timeline.tsx`、`apps/admin/src/components/confirm-dialog.tsx`。

将现有 `Activate/Rollback/Archive` 作为历史兼容 UI 重新绑定 C/A1 typed command；不得直接用旧 `http.post('/admin/releases/...')` 声称新治理完成。

#### Review-evidence matrix

每个候选/已批准/部署尝试显示以下行，行状态来自 C manifest/approval/deployment contract：

| 证据区 | 必须呈现 | 阻断时行为 |
|---|---|---|
| frozen inputs | content revision、dataset IDs、ontology release-set、config hash、build time | publish disabled，链接到差异/诊断 |
| quality/license/citation | validation summary、license decision、citation/provenance digest | publish disabled，显示 unresolved count |
| artifacts | HTML/SSG、search/index、download、hash、SBOM、ready marker | promotion disabled，显示 artifact capability failure |
| search/router impact | Internal/External separation、route/sitemap/filter changes、D manifest binding | preview/review required |
| accessibility/visual | E a11y、responsive、designer handoff/screenshot evidence | release approval disabled |
| separation of duties | requester、reviewer、publisher、policy/quorum、expiry | self-approval/insufficient quorum disabled |
| deployment/rollback | environment approval、attempt/fencing、prior verified manifest、retention | CAS/rollback disabled until contract says eligible |

#### 三条 history timeline

- [ ] Dataset approval history：candidate、validation、remediation、review、accepted/rejected/expired；不把 current projection 当唯一事实。
- [ ] Publication build/approval history：freeze、queue、build、validation、artifact_ready、submitted、approved/rejected/expired；最终 publication approval 独立于 deployment approval。
- [ ] Deployment-attempt history：promotion、verifying、smoke result、failed/unknown、compensation、rollback；原 attempt 不改写成“未发生”。
- [ ] 每个 event 显示 timestamp、actor/capability（按权限）、target/revision digest、correlation/idempotency key、reason、evidence link 和 result；敏感内部字段遵循 public/admin projection schema。

高风险动作必须打开 A1 reauthentication/confirmation flow，要求确认目标 manifest digest、environment、impact summary、rollback target、reason/audit capture；按钮 disabled 不是成功，必须附带 `aria-describedby` 的阻断理由。CAS 后 smoke 失败显示 `verifying/compensation/unknown` 的真实状态，不提示旧指针“仍未改变”。

### 6.5 治理（Governance）

路径：`apps/admin/src/routes/users.tsx`、`apps/admin/src/routes/audit.tsx`、`apps/admin/src/routes/settings.tsx`，新增语义组件在 `apps/admin/src/components/rl-governance-*.tsx`。

- [ ] Users/roles 以 capability matrix 展示，不用角色继承推断权限；Auditor 始终 read-only。
- [ ] Audit 页面显示 append-only evidence、failure-audit、retention/legal hold 状态和 chain/checkpoint health；没有 edit/delete affordance。
- [ ] Settings 只显示 A1/C 已登记可编辑策略；未有 typed command 的设置入口删除或 disabled，不把通用 settings endpoint 当万能写入口。
- [ ] 403/401/reauth required/capability absent/retention hold/stale audit cursor 分别处理；权限拒绝显示安全的公开原因，不显示 secret、internal path 或未授权诊断。

## 7. E5：测试驱动实施顺序

每个子任务遵循 Red → Green → Refactor；先提交/运行失败测试，再写最小实现，再由 designer 做视觉 handoff 对照，最后才共享给下一 owner。不得把全量页面重写作为第一步。

### 7.1 Unit/component/Story 命令

```bash
pnpm --filter @soymutdb/ui test -- --run
pnpm --filter @soymutdb/ui typecheck
pnpm --filter @soymutdb/ui lint
pnpm --filter @soymutdb/ui storybook -- --ci
pnpm --filter @soymutdb/web test -- --run
pnpm --filter @soymutdb/admin test -- --run
pnpm --filter @soymutdb/web typecheck
pnpm --filter @soymutdb/admin typecheck
```

Expected signals：tests exit 0；新增 semantic state/scope/provenance/ontology/403/stale/preview/deprecated cases pass；typecheck 无新增错误；Story build 能加载所有 stories，无 missing export 或 invalid aria contract。若仓库 package script 名称与上述命令不一致，先读取对应 `package.json`，只使用已存在的等价 script，不新增依赖。

### 7.2 Focused Playwright E2E

新增 `tests/e2e/rl-phase-e-public.spec.ts`、`tests/e2e/rl-phase-e-admin.spec.ts`、`tests/e2e/rl-phase-e-jbrowse.spec.ts`，复用 `tests/e2e/playwright.config.ts` 的固定服务启动方式，不复用未知 localhost 服务。

```bash
npx playwright test tests/e2e/rl-phase-e-public.spec.ts --config=tests/e2e/playwright.config.ts
npx playwright test tests/e2e/rl-phase-e-admin.spec.ts --config=tests/e2e/playwright.config.ts
npx playwright test tests/e2e/rl-phase-e-jbrowse.spec.ts --config=tests/e2e/playwright.config.ts
npx playwright test tests/e2e/accessibility.spec.ts --config=tests/e2e/playwright.config.ts
```

Expected signals：

- Public：无上下文不下载 index；切换 scope 更新 canonical URL 并警告清除项；Internal/External 分区独立；Worker failure 回 Internal API/static directory；详情显示 scope/provenance/citation；compare qualification 正确；download digest/license/citation 同 release；JBrowse launch summary pinned 且 capability failure 精确。
- Admin：无 capability 的 route/action 获得真实 403 或 truthful disabled；导入五步在 scope/license/diagnostic 阻断；内容模块影响预览可见；发布中心 evidence matrix 和三条 timeline 与 fixture 一致；self-approval/quorum/reauth/unknown 状态不可绕过。
- A11y：skip link、landmarks、heading hierarchy、focus trap/restore、keyboard switcher/disclosure/dialog、`aria-live` result/task updates、non-color status、mobile object-card、44px public/36px compact-admin targets 均通过。

### 7.3 Responsive 与视觉 handoff evidence

- [ ] Playwright 覆盖 desktop、tablet、mobile viewport；宽表横向滚动可达，mobile object card 保留 scope/primary action；不依赖 hover。
- [ ] designer 在执行期提供每个公共关键 flow 与五个 Admin workspace 的 handoff screenshots/annotations；quality owner 将实现截图与 handoff 对照，记录 intentional deviation 和原因。
- [ ] 视觉验证只检查 Scientific Field Manual：纸张/灰绿基底、深绿 action、低对比分隔、高密度 metadata、等宽 ID/坐标、 restrained motion；不引入 marketing modules 或随机 metrics。
- [ ] `prefers-reduced-motion` 下 transitions/iframe loading/track pan 不产生非必要动画；测试使用 `page.emulateMedia({ reducedMotion: 'reduce' })`。

## 8. 403、错误、stale 与 disabled 的统一契约

实现 `apps/web/src/lib/rl-surface-state.ts` 与 `apps/admin/src/lib/rl-capability-state.ts`，但它们只能转换 A1/C/D response，不创建授权事实。

```ts
export type rl_capability_state =
  | { kind: "allowed" }
  | { kind: "forbidden"; capability: string; reason: string }
  | { kind: "reauth_required"; expires_at: string }
  | { kind: "stale"; expected_digest: string; actual_digest: string }
  | { kind: "unavailable"; contract: string };
```

- [ ] HTTP 403 与 capability response 都映射为同一 truthful disabled/forbidden presentation；按钮若展示，必须 disabled、说明理由、不可触发 mutation。
- [ ] 401/reauth 进入 A1 流程；不在 E 中自行弹出“确认即授权”的 dialog。
- [ ] stale response 显示 expected/actual release/digest 和 refresh/reload；不自动重试到另一个 release。
- [ ] network error 有有限 retry/backoff 和静态/只读 fallback；权限错误不 retry，contract mismatch 不 silent fallback。
- [ ] Admin permission gate 在 route loader、query action 和 mutation action 三层测试；public 只接受已发布 projection。

## 9. 回滚、失败处理与 Oracle phase review

### 9.1 E 内部回滚

- [ ] E 发布前保留现有 route/component exports 和旧视觉入口的可回退分支；先以 feature flag/route-level composition 连接 semantic primitives，flag 关闭时不改变 C/D resource identity。
- [ ] 若 E UI 失败，回滚只切换 E 的 frontend artifact/feature flag 到上一份通过的 Web/Admin bundle；不得回滚 `PublicationManifest`、public pointer、dataset release、search shard、artifact registry、approval history 或 deployment attempt。
- [ ] 若发现 projection 字段泄露，立即停止该 UI artifact promotion，记录 security evidence，修复 `rl_public_projection_schema` consumer；不得通过隐藏 DOM 或客户端清洗掩盖 C 产物问题。
- [ ] 若 JBrowse capability mismatch，保留 release-pinned summary 和精确诊断，禁用 launch；不得切换到 default/latest track。
- [ ] rollback rehearsal 必须验证旧 Web/Admin bundle 仍显示当前 active publication digest，Admin 仍遵循 A1 capability/403，public 仍无数据库依赖。

### 9.2 Oracle review 输入与通过条件

E 完成后只提交 E 证据包给 Oracle phase review：

1. exact file diff/ownership ledger，证明只改 E 允许路径（计划文件自身除外）。
2. shared primitive unit/component/Story results，包含 scope applicability、provenance redaction、ontology lifecycle、state semantics 和 a11y evidence。
3. public Playwright traces/screenshots：search isolation、detail/citation、compare qualification、download snapshot、JBrowse pinned/capability failure、mobile/reduced-motion。
4. Admin Playwright traces/screenshots：五 workspace、五-step import、diagnostic workspace、evidence matrix、three histories、403/disabled/reauth/stale/unknown。
5. designer handoff、视觉差异记录、a11y/keyboard/aria-live/responsive results；明确没有 marketing card-grid/random metrics/animations 或 framework/icon migration。
6. E rollback rehearsal 和旧 bundle/current manifest digest consistency evidence。
7. dependency proof：A0/A1/B/C/D artifact IDs/digests and gate verdicts are consumed read-only; E 未新增 authority、migration、dependency、deployment 或 API protocol。

Oracle 通过标准：无未解释的 capability affordance、无跨 release 混用、无本地/外部搜索混排、无 public projection 泄露、无 ontology 自动 redirect、无 JBrowse fallback 猜测、无 arbitrary content execution、无绕过授权；所有 failed/blocked/stale/unknown 状态可在 UI 中解释并复现。Oracle 未通过时只修 E 文件和测试/证据，不顺手扩展 A0/A1/B/C/D。

## 10. 最终执行清单

- [ ] 已确认 A0/A1/B/C/D gate verdict 和 artifact digests，且在执行日志中引用，不把“计划存在”当作 gate 通过。
- [ ] 已完成 E1 shared semantic primitives 与 Story/component tests。
- [ ] 已完成 E2 shell/context ledger 与 public state matrix。
- [ ] 已完成 E3 search/detail/compare/download/JBrowse consumer UX，严格使用 D/C contracts。
- [ ] 已完成 E4 五个 Admin workspaces、五步骤导入、diagnostic workspace、evidence matrix、three-history timelines。
- [ ] 已完成 E5 unit/component/Story/Playwright/a11y/responsive/reduced-motion 和 designer handoff evidence。
- [ ] 已运行 focused validation，记录 expected signals、失败项和修复 commit/artifact（不在本任务自动提交）。
- [ ] 已执行 E-only rollback rehearsal；未修改 authority、migration、dependency、deployment 或既有计划。
- [ ] 已请求 Oracle Phase E review；Oracle 通过前不得把 E 标为 completed 或进入 F。

**No automatic Git actions:** 本计划不授权 `git add`、`commit`、`amend`、`push`、branch、merge 或 PR；执行者必须等待用户/Orchestrator 明确授权。
