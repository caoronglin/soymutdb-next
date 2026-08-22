import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE_FILES = [
  "src/routes/news/index.tsx",
  "src/components/news-form.tsx",
];
const LEGACY_PACKAGE = ["@ant-design", "pro-components"].join("/");

describe("AntD 6 source contract", () => {
  it("keeps Admin news screens independent of legacy Pro Components", () => {
    for (const sourcePath of SOURCE_FILES) {
      const source = readFileSync(resolve(process.cwd(), sourcePath), "utf8");
      expect(source).not.toContain(LEGACY_PACKAGE);
    }
  });
});
