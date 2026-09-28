/**
 * Image viewer — displays PNG/JPG/SVG files in a contained frame.
 */
interface ImageViewerProps {
  url: string;
  /** Optional alt text. */
  alt?: string;
}

export function ImageViewer({ url, alt }: ImageViewerProps) {
  return (
    <div className="flex items-center justify-center rounded-md border bg-black/5 p-4 dark:bg-white/5">
      <img
        src={url}
        alt={alt ?? "File preview"}
        className="max-h-[70vh] max-w-full rounded object-contain"
      />
    </div>
  );
}
