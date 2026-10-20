/**
 * Text handling shared by the tool charts' tooltips.
 *
 * The legacy ECharts tooltips return HTML strings, and the enrichment tooltip
 * escapes four characters before interpolating the term name. The shared
 * facade's tooltip formatter returns a string too, and the engine still
 * renders it as markup -- so "it is only text" is not a safety argument, in
 * either renderer.
 *
 * The rule the tool charts follow: escape at the boundary, and never hand a
 * bare server string to a tooltip. `escapeChartText` escapes the five
 * characters that can start markup or break out of an attribute; the tool
 * charts use it for every interpolated value, including gene and condition
 * identifiers, which the legacy heatmap tooltip echoed unescaped.
 */

const HTML_ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

/** Escape one interpolated value for a tooltip body. */
export function escapeChartText(value: string): string {
  return value.replace(/[&<>"']/g, (character) => HTML_ESCAPES[character]);
}

/**
 * Join tooltip facts with a separator, escaping each part.
 *
 * Returns one line of text with no markup of our own, which is what the
 * shared formatter should receive: the value is then safe whether the engine
 * treats it as HTML or as plain text.
 */
export function chartTooltipText(parts: readonly string[], separator = " · "): string {
  return parts.map(escapeChartText).join(separator);
}
