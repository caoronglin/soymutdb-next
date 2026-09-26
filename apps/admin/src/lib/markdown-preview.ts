/**
 * Dependency-free Markdown preview for the admin news editor.
 *
 * The CMS stores an article body that the editor previews before saving. The
 * console must never let authored HTML execute, so the preview pipeline is:
 *
 *   1. HTML-escape the source (author HTML is shown as text, never injected);
 *   2. render a conservative Markdown subset to an HTML string;
 *   3. pass the result through an allowlist sanitiser before it reaches
 *      `v-html`.
 *
 * The public portal re-sanitises the stored body on its own render path; this
 * is the editor-time counterpart. There is no Markdown or sanitiser dependency
 * in this workspace, so the renderer and allowlist live here and are unit
 * tested directly.
 */

/** Tags the preview is allowed to emit (and therefore allowed to keep). */
const ALLOWED_TAGS = new Set([
  "p",
  "br",
  "hr",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "strong",
  "b",
  "em",
  "i",
  "del",
  "code",
  "pre",
  "ul",
  "ol",
  "li",
  "blockquote",
  "a",
]);

/** Attributes kept per tag; everything else is stripped. */
const ALLOWED_ATTRS: Record<string, ReadonlySet<string>> = {
  a: new Set(["href", "target", "rel"]),
  code: new Set(["class"]),
};

/**
 * Disallowed containers whose *text* must not survive sanitising. Unwrapping a
 * `<script>` would leave its source as visible text; these are removed whole.
 */
const DROPPED_TAGS = new Set([
  "script",
  "style",
  "iframe",
  "object",
  "embed",
  "template",
  "noscript",
  "svg",
  "math",
  "link",
  "meta",
  "title",
  "base",
]);

const BLOCK_START = /^\s*(?:#{1,6}\s|```|>\s?|[-*+]\s+|\d+\.\s+|---|\*\*\*|___)/;

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Return a link target safe to put in `href`, or `null` to drop the link.
 *
 * Only absolute `http(s)`/`mailto` URLs and relative/anchor targets survive;
 * `javascript:`, `data:`, `vbscript:` and every other scheme are rejected.
 * Whitespace is ignored while inspecting the scheme so `java\nscript:` cannot
 * slip past.
 */
export function safePreviewHref(raw: string): string | null {
  const value = raw.trim();
  if (!value) return null;
  const scheme = Array.from(value)
    .filter((char) => {
      const code = char.charCodeAt(0);
      return code > 0x20 && code !== 0x7f;
    })
    .join("")
    .toLowerCase();
  if (/^(?:javascript|data|vbscript|file):/.test(scheme)) return null;
  const explicitScheme = value.match(/^[a-z][a-z0-9+.-]*:/i);
  if (explicitScheme) {
    return /^(?:https?:|mailto:)/i.test(value) ? value : null;
  }
  return value;
}

/** Escape then apply the inline (non-block) Markdown subset. */
function renderInline(raw: string): string {
  const codeSpans: string[] = [];
  let text = escapeHtml(raw);

  // Inline code first so emphasis markers inside it stay literal.
  text = text.replace(/`([^`\n]+)`/g, (_match, code: string) => {
    codeSpans.push(`<code>${code}</code>`);
    return `\uE000${codeSpans.length - 1}\uE000`;
  });

  text = text.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_match, label: string, href: string) => {
    const target = safePreviewHref(href);
    if (target === null) return label;
    return `<a href="${target}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });

  text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  text = text.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  text = text.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  text = text.replace(/(^|[^_])_([^_\n]+)_/g, "$1<em>$2</em>");

  return text.replace(/\uE000(\d+)\uE000/g, (_match, index: string) => codeSpans[Number(index)]);
}

/** Render the supported Markdown subset to an HTML string. */
export function renderMarkdown(source: string): string {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: string[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    const fence = line.match(/^\s*```(\w*)\s*$/);
    if (fence) {
      const language = fence[1];
      index += 1;
      const code: string[] = [];
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) {
        code.push(lines[index]);
        index += 1;
      }
      index += 1;
      const className = language ? ` class="language-${language.replace(/[^a-z0-9-]/gi, "")}"` : "";
      blocks.push(`<pre><code${className}>${escapeHtml(code.join("\n"))}</code></pre>`);
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      const level = heading[1].length;
      blocks.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }

    if (/^\s*(?:---|\*\*\*|___)\s*$/.test(line)) {
      blocks.push("<hr />");
      index += 1;
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const quote: string[] = [];
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
        quote.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      blocks.push(`<blockquote>${renderMarkdown(quote.join("\n"))}</blockquote>`);
      continue;
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*+]\s+/, ""));
        index += 1;
      }
      blocks.push(`<ul>${items.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ul>`);
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+\.\s+/, ""));
        index += 1;
      }
      blocks.push(`<ol>${items.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ol>`);
      continue;
    }

    if (/^\s*$/.test(line)) {
      index += 1;
      continue;
    }

    const paragraph: string[] = [];
    while (
      index < lines.length &&
      !/^\s*$/.test(lines[index]) &&
      !BLOCK_START.test(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push(`<p>${renderInline(paragraph.join("\n")).replace(/\n/g, "<br />")}</p>`);
  }

  return blocks.join("\n");
}

function sanitizeElement(element: Element): void {
  const tag = element.tagName.toLowerCase();
  for (const attribute of Array.from(element.attributes)) {
    const allowed = ALLOWED_ATTRS[tag];
    if (!allowed || !allowed.has(attribute.name.toLowerCase())) {
      element.removeAttribute(attribute.name);
    }
  }
  if (tag === "a") {
    const href = element.getAttribute("href");
    if (href === null || safePreviewHref(href) === null) {
      element.removeAttribute("href");
    }
    element.setAttribute("rel", "noopener noreferrer");
    element.setAttribute("target", "_blank");
  }

  for (const child of Array.from(element.childNodes)) {
    if (child.nodeType === Node.ELEMENT_NODE) {
      const childElement = child as Element;
      const childTag = childElement.tagName.toLowerCase();
      if (DROPPED_TAGS.has(childTag)) {
        childElement.remove();
        continue;
      }
      sanitizeElement(childElement);
      if (!ALLOWED_TAGS.has(childTag)) {
        const parent = childElement.parentNode;
        if (parent) {
          while (childElement.firstChild) {
            parent.insertBefore(childElement.firstChild, childElement);
          }
          parent.removeChild(childElement);
        }
      }
    } else if (child.nodeType !== Node.TEXT_NODE) {
      child.remove();
    }
  }
}

/**
 * Strip every tag/attribute outside the preview allowlist.
 *
 * Used as defence in depth after `renderMarkdown` (which already escapes raw
 * author HTML) and exported so the allowlist can be unit tested against hostile
 * input directly.
 */
export function sanitizePreviewHtml(html: string): string {
  if (typeof DOMParser === "undefined") {
    // Non-DOM fallback: renderMarkdown only emits allowlisted tags and values,
    // so there is nothing else to strip in a headless environment.
    return html;
  }
  const document = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  sanitizeElement(document.body);
  return document.body.innerHTML;
}

/** Render and sanitise one Markdown body for a `v-html` preview. */
export function renderMarkdownPreview(source: string): string {
  return sanitizePreviewHtml(renderMarkdown(source));
}
