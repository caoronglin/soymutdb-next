/**
 * Query marking: what gets highlighted, and what must not.
 *
 * The rules exist because a careless highlighter makes results worse: marking a
 * single letter paints every row, and interpreting the query as a regex either
 * throws on "(" or highlights text the server never matched.
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { HighlightText, highlightRanges } from "./highlight-text";

describe("highlightRanges", () => {
  it("marks the query case-insensitively", () => {
    expect(highlightRanges("Glyma.01G000100", "glyma")).toEqual([[0, 5]]);
  });

  it("marks every occurrence, including overlapping ones", () => {
    expect(highlightRanges("AAAA", "AA")).toEqual([
      [0, 2],
      [1, 3],
      [2, 4],
    ]);
  });

  it("ignores a one-character query", () => {
    // A single letter matches almost every cell and turns the list into noise.
    expect(highlightRanges("Glyma.01G000100", "G")).toEqual([]);
  });

  it("treats the query literally, never as a regex", () => {
    // "b)" is a literal substring of "a(b)c" at index 2, and it is marked as
    // such. A regex engine would instead treat the ")" as an unbalanced group
    // and either throw or match something else.
    expect(highlightRanges("a(b)c", "b)")).toEqual([[2, 4]]);
    expect(highlightRanges("a(b)c", "(b)")).toEqual([[1, 4]]);
    // A pattern that only means something to a regex matches no literal text.
    expect(highlightRanges("abc", "a.c")).toEqual([]);
  });

  it("returns nothing for an empty query or empty text", () => {
    expect(highlightRanges("anything", "   ")).toEqual([]);
    expect(highlightRanges("", "abc")).toEqual([]);
  });
});

describe("HighlightText", () => {
  it("renders the query inside a mark and keeps the original casing", () => {
    const { container } = render(<HighlightText text="Glyma.01G000100" query="glyma" />);

    const mark = container.querySelector("mark");
    expect(mark?.textContent).toBe("Glyma");
    expect(container.textContent).toBe("Glyma.01G000100");
  });

  it("renders plain text when nothing matches", () => {
    const { container } = render(<HighlightText text="Glyma.01G000100" query="zzz" />);

    expect(container.querySelector("mark")).toBeNull();
    expect(container.textContent).toBe("Glyma.01G000100");
  });

  it("never injects markup from the query", () => {
    const { container } = render(<HighlightText text="safe text" query="<img src=x>" />);

    // The query is data: it may be marked as text, but it cannot become an
    // element, and the surrounding text is unchanged.
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toBe("safe text");
  });
});
