// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import {
  renderMarkdown,
  renderMarkdownPreview,
  safePreviewHref,
  sanitizePreviewHtml,
} from "./markdown-preview";

describe("safePreviewHref", () => {
  it("keeps http(s), mailto and relative targets", () => {
    expect(safePreviewHref("https://example.org/a?b=1")).toBe("https://example.org/a?b=1");
    expect(safePreviewHref("mailto:editor@example.org")).toBe("mailto:editor@example.org");
    expect(safePreviewHref("/news/slug")).toBe("/news/slug");
    expect(safePreviewHref("#section")).toBe("#section");
  });

  it("rejects scripting, data and unknown schemes", () => {
    expect(safePreviewHref("javascript:alert(1)")).toBeNull();
    expect(safePreviewHref("JaVaScRiPt:alert(1)")).toBeNull();
    expect(safePreviewHref("java\nscript:alert(1)")).toBeNull();
    expect(safePreviewHref("data:text/html;base64,PHNjcmlwdD4=")).toBeNull();
    expect(safePreviewHref("vbscript:msgbox(1)")).toBeNull();
    expect(safePreviewHref("file:///etc/passwd")).toBeNull();
  });
});

describe("renderMarkdown", () => {
  it("renders the supported block and inline subset", () => {
    const html = renderMarkdown(
      "# Heading\n\nA **bold** and *italic* line with \u0060code\u0060.\n\n- one\n- two\n",
    );
    expect(html).toContain("<h1>Heading</h1>");
    expect(html).toContain("<strong>bold</strong>");
    expect(html).toContain("<em>italic</em>");
    expect(html).toContain("<code>code</code>");
    expect(html).toContain("<ul><li>one</li><li>two</li></ul>");
  });

  it("renders fenced code blocks without interpreting markup inside", () => {
    const html = renderMarkdown("\u0060\u0060\u0060ts\nconst x = <b>1</b>;\n\u0060\u0060\u0060");
    expect(html).toContain('<pre><code class="language-ts">');
    expect(html).toContain("const x = &lt;b&gt;1&lt;/b&gt;;");
    expect(html).not.toContain("<b>1</b>");
  });
});

describe("sanitizePreviewHtml", () => {
  it("keeps allowed markup and strips event handlers and disallowed tags", () => {
    const clean = sanitizePreviewHtml(
      '<img src=x onerror="alert(1)"><p class="x">ok <a href="javascript:alert(1)">link</a></p>',
    );
    expect(clean).not.toContain("<img");
    expect(clean).not.toContain("onerror");
    expect(clean).not.toContain("class=");
    expect(clean).not.toContain("javascript:");
    expect(clean).toContain("<p>ok ");
    expect(clean).toContain("link");
    expect(clean).not.toContain("<a href=");
  });

  it("hardens anchors with rel/target and keeps safe hrefs", () => {
    const clean = sanitizePreviewHtml('<a href="https://example.org">read</a>');
    expect(clean).toBe(
      '<a href="https://example.org" rel="noopener noreferrer" target="_blank">read</a>',
    );
  });

  it("removes script and style nodes entirely", () => {
    const clean = sanitizePreviewHtml("<script>alert(1)</script><style>p{}</style><p>safe</p>");
    expect(clean).toBe("<p>safe</p>");
  });
});

describe("renderMarkdownPreview", () => {
  it("escapes author HTML instead of injecting it", () => {
    const html = renderMarkdownPreview("# Hi\n\n<script>alert(1)</script>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
  });

  it("drops javascript: links but keeps the label", () => {
    const html = renderMarkdownPreview("[click](javascript:alert)");
    expect(html).not.toContain("javascript:");
    expect(html).not.toContain("<a ");
    expect(html).toContain("click");
  });

  it("keeps https links with a hardened rel", () => {
    const html = renderMarkdownPreview("[docs](https://example.org/docs)");
    expect(html).toContain('href="https://example.org/docs"');
    expect(html).toContain('rel="noopener noreferrer"');
  });
});
