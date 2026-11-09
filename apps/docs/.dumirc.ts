import { resolve } from "node:path";

import { defineConfig } from "dumi";

// Component documentation is a developer-facing artifact. It is deliberately
// outside the portal/admin build: `docs:build` writes apps/docs/dist, which is
// never copied into apps/web/dist/external or served from either site origin.
export default defineConfig({
  title: "SoyMutDB UI",
  outputPath: "dist",
  hash: true,
  theme: {
    "@c-primary": "#2f6f4f",
  },
  // Workspace packages ship TypeScript sources; alias them so the docs bundler
  // transpiles the same files the applications consume.
  alias: {
    "@soymutdb/ui-react": resolve(__dirname, "../../packages/ui-react/src/index.tsx"),
    "@soymutdb/charts": resolve(__dirname, "../../packages/charts/src/index.ts"),
    "@soymutdb/genome-view": resolve(__dirname, "../../packages/genome-view/src/index.ts"),
  },
  resolve: {
    docDirs: ["docs"],
    codeBlockMode: "active",
  },
  themeConfig: {
    name: "SoyMutDB UI",
    logo: false,
    prefersColor: { default: "light", switch: false },
    nav: [
      { title: "指南", link: "/guide" },
      { title: "设计系统", link: "/design-tokens" },
      { title: "组件", link: "/components/provider" },
      { title: "动效", link: "/motion" },
    ],
    sidebar: {
      "/components": [
        {
          title: "组件",
          children: [
            { title: "SoyMutdbProvider", link: "/components/provider" },
            { title: "MotionPolicy", link: "/components/motion-policy" },
            { title: "ChartCanvas", link: "/components/chart-canvas" },
            { title: "GenomeView", link: "/components/genome-view" },
          ],
        },
      ],
    },
    footer: "SoyMutDB · 组件与设计系统文档",
  },
  mfsu: false,
});