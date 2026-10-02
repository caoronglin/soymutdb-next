/**
 * CSV/TSV viewer — antd's native `Table`.
 *
 * Parses with a simple split; max 100 rows shown to avoid browser strain. The
 * bounded body height and the header that stays put while scrolling are the
 * table's own `scroll` behaviour now, rather than a hand-rolled sticky <th>.
 */
import { useMemo } from "react";
import { Table, type TableColumnsType } from "@/lib/antd";

interface CsvViewerProps {
  content: string;
  delimiter?: string;
}

const MAX_ROWS = 100;
/** Body height in px, matching the previous `max-h-96` container. */
const BODY_HEIGHT = 384;

type CsvRow = Record<string, string>;

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

  // CSV headers can repeat or be empty, so columns are addressed by position
  // instead of by the header text.
  const columns: TableColumnsType<CsvRow> = useMemo(
    () =>
      headers.map((header, index) => ({
        title: header,
        dataIndex: `c${index}`,
        key: `c${index}`,
        render: (value: string) => <span className="font-mono">{value}</span>,
      })),
    [headers],
  );

  const dataSource: CsvRow[] = useMemo(
    () =>
      rows.map((cells, index) => {
        const record: CsvRow = { key: String(index) };
        headers.forEach((_, h) => {
          record[`c${h}`] = cells[h] ?? "";
        });
        return record;
      }),
    [rows, headers],
  );

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
      <Table<CsvRow>
        rowKey="key"
        size="small"
        bordered
        columns={columns}
        dataSource={dataSource}
        pagination={false}
        scroll={{ x: "max-content", y: BODY_HEIGHT }}
      />
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
