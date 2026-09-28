/**
 * DOCX → HTML import for RichEditor (E1).
 *
 * mammoth (browser build) is loaded lazily so it lands in the editor chunk
 * only when the "Import DOCX" action is actually used. Heading styles map
 * to h1–h3 so the article structure survives the round trip; the produced
 * HTML is sanitized with DOMPurify before it is handed to TipTap.
 */
import DOMPurify from "dompurify";

/** Heading style-map so DOCX "Heading N" paragraphs become real h1–h3. */
const STYLE_MAP = [
  "p[style-name='Heading 1'] => h1:fresh",
  "p[style-name='Heading 2'] => h2:fresh",
  "p[style-name='Heading 3'] => h3:fresh",
  "p[style-name='Title'] => h1:fresh",
  "p[style-name='Subtitle'] => h3:fresh",
  // LibreOffice / WPS naming variants
  "p[style-name='标题 1'] => h1:fresh",
  "p[style-name='标题 2'] => h2:fresh",
  "p[style-name='标题 3'] => h3:fresh",
];

/**
 * Convert a .docx File to sanitized HTML ready for `editor.setContent()`.
 * Rejects files above `maxSizeBytes` (default 10 MB) before parsing.
 */
export async function docxToHtml(
  file: File,
  maxSizeBytes = 10 * 1024 * 1024,
): Promise<string> {
  if (file.size > maxSizeBytes) {
    throw new Error(`File exceeds the ${Math.round(maxSizeBytes / 1024 / 1024)} MB limit`);
  }

  const arrayBuffer = await file.arrayBuffer();

  // CJS interop — the browserify bundle exposes functions on module.exports.
  const mammothModule = await import("mammoth/mammoth.browser");
  const mammoth = (mammothModule as unknown as {
    convertToHtml: (options: {
      arrayBuffer: ArrayBuffer;
      styleMap?: string[];
    }) => Promise<{ value: string }>;
  }).convertToHtml;

  const result = await mammoth({ arrayBuffer, styleMap: STYLE_MAP });

  // Sanitize before it ever reaches the editor / is persisted.
  return DOMPurify.sanitize(result.value, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ["script", "style", "iframe", "object", "embed", "form", "input"],
    FORBID_ATTR: ["onerror", "onclick", "onload", "style"],
  });
}
