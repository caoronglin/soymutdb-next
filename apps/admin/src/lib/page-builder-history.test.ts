import { describe, expect, it } from "vitest";
import type { PageDefinitionV2 } from "@soymutdb/shared";
import {
  emptyHistory,
  pushHistory,
  redoHistory,
  undoHistory,
} from "./page-builder-history";

function definition(theme: PageDefinitionV2["theme_id"]): PageDefinitionV2 {
  return {
    schema_version: 2,
    root: { type: "divider", props: {} },
    data_sources: [],
    theme_id: theme,
    layouts: { desktop: {}, tablet: {}, mobile: {} },
  };
}

describe("Page Builder history", () => {
  it("undoes and redoes bounded draft snapshots", () => {
    const v1 = definition("scientific-light");
    const v2 = definition("scientific-dark");
    const v3 = definition("compact-data");

    let history = pushHistory(emptyHistory(), v1, v2);
    history = pushHistory(history, v2, v3);
    expect(history.past).toEqual([v1, v2]);
    expect(history.future).toEqual([]);

    const undone = undoHistory(history, v3);
    expect(undone?.draft).toEqual(v2);
    expect(undone?.history.future).toEqual([v3]);

    const redone = redoHistory(undone!.history, v2);
    expect(redone?.draft).toEqual(v3);
    expect(redone?.history.future).toEqual([]);
  });

  it("does not push identical snapshots", () => {
    const value = definition("print");
    const history = pushHistory(emptyHistory(), value, value);
    expect(history.past).toEqual([]);
  });
});
