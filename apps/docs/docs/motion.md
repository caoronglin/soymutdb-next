---
title: 动效策略
nav:
  title: 动效
  order: 3
---

## 一个决策函数

所有动效先经过 `resolveMotionDecision`：它把用户偏好、`prefers-reduced-motion`、省流量、
低资源信号和会话上限合并成**一个**最终模式，避免各组件各自判断。

```tsx
import { resolveMotionDecision, Table, Tag } from "@soymutdb/ui-react";

const cases = [
  ["auto", {}, "standard"],
  ["auto", { reduced: true }, "standard"],
  ["standard", { saveData: true }, "standard"],
  ["standard", {}, "minimal"],
  ["minimal", {}, "standard"],
  ["off", {}, "standard"],
] as const;

export default () => {
  const rows = cases.map(([requested, signals, ceiling], index) => {
    const decision = resolveMotionDecision(requested, signals, ceiling);
    return {
      key: index,
      requested,
      signals: Object.keys(signals).length ? Object.keys(signals).join(", ") : "—",
      effective: decision.effective,
      reason: decision.reason,
    };
  });
  return (
    <Table
      size="small"
      pagination={false}
      dataSource={rows}
      columns={[
        { title: "请求", dataIndex: "requested" },
        { title: "信号", dataIndex: "signals" },
        {
          title: "最终",
          dataIndex: "effective",
          render: (value: string) => <Tag color={value === "off" ? "default" : "green"}>{value}</Tag>,
        },
        { title: "原因", dataIndex: "reason" },
      ]}
    />
  );
};
```

优先级：`reduced-motion` → 用户显式 `off` → 省流量/低资源 → 会话降级 → 偏好。

## 映射到 antd token

```ts
import { motionTokens } from "@soymutdb/ui-react";

motionTokens("standard"); // { base: 0.2, fast: 0.16, mid: 0.24, slow: 0.3 }
motionTokens("minimal");  // { base: 0.06, fast: 0.1, mid: 0.12, slow: 0.16 }
motionTokens("off");      // 全部为 0
```

`off` 不是删除 token，而是把时长置零：组件仍会读取 token，只是过渡瞬间完成。

## 约束

- 页面级入场编排（TweenOne）只在 `standard` 下启用。
- 图表动画同时受 `reduced` 与 `intensity` 控制；`off` 时不创建动画。
- 不允许组件内部直接读取 `matchMedia` 后再自行决定另一套规则。