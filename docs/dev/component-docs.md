# 组件文档（apps/docs）

`apps/docs` 是 dumi 构建的组件与设计系统文档站，只面向开发者。它不是站点变体：
不参与 `pnpm build` / turbo 产物，也不会被复制进 `apps/web/dist/external` 或
`apps/admin/dist`，因此不需要、也不允许接入发布流水线。

## 命令

```bash
pnpm docs:dev       # dumi dev（热更新）
pnpm docs:build     # 输出 apps/docs/dist
pnpm docs:preview   # 预览已构建产物
bash scripts/verify-docs-artifact.sh            # 构建 + 校验
bash scripts/verify-docs-artifact.sh --no-build # 只校验现有 dist
```

`apps/docs/package.json` 特意**没有** `build` 脚本，所以 Turbo 的
`dependsOn: ["^build"]` 永远不会把文档站纳入生产构建图。校验脚本会把这条
性质当作不变量检查。

## 内容结构

| 路径 | 内容 |
| --- | --- |
| `docs/index.md` | 首页：包清单、约定、命令 |
| `docs/guide.md` | 使用指南：安装、主题、站点变体边界 |
| `docs/design-tokens.md` | 设计系统：品牌 token、主题构造、配色规则 |
| `docs/motion.md` | 动效策略：`MotionPolicy` 与已解析动画输入 |
| `docs/components/*.md` | `SoyMutdbProvider`、`MotionPolicy`、`ChartCanvas`、`GenomeView` |

`codeBlockMode: "active"` 让 `tsx` 围栏自动生成 `~demos/<id>` 演示页；
演示数据必须满足组件契约（例如 `SvgFeature` 需要 `id`，`Region` 需要
`assemblyKey`），否则构建后的演示页会在浏览器里抛错，纯 SSR 检查发现不了。

## 配置要点（dumi 2.4）

- 顶层只允许 `resolve`、`extraRemarkPlugins`、`extraRehypePlugins`、
  `themeConfig`、`logo`、`live`。写错 key 会被 Umi 的 `validateConfig` 直接
  拒绝；`mode` 在 dumi 2 已移除。
- `themeConfig.sidebar` 的类型是 `Record<string, ISidebarGroup[]>`，每个分组
  必须有 `children`；平铺的 `{ title, link }` 会让 `DocLayout` 在
  `group.children.map` 处崩溃。
- 工作区包只导出 TypeScript 源码，`resolve.alias` 指向源文件即可，不要用
  `require.resolve`（仅声明 `exports.import` 的包会抛
  `ERR_PACKAGE_PATH_NOT_EXPORTED`）。

## 校验

浏览器验证（必须，因为 dumi 预览对每个路由返回同一个 SPA 外壳）：

```bash
pnpm docs:build
pnpm docs:preview --port 18080
```

需要检查：所有路由 200 且出现预期标题、侧边栏链接存在、每个 `~demos` 页面
渲染出真实 DOM（canvas / svg / antd 组件）、控制台无错误。触碰图表或基因组
组件的演示时，还要确认图表画布或 `svg[data-strand]` 真的出现。

产物隔离由 `scripts/verify-docs-artifact.sh` 固定：`apps/docs/dist` 中不得出现
`:8001`、`:8002`、`100.66.114.71`、`internal_id`、`legacy-clickhouse`。