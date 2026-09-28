/**
 * RichEditor public component (E1) — lazy TipTap wrapper.
 *
 * Contract (frozen in docs/design/static-content-richtext-2026-08.md §3):
 * - Only exposes `value: string` (HTML) + `onChange(html: string)` to the
 *   form layer; markdown stays an internal state.
 * - Loads the TipTap chunk lazily (Suspense → AntD Skeleton), so the admin
 *   main bundle never contains tiptap/prosemirror.
 */
import { lazy, Suspense } from "react";
import { Skeleton } from "../../lib/antd";

export interface RichEditorProps {
  /** Controlled HTML content. */
  value?: string;
  /** Emitted on every editor change. Parent must NOT write back. */
  onChange?: (html: string) => void;
  /** Placeholder shown when the document is empty. */
  placeholder?: string;
}

const TiptapEditor = lazy(() =>
  import("./tiptap-editor").then((m) => ({ default: m.TiptapEditor })),
);

export function RichEditor(props: RichEditorProps) {
  return (
    <Suspense
      fallback={
        <div style={{ border: "1px solid var(--ant-color-border, #d9d9d9)", borderRadius: 8, padding: 16 }}>
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      }
    >
      <TiptapEditor {...props} />
    </Suspense>
  );
}

export default RichEditor;
