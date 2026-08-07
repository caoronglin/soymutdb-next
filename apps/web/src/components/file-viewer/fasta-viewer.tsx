/**
 * Specialized FASTA viewer — header lines (>...) bold, sequence wrapped at 60 chars.
 */
import { useMemo } from "react";

interface FastaViewerProps {
  content: string;
}

type LineItem =
  | { type: "header"; text: string }
  | { type: "sequence"; text: string }
  | { type: "empty"; text: string };

export function FastaViewer({ content }: FastaViewerProps) {
  const lines: LineItem[] = useMemo(() => {
    const result: LineItem[] = [];
    const splitLines = content.split("\n");
    for (const line of splitLines) {
      if (line.startsWith(">")) {
        result.push({ type: "header", text: line });
      } else {
        // Sequence line — wrap at 60 characters.
        let wrapped = false;
        for (let i = 0; i < line.length; i += 60) {
          result.push({ type: "sequence", text: line.slice(i, i + 60) });
          wrapped = true;
        }
        if (!wrapped) {
          result.push({ type: "empty", text: "" });
        }
      }
    }
    return result;
  }, [content]);

  return (
    <div className="overflow-auto rounded-md border bg-black/5 p-4 font-mono text-xs leading-relaxed dark:bg-white/5">
      {lines.map((line, idx) => {
        if (line.type === "header") {
          return (
            <div key={idx} className="font-bold text-primary">
              {line.text}
            </div>
          );
        }
        if (line.type === "empty") {
          return <div key={idx}>&nbsp;</div>;
        }
        return (
          <div key={idx} className="text-foreground">
            <span className="mr-4 select-none text-muted-foreground">{idx + 1}</span>
            {line.text}
          </div>
        );
      })}
    </div>
  );
}
