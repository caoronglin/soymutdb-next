import { describe, expect, it } from "vitest";
import {
  AVAILABLE_SUBMISSION_IMPORT_TYPES,
  DEFAULT_SUBMISSION_IMPORT_TYPE,
} from "./imports";

describe("import submission availability", () => {
  it("offers only the durable module TSV writer for new submissions", () => {
    expect(AVAILABLE_SUBMISSION_IMPORT_TYPES).toEqual(["module_tsv"]);
    expect(DEFAULT_SUBMISSION_IMPORT_TYPE).toBe("module_tsv");
  });
});
