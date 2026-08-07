/**
 * File viewer dialog — fetches and displays file content with format-specific rendering.
 *
 * - Files ≤ 10MB: full content fetched
 * - Files > 10MB: first 1MB fetched with truncation banner
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Download } from "lucide-react";
import { Button, Dialog, DialogContent, DialogHeader, DialogTitle, Skeleton } from "@soymutdb/ui";
import { FadeUp } from "../route-motion";
import { TextViewer } from "./text-viewer";
import { FastaViewer } from "./fasta-viewer";
import { CsvViewer } from "./csv-viewer";
import { ImageViewer } from "./image-viewer";

const MAX_FULL_SIZE = 10 * 1024 * 1024; // 10 MB
const TRUNCATED_SIZE = 1024 * 1024; // 1 MB

interface FileViewerProps {
  /** The file metadata. */
  file: {
    name: string;
    url: string;
    size: number;
    format: string;
  };
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type ViewerState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; content: string; truncated: boolean };

function getFileExtension(name: string): string {
  const parts = name.toLowerCase().split(".");
  if (parts.length < 2) return "txt";
  // Handle .gz, .bz2, .zip
  const last = parts[parts.length - 1];
  if (last === "gz" || last === "bz2" || last === "zip") {
    return parts.length > 2 ? parts[parts.length - 2] : "txt";
  }
  return last;
}

export function FileViewerDialog({ file, open, onOpenChange }: FileViewerProps) {
  const { t } = useTranslation();
  const [state, setState] = useState<ViewerState>({ status: "loading" });
  const ext = getFileExtension(file.name);

  useEffect(() => {
    if (!open) return;

    setState({ status: "loading" });

    const controller = new AbortController();
    const fetchSize = file.size > MAX_FULL_SIZE ? TRUNCATED_SIZE : undefined;

    fetch(file.url, { signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        let text: string;
        if (fetchSize) {
          // Read the full response but only keep the first fetchSize bytes
          const reader = res.body?.getReader();
          const decoder = new TextDecoder();
          let result = "";
          let total = 0;

          if (reader) {
            while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              const chunk = decoder.decode(value, { stream: true });
              total += chunk.length;
              result += chunk;
              if (total >= fetchSize) {
                reader.cancel();
                break;
              }
            }
          } else {
            // Fallback: read entire response
            text = await res.text();
            result = text;
          }
          text = result;
        } else {
          text = await res.text();
        }

        setState({
          status: "ready",
          content: text.slice(0, fetchSize ?? undefined),
          truncated: file.size > MAX_FULL_SIZE,
        });
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "Failed to load file",
        });
      });

    return () => controller.abort();
  }, [file.url, file.size, open]);

  const renderContent = () => {
    switch (state.status) {
      case "loading":
        return (
          <div className="space-y-3 p-4">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-4 w-2/3" />
            <p className="text-center text-sm text-muted-foreground">
              {t("downloads.loading_preview")}
            </p>
          </div>
        );
      case "error":
        return (
          <div className="flex flex-col items-center gap-3 p-8 text-center">
            <p className="text-sm text-destructive">{state.message}</p>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.close")}
            </Button>
          </div>
        );
      case "ready": {
        const imageExts = ["png", "jpg", "jpeg", "svg", "gif", "webp"];
        const csvExts = ["csv", "tsv"];
        const fastaExts = ["fasta", "fa", "fna", "ffn", "frn"];

        return (
          <div className="space-y-3">
            {state.truncated && (
              <div className="flex items-center gap-2 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
                <span>{t("downloads.showing_partial")}</span>
                <Button
                  variant="outline"
                  size="sm"
                  className="ml-auto"
                  onClick={() => window.open(file.url, "_blank")}
                >
                  <Download className="size-3" />
                  {t("downloads.download")}
                </Button>
              </div>
            )}

            {imageExts.includes(ext) ? (
              <ImageViewer url={file.url} alt={file.name} />
            ) : fastaExts.includes(ext) ? (
              <FastaViewer content={state.content} />
            ) : csvExts.includes(ext) ? (
              <CsvViewer content={state.content} delimiter={ext === "tsv" ? "\t" : ","} />
            ) : (
              <TextViewer content={state.content} language={ext} />
            )}
          </div>
        );
      }
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-2 pr-8">
            <DialogTitle className="truncate font-mono text-sm">{file.name}</DialogTitle>
          </div>
          <p className="text-xs text-muted-foreground">
            {file.format} &middot; {formatSize(file.size)}
          </p>
        </DialogHeader>
        <FadeUp>{renderContent()}</FadeUp>
      </DialogContent>
    </Dialog>
  );
}

function formatSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const size = bytes / Math.pow(1024, i);
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}
