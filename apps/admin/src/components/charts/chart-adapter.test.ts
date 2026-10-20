import { describe, expect, it } from "vitest";

import {
  IMPORT_SERIES_COLORS,
  LATENCY_SERIES_COLORS,
  readDocumentThemeMode,
  toSeriesRows,
  toTrendRows,
} from "./chart-adapter";

interface ThroughputRow {
  date: string;
  imported: number;
  failed: number;
}

describe("toSeriesRows", () => {
  it("emits one row per date per series, in series order", () => {
    const data: ThroughputRow[] = [
      { date: "2026-01-01", imported: 10, failed: 1 },
      { date: "2026-01-02", imported: 20, failed: 2 },
    ];

    const rows = toSeriesRows(data, [
      { name: "Imported", pick: (datum) => datum.imported },
      { name: "Failed", pick: (datum) => datum.failed },
    ]);

    expect(rows).toEqual([
      { date: "2026-01-01", series: "Imported", value: 10 },
      { date: "2026-01-01", series: "Failed", value: 1 },
      { date: "2026-01-02", series: "Imported", value: 20 },
      { date: "2026-01-02", series: "Failed", value: 2 },
    ]);
  });

  it("keeps the series order the color scale depends on", () => {
    const rows = toSeriesRows([{ date: "d", imported: 1, failed: 2 }], [
      { name: "Failed", pick: (datum) => datum.failed },
      { name: "Imported", pick: (datum) => datum.imported },
    ]);

    expect(rows.map((row) => row.series)).toEqual(["Failed", "Imported"]);
  });

  it("drops non-finite measures instead of handing NaN to the engine", () => {
    const rows = toSeriesRows(
      [
        { date: "2026-01-01", imported: Number.NaN, failed: 3 },
        { date: "2026-01-02", imported: Number.POSITIVE_INFINITY, failed: 4 },
      ],
      [
        { name: "Imported", pick: (datum) => datum.imported },
        { name: "Failed", pick: (datum) => datum.failed },
      ],
    );

    expect(rows).toEqual([
      { date: "2026-01-01", series: "Failed", value: 3 },
      { date: "2026-01-02", series: "Failed", value: 4 },
    ]);
  });

  it("returns no rows for no data", () => {
    expect(toSeriesRows([], [{ name: "Imported", pick: () => 1 }])).toEqual([]);
  });
});

describe("toTrendRows", () => {
  it("keeps the date and the single value per row", () => {
    expect(toTrendRows([{ date: "2026-01-01", bytes: 1024 }], (datum) => datum.bytes)).toEqual([
      { date: "2026-01-01", value: 1024 },
    ]);
  });
});

describe("readDocumentThemeMode", () => {
  it("reads data-theme off the document element", () => {
    const root = document.documentElement;
    const previous = root.getAttribute("data-theme");
    try {
      root.setAttribute("data-theme", "light");
      expect(readDocumentThemeMode()).toBe("light");
      root.setAttribute("data-theme", "dark");
      expect(readDocumentThemeMode()).toBe("dark");
      root.removeAttribute("data-theme");
      expect(readDocumentThemeMode()).toBe("light");
    } finally {
      if (previous === null) root.removeAttribute("data-theme");
      else root.setAttribute("data-theme", previous);
    }
  });
});

describe("series colors", () => {
  it("keeps the colors the ECharts charts drew", () => {
    expect(IMPORT_SERIES_COLORS).toEqual(["#2f7d32", "#c0392b"]);
    expect(LATENCY_SERIES_COLORS).toEqual(["#2f7d32", "#e6a817", "#c0392b"]);
  });
});

