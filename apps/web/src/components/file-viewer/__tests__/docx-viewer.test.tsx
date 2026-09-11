// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  convertToHtml: vi.fn(),
}));

vi.mock("mammoth/mammoth.browser", () => ({
  convertToHtml: state.convertToHtml,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/lib/antd", () => ({
  Skeleton: () => null,
}));

import { DocxViewer } from "../docx-viewer";

describe("DocxViewer", () => {
  beforeEach(() => {
    state.convertToHtml.mockReset();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        headers: new Headers(),
        arrayBuffer: () => Promise.resolve(new ArrayBuffer(1)),
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("removes malicious Mammoth HTML before rendering", async () => {
    state.convertToHtml.mockResolvedValue({
      value: '<p>Safe text</p><script>alert(1)</script><img src="x" onerror="alert(1)"><a href="javascript:alert(1)">bad link</a>',
    });

    render(<DocxViewer url="/document.docx" />);

    const safeText = await screen.findByText("Safe text");
    const viewer = safeText.closest(".rl-docx-viewer");
    expect(viewer?.querySelector("script")).toBeNull();
    expect(viewer?.querySelector("img")?.getAttribute("onerror")).toBeNull();
    expect(viewer?.querySelector("a")?.getAttribute("href")).toBeNull();
  });

  it("retains safe DOCX formatting and links", async () => {
    state.convertToHtml.mockResolvedValue({
      value: '<h1>Report</h1><p><strong>Important</strong> <a href="https://example.com" target="_blank">reference</a></p>',
    });

    render(<DocxViewer url="/document.docx" />);

    const reference = await screen.findByRole("link", { name: "reference" });
    const viewer = reference.closest(".rl-docx-viewer");
    expect(viewer?.querySelector("h1")?.textContent).toBe("Report");
    expect(viewer?.querySelector("strong")?.textContent).toBe("Important");
    expect(reference.getAttribute("href")).toBe("https://example.com");
    expect(reference.getAttribute("target")).toBe("_blank");
    expect(reference.getAttribute("rel")).toBe("noopener noreferrer");
  });
});
