/**
 * File-viewer format matrix — extension → kind mapping shared by
 * FilePreviewDialog and the per-kind viewers.
 *
 * Kinds:
 * - image:     <img> rendering
 * - csv/tsv:   native HTML table
 * - fasta:     specialized sequence viewer
 * - pdf:       pdfjs-dist (lazy chunk)
 * - docx:      mammoth (lazy chunk)
 * - markdown:  marked + DOMPurify (lazy chunk)
 * - code:      highlight.js (lazy chunk)
 * - text:      plain text fallback
 */

export type FileKind =
  | "image"
  | "csv"
  | "fasta"
  | "pdf"
  | "docx"
  | "markdown"
  | "code"
  | "text";

export const IMAGE_EXTENSIONS = new Set([
  "png",
  "jpg",
  "jpeg",
  "svg",
  "gif",
  "webp",
  "bmp",
  "tif",
  "tiff",
]);

export const CSV_EXTENSIONS = new Set(["csv", "tsv"]);

export const FASTA_EXTENSIONS = new Set(["fasta", "fa", "fna", "ffn", "frn"]);

export const PDF_EXTENSIONS = new Set(["pdf"]);

export const DOCX_EXTENSIONS = new Set(["docx"]);

export const MARKDOWN_EXTENSIONS = new Set(["md", "markdown", "mdown", "mkd"]);

/** ext → highlight.js language id (subset of `highlight.js/lib/common`). */
export const CODE_LANGUAGES: Record<string, string> = {
  py: "python",
  js: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  ts: "typescript",
  tsx: "typescript",
  mts: "typescript",
  cts: "typescript",
  json: "json",
  xml: "xml",
  html: "xml",
  htm: "xml",
  yaml: "yaml",
  yml: "yaml",
  sh: "bash",
  bash: "bash",
  zsh: "bash",
  c: "c",
  h: "c",
  cpp: "cpp",
  cc: "cpp",
  hpp: "cpp",
  java: "java",
  kt: "kotlin",
  r: "r",
  rb: "ruby",
  go: "go",
  rs: "rust",
  php: "php",
  sql: "sql",
  css: "css",
  scss: "scss",
  less: "less",
  toml: "ini",
  ini: "ini",
  conf: "ini",
  cfg: "ini",
  pl: "perl",
  ps1: "powershell",
  ipynb: "json",
};

/** Genomic text formats rendered as plain text (no highlighting). */
const PLAIN_TEXT_EXTENSIONS = new Set(["txt", "text", "gff3", "gff", "gtf", "bed", "vcf", "log"]);

/** Strip double-compression suffixes (.gz/.bz2/.zip) to reach the real format. */
export function getFileExtension(name: string): string {
  const parts = name.toLowerCase().split(".");
  if (parts.length < 2) return "txt";
  const last = parts[parts.length - 1];
  if (last === "gz" || last === "bz2" || last === "zip") {
    return parts.length > 2 ? parts[parts.length - 2] : "txt";
  }
  return last;
}

export function getFileKind(name: string): FileKind {
  const ext = getFileExtension(name);
  if (IMAGE_EXTENSIONS.has(ext)) return "image";
  if (CSV_EXTENSIONS.has(ext)) return "csv";
  if (FASTA_EXTENSIONS.has(ext)) return "fasta";
  if (PDF_EXTENSIONS.has(ext)) return "pdf";
  if (DOCX_EXTENSIONS.has(ext)) return "docx";
  if (MARKDOWN_EXTENSIONS.has(ext)) return "markdown";
  if (ext in CODE_LANGUAGES) return "code";
  if (PLAIN_TEXT_EXTENSIONS.has(ext)) return "text";
  // Unknown extensions default to plain text (best-effort preview).
  return "text";
}

/** Whether the kind is fetched as text (subject to truncation) rather than binary. */
export function isTextKind(kind: FileKind): boolean {
  return kind === "csv" || kind === "fasta" || kind === "markdown" || kind === "code" || kind === "text";
}

/** Language id for highlight.js, or null when not a code kind. */
export function getHighlightLanguage(name: string): string | null {
  const ext = getFileExtension(name);
  return CODE_LANGUAGES[ext] ?? null;
}

export function formatFileSize(bytes: number): string {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const size = bytes / Math.pow(1024, i);
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}
