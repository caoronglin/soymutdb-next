/**
 * FilePreviewDialog — unified preview container for the downloads page.
 *
 * Architecture modeled on Open File Viewer's unified container:
 * - single dialog, per-kind renderer picked from a format matrix (format.ts)
 * - multi-file switching (prev/next arrows + file list dropdown)
 * - fullscreen mode (AntD Modal `fullscreen`), print (current document),
 *   theme-following surface (CSS variables driven by [data-theme])
 *
 * Lazy chunks: pdfjs-dist (pdf), mammoth (docx), marked (markdown),
 * highlight.js (code). None of them land in the entry bundle.
 *
 * Text-ish kinds are truncated at 1 MB for files > 10 MB (same policy as the
 * legacy dialog). PDF streams from the URL via pdf.js (no full fetch).
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Dropdown, Modal, Skeleton, Tag, Tooltip, type MenuProps } from "@/lib/antd";
import {
  LeftOutlined,
  RightOutlined,
  DownloadOutlined,
  ExpandOutlined,
  CompressOutlined,
  PrinterOutlined,
  FileTextOutlined,
} from "@ant-design/icons";
import {
  formatFileSize,
  getFileExtension,
  getFileKind,
  getHighlightLanguage,
  isTextKind,
  type FileKind,
} from "./format";
import { TextViewer } from "./text-viewer";
import { FastaViewer } from "./fasta-viewer";
import { CsvViewer } from "./csv-viewer";
import { ImageViewer } from "./image-viewer";
import { PdfViewer } from "./pdf-viewer";
import { DocxViewer } from "./docx-viewer";
import { MarkdownViewer } from "./markdown-viewer";
import { CodeViewer } from "./code-viewer";

const MAX_FULL_SIZE = 10 * 1024 * 1024; // 10 MB — full content
const TRUNCATED_SIZE = 1024 * 1024; // 1 MB — first chunk for large files

export interface PreviewFile {
  name: string;
  url: string;
  size: number;
  /** Optional display badge (e.g. "VCF.GZ"); falls back to the extension. */
  format?: string;
}

export interface FilePreviewDialogProps {
  /** Files available for switching (typically the same download group). */
  files: PreviewFile[];
  /** Index into `files` to open first (default 0). */
  initialIndex?: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type TextState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; content: string; truncated: boolean };

/** Print styles injected while the dialog is mounted. */
const PRINT_STYLES = `
@media print {
  body.rl-preview-printing > :not(.ant-modal-root) { display: none !important; }
  body.rl-preview-printing .ant-modal-mask,
  body.rl-preview-printing .ant-modal-close,
  body.rl-preview-printing .rl-preview-toolbar,
  body.rl-preview-printing .rl-preview-nav { display: none !important; }
  body.rl-preview-printing .ant-modal-wrap { position: static !important; inset: auto !important; }
  body.rl-preview-printing .ant-modal { position: static !important; margin: 0 !important; max-width: 100% !important; }
  body.rl-preview-printing .ant-modal-content { box-shadow: none !important; border: 0 !important; padding: 0 !important; }
  body.rl-preview-printing .rl-preview-body { max-height: none !important; overflow: visible !important; }
}
`;

/** Fullscreen mode styles (AntD 5.x has no `fullscreen` prop on Modal). */
const FULLSCREEN_STYLES = `
.rl-preview-modal-fullscreen .ant-modal {
  top: 0 !important;
  max-width: 100vw !important;
  padding-bottom: 0 !important;
  margin: 0 !important;
}
.rl-preview-modal-fullscreen .ant-modal-content {
  height: 100vh !important;
  max-height: 100vh !important;
  border-radius: 0 !important;
}
.rl-preview-modal-fullscreen .rl-preview-body { max-height: none !important; }
`;

export function FilePreviewDialog({
  files,
  initialIndex = 0,
  open,
  onOpenChange,
}: FilePreviewDialogProps) {
  const { t } = useTranslation();
  const [currentIndex, setCurrentIndex] = useState(() => clampIndex(initialIndex, files.length));
  const [fullscreen, setFullscreen] = useState(false);
  const [textState, setTextState] = useState<TextState>({ status: "loading" });

  // Reset to the requested index every time the dialog opens.
  useEffect(() => {
    if (open) setCurrentIndex(clampIndex(initialIndex, files.length));
  }, [open, initialIndex, files.length]);

  const current = files[currentIndex] ?? files[0];
  const kind: FileKind = current ? getFileKind(current.name) : "text";

  // Fetch text-ish content (csv/fasta/md/code/text) with truncation.
  useEffect(() => {
    if (!open || !current || !isTextKind(kind)) return;

    let disposed = false;
    const controller = new AbortController();
    setTextState({ status: "loading" });

    // A missing size is untrusted metadata: sample it rather than risking an
    // unbounded text decode in the browser.
    const fetchSize =
      current.size <= 0 || current.size > MAX_FULL_SIZE
        ? TRUNCATED_SIZE
        : undefined;

    fetch(current.url, { signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        let text: string;
        let truncated = false;
        if (fetchSize) {
          if (!res.body) throw new Error("The server did not provide a readable stream");
          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let result = "";
          let receivedBytes = 0;
          while (true) {
            const { done, value } = await reader.read();
            if (done) {
              result += decoder.decode();
              break;
            }
            receivedBytes += value.byteLength;
            result += decoder.decode(value, { stream: true });
            if (receivedBytes >= fetchSize) {
              truncated = true;
              await reader.cancel();
              break;
            }
          }
          text = result;
        } else {
          text = await res.text();
        }

        if (disposed) return;
        setTextState({
          status: "ready",
          content: text,
          truncated,
        });
      })
      .catch((err) => {
        if (disposed || err.name === "AbortError") return;
        setTextState({
          status: "error",
          message: err instanceof Error ? err.message : "Failed to load file",
        });
      });

    return () => {
      disposed = true;
      controller.abort();
    };
    // `current` is read only through its url/size fields below, so those
    // (not the object identity) are the real dependencies; depending on the
    // object would re-fetch on every parent re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, current?.url, current?.size, kind]);

  const goTo = useCallback(
    (index: number) => {
      setCurrentIndex(clampIndex(index, files.length));
    },
    [files.length],
  );

  const handlePrint = useCallback(() => {
    document.body.classList.add("rl-preview-printing");
    const cleanup = () => {
      document.body.classList.remove("rl-preview-printing");
      window.removeEventListener("afterprint", cleanup);
    };
    window.addEventListener("afterprint", cleanup);
    // print() blocks until the dialog closes; remove the class right after.
    setTimeout(() => {
      window.print();
      cleanup();
    }, 0);
  }, []);

  if (!current) return null;

  const menuItems: MenuProps["items"] = files.map((f, idx) => ({
    key: String(idx),
    label: f.name,
    icon: idx === currentIndex ? <FileTextOutlined className="size-3.5" /> : undefined,
  }));

  const renderBody = () => {
    switch (kind) {
      case "image":
        return <ImageViewer url={current.url} alt={current.name} />;
      case "pdf":
        return <PdfViewer url={current.url} />;
      case "docx":
        return <DocxViewer url={current.url} />;
      case "csv":
        if (textState.status === "loading") return <LoadingSkeleton />;
        if (textState.status === "error") return <ErrorState message={textState.message} />;
        return (
          <CsvViewer
            content={textState.content}
            delimiter={getFileExtension(current.name) === "tsv" ? "\t" : ","}
          />
        );
      case "fasta":
        if (textState.status === "loading") return <LoadingSkeleton />;
        if (textState.status === "error") return <ErrorState message={textState.message} />;
        return <FastaViewer content={textState.content} />;
      case "markdown":
        if (textState.status === "loading") return <LoadingSkeleton />;
        if (textState.status === "error") return <ErrorState message={textState.message} />;
        return <MarkdownViewer content={textState.content} />;
      case "binary":
        return <DownloadOnlyState url={current.url} name={current.name} />;
      case "code": {
        if (textState.status === "loading") return <LoadingSkeleton />;
        if (textState.status === "error") return <ErrorState message={textState.message} />;
        const language = getHighlightLanguage(current.name) ?? "plaintext";
        return <CodeViewer content={textState.content} language={language} />;
      }
      default:
        if (textState.status === "loading") return <LoadingSkeleton />;
        if (textState.status === "error") return <ErrorState message={textState.message} />;
        return <TextViewer content={textState.content} />;
    }
  };

  const hasMultiple = files.length > 1;
  const canPrev = currentIndex > 0;
  const canNext = currentIndex < files.length - 1;

  return (
    <Modal
      open={open}
      onCancel={() => onOpenChange(false)}
      footer={null}
      width={fullscreen ? "100vw" : 1024}
      destroyOnHidden
      className={fullscreen ? "rl-preview-modal-fullscreen" : undefined}
      styles={{
        container: {
          background: "var(--card)",
          color: "var(--foreground)",
          padding: 0,
          display: "flex",
          flexDirection: "column",
          maxHeight: "92vh",
        },
        body: { padding: 0, overflow: "hidden" },
      }}
      title={
        <div className="rl-preview-header flex items-center gap-2 pr-10">
          <span
            className="flex-1 truncate font-mono text-sm"
            title={current.name}
          >
            {current.name}
          </span>
          <Tag bordered={false} className="font-mono text-[10px]">
            {(current.format ?? getFileExtension(current.name)).toUpperCase()}
          </Tag>
          <span className="whitespace-nowrap text-xs text-muted-foreground">
            {formatFileSize(current.size)}
          </span>
        </div>
      }
    >
      <style>{PRINT_STYLES}</style>
      {fullscreen && <style>{FULLSCREEN_STYLES}</style>}
      <div className="rl-preview flex flex-col" style={{ height: "100%" }}>
        {/* Toolbar: nav / files dropdown / actions */}
        <div className="rl-preview-toolbar flex items-center gap-1 border-b px-3 py-1.5">
          <div className="rl-preview-nav flex items-center gap-1">
            <Tooltip title={t("fileViewer.previous")}>
              <Button
                type="text"
                size="small"
                disabled={!canPrev}
                icon={<LeftOutlined className="size-4" />}
                onClick={() => goTo(currentIndex - 1)}
              />
            </Tooltip>
            {hasMultiple ? (
              <Dropdown
                menu={{
                  items: menuItems,
                  selectedKeys: [String(currentIndex)],
                  onClick: ({ key }) => goTo(Number(key)),
                }}
                trigger={["click"]}
              >
                <Button type="text" size="small" className="font-mono text-xs">
                  {currentIndex + 1} / {files.length}
                </Button>
              </Dropdown>
            ) : (
              <span className="px-1 text-xs text-muted-foreground">
                {t("fileViewer.singleFile")}
              </span>
            )}
            <Tooltip title={t("fileViewer.next")}>
              <Button
                type="text"
                size="small"
                disabled={!canNext}
                icon={<RightOutlined className="size-4" />}
                onClick={() => goTo(currentIndex + 1)}
              />
            </Tooltip>
          </div>

          <span className="mx-1 h-4 w-px bg-[var(--border)]" />

          <div className="ml-auto flex items-center gap-1">
            {isTextKind(kind) && textState.status === "ready" && textState.truncated && (
              <span className="hidden text-xs text-muted-foreground sm:inline">
                {t("downloads.showing_partial")}
              </span>
            )}
            <Tooltip title={t("downloads.download")}>
              <Button
                type="text"
                size="small"
                icon={<DownloadOutlined className="size-4" />}
                onClick={() => window.open(current.url, "_blank", "noopener,noreferrer")}
              />
            </Tooltip>
            <Tooltip title={t("fileViewer.print")}>
              <Button
                type="text"
                size="small"
                icon={<PrinterOutlined className="size-4" />}
                onClick={handlePrint}
              />
            </Tooltip>
            <Tooltip
              title={fullscreen ? t("fileViewer.exitFullscreen") : t("fileViewer.fullscreen")}
            >
              <Button
                type="text"
                size="small"
                icon={fullscreen ? <CompressOutlined className="size-4" /> : <ExpandOutlined className="size-4" />}
                onClick={() => setFullscreen((f) => !f)}
              />
            </Tooltip>
          </div>
        </div>

        {/* Body */}
        <div className="rl-preview-body flex-1 overflow-auto p-4">{renderBody()}</div>
      </div>
    </Modal>
  );
}

function clampIndex(index: number, length: number): number {
  if (length <= 0) return 0;
  return Math.min(Math.max(index, 0), length - 1);
}

function LoadingSkeleton() {
  return (
    <div className="space-y-3 p-4">
      <Skeleton className="h-4 w-3/4" active paragraph={{ rows: 0 }} />
      <Skeleton active paragraph={{ rows: 4 }} />
    </div>
  );
}

function DownloadOnlyState({ url, name }: { url: string; name: string }) {
  const { t } = useTranslation();
  return (
    <div className="rl-preview-empty">
      <p>{t("fileViewer.downloadOnly", { defaultValue: "Download-only preview" })}</p>
      <p className="rl-preview-empty-sub">
        {t("fileViewer.downloadOnlyHint", {
          defaultValue: "This compressed, unknown, or binary format is not decoded in the browser.",
        })}
      </p>
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="link-underline text-sm text-primary hover:text-primary/80"
      >
        {t("downloads.download")}: {name}
      </a>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  const { t } = useTranslation();
  return (
    <div className="rl-preview-empty">
      <p>{t("fileViewer.loadFailed")}</p>
      <p className="rl-preview-empty-sub">{message}</p>
    </div>
  );
}
