import { describe, expect, it } from "vitest";
import viteConfig from "../../vite.config";

type ConfigFactory = (env: {
  command: "build" | "serve";
  mode: string;
  isSsrBuild: boolean;
  isPreview: boolean;
}) => {
  build?: {
    rollupOptions?: {
      output?: {
        manualChunks?: (id: string) => string | undefined;
      };
    };
  };
};

describe("public Vite manual chunks", () => {
  it("keeps the complete Ant Design and rc runtime in one acyclic chunk", () => {
    const config = (viteConfig as unknown as ConfigFactory)({
      command: "build",
      mode: "development",
      isSsrBuild: false,
      isPreview: false,
    });
    const manualChunks = config.build?.rollupOptions?.output?.manualChunks;

    expect(manualChunks).toBeTypeOf("function");
    expect(manualChunks?.("/repo/node_modules/rc-table/es/index.js")).toBe("antd");
    expect(manualChunks?.("/repo/node_modules/antd/es/table/index.js")).toBe("antd");
    expect(manualChunks?.("/repo/node_modules/@ant-design/icons-svg/es/asn/CheckOutlined.js")).toBe("antd-icons");
    expect(manualChunks?.("/repo/node_modules/antd/es/button/index.js")).toBe("antd");
  });
});
