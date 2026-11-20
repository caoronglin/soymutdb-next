---
title: MotionPolicy
group:
  title: 基础
  order: 2
toc: content
---

## 纯函数契约

动效决策与 React 无关，可在路由预渲染、测试和图表里复用：

| 函数 | 说明 |
| --- | --- |
| `parseMotionPreference(raw)` | 解析持久化偏好，兼容旧的 `normal`/`expressive` 词汇 |
| `resolveMotionDecision(requested, signals, ceiling?)` | 合并系统与用户信号，返回唯一最终模式 |
| `motionTokens(effective)` | 映射为 antd 的四个时长 token |

```ts
import { parseMotionPreference, resolveMotionDecision } from "@soymutdb/ui-react";

parseMotionPreference(JSON.stringify({ intensity: "normal", explicit: false }));
// "auto"

resolveMotionDecision("standard", { reduced: true });
// { requested: "standard", effective: "off", reason: "reduced-motion" }
```

## 信号一览

| 信号 | 来源 | 效果 |
| --- | --- | --- |
| `reduced` | `prefers-reduced-motion` | 强制 `off`，优先级最高 |
| `saveData` | `navigator.connection.saveData` | `standard` 降为 `minimal` |
| `lowResource` | 设备/内存探测 | `standard` 降为 `minimal` |
| `sessionCeiling` | 本次会话已发生的降级 | `standard` 降为 `minimal` |

## 测试建议

决策是纯函数，直接断言返回值即可，不需要渲染组件。所有分支在
`packages/ui-react/src/motion-policy.test.ts` 中有覆盖；新增原因分支时同步补充测试。