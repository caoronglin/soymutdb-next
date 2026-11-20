---
title: 设计系统
nav:
  title: 设计系统
  order: 2
---

## 品牌 token

`@soymutdb/ui-react` 暴露框架无关的品牌 token 与 CSS 变量生成器。

```ts
import { brandCssVariables, brandTokens, BRAND_PRIMARY_HEX } from "@soymutdb/ui-react";

brandTokens.primary;      // oklch(0.46 0.13 152)
brandTokens.radius;       // 10
BRAND_PRIMARY_HEX;        // #2f6f4f
brandCssVariables();      // { '--smdb-primary': ..., ... }
```

| token | 值 | 用途 |
| --- | --- | --- |
| `primary` | `oklch(0.46 0.13 152)` | 浅色主色 |
| `primaryDark` | `oklch(0.70 0.12 151)` | 深色主色 |
| `radius` | `10` | 统一圆角 |
| `fontFamily` | `HarmonyOS Sans SC` 优先 | 中文界面字体栈 |

## 主题构造

```tsx
import { Button, Card, Space, SoyMutdbProvider } from "@soymutdb/ui-react";

export default () => (
  <Space size="large" align="start" wrap>
    <SoyMutdbProvider>
      <Card title="浅色" size="small" style={{ width: 260 }}>
        <Space>
          <Button type="primary">主要</Button>
          <Button>次要</Button>
        </Space>
      </Card>
    </SoyMutdbProvider>
    <SoyMutdbProvider dark>
      <Card title="深色" size="small" style={{ width: 260 }}>
        <Space>
          <Button type="primary">主要</Button>
          <Button>次要</Button>
        </Space>
      </Card>
    </SoyMutdbProvider>
  </Space>
);
```

## 颜色使用规则

- 主色只用于一个视图的主要操作，次要操作使用默认按钮。
- 数值与坐标使用等宽字体；长标识符允许换行，禁止截断成不可辨认的前缀。
- 深色模式通过 `SoyMutdbProvider dark` 切换算法，不新增第二套硬编码色板。