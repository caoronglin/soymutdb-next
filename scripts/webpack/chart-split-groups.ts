/** Shared chart extraction; the closure gate still charges complete chunks. */
export function chartSupportCacheGroups() {
  return {
    chartFacade: {
      test: /[\\/]packages[\\/]charts[\\/]src[\\/]/,
      name: "chart-facade",
      priority: 45,
      enforce: true,
    },
    chartDependencies: {
      test: /[\\/]node_modules[\\/](?:@babel[\\/]runtime|color-name|color-string|d3-[^\\/]+|eventemitter3|fecha|flru|gl-matrix|html2canvas|internmap|is-arrayish|simple-swizzle|tslib)[\\/]/,
      name: (_module: unknown, chunks: { canBeInitial(): boolean }[]) =>
        chunks.some((chunk) => chunk.canBeInitial())
          ? "chart-dependencies-initial"
          : "chart-dependencies",
      priority: 24,
      enforce: true,
    },
  };
}
