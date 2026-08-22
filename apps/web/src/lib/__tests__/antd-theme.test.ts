import { describe, expect, it } from "vitest";
import { createAntdTheme } from "../antd-theme";

describe("web AntD theme", () => {
  it("disables component motion only for the effective off mode", () => {
    expect(createAntdTheme({ motion: "off" }).token?.motion).toBe(false);
    expect(createAntdTheme({ motion: "minimal" }).token?.motion).toBe(true);
    expect(createAntdTheme({ motion: "standard" }).token?.motion).toBe(true);
  });

  it("uses shorter AntD timing tokens for minimal motion", () => {
    const token = createAntdTheme({ motion: "minimal" }).token;
    expect(token?.motionDurationFast).toBe("0.08s");
    expect(token?.motionDurationMid).toBe("0.1s");
    expect(token?.motionDurationSlow).toBe("0.15s");
  });
});
