# Plan — Ant Design Mobile 移动端采用（公共站）

- 附属计划。主计划：[`2026-10-10-antv-analytics-python315.md`](./2026-10-10-antv-analytics-python315.md)。
  主计划的 integration（A 轨 bundle 预算实测）由协调者**串行后置派发**，本计划不依赖其结论，也不阻塞其执行。
- 日期：2026-10-11
- 状态：**仅研究与计划**。无实现、无安装、无构建、无服务启动、无 Git lifecycle。
- TDD Route：**off**（无 test-first 排序）。行为变更仍需 post-change regression。
- ArchitectureReviewRequired：**yes** — 新增第二个组件运行时 owner（antd-mobile）与现有 antd
  并存，涉及打包预算、双主题桥接与 SSG/hydration 边界。

## 目标

公共站（`apps/web`）在窄 viewport 下用 antd-mobile 呈现检索主页、筛选、结果列表与详情页；
桌面保留 antd。组件展示由 viewport 响应式决定，**不参与任何授权判定**。

## 资料获取实况（如实记录）

| 来源 | 结果 |
| --- | --- |
| `https://mobile.ant.design/zh` | HTTP 301 → `/zh/` 200，HTML 仅 **37 字符**可见文本 → **SPA 空壳，正文未读** |
| Jina Reader (`r.jina.ai`) | 连接失败 exit=7，未取得内容 |
| 官方仓库 Markdown（`ant-design-mobile` master） | 成功：`docs/guide/{quick-start,css-variables,dark-mode,import-on-demand}.zh.md`、`src/components/search-bar/index.zh.md`、组件目录（83 个） |
| npm registry `antd-mobile/latest` | HTTP 200，`5.43.0` |

官网 URL **正文未核**：此前只记录到 301 → `/zh/` 200 且为 SPA 空壳，正文从未取得，
因此**不能声称「官网内容与 GitHub Markdown 相同」**。上表原文获取记录不变。本文件全部内容
结论的依据是**官方仓库 Markdown 与 npm registry**；下列 canonical 源码链接即该依据：

- 快速开始 <https://github.com/ant-design/ant-design-mobile/blob/master/docs/guide/quick-start.zh.md>
- CSS 变量 <https://github.com/ant-design/ant-design-mobile/blob/master/docs/guide/css-variables.zh.md>
- 暗黑模式 <https://github.com/ant-design/ant-design-mobile/blob/master/docs/guide/dark-mode.zh.md>
- 按需加载 <https://github.com/ant-design/ant-design-mobile/blob/master/docs/guide/import-on-demand.zh.md>
- SearchBar <https://github.com/ant-design/ant-design-mobile/blob/master/src/components/search-bar/index.zh.md>

官网对应路径（仅作定位参考，正文未读、结论不以其为准）：
<https://mobile.ant.design/zh/guide/quick-start>、<https://mobile.ant.design/zh/guide/css-variables>、
<https://mobile.ant.design/zh/guide/dark-mode>、<https://mobile.ant.design/zh/guide/import-on-demand>、
<https://mobile.ant.design/zh/components/search-bar>

## 现状核对（分层声明）

**支持声明（实证）**：registry `peerDependencies` 为
`react: ^16.8.0 || ^17.0.0 || ^18.0.0 || ^19.0.0`，工作区 catalog `react/react-dom: 19.3.0`
→ **peer 范围被满足**。

**冲突事实**：官方快速开始页仍写「React 兼容 `^16.8.0 ^17.0.0 ^18.0.0`」，**未列 19**；
registry 包声明含 `^19.0.0`。二者不一致。

**安装实证**：无。`node_modules/antd-mobile` 不存在，`pnpm-lock.yaml`、
`apps/web/package.json`、`apps/admin/package.json`、`pnpm-workspace.yaml` 均无 `antd-mobile`。
`autoInstallPeers: false`。

> **结论**：peer 满足 ≠ runtime 兼容。React 19.3.0 下的真实渲染、SSR/SSG、触摸与 a11y
> 全部**未验证，标待核**。官方文档层面的兼容声明与 npm 元数据存在版本不一致，须实测裁决。

## 架构与边界

```
apps/web (React 19.3.0, antd 6.6.5, Umi Max 4.7.20)
   ├── 桌面 >= 断点  ──> antd（现状，不动）
   └── 移动 <  断点  ──> React.lazy + <Suspense> 动态 import ──> antd-mobile 5.43.0
                                  ↑ 目标：仅此 chunk 进入移动端首屏（**未实证**）
```

> 上图「仅此 chunk 进入移动端首屏」是**设计目标，不是已实证结论**。`React.lazy` 本身
> **不保证**桌面端不下载该 chunk：是否真按需加载、是否只出现在移动首屏，必须在实现后由
> 产物清单与网络瀑布实测确认。当前无实现、无构建、无产物，**该目标未验证**。

- **viewport 响应式**（CSS media query / `matchMedia`）是唯一展示开关；
  禁止用 UA / IP / host 决定 external/internal 或权限。
- `public_id`/`internal_id` 授权、v4/v5 命名空间、服务端分页、共享 service client 与
  URL 过滤状态**全部复用现有 owner**，移动端不新增第二套客户端或标识符。
- **主题桥接**：antd-mobile 走 `--adm-*` CSS 变量 + `data-prefers-color-scheme="dark"`
  （官方标注 Experimental）。antd 主题**不会**自然继承，必须显式桥接品牌色与暗色。
- **图表**：沿主计划同一 `@soymutdb/charts` AntV facade；移动端保留触摸交互、
  a11y 角色与精确数值表格降级。
- **hydration/SSG**：顶层不得读 `window`/`matchMedia`；判定必须在挂载后或纯 CSS，
  否则 SSG 产出与客户端首帧不一致。

## 组件映射（按官网实际组件）

| 场景 | antd-mobile 组件 | 约束 |
| --- | --- | --- |
| 检索主页 | `SearchBar`（`onSearch`/`onChange`/`showCancelButton`） | 输入仍走现有服务客户端 |
| 筛选 | `Popup` + `Selector` + `Dropdown` | 过滤态写 URL，服务端分页 |
| 结果列表 | `List` + `Card`；密集表格走现有 Table 响应式 | **不做全库无限加载** |
| 详情 | `Tabs` + `Collapse` | 显式展示 assembly / release / provenance |
| 状态反馈 | `Skeleton` / `Empty` / `ErrorBlock` / `Toast` | 复用既有语义 |
| 导航 | `NavBar` / `TabBar` / `SideBar` | **仅在真实信息架构需要时**引入 |
| 其它 | `Form` / `ImageUploader` / `SafeArea` / `PullToRefresh` | 后台密集表格**不强制**手机全量替换 |

官方按需加载：支持 Tree Shaking；手动按需时须额外 `import 'antd-mobile/es/global'`。

## 任务（后续派发，当前不执行）

1. **T1 依赖引入**：`pnpm-workspace.yaml` catalog 新增 `antd-mobile`（`pnpm`，非 mamba），
   `apps/web` 通过 `catalog:` 引用。回归：`pnpm install` + `pnpm typecheck`。
2. **T2 主题桥接**：新增显式 `--adm-*` 品牌/暗色桥接层。回归：明暗两态快照。
3. **T3 移动 shell**：`React.lazy` + `<Suspense>` 仅装移动 chunk；桌面首屏不得加载 mobile 全库
   ——**这是待实测的目标，不是 lazy 的既得结论**（见「架构与边界」下的说明）。
   回归：`bash scripts/check-bundle-size.sh <assets 目录>`，目录**按实际构建产物选取**，不写死：
   - 普通本机 `max build` 的产物在 `dist` **根**下，脚本参数取该次构建实际的 `assets` 路径
     （如 `apps/web/dist/assets`）；
   - 只有 `build:sites` **成功**产出站点变体时才是 `apps/web/dist/external/assets`；
   - 执行前先确认目录真实存在且含 `.js`，否则脚本会因目录缺失/无 JS 直接失败（`:36,:47`），
     不能拿失败当通过。
4. **T4 检索/筛选/列表/详情**：复用现有 service client 与 URL 过滤态。
5. **T5 回归与门限**：post-change regression，**TDD off**。

## 门限与验证

沿用 `scripts/check-bundle-size.sh` 既有预算（gzip）：`ENTRY_MAX_KB=750`、`CHUNK_MAX_KB=600`、
`CHARTS_MAX_KB=370`、`UI_MAX_KB=320`。**本计划不自创新阈值**；新增「移动 lazy chunk 统计」
条目，具体数值 **待主计划 A1 实测后由协调者串行确定**。脚本默认参数是
`apps/web/dist/external/assets`，但那是默认值不是必然产物路径——**以实际构建输出为准**。

回归命令取自根 `package.json` 既有 scripts，不臆造：
`pnpm build:web`、`pnpm lint`、`pnpm typecheck`、`pnpm test`、`pnpm ci:verify`
（= `bash scripts/ci-job-steps.sh run frontend`）、`pnpm smoke:artifact`。

测试矩阵：无 JS、低带宽、`SafeArea`/刘海、横竖屏、键盘弹出导致 viewport 变化、
最小触摸目标、读屏、`prefers-reduced-motion`。

## 风险

1. **React 19 runtime 兼容未验证**（最高）— 文档与 registry 声明不一致。
2. 双主题桥接遗漏导致明暗态割裂。
3. 移动 chunk 拖垮 `ENTRY_MAX_KB=750` 预算。
4. 顶层读 `window` 导致 SSG/hydration 不一致。
5. 越界：用 UA 判定站点变体或权限。

## 验收

计划自审：范围仅公共站移动端；不阻塞主计划 AntV/Python 315 路线；
每条组件/能力结论均标注官方 URL 或「无法读取（SPA 空壳）」。
