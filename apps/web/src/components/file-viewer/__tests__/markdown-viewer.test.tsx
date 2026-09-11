// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  domPurifyModuleLoads: 0,
  parse: vi.fn(),
}));

vi.mock("dompurify", async (importOriginal) => {
  state.domPurifyModuleLoads += 1;
  return importOriginal();
});

vi.mock("marked", () => ({
  marked: { parse: state.parse },
}));

// The shared double keeps a stable `t` identity: an inline
// `() => ({ t: (key) => key })` returns a new function per render, which
// makes any component with `t` in an effect dependency loop forever.
// See src/test/mocks.ts.
vi.mock("react-i18next", async () => (await import("../../../test/mocks")).mockTranslation);

vi.mock("@/lib/antd", () => ({
  Skeleton: () => null,
}));

import { MarkdownViewer } from "../markdown-viewer";

describe("MarkdownViewer", () => {
  beforeEach(() => {
    state.parse.mockReset();
    state.parse.mockResolvedValue('<p>Safe content</p><script>alert(1)</script><img src="x" onerror="alert(1)"><a href="https://example.com" target="_blank">reference</a>');
  });

  afterEach(() => {
    cleanup();
  });

  it("uses DOMPurify from the static app graph and renders only sanitized markdown", async () => {
    expect(state.domPurifyModuleLoads).toBe(1);

    render(<MarkdownViewer content="# Preview" />);

    const safeContent = await screen.findByText("Safe content");
    const viewer = safeContent.closest(".rl-md-viewer");
    expect(state.parse).toHaveBeenCalledWith("# Preview");
    expect(viewer?.querySelector("script")).toBeNull();
    expect(viewer?.querySelector("img")?.getAttribute("onerror")).toBeNull();
    expect(viewer?.querySelector("a")?.getAttribute("rel")).toBe(
      "noopener noreferrer",
    );
  });
});
