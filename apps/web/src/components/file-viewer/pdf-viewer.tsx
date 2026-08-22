/**
 * PDF viewer — pdfjs-dist loaded lazily (own chunk, not in the entry bundle).
 *
 * Renders every page into stacked canvases with a scale control
 * (fit-width / 75% / 100% / 125% / 150%). pdf.js is instructed to stream
 * from the URL directly so big documents do not require a full fetch.
 */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Skeleton } from "@/lib/antd";
import { Minus, Plus } from "lucide-react";
import type { PDFDocumentProxy } from "pdfjs-dist";

interface PdfViewerProps {
  url: string;
}

type PdfState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; doc: PDFDocumentProxy };

const SCALES = [0.75, 1, 1.25, 1.5];
const MAX_PAGES = 200;

export function PdfViewer({ url }: PdfViewerProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<PdfState>({ status: "loading" });
  const [scaleIndex, setScaleIndex] = useState(0); // index into SCALES (1 = 100%)
  const [fitWidth, setFitWidth] = useState(true);

  // Load the library + document once per URL.
  useEffect(() => {
    let disposed = false;
    let doc: PDFDocumentProxy | null = null;

    setState({ status: "loading" });

    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        const workerUrl = (await import("pdfjs-dist/build/pdf.worker.min.mjs?url")).default;
        if (disposed) return;
        pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

        const loadingTask = pdfjs.getDocument({ url });
        doc = await loadingTask.promise;
        if (disposed) {
          void doc.destroy();
          return;
        }
        setState({ status: "ready", doc });
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
      if (doc) void doc.destroy();
    };
  }, [url]);

  // Render pages into canvases whenever the doc or scale changes.
  useEffect(() => {
    if (state.status !== "ready" || !containerRef.current) return;

    const container = containerRef.current;
    const doc = state.doc;
    let cancelled = false;

    const scale = fitWidth ? null : SCALES[scaleIndex] ?? 1;

    (async () => {
      container.replaceChildren();
      const pageCount = Math.min(doc.numPages, MAX_PAGES);
      const usableWidth = container.clientWidth - 32;

      for (let i = 1; i <= pageCount; i++) {
        if (cancelled) return;
        const page = await doc.getPage(i);
        if (cancelled) return;

        let viewport = page.getViewport({ scale: 1 });
        const effectiveScale = scale ?? usableWidth / viewport.width;
        viewport = page.getViewport({ scale: Math.max(effectiveScale, 0.1) });

        const canvas = document.createElement("canvas");
        canvas.className = "rl-pdf-page";
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;

        const wrapper = document.createElement("div");
        wrapper.className = "rl-pdf-page-wrap";
        wrapper.appendChild(canvas);
        container.appendChild(wrapper);

        const ctx = canvas.getContext("2d");
        if (!ctx) continue;
        await page.render({ canvasContext: ctx, viewport }).promise;
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [state, scaleIndex, fitWidth]);

  if (state.status === "error") {
    return (
      <div className="rl-preview-empty">
        <p>{t("fileViewer.pdfLoadFailed")}</p>
        <p className="rl-preview-empty-sub">{state.message}</p>
      </div>
    );
  }

  if (state.status === "loading") {
    return (
      <div className="space-y-3 p-4">
        <Skeleton active paragraph={{ rows: 4 }} />
        <p className="text-center text-xs text-muted-foreground">
          {t("downloads.loading_preview")}
        </p>
      </div>
    );
  }

  const tooMany = state.doc.numPages > MAX_PAGES;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground">
        <span>
          {t("fileViewer.pages", { count: Math.min(state.doc.numPages, MAX_PAGES) })}
          {tooMany ? ` (${state.doc.numPages})` : ""}
        </span>
        <span className="mx-1 opacity-40">|</span>
        <Button
          size="small"
          type={fitWidth ? "primary" : "default"}
          onClick={() => setFitWidth(true)}
        >
          {t("fileViewer.fitWidth")}
        </Button>
        {SCALES.map((s, idx) => (
          <Button
            key={s}
            size="small"
            type={!fitWidth && scaleIndex === idx ? "primary" : "default"}
            onClick={() => {
              setScaleIndex(idx);
              setFitWidth(false);
            }}
          >
            {Math.round(s * 100)}%
          </Button>
        ))}
        <span className="mx-1 opacity-40">|</span>
        <Button
          size="small"
          icon={<Minus className="size-3.5" />}
          disabled={fitWidth || scaleIndex === 0}
          onClick={() => setScaleIndex((i) => Math.max(0, i - 1))}
        />
        <Button
          size="small"
          icon={<Plus className="size-3.5" />}
          disabled={fitWidth || scaleIndex === SCALES.length - 1}
          onClick={() => setScaleIndex((i) => Math.min(SCALES.length - 1, i + 1))}
        />
      </div>
      {tooMany && (
        <p className="text-xs text-muted-foreground">
          {t("fileViewer.tooManyPages")}
        </p>
      )}
      <div
        ref={containerRef}
        className="rl-pdf-scroll overflow-auto rounded-md border bg-[var(--background)] p-4"
      />
    </div>
  );
}
