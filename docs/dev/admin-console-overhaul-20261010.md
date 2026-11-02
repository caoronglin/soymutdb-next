# 管理后台重构 — 排查记录与执行状态

> 本机工作记录。仓库契约见 `AGENTS.md`，运行方式见 `.ai-memory/LOCAL-RUN-ENV.md`。
> 状态字段：`done` 已实测验证 / `wip` 进行中 / `open` 未开始 / `blocked` 需外部条件。

日期：2026-10-10

---

## 1. 根因：两份 antd 同时渲染一个 DOM

这是"样式怎么调都不对"的真正原因，不是配色问题。

| 组件 | 版本 |
| --- | --- |
| 应用使用的 antd | **6.6.5**（`pnpm-workspace.yaml` catalog） |
| `@ant-design/pro-layout@7.22.7` 的 peer 声明 | `antd: ^4.24.15 \|\| ^5.11.2` |
| pnpm 实际安装 | 额外装了一份 **`antd@4.24.16`** 专门喂 ProLayout |

`pro-components@3.1.15-2` 把 `pro-layout` 声明为硬依赖，所以移除需要连 `PageContainer` /
`ProCard` 一起换掉（239 处调用）。本次只把外壳切走，第二份 antd 因此**不在渲染路径上**，
但仍留在依赖图里。

两份 antd 各有独立的 CSS-in-JS 缓存与 `ConfigProvider` 上下文，所以主题 token、locale、
动效、暗色模式**全都传不进侧边栏**。证据：切换外壳前后，侧边栏选中态从拿不到 token 变为
拿到品牌绿。

### 证据

```
DOM: <div class="ant-design-pro ant-pro-layout">   (改造前)
     <div class="ant-layout-sider"> + .ant-menu      (改造后)
probe: proLayout=false  nativeSider=true  menuGroups=4  menuItems=18  itemHasIcon=18
```

---

## 2. 侧边栏分组是被 `flatMap` 丢掉的

`__root.tsx` 用 `NAV_SECTIONS.flatMap((section) => section.items.map(...))` 构造菜单，
4 个分组被展平成 19 项平铺。

**为什么没直接改回嵌套**：该处注释显示嵌套菜单曾被试过并因"看起来像空白栏"回退——问题被
绕开而非解决。原生 `Menu` 的 `type: "group"` 渲染正常，所以采用原生组件而非继续调
ProLayout 的参数。

`NAV_SECTIONS` 保持为导航唯一数据源：`nav-reachability.test.ts` 与
`navigation-render.test.tsx` 断言的对象就是它。

---

## 3. 已完成（`done`）

| 项 | 证据 |
| --- | --- |
| 外壳换原生 antd 6 `Layout`/`Sider`/`Menu` | 浏览器：4 组标题、18 项全部带图标、选中态拿到 token |
| 保留 `PageContainer`/`ProCard` 不动 | 239 处调用，渲染正常，避免回归 |
| 登录页按官方 Pro 左右分栏重写 | 浏览器：`管理大豆突变数据库 / 登录 / 用户名 / 密码` |
| 补齐 251 个缺失 i18n 键 | `apps/admin` 缺失键 0 |
| 新增"键缺失"守卫 | `test_locale_language_purity.py` 5 passed |

### 3.1 缺失键的性质

251 个键在源码里被 `t(key, { defaultValue })` 引用，但**两个 bundle 里都没有**，于是每个调用
静默渲染英文默认值。这是登录页在中文界面下仍是全英文的原因——键根本不存在，所以上一轮的
双语标签修复没覆盖到它。

其中：

- `admin.login.*` 19 个 —— 登录页全英文
- `admin.shell.*` 9 个 —— 侧边栏 Imports/Pages/News/Settings 等 9 项显示英文
- `admin.content.*` / `admin.media.*` / `admin.ops.*` / `admin.charts.*` 等 —— 表格列名、
  图表标题、空状态、按钮
- `admin.news.trash` 与 `admin.uploads` 在 bundle 里是**标签字符串**，代码却当命名空间用
  （`admin.news.trash.title`）。无人按标签读取，故以命名空间为准。

### 3.2 守卫的设计取舍

`test_both_locales_define_the_same_keys` **结构上看不见**"两边都缺"的情况，所以新增
`test_every_translated_key_exists_in_the_bundle`。

该守卫**限定 `apps/admin`**，因为门户仍有 127 个这类键。长期红灯的守卫等于没有守卫——会
训练所有人忽略它。门户那 127 个键见第 5 节。

---

## 4. 功能缺口排查（`wip`）

用户反馈"所有功能都不全"。已排除的**伪缺口**（查证后不是 stub）：

- `settings/{site,security,appearance,localization,advanced}.tsx` 各 2 行 —— 是
  `SettingsDomainPage` 的重导出转发，不是空实现
- `routes/imports/index.tsx`、`apps/web/src/routes/index.tsx` 极简 —— 重导出
- 全仓无 `TODO`/`FIXME`/`NotImplementedError`/`501`（仅 3 处注释级标记，见下）

真实的可疑点：

| 位置 | 内容 | 状态 |
| --- | --- | --- |
| `apps/api/app/api/v1/admin_imports.py:262` | "durable writer is not implemented default to OFF" | `open` |
| `apps/web/src/routes/analyses/index.tsx:82` | "TODO: remove once `GET /analyses` ships everywhere" | `open` |
| `apps/api/app/api/v1/sra.py:16` | 非预期 accession 返回 `"unknown"` stub 值 | `open` |
| 设置首页只有 6 个领域入口卡片 + "打开完整设置表单" | 待确认是否构成缺口 | `open` |
| 本地库为空（基因/变异/株系均 0） | 数据缺失，非代码缺陷 | `blocked` 需灌种子数据 |

**待用户指明**：具体是哪类功能缺失（缺页面 / 缺操作入口 / 点了没反应）。当前已排查的 4 处
均较小，无法支撑"所有功能都不全"的判断。

---

## 5. 未开始（`open`）

| 项 | 规模 | 说明 |
| --- | --- | --- |
| 门户 127 个缺失 i18n 键 | 中 | `analyses.*` 18+16、`mutants.*` 16、`genomeView.*` 5 等。与第 3 节同类 |
| 动效打磨 | 中 | antd 6 motion token 已接通，尚无额外过渡设计 |
| 移除 `pro-layout` 依赖 | 大 | 需同时替换 239 处 `PageContainer`/`ProCard` |

---

## 6. 回归基线

```
tsc --noEmit    web / admin 均干净
vitest          admin 62 passed
pytest scripts  380 passed, 1 skipped
locale guard    5 passed
browser sweep   18 个控制台页面，中文界面无英文 UI 文案
```

扫描残留只有产品名 `SoyMutDB`、数据库实例名 `Local SoyMutDB (local)`、用户名
`Local administrator` —— 都是数据不是界面文案。

提交：`e5f9a6f34`（外壳 + 登录页 + 251 键）、`166f76bda`（清理）。
CNB 上最后一次绿线仍是 `821fa7b4d`，以上均未推送。