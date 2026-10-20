import { describe, expect, it } from "vitest";
import { summarizeImportPage } from "./import-task-stats";

describe("import page statistics", () => {
  it("keeps the filtered total separate from visible status counts", () => {
    expect(summarizeImportPage([
      { status: "running" }, { status: "queued" }, { status: "failed" },
      { status: "completed" }, { status: "cancelled" }, { status: "unknown" },
    ], 200)).toEqual({ total: 200, running: 2, failed: 1, completed: 1 });
  });

  it("does not invent counts for tasks on another page", () => {
    expect(summarizeImportPage([], 100)).toEqual({
      total: 100, running: 0, failed: 0, completed: 0,
    });
  });
});
