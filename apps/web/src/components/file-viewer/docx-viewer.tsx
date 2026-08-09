/**
 * DOCX viewer — mammoth (browser build) loaded lazily (own chunk).
 *
 * The whole file must be fetched as an ArrayBuffer; callers are expected to
 * gate on size (MAX_PREVIEW_SIZE) before mounting this viewer.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Skeleton } from "antd";

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

export function DocxViewer({ url, maxSize = DEFAULT_MAX_SIZE }: DocxViewerProps) {
  const { t } = useTranslation();
  const [state, setState] = useState<DocxState>({ status: "loading" });

  useEffect(() => {
    let disposed = false;
    setState({ status: "loading" });

    (async () => {
      try {
        const res = await fetch(url);
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
        setState({ status: "ready", html: result.value });
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
      // mammoth output is sanitized the same way as markdown before render
      dangerouslySetInnerHTML={{ __html: state.html }}
    />
  );
}
