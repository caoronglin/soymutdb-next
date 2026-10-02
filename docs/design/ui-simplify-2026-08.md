# SoyMutDB 门户 UI 简约化设计方案（2026-08）

> **已归档（2026-10-01）**：2026-08 设计波次与旧基线快照。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md；门户布局以 `docs/superpowers/specs/2026-08-14-public-web-layout-alignment-design.md` 为准。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

目标：首页从"繁华门户"收敛为"一句话定位 + 搜索 + 三入口"的极简结构（参考 iSoybean）；导航从 7 个平铺条目收敛为 4 个分组；数据页统一模板。
涉及文件（fixer 只改这些）：
- `apps/web/src/routes/index.tsx`（首页重构）
- `apps/web/src/components/site-header.tsx`（导航重构）
- `apps/web/src/routes/genes/index.tsx`、`variants/index.tsx`、`blast.tsx`（模板统一）
- `packages/i18n/src/locales/{en,zh}/common.json`（新增 3 个 nav key，见 §3）

不改：`index.css` token 与类定义、packages/ui 组件源码、api-client、任何依赖版本。

## 1. 设计原则
1. 单一焦点：首屏只有标题、一句话定位、搜索框、三个入口；其余内容全部移除或降级。
2. 留白优先：垂直节奏靠容器 padding，不靠装饰元素填充；每屏可见元素 ≤ 4 组。
3. 克制色彩：primary 只用于链接、激活态、图标；全站每页最多保留 1 处渐变（首页 h1 的 `text-gradient`）。
4. 层级靠字号与灰度：标题 font-display semibold，正文 text-muted-foreground，数字 tabular-nums；不用阴影/光晕制造层级。
5. 动效只做颜色与边框过渡：hover 不用位移/缩放；入场动画只保留现有 CSS 过渡，HarmonyOS Sans SC 的字重对比（400/500/700）承担区分度。

## 2. 首页重构（apps/web/src/routes/index.tsx）

### 2.1 现有元素去留清单
| 现有元素 | 决定 |
|---|---|
| `DnaBackground` 动画背景 | 删除（含 import） |
| release eyebrow 徽章 | 删除（信息并入统计区 caption） |
| h1 标题 + `text-gradient` 高亮 | 保留 |
| subtitle 段落（home.subtitle） | 保留 |
| 搜索表单（input + 按钮） | 保留并弱化 |
| 示例 chips（SEARCH_EXAMPLES） | 保留并弱化 |
| ⌘K "Quick open" 按钮 | 删除（header 已有入口） |
| 右侧 ChromosomeHero "Variant density map" 卡片 | 删除（含 `ChromosomeHero` import、`densityQuery`） |
| 三个任务入口 TASK_ENTRIES | 保留，换内容、统一样式 |
| 统计区（6 StatCell + h2 标题） | 保留数字，弱化为单行文本条，删 h2/图标/hover |
| stats source caption | 保留，合并 release/日期为一行 |
| Data Overview 图表区（ChromosomeDensityChart + ImpactDistribution） | 整区删除（含两个 React.lazy import、`impactQuery`、`fetchChromosomeDensity`、`fetchImpactSummary`） |
| Features 六卡区（FEATURES） | 整区删除 |
| Latest Release 渐变 CTA 区（ReleaseStat） | 整区删除 |

删除后不再使用的 import 一并清理：`Microscope/FlaskConical/Search` 以外的 lucide 图标、`Card*`、`EmptyState`、`ChromosomeHero`、`DnaBackground`。保留 `statsQuery`、`formatStat`、`DataErrorState`、`Skeleton`。页面最终结构 = hero section + 统计条 section + footer。

### 2.2 新 hero（居中单列）
```tsx
<section className="border-b bg-gradient-accent">
  <div className="container-prose flex flex-col items-center py-20 text-center md:py-28">…</div>
</section>
```
- h1：`mt-0 font-display text-4xl font-semibold leading-[1.1] tracking-tight md:text-5xl`，第二个 span 保留 `text-gradient block`。
- subtitle：`mt-4 max-w-2xl text-base leading-relaxed text-muted-foreground md:text-lg`。
- 搜索表单：`mt-8 w-full max-w-2xl`，`role="search"`。input 改为 `h-14 w-full rounded-xl border border-input bg-card pl-12 pr-32 text-base shadow-sm outline-none transition-colors placeholder:text-muted-foreground/80 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2`（删 shadow-md/glow/backdrop-blur/hover 位移）。按钮 `<Button type="submit" size="lg" className="absolute right-1.5 top-1 h-12">`，删 `btn-glow`。
- 示例 chips：容器 `mt-3 flex flex-wrap items-center justify-center gap-2`；chip `rounded-full border border-border bg-card px-3 py-1 font-mono text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary`（删 hover:-translate、backdrop-blur、bg-primary/5）。
- 三入口：容器 `mt-10 grid w-full max-w-3xl gap-3 sm:grid-cols-3`；新 TASK_ENTRIES：
  1. `{ to: "/browser", titleKey: "nav.browser", descKey: "browser.subtitle", icon: Microscope }`
  2. `{ to: "/blast", titleKey: "nav.blast", descKey: "blast.subtitle", icon: FlaskConical }`
  3. `{ to: "/genes", titleKey: "home.taskGenes", descKey: "genes.subtitle", icon: Search }`
  删除 `emphasis`/`tileClass` 字段。入口卡片：`group flex items-center gap-3 rounded-xl border border-border bg-card p-4 text-left transition-colors hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`；图标 `flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted text-primary`；标题 `text-sm font-semibold tracking-tight`；描述 `mt-0.5 line-clamp-1 text-xs text-muted-foreground`。不加箭头图标、不加位移/阴影 hover。

### 2.3 统计条（弱化）
```tsx
<section className="border-b bg-muted/20">
  <div className="container-prose py-6">
    <dl className="flex flex-wrap items-center justify-center gap-x-10 gap-y-3">
      {/* 6 个 cell：total_variants / gene_count / mutant_line_count / snp_count / indel_count / seed_accessions */}
      <div className="flex items-baseline gap-2">
        <dt className="text-xs uppercase tracking-wider text-muted-foreground">{label}</dt>
        <dd className="font-display text-lg font-semibold tabular-nums">{loading ? <Skeleton className="h-5 w-16" /> : value}</dd>
      </div>
    </dl>
    <p className="mt-4 text-center text-xs text-muted-foreground">
      {t("home.statsSource")} · <span className="font-mono">Wm82.a4.v1</span>
      {stats?.last_release_name ? <> · {stats.last_release_name}</> : null}
      {stats?.last_release_date ? <> · Updated <span className="font-mono">{stats.last_release_date}</span></> : null}
    </p>
  </div>
</section>
```
statsQuery.isError 时仍渲染现有 `DataErrorState`。删除 StatCell 组件与 grid gap-px 卡片外观。

### 2.4 动效
不新增任何 keyframe/JS 动画。hero 静态呈现；仅保留 hover/focus 的颜色与边框过渡（已受 `[data-anim="off"]` 与 prefers-reduced-motion 全局规则约束）。`FadeUp` 现为 no-op，无需处理。

## 3. 导航重构（apps/web/src/components/site-header.tsx）

### 3.1 结构
用 `NAV_GROUPS` + 独立直链替换 PRIMARY_NAV/SECONDARY_NAV：
- Explore（`nav.explore`，新 key）：/genes、/variants、/browser、/sra、/compare、/analytics
- Tools（`nav.tools`，已有）：/blast、/analyses、分隔线、/tools/seqfetch、/tools/enrichment、/tools/exppattern、分隔线、/tools（标签 `nav.allTools`，新 key）
- Downloads（`nav.downloads`）：顶级直链（仅 1 项，不做下拉）
- Resources（`nav.resources`，新 key）：/guide、/help、/news、/publications、/seed-request

新增 i18n key（en/zh common.json 的 nav 段）：`explore` = "Explore"/"浏览"；`resources` = "Resources"/"资源"；`allTools` = "All tools"/"全部工具"。

### 3.2 桌面下拉（新组件 NavDropdown，复制 LanguageSwitcher 的 outside-pointer 模式）
- 状态提升到 SiteHeader：`openMenu: string | null`，同时只开一个；路由变化（currentPath effect）与 Escape 关闭。
- 触发按钮：`nav-link flex items-center gap-1 rounded-md px-3 py-2 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring` + `ChevronDown className="size-3.5 transition-transform"`（打开时 rotate-180）；未激活 `text-muted-foreground hover:text-foreground`，激活 `text-foreground`。组激活判定：currentPath 与组内任一项满足 `===` 或 `startsWith`，写入 `data-active`（复用 `.nav-link::after` 下划线）。
- 面板：`absolute left-1/2 top-full z-50 mt-2 w-60 -translate-x-1/2 rounded-xl border bg-popover p-1.5 shadow-lg`，`style={{ animation: "fade-down 160ms cubic-bezier(0.16,1,0.3,1)" }}`，`role="menu"`。
- 菜单项：`flex items-center rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground`；当前路由项加 `bg-accent/60 font-medium text-foreground`。Tools 组两条分隔线：`<div className="my-1 h-px bg-border" aria-hidden />`。
- 桌面搜索 pill、语言/主题/AnimationControl 保持现状。

### 3.3 移动端菜单
- 保留 `mobile-menu-enter` 面板与搜索表单（md:hidden）；删除每个 item 的 `style={{ animationDelay }}` 交错。
- 内容改为 4 个顺序区块：Explore / Tools / Downloads（仅 1 条）/ Resources。区块标题 `px-1 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70`，区块间 `mt-5`；不使用折叠/手风琴。
- 链接：`flex items-center rounded-xl px-4 py-3 text-[15px] font-medium transition-colors`；激活 `bg-primary/10 text-primary`，默认 `text-foreground/80 hover:bg-accent`；删除 ChevronRight 与 inset shadow。
- 焦点管理：打开时 focus 第一个链接（ref + effect）；Escape 关闭并把焦点还给汉堡按钮；路由变化关闭（已有）。

## 4. 全局布局规则（类使用约定，index.css 不动）
1. 宽度：一律 `container-prose`；居中内容用 `max-w-2xl/3xl` 内层限宽。
2. 间距：内容/数据页用 `py-10 md:py-14`（不再用 `section-rhythm`，后者只留首页 hero）；页内：PageHeader→内容 `mt-8`，筛选→表格 `mt-4`。
3. 卡片：统一 `rounded-xl border border-border bg-card shadow-sm`；hover 只允许 `hover:border-primary/40`；禁用 `card-lift`、`card-hover-accent`、`btn-glow`、`text-gradient-animated`（类定义保留，移除首页/导航中的使用）。
4. 暗色：使用实心 `bg-card`/`bg-popover`；移除 `bg-card/70` + `backdrop-blur` 组合（header 的 token 驱动透明度除外）。
5. reduced-motion：不新增动画；hover 只改颜色/边框，reduced-motion 用户零损失。

## 5. 数据页模板（genes / variants / blast）
```tsx
<div className="container-prose py-10 md:py-14">
  <PageHeader title={…} description={…} breadcrumb={[{ label: t("nav.home"), href: "/" }, { label: … }]} actions={…} />
  <FilterBar className="mt-8" columns={3} items={…} active={activeFilters > 0} onClearAll={reset} />
  <div className="mt-4"><DataTable … /></div>
</div>
```
- genes：FilterBar items = q（Input 承载原搜索框）、chromosome、biotype；删除原 `flex gap-6` 侧栏 FilterPanel 布局；查询/列/分页逻辑不变。
- variants：items = chromosome、variant_type、impact；Export 按钮移入 PageHeader `actions`。
- blast：PageHeader + `<Card className="mt-8 max-w-3xl">` 表单，recent jobs 列表 `mt-6`；不用 FilterBar/DataTable。
- 保留 FadeUp 包裹（no-op，零风险）；本地 `components/data-table.tsx` 继续使用。

## 6. 验收清单（fixer 自检）
1. `pnpm typecheck`、`pnpm build:web` 通过，无 TS/ESLint 错误。
2. 首页只剩 hero + 统计条 + footer 三块；无图表、无 feature 卡、无渐变 CTA、无 DNA 背景。
3. Network 面板首页仅 `homepage-stats` 请求（chromosome-density、impact-summary 消失）。
4. 导航：桌面 4 组（Explore 6 项、Tools 7 项含 /tools、Downloads 直链、Resources 5 项）全部可达；子路由激活正确（如 /genes/Glyma.xx 高亮 Explore）。
5. 360px：搜索框、三入口纵排、统计条换行、移动菜单可滚动，无横向滚动条。
6. 暗色模式：无发灰半透明块、文字对比正常。
7. AnimationControl 设为 off 及系统 prefers-reduced-motion：无入场/位移动画，内容完整可见。
8. 搜索提交跳 /search?q=；示例 chips 可跳转；header ⌘K 面板正常。
9. zh/en 切换无缺失 key（不出现 nav.explore 等裸 key）。
10. genes/variants/blast 回归：筛选、排序、分页、空态、错误态正常。
