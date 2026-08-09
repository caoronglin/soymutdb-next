/**
 * Markdown viewer — marked (lazy chunk) + DOMPurify sanitization.
 *
 * DOMPurify is an existing project dependency; marked is loaded on demand
 * so neither lands in the entry bundle.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Skeleton } from "antd";

interface MarkdownViewerProps {
  content: string;
}

type MdState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; html: string };

export function MarkdownViewer({ content }: MarkdownViewerProps) {
  const { t } = useTranslation();
  const [state, setState] = useState<MdState>({ status: "loading" });

  useEffect(() => {
    let disposed = false;
    setState({ status: "loading" });

    (async () => {
      try {
        const [{ marked }, { default: DOMPurify }] = await Promise.all([
          import("marked"),
          import("dompurify"),
        ]);
        if (disposed) return;
        const rawHtml = await marked.parse(content);
        if (disposed) return;
        // Sanitize before injecting — markdown may embed raw HTML.
        const html = DOMPurify.sanitize(rawHtml as string, {
          ADD_ATTR: ["target"],
        });
        setState({ status: "ready", html });
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
  }, [content]);

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

  return <div className="rl-md-viewer" dangerouslySetInnerHTML={{ __html: state.html }} />;
}
