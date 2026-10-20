import { describe, expect, it, vi } from "vitest";

import {
  buildImportSubmission,
  createImportIdempotencyKey,
  describeImportIntent,
  fileExtensionOf,
  isSupportedModuleFilename,
  parseDataSetId,
  parseModuleReleaseId,
  resolveIdempotencyKey,
  validateModuleImport,
} from "./import-submission";

describe("parseDataSetId / parseModuleReleaseId", () => {
  it("accepts positive integers and keeps the established messages", () => {
    expect(parseDataSetId(" 12 ")).toBe(12);
    for (const bad of ["", "0", "-1", "1.5", "abc", undefined]) {
      expect(() => parseDataSetId(bad)).toThrow(
        "A positive data set ID is required to submit an import.",
      );
    }
    expect(() => parseModuleReleaseId("0")).toThrow(
      "A positive release ID is required for module data imports.",
    );
  });

  it("rejects values beyond the safe integer range instead of rounding them", () => {
    expect(() => parseDataSetId("9007199254740993")).toThrow(/positive data set ID/);
  });
});

describe("createImportIdempotencyKey", () => {
  it("never returns an empty key", () => {
    expect(createImportIdempotencyKey()).toMatch(/^import-.+/);
    expect(createImportIdempotencyKey()).not.toBe(createImportIdempotencyKey());
  });
});

describe("module filename acceptance", () => {
  it("mirrors the backend module format list", () => {
    for (const name of ["genes.tsv", "genes.TXT", "a.csv", "b.xlsx"]) {
      expect(isSupportedModuleFilename(name)).toBe(true);
    }
    for (const name of ["genes.vcf", "genes.gz", "genes", "genes."]) {
      expect(isSupportedModuleFilename(name)).toBe(false);
    }
    expect(fileExtensionOf("Genes.TSV")).toBe(".tsv");
    expect(fileExtensionOf("noext")).toBe("");
  });
});

describe("validateModuleImport", () => {
  it("reports the same first blocker, in the same order, as the form", () => {
    expect(
      validateModuleImport({ filename: "genes.vcf", moduleKey: "genes", sourceMode: "local" }),
    ).toBe("Module data files must use one of .tsv / .txt / .csv / .xlsx.");
    expect(
      validateModuleImport({ filename: "genes.tsv", moduleKey: "  ", sourceMode: "local" }),
    ).toBe("Module key is required for module data imports.");
    expect(
      validateModuleImport({ filename: "genes.tsv", moduleKey: "genes", sourceMode: "s3" }),
    ).toBe("Checksum is required for module data imports.");
  });

  it("accepts a complete local draft without a checksum and a complete S3 draft with one", () => {
    expect(
      validateModuleImport({ filename: "genes.tsv", moduleKey: "genes", sourceMode: "local" }),
    ).toBeNull();
    expect(
      validateModuleImport({
        filename: "genes.tsv",
        moduleKey: "genes",
        sourceMode: "s3",
        checksum: "abc",
      }),
    ).toBeNull();
  });
});

describe("describeImportIntent", () => {
  it("ignores whitespace noise but distinguishes every submitted field", () => {
    const base = { filename: "genes.tsv", type: "module_tsv", dataSetId: 1 };
    expect(describeImportIntent({ ...base, moduleKey: "genes" })).toBe(
      describeImportIntent({ ...base, moduleKey: "  genes  " }),
    );
    const intent = describeImportIntent({ ...base, moduleKey: "genes" });
    expect(describeImportIntent({ ...base, moduleKey: "variants" })).not.toBe(intent);
    expect(describeImportIntent({ ...base, moduleKey: "genes", dataSetId: 2 })).not.toBe(intent);
    expect(describeImportIntent({ ...base, moduleKey: "genes", releaseId: "9" })).not.toBe(intent);
    expect(describeImportIntent({ ...base, moduleKey: "genes", objectKey: "data/1/x" })).not.toBe(intent);
    expect(describeImportIntent({ ...base, moduleKey: "genes", checksum: "deadbeef" })).not.toBe(intent);
  });

  it("collapses an empty optional field with an absent one, like the built payload does", () => {
    // buildImportSubmission omits falsy optional fields, so an empty object key
    // and no object key at all are the same request and must share a key.
    expect(
      describeImportIntent({ filename: "a.tsv", type: "module_tsv", dataSetId: 1, objectKey: "" }),
    ).toBe(describeImportIntent({ filename: "a.tsv", type: "module_tsv", dataSetId: 1 }));
  });
});

describe("resolveIdempotencyKey", () => {
  it("mints a key for the first submission of a session", () => {
    const createKey = vi.fn(() => "key-2");
    expect(
      resolveIdempotencyKey({ currentKey: "", currentIntent: null, nextIntent: "A", createKey }),
    ).toBe("key-2");
    expect(createKey).toHaveBeenCalledTimes(1);
  });

  it("reuses the key while the intent is unchanged so a retry de-duplicates", () => {
    const createKey = vi.fn(() => "key-2");
    expect(
      resolveIdempotencyKey({ currentKey: "key-1", currentIntent: "A", nextIntent: "A", createKey }),
    ).toBe("key-1");
    expect(createKey).not.toHaveBeenCalled();
  });

  it("rotates the key when the payload changes after a failure", () => {
    // Regression: the API keeps the key under a unique constraint and answers a
    // repeat with the task it already created. Holding the key after the
    // operator edited the file made the new content disappear without an error.
    const createKey = vi.fn(() => "key-2");
    expect(
      resolveIdempotencyKey({ currentKey: "key-1", currentIntent: "A", nextIntent: "B", createKey }),
    ).toBe("key-2");
  });

  it("never reuses a whitespace-only key", () => {
    const createKey = vi.fn(() => "key-2");
    expect(
      resolveIdempotencyKey({ currentKey: "   ", currentIntent: "A", nextIntent: "A", createKey }),
    ).toBe("key-2");
  });
});

describe("buildImportSubmission", () => {
  it("keeps the backend field names and omits absent optional fields", () => {
    expect(
      buildImportSubmission({
        filename: "genes.tsv",
        type: "module_tsv",
        objectKey: "data/1/genes.tsv",
        moduleKey: "genes",
        checksum: "abc",
        dataSetIdInput: "1",
        releaseIdInput: "4",
        idempotencyKey: "key-1",
      }),
    ).toEqual({
      filename: "genes.tsv",
      type: "module_tsv",
      object_key: "data/1/genes.tsv",
      module_key: "genes",
      checksum: "abc",
      data_set_id: 1,
      idempotency_key: "key-1",
      release_id: 4,
    });
  });

  it("requires a release only for module_tsv and a non-empty key always", () => {
    expect(() =>
      buildImportSubmission({
        filename: "a.vcf",
        type: "vcf",
        filePath: "s3://bucket/a.vcf",
        dataSetIdInput: "1",
        idempotencyKey: "key-1",
      }),
    ).not.toThrow();
    expect(() =>
      buildImportSubmission({
        filename: "a.vcf",
        type: "vcf",
        filePath: "s3://bucket/a.vcf",
        dataSetIdInput: "1",
        idempotencyKey: "   ",
      }),
    ).toThrow("An idempotency key is required to submit an import.");
  });
});
