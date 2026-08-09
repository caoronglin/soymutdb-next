/**
 * Code viewer — highlight.js (lazy chunk) syntax highlighting.
 *
 * Uses `highlight.js/lib/common` (auto-registers the most common languages)
 * plus a couple of project-relevant ones. Rendering happens once per
 * content/language pair; the highlighted HTML is injected as-is (hljs output
 * is generated from text, not user HTML).
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Skeleton } from "antd";

interface CodeViewerProps {
  content: string;
  language: string;
}

type CodeState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; html: string };

export function CodeViewer({ content, language }: CodeViewerProps) {
  const { t } = useTranslation();
  const [state, setState] = useState<CodeState>({ status: "loading" });

  useEffect(() => {
    let disposed = false;
    setState({ status: "loading" });

    (async () => {
      try {
        const { default: hljs } = await import("highlight.js/lib/common");
        if (disposed) return;
        const lang = hljs.getLanguage(language) ? language : "plaintext";
        const html = hljs.highlight(content, { language: lang, ignoreIllegals: true }).value;
        if (disposed) return;
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
  }, [content, language]);

  if (state.status === "loading") {
    return (
      <div className="space-y-3 p-4">
        <Skeleton active paragraph={{ rows: 3 }} />
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
    <pre className="rl-code-viewer overflow-auto rounded-md border p-4">
      <code
        className="hljs"
        style={{ fontFamily: "var(--font-mono)", fontSize: "0.8rem", lineHeight: 1.6 }}
        dangerouslySetInnerHTML={{ __html: state.html }}
      />
    </pre>
  );
}
