/**
 * DOCX viewer — mammoth (browser build) loaded lazily (own chunk).
 *
 * The whole file must be fetched as an ArrayBuffer; callers are expected to
 * gate on size (MAX_PREVIEW_SIZE) before mounting this viewer.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Skeleton } from "@/lib/antd";
import DOMPurify from "dompurify";

interface DocxViewerProps {
  url: string;
  /** Fetch size cap in bytes — larger files are rejected without fetching. */
  maxSize?: number;
}

type DocxState =
  | { status: "loading" }
  | { status: "too-large" }
  | { status: "error"; message: string }
  | { status: "ready"; html: string };

const DEFAULT_MAX_SIZE = 10 * 1024 * 1024; // 10 MB

// Mammoth emits a document fragment, so accept only semantic formatting it
// normally produces. Safe links and inline images are retained; all styling,
// event attributes, embedded content, and active elements are excluded.
const DOCX_SANITIZE_CONFIG = {
  ALLOWED_TAGS: [
    "a", "b", "blockquote", "br", "code", "del", "div", "em",
    "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img",
    "li", "ol", "p", "pre", "span", "strong", "sub", "sup",
    "table", "tbody", "td", "th", "thead", "tr", "u", "ul",
  ],
  ALLOWED_ATTR: ["alt", "colspan", "href", "rowspan", "src", "target", "title"],
  ALLOW_DATA_ATTR: false,
  ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):|[^a-z]|[a-z+.-]+(?:[^a-z+.-:]|$))/i,
};

function sanitizeDocxHtml(rawHtml: string): string {
  const sanitized = DOMPurify.sanitize(rawHtml, DOCX_SANITIZE_CONFIG);
  const template = document.createElement("template");
  template.innerHTML = sanitized;
  template.content.querySelectorAll('a[target="_blank"]').forEach((link) => {
    link.setAttribute("rel", "noopener noreferrer");
  });
  return template.innerHTML;
}

export function DocxViewer({ url, maxSize = DEFAULT_MAX_SIZE }: DocxViewerProps) {
  const { t } = useTranslation();
  const [state, setState] = useState<DocxState>({ status: "loading" });

  useEffect(() => {
    let disposed = false;
    const controller = new AbortController();
    setState({ status: "loading" });

    (async () => {
      try {
        const res = await fetch(url, { signal: controller.signal });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const length = Number(res.headers.get("content-length") ?? 0);
        if (length > maxSize) {
          if (!disposed) setState({ status: "too-large" });
          return;
        }

        const arrayBuffer = await res.arrayBuffer();
        if (arrayBuffer.byteLength > maxSize) {
          if (!disposed) setState({ status: "too-large" });
          return;
        }

        const mammothModule = await import("mammoth/mammoth.browser");
        // CJS interop — the browserify bundle exposes functions on module.exports.
        const mammoth = (mammothModule as unknown as {
          convertToHtml: (o: { arrayBuffer: ArrayBuffer }) => Promise<{ value: string }>;
        }).convertToHtml;
        const result = await mammoth({ arrayBuffer });
        if (disposed) return;
        setState({
          status: "ready",
          html: sanitizeDocxHtml(result.value),
        });
      } catch (err) {
        if (disposed) return;
        setState({
          status: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      }
    })();

    return () => {
      disposed = true;
      controller.abort();
    };
  }, [url, maxSize]);

  if (state.status === "loading") {
    return (
      <div className="space-y-3 p-4">
        <Skeleton active paragraph={{ rows: 5 }} />
        <p className="text-center text-xs text-muted-foreground">
          {t("downloads.loading_preview")}
        </p>
      </div>
    );
  }

  if (state.status === "too-large") {
    return (
      <div className="rl-preview-empty">
        <p>{t("fileViewer.docxTooLarge")}</p>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="rl-preview-empty">
        <p>{t("fileViewer.loadFailed")}</p>
        <p className="rl-preview-empty-sub">{state.message}</p>
      </div>
    );
  }

  return (
    <div
      className="rl-md-viewer rl-docx-viewer"
      // Mammoth output is sanitized before it reaches this injection sink.
      dangerouslySetInnerHTML={{ __html: state.html }}
    />
  );
}
