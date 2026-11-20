---
title: 使用指南
nav:
  title: 指南
  order: 1
---

## 安装与引入

工作区内的应用直接依赖源码包，无需构建产物：

```json
{
  "dependencies": {
    "@soymutdb/ui-react": "workspace:*",
    "@soymutdb/charts": "workspace:*",
    "@soymutdb/genome-view": "workspace:*"
  }
}
```

```tsx
import { Button, SoyMutdbProvider } from "@soymutdb/ui-react";

export default () => (
  <SoyMutdbProvider>
    <Button type="primary">查询突变体</Button>
  </SoyMutdbProvider>
);
```

## 三条约定

1. **不要绕开门面**：应用只从 `@soymutdb/*` 导入，不直接引用 `antd/es/*` 或图表引擎。
2. **动效必须可降级**：任何入场/过渡先经过 `resolveMotionDecision`，`off` 时不得播放。
3. **可访问替代**：图表同时提供精确数值表；基因组视图必须带 `ariaLabel`。

## 主题

`SoyMutdbProvider` 把品牌 token 注入 antd `ConfigProvider`。应用级覆盖通过 `theme` 属性合并，
不要在组件里散落硬编码颜色。

## 与站点变体的关系

文档站只服务开发者。`external`/`internal` 站点变体的构建、缓存与访问控制不受本应用影响。