/**
 * Minimal type declarations for `mammoth/mammoth.browser`.
 *
 * mammoth ships lib/index.d.ts but does not declare a `types`/`exports`
 * field, so the browser entry (a browserify UMD bundle) resolves as
 * implicit-any under `moduleResolution: bundler`. The public API used by
 * the DOCX viewer is a strict subset of the real types.
 */
declare module "mammoth/mammoth.browser" {
  export interface MammothConversionOptions {
    /** The DOCX file content as an ArrayBuffer. */
    arrayBuffer: ArrayBuffer;
    /** Optional inline image handler; omitted — images are skipped. */
    convertImage?: unknown;
    styleMap?: unknown;
    includeDefaultStyleMap?: boolean;
    includeEmbeddedStyleMap?: boolean;
  }

  export interface MammothResult {
    /** Generated HTML fragment. */
    value: string;
    messages: unknown[];
  }

  export function convertToHtml(
    options: MammothConversionOptions,
  ): Promise<MammothResult>;

  export function convertToMarkdown(
    options: MammothConversionOptions,
  ): Promise<MammothResult>;

  export function extractRawText(
    options: MammothConversionOptions,
  ): Promise<{ value: string; messages: unknown[] }>;

  export function images(options: unknown): unknown;

  const mammoth: {
    convertToHtml: typeof convertToHtml;
    convertToMarkdown: typeof convertToMarkdown;
    extractRawText: typeof extractRawText;
    images: typeof images;
  };

  export default mammoth;
}
