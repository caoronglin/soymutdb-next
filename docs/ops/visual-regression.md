# 多视口截图与布局指标

`e2e/tests/visual-layout.spec.ts` 对公共门户的 PPTX 关键页执行截图与基础几何验收，服务于 [`pptx-layout-acceptance-checklist.md`](pptx-layout-acceptance-checklist.md)。它是**视觉回归证据**，而非生产数据/API 质量门禁。

## 覆盖范围

- 路由：`/`、`/search/genes`、`/search/location`、`/search/gbrowse`、`/blast`
- 视口：desktop `1440×900`、tablet `1024×768`、mobile `390×844`
- 每次运行：15 张完整页面 PNG + `report.json`
- 硬断言：页面级无横向溢出、存在可见主内容、正文不为空。
- 记录指标：文档宽高、主内容/标题可见性、可交互元素数、小于 24×24px 的可交互元素清单。

## 前置条件

必须先构建当前工作树的 Web 静态制品；Playwright 的本地服务只服务该制品，并不启动另一个 Vite 开发应用。

```bash
pnpm --filter @soymutdb/web build
cd e2e
npm run test:visual
```

如 Chromium 未安装：

```bash
cd e2e
npx playwright install chromium
```

默认本地地址为 `http://localhost:4173/soymutdb-next/`，由 `e2e/static-server.mjs` 托管 `apps/web/dist`。如要审计已有 staging/预览环境，不启动本地服务：

```bash
cd e2e
VISUAL_BASE_URL=https://staging.example.org/ npm run test:visual
```

> `VISUAL_BASE_URL` 必须以 `/` 结束，并与被测应用的部署子路径一致。

## 输出与复核

输出目录为 `e2e/visual-artifacts/<ISO timestamp>/`：

- `home--desktop.png` 等：完整页面截图。
- `report.json`：机器可读指标；将其中 `scrollWidth > clientWidth`、`visible.main=false`、`undersized` 项与清单逐项复核。
- `e2e/playwright-report-visual/`：Playwright HTML 报告。

该测试**不自动把所有小型图标链接视为失败**，而是写进 `undersized`；QA 应结合实际点击面积和 ARIA 语义判断。任何硬断言失败必须修复或作为 No-Go 视觉问题登记。

## 当前边界

- 截图基于静态构建和 local mock；真实 Release 数据、BLAST 服务、JBrowse 外部 iframe 的最终内容需要在 staging 复跑并附环境 URL。
- 页面因路由未实现、iframe 配置缺失或 API 不可用产生的状态，应明确标记为环境/功能缺口，不能以截图存在代替可用性。
