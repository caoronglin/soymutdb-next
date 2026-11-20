/**
 * RichEditor core (E1) — TipTap v3 editor instance + Tabs surface.
 *
 * Contract (frozen in docs/design/static-content-richtext-2026-08.md §3):
 * - Controlled via `value: string` (HTML) + `onChange(html)`; the parent
 *   never writes back — the editor syncs external value changes itself and
 *   guards the loop with a lastEmitted ref.
 * - Markdown is an explicit import/export/apply surface (Tabs), guarded by
 *   a confirmation on switch; no lossless HTML/MD round-trip is promised.
 * - `immediatelyRender: false` + idempotent onCreate/onUpdate (React 19
 *   StrictMode). No FloatingMenu, no NodeView extensions.
 */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Tabs } from "../../lib/antd";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
// v3: table row/header/cell live in @tiptap/extension-table (the dedicated
// table-row/header/cell packages re-export from it).
import { Table, TableRow, TableHeader, TableCell } from "@tiptap/extension-table";
import Image from "@tiptap/extension-image";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";
import { Markdown } from "@tiptap/markdown";
import { Toolbar } from "./toolbar";
import { MarkdownMode } from "./markdown-mode";
import "./rich-editor.css";

export interface TiptapEditorProps {
  /** Initial / controlled HTML content. */
  value?: string;
  /** Emitted on every editor change (HTML). Parent should NOT write back. */
  onChange?: (html: string) => void;
  /** Placeholder shown when the document is empty. */
  placeholder?: string;
}

export function TiptapEditor({ value, onChange, placeholder }: TiptapEditorProps) {
  const { t } = useTranslation();
  const { modal } = App.useApp();
  const [tab, setTab] = useState<"richtext" | "markdown">("richtext");
  // Guards the controlled loop: last HTML we emitted via onChange. If the
  // parent echoes the same value back we must not re-run setContent.
  const lastEmittedRef = useRef<string | undefined>(undefined);

  const editor = useEditor({
    immediatelyRender: false,
    extensions: [
      StarterKit.configure({
        // Link is registered explicitly below with noopener rel.
        link: false,
      }),
      Table.configure({ resizable: false }),
      TableRow,
      TableHeader,
      TableCell,
      // External images only (allowBase64: false) — matches the server-side
      // upload validation story (E2).
      Image.configure({ allowBase64: false }),
      Link.configure({
        openOnClick: false,
        autolink: true,
        linkOnPaste: true,
        HTMLAttributes: {
          rel: "noopener noreferrer",
          target: "_blank",
        },
      }),
      Placeholder.configure({
        placeholder: placeholder ?? t("admin.editor.placeholder"),
      }),
      // Markdown import/export + explicit setContent({ contentType }) —
      // no transformPasted hooking.
      Markdown,
    ],
    content: value ?? "",
    onCreate: () => {
      // Idempotent no-op — StrictMode double-invokes effects; the editor
      // instance is created once and content is set at construction.
      lastEmittedRef.current = value;
    },
    onUpdate: ({ editor: e }) => {
      const html = e.getHTML();
      lastEmittedRef.current = html;
      onChange?.(html);
    },
  });

  // External value sync — only when the value differs from the current
  // document AND is not our own echo (lastEmitted). This keeps the editor
  // controlled without cursor jumps while editing.
  useEffect(() => {
    if (!editor) return;
    const current = editor.getHTML();
    const next = value ?? "";
    if (current === next) return;
    if (lastEmittedRef.current === value) return;
    lastEmittedRef.current = value;
    editor.commands.setContent(next);
  }, [editor, value]);

  if (!editor) {
    // immediatelyRender: false — first render has no editor instance yet.
    return null;
  }

  const handleTabChange = (key: string) => {
    if (key === "markdown") {
      modal.confirm({
        title: t("admin.editor.overwriteConfirmTitle"),
        content: t("admin.editor.overwriteConfirmContent"),
        okText: t("admin.editor.overwriteConfirmOk"),
        cancelText: t("admin.editor.cancel"),
        onOk: () => setTab("markdown"),
      });
      return;
    }
    setTab("richtext");
  };

  return (
    <div className="rl-editor">
      <Tabs
        size="small"
        activeKey={tab}
        onChange={handleTabChange}
        items={[
          {
            key: "richtext",
            label: t("admin.editor.tabRichtext"),
            children: (
              <>
                <Toolbar
                  editor={editor}
                  onSourceMode={() => handleTabChange("markdown")}
                />
                <EditorContent editor={editor} className="rl-editor-content" />
              </>
            ),
          },
          {
            key: "markdown",
            label: t("admin.editor.tabMarkdown"),
            children: <MarkdownMode editor={editor} />,
          },
        ]}
      />
    </div>
  );
}
