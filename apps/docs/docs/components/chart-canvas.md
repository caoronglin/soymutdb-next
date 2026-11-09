---
title: ChartCanvas / ChartFigure
group:
  title: 图表
  order: 3
toc: content
---

## 契约先行

图表定义是**可序列化**的：`categoryBarChart` / `trendAreaChart` 只产出 `ChartDefinition`，
引擎选项由 `@soymutdb/charts` 内部构造。应用不要直接依赖 `@antv/g2`。

`ChartFigure` = `ChartCanvas` + 精确数值表 + 空/失败状态，是页面里的默认选择；
只有需要自定义替代内容时才单独使用 `ChartCanvas`。

## 示例

```tsx
import { ChartFigure, categoryBarChart } from "@soymutdb/charts";

const data = [
  { category: "SNP", value: 1280 },
  { category: "InDel", value: 340 },
  { category: "SV", value: 96 },
  { category: "MNV", value: 24 },
];

const definition = categoryBarChart(data, { valueLabel: "突变数" });

export default () => (
  <ChartFigure
    definition={definition}
    data={data}
    label="按类型统计的突变数量"
    description="示例数据，仅用于展示图表契约。"
    tableColumns={["类型", "数量"]}
    tableRow={(row) => [row.category, String(row.value)]}
    height={280}
  />
);
```

## API 摘要

| 属性 | 说明 | 类型 |
| --- | --- | --- |
| `definition` | 序列化图表定义 | `ChartDefinition` |
| `data` | 数据行 | `readonly TDatum[]` |
| `label` | 图形可访问名称 | `string` |
| `description` | 图形描述 | `string` |
| `tableColumns` / `tableRow` | 精确数值表（仅 `ChartFigure`） | `readonly string[]` / `(datum) => string[]` |
| `height` | 高度，默认 280 | `number` |
| `animation` | 动效输入，应用传入已解析结果 | `{ reduced?, intensity? }` |
| `theme` | 已解析主题；省略时读 CSS 变量 | `ChartThemeInput` |
| `onStatusChange` | 生命周期（`ChartFigure`） | `(status) => void` |

## 约束

- `total ≠ snp + indel + sv` 时不要用饼图；MNV 等类型必须单独可见。
- 空数据渲染 `emptyText`，引擎失败渲染可访问表格，两种情况都不能让路由白屏。
- 动画必须传入门面解析后的 `animation`，不要在图表内部读取系统偏好。