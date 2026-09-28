/** Sanitized static preview document for the Admin Page Builder iframe. */

import type { PageComponentNode, PageDefinitionV2 } from "@soymutdb/shared";

const THEME_STYLES: Record<string, { background: string; foreground: string; accent: string }> = {
  "scientific-light": { background: "#ffffff", foreground: "#1f2937", accent: "#2563eb" },
  "scientific-dark": { background: "#111827", foreground: "#f9fafb", accent: "#60a5fa" },
  "high-contrast": { background: "#000000", foreground: "#ffffff", accent: "#fbbf24" },
  "compact-data": { background: "#f8fafc", foreground: "#0f172a", accent: "#0ea5e9" },
  print: { background: "#ffffff", foreground: "#000000", accent: "#000000" },
};

function escapeHtml(value: unknown): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderNode(node: PageComponentNode): string {
  const type = escapeHtml(node.type);
  const props = Object.entries(node.props ?? {})
    .filter(
      ([key, value]) =>
        !/^(?:on[a-z]+|script|style|href|src|url)$/i.test(key) &&
        !/javascript\s*:|^\s*(?:https?:|data:|vbscript:|file:)/i.test(
          String(value),
        ),
    )
    .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`)
    .join("");
  const children = (node.children ?? [])
    .map((child) => `<li>${renderNode(child)}</li>`)
    .join("");
  return `<section class="node" data-type="${type}"><h3>${type}</h3><dl>${props}</dl>${
    children ? `<ul>${children}</ul>` : ""
  }</section>`;
}

export function buildPreviewDocument(definition: PageDefinitionV2): string {
  const theme = THEME_STYLES[definition.theme_id] ?? THEME_STYLES["scientific-light"];
  const layouts = definition.layouts ?? {};
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Page preview</title>
  <style>
    :root { color-scheme: ${definition.theme_id === "scientific-dark" ? "dark" : "light"}; }
    body { margin: 0; padding: 16px; background: ${theme.background}; color: ${theme.foreground}; font: 14px/1.5 system-ui, sans-serif; }
    .node { border: 1px solid ${theme.accent}33; border-radius: 8px; padding: 10px; margin: 8px 0; }
    .node h3 { margin: 0 0 6px; color: ${theme.accent}; }
    dl { display: grid; grid-template-columns: auto 1fr; gap: 4px 8px; margin: 0; }
    dt { font-weight: 600; } dd { margin: 0; overflow-wrap: anywhere; }
    ul { list-style: none; padding-left: 12px; margin: 0; }
  </style>
</head>
<body data-theme="${escapeHtml(definition.theme_id)}" data-layouts="${escapeHtml(
    JSON.stringify({ desktop: layouts.desktop, tablet: layouts.tablet, mobile: layouts.mobile }),
  )}">
  <main>${renderNode(definition.root)}</main>
</body>
</html>`;
}
