---
title: GenomeView
group:
  title: 基因组视图
  order: 4
toc: content
---

## 组成

`@soymutdb/genome-view` 把基因组浏览器拆成四层，任何一层都可以独立复用：

| 导出 | 职责 |
| --- | --- |
| `createViewport` / `panViewport` / `zoomViewport` | 纯几何，无 DOM |
| `layoutIntervals` / `mergeExonSpans` | 轨道布局与基因结构 |
| `renderGenomeViewSvg` | 预渲染与交互路径共享的 SVG 输出 |
| `GenomeView` | 测量容器、指针手势、视口状态 |

## 示例

```tsx
import { GenomeView } from "@soymutdb/genome-view";

const region = {
  assemblyKey: "glyma.Wm82.a5",
  refName: "chr01",
  start: 100000,
  end: 140000,
};

const tracks = [
  { id: "ruler", label: "chr01", kind: "ruler" as const },
  {
    id: "genes",
    label: "基因",
    kind: "feature" as const,
    features: [
      { id: "glyma_01g001", start: 108000, end: 112000, label: "GLYMA_01G001", kind: "gene" as const, strand: "+" as const },
      { id: "glyma_01g002", start: 124000, end: 131000, label: "GLYMA_01G002", kind: "gene" as const, strand: "-" as const },
    ],
  },
];

const theme = {
  background: "#ffffff",
  surface: "#fafafa",
  text: "rgba(0,0,0,.88)",
  textSecondary: "rgba(0,0,0,.65)",
  border: "#f0f0f0",
  primary: "#2f6f4f",
  warn: "#faad14",
};

export default () => (
  <GenomeView
    region={region}
    tracks={tracks}
    theme={theme}
    ariaLabel="示例基因视图（chr01:100,000-140,000）"
  />
);
```

## 两种首屏

- 传入 `prerenderedSrc`：首屏直接显示服务端生成的静态 SVG，用户第一次平移/缩放后切换为实时渲染。
- 不传：从第一帧就在浏览器内按当前窗口生成 SVG。

两条路径使用同一个 `renderGenomeViewSvg`，因此标记结构一致，测试可以共享快照。

## 坐标约定

`Region` 使用 **0-based 半开区间**；只有深层链接/展示层才转换为 1-based 闭区间。
`assemblyKey` 必须显式携带，v4 与 v5 是不同命名空间，禁止按坐标猜测版本。

## 控件由调用方提供

组件不依赖 UI 组件库。调用方通过 `renderControls(api)` 使用 antd 的 `Button`/`Space`/`Segmented`
渲染控制条，`api` 提供 `viewport`、`pan`、`zoom`、`reset`、`panStepBp` 与 `interacted`。