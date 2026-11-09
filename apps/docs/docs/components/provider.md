---
title: SoyMutdbProvider
group:
  title: 基础
  order: 1
toc: content
---

## 何时使用

应用根节点需要一个 antd `ConfigProvider`，并希望品牌主色、圆角、字体在所有页面一致时使用。
`@soymutdb/ui-react` 的组件都在这个 Provider 内工作。

## 示例

```tsx
import { Button, Card, Space, SoyMutdbProvider, Typography } from "@soymutdb/ui-react";

export default () => (
  <SoyMutdbProvider>
    <Card
      title="查询工作台"
      extra={<Button type="primary">开始查询</Button>}
      style={{ maxWidth: 520 }}
    >
      <Typography.Paragraph>
        Provider 只注入主题，不包裹路由、不发起请求，也不改变站点的安全边界。
      </Typography.Paragraph>
      <Space>
        <Button>查看发布</Button>
        <Button type="link">下载数据</Button>
      </Space>
    </Card>
  </SoyMutdbProvider>
);
```

## API

| 属性 | 说明 | 类型 | 默认值 |
| --- | --- | --- | --- |
| `dark` | 使用深色算法 | `boolean` | `false` |
| `theme` | 与品牌主题深度合并的 antd `ThemeConfig` | `ThemeConfig` | — |
| `children` | 子树 | `ReactNode` | — |

## 覆盖规则

`theme.token` 与 `theme.components` 会和 `createSoyMutdbTheme` 的结果合并；未覆盖的字段保持品牌值。
不要在子树里再嵌一个 `ConfigProvider`，除非确实需要局部暗色区域。