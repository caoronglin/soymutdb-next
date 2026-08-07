/**
 * CSV/TSV viewer — native HTML <table> (NOT @tanstack/react-table).
 *
 * Parses with a simple split; max 100 rows shown to avoid browser strain.
 */
import { useMemo } from "react";

interface CsvViewerProps {
  content: string;
  delimiter?: string;
}

const MAX_ROWS = 100;

export function CsvViewer({ content, delimiter = "," }: CsvViewerProps) {
  const { headers, rows, totalRows, truncated } = useMemo(() => {
    const lines = content.split("\n").filter((l) => l.trim().length > 0);
    if (lines.length === 0) {
      return { headers: [], rows: [], totalRows: 0, truncated: false };
    }

    const hdrs = parseLine(lines[0], delimiter);
    const dataLines = lines.slice(1);
    const total = dataLines.length;

    const shown = dataLines.slice(0, MAX_ROWS).map((line) => parseLine(line, delimiter));
    return {
      headers: hdrs,
      rows: shown,
      totalRows: total,
      truncated: total > MAX_ROWS,
    };
  }, [content, delimiter]);

  if (headers.length === 0) {
    return (
      <div className="p-4 text-center text-sm text-muted-foreground">
        No data to display
      </div>
    );
  }

  return (
    <div>
      {truncated && (
        <div className="mb-2 rounded-md bg-muted px-3 py-1.5 text-xs text-muted-foreground">
          Showing {MAX_ROWS} of {totalRows} rows
        </div>
      )}
      <div className="overflow-auto max-h-96 rounded-md border">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-background">
            <tr className="border-b">
              {headers.map((h, i) => (
                <th key={i} className="px-3 py-2 font-semibold text-muted-foreground">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} className="border-b last:border-0 hover:bg-accent/30">
                {row.map((cell, ci) => (
                  <td key={ci} className="px-3 py-1.5 font-mono">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function parseLine(line: string, delimiter: string): string[] {
  const result: string[] = [];
  let current = "";
  let inQuotes = false;

  for (let i = 0; i < line.length; i++) {
    const char = line[i];
    if (char === '"') {
      if (inQuotes && i + 1 < line.length && line[i + 1] === '"') {
        current += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === delimiter && !inQuotes) {
      result.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }
  result.push(current.trim());
  return result;
}
