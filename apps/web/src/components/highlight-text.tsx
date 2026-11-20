/**
 * Highlight the query inside a result string.
 *
 * A search result that repeats the reader's term back without marking it makes
 * them re-scan every cell to find the hit. This marks it, and does so by
 * splitting the string, never by building HTML: `dangerouslySetInnerHTML` on a
 * user-supplied query is an injection sink, and the gene name is user-supplied
 * data too.
 *
 * Deliberate limits:
 *
 * - only the literal query is marked, matched case-insensitively; a regex or
 *   fuzzy match would highlight ranges the server did not actually match;
 * - a query shorter than two characters is not highlighted, because a single
 *   letter matches nearly every cell and turns the table into noise;
 * - the matched slice keeps its original casing in the output.
 */
import * as React from "react";

/** Shortest query worth marking; one character matches almost every cell. */
const MIN_HIGHLIGHT_LENGTH = 2;

export interface HighlightTextProps {
  text: string;
  /** The reader's query, used verbatim (no regex interpretation). */
  query?: string;
  className?: string;
}

/** Ranges of `text` that equal `query`, case-insensitively. */
export function highlightRanges(text: string, query: string): [number, number][] {
  const needle = query.trim();
  if (needle.length < MIN_HIGHLIGHT_LENGTH || !text) return [];

  const ranges: [number, number][] = [];
  const haystack = text.toLowerCase();
  const lowered = needle.toLowerCase();
  let from = 0;
  for (;;) {
    const at = haystack.indexOf(lowered, from);
    if (at === -1) break;
    ranges.push([at, at + needle.length]);
    // Advance by one so overlapping occurrences are each marked, and a
    // zero-width loop is impossible because the needle is non-empty.
    from = at + 1;
  }
  return ranges;
}

export function HighlightText({ text, query, className }: HighlightTextProps) {
  const ranges = React.useMemo(
    () => (query ? highlightRanges(text, query) : []),
    [text, query],
  );

  if (ranges.length === 0) {
    return <span className={className}>{text}</span>;
  }

  const parts: React.ReactNode[] = [];
  let cursor = 0;
  ranges.forEach(([start, end], index) => {
    if (start > cursor) parts.push(text.slice(cursor, start));
    parts.push(
      <mark key={`${start}-${index}`} className="bg-transparent font-semibold text-foreground">
        {text.slice(start, end)}
      </mark>,
    );
    cursor = end;
  });
  if (cursor < text.length) parts.push(text.slice(cursor));

  return <span className={className}>{parts}</span>;
}
