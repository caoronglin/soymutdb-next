/**
 * Markdown viewer — @ant-design/x-markdown (lazy chunk).
 *
 * X-Markdown parses with marked and sanitizes the result with DOMPurify.
 * File contents are untrusted, so `escapeRawHtml` renders embedded HTML as
 * visible text instead of markup, and `openLinksInNewTab` emits
 * rel="noopener noreferrer" on every link.
 */
import { useEffect, useState, type ComponentType } from "react";
import { useTranslation } from "react-i18next";
import { Skeleton } from "@/lib/antd";
import type { XMarkdownProps } from "@ant-design/x-markdown";

interface MarkdownViewerProps {
  content: string;
}

type MdState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; Renderer: ComponentType<XMarkdownProps> };

export function MarkdownViewer({ content }: MarkdownViewerProps) {
  const { t } = useTranslation();
  const [state, setState] = useState<MdState>({ status: "loading" });

  useEffect(() => {
    let disposed = false;
    setState({ status: "loading" });

    import("@ant-design/x-markdown")
      .then((mod) => {
        if (!disposed) setState({ status: "ready", Renderer: mod.default });
      })
      .catch((err) => {
        if (!disposed) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      });

    return () => {
      disposed = true;
    };
  }, []);

  if (state.status === "loading") {
    return (
      <div className="space-y-3 p-4">
        <Skeleton active paragraph={{ rows: 4 }} />
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

  const { Renderer } = state;
  return (
    <div className="rl-md-viewer">
      <Renderer content={content} escapeRawHtml openLinksInNewTab />
    </div>
  );
}