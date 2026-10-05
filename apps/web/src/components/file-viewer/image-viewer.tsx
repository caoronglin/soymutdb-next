/**
 * Image viewer — displays PNG/JPG/SVG files in a contained frame.
 */
import { useTranslation } from "react-i18next";
interface ImageViewerProps {
  url: string;
  /** Optional alt text. */
  alt?: string;
}

export function ImageViewer({ url, alt }: ImageViewerProps) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-center rounded-md border bg-black/5 p-4 dark:bg-white/5">
      <img
        src={url}
        alt={alt ?? t("fileViewer.title")}
        className="max-h-[70vh] max-w-full rounded object-contain"
      />
    </div>
  );
}
