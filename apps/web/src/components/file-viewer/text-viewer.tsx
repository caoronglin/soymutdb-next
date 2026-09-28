/**
 * Text viewer — plain read-only text display (monospace, wraps, scrolls).
 *
 * Syntax highlighting lives in code-viewer.tsx (highlight.js, lazy chunk);
 * FASTA gets its own specialized rendering in fasta-viewer.tsx.
 */
interface TextViewerProps {
  content: string;
}

export function TextViewer({ content }: TextViewerProps) {
  return (
    <div className="overflow-auto rounded-md border bg-[var(--background)]">
      <pre
        className="p-4"
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: "0.8rem",
          lineHeight: 1.6,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {content}
      </pre>
    </div>
  );
}
