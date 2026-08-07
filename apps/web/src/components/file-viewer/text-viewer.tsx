/**
 * Text viewer — syntax-highlighted read-only display using react-syntax-highlighter.
 */
import { useMemo } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

interface TextViewerProps {
  content: string;
  language?: string;
}

const LANGUAGE_MAP: Record<string, string> = {
  fasta: "text",
  gff3: "text",
  vcf: "text",
  tsv: "text",
  csv: "text",
  txt: "text",
  py: "python",
  js: "javascript",
  ts: "typescript",
  json: "json",
  xml: "xml",
  yaml: "yaml",
  yml: "yaml",
  md: "markdown",
};

export function TextViewer({ content, language = "text" }: TextViewerProps) {
  const lang = useMemo(() => LANGUAGE_MAP[language] ?? "text", [language]);

  return (
    <div className="overflow-auto rounded-md border text-sm">
      <SyntaxHighlighter
        style={oneDark}
        language={lang}
        showLineNumbers
        wrapLines
        customStyle={{
          margin: 0,
          borderRadius: "0.375rem",
          fontSize: "0.8rem",
          maxHeight: "70vh",
        }}
      >
        {content}
      </SyntaxHighlighter>
    </div>
  );
}
