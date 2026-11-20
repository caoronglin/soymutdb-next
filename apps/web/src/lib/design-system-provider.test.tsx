/**
 * The internal variant labels what a screenshot would carry.
 *
 * The external site must stay unmarked: a watermark on public pages would be
 * noise, and the distinction between the two variants is a security boundary
 * the build already enforces.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const variant = vi.hoisted(() => ({ internal: true }));
const watermarkCalls = vi.hoisted(() => ({ count: 0, content: "" }));

vi.mock("./site-variant", () => ({
  get IS_INTERNAL_SITE() {
    return variant.internal;
  },
}));

vi.mock("./antd", () => ({
  ConfigProvider: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  App: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Watermark: ({ content, children }: { content?: string; children?: React.ReactNode }) => {
    watermarkCalls.count += 1;
    watermarkCalls.content = String(content ?? "");
    return <div data-watermark={content}>{children}</div>;
  },
}));

vi.mock("./antd-theme", () => ({
  createAntdTheme: () => ({}),
  loadAntdLocale: () => Promise.resolve(null),
}));

vi.mock("./theme-provider", () => ({ useTheme: () => ({ theme: "light" }) }));
vi.mock("./animation-context", () => ({ useAnimation: () => ({ intensity: "full" }) }));
vi.mock("@soymutdb/i18n", () => ({
  default: { language: "zh", on: () => {}, off: () => {} },
}));

import { DesignSystemProvider } from "./design-system-provider";

beforeEach(() => {
  watermarkCalls.count = 0;
  watermarkCalls.content = "";
});

describe("DesignSystemProvider", () => {
  it("watermarks the internal variant", () => {
    variant.internal = true;
    render(<DesignSystemProvider><p>body</p></DesignSystemProvider>);

    expect(watermarkCalls.count).toBe(1);
    expect(watermarkCalls.content).toBe("未发布数据");
    expect(screen.getByTestId("internal-watermark")).toBeTruthy();
  });

  it("leaves the external variant unmarked", () => {
    variant.internal = false;
    render(<DesignSystemProvider><p>body</p></DesignSystemProvider>);

    expect(watermarkCalls.count).toBe(0);
    expect(screen.queryByTestId("internal-watermark")).toBeNull();
    expect(screen.getByText("body")).toBeTruthy();
  });
});
