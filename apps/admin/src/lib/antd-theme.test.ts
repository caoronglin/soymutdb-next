import { describe, expect, it } from "vitest";
import { createAntdTheme } from "./antd-theme";

describe("admin AntD theme", () => {
  it("receives the resolved motion mode from the design-system provider", () => {
    expect(createAntdTheme({ motion: "off" }).token?.motion).toBe(false);
    expect(createAntdTheme({ motion: "minimal" }).token?.motionDurationMid).toBe("0.1s");
    expect(createAntdTheme({ motion: "standard" }).token?.motion).toBe(true);
  });
});
