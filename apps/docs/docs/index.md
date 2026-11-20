---
title: SoyMutDB UI
hero:
  title: SoyMutDB UI
  description: 共享设计系统、动效策略与基因组视图组件的开发文档
  actions:
    - text: 开始阅读
      link: /guide
    - text: 设计系统
      link: /design-tokens
---

## 这个文档站是什么

`apps/docs` 是 dumi 驱动的**开发者文档**，收录 `@soymutdb/ui-react`、`@soymutdb/charts` 与
`@soymutdb/genome-view` 的公共契约。它不参与门户或管理台构建：

- `apps/docs/dist` 不会复制进 `apps/web/dist/external`；
- 文档站不是 `external`/`internal` 站点变体，不承载任何数据库记录；
- 生产交付仍走 `scripts/build-pages-artifact.sh` 与站点变体构建。

## 本地命令

```bash
pnpm docs:dev      # 本地预览 http://localhost:8000
pnpm docs:build    # 静态输出到 apps/docs/dist
pnpm docs:preview  # 预览已构建的静态站点
```

## 组件来源

| 包 | 职责 |
| --- | --- |
| `@soymutdb/ui-react` | antd 6 + ProComponents v3 门面、品牌主题、动效 token |
| `@soymutdb/charts` | 图表门面，内置精确数值表作为可访问替代 |
| `@soymutdb/genome-view` | 视口、轨道注册表与共享 SVG 渲染器 |

原生组件已经提供能力时直接复用 antd 组件，不重复实现；文档示例只展示项目自己的契约层。