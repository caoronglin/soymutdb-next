/**
 * RichEditor toolbar (E1) — AntD Button + Tooltip + Divider assembled.
 *
 * Covers: inline marks, headings, lists, table, image, link, undo/redo,
 * DOCX import, "Paste as Markdown" and source-mode toggle. The BubbleMenu
 * (selection formatting) renders inside this toolbar component but is
 * positioned by TipTap over the selection.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Divider, Input, Modal, Tooltip, Upload } from "../../lib/antd";
import type { Editor } from "@tiptap/react";
import { BubbleMenu } from "@tiptap/react/menus";
// Type-only imports: pull in each extension's `declare module '@tiptap/core'`
// command augmentation (bold/italic/heading/table/image/link) so the
// chained commands below are typed. They compile to zero runtime imports.
import type {} from "@tiptap/starter-kit";
import type {} from "@tiptap/extension-table";
import type {} from "@tiptap/extension-image";
import type {} from "@tiptap/extension-link";
import {
  BoldOutlined,
  ItalicOutlined,
  StrikethroughOutlined,
  UndoOutlined,
  RedoOutlined,
  OrderedListOutlined,
  UnorderedListOutlined,
  TableOutlined,
  PictureOutlined,
  LinkOutlined,
  FileWordOutlined,
  FileMarkdownOutlined,
  CodeOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import FileUpload from "../file-upload";
import { docxToHtml } from "./docx-import";

interface ToolbarProps {
  editor: Editor;
  /** Called after DOCX import set the content. */
  onDocxImported?: () => void;
  /** Called after "paste as markdown" set the content. */
  onMarkdownPasted?: () => void;
  /** Switch to Markdown source mode (Tabs). */
  onSourceMode?: () => void;
}

export function Toolbar({ editor, onDocxImported, onMarkdownPasted, onSourceMode }: ToolbarProps) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [imageModalOpen, setImageModalOpen] = useState(false);
  const [linkModalOpen, setLinkModalOpen] = useState(false);
  const [imageUrl, setImageUrl] = useState("");
  const [linkUrl, setLinkUrl] = useState(() =>
    editor.isActive("link") ? (editor.getAttributes("link").href as string) ?? "" : "",
  );

  const handleImageInsert = () => {
    const url = imageUrl.trim();
    if (!url) return;
    editor.chain().focus().setImage({ src: url }).run();
    setImageUrl("");
    setImageModalOpen(false);
  };

  const handleLinkSet = () => {
    const url = linkUrl.trim();
    if (!url) return;
    editor.chain().focus().extendMarkRange("link").setLink({ href: url, rel: "noopener noreferrer", target: "_blank" }).run();
    setLinkModalOpen(false);
  };

  const handleLinkUnset = () => {
    editor.chain().focus().extendMarkRange("link").unsetLink().run();
    setLinkModalOpen(false);
  };

  const handleDocxFile = async (file: File) => {
    try {
      const html = await docxToHtml(file);
      editor.chain().focus().setContent(html).run();
      onDocxImported?.();
      message.success(t("admin.editor.docxImportSuccess"));
    } catch (err) {
      message.error(
        `${t("admin.editor.docxImportError")}: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
    return false; // AntD Upload — prevent auto-upload.
  };

  const handlePasteMarkdown = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (!text || text.trim().length === 0) {
        message.warning(t("admin.editor.clipboardEmpty"));
        return;
      }
      // Markdown extension parses the clipboard text as markdown (contentType
      // "markdown") — this is an explicit action, no transformPasted hooking.
      editor.chain().focus().setContent(text, { contentType: "markdown" }).run();
      onMarkdownPasted?.();
      message.success(t("admin.editor.markdownPasteSuccess"));
    } catch {
      message.error(t("admin.editor.clipboardError"));
    }
  };

  return (
    <div className="rl-editor-toolbar" role="toolbar" aria-label={t("admin.editor.toolbar")}>
      <BubbleMenu editor={editor} shouldShow={({ editor: e, state }) => !e.isActive("link") && !state.selection.empty}>
        <div className="rl-editor-toolbar" style={{ border: "1px solid var(--ant-color-border, #d9d9d9)", boxShadow: "var(--ant-box-shadow, 0 2px 8px rgba(0,0,0,0.12))" }}>
          <Tooltip title={t("admin.editor.bold")}>
            <Button type="text" size="small" icon={<BoldOutlined />} onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().toggleBold().run()} />
          </Tooltip>
          <Tooltip title={t("admin.editor.italic")}>
            <Button type="text" size="small" icon={<ItalicOutlined />} onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().toggleItalic().run()} />
          </Tooltip>
          <Tooltip title={t("admin.editor.strike")}>
            <Button type="text" size="small" icon={<StrikethroughOutlined />} onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().toggleStrike().run()} />
          </Tooltip>
          <Divider type="vertical" />
          <Tooltip title={t("admin.editor.heading1")}>
            <Button type="text" size="small" onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}>
              H1
            </Button>
          </Tooltip>
          <Tooltip title={t("admin.editor.heading2")}>
            <Button type="text" size="small" onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}>
              H2
            </Button>
          </Tooltip>
          <Tooltip title={t("admin.editor.heading3")}>
            <Button type="text" size="small" onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}>
              H3
            </Button>
          </Tooltip>
          <Divider type="vertical" />
          <Tooltip title={t("admin.editor.bulletList")}>
            <Button type="text" size="small" icon={<UnorderedListOutlined />} onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().toggleBulletList().run()} />
          </Tooltip>
          <Tooltip title={t("admin.editor.orderedList")}>
            <Button type="text" size="small" icon={<OrderedListOutlined />} onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().toggleOrderedList().run()} />
          </Tooltip>
        </div>
      </BubbleMenu>

      <Tooltip title={t("admin.editor.bold")}>
        <Button type="text" size="small" icon={<BoldOutlined />} onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().toggleBold().run()} />
      </Tooltip>
      <Tooltip title={t("admin.editor.italic")}>
        <Button type="text" size="small" icon={<ItalicOutlined />} onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().toggleItalic().run()} />
      </Tooltip>
      <Tooltip title={t("admin.editor.strike")}>
        <Button type="text" size="small" icon={<StrikethroughOutlined />} onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().toggleStrike().run()} />
      </Tooltip>
      <Divider type="vertical" />
      <Tooltip title={t("admin.editor.heading1")}>
        <Button type="text" size="small" onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}>
          H1
        </Button>
      </Tooltip>
      <Tooltip title={t("admin.editor.heading2")}>
        <Button type="text" size="small" onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}>
          H2
        </Button>
      </Tooltip>
      <Tooltip title={t("admin.editor.heading3")}>
        <Button type="text" size="small" onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}>
          H3
        </Button>
      </Tooltip>
      <Divider type="vertical" />
      <Tooltip title={t("admin.editor.bulletList")}>
        <Button type="text" size="small" icon={<UnorderedListOutlined />} onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().toggleBulletList().run()} />
      </Tooltip>
      <Tooltip title={t("admin.editor.orderedList")}>
        <Button type="text" size="small" icon={<OrderedListOutlined />} onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().toggleOrderedList().run()} />
      </Tooltip>
      <Divider type="vertical" />
      <Tooltip title={t("admin.editor.table")}>
        <Button type="text" size="small" icon={<TableOutlined />} onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()} />
      </Tooltip>
      <Tooltip title={t("admin.editor.image")}>
        <Button type="text" size="small" icon={<PictureOutlined />} onMouseDown={(e) => e.preventDefault()} onClick={() => setImageModalOpen(true)} />
      </Tooltip>
      <Tooltip title={t("admin.editor.link")}>
        <Button type="text" size="small" icon={<LinkOutlined />} onMouseDown={(e) => e.preventDefault()} onClick={() => setLinkModalOpen(true)} />
      </Tooltip>
      <Divider type="vertical" />
      <Tooltip title={t("admin.editor.undo")}>
        <Button type="text" size="small" icon={<UndoOutlined />} disabled={!editor.can().chain().focus().undo().run()} onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().undo().run()} />
      </Tooltip>
      <Tooltip title={t("admin.editor.redo")}>
        <Button type="text" size="small" icon={<RedoOutlined />} disabled={!editor.can().chain().focus().redo().run()} onMouseDown={(e) => e.preventDefault()} onClick={() => editor.chain().focus().redo().run()} />
      </Tooltip>
      <Divider type="vertical" />
      <Tooltip title={t("admin.editor.pasteMarkdown")}>
        <Button type="text" size="small" icon={<FileMarkdownOutlined />} onClick={handlePasteMarkdown} />
      </Tooltip>
      <Tooltip title={t("admin.editor.sourceMode")}>
        <Button type="text" size="small" icon={<CodeOutlined />} onClick={() => onSourceMode?.()} />
      </Tooltip>
      <Upload
        accept=".docx"
        showUploadList={false}
        beforeUpload={handleDocxFile}
      >
        <Tooltip title={t("admin.editor.importDocx")}>
          <Button type="text" size="small" icon={<FileWordOutlined />} />
        </Tooltip>
      </Upload>

      {/* Image URL dialog (D4 file-upload reuse for direct upload) */}
      <Modal
        title={t("admin.editor.image")}
        open={imageModalOpen}
        onOk={handleImageInsert}
        onCancel={() => setImageModalOpen(false)}
        okButtonProps={{ disabled: !imageUrl.trim() }}
        width={480}
      >
        <Input
          placeholder={t("admin.editor.imagePlaceholder")}
          value={imageUrl}
          onChange={(e) => setImageUrl(e.target.value)}
          onPressEnter={handleImageInsert}
          style={{ marginBottom: 8 }}
        />
        <FileUpload
          purpose="news"
          maxSizeMB={10}
          accept="image/*"
          maxCount={1}
          buttonText={t("admin.editor.imageUpload")}
          value={imageUrl}
          onChange={(url) => {
            if (typeof url === "string") setImageUrl(url);
          }}
        />
      </Modal>

      {/* Link dialog */}
      <Modal
        title={t("admin.editor.link")}
        open={linkModalOpen}
        onOk={handleLinkSet}
        onCancel={() => setLinkModalOpen(false)}
        okButtonProps={{ disabled: !linkUrl.trim() }}
        width={440}
      >
        <Input
          placeholder={t("admin.editor.linkPlaceholder")}
          value={linkUrl}
          onChange={(e) => setLinkUrl(e.target.value)}
          onPressEnter={handleLinkSet}
        />
        {editor.isActive("link") && (
          <Button
            danger
            type="text"
            size="small"
            icon={<DeleteOutlined />}
            onClick={handleLinkUnset}
            style={{ marginTop: 8 }}
          >
            {t("admin.editor.linkUnset")}
          </Button>
        )}
      </Modal>
    </div>
  );
}
