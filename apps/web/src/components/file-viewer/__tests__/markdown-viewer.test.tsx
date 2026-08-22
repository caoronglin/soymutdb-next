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

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/lib/antd", () => ({
  Skeleton: () => null,
}));

import { MarkdownViewer } from "../markdown-viewer";

describe("MarkdownViewer", () => {
  beforeEach(() => {
    state.parse.mockReset();
    state.parse.mockResolvedValue('<p>Safe content</p><script>alert(1)</script><img src="x" onerror="alert(1)">');
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
  });
});
