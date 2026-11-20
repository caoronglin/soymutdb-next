/**
 * Markdown source mode for RichEditor (E1).
 *
 * The markdown text is an EXPLICIT import/export surface: it starts as a
 * snapshot of `editor.getMarkdown()` and only touches the rich-text content
 * when the user presses "Apply" (`setContent(..., { contentType: 'markdown' })`).
 * No lossless round-trip is promised — the Tabs switch is guarded by a
 * confirmation (see tiptap-editor.tsx).
 */
import { lazy, Suspense, useState } from "react";
import type { Editor } from "@tiptap/react";
// Side-effect import: pulls in @tiptap/markdown's module augmentation so
// `editor.getMarkdown()` / `setContent(..., { contentType: 'markdown' })`
// are typed in this file.
import "@tiptap/markdown";
import { Alert, Button, Skeleton, Space } from "../../lib/antd";
import { CheckOutlined, EyeOutlined, EditOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

// X-Markdown sanitizes with DOMPurify by default. The extra FORBID_* entries
// keep the preview at the same trust level the previous marked+DOMPurify
// pipeline enforced for author-supplied HTML.
const XMarkdown = lazy(() => import("@ant-design/x-markdown"));

interface MarkdownModeProps {
  /** The live TipTap editor (non-null — rendered only when mounted). */
  editor: Editor;
  /** Called after a successful explicit apply. */
  onApplied?: () => void;
}

export function MarkdownMode({ editor, onApplied }: MarkdownModeProps) {
  const { t } = useTranslation();
  const [source, setSource] = useState(() => editor.getMarkdown() ?? "");
  const [preview, setPreview] = useState(false);
  const [applied, setApplied] = useState(false);

  const handleApply = () => {
    editor.commands.setContent(source, { contentType: "markdown" });
    setApplied(true);
    onApplied?.();
  };

  return (
    <div>
      <Alert
        type="info"
        showIcon
        title={t("admin.editor.markdownHint")}
        style={{ margin: "8px 12px 0" }}
      />
      <div className="rl-editor-markdown-wrap" style={{ position: "relative" }}>
        {preview ? (
          <div className="rl-editor-content rl-editor-preview">
            <Suspense fallback={<Skeleton active paragraph={{ rows: 4 }} />}>
              <XMarkdown
                content={source}
                openLinksInNewTab
                dompurifyConfig={{
                  USE_PROFILES: { html: true },
                  FORBID_TAGS: ["script", "style", "iframe", "object", "embed", "form", "input"],
                  FORBID_ATTR: ["onerror", "onclick", "onload", "style"],
                }}
              />
            </Suspense>
          </div>
        ) : (
          <textarea
            className="rl-editor-markdown"
            value={source}
            onChange={(e) => {
              setSource(e.target.value);
              setApplied(false);
            }}
            placeholder={t("admin.editor.markdownPlaceholder")}
            aria-label={t("admin.editor.markdown")}
          />
        )}
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          padding: "8px 12px",
          borderTop: "1px solid var(--ant-color-split, rgba(5,5,5,0.06))",
        }}
      >
        <Space>
          <Button
            size="small"
            icon={preview ? <EditOutlined /> : <EyeOutlined />}
            onClick={() => setPreview((p) => !p)}
          >
            {preview ? t("admin.editor.markdownEdit") : t("admin.editor.markdownPreview")}
          </Button>
          <Button
            size="small"
            type="primary"
            icon={<CheckOutlined />}
            onClick={handleApply}
          >
            {applied ? t("admin.editor.markdownApplied") : t("admin.editor.markdownApply")}
          </Button>
        </Space>
      </div>
    </div>
  );
}
