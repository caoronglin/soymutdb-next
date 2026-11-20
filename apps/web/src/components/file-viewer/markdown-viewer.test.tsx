import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { MarkdownViewer } from "./markdown-viewer";

vi.mock("react-i18next", () => {
  const translation = { t: (key: string) => key };
  return { useTranslation: () => translation };
});

describe("MarkdownViewer", () => {
  it("renders markdown structure once the lazy chunk resolves", async () => {
    const { container } = render(<MarkdownViewer content={"# Title\n\n**bold** text"} />);

    const heading = await screen.findByRole("heading", { name: "Title" });
    expect(heading.tagName).toBe("H1");
    expect(container.querySelector("strong")?.textContent).toBe("bold");
  });

  it("renders raw HTML from an untrusted file as text, not markup", async () => {
    const { container } = render(
      <MarkdownViewer
        content={'<script>alert(1)</script>\n\n<img src="x" onerror="alert(2)">'}
      />,
    );

    await screen.findByText(/alert\(1\)/);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("opens links in a new tab with noopener noreferrer", async () => {
    render(<MarkdownViewer content="[NCBI](https://www.ncbi.nlm.nih.gov/)" />);

    const link = await screen.findByRole("link", { name: "NCBI" });
    expect(link.getAttribute("href")).toBe("https://www.ncbi.nlm.nih.gov/");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("drops javascript: link targets", async () => {
    const { container } = render(<MarkdownViewer content="[x](javascript:alert(1))" />);

    await screen.findByText("x");
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
  });
});