# opt3-m — 门户路由动效运行时（Vue）

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

状态：已实现并验证（2026-09-27）。范围仅限 `apps/web`，**未改** `views/**`、`PortalHeader.vue`、`style.css`。

## 1. 背景

Vue 门户迁移后，`apps/web/src/style.css` 已带完整动效令牌与 `@keyframes` / `::view-transition-*` 规则，
但**没有任何运行时代码消费它们**：`--anim-duration*` / `--anim-easing*` / `--anim-stagger` 全是死令牌，
页面切换无过渡、区块无入场。React 基线的工作由 `motion-policy.ts`（决策）、`motion-prefs.ts`（持久化）、
`animation-context.tsx`（Provider + `data-anim` 属性）、`view-transitions.ts`（View Transitions 包装）
四处承担。本次把这些能力收敛进 Vue 侧的单一模块，并按仓库约束**不引入任何动画库**。

## 2. 交付文件

| 文件 | 作用 |
| --- | --- |
| `apps/web/src/lib/motion.ts` | 纯策略函数 + 令牌读取 + 模块级单一状态源 + `useMotion()` + `installRouteMotion()` |
| `apps/web/src/lib/motion.test.ts` | 纯函数四种组合、令牌解析、`matchMedia` 翻转、路由运行时、SSR 安全 |
| `apps/web/src/components/motion/RevealOnMount.vue` | 挂载入场组件（淡入 + 12px 上移），`as` / `delay` / `index` / `disabled` |
| `apps/web/src/components/motion/RevealOnMount.test.ts` | reduced 不加入场类、非 reduced 加入场类、两种情况内容均可见 |
| `apps/web/src/components/PortalLayout.vue` | `#main` 路由视图区包一层 keyed `RevealOnMount`（区块顺序改为 `template → script → style`） |
| `apps/web/src/main.ts` | 挂载后接线 `installRouteMotion(router)` |

## 3. 设计要点

- **单一状态源**：与 `lib/theme.ts` 同款模块级 `ref`。`preference`（localStorage `soymutdb-animation-prefs`）
  与 `prefersReduced`（`matchMedia("(prefers-reduced-motion: reduce)")`）两个 ref，派生一个 `computed` 决策；
  `watch(..., { flush: "sync" })` 把 `off / minimal / standard` 写到 `<html data-anim>`，
  直接复用 `style.css` 里已有的 `[data-anim="off"] *`（全量停动画）与 `[data-anim="minimal"]`（缩短令牌）。
- **纯函数**：`resolveMotionDecision({ reduced, preference })` 不读 DOM；reduced 优先于一切偏好，
  返回 `{ requested, effective, animate, reason }`。四种组合即测试矩阵。
- **SSR / 预渲染安全**：`typeof window === "undefined"` 时 `reduced = true`、令牌走兜底常量、不抛错。
- **令牌即时长**：`readMotionTokens()` 从 `getComputedStyle(document.documentElement)` 读 `--anim-*`，
  分 token 兜底；CSS 与 JS 不会各写一套时长。`minimal` 偏好经 `data-anim` 生效后，JS 读到的就是 100ms 那套。
- **降级不阻断导航**：`installRouteMotion` 用 `router.afterEach`（此刻 `currentRoute` 已更新但 Vue 尚未 patch DOM），
  回调里 `await nextTick()` 让浏览器先快照旧页、再快照新页；API 缺失 / reduced / 同路径 / `document.hidden`
  一律直接返回。`try/catch` + `transition.finished.catch()` 保证动效失败不影响路由，与 `AppErrorBoundary` 无耦合。

## 4. 与 React 基线逐项对照

| React 基线 | Vue 现状 | 说明 |
| --- | --- | --- |
| `motion-policy.ts#resolveMotionDecision` | `motion.ts#resolveMotionDecision` | 补齐。简化为 `reduced × preference`，保留 `auto/standard/minimal/off` 词表 |
| `motion-policy.ts#parseMotionPreference` | `motion.ts#parseMotionPreference` | 补齐（沿用 `soymutdb-animation-prefs` 键，跨版本不丢偏好） |
| `motion-prefs.ts`（saveData / lowPower / 硬件探测） | **有意简化**：只看 reduced | 本轮只要求 reduced；`connection.saveData`、`hardwareConcurrency` 探测留待需要时加，避免多一套判定 |
| `animation-context.tsx`（Provider + `data-anim` + `setIntensity`） | `useMotion()` + `setMotionPreference()` + `<html data-anim>` | 补齐。无 Provider：模块级状态天然单例，组件无需包一层 |
| `animation-context.tsx` 的 `INTENSITY_TOKENS` 硬编码时长 | 读 `style.css` 的 `--anim-*` | 补齐且更强：不再与 CSS 双写 |
| `route-motion.tsx` 的 `FadeUp/FadeIn/ScaleIn/Stagger/Reveal` | `RevealOnMount.vue` 一个组件 | **有意简化**：这次只做「入场」。React 那批包装组件本身是空壳（只丢 props），没有真实运行时 |
| `route-motion.tsx#CountUp` / `TextReveal` | 未做 | 数字滚动、逐字显示不在本轮 |
| `view-transitions.ts`（`startViewTransition` 包装 + `shouldSkipTransition`） | `installRouteMotion()` | 补齐。React 只提供 helper（且其 `RouteMotionRuntime` 返回 `null`，等于没接线），Vue 这次真正接上了 `afterEach` |
| React `RouteMotionRuntime` 从未接线 | 已接线 | 补缺口 |

**与任务书的一处偏离（有意）**：任务书建议 PortalLayout 用 `<RouterView v-slot>` + `<Transition>`。
实测 `<Transition>` 放在 PortalLayout 内是**惰性的**：PortalLayout 会随每个路由整体重建，
旧实例被同步卸载（leave 类从未出现），新实例的 Transition 又没 `appear`。
用 rAF 采样导航后 700ms 内的 `#main *` 类名，`.route-fade-*` 出现次数恒为 0。
因此改为 keyed `RevealOnMount`：新实例挂载即入场，语义正确、可验证、reduced 下类名根本不加。
`<Transition appear>` 也能工作，但与 reveal 会对同一元素叠加两层 opacity/transform 动画，故二选一。

## 5. 令牌消费映射

| 令牌（`style.css`） | JS 字段（`motion.ts`） | 消费点 |
| --- | --- | --- |
| `--anim-duration` | `MotionTokens.durationMs` → `useMotion().durationMs` | `RevealOnMount.vue` 的 `animation` 时长（CSS 直接 `var()`，JS 侧同源可读） |
| `--anim-easing` | `easing` | 同上（timing-function） |
| `--anim-stagger` | `staggerMs` | `RevealOnMount` 的 `index * staggerMs` → `style.animationDelay` |
| `--anim-duration-fast` | `durationFastMs` | 已暴露，供调用方/后续接入使用（当前无组件消费） |
| `--anim-duration-slow` | `durationSlowMs` | 同上 |
| `--anim-easing-spring` | `easingSpring` | 同上 |
| `data-anim="off"` / `data-anim="minimal"` | `EffectiveMotionMode` | `motion.ts` 写 `<html>`；由 `style.css` 既有规则消费 |

预算是「只动 opacity/transform」：reveal 的 keyframes 仅这两个属性，`will-change: opacity, transform`；
路由包装只加一层 div，不改变高度、不触发整页 layout。

## 6. SSG 可见性取舍

`RevealOnMount` **不输出内联 `opacity: 0`**：入场靠 `onMounted` 加类 `motion-reveal--active`，
由 scoped CSS 驱动。因此预渲染 HTML / 无 JS / 爬虫看到的都是完全可见的内容；
代价是入场只能在挂载后开始（客户端首帧前同任务内加类，不会先闪一帧全亮）。
没有选 `@starting-style`，因为它要求初始隐藏态在 JS 之前就存在，与「无 JS 可见」冲突。

证据（构建后实测）：

```
$ grep -o "<title>[^<]*</title>" apps/web/dist/index.html
<title>SoyMutDB — Soybean Mutant Database</title>
$ grep -c 'style="[^"]*opacity' apps/web/dist/index.html
0
$ grep -o '<div id="app"[^>]*>' apps/web/dist/index.html
<div id="app">                      # 无内联 style
$ grep -o 'motion-reveal--active\[data-v-[a-f0-9]*\]{[^}]*}' apps/web/dist/assets/index-*.css
motion-reveal--active[data-v-eae7b9b4]{animation:motion-reveal-in-eae7b9b4 var(--anim-duration) var(--anim-easing) both;will-change:opacity,transform}
```

注意：本仓库的「预渲染」目前只是**静态 shell + 每路由 head**（`#app` 为空、正文由 SPA 渲染），
所以首页 hero 文案（`Explore the unknown frontier...`）本来就不在 HTML 里（grep 计数 0）；
HTML 里稳定存在的是 `<title>` 与 `<meta name="description">`（两者均已验证存在）。
`RevealOnMount` 的取舍在将来任何 SSG/SSR 化之后依然成立。

## 7. 验证记录

| 命令 | 结果 |
| --- | --- |
| `pnpm --filter @soymutdb/web exec vitest run src/lib/motion.test.ts src/components/motion` | exit 0，2 files / 25 tests |
| `pnpm --filter @soymutdb/web test` | exit 0，**50 files / 251 tests**（只增不减；新增 2 files / 25 tests） |
| `pnpm --filter @soymutdb/web typecheck` | exit 0，0 错误 |
| `pnpm --filter @soymutdb/web lint` | exit 0 |
| `python3 scripts/check_visible_i18n.py` | `visible i18n OK` |
| `python3 scripts/test_motion_policy.py` | exit 0（无 gsap / lenis / ScrollTrigger 痕迹） |
| `VITE_API_BASE_URL=http://localhost:8010 VITE_JBROWSE_BASE_URL=http://localhost:5175 pnpm --filter @soymutdb/web build` | exit 0，27 documents |

浏览器（Playwright + Chromium，dev server 5173；API 以 route 桩稳定化）：

1. 默认 `no-preference`、原生 VT 可用：导航后 `document.startViewTransition` 调用 **1** 次，
   `.motion-reveal--active` 为 0（让位给根交叉淡入），URL 与正文正常；
2. 默认、删掉 `document.startViewTransition`：VT 调用 0 次，`animationName = "motion-reveal-in-7801035c"`
   （降级入场真实运行），导航正常；
3. `reducedMotion: "reduce"`：`html[data-anim="off"]`，VT 0 次、reveal 0 个，
   导航正常、正文正常、主题切换仍可交互（light → dark）；
4. `page.emulateMedia({ reducedMotion: "reduce" })` 在线切换：`data-anim` 立即由 `standard` 翻为 `off`
   （matchMedia change 监听生效），随后导航保持静默；
5. 四种场景 `pageerror` 均为 0。

## 8. 页面区块接入建议（本轮未改 `views/**`）

用法（`script setup` 里 import 即可，无需 Provider）：

```vue
<script setup lang="ts">
import RevealOnMount from "../components/motion/RevealOnMount.vue";
</script>

<template>
  <!-- 单块入场 -->
  <RevealOnMount as="section" class="mt-16">
    <h2>…</h2>
  </RevealOnMount>

  <!-- 列表交错：index 会乘以 --anim-stagger（60ms），无需手写延迟 -->
  <div class="grid gap-4 md:grid-cols-3">
    <RevealOnMount v-for="(card, i) in cards" :key="card.id" as="article" :index="i">
      …
    </RevealOnMount>
  </div>
</template>
```

规则：
- 只包**区块**，不要包整页（整页已由 PortalLayout + VT 负责），否则会叠两层动画；
- 一个区块只用一个 wrapper，避免嵌套；
- 首屏 hero 区块可先不加（它已经在首帧可见，加了会晚 300ms 才到位）；
- `index` 建议封顶 `Math.min(i, 6)`，长列表后半段别累加出秒级延迟。

建议先接 2~3 个页面（风险从低到高）：
1. **HomeView** `/` —— 首页刚验收，区块结构清晰（hero 之后的 `featured news` / `database stats` / `tool grid`），
   接入效果最直观；hero 保持不动；
2. **AboutView** `/about` —— 纯静态 CMS 文本，区块少、无数据依赖，回归面最小；
3. **GenesListView** 或 **MutantsListView** —— 表格/列表页，适合验证 `index` 交错与滚动列表下的性能。

## 9. 未完成 / 已知限制

- `views/**` 未接入 `RevealOnMount`（本轮刻意）；因此除首页/下载等页面外，区块入场要等下一轮。
- `saveData` / `lowPower` / `hardwareConcurrency` 降级未实现（React 有，Vue 有意简化）。
- `minimal` 偏好没有 UI 开关（React 有 `animation-control.tsx`），只能写 localStorage；
  `setMotionPreference` 已导出，接 UI 时直接用。
- `CountUp` / `TextReveal` 未做。
- `durationFastMs` / `durationSlowMs` / `easingSpring` 已从令牌读出但暂无消费点。
- 路由过渡目前是「新页入场 / 根交叉淡入」，没有 leave 动画——由 PortalLayout 每路由重建这一既有结构决定。
