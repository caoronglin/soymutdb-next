import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { Editor } from "@tiptap/react";

import { MarkdownMode } from "./markdown-mode";

vi.mock("react-i18next", () => {
  const translation = { t: (key: string) => key };
  return { useTranslation: () => translation };
});

function fakeEditor(markdown: string) {
  const setContent = vi.fn();
  return {
    editor: { getMarkdown: () => markdown, commands: { setContent } } as unknown as Editor,
    setContent,
  };
}

describe("MarkdownMode", () => {
  it("previews author markdown and strips event-handler attributes", async () => {
    const { editor } = fakeEditor('**bold**\n\n<img src="x" onerror="alert(1)">');
    const { container } = render(<MarkdownMode editor={editor} />);

    fireEvent.click(screen.getByRole("button", { name: /markdownPreview/ }));

    expect(await screen.findByText("bold")).toBeTruthy();
    const img = container.querySelector("img");
    expect(img?.getAttribute("onerror")).toBeNull();
  });

  it("applies the source through TipTap's markdown content type", async () => {
    const { editor, setContent } = fakeEditor("# Title");
    render(<MarkdownMode editor={editor} onApplied={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /markdownApply/ }));

    expect(setContent).toHaveBeenCalledWith("# Title", { contentType: "markdown" });
  });
});